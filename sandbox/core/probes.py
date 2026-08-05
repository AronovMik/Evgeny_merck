"""Пробы процесса генерации — попытка установить причину, а не предположить её.

Данные о входе объясняют не всё. Две пробы дают то, чего не видно в одном прогоне:

  * СТАБИЛЬНОСТЬ — тот же запрос повторяется N раз. Если спорный фрагмент
    воспроизводится каждый раз, это систематическое поведение промпта; если
    плавает — модель не знает ответа и достраивает его случайно. Лечится это
    по-разному, поэтому различать важно.

  * АБЛЯЦИЯ — тот же вопрос прогоняется без одного из файлов промпта. Если без
    файла ошибка исчезает, файл и есть причина. Это установление причины
    вмешательством, а не корреляцией по логу.

Обе пробы пишут обычные прогоны в общий журнал (с меткой probe), поэтому
их результат можно перепроверить и сравнить как любой другой прогон.
"""

from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

from .annotations import _extract_terms
from .diffs import similarity
from .profiles import get_profile
from .runlog import load_run
from .runner import run_sync


def _target_terms(record: dict, annotation_index: int | None, custom_terms: list[str] | None) -> tuple[list[str], str]:
    """Что именно ищем в повторных прогонах: термины замечания или свои."""
    if custom_terms:
        return [term.lower() for term in custom_terms if term.strip()], ""
    annotations = record.get("annotations") or []
    if annotation_index is not None and 0 <= annotation_index < len(annotations):
        quote = annotations[annotation_index].get("quote") or ""
        return _extract_terms(quote, limit=12), quote
    return [], ""


def _term_hits(text: str, terms: list[str]) -> dict:
    lowered = (text or "").lower()
    found = [term for term in terms if term in lowered]
    return {
        "found": found,
        "missing": [term for term in terms if term not in lowered],
        "share": round(len(found) / len(terms), 3) if terms else None,
    }


def stability_probe(
    run_id: str,
    *,
    repeats: int = 5,
    annotation_index: int | None = None,
    terms: list[str] | None = None,
    workers: int = 3,
) -> dict:
    """Повторяет прогон N раз и смотрит, воспроизводится ли спорный фрагмент."""
    record = load_run(run_id)
    if record is None:
        raise ValueError(f"Прогон не найден: {run_id}")

    profile_id = (record.get("profile") or {}).get("id", "")
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError(f"Профиль прогона больше не существует: {profile_id}")

    recorded_sha = (record.get("profile") or {}).get("source_sha")
    profile_changed = recorded_sha != profile.source_sha

    request = record.get("request") or {}
    overrides = {
        "model": request.get("model"),
        "temperature": request.get("temperature"),
        "top_p": request.get("top_p"),
        "max_tokens": request.get("max_tokens"),
        "reasoning_effort": request.get("reasoning_effort"),
        "logprobs": request.get("logprobs", False),
        "seed": None,  # seed снимается намеренно: проба меряет разброс
    }
    question = (record.get("input") or {}).get("user_message", "")
    original_text = (record.get("response") or {}).get("text", "")
    target_terms, quote = _target_terms(record, annotation_index, terms)

    def one(index: int) -> dict:
        result = run_sync(
            profile,
            question,
            overrides=overrides,
            check_set_name=record.get("check_set") or "default",
            suite="probe",
            suite_label=f"stability:{run_id}",
            item_title=f"повтор {index + 1}",
        )
        text = (result.get("response") or {}).get("text", "")
        hits = _term_hits(text, target_terms)
        return {
            "run_id": result["id"],
            "similarity_to_original": round(similarity(original_text, text), 4),
            "terms": hits,
            "reproduced": bool(target_terms) and hits["share"] is not None and hits["share"] >= 0.6,
            "checks_failed": (result.get("checks_summary") or {}).get("failed"),
            "chars": len(text),
            "error": (result.get("response") or {}).get("error", ""),
        }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        repeats_result = list(pool.map(one, range(max(1, repeats))))

    reproduced = len([item for item in repeats_result if item["reproduced"]])
    similarities = [item["similarity_to_original"] for item in repeats_result]

    if not target_terms:
        verdict = "Фрагмент для проверки не задан — измерен только разброс формулировок."
    elif reproduced == len(repeats_result):
        verdict = (
            f"Фрагмент воспроизвёлся во всех {reproduced} повторах — это устойчивое поведение "
            "текущего промпта, а не случайность. Править надо промпт или контекст."
        )
    elif reproduced == 0:
        verdict = (
            "Фрагмент не воспроизвёлся ни разу — исходный ответ был случайным отклонением. "
            "Правка промпта по одному наблюдению здесь необоснованна."
        )
    else:
        verdict = (
            f"Фрагмент воспроизвёлся в {reproduced} из {len(repeats_result)} повторов — "
            "модель неустойчива на этом месте. Обычно это признак нехватки опоры в контексте."
        )

    return {
        "kind": "stability",
        "source_run": run_id,
        "profile": profile_id,
        "profile_changed_since_run": profile_changed,
        "question": question,
        "quote": quote,
        "terms": target_terms,
        "repeats": repeats_result,
        "reproduced_count": reproduced,
        "repeats_total": len(repeats_result),
        "similarity_mean": round(sum(similarities) / len(similarities), 4) if similarities else None,
        "similarity_min": round(min(similarities), 4) if similarities else None,
        "verdict": verdict,
    }


