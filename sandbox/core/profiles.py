"""Профили — конфигурации, которые тестируются и сравниваются между собой.

Профиль = обычный Markdown-файл в sandbox/profiles/ с шапкой:

    ---
    name: Правила репозитория
    model: gpt-5
    temperature: 0.3
    system_files:
      - INSTRUCTIONS.md
      - CLAUDE.md
    context_files:
      - context/product-info/PORTFOLIO_CHEATSHEET.md
    ---

    Здесь — дополнительный системный текст (может быть пустым).

Формат выбран Markdown-ом сознательно: промпт правится глазами и в обычном
редакторе, без риска сломать JSON запятой. Парсер шапки максимально снисходителен.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .config import PROFILES_DIR, REPO_ROOT

_SCALAR_TRUE = {"true", "yes", "да", "1", "on"}
_SCALAR_FALSE = {"false", "no", "нет", "0", "off"}


def _coerce(value: str):
    text = value.strip().strip('"').strip("'")
    if text.lower() in _SCALAR_TRUE:
        return True
    if text.lower() in _SCALAR_FALSE:
        return False
    if text == "":
        return ""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Разбирает шапку между --- . Поддерживает скаляры и списки через '- '."""
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text

    meta: dict = {}
    current_key: str | None = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if re.match(r"^\s*-\s+", raw) and current_key:
            item = re.sub(r"^\s*-\s+", "", raw).strip()
            if item:
                meta.setdefault(current_key, [])
                if isinstance(meta[current_key], list):
                    meta[current_key].append(_coerce(item))
            continue
        if ":" in raw:
            key, _, value = raw.partition(":")
            key = key.strip()
            value = value.strip()
            current_key = key
            meta[key] = [] if value == "" else _coerce(value)

    body = "\n".join(lines[end + 1 :]).strip()
    return meta, body


@dataclass
class Profile:
    """Одна конфигурация под тест."""

    id: str
    name: str
    path: str
    model: str = ""
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str = ""
    seed: int | None = None
    system_files: list[str] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)
    # База знаний проекта: подаётся поиском по фрагментам, как в Langdock
    knowledge_files: list[str] = field(default_factory=list)
    knowledge_top_k: int = 50
    knowledge_chunk_chars: int = 1200
    knowledge_full_text_limit: int = 4000
    system_text: str = ""
    checks: str = "default"
    description: str = ""
    logprobs: bool = False  # запрашивать пословную уверенность модели
    order: int = 100  # порядок в списке; меньше — выше
    truncate_chars: int = 0  # 0 = не обрезать вложенные файлы
    source_sha: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _as_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def load_profile(path: Path) -> Profile:
    raw = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)

    temperature = meta.get("temperature")
    top_p = meta.get("top_p")
    max_tokens = meta.get("max_tokens")
    seed = meta.get("seed")

    return Profile(
        id=path.stem,
        name=str(meta.get("name") or path.stem),
        path=str(path.relative_to(REPO_ROOT)),
        model=str(meta.get("model") or ""),
        temperature=float(temperature) if isinstance(temperature, (int, float)) else None,
        top_p=float(top_p) if isinstance(top_p, (int, float)) else None,
        max_tokens=int(max_tokens) if isinstance(max_tokens, (int, float)) else None,
        reasoning_effort=str(meta.get("reasoning_effort") or ""),
        seed=int(seed) if isinstance(seed, (int, float)) else None,
        system_files=_as_list(meta.get("system_files")),
        context_files=_as_list(meta.get("context_files")),
        knowledge_files=_as_list(meta.get("knowledge_files")),
        knowledge_top_k=int(meta.get("knowledge_top_k") or 50),
        knowledge_chunk_chars=int(meta.get("knowledge_chunk_chars") or 1200),
        knowledge_full_text_limit=int(meta.get("knowledge_full_text_limit") or 4000),
        system_text=body,
        checks=str(meta.get("checks") or "default"),
        description=str(meta.get("description") or ""),
        logprobs=bool(meta.get("logprobs") or False),
        order=int(meta.get("order") or 100),
        truncate_chars=int(meta.get("truncate_chars") or 0),
        source_sha=hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12],
    )


def list_profiles() -> list[Profile]:
    if not PROFILES_DIR.exists():
        return []
    profiles = []
    for path in sorted(PROFILES_DIR.glob("*.md")):
        if path.name.startswith("_") or path.name.upper() == "README.MD":
            continue
        try:
            profiles.append(load_profile(path))
        except Exception as exc:  # битый профиль не должен ронять сервер
            profiles.append(
                Profile(
                    id=path.stem,
                    name=f"{path.stem} — ОШИБКА ЧТЕНИЯ: {exc}",
                    path=str(path.relative_to(REPO_ROOT)),
                )
            )
    profiles.sort(key=lambda profile: (profile.order, profile.name))
    return profiles


def get_profile(profile_id: str) -> Profile | None:
    path = PROFILES_DIR / f"{profile_id}.md"
    if not path.exists():
        return None
    return load_profile(path)
