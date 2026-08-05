"""Стоимость прогонов.

Цены лежат в редактируемом sandbox/pricing.json и НЕ являются источником истины —
их надо сверять с openai.com/pricing. Если модели в таблице нет, стоимость
считается неизвестной (null) и в отчёте показывается как «цена не задана»,
а не как ноль: молчаливый ноль в тестовом логе хуже честного пропуска.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import SANDBOX_DIR

_PRICING_PATH = SANDBOX_DIR / "pricing.json"


def load_pricing() -> dict:
    if not _PRICING_PATH.exists():
        return {}
    try:
        data = json.loads(_PRICING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _match_model(model: str, table: dict) -> dict | None:
    if not model:
        return None
    if model in table:
        return table[model]
    # gpt-5-2026-01-01 -> gpt-5 : ищем самый длинный префикс
    candidates = [key for key in table if model.startswith(key)]
    if candidates:
        return table[max(candidates, key=len)]
    return None


def estimate_cost(model: str, usage: dict | None) -> dict:
    """Возвращает разбивку стоимости в долларах или {'known': False}."""
    table = load_pricing()
    rates = _match_model(model, table)
    if not rates or not usage:
        return {"known": False, "model_matched": None}

    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    fresh_prompt = max(0, prompt_tokens - cached)

    per_million = 1_000_000
    input_rate = float(rates.get("input", 0))
    output_rate = float(rates.get("output", 0))
    cached_rate = float(rates.get("cached_input", input_rate))

    input_cost = fresh_prompt * input_rate / per_million
    cached_cost = cached * cached_rate / per_million
    output_cost = completion_tokens * output_rate / per_million

    return {
        "known": True,
        "model_matched": next((k for k in table if model.startswith(k)), model),
        "currency": "USD",
        "input": round(input_cost, 6),
        "cached_input": round(cached_cost, 6),
        "output": round(output_cost, 6),
        "total": round(input_cost + cached_cost + output_cost, 6),
        "rates": rates,
    }
