"""Сборка запроса к API.

ГЛАВНЫЙ ПРИНЦИП: песочница не добавляет собственной обвязки.

Тело запроса — это ровно то, что ушло бы при прямом вызове OpenAI API:
system-сообщение + история + сообщение пользователя. Никаких служебных
преамбул, никаких «ты работаешь в тестовой среде», никакой разметки вокруг
текста. Иначе тест меряет обвязку песочницы, а не тестируемый промпт.

Всё, что песочница всё-таки вынуждена добавить (склейка нескольких файлов,
обрезка, заголовки источников), фиксируется в списке `deviations`. Пустой
список = прогон побайтово эквивалентен прямому вызову API. Это ключевая
гарантия валидности теста, поэтому она вычисляется явно, а не подразумевается.

Отдельно: вкладывание файлов знаний ЦЕЛИКОМ не эквивалентно RAG-подходу,
если платформа-оригинал ищет по ним фрагменты. Такой прогон помечается
отклонением `context_files_inlined` — сравнивать его с платформой напрямую нельзя.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import REPO_ROOT
from .profiles import Profile
from .tokens import estimate_tokens

# Как склеивать несколько файлов в один системный промпт.
#   none    — встык через пустую строку (минимальное вмешательство)
#   labeled — с заголовком-путём перед каждым файлом (удобно читать, но это добавка)
WRAPPER_NONE = "none"
WRAPPER_LABELED = "labeled"


@dataclass
class Block:
    """Один кусок системного промпта с полной атрибуцией."""

    kind: str  # profile_text | file | context_file
    source: str  # путь относительно корня репо или "profile"
    chars: int
    tokens: int
    sha256: str
    mtime: str = ""
    truncated: bool = False
    missing: bool = False

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "source": self.source,
            "chars": self.chars,
            "tokens": self.tokens,
            "sha256": self.sha256,
            "mtime": self.mtime,
            "truncated": self.truncated,
            "missing": self.missing,
        }


@dataclass
class Deviation:
    """Любое расхождение с «чистым» прямым вызовом API."""

    code: str
    detail: str
    severity: str = "info"  # info | warn | high

    def to_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail, "severity": self.severity}


@dataclass
class BuiltPrompt:
    system_prompt: str
    blocks: list[Block] = field(default_factory=list)
    deviations: list[Deviation] = field(default_factory=list)
    system_tokens: int = 0
    system_sha256: str = ""

    def to_dict(self) -> dict:
        return {
            "system_prompt": self.system_prompt,
            "system_tokens": self.system_tokens,
            "system_sha256": self.system_sha256,
            "blocks": [b.to_dict() for b in self.blocks],
            "deviations": [d.to_dict() for d in self.deviations],
            "clean": not self.deviations,
        }


def _read_file(rel_path: str) -> tuple[str, Path, bool]:
    path = (REPO_ROOT / rel_path).resolve()
    try:
        path.relative_to(REPO_ROOT)  # защита от выхода за пределы репозитория
    except ValueError:
        return "", path, True
    if not path.exists() or not path.is_file():
        return "", path, True
    if path.suffix.lower() == ".pdf":
        # PDF намеренно не парсится: любой парсер — это обвязка, которой нет
        # в тестируемой платформе. Нужен текст — положить рядом .md.
        return "", path, True
    try:
        return path.read_text(encoding="utf-8"), path, False
    except Exception:
        return "", path, True


def _mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return ""


def build_system_prompt(
    profile: Profile,
    *,
    wrapper: str = WRAPPER_NONE,
    override_system_text: str | None = None,
) -> BuiltPrompt:
    """Собирает системный промпт и полную атрибуцию его состава."""
    blocks: list[Block] = []
    deviations: list[Deviation] = []
    parts: list[str] = []

    system_text = profile.system_text if override_system_text is None else override_system_text
    if override_system_text is not None and override_system_text != profile.system_text:
        deviations.append(
            Deviation(
                "system_text_overridden",
                "Системный текст изменён в интерфейсе и отличается от файла профиля",
                "info",
            )
        )

    files_used = 0

    # 1. Файлы правил (то, что в платформе лежит в поле «инструкции» ассистента).
    for rel in profile.system_files:
        text, path, missing = _read_file(rel)
        if missing:
            blocks.append(Block("file", rel, 0, 0, "", "", missing=True))
            deviations.append(Deviation("file_missing", f"Файл не прочитан: {rel}", "high"))
            continue
        truncated = False
        if profile.truncate_chars and len(text) > profile.truncate_chars:
            text = text[: profile.truncate_chars]
            truncated = True
            deviations.append(
                Deviation("truncation", f"Файл обрезан до {profile.truncate_chars} симв.: {rel}", "high")
            )
        blocks.append(
            Block(
                "file",
                rel,
                len(text),
                estimate_tokens(text, profile.model),
                hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                _mtime(path),
                truncated=truncated,
            )
        )
        parts.append(f"# {rel}\n\n{text}" if wrapper == WRAPPER_LABELED else text)
        files_used += 1

    # 2. Собственный текст профиля.
    if system_text.strip():
        blocks.append(
            Block(
                "profile_text",
                f"{profile.path} (тело)",
                len(system_text),
                estimate_tokens(system_text, profile.model),
                hashlib.sha256(system_text.encode("utf-8")).hexdigest()[:16],
            )
        )
        parts.append(system_text.strip())

    # 3. Справочные документы. Целиком в промпт — это НЕ то же самое, что RAG.
    for rel in profile.context_files:
        text, path, missing = _read_file(rel)
        if missing:
            blocks.append(Block("context_file", rel, 0, 0, "", "", missing=True))
            deviations.append(Deviation("file_missing", f"Файл не прочитан: {rel}", "high"))
            continue
        truncated = False
        if profile.truncate_chars and len(text) > profile.truncate_chars:
            text = text[: profile.truncate_chars]
            truncated = True
            deviations.append(
                Deviation("truncation", f"Файл обрезан до {profile.truncate_chars} симв.: {rel}", "high")
            )
        blocks.append(
            Block(
                "context_file",
                rel,
                len(text),
                estimate_tokens(text, profile.model),
                hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                _mtime(path),
                truncated=truncated,
            )
        )
        parts.append(f"# {rel}\n\n{text}" if wrapper == WRAPPER_LABELED else text)
        files_used += 1

    if profile.context_files:
        deviations.append(
            Deviation(
                "context_files_inlined",
                "Справочные файлы вложены в промпт целиком. Если платформа-оригинал "
                "ищет по ним фрагменты (RAG), вход отличается — прямое сравнение невалидно",
                "high",
            )
        )

    # Любая склейка — это решение песочницы, а не тестируемого промпта.
    # Один источник = байт в байт то, что лежит в файле; два и больше — уже сборка.
    if len(parts) > 1:
        deviations.append(
            Deviation(
                "parts_joined",
                f"Системный промпт склеен из {len(parts)} частей через пустую строку"
                + (", с заголовками-путями перед каждым файлом" if wrapper == WRAPPER_LABELED else ""),
                "warn" if wrapper == WRAPPER_LABELED else "info",
            )
        )

    system_prompt = "\n\n".join(part for part in parts if part.strip())
    return BuiltPrompt(
        system_prompt=system_prompt,
        blocks=blocks,
        deviations=deviations,
        system_tokens=estimate_tokens(system_prompt, profile.model),
        system_sha256=hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
    )


def build_messages(
    built: BuiltPrompt,
    user_message: str,
    history: list[dict] | None = None,
) -> list[dict]:
    """Формирует messages ровно так, как ушло бы при прямом вызове API."""
    messages: list[dict] = []
    if built.system_prompt.strip():
        messages.append({"role": "system", "content": built.system_prompt})
    for item in history or []:
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages
