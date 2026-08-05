"""Схожесть текстов — нужна пробам, чтобы измерять разброс между повторами."""

from __future__ import annotations

import difflib


def similarity(a: str, b: str) -> float:
    """Доля совпадения текстов, 0..1."""
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()
