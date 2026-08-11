"""Разметка ответов — главный источник данных о качестве.

Рабочий цикл агента состоит из трёх элементов: он формулирует клинический
случай, выдаёт разбор и выдаёт эталон. Оценивать это одним баллом бессмысленно —
ошибка живёт в конкретной фразе. Поэтому основная единица оценки здесь —
ЗАМЕЧАНИЕ К ФРАГМЕНТУ: выделенная цитата + часть ответа + категория ошибки +
комментарий.

Замечания пишутся в двух видах:
  * внутрь записи прогона — чтобы фрагмент был привязан к своему входу;
  * в общий поток logs/annotations.jsonl — плоский файл, по которому Claude Code
    разбирает накопленное за недели: какие категории ошибок повторяются, в какой
    части ответа, при каком промпте.

Плюс сводка logs/ANNOTATIONS.md — та же информация, сгруппированная для чтения.
"""

from __future__ import annotations

import json
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .config import LOGS_DIR, REPO_ROOT, SANDBOX_DIR, ensure_dirs
from .runlog import load_run, update_run

_STREAM_PATH = LOGS_DIR / "annotations.jsonl"
_DIGEST_PATH = LOGS_DIR / "ANNOTATIONS.md"
_CATEGORIES_PATH = SANDBOX_DIR / "annotation-categories.json"
_LOCK = threading.Lock()

# Части ответа агента. Порядок — как в реальном рабочем цикле.
DEFAULT_PARTS = [
    {"id": "case", "label": "Клинический случай"},
    {"id": "analysis", "label": "Разбор"},
    {"id": "reference", "label": "Эталон"},
    {"id": "other", "label": "Другое"},
]


def load_categories() -> dict:
    """Категории ошибок и части ответа. Правятся руками под себя."""
    if _CATEGORIES_PATH.exists():
        try:
            data = json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8"))
            return {
                "parts": data.get("parts") or DEFAULT_PARTS,
                "categories": data.get("categories") or [],
                "severities": data.get("severities") or [],
                "section_patterns": data.get("section_patterns") or {},
            }
        except Exception:
            pass
    return {"parts": DEFAULT_PARTS, "categories": [], "severities": [], "section_patterns": {}}


