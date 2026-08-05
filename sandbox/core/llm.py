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

from .config import CONFIG

# Семейства с reasoning: не принимают temperature/top_p и требуют
# max_completion_tokens вместо max_tokens.
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4", "gpt-6")


def is_reasoning_model(model: str) -> bool:
    return any(model.startswith(prefix) for prefix in _REASONING_PREFIXES)


@dataclass
class LLMResult:
    text: str = ""
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
) -> tuple[dict, list[dict]]:
    """Собирает тело запроса. Возвращает (body, adaptations)."""
    body: dict = {"model": model, "messages": messages}
    adaptations: list[dict] = []

    reasoning = is_reasoning_model(model)

    if temperature is not None:
        if reasoning:
            adaptations.append(
                {
                    "code": "param_dropped",
                    "param": "temperature",
                    "value": temperature,
                    "reason": f"{model} — reasoning-модель, temperature не поддерживается",
                }
            )
        else:
            body["temperature"] = temperature

    if top_p is not None:
        if reasoning:
            adaptations.append(
                {"code": "param_dropped", "param": "top_p", "value": top_p, "reason": "reasoning-модель"}
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

    result = LLMResult(
        text=reply,
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
