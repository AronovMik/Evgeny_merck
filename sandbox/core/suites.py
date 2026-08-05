"""Наборы тестов (регрессы).

Набор — Markdown-файл с фиксированными вопросами и ожиданиями. Прогон набора
даёт метку (label), например `base` до правки и `после-правки-блока-3` после.
Две метки сравниваются пункт за пунктом — это и есть ответ на вопрос
«правка улучшила результат или сломала».

Формат файла (sandbox/suites/*.md):

    ---
    name: Регресс по портфелю Конкор
    profile: repo-rules
    checks: default
    judge_rubric: |
      Точность по ОХЛП; наличие источников; отсутствие off-label без дисклеймера.
    ---

    ## Показания Конкор Кор

    ### Вопрос
    Какие показания зарегистрированы у Конкор Кор?

    ### Проверки
    - contains: ХСН
    - not_contains: артериальная гипертензия
    - cites_source
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .checks import parse_check_line
from .config import REPO_ROOT, SUITES_DIR, SUITE_RESULTS_DIR
from .diffs import similarity
from .profiles import get_profile, parse_frontmatter
from .runlog import load_run
from .runner import run_sync

_SLUG = re.compile(r"[^a-zA-Z0-9а-яА-Я_-]+")


@dataclass
class SuiteItem:
    title: str
    question: str
    checks: list[dict] = field(default_factory=list)


@dataclass
class Suite:
    id: str
    name: str
    path: str
    profile: str = ""
    check_set: str = "default"
    judge_rubric: str = ""
    judge_model: str = ""
    items: list[SuiteItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "profile": self.profile,
            "check_set": self.check_set,
            "judge_rubric": self.judge_rubric,
            "judge_model": self.judge_model,
            "items": [
                {"title": item.title, "question": item.question, "checks": item.checks}
                for item in self.items
            ],
        }


def _parse_items(body: str) -> list[SuiteItem]:
    items: list[SuiteItem] = []
    chunks = re.split(r"^##\s+(?!#)", body, flags=re.MULTILINE)
    for chunk in chunks[1:]:
        lines = chunk.splitlines()
        title = lines[0].strip() if lines else "Без названия"
        rest = "\n".join(lines[1:])

        sections = re.split(r"^###\s+", rest, flags=re.MULTILINE)
        question = sections[0].strip()
        checks: list[dict] = []

        for section in sections[1:]:
            header, _, content = section.partition("\n")
            header_lower = header.strip().lower()
            if header_lower.startswith(("вопрос", "question", "prompt")):
                question = content.strip()
            elif header_lower.startswith(("проверк", "ожидан", "checks", "expect")):
                for line in content.splitlines():
                    if not line.strip():
                        continue
                    parsed = parse_check_line(line)
                    if parsed:
                        checks.append(parsed)

        if question:
            items.append(SuiteItem(title=title, question=question, checks=checks))
    return items


def load_suite(path: Path) -> Suite:
    raw = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    return Suite(
        id=path.stem,
        name=str(meta.get("name") or path.stem),
        path=str(path.relative_to(REPO_ROOT)),
        profile=str(meta.get("profile") or ""),
        check_set=str(meta.get("checks") or "default"),
        judge_rubric=str(meta.get("judge_rubric") or ""),
        judge_model=str(meta.get("judge_model") or ""),
        items=_parse_items(body),
    )


def list_suites() -> list[Suite]:
    if not SUITES_DIR.exists():
        return []
    suites = []
    for path in sorted(SUITES_DIR.glob("*.md")):
        if path.name.startswith("_") or path.name.upper() == "README.MD":
            continue
        try:
            suites.append(load_suite(path))
        except Exception as exc:
            suites.append(Suite(id=path.stem, name=f"{path.stem} — ОШИБКА: {exc}", path=str(path)))
    return suites


def get_suite(suite_id: str) -> Suite | None:
    path = SUITES_DIR / f"{suite_id}.md"
    return load_suite(path) if path.exists() else None


def safe_label(label: str) -> str:
    cleaned = _SLUG.sub("-", (label or "").strip()).strip("-")
    return cleaned or datetime.now().strftime("%Y%m%d-%H%M%S")


def run_suite(
    suite: Suite,
    *,
    profile_id: str = "",
    label: str = "",
    overrides: dict | None = None,
    use_judge: bool = False,
    workers: int = 3,
    progress=None,
) -> dict:
    """Прогоняет весь набор и сохраняет результат под меткой."""
    profile = get_profile(profile_id or suite.profile)
    if profile is None:
        raise ValueError(f"Профиль не найден: {profile_id or suite.profile}")

    label = safe_label(label)
    rubric = suite.judge_rubric if use_judge else ""
    total = len(suite.items)
    done = [0]

    def run_item(item: SuiteItem) -> dict:
        record = run_sync(
            profile,
            item.question,
            overrides=overrides,
            item_checks=item.checks,
            check_set_name=suite.check_set,
            suite=suite.id,
            suite_label=label,
            item_title=item.title,
            judge_rubric=rubric,
            judge_model=suite.judge_model,
        )
        done[0] += 1
        if progress:
            progress({"done": done[0], "total": total, "title": item.title})
        summary = record.get("checks_summary") or {}
        usage = (record.get("response") or {}).get("usage") or {}
        return {
            "title": item.title,
            "question": item.question,
            "run_id": record["id"],
            "checks_ok": summary.get("ok"),
            "checks_passed": summary.get("passed"),
            "checks_failed": summary.get("failed"),
            "checks_total": summary.get("total"),
            "failed_list": [
                f"{c['kind']}{(': ' + c['arg']) if c.get('arg') else ''}"
                for c in record.get("checks", [])
                if not c.get("passed") and c.get("severity") == "error"
            ],
            "judge_score": (record.get("judge") or {}).get("score"),
            "judge_verdict": (record.get("judge") or {}).get("verdict", ""),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cost": (record.get("cost") or {}).get("total"),
            "latency_ms": (record.get("response") or {}).get("latency_ms"),
            "error": (record.get("response") or {}).get("error", ""),
            "answer_chars": len((record.get("response") or {}).get("text", "")),
        }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(run_item, suite.items))

    first_run = load_run(results[0]["run_id"]) if results else {}
    passed_items = len([r for r in results if r.get("checks_ok")])
    judge_scores = [r["judge_score"] for r in results if isinstance(r.get("judge_score"), (int, float))]
    costs = [r["cost"] for r in results if isinstance(r.get("cost"), (int, float))]

    report = {
        "suite": suite.id,
        "suite_name": suite.name,
        "label": label,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": profile.id,
        "profile_name": profile.name,
        "profile_sha": profile.source_sha,
        "model": (first_run.get("request") or {}).get("model", ""),
        "system_sha": (first_run.get("prompt") or {}).get("system_sha256", "")[:16],
        "system_tokens": (first_run.get("prompt") or {}).get("system_tokens"),
        "git": first_run.get("git", {}),
        "mock": first_run.get("mock", False),
        "deviations": (first_run.get("prompt") or {}).get("deviations", []),
        "overrides": overrides or {},
        "items": results,
        "summary": {
            "items": len(results),
            "items_ok": passed_items,
            "items_failed": len(results) - passed_items,
            "checks_failed_total": sum(r.get("checks_failed") or 0 for r in results),
            "errors": len([r for r in results if r.get("error")]),
            "judge_avg": round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None,
            "cost_total": round(sum(costs), 6) if costs else None,
        },
    }

    folder = SUITE_RESULTS_DIR / suite.id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{label}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def list_suite_results(suite_id: str) -> list[dict]:
    folder = SUITE_RESULTS_DIR / suite_id
    if not folder.exists():
        return []
    results = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        results.append(
            {
                "label": data.get("label"),
                "ts": data.get("ts"),
                "profile": data.get("profile"),
                "model": data.get("model"),
                "system_sha": data.get("system_sha"),
                "summary": data.get("summary"),
                "mock": data.get("mock"),
            }
        )
    results.sort(key=lambda item: item.get("ts") or "", reverse=True)
    return results


def load_suite_result(suite_id: str, label: str) -> dict | None:
    path = SUITE_RESULTS_DIR / suite_id / f"{safe_label(label)}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def compare_suite_results(suite_id: str, label_a: str, label_b: str) -> dict:
    """Сравнение двух прогонов набора — таблица регрессий и улучшений."""
    report_a = load_suite_result(suite_id, label_a)
    report_b = load_suite_result(suite_id, label_b)
    if not report_a or not report_b:
        raise ValueError("Не найден один из прогонов набора")

    items_a = {item["title"]: item for item in report_a["items"]}
    items_b = {item["title"]: item for item in report_b["items"]}

    rows = []
    improved = regressed = unchanged = 0

    for title in items_b:
        item_b = items_b[title]
        item_a = items_a.get(title)
        if not item_a:
            rows.append({"title": title, "status": "новый", "after": item_b})
            continue

        run_a = load_run(item_a["run_id"]) or {}
        run_b = load_run(item_b["run_id"]) or {}
        text_a = (run_a.get("response") or {}).get("text", "")
        text_b = (run_b.get("response") or {}).get("text", "")

        failed_a = item_a.get("checks_failed") or 0
        failed_b = item_b.get("checks_failed") or 0
        if failed_b < failed_a:
            status = "улучшение"
            improved += 1
        elif failed_b > failed_a:
            status = "регрессия"
            regressed += 1
        else:
            status = "без изменений"
            unchanged += 1

        rows.append(
            {
                "title": title,
                "status": status,
                "checks_failed_before": failed_a,
                "checks_failed_after": failed_b,
                "failed_before_list": item_a.get("failed_list", []),
                "failed_after_list": item_b.get("failed_list", []),
                "judge_before": item_a.get("judge_score"),
                "judge_after": item_b.get("judge_score"),
                "similarity": round(similarity(text_a, text_b), 4),
                "len_before": len(text_a),
                "len_after": len(text_b),
                "cost_before": item_a.get("cost"),
                "cost_after": item_b.get("cost"),
                "run_before": item_a["run_id"],
                "run_after": item_b["run_id"],
            }
        )

    removed = [title for title in items_a if title not in items_b]

    return {
        "suite": suite_id,
        "a": {
            "label": report_a["label"],
            "ts": report_a["ts"],
            "profile": report_a["profile"],
            "model": report_a["model"],
            "system_sha": report_a["system_sha"],
            "summary": report_a["summary"],
        },
        "b": {
            "label": report_b["label"],
            "ts": report_b["ts"],
            "profile": report_b["profile"],
            "model": report_b["model"],
            "system_sha": report_b["system_sha"],
            "summary": report_b["summary"],
        },
        "input_changed": report_a.get("system_sha") != report_b.get("system_sha"),
        "rows": rows,
        "removed_items": removed,
        "totals": {"improved": improved, "regressed": regressed, "unchanged": unchanged},
    }
