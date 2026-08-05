"""Журнал прогонов — ядро песочницы.

Единица логирования — не сообщение чата, а ПРОГОН (run): полный отпечаток
входа, ответ, автопроверки, стоимость и связь с базовой линией. Такой лог
отвечает на главный вопрос тестирования: «что именно я изменил и что от этого
поменялось в результате».

Что пишется на каждый прогон:
  * отпечаток входа — sha системного промпта, sha каждого файла, его mtime,
    вклад в токенах; параметры вызова; версия репозитория (ветка, коммит, грязь);
  * точное тело запроса, ушедшее в API (без ключа);
  * ответ целиком + usage, finish_reason, задержки (TTFB и общая), стоимость,
    какая модель реально ответила, system_fingerprint;
  * результаты автопроверок и замечания разметки;
  * список отклонений от чистого вызова API — пустой список означает, что
    прогон эквивалентен прямому обращению к модели.

Формат: JSONL-индекс для быстрых выборок + полный JSON на прогон + читаемый MD.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .config import REPO_ROOT, RUNS_DIR, LOGS_DIR, ensure_dirs

_INDEX_PATH = LOGS_DIR / "runs.jsonl"
_LOCK = threading.Lock()


def new_run_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def git_state(watched_files: list[str] | None = None) -> dict:
    """Версия репозитория на момент прогона.

    `dirty_watched` важнее общей грязи: если изменён именно тот файл, который
    вложен в промпт, коммит-хеш перестаёт описывать вход, и сравнение прогонов
    по коммиту вводит в заблуждение.
    """
    status = _git("status", "--porcelain")
    dirty_files = [line[3:].strip() for line in status.splitlines() if line.strip()]
    watched = watched_files or []
    return {
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": _git("rev-parse", "--short", "HEAD"),
        "dirty": bool(dirty_files),
        "dirty_files_count": len(dirty_files),
        "dirty_watched": sorted({f for f in dirty_files if any(f == w or f.endswith(w) for w in watched)}),
    }


def _index_entry(record: dict) -> dict:
    """Компактная строка индекса — по ней строятся списки, фильтры и тренды."""
    prompt = record.get("prompt", {})
    response = record.get("response", {})
    usage = response.get("usage") or {}
    checks = record.get("checks_summary") or {}
    return {
        "id": record["id"],
        "ts": record["ts"],
        "profile": record.get("profile", {}).get("id", ""),
        "profile_name": record.get("profile", {}).get("name", ""),
        "profile_sha": record.get("profile", {}).get("source_sha", ""),
        "model": record.get("request", {}).get("model", ""),
        "model_returned": response.get("model_returned", ""),
        "system_sha": (prompt.get("system_sha256") or "")[:12],
        "system_tokens": prompt.get("system_tokens", 0),
        "question": (record.get("input", {}).get("user_message") or "")[:160],
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cost": (record.get("cost") or {}).get("total"),
        "latency_ms": response.get("latency_ms"),
        "checks_ok": checks.get("ok"),
        "checks_failed": checks.get("failed"),
        "judge_score": (record.get("judge") or {}).get("score"),
        "annotations_count": len(record.get("annotations") or []),
        "annotation_categories": sorted(
            {item.get("category") for item in (record.get("annotations") or []) if item.get("category")}
        ),
        "deviations": len(prompt.get("deviations") or []),
        "clean": not (prompt.get("deviations") or []),
        "mock": record.get("mock", False),
        "error": bool(response.get("error")),
        "suite": record.get("suite", ""),
        "suite_label": record.get("suite_label", ""),
        "git_commit": record.get("git", {}).get("commit", ""),
    }


def _run_paths(run_id: str) -> tuple[Path, Path]:
    day = run_id[:8]
    folder = RUNS_DIR / f"{day[:4]}-{day[4:6]}-{day[6:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{run_id}.json", folder / f"{run_id}.md"


def save_run(record: dict) -> dict:
    """Сохраняет прогон: полный JSON, читаемый MD и строку в индексе."""
    ensure_dirs()
    json_path, md_path = _run_paths(record["id"])
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(record), encoding="utf-8")

    entry = _index_entry(record)
    with _LOCK:
        with _INDEX_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load_run(run_id: str) -> dict | None:
    json_path, _ = _run_paths(run_id)
    if json_path.exists():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    for path in RUNS_DIR.rglob(f"{run_id}.json"):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def update_run(run_id: str, patch: dict) -> dict | None:
    """Дописывает в прогон оценку/заметку и синхронизирует индекс."""
    record = load_run(run_id)
    if record is None:
        return None
    record.update(patch)
    json_path, md_path = _run_paths(run_id)
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(record), encoding="utf-8")

    with _LOCK:
        if _INDEX_PATH.exists():
            lines = _INDEX_PATH.read_text(encoding="utf-8").splitlines()
            updated = []
            for line in lines:
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("id") == run_id:
                    entry = _index_entry(record)
                updated.append(json.dumps(entry, ensure_ascii=False))
            _INDEX_PATH.write_text("\n".join(updated) + "\n", encoding="utf-8")
    return record


def list_runs(limit: int = 200, profile: str = "", suite: str = "", only_errors: bool = False) -> list[dict]:
    if not _INDEX_PATH.exists():
        return []
    entries: list[dict] = []
    for line in _INDEX_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if profile and entry.get("profile") != profile:
            continue
        if suite and entry.get("suite") != suite:
            continue
        if only_errors and not entry.get("error"):
            continue
        entries.append(entry)
    entries.reverse()  # свежие сверху
    return entries[:limit]


def find_previous_similar(run_id: str, profile: str, question: str) -> dict | None:
    """Ищет предыдущий прогон того же вопроса — кандидат в базовую линию.

    Именно эта пара (тот же вопрос, другой промпт) и отвечает на вопрос
    «что изменилось от моей правки».
    """
    normalized = (question or "").strip()[:160]
    for entry in list_runs(limit=500):
        if entry["id"] == run_id:
            continue
        if entry.get("question", "").strip() != normalized:
            continue
        if profile and entry.get("profile") != profile:
            continue
        return entry
    return None


def render_markdown(record: dict) -> str:
    """Читаемый отчёт по прогону — открывается в любом редакторе."""
    prompt = record.get("prompt", {})
    request = record.get("request", {})
    response = record.get("response", {})
    usage = response.get("usage") or {}
    cost = record.get("cost") or {}
    checks = record.get("checks") or []
    summary = record.get("checks_summary") or {}
    deviations = prompt.get("deviations") or []

    lines: list[str] = []
    lines.append(f"# Прогон {record['id']}")
    lines.append("")
    lines.append(f"- **Время:** {record.get('ts')}")
    lines.append(f"- **Профиль:** {record.get('profile', {}).get('name')} (`{record.get('profile', {}).get('id')}`, sha `{record.get('profile', {}).get('source_sha')}`)")
    lines.append(f"- **Модель запрошена / ответила:** `{request.get('model')}` / `{response.get('model_returned')}`")
    lines.append(f"- **Отпечаток системного промпта:** `{(prompt.get('system_sha256') or '')[:16]}`")
    git = record.get("git", {})
    lines.append(f"- **Репозиторий:** {git.get('branch')} @ {git.get('commit')}" + (" — **есть незакоммиченные изменения**" if git.get("dirty") else ""))
    if git.get("dirty_watched"):
        lines.append(f"  - ⚠️ изменены файлы, участвующие в промпте: {', '.join(git['dirty_watched'])}")
    if record.get("mock"):
        lines.append("- **MOCK-прогон** (без обращения к API)")
    lines.append("")

    lines.append("## Чистота теста")
    if not deviations:
        lines.append("Отклонений нет — запрос эквивалентен прямому вызову API.")
    else:
        lines.append("Песочница добавила к чистому вызову следующее:")
        for dev in deviations:
            mark = {"high": "🔴", "warn": "🟡", "info": "⚪"}.get(dev.get("severity"), "⚪")
            lines.append(f"- {mark} `{dev.get('code')}` — {dev.get('detail')}")
    lines.append("")

    lines.append("## Состав системного промпта")
    lines.append("")
    lines.append("| Источник | Тип | Символов | Токенов (оценка) | Доля | sha |")
    lines.append("|---|---|---:|---:|---:|---|")
    total_tokens = max(1, prompt.get("system_tokens") or 1)
    for block in prompt.get("blocks", []):
        share = 100.0 * (block.get("tokens") or 0) / total_tokens
        flag = " ⚠️ НЕ ПРОЧИТАН" if block.get("missing") else (" ✂️ обрезан" if block.get("truncated") else "")
        lines.append(
            f"| `{block.get('source')}`{flag} | {block.get('kind')} | {block.get('chars')} | "
            f"{block.get('tokens')} | {share:.1f}% | `{block.get('sha256')}` |"
        )
    lines.append(f"| **ИТОГО** | | | **{prompt.get('system_tokens')}** | 100% | |")
    lines.append("")

    lines.append("## Параметры вызова")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(record.get("request_body_redacted", {}), ensure_ascii=False, indent=2))
    lines.append("```")
    if response.get("adaptations"):
        lines.append("")
        lines.append("**Клиент изменил параметры:**")
        for adaptation in response["adaptations"]:
            lines.append(f"- `{adaptation.get('code')}` {adaptation.get('param')}: {adaptation.get('reason')}")
    lines.append("")

    lines.append("## Результат")
    lines.append("")
    if response.get("error"):
        lines.append(f"**ОШИБКА:** {response['error']}")
    lines.append(
        f"- Токены: prompt={usage.get('prompt_tokens')}, completion={usage.get('completion_tokens')}, "
        f"total={usage.get('total_tokens')}"
    )
    details = usage.get("completion_tokens_details") or {}
    if details.get("reasoning_tokens"):
        lines.append(f"- Из них reasoning: {details['reasoning_tokens']}")
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    if cached:
        lines.append(f"- Из промпта закешировано: {cached}")
    lines.append(f"- Задержка: TTFB {response.get('ttfb_ms')} мс, всего {response.get('latency_ms')} мс")
    if cost.get("known"):
        lines.append(f"- Стоимость: ${cost.get('total')} (in ${cost.get('input')} + cached ${cost.get('cached_input')} + out ${cost.get('output')})")
    else:
        lines.append("- Стоимость: цена модели не задана в pricing.json")
    lines.append(f"- finish_reason: `{response.get('finish_reason')}`, попыток: {response.get('attempts')}")
    lines.append("")

    if checks:
        lines.append("## Автопроверки")
        lines.append("")
        lines.append(f"Пройдено {summary.get('passed')}/{summary.get('total')}, провалено {summary.get('failed')}, предупреждений {summary.get('warnings')}.")
        lines.append("")
        for check in checks:
            mark = "✅" if check.get("passed") else ("⚠️" if check.get("severity") == "warn" else "❌")
            arg = f" `{check.get('arg')}`" if check.get("arg") else ""
            detail = f" — {check.get('detail')}" if check.get("detail") else ""
            lines.append(f"- {mark} {check.get('kind')}{arg}{detail}")
        lines.append("")

    judge = record.get("judge")
    if judge:
        lines.append("## Оценка модели-судьи")
        lines.append("")
        lines.append(f"- Балл: **{judge.get('score')}/5** — {judge.get('verdict')}")
        for issue in judge.get("issues") or []:
            lines.append(f"  - ❗ {issue}")
        for strength in judge.get("strengths") or []:
            lines.append(f"  - ➕ {strength}")
        lines.append("")

    lines.append("## Вопрос")
    lines.append("")
    lines.append("```")
    lines.append(record.get("input", {}).get("user_message", ""))
    lines.append("```")
    lines.append("")
    lines.append("## Ответ")
    lines.append("")
    lines.append(response.get("text", ""))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("<details><summary>Полный системный промпт</summary>")
    lines.append("")
    lines.append("```")
    lines.append(prompt.get("system_prompt", ""))
    lines.append("```")
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines)


def redact_body(body: dict) -> dict:
    """Тело запроса для лога: длинные тексты сообщений заменяются описанием.

    Полный системный промпт хранится отдельно в prompt.system_prompt —
    дублировать его в теле запроса незачем.
    """
    clone = {k: v for k, v in body.items() if k != "messages"}
    clone["messages"] = [
        {
            "role": message.get("role"),
            "chars": len(message.get("content") or ""),
            "preview": (message.get("content") or "")[:200],
        }
        for message in body.get("messages", [])
    ]
    return clone
