"""Сравнение прогонов: что изменилось на входе и что от этого изменилось на выходе.

Это основной инструмент оценки правки. Отдельно считается диф ВХОДА
(состав промпта, параметры, версии файлов) и диф ВЫХОДА (текст ответа,
проверки, стоимость). Если вход не менялся, а выход изменился — расхождение
объясняется недетерминированностью модели, и это тоже видно явно.
"""

from __future__ import annotations

import difflib


def similarity(a: str, b: str) -> float:
    """Доля совпадения текстов, 0..1."""
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()


def unified(a: str, b: str, label_a: str = "База", label_b: str = "Новый", context: int = 2) -> str:
    diff = difflib.unified_diff(
        (a or "").splitlines(),
        (b or "").splitlines(),
        fromfile=label_a,
        tofile=label_b,
        lineterm="",
        n=context,
    )
    return "\n".join(diff)


def word_diff(a: str, b: str) -> list[dict]:
    """Пословный диф для подсветки в интерфейсе."""
    a_words = (a or "").split()
    b_words = (b or "").split()
    matcher = difflib.SequenceMatcher(None, a_words, b_words)
    result: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            result.append({"op": "equal", "text": " ".join(b_words[j1:j2])})
        elif tag == "delete":
            result.append({"op": "delete", "text": " ".join(a_words[i1:i2])})
        elif tag == "insert":
            result.append({"op": "insert", "text": " ".join(b_words[j1:j2])})
        else:
            result.append({"op": "delete", "text": " ".join(a_words[i1:i2])})
            result.append({"op": "insert", "text": " ".join(b_words[j1:j2])})
    return result


def compare_composition(blocks_a: list[dict], blocks_b: list[dict]) -> dict:
    """Пофайловое сравнение состава промпта по sha."""
    map_a = {block["source"]: block for block in blocks_a}
    map_b = {block["source"]: block for block in blocks_b}

    added = [src for src in map_b if src not in map_a]
    removed = [src for src in map_a if src not in map_b]
    changed = [
        {
            "source": src,
            "sha_before": map_a[src].get("sha256"),
            "sha_after": map_b[src].get("sha256"),
            "tokens_before": map_a[src].get("tokens"),
            "tokens_after": map_b[src].get("tokens"),
        }
        for src in map_a
        if src in map_b and map_a[src].get("sha256") != map_b[src].get("sha256")
    ]
    return {"added": added, "removed": removed, "changed": changed}


def compare_params(request_a: dict, request_b: dict) -> list[dict]:
    keys = sorted(set(request_a) | set(request_b))
    changes = []
    for key in keys:
        if key == "messages":
            continue
        before, after = request_a.get(key), request_b.get(key)
        if before != after:
            changes.append({"param": key, "before": before, "after": after})
    return changes


def compare_runs(run_a: dict, run_b: dict) -> dict:
    """Полное сравнение двух прогонов: вход, выход, метрики."""
    prompt_a, prompt_b = run_a.get("prompt", {}), run_b.get("prompt", {})
    response_a, response_b = run_a.get("response", {}), run_b.get("response", {})
    usage_a = response_a.get("usage") or {}
    usage_b = response_b.get("usage") or {}

    system_changed = prompt_a.get("system_sha256") != prompt_b.get("system_sha256")
    params = compare_params(
        run_a.get("request_body_redacted", {}), run_b.get("request_body_redacted", {})
    )
    question_changed = (
        (run_a.get("input", {}).get("user_message") or "").strip()
        != (run_b.get("input", {}).get("user_message") or "").strip()
    )

    text_a, text_b = response_a.get("text", ""), response_b.get("text", "")
    checks_a = run_a.get("checks_summary") or {}
    checks_b = run_b.get("checks_summary") or {}

    input_identical = not system_changed and not params and not question_changed

    return {
        "input": {
            "identical": input_identical,
            "system_prompt_changed": system_changed,
            "question_changed": question_changed,
            "composition": compare_composition(prompt_a.get("blocks", []), prompt_b.get("blocks", [])),
            "params": params,
            "system_prompt_diff": unified(
                prompt_a.get("system_prompt", ""),
                prompt_b.get("system_prompt", ""),
                "промпт (база)",
                "промпт (новый)",
            )[:20000],
            "tokens_before": prompt_a.get("system_tokens"),
            "tokens_after": prompt_b.get("system_tokens"),
        },
        "output": {
            "similarity": round(similarity(text_a, text_b), 4),
            "identical": text_a == text_b,
            "diff": unified(text_a, text_b, "ответ (база)", "ответ (новый)", context=3)[:40000],
            "word_diff": word_diff(text_a, text_b)[:4000],
            "len_before": len(text_a),
            "len_after": len(text_b),
        },
        "metrics": {
            "checks_failed_before": checks_a.get("failed"),
            "checks_failed_after": checks_b.get("failed"),
            "checks_passed_before": checks_a.get("passed"),
            "checks_passed_after": checks_b.get("passed"),
            "judge_before": (run_a.get("judge") or {}).get("score"),
            "judge_after": (run_b.get("judge") or {}).get("score"),
            "rating_before": (run_a.get("rating") or {}).get("score"),
            "rating_after": (run_b.get("rating") or {}).get("score"),
            "prompt_tokens_before": usage_a.get("prompt_tokens"),
            "prompt_tokens_after": usage_b.get("prompt_tokens"),
            "completion_tokens_before": usage_a.get("completion_tokens"),
            "completion_tokens_after": usage_b.get("completion_tokens"),
            "cost_before": (run_a.get("cost") or {}).get("total"),
            "cost_after": (run_b.get("cost") or {}).get("total"),
            "latency_before": response_a.get("latency_ms"),
            "latency_after": response_b.get("latency_ms"),
        },
        "verdict": _verdict(input_identical, text_a == text_b, checks_a, checks_b),
    }


def _verdict(input_identical: bool, output_identical: bool, checks_a: dict, checks_b: dict) -> str:
    if input_identical and output_identical:
        return "Вход и выход совпали полностью."
    if input_identical and not output_identical:
        return (
            "Вход идентичен, выход разошёлся — это недетерминированность модели, "
            "а не эффект правки. Для оценки правки нужен повтор или прогон набора тестов."
        )
    failed_before = checks_a.get("failed")
    failed_after = checks_b.get("failed")
    if isinstance(failed_before, int) and isinstance(failed_after, int):
        if failed_after < failed_before:
            return f"Вход изменён. Автопроверок провалено: было {failed_before}, стало {failed_after} — улучшение."
        if failed_after > failed_before:
            return f"Вход изменён. Автопроверок провалено: было {failed_before}, стало {failed_after} — регрессия."
    return "Вход изменён, выход отличается. Автопроверки не дали разницы — оценивать по тексту."
