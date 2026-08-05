"""Клиент OpenAI Chat Completions на голой стандартной библиотеке.

Никаких SDK и зависимостей: на рабочем ноутбуке без прав на pip install
песочница всё равно запустится.

Клиент — прозрачный: тело запроса собирается из параметров профиля и
отправляется как есть. Всё, что клиент вынужден изменить (например, убрать
параметр, который модель не принимает), возвращается в `adaptations` и
попадает в лог прогона как отклонение.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .config import CONFIG, SANDBOX_DIR

_MODELS_PATH = SANDBOX_DIR / "models.json"

# Запасные значения, если models.json отсутствует или битый.
_FALLBACK_REASONING_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")


def model_capabilities(model: str) -> dict:
    """Возможности модели из редактируемого models.json (самый длинный префикс)."""
    defaults = {
        "reasoning": any(model.startswith(prefix) for prefix in _FALLBACK_REASONING_PREFIXES),
        "temperature": not any(model.startswith(prefix) for prefix in _FALLBACK_REASONING_PREFIXES),
        "logprobs": True,
    }
    if not _MODELS_PATH.exists() or not model:
        return defaults
    try:
        table = json.loads(_MODELS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return defaults

    matches = [key for key in table if not key.startswith("_") and model.startswith(key)]
    if not matches:
        return defaults
    entry = table[max(matches, key=len)]
    return {
        "reasoning": bool(entry.get("reasoning", defaults["reasoning"])),
        "temperature": bool(entry.get("temperature", defaults["temperature"])),
        "logprobs": bool(entry.get("logprobs", defaults["logprobs"])),
    }


def is_reasoning_model(model: str) -> bool:
    return model_capabilities(model)["reasoning"]


@dataclass
class LLMResult:
    text: str = ""
    tokens: list[str] = field(default_factory=list)
    logprobs: list[float] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    finish_reason: str = ""
    model_returned: str = ""
    response_id: str = ""
    system_fingerprint: str = ""
    service_tier: str = ""
    latency_ms: int = 0
    ttfb_ms: int = 0
    attempts: int = 1
    adaptations: list[dict] = field(default_factory=list)
    error: str = ""
    http_status: int = 0
    raw_request: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            # Пословная уверенность модели. Пусто, если модель не отдаёт logprobs.
            "tokens": self.tokens,
            "logprobs": self.logprobs,
            "usage": self.usage,
            "finish_reason": self.finish_reason,
            "model_returned": self.model_returned,
            "response_id": self.response_id,
            "system_fingerprint": self.system_fingerprint,
            "service_tier": self.service_tier,
            "latency_ms": self.latency_ms,
            "ttfb_ms": self.ttfb_ms,
            "attempts": self.attempts,
            "adaptations": self.adaptations,
            "error": self.error,
            "http_status": self.http_status,
        }


def build_request_body(
    model: str,
    messages: list[dict],
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str = "",
    seed: int | None = None,
    stream: bool = True,
    logprobs: bool = False,
) -> tuple[dict, list[dict]]:
    """Собирает тело запроса. Возвращает (body, adaptations)."""
    body: dict = {"model": model, "messages": messages}
    adaptations: list[dict] = []

    # logprobs — единственное окно в процесс генерации, которое отдаёт API:
    # вероятность каждого выданного токена. Поддержка зависит от модели;
    # если модель откажет, параметр снимется и это попадёт в лог.
    if logprobs:
        body["logprobs"] = True
        body["top_logprobs"] = 1

    caps = model_capabilities(model)
    reasoning = caps["reasoning"]

    if temperature is not None:
        if not caps["temperature"]:
            adaptations.append(
                {
                    "code": "param_dropped",
                    "param": "temperature",
                    "value": temperature,
                    "reason": f"по models.json {model} не принимает temperature",
                }
            )
        else:
            body["temperature"] = temperature

    if top_p is not None:
        if not caps["temperature"]:
            adaptations.append(
                {
                    "code": "param_dropped",
                    "param": "top_p",
                    "value": top_p,
                    "reason": f"по models.json {model} не принимает top_p",
                }
            )
        else:
            body["top_p"] = top_p

    if max_tokens:
        if reasoning:
            body["max_completion_tokens"] = max_tokens
            adaptations.append(
                {
                    "code": "param_renamed",
                    "param": "max_tokens",
                    "to": "max_completion_tokens",
                    "reason": "требование reasoning-моделей",
                }
            )
        else:
            body["max_tokens"] = max_tokens

    if reasoning_effort and reasoning:
        body["reasoning_effort"] = reasoning_effort

    if seed is not None:
        body["seed"] = seed

    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}

    return body, adaptations


def _headers() -> dict:
    headers = {
        "Authorization": f"Bearer {CONFIG.api_key}",
        "Content-Type": "application/json",
    }
    if CONFIG.organization:
        headers["OpenAI-Organization"] = CONFIG.organization
    return headers


def _strip_param_from_error(body: dict, message: str) -> str | None:
    """Достаёт имя параметра, на который ругнулся API, чтобы убрать его и повторить."""
    match = re.search(r"[Uu]nsupported parameter:?\s*'?([\w_]+)'?", message)
    if not match:
        match = re.search(r"[Uu]nrecognized request argument supplied:?\s*'?([\w_]+)'?", message)
    if not match:
        match = re.search(r"'([\w_]+)' is not supported", message)
    if match and match.group(1) in body:
        return match.group(1)
    return None


def stream_completion(body: dict, adaptations: list[dict]):
    """Генератор событий: ('meta'|'delta'|'usage'|'done'|'error', payload).

    Ретраи на сетевых ошибках и 429/5xx — до CONFIG.max_retries с экспоненциальной
    паузой. Каждый ретрай виден в итоговом логе (поле attempts).
    """
    url = f"{CONFIG.base_url}/chat/completions"
    attempt = 0
    local_adaptations = list(adaptations)

    while True:
        attempt += 1
        started = time.monotonic()
        ttfb_ms = 0
        got_first = False
        result = LLMResult(attempts=attempt, adaptations=local_adaptations, raw_request=body)

        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers=_headers(),
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=CONFIG.request_timeout) as response:
                result.http_status = response.status
                buffer = ""
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    if not got_first:
                        got_first = True
                        ttfb_ms = int((time.monotonic() - started) * 1000)
                        result.ttfb_ms = ttfb_ms
                        result.response_id = chunk.get("id", "")
                        result.model_returned = chunk.get("model", "")
                        result.system_fingerprint = chunk.get("system_fingerprint", "") or ""
                        result.service_tier = chunk.get("service_tier", "") or ""
                        yield "meta", {
                            "response_id": result.response_id,
                            "model_returned": result.model_returned,
                            "system_fingerprint": result.system_fingerprint,
                            "ttfb_ms": ttfb_ms,
                        }

                    if chunk.get("usage"):
                        result.usage = chunk["usage"]

                    for choice in chunk.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            buffer += delta
                            yield "delta", delta
                        for entry in ((choice.get("logprobs") or {}).get("content") or []):
                            result.tokens.append(entry.get("token", ""))
                            result.logprobs.append(round(float(entry.get("logprob", 0.0)), 4))
                        if choice.get("finish_reason"):
                            result.finish_reason = choice["finish_reason"]

                result.text = buffer
                result.latency_ms = int((time.monotonic() - started) * 1000)
                yield "done", result
                return

        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
                message = (parsed.get("error") or {}).get("message", raw)
            except Exception:
                message = raw

            # Модель отвергла параметр — убираем его и повторяем, фиксируя это.
            offending = _strip_param_from_error(body, message)
            if exc.code == 400 and offending:
                removed = body.pop(offending)
                local_adaptations.append(
                    {
                        "code": "param_dropped_after_400",
                        "param": offending,
                        "value": removed,
                        "reason": message[:300],
                    }
                )
                continue

            if exc.code in (429, 500, 502, 503, 504) and attempt <= CONFIG.max_retries:
                time.sleep(2 ** attempt)
                continue

            result.error = f"HTTP {exc.code}: {message}"
            result.http_status = exc.code
            result.latency_ms = int((time.monotonic() - started) * 1000)
            yield "error", result
            return

        except Exception as exc:
            if attempt <= CONFIG.max_retries:
                time.sleep(2 ** attempt)
                continue
            result.error = f"{type(exc).__name__}: {exc}"
            result.latency_ms = int((time.monotonic() - started) * 1000)
            yield "error", result
            return


def complete(body: dict, adaptations: list[dict]) -> LLMResult:
    """Синхронный вызов (для батч-прогонов наборов тестов)."""
    final: LLMResult | None = None
    for event, payload in stream_completion(body, adaptations):
        if event in ("done", "error"):
            final = payload
    return final or LLMResult(error="Пустой ответ клиента")


def mock_completion(body: dict, adaptations: list[dict]):
    """Детерминированный псевдо-ответ без обращения к API.

    Нужен, чтобы проверять саму песочницу (логи, проверки, сравнения),
    не тратя токены. Помечается в логе как mock — с реальными прогонами
    такие записи не смешиваются.
    """
    messages = body.get("messages", [])
    user_text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    system_text = next((m["content"] for m in messages if m["role"] == "system"), "")

    reply = (
        f"[MOCK] Ответ без обращения к API.\n\n"
        f"Вопрос: {user_text[:200]}\n"
        f"Символов в системном промпте: {len(system_text)}\n"
        f"Модель из запроса: {body.get('model')}\n\n"
        "Источники: ОХЛП Конкор (см. context/product-info/), КР МЗ РФ."
    )

    # Псевдо-logprobs: детерминированные, чтобы проверять отображение уверенности.
    mock_tokens: list[str] = []
    mock_logprobs: list[float] = []
    if body.get("logprobs"):
        cursor = 0
        for word in re.findall(r"\S+\s*", reply):
            mock_tokens.append(word)
            # Слова с цифрами и латиницей «менее уверенные» — видно на глаз.
            penalty = 0.9 if re.search(r"\d|[A-Za-z]", word) else 0.05
            mock_logprobs.append(round(-0.02 - penalty * ((cursor % 7) / 7), 4))
            cursor += 1

    result = LLMResult(
        text=reply,
        tokens=mock_tokens,
        logprobs=mock_logprobs,
        usage={
            "prompt_tokens": max(1, len(system_text) // 3),
            "completion_tokens": max(1, len(reply) // 3),
            "total_tokens": max(2, (len(system_text) + len(reply)) // 3),
        },
        finish_reason="stop",
        model_returned=f"{body.get('model')} (mock)",
        response_id="mock-response",
        latency_ms=120,
        ttfb_ms=40,
        adaptations=adaptations,
        raw_request=body,
    )

    yield "meta", {
        "response_id": result.response_id,
        "model_returned": result.model_returned,
        "system_fingerprint": "",
        "ttfb_ms": result.ttfb_ms,
    }
    for index in range(0, len(reply), 40):
        yield "delta", reply[index : index + 40]
    yield "done", result


def list_models() -> list[str]:
    """Список моделей из API — чтобы не гадать с названиями в интерфейсе."""
    if CONFIG.effective_mock:
        return ["mock-model"]
    try:
        request = urllib.request.Request(f"{CONFIG.base_url}/models", headers=_headers(), method="GET")
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        models = sorted({item.get("id", "") for item in data.get("data", []) if item.get("id")})
        return [m for m in models if m]
    except Exception:
        return []