def save_annotations(run_id: str, annotations: list[dict]) -> dict | None:
    """Записывает полный список замечаний к прогону (замена, не добавление)."""
    ensure_dirs()
    record = load_run(run_id)
    if record is None:
        return None

    stamped = []
    for index, annotation in enumerate(annotations):
        item = {
            "n": index + 1,
            "part": annotation.get("part") or "other",
            "category": annotation.get("category") or "",
            "severity": annotation.get("severity") or "major",
            "quote": annotation.get("quote") or "",
            "start": annotation.get("start"),
            "end": annotation.get("end"),
            "comment": annotation.get("comment") or "",
            "created_at": annotation.get("created_at")
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        # Доказательная база собирается здесь, а не при чтении лога:
        # состояние входа со временем меняется, факты должны быть зафиксированы.
        item["evidence"] = build_evidence(record, item)
        stamped.append(item)

    updated = update_run(
        run_id,
        {
            "annotations": stamped,
            "annotations_summary": summarize(stamped),
        },
    )
    _rewrite_stream(run_id, updated, stamped)
    write_digest()
    return updated


_STOPWORDS = {
    "который", "которая", "которые", "этого", "этому", "этом", "быть", "было", "были",
    "если", "чтобы", "также", "более", "менее", "может", "можно", "нужно", "после",
    "перед", "через", "между", "всех", "всего", "того", "тому", "как", "при", "для",
    "что", "или", "его", "она", "они", "оно", "так", "уже", "еще", "ещё", "the", "and",
    "for", "with", "this", "that", "from", "have", "has",
}

# Значимые для медицинского текста токены: слова от 4 букв, дозы и числа с запятой.
_TERM_RE = __import__("re").compile(r"[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z-]{3,}|\d+[,.]?\d*")


def _extract_terms(quote: str, limit: int = 25) -> list[str]:
    seen: list[str] = []
    for match in _TERM_RE.findall(quote or ""):
        token = match.strip("-").lower()
        if not token or token in _STOPWORDS or token in seen:
            continue
        seen.append(token)
        if len(seen) >= limit:
            break
    return seen


def build_evidence(record: dict, annotation: dict) -> dict:
    """Собирает факты о входе, относящиеся к размеченному фрагменту.

    Это именно ФАКТЫ, а не версия причины: было ли упоминание в промпте, какие
    файлы участвовали, не обрезан ли ответ, какие параметры генерации стояли.
    Вывод о причине делает человек (или Claude Code при разборе), опираясь на них.
    """
    prompt = record.get("prompt") or {}
    response = record.get("response") or {}
    request = record.get("request") or {}
    usage = response.get("usage") or {}
    system_prompt = (prompt.get("system_prompt") or "").lower()
    answer = response.get("text") or ""

    # 1. Термины из цитаты — есть ли они в системном промпте вообще.
    terms = _extract_terms(annotation.get("quote") or "")
    coverage = []
    for term in terms:
        count = system_prompt.count(term)
        coverage.append({"term": term, "in_prompt": count > 0, "hits": count})
    missing = [item["term"] for item in coverage if not item["in_prompt"]]

    # 1б. Если работала база знаний — развести три разные причины.
    retrieval_diagnosis = _diagnose_retrieval(record, terms)

    # 2. Позиция фрагмента в ответе: хвостовые ошибки часто связаны с обрывом.
    start = annotation.get("start")
    position = None
    if isinstance(start, int) and answer:
        position = round(100.0 * start / max(1, len(answer)), 1)

    # 3. Признак обрыва по лимиту токенов — типичная причина «пропущено важное».
    truncated = response.get("finish_reason") == "length"

    # 4. Что вообще лежало в промпте.
    files = [
        {
            "source": block.get("source"),
            "kind": block.get("kind"),
            "tokens": block.get("tokens"),
            "sha256": block.get("sha256"),
            "missing": block.get("missing", False),
        }
        for block in prompt.get("blocks") or []
    ]

    # 5. Уверенность модели именно на этом фрагменте — окно в процесс генерации.
    confidence = span_confidence(response, annotation.get("start"), annotation.get("end"))

    notes: list[str] = []
    if confidence.get("available"):
        mean_probability = confidence["mean_probability"]
        if mean_probability < 0.55:
            notes.append(
                f"На этом фрагменте модель была не уверена: средняя вероятность токена "
                f"{mean_probability:.2f} против {confidence['answer_mean_probability']:.2f} по ответу целиком."
            )
        elif mean_probability > 0.9:
            notes.append(
                f"Фрагмент выдан уверенно (средняя вероятность {mean_probability:.2f}). "
                "Уверенная ошибка правится промптом или контекстом, а не температурой."
            )
    if truncated:
        notes.append(
            "Ответ оборван по лимиту токенов (finish_reason=length) — неполнота может объясняться этим, а не промптом."
        )

    if retrieval_diagnosis:
        # При работающей базе знаний это главный вывод: причины лечатся
        # по-разному, и путать их нельзя.
        if retrieval_diagnosis["absent_from_base"]:
            notes.append(
                "В базе знаний вообще нет: "
                + ", ".join(retrieval_diagnosis["absent_from_base"][:8])
                + ". Это пробел базы — модель взяла это не из ваших файлов."
            )
        if retrieval_diagnosis.get("near_cut_uncertain"):
            notes.append(
                "У границы обрезки, доехало или нет — точно неизвестно: "
                + ", ".join(retrieval_diagnosis["near_cut_uncertain"][:8])
                + ". Потолок платформы установлен лишь как коридор 21–28 тыс. символов, "
                "и эти слова лежат внутри него. Утверждать причину по ним нельзя."
            )
        if retrieval_diagnosis.get("cut_by_preview_limit"):
            notes.append(
                "Есть в файле, но НЕ доехало до модели из-за обрезки предпросмотра: "
                + ", ".join(retrieval_diagnosis["cut_by_preview_limit"][:8])
                + ". Модель физически не видела этот кусок — правка промпта тут бесполезна, "
                "надо поднимать нужное выше по файлу или дробить файл."
            )
        if retrieval_diagnosis["in_base_not_retrieved"]:
            notes.append(
                "Есть в базе, но поиск это не поднял: "
                + ", ".join(retrieval_diagnosis["in_base_not_retrieved"][:8])
                + ". Промах поиска, а не промпта: модель нужного фрагмента не видела."
            )
        if retrieval_diagnosis["in_retrieved"]:
            notes.append(
                "Было в поданных фрагментах: "
                + ", ".join(retrieval_diagnosis["in_retrieved"][:8])
                + ". Материал модель получила и всё равно ответила так — причина в промпте или в самой модели."
            )
    elif missing:
        notes.append(
            "Терминов из цитаты нет в системном промпте: " + ", ".join(missing[:10])
            + ". Модель писала это не из предоставленного контекста."
        )
    if any(block.get("missing") for block in prompt.get("blocks") or []):
        notes.append("Часть заявленных файлов не была прочитана — контекст ушёл неполным.")
    if request.get("seed") is None:
        notes.append("Seed не задан — точный повтор прогона невозможен, часть расхождений объясняется случайностью.")
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    if reasoning:
        notes.append(f"Модель потратила {reasoning} токенов на рассуждение — оно в ответ не попадает и в логе не видно.")

    return {
        "system_sha": (prompt.get("system_sha256") or "")[:12],
        "profile": (record.get("profile") or {}).get("id"),
        "profile_sha": (record.get("profile") or {}).get("source_sha"),
        "model": request.get("model"),
        "model_returned": response.get("model_returned"),
        "params": {
            "temperature": request.get("temperature"),
            "top_p": request.get("top_p"),
            "seed": request.get("seed"),
            "max_tokens": request.get("max_tokens"),
            "reasoning_effort": request.get("reasoning_effort"),
        },
        "finish_reason": response.get("finish_reason"),
        "truncated_by_limit": truncated,
        "history_turns": (record.get("input") or {}).get("history_len", 0),
        "files_in_prompt": files,
        "deviations": prompt.get("deviations") or [],
        "term_coverage": coverage,
        "terms_missing_from_prompt": missing,
        "position_percent": position,
        "answer_chars": len(answer),
        "confidence": confidence,
        "retrieval": retrieval_diagnosis,
        "facts": notes,
    }


def _diagnose_retrieval(record: dict, terms: list[str]) -> dict | None:
    """Разводит причины: пробел базы, обрыв предпросмотра, промах поиска, ошибка на
    полном контексте. Отдельно — слова у границы обрыва, где вывод недостоверен.

    Работает по сохранённому в прогоне отчёту о поиске, а не по текущему
    состоянию файлов: база могла с тех пор измениться, и тогда разбор
    прошлого замечания по свежим файлам врал бы.
    """
    retrieval = record.get("retrieval")
    if not retrieval or not terms:
        return None

    from . import knowledge as knowledge_mod

    # Режим предпросмотра: сравниваем с тем, что РЕАЛЬНО доехало после обрезки,
    # и отдельно с полным файлом. Разница между ними — самая коварная причина:
    # в файле написано, а модель этого куска не видела.
    if retrieval.get("mode") == "preview":
        delivered = ""
        full = ""
        for item in retrieval.get("full_text_files", []):
            try:
                text = (REPO_ROOT / item["source"]).read_text(encoding="utf-8")
            except Exception:
                continue
            full += " " + text.lower()
            delivered += " " + text[: item.get("chars") or len(text)].lower()

        # Точный потолок обрезки у платформы не установлен: по позициям
        # увиденного он лежит между 21 и 28 тыс. символов. Поэтому термины
        # из этой зоны нельзя объявлять «не доехавшими» — только «на границе».
        UNCERTAIN_TO = 28000
        доехало, обрезано, на_границе, нет_в_базе = [], [], [], []
        for term in terms:
            lowered = term.lower()
            if lowered in delivered:
                доехало.append(term)
            elif lowered in full:
                позиция = full.find(lowered)
                (на_границе if позиция < UNCERTAIN_TO else обрезано).append(term)
            else:
                нет_в_базе.append(term)
        return {
            "in_retrieved": доехало,
            "in_base_not_retrieved": [],
            "cut_by_preview_limit": обрезано,
            "near_cut_uncertain": на_границе,
            "absent_from_base": нет_в_базе,
            "mode": "preview",
            "truncated_files": [
                f["source"] for f in retrieval.get("full_text_files", []) if f.get("truncated")
            ],
        }

    retrieved = retrieval.get("retrieved") or []
    retrieved_text = " ".join(item.get("text") or "" for item in retrieved).lower()

    # Полный текст базы берём с диска: в прогоне его нет, а знать, есть ли
    # термин в базе вообще, необходимо.
    chunks: list = []
    searched = [f["source"] for f in retrieval.get("searched_files", []) if not f.get("missing")]
    if searched:
        try:
            chunks, _ = knowledge_mod.build_index(
                searched, chunk_chars=retrieval.get("chunk_chars", 1200)
            )
        except Exception:
            chunks = []

    base_text = " ".join(chunk.text for chunk in chunks).lower()
    for item in retrieval.get("full_text_files", []):
        try:
            base_text += " " + (REPO_ROOT / item["source"]).read_text(encoding="utf-8").lower()
        except Exception:
            pass

    in_retrieved, in_base_only, absent = [], [], []
    for term in terms:
        lowered = term.lower()
        if lowered in retrieved_text:
            in_retrieved.append(term)
        elif base_text and lowered in base_text:
            in_base_only.append(term)
        else:
            absent.append(term)

    return {
        "in_retrieved": in_retrieved,
        "in_base_not_retrieved": in_base_only,
        "absent_from_base": absent,
        "chunks_used": retrieval.get("chunks_used"),
        "chunks_total": retrieval.get("chunks_total"),
        "method": retrieval.get("method"),
    }


def span_confidence(response: dict, start, end) -> dict:
    """Пословная уверенность модели на выделенном фрагменте.

    Единственное, что API показывает о самом процессе генерации: вероятность
    каждого выданного токена. Токены сопоставляются с символьными границами
    выделения накопительной длиной — тот же порядок, в каком они пришли.
    Если модель не отдала logprobs, честно возвращается available=False.
    """
    tokens = response.get("tokens") or []
    logprobs = response.get("logprobs") or []
    if not tokens or not logprobs or len(tokens) != len(logprobs):
        return {"available": False, "reason": "модель не вернула logprobs для этого прогона"}

    import math

    probabilities = [math.exp(value) for value in logprobs]
    answer_mean = sum(probabilities) / len(probabilities)

    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        return {
            "available": True,
            "span": False,
            "answer_mean_probability": round(answer_mean, 4),
            "mean_probability": round(answer_mean, 4),
        }

    span_indexes: list[int] = []
    cursor = 0
    for index, token in enumerate(tokens):
        token_start = cursor
        cursor += len(token)
        if token_start < end and cursor > start:
            span_indexes.append(index)

    if not span_indexes:
        return {
            "available": True,
            "span": False,
            "answer_mean_probability": round(answer_mean, 4),
            "mean_probability": round(answer_mean, 4),
            "reason": "не удалось сопоставить выделение с токенами",
        }

    span_probabilities = [probabilities[index] for index in span_indexes]
    weakest = sorted(span_indexes, key=lambda index: probabilities[index])[:5]

    return {
        "available": True,
        "span": True,
        "tokens_in_span": len(span_indexes),
        "mean_probability": round(sum(span_probabilities) / len(span_probabilities), 4),
        "min_probability": round(min(span_probabilities), 4),
        "low_confidence_tokens": len([p for p in span_probabilities if p < 0.5]),
        "answer_mean_probability": round(answer_mean, 4),
        "weakest_tokens": [
            {"token": tokens[index], "probability": round(probabilities[index], 4)} for index in weakest
        ],
    }


def summarize(annotations: list[dict]) -> dict:
    by_part = Counter(item.get("part") or "other" for item in annotations)
    by_category = Counter(item.get("category") or "—" for item in annotations)
    by_severity = Counter(item.get("severity") or "major" for item in annotations)
    return {
        "total": len(annotations),
        "by_part": dict(by_part),
        "by_category": dict(by_category),
        "by_severity": dict(by_severity),
        "blocking": by_severity.get("blocker", 0) + by_severity.get("major", 0),
    }


def _rewrite_stream(run_id: str, record: dict | None, annotations: list[dict]) -> None:
    """Обновляет плоский поток: строки этого прогона заменяются целиком."""
    with _LOCK:
        existing: list[dict] = []
        if _STREAM_PATH.exists():
            for line in _STREAM_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("run_id") != run_id:
                    existing.append(entry)

        record = record or {}
        profile = record.get("profile", {})
        for annotation in annotations:
            existing.append(
                {
                    **annotation,
                    "run_id": run_id,
                    "run_ts": record.get("ts"),
                    "profile": profile.get("id"),
                    "profile_name": profile.get("name"),
                    "profile_sha": profile.get("source_sha"),
                    "model": (record.get("request") or {}).get("model"),
                    "system_sha": (record.get("prompt") or {}).get("system_sha256", "")[:12],
                    "git_commit": (record.get("git") or {}).get("commit"),
                    "question": (record.get("input") or {}).get("user_message", "")[:200],
                }
            )

        existing.sort(key=lambda item: (item.get("run_ts") or "", item.get("n") or 0))
        _STREAM_PATH.write_text(
            "\n".join(json.dumps(entry, ensure_ascii=False) for entry in existing) + "\n",
            encoding="utf-8",
        )


def load_stream() -> list[dict]:
    if not _STREAM_PATH.exists():
        return []
    entries = []
    for line in _STREAM_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def aggregate() -> dict:
    """Срез по всем замечаниям — что повторяется чаще всего."""
    entries = load_stream()
    categories = {item["id"]: item["label"] for item in load_categories().get("categories", [])}
    parts = {item["id"]: item["label"] for item in load_categories().get("parts", [])}

    by_category = Counter(entry.get("category") or "—" for entry in entries)
    by_part = Counter(entry.get("part") or "other" for entry in entries)
    by_profile = Counter(entry.get("profile") or "—" for entry in entries)
    by_severity = Counter(entry.get("severity") or "major" for entry in entries)

    cross = defaultdict(Counter)
    for entry in entries:
        cross[entry.get("part") or "other"][entry.get("category") or "—"] += 1

    runs = {entry.get("run_id") for entry in entries}

    return {
        "total": len(entries),
        "runs_annotated": len(runs),
        "by_category": [
            {"id": key, "label": categories.get(key, key), "count": value}
            for key, value in by_category.most_common()
        ],
        "by_part": [
            {"id": key, "label": parts.get(key, key), "count": value}
            for key, value in by_part.most_common()
        ],
        "by_profile": [{"id": key, "count": value} for key, value in by_profile.most_common()],
        "by_severity": [{"id": key, "count": value} for key, value in by_severity.most_common()],
        "cross": {
            part: [{"id": key, "label": categories.get(key, key), "count": value} for key, value in counter.most_common()]
            for part, counter in cross.items()
        },
        "entries": sorted(entries, key=lambda item: item.get("run_ts") or "", reverse=True)[:500],
        "digest_path": str(_DIGEST_PATH),
        "stream_path": str(_STREAM_PATH),
    }


def write_digest() -> Path:
    """Сводка для чтения и для разбора Claude Code."""
    data = aggregate()
    entries = data["entries"]
    categories = {item["id"]: item["label"] for item in load_categories().get("categories", [])}
    parts = {item["id"]: item["label"] for item in load_categories().get("parts", [])}

    lines: list[str] = []
    lines.append("# Сводка замечаний к ответам агента")
    lines.append("")
    lines.append(f"> Собрано автоматически песочницей. Замечаний: **{data['total']}**, размеченных прогонов: **{data['runs_annotated']}**.")
    lines.append("> Машинный источник — `logs/annotations.jsonl` (одна строка на замечание).")
    lines.append("")

    if not entries:
        lines.append("Замечаний пока нет.")
        _DIGEST_PATH.write_text("\n".join(lines), encoding="utf-8")
        return _DIGEST_PATH

    lines.append("## Что повторяется чаще всего")
    lines.append("")
    lines.append("| Категория ошибки | Замечаний |")
    lines.append("|---|---:|")
    for item in data["by_category"]:
        lines.append(f"| {item['label']} | {item['count']} |")
    lines.append("")

    lines.append("## Распределение по частям ответа")
    lines.append("")
    lines.append("| Часть | Замечаний |")
    lines.append("|---|---:|")
    for item in data["by_part"]:
        lines.append(f"| {item['label']} | {item['count']} |")
    lines.append("")

    lines.append("## Часть × категория")
    lines.append("")
    for part_id, rows in data["cross"].items():
        lines.append(f"**{parts.get(part_id, part_id)}**")
        lines.append("")
        for row in rows:
            lines.append(f"- {row['label']} — {row['count']}")
        lines.append("")

    lines.append("## Замечания по прогонам")
    lines.append("")
    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        grouped[entry.get("run_id") or "—"].append(entry)

    for run_id, items in grouped.items():
        head = items[0]
        lines.append(f"### Прогон `{run_id}` — {head.get('run_ts')}")
        lines.append("")
        lines.append(f"- Профиль: {head.get('profile_name')} (`{head.get('profile')}`, sha `{head.get('profile_sha')}`)")
        lines.append(f"- Модель: `{head.get('model')}`, промпт sha `{head.get('system_sha')}`, коммит `{head.get('git_commit')}`")
        lines.append(f"- Вопрос: {head.get('question')}")
        lines.append("")
        for item in sorted(items, key=lambda value: value.get("n") or 0):
            label = categories.get(item.get("category"), item.get("category") or "без категории")
            part_label = parts.get(item.get("part"), item.get("part") or "—")
            lines.append(f"**{item.get('n')}. [{part_label}] {label}** — важность: {item.get('severity')}")
            lines.append("")
            quote = (item.get("quote") or "").strip()
            for quote_line in quote.splitlines() or [""]:
                lines.append(f"> {quote_line}")
            lines.append("")
            lines.append(f"{item.get('comment')}")
            lines.append("")
        lines.append("---")
        lines.append("")

    _DIGEST_PATH.write_text("\n".join(lines), encoding="utf-8")
    return _DIGEST_PATH
