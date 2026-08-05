"""Подсчёт токенов.

Точные цифры приходят от API в поле usage. До запроса нужна оценка —
чтобы видеть вклад каждого файла в системный промпт и ловить переполнение
контекста ДО того, как потрачены деньги.

Если в окружении есть tiktoken — используется он. Если нет (обычная ситуация
на рабочем ноутбуке без прав на pip install) — работает эвристика, откалиброванная
по фактическим ответам API: после каждого реального запроса песочница сравнивает
оценку с usage.prompt_tokens и подтягивает коэффициент.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from .config import LOGS_DIR

try:  # опционально, песочница работает и без него
    import tiktoken  # type: ignore

    _HAS_TIKTOKEN = True
except Exception:  # pragma: no cover - зависит от окружения
    tiktoken = None  # type: ignore
    _HAS_TIKTOKEN = False

_CALIBRATION_PATH = LOGS_DIR / "calibration.json"
_LOCK = threading.Lock()

_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_LATIN = re.compile(r"[A-Za-z]")

# Базовые делители «символов на токен».
# Кириллица токенизируется плотнее латиницы — отсюда разные коэффициенты.
# 3.14 — не теория, а замер: индикатор контекста Langdock показал 5,7 тыс.
# токенов на файле инструкций в 10 068 символов (за вычетом их служебного
# текста) и 38,7 тыс. на 121 тыс. символов базы знаний.
_CHARS_PER_TOKEN_CYR = 3.14
_CHARS_PER_TOKEN_LAT = 4.0
_CHARS_PER_TOKEN_OTHER = 3.0


def _load_calibration() -> dict:
    if _CALIBRATION_PATH.exists():
        try:
            return json.loads(_CALIBRATION_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_calibration(data: dict) -> None:
    _CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CALIBRATION_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _encoding_for(model: str):
    if not _HAS_TIKTOKEN:
        return None
    try:
        return tiktoken.encoding_for_model(model)
    except Exception:
        try:
            return tiktoken.get_encoding("o200k_base")
        except Exception:
            return None


def estimate_tokens(text: str, model: str = "") -> int:
    """Оценка числа токенов. Точность ~±10% на русских текстах."""
    if not text:
        return 0

    enc = _encoding_for(model)
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass

    cyr = len(_CYRILLIC.findall(text))
    lat = len(_LATIN.findall(text))
    other = max(0, len(text) - cyr - lat)
    raw = cyr / _CHARS_PER_TOKEN_CYR + lat / _CHARS_PER_TOKEN_LAT + other / _CHARS_PER_TOKEN_OTHER

    factor = _load_calibration().get(_calib_key(model), {}).get("factor", 1.0)
    return max(1, int(round(raw * factor)))


def estimation_method(model: str = "") -> str:
    if _encoding_for(model) is not None:
        return "tiktoken (точно)"
    factor = _load_calibration().get(_calib_key(model), {}).get("factor")
    if factor:
        return f"эвристика, откалибровано по API (k={factor:.3f})"
    return "эвристика (без калибровки)"


def _calib_key(model: str) -> str:
    return model or "default"


def record_actual(model: str, estimated: int, actual: int) -> None:
    """Подтягивает коэффициент оценки по фактическому usage из ответа API.

    Экспоненциальное сглаживание: свежие наблюдения весят больше, но один
    выброс не ломает калибровку.
    """
    if estimated <= 0 or actual <= 0:
        return
    with _LOCK:
        data = _load_calibration()
        key = _calib_key(model)
        entry = data.get(key, {"factor": 1.0, "samples": 0})
        # Оценка уже включала прежний factor — восстанавливаем «сырую» оценку.
        raw = estimated / max(entry.get("factor", 1.0), 1e-6)
        observed = actual / max(raw, 1e-6)
        alpha = 0.3 if entry.get("samples", 0) else 1.0
        entry["factor"] = round((1 - alpha) * entry.get("factor", 1.0) + alpha * observed, 4)
        entry["samples"] = entry.get("samples", 0) + 1
        entry["last_actual"] = actual
        entry["last_estimated"] = estimated
        data[key] = entry
        _save_calibration(data)


def count_messages(messages: list[dict], model: str = "") -> int:
    """Оценка токенов на весь список сообщений (+~4 токена служебных на сообщение)."""
    total = 0
    for message in messages:
        content = message.get("content") or ""
        if isinstance(content, list):  # мультимодальный формат
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        total += estimate_tokens(content, model) + 4
    return total + 3
