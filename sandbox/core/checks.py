"""Автоматические проверки ответа — дешёвый сигнал до чтения текста.

Проверяется то, что проверяется детерминированно: запрещённые формулировки
из Блока 2.3 INSTRUCTIONS.md, дисклеймер при упоминании off-label, язык ответа.
Набор правится в sandbox/checks/default.json. Качество по существу оценивает
человек разметкой — эти проверки её не заменяют, а лишь ловят грубое.

Важно: проверки выполняются ПОСЛЕ получения ответа, над готовым текстом.
В запрос к модели они ничего не добавляют — тестируемый вызов остаётся чистым.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict

from .config import CHECKS_DIR

# Признаки того, что ответ на что-то опирается: PMID/DOI, ОХЛП, клинреки.
_SOURCE_PATTERNS = [
    r"PMID\s*:?\s*\d+",
    r"\b10\.\d{4,9}/\S+",  # DOI
    r"ОХЛП",
    r"КР\s+МЗ\s+РФ",
    r"\bESC\b",
    r"\bESH\b",
    r"AHA/ACC",
    r"\bРКО\b",
    r"инструкц\w+ по применению",
]

# Слова-триггеры, после которых ожидается off-label дисклеймер.
_OFF_LABEL_TRIGGERS = [
    r"off-label",
    r"вне\s+показани",
    r"не\s+зарегистрирован\w*\s+показани",
]
_OFF_LABEL_DISCLAIMER = [
    r"off-label",
    r"вне\s+инструкц",
    r"вне\s+зарегистрированн\w+\s+показани",
    r"получены\s+у",
]


@dataclass
class CheckResult:
    kind: str
    arg: str
    passed: bool
    detail: str = ""
    severity: str = "error"  # error | warn

    def to_dict(self) -> dict:
        return asdict(self)


def load_check_set(name: str = "default") -> dict:
    path = CHECKS_DIR / f"{name}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def run_checks(text: str, checks: list[dict], check_set: dict | None = None) -> list[CheckResult]:
    """Прогоняет список проверок над текстом ответа."""
    results: list[CheckResult] = []
    check_set = check_set or {}
    lowered = text.lower()

    for check in checks:
        kind = (check.get("kind") or "").strip().lower()
        arg = str(check.get("arg") or "").strip()
        severity = check.get("severity", "error")

        if kind == "contains":
            passed = arg.lower() in lowered
            results.append(CheckResult(kind, arg, passed, "" if passed else "фрагмент не найден", severity))

        elif kind in ("not_contains", "must_not_contain"):
            passed = arg.lower() not in lowered
            results.append(CheckResult(kind, arg, passed, "" if passed else "найден запрещённый фрагмент", severity))

        elif kind == "contains_any":
            options = [o.strip().lower() for o in arg.split("|") if o.strip()]
            hit = [o for o in options if o in lowered]
            results.append(
                CheckResult(kind, arg, bool(hit), f"совпало: {', '.join(hit)}" if hit else "ни один вариант не найден", severity)
            )

        elif kind == "contains_all":
            options = [o.strip().lower() for o in arg.split("|") if o.strip()]
            missing = [o for o in options if o not in lowered]
            results.append(
                CheckResult(kind, arg, not missing, "" if not missing else f"не найдено: {', '.join(missing)}", severity)
            )

        elif kind == "regex":
            try:
                passed = bool(re.search(arg, text, re.IGNORECASE | re.MULTILINE))
                results.append(CheckResult(kind, arg, passed, "" if passed else "нет совпадения", severity))
            except re.error as exc:
                results.append(CheckResult(kind, arg, False, f"битое регулярное выражение: {exc}", severity))

        elif kind == "not_regex":
            try:
                passed = not re.search(arg, text, re.IGNORECASE | re.MULTILINE)
                results.append(CheckResult(kind, arg, passed, "" if passed else "найдено запрещённое совпадение", severity))
            except re.error as exc:
                results.append(CheckResult(kind, arg, False, f"битое регулярное выражение: {exc}", severity))

        elif kind in ("max_words", "min_words", "max_chars", "min_chars"):
            try:
                limit = int(arg)
            except ValueError:
                results.append(CheckResult(kind, arg, False, "аргумент не число", severity))
                continue
            value = _words(text) if "words" in kind else len(text)
            passed = value <= limit if kind.startswith("max") else value >= limit
            results.append(CheckResult(kind, arg, passed, f"фактически: {value}", severity))

        elif kind in ("cites_source", "must_cite_source"):
            hit = [p for p in _SOURCE_PATTERNS if re.search(p, text, re.IGNORECASE)]
            results.append(
                CheckResult(kind, "", bool(hit), f"найдено: {len(hit)} признак(ов) источника" if hit else "нет ссылок на источники", severity)
            )

        elif kind == "no_forbidden_phrases":
            forbidden = check_set.get("forbidden_phrases", [])
            found = [phrase for phrase in forbidden if phrase.lower() in lowered]
            results.append(
                CheckResult(kind, "", not found, "" if not found else f"найдены: {', '.join(found)}", severity)
            )

        elif kind == "language_ru":
            cyr = len(re.findall(r"[Ѐ-ӿ]", text))
            lat = len(re.findall(r"[A-Za-z]", text))
            passed = cyr > lat
            results.append(CheckResult(kind, "", passed, f"кириллица={cyr}, латиница={lat}", severity))

        elif kind == "off_label_disclaimer":
            triggered = any(re.search(p, text, re.IGNORECASE) for p in _OFF_LABEL_TRIGGERS)
            if not triggered:
                results.append(CheckResult(kind, "", True, "тема off-label не поднималась", "warn"))
            else:
                has = any(re.search(p, text, re.IGNORECASE) for p in _OFF_LABEL_DISCLAIMER)
                results.append(CheckResult(kind, "", has, "" if has else "off-label упомянут без дисклеймера", severity))

        else:
            results.append(CheckResult(kind or "?", arg, False, "неизвестный тип проверки", "warn"))

    return results


def summarize(results: list[CheckResult]) -> dict:
    errors = [r for r in results if not r.passed and r.severity == "error"]
    warns = [r for r in results if not r.passed and r.severity == "warn"]
    return {
        "total": len(results),
        "passed": len([r for r in results if r.passed]),
        "failed": len(errors),
        "warnings": len(warns),
        "ok": not errors,
    }

