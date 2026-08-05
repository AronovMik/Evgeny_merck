"""Конфигурация песочницы.

Читает .env (без внешних зависимостей), задаёт пути и значения по умолчанию.
Ключ API никогда не попадает в логи и не отдаётся в браузер.
"""

from __future__ import annotations

import os
from pathlib import Path

# sandbox/core/config.py -> sandbox/ -> корень репозитория
SANDBOX_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SANDBOX_DIR.parent

PROFILES_DIR = SANDBOX_DIR / "profiles"
CHECKS_DIR = SANDBOX_DIR / "checks"
WEB_DIR = SANDBOX_DIR / "web"
LOGS_DIR = SANDBOX_DIR / "logs"
RUNS_DIR = LOGS_DIR / "runs"

DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _load_env_file(path: Path) -> None:
    """Загружает KEY=VALUE из .env в os.environ (не перетирая уже заданные)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(SANDBOX_DIR / ".env")
_load_env_file(REPO_ROOT / ".env")


class Config:
    """Снимок настроек. Читается при старте сервера."""

    def __init__(self) -> None:
        self.api_key: str = os.environ.get("OPENAI_API_KEY", "").strip()
        self.base_url: str = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
        self.organization: str = os.environ.get("OPENAI_ORG_ID", "").strip()
        self.host: str = os.environ.get("SANDBOX_HOST", "127.0.0.1").strip()
        self.port: int = int(os.environ.get("SANDBOX_PORT", "8765"))
        self.default_model: str = os.environ.get("SANDBOX_DEFAULT_MODEL", "gpt-5.5").strip()
        self.request_timeout: int = int(os.environ.get("SANDBOX_TIMEOUT", "600"))
        self.max_retries: int = int(os.environ.get("SANDBOX_MAX_RETRIES", "4"))
        # Жёсткий предел на размер собранного системного промпта (в токенах-оценках).
        # Защищает от случайной вкладки гайдлайна на 200k токенов.
        self.prompt_token_guard: int = int(os.environ.get("SANDBOX_PROMPT_TOKEN_GUARD", "180000"))
        # mock=1 — работать без обращения к API (проверка самой песочницы).
        self.mock: bool = os.environ.get("SANDBOX_MOCK", "").strip() in ("1", "true", "yes")

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    @property
    def effective_mock(self) -> bool:
        """Без ключа песочница автоматически уходит в mock-режим."""
        return self.mock or not self.has_key

    def public_dict(self) -> dict:
        """Безопасное представление для браузера — без ключа."""
        return {
            "base_url": self.base_url,
            "default_model": self.default_model,
            "has_key": self.has_key,
            "mock": self.effective_mock,
            "prompt_token_guard": self.prompt_token_guard,
            "repo_root": str(REPO_ROOT),
        }


def ensure_dirs() -> None:
    for path in (LOGS_DIR, RUNS_DIR, PROFILES_DIR, CHECKS_DIR):
        path.mkdir(parents=True, exist_ok=True)


CONFIG = Config()