def ablation_probe(
    run_id: str,
    *,
    annotation_index: int | None = None,
    terms: list[str] | None = None,
    workers: int = 3,
) -> dict:
    """Прогоняет тот же вопрос без каждого из файлов промпта по очереди."""
    record = load_run(run_id)
    if record is None:
        raise ValueError(f"Прогон не найден: {run_id}")

    profile_id = (record.get("profile") or {}).get("id", "")
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError(f"Профиль прогона больше не существует: {profile_id}")

    files = list(profile.system_files) + list(profile.context_files)
    if not files:
        raise ValueError("В профиле нет подключённых файлов — отключать нечего")

    request = record.get("request") or {}
    overrides = {
        "model": request.get("model"),
        "temperature": request.get("temperature"),
        "top_p": request.get("top_p"),
        "max_tokens": request.get("max_tokens"),
        "logprobs": request.get("logprobs", False),
    }
    question = (record.get("input") or {}).get("user_message", "")
    target_terms, quote = _target_terms(record, annotation_index, terms)

    variants = [{"label": "полный промпт", "drop": None}]
    variants += [{"label": f"без {path}", "drop": path} for path in files]

    def one(variant: dict) -> dict:
        dropped = variant["drop"]
        variant_profile = (
            profile
            if dropped is None
            else replace(
                profile,
                system_files=[path for path in profile.system_files if path != dropped],
                context_files=[path for path in profile.context_files if path != dropped],
            )
        )
        result = run_sync(
            variant_profile,
            question,
            overrides=overrides,
            check_set_name=record.get("check_set") or "default",
            suite="probe",
            suite_label=f"ablation:{run_id}",
            item_title=variant["label"],
        )
        text = (result.get("response") or {}).get("text", "")
        hits = _term_hits(text, target_terms)
        return {
            "label": variant["label"],
            "dropped": dropped,
            "run_id": result["id"],
            "terms": hits,
            "reproduced": bool(target_terms) and hits["share"] is not None and hits["share"] >= 0.6,
            "checks_failed": (result.get("checks_summary") or {}).get("failed"),
            "system_tokens": (result.get("prompt") or {}).get("system_tokens"),
            "chars": len(text),
            "error": (result.get("response") or {}).get("error", ""),
        }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, variants))

    control = next((item for item in results if item["dropped"] is None), None)
    culprits = [
        item["dropped"]
        for item in results
        if item["dropped"] and control and control["reproduced"] and not item["reproduced"]
    ]

    if not target_terms:
        verdict = "Фрагмент для проверки не задан — сравнивать нечего, смотрите тексты прогонов."
    elif control and not control["reproduced"]:
        verdict = (
            "На контрольном прогоне фрагмент не воспроизвёлся — абляция неинформативна. "
            "Сначала проверьте стабильность."
        )
    elif culprits:
        verdict = (
            "Фрагмент исчезает при отключении: " + ", ".join(culprits)
            + ". Это и есть источник — причина установлена вмешательством."
        )
    else:
        verdict = (
            "Фрагмент воспроизводится без любого из файлов — источник не в подключённом контексте, "
            "а в самой модели или в формулировке вопроса."
        )

    return {
        "kind": "ablation",
        "source_run": run_id,
        "profile": profile_id,
        "question": question,
        "quote": quote,
        "terms": target_terms,
        "variants": results,
        "culprits": culprits,
        "verdict": verdict,
    }
