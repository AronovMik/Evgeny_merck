#!/usr/bin/env python3
"""Проверка боевого пути: python3 sandbox/check-api.py

Прогоняет то, что нельзя проверить без ключа: доступность модели, реакцию
gpt-5.5 на параметры, эмбеддинги, индексацию базы знаний, семантический поиск
и один настоящий запрос через профиль тренажёра.

Печатает отчёт, который безопасно показать: ключ не выводится ни целиком,
ни частями, тексты базы знаний не печатаются. Тратит несколько центов.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import knowledge, llm, runner  # noqa: E402
from core.config import CONFIG  # noqa: E402
from core.profiles import get_profile  # noqa: E402

FINDINGS: list[str] = []


def line(mark: str, text: str) -> None:
    print(f"  {mark} {text}")


def ok(text: str) -> None:
    line("✓", text)


def bad(text: str, fix: str = "") -> None:
    line("✕", text)
    if fix:
        FINDINGS.append(fix)


def warn(text: str, fix: str = "") -> None:
    line("△", text)
    if fix:
        FINDINGS.append(fix)


def api_get(path: str):
    request = urllib.request.Request(
        f"{CONFIG.base_url}{path}",
        headers={"Authorization": f"Bearer {CONFIG.api_key}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    if not CONFIG.has_key:
        print("Ключ не задан. Сначала: bash sandbox/set-key.sh")
        return 1

    print("=" * 66)
    print("  ПРОВЕРКА БОЕВОГО ПУТИ")
    print("=" * 66)
    print(f"  Адрес API: {CONFIG.base_url}")
    print(f"  Модель по умолчанию: {CONFIG.default_model}")
    print()

    # 1. Ключ и список моделей ------------------------------------------------
    print("1. Ключ и доступные модели")
    try:
        models = sorted(item["id"] for item in api_get("/models").get("data", []))
    except urllib.error.HTTPError as exc:
        bad(f"API отклонил ключ: HTTP {exc.code} {exc.reason}")
        print("\nДальше проверять нечего — разберитесь с ключом.")
        return 1
    except Exception as exc:
        bad(f"Не удалось обратиться к API: {type(exc).__name__}: {exc}")
        return 1

    ok(f"ключ принят, моделей доступно: {len(models)}")
    target = CONFIG.default_model
    if target in models:
        ok(f"модель {target} в списке доступных")
    else:
        близкие = [m for m in models if m.startswith("gpt-5")][:6]
        bad(
            f"модели {target} в списке НЕТ. Похожие: {', '.join(близкие) or 'не найдено'}",
            f"Поправьте SANDBOX_DEFAULT_MODEL в sandbox/.env и model: в профилях — "
            f"модели «{target}» ваш аккаунт не отдаёт.",
        )

    # 2. Как модель реагирует на параметры ------------------------------------
    print("\n2. Что модель принимает (проверка models.json)")
    caps = llm.model_capabilities(target)
    print(f"     сейчас записано: temperature={caps['temperature']}, logprobs={caps['logprobs']}")

    def try_call(extra: dict, label: str) -> bool:
        body = {
            "model": target,
            "messages": [{"role": "user", "content": "Ответь одним словом: работает"}],
            **extra,
        }
        try:
            request = urllib.request.Request(
                f"{CONFIG.base_url}/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {CONFIG.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=120):
                return True
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            print(f"     {label}: отклонено — {detail.strip()[:160]}")
            return False
        except Exception as exc:
            print(f"     {label}: сбой — {type(exc).__name__}")
            return False

    accepts_temperature = try_call({"temperature": 0.5}, "temperature")
    if accepts_temperature == caps["temperature"]:
        ok(f"temperature: {'принимается' if accepts_temperature else 'не принимается'} — как в models.json")
    else:
        warn(
            f"temperature: на деле {'принимается' if accepts_temperature else 'НЕ принимается'}, "
            f"а в models.json записано обратное",
            f'В sandbox/models.json у "{target}" поставьте "temperature": {str(accepts_temperature).lower()}',
        )

    accepts_logprobs = try_call({"logprobs": True, "top_logprobs": 1}, "logprobs")
    if accepts_logprobs == caps["logprobs"]:
        ok(f"logprobs: {'отдаются' if accepts_logprobs else 'не отдаются'} — как в models.json")
    else:
        warn(
            f"logprobs: на деле {'ОТДАЮТСЯ' if accepts_logprobs else 'не отдаются'}, "
            f"а в models.json записано обратное",
            f'В sandbox/models.json у "{target}" поставьте "logprobs": {str(accepts_logprobs).lower()}'
            + (" — и тогда в интерфейсе появится галочка «Уверенность»." if accepts_logprobs else ""),
        )

    # 3. Эмбеддинги — сердце базы знаний --------------------------------------
    print("\n3. Эмбеддинги (без них база знаний работать не будет)")
    try:
        vectors = knowledge.embed_texts(["проверка связи"])
        if vectors and len(vectors[0]) == knowledge.EMBEDDING_DIMENSIONS:
            ok(f"{knowledge.EMBEDDING_MODEL} отвечает, вектор {len(vectors[0])} измерений")
        else:
            bad("эмбеддинги вернулись в неожиданном виде")
    except urllib.error.HTTPError as exc:
        bad(
            f"эмбеддинги недоступны: HTTP {exc.code}",
            "Без эмбеддингов база знаний ищется совпадением слов — с Langdock такой "
            "прогон не сопоставим. Проверьте, доступна ли модель text-embedding-3-small.",
        )
        return _finish()
    except Exception as exc:
        bad(f"эмбеддинги недоступны: {type(exc).__name__}: {exc}")
        return _finish()

    # 4. Индексация базы знаний ------------------------------------------------
    print("\n4. Индексация базы знаний тренажёра")
    profile = get_profile("medrep-simulator")
    if profile is None:
        bad("профиль medrep-simulator не найден")
        return _finish()

    search_files = [
        f for f in profile.knowledge_files
        if (Path(__file__).resolve().parent.parent / f).stat().st_size > profile.knowledge_full_text_limit
    ]
    started = time.monotonic()
    chunks, stats = knowledge.build_index(search_files, chunk_chars=profile.knowledge_chunk_chars)
    elapsed = time.monotonic() - started

    if stats["method"] == "embeddings":
        ok(f"индекс построен: {len(chunks)} фрагментов за {elapsed:.1f} с")
        print(f"     новых эмбеддингов: {stats['embedded_now']}, из кэша: {stats['from_cache']}")
    else:
        bad("индекс собран БЕЗ эмбеддингов — поиск будет лексическим")

    # 5. Семантический поиск ---------------------------------------------------
    print("\n5. Семантический поиск — то, ради чего всё это")
    query = "Пациент на бисопрололе и амлодипине раздельно, врач против перевода на Конкор АМ"
    found = knowledge.retrieve(query, chunks, top_k=profile.knowledge_top_k)
    if not found:
        bad("поиск не вернул ни одного фрагмента")
    else:
        ok(f"по запросу подставлено {len(found)} фрагментов (потолок {profile.knowledge_top_k})")
        print("     что нашлось (первые 5):")
        for item in found[:5]:
            print(f"       {item['score']:.3f}  {item['source'].split('/')[-1]:<26} {item['heading'][:48]}")
        уникальных = len({item["source"] for item in found})
        if уникальных == 1:
            warn(
                "все фрагменты из одного файла — возможно, поиск смещён",
                "Посмотрите, не перекошена ли выдача: при таком запросе ожидались "
                "фрагменты минимум из typology_v2 и mandatory_args.",
            )
        else:
            ok(f"выдача разложена по {уникальных} файлам — поиск не залип на одном")

    # 6. Настоящий прогон ------------------------------------------------------
    print("\n6. Настоящий запрос через профиль тренажёра")
    try:
        record = runner.run_sync(
            profile,
            "Дай первый кейс сессии.",
            check_set_name=profile.checks,
        )
    except Exception as exc:
        bad(f"прогон упал: {type(exc).__name__}: {exc}")
        return _finish()

    response = record.get("response") or {}
    if response.get("error"):
        bad(f"модель вернула ошибку: {response['error'][:200]}")
        return _finish()

    usage = response.get("usage") or {}
    ok(f"ответ получен: {len(response.get('text',''))} символов, {response.get('latency_ms')} мс")
    print(f"     токены: промпт {usage.get('prompt_tokens')}, ответ {usage.get('completion_tokens')}")
    детали = usage.get("completion_tokens_details") or {}
    if детали.get("reasoning_tokens"):
        print(f"     из них на рассуждение: {детали['reasoning_tokens']}")
    print(f"     ответила модель: {response.get('model_returned')}")

    cost = record.get("cost") or {}
    if cost.get("known"):
        print(f"     стоимость прогона: ${cost['total']}")
    else:
        warn(
            "стоимость не посчитана — тарифа нет в pricing.json",
            f'Впишите в sandbox/pricing.json строку для "{target}" после сверки с openai.com/pricing.',
        )

    if response.get("logprobs"):
        ok("logprobs пришли — уверенность по фрагменту будет считаться")

    if response.get("finish_reason") == "length":
        warn("ответ оборван лимитом токенов", "Поднимите max_tokens в профиле.")

    retrieval = record.get("retrieval") or {}
    if retrieval:
        ok(f"база знаний сработала: {retrieval['chunks_used']} фрагментов из {retrieval['chunks_total']}")

    памятка = "Как устроен тренажёр" in response.get("text", "")
    if памятка:
        ok("памятка из onboarding.md выведена — файл целиком доехал до модели")
    else:
        warn(
            "памятки из onboarding.md в ответе нет",
            "Промпт требует выводить её перед первым кейсом. Проверьте, дошёл ли файл: "
            "он подаётся целиком, значит дело в промпте или в модели, а не в поиске.",
        )

    print(f"\n     начало ответа: {response.get('text','')[:160].strip()}…")
    print(f"     прогон записан: {record['id']}")
    return _finish()


def _finish() -> int:
    print()
    print("=" * 66)
    if FINDINGS:
        print("ЧТО ПОПРАВИТЬ:")
        for item in FINDINGS:
            print(f"  • {item}")
    else:
        print("Всё сошлось: боевой путь работает, настройки соответствуют реальности.")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
