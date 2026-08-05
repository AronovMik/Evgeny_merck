"""Оркестрация одного прогона: сборка → вызов → проверки → журнал.

Один и тот же код обслуживает и чат, и повторные прогоны проб —
иначе основной и служебные прогоны меряли бы разное.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import checks as checks_mod
from . import knowledge as knowledge_mod
from . import llm, pricing, runlog, tokens
from .config import CONFIG, REPO_ROOT
from .profiles import Profile
from .prompt_builder import build_messages, build_system_prompt


def gather_knowledge(profile: Profile, query: str) -> dict | None:
    """Готовит контекст из файлов проекта так же, как это делает Langdock.

    Небольшие файлы подаются целиком, крупные — поиском по фрагментам.
    Возвращает и сам текст, и полный отчёт о поиске: без отчёта потом
    невозможно отличить «модель не увидела нужный кусок» от «в базе этого нет».
    """
    if not profile.knowledge_files:
        return None

    # Правило Langdock: способ подачи определяется ЧИСЛОМ документов, а не их
    # размером. До 20 документов агент показывает модели все файлы целиком,
    # с 21-го переходит на поиск по фрагментам. Режим можно задать в профиле
    # явно, если файлы подключены не прямой загрузкой, а базой знаний или
    # синхронизированной папкой — там поиск включается всегда.
    mode = profile.knowledge_mode
    if mode == "auto":
        mode = "preview" if len(profile.knowledge_files) <= 20 else "embedding"

    if mode == "preview":
        full_files = list(profile.knowledge_files)
        search_files = []
    else:
        full_files = []
        search_files = list(profile.knowledge_files)

    chunks, stats = knowledge_mod.build_index(
        search_files, chunk_chars=profile.knowledge_chunk_chars
    )
    found = knowledge_mod.retrieve(query, chunks, top_k=profile.knowledge_top_k)

    blocks: list[str] = []
    full_details = []
    for relative in full_files:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        blocks.append(f"[{relative}]\n{text}")
        full_details.append({"source": relative, "chars": len(text)})

    if found:
        blocks.append(knowledge_mod.render_context(found))

    context = "\n\n".join(blocks)
    return {
        "mode": mode,
        "documents": len(profile.knowledge_files),
        "text": context,
        "retrieved": found,
        "chunks_total": len(chunks),
        "chunks_used": len(found),
        "full_text_files": full_details,
        "searched_files": stats["files"],
        "method": stats["method"],
        "top_k": profile.knowledge_top_k,
        "chunk_chars": profile.knowledge_chunk_chars,
        "embedding_model": knowledge_mod.EMBEDDING_MODEL,
        "context_chars": len(context),
    }


def prepare(
    profile: Profile,
    user_message: str,
    *,
    history: list[dict] | None = None,
    overrides: dict | None = None,
    wrapper: str = "none",
    stream: bool = True,
) -> dict:
    """Готовит всё для вызова, не обращаясь к API."""
    overrides = overrides or {}

    built = build_system_prompt(
        profile,
        wrapper=wrapper,
        override_system_text=overrides.get("system_text"),
    )
    messages = build_messages(built, user_message, history)

    # База знаний проекта: ищем под конкретный вопрос и вкладываем найденное
    # отдельным системным сообщением — тестируемый промпт остаётся нетронутым,
    # а найденное видно в логе отдельной строкой.
    retrieval = gather_knowledge(profile, user_message)
    if retrieval and retrieval["text"]:
        insert_at = 1 if messages and messages[0]["role"] == "system" else 0
        messages.insert(insert_at, {"role": "system", "content": retrieval["text"]})

    model = overrides.get("model") or profile.model or CONFIG.default_model
    temperature = overrides.get("temperature", profile.temperature)
    top_p = overrides.get("top_p", profile.top_p)
    max_tokens = overrides.get("max_tokens", profile.max_tokens)
    seed = overrides.get("seed", profile.seed)
    reasoning_effort = overrides.get("reasoning_effort", profile.reasoning_effort)
    want_logprobs = bool(overrides.get("logprobs", profile.logprobs))

    body, adaptations = llm.build_request_body(
        model,
        messages,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort or "",
        seed=seed,
        stream=stream,
        logprobs=want_logprobs,
    )

    deviations = [dev.to_dict() for dev in built.deviations]

    if retrieval and retrieval["mode"] == "preview":
        deviations.append(
            {
                "code": "knowledge_preview",
                "detail": (
                    f"Файлы проекта поданы целиком — {retrieval['documents']} документов, "
                    f"{retrieval['context_chars']} символов. Это правило Langdock: до 20 документов "
                    f"агент показывает модели весь файл, поиск по фрагментам включается с 21-го. "
                    f"Не опубликовано, есть ли у их предпросмотра потолок объёма («as much text as "
                    f"possible»), — если есть, платформа могла отдать модели меньше нашего."
                ),
                "severity": "info",
            }
        )
    elif retrieval:
        deviations.append(
            {
                "code": "knowledge_retrieval",
                "detail": (
                    f"База знаний подана поиском по фрагментам: подставлено "
                    f"{retrieval['chunks_used']} из {retrieval['chunks_total']} фрагментов "
                    f"(потолок {retrieval['top_k']}), фрагмент {retrieval['chunk_chars']} симв., "
                    f"вектор {knowledge_mod.EMBEDDING_DIMENSIONS} измерений. Размер фрагмента, "
                    f"размерность и потолок — по документации Langdock; какой моделью они считают "
                    f"эмбеддинги, не опубликовано."
                ),
                "severity": "info",
            }
        )
    if retrieval and retrieval["mode"] != "preview":
        if retrieval["method"] != "embeddings":
            deviations.append(
                {
                    "code": "knowledge_lexical_fallback",
                    "detail": (
                        "Эмбеддинги недоступны, фрагменты отобраны совпадением слов. "
                        "Это не семантический поиск — с платформой такой прогон не сопоставим."
                    ),
                    "severity": "high",
                }
            )
    if retrieval:
        missing = [f for f in retrieval["searched_files"] if f.get("missing")]
        if missing:
            deviations.append(
                {
                    "code": "knowledge_file_missing",
                    "detail": "Файлы базы знаний не прочитаны: "
                    + ", ".join(f["source"] for f in missing),
                    "severity": "high",
                }
            )

    if history:
        deviations.append(
            {
                "code": "history_included",
                "detail": f"В запрос включена история диалога: {len(history)} сообщений",
                "severity": "info",
            }
        )

    estimated_prompt_tokens = tokens.count_messages(messages, model)
    if estimated_prompt_tokens > CONFIG.prompt_token_guard:
        deviations.append(
            {
                "code": "prompt_too_large",
                "detail": (
                    f"Оценка промпта {estimated_prompt_tokens} токенов превышает порог "
                    f"{CONFIG.prompt_token_guard}. Запрос, скорее всего, будет отклонён или дорог."
                ),
                "severity": "high",
            }
        )

    run_id = runlog.new_run_id()
    watched = [block.source for block in built.blocks]

    record = {
        "id": run_id,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mock": CONFIG.effective_mock,
        "profile": profile.to_dict(),
        "input": {
            "user_message": user_message,
            "history_len": len(history or []),
            "history": history or [],
        },
        "prompt": {
            **built.to_dict(),
            "deviations": deviations,
            "clean": not deviations,
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "estimation_method": tokens.estimation_method(model),
        },
        "request": {
            "model": model,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "seed": seed,
            "reasoning_effort": reasoning_effort,
            "logprobs": want_logprobs,
            "base_url": CONFIG.base_url,
            "stream": stream,
        },
        "request_body_redacted": runlog.redact_body(body),
        "git": runlog.git_state(watched + [f["source"] for f in (retrieval or {}).get("searched_files", [])]),
    }

    if retrieval:
        # Найденные фрагменты сохраняются целиком: запись прогона должна
        # показывать ровно то, что модель видела. Без этого через неделю
        # невозможно отличить пробел в базе от промаха поиска.
        record["retrieval"] = {key: value for key, value in retrieval.items() if key != "text"}

    return {"record": record, "body": body, "adaptations": adaptations, "built": built}


def finalize(
    record: dict,
    result: llm.LLMResult,
    *,
    item_checks: list[dict] | None = None,
    check_set_name: str = "default",
    suite: str = "",
    suite_label: str = "",
    item_title: str = "",
) -> dict:
    """Достраивает запись прогона: проверки, стоимость, сравнение с базой, запись на диск."""
    check_set = checks_mod.load_check_set(check_set_name)
    all_checks = list(check_set.get("default_checks") or []) + list(item_checks or [])
    check_results = checks_mod.run_checks(result.text, all_checks, check_set)

    usage = result.usage or {}
    # Калибровка счётчика токенов идёт только по настоящим ответам API:
    # выдуманные mock-цифры испортили бы оценку для реальных прогонов.
    if usage.get("prompt_tokens") and not record.get("mock"):
        tokens.record_actual(
            record["request"]["model"],
            record["prompt"].get("estimated_prompt_tokens") or 0,
            usage["prompt_tokens"],
        )

    deviations = list(record["prompt"].get("deviations") or [])
    for adaptation in result.adaptations or []:
        deviations.append(
            {
                "code": adaptation.get("code", "param_adapted"),
                "detail": f"{adaptation.get('param')}: {adaptation.get('reason')}",
                "severity": "warn",
            }
        )
    record["prompt"]["deviations"] = deviations
    record["prompt"]["clean"] = not deviations

    record["response"] = result.to_dict()
    record["checks"] = [check.to_dict() for check in check_results]
    record["checks_summary"] = checks_mod.summarize(check_results)
    record["cost"] = pricing.estimate_cost(record["request"]["model"], usage)
    record["check_set"] = check_set_name
    if suite:
        record["suite"] = suite
        record["suite_label"] = suite_label
        record["item_title"] = item_title

    previous = runlog.find_previous_similar(
        record["id"], record["profile"]["id"], record["input"]["user_message"]
    )
    if previous:
        record["baseline_candidate"] = previous["id"]

    runlog.save_run(record)
    return record


def run_sync(
    profile: Profile,
    user_message: str,
    *,
    overrides: dict | None = None,
    item_checks: list[dict] | None = None,
    check_set_name: str = "default",
    suite: str = "",
    suite_label: str = "",
    item_title: str = "",
) -> dict:
    """Полный синхронный прогон — используется пробами (повтор и абляция)."""
    prepared = prepare(profile, user_message, overrides=overrides, stream=False)
    engine = llm.mock_completion if CONFIG.effective_mock else llm.stream_completion

    # Для не-стримингового режима всё равно идём через общий генератор,
    # чтобы поведение и логи ручного и батч-прогона не разъезжались.
    prepared["body"]["stream"] = True
    prepared["body"]["stream_options"] = {"include_usage": True}

    result = None
    for event, payload in engine(prepared["body"], prepared["adaptations"]):
        if event in ("done", "error"):
            result = payload
    result = result or llm.LLMResult(error="Пустой ответ клиента")

    return finalize(
        prepared["record"],
        result,
        item_checks=item_checks,
        check_set_name=check_set_name,
        suite=suite,
        suite_label=suite_label,
        item_title=item_title,
    )

