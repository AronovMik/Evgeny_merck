#!/usr/bin/env python3
"""Самопроверка песочницы: python3 sandbox/selftest.py

Поднимает сервер в mock-режиме на свободном порту, прогоняет весь цикл
(чат → лог прогона → разметка → возврат к прогону → пробы) и печатает отчёт.
К API не обращается и денег не тратит.

Запускать после правок песочницы или когда что-то ведёт себя странно.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SANDBOX = Path(__file__).resolve().parent
FAILURES: list[str] = []


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "✓" if condition else "✕"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES.append(name)


def request(url: str, payload: dict | None = None, raw: bool = False):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as response:
        body = response.read().decode("utf-8")
    return body if raw else json.loads(body)


def parse_sse(text: str) -> dict:
    events: dict[str, list] = {}
    for block in text.split("\n\n"):
        match = re.match(r"event: (\w+)\ndata: (.*)", block, re.S)
        if match:
            events.setdefault(match.group(1), []).append(json.loads(match.group(2)))
    return events


def main() -> int:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "SANDBOX_MOCK": "1",
        "SANDBOX_PORT": str(port),
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(name, None)

    server = subprocess.Popen(
        [sys.executable, str(SANDBOX / "app.py"), "--no-browser"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    try:
        for _ in range(40):
            try:
                request(f"{base}/api/config")
                break
            except Exception:
                time.sleep(0.25)
        else:
            print("Сервер не поднялся")
            return 1

        print("\n1. Конфигурация и профили")
        config = request(f"{base}/api/config")
        check("сервер отвечает", config.get("mock") is True, "mock-режим")
        profiles = request(f"{base}/api/profiles")
        check("профили читаются", len(profiles) >= 1, f"найдено: {len(profiles)}")
        ids = [profile["id"] for profile in profiles]

        print("\n2. Чистота теста (главная гарантия валидности)")
        clean = request(f"{base}/api/preview", {"profile": "repo-instructions", "message": "тест"})
        check(
            "профиль с одним файлом даёт прогон без обвязки",
            clean["prompt"]["clean"] is True,
            f"отклонений: {len(clean['prompt']['deviations'])}",
        )
        dirty = request(
            f"{base}/api/preview",
            {"profile": "repo-instructions-plus-cheatsheet", "message": "тест"},
        )
        codes = [item["code"] for item in dirty["prompt"]["deviations"]]
        check("вложение файлов помечается отклонением", "context_files_inlined" in codes, ", ".join(codes))
        check(
            "состав промпта разложен пофайлово",
            len(dirty["prompt"]["blocks"]) == 2,
            f"блоков: {len(dirty['prompt']['blocks'])}",
        )

        print("\n3. Чат и запись прогона")
        raw = request(
            f"{base}/api/chat",
            {
                "profile": "repo-instructions",
                "message": "Какие показания зарегистрированы у Конкор Кор?",
                "history": [],
                "overrides": {"logprobs": True},
            },
            raw=True,
        )
        events = parse_sse(raw)
        check("поток дошёл до конца", "done" in events, f"событий delta: {len(events.get('delta', []))}")
        done = events["done"][0]
        run_id = done["run_id"]
        check("автопроверки отработали", done["checks_summary"]["total"] > 0, f"{done['checks_summary']}")
        check("logprobs записаны", len(done["response"].get("logprobs") or []) > 0)
        check("цена не выдумана", done["cost"]["known"] is False, "gpt-5.5 нет в pricing.json — так и должно быть")

        record = request(f"{base}/api/run/{run_id}")
        check("полный системный промпт сохранён", len(record["prompt"]["system_prompt"]) > 1000)
        check("версия репозитория записана", bool(record["git"]["commit"]), record["git"]["commit"])
        markdown = SANDBOX / "logs" / "runs" / f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}" / f"{run_id}.md"
        check("читаемый отчёт создан", markdown.exists(), str(markdown.name))

        print("\n4. Разметка ответа и доказательная база")
        answer = record["response"]["text"]
        quote = answer[20:90]
        saved = request(
            f"{base}/api/run/{run_id}/annotations",
            {
                "annotations": [
                    {
                        "part": "analysis",
                        "category": "fact",
                        "severity": "major",
                        "quote": quote,
                        "start": 20,
                        "end": 90,
                        "comment": "проверка самотестом",
                    }
                ]
            },
        )
        check("замечание сохранено", len(saved["annotations"]) == 1)
        evidence = saved["annotations"][0].get("evidence") or {}
        check("собрана доказательная база", bool(evidence.get("term_coverage")), f"терминов проверено: {len(evidence.get('term_coverage', []))}")
        check("уверенность модели посчитана", (evidence.get("confidence") or {}).get("available") is True)
        check("зафиксированы факты о входе", isinstance(evidence.get("facts"), list), f"фактов: {len(evidence.get('facts', []))}")

        stream = SANDBOX / "logs" / "annotations.jsonl"
        digest = SANDBOX / "logs" / "ANNOTATIONS.md"
        check("поток для разбора Claude Code пишется", stream.exists())
        check("сводка собрана", digest.exists())

        # Срез считается по накопленному потоку, а не по одному прогону:
        # сверять с единицей нельзя — от прошлых запусков там уже есть записи.
        aggregate = request(f"{base}/api/annotations")
        check(
            "срез по замечаниям строится",
            aggregate["total"] >= 1
            and any(item["id"] == "fact" for item in aggregate["by_category"]),
            f"всего замечаний в потоке: {aggregate['total']}, категорий: {len(aggregate['by_category'])}",
        )

        print("\n5. Возврат к прогону для доразметки")
        again = request(f"{base}/api/run/{run_id}")
        check("прогон отдаётся целиком", bool((again.get("response") or {}).get("text")))
        check("замечания при нём сохранились", len(again.get("annotations") or []) == 1)
        listing = request(f"{base}/api/runs?limit=10")
        check(
            "в журнале виден счётчик замечаний",
            any(item["id"] == run_id and item.get("annotations_count") == 1 for item in listing),
        )

        print("\n6. Пробы процесса")
        stability = request(f"{base}/api/probe/stability", {"run_id": run_id, "annotation_index": 0, "repeats": 3})
        check("проба на стабильность отработала", len(stability["repeats"]) == 3, stability["verdict"][:70])
        ablation = request(f"{base}/api/probe/ablation", {"run_id": run_id, "annotation_index": 0})
        check("проба абляцией отработала", len(ablation["variants"]) == 2, ablation["verdict"][:70])

        print("\n7. База знаний проекта (механика Langdock)")
        knowledge = request(
            f"{base}/api/preview",
            {"profile": "medrep-simulator", "message": "Пациент на бисопрололе и амлодипине раздельно"},
        )
        retrieval = knowledge.get("retrieval") or {}
        check(
            "7 документов → режим предпросмотра (правило Langdock: поиск с 21-го)",
            retrieval.get("mode") == "preview",
            f"режим: {retrieval.get('mode')}, документов: {retrieval.get('documents')}",
        )
        check(
            "все файлы попали в одну выдачу инструмента",
            len(retrieval.get("full_text_files", [])) == 7,
            f"файлов: {len(retrieval.get('full_text_files', []))}, "
            f"{retrieval.get('context_chars', 0) // 1024} КБ",
        )
        check(
            "длинные файлы обрезаны с хвоста, доля доехавшего посчитана",
            any(f.get("truncated") for f in retrieval.get("full_text_files", [])),
            ", ".join(
                f"{f['source'].split('/')[-1]} {int(f['delivered_share'] * 100)}%"
                for f in retrieval.get("full_text_files", [])
                if f.get("truncated")
            ),
        )
        codes = [item["code"] for item in knowledge["prompt"]["deviations"]]
        check("способ подачи помечен отклонением", "knowledge_preview" in codes, ", ".join(codes))
        check(
            "системный промпт — только файл инструкций",
            len(knowledge["prompt"]["blocks"]) == 1
            and "medrep_prompt_v16" in knowledge["prompt"]["blocks"][0]["source"],
        )
        roles = [m["role"] for m in knowledge["request_body_redacted"]["messages"]]
        check(
            "на первом ходу: system → вопрос → запрос файлов → выдача",
            roles == ["system", "user", "assistant", "tool"],
            " → ".join(roles),
        )

        second = request(
            f"{base}/api/preview",
            {
                "profile": "medrep-simulator",
                "message": "Теперь дай разбор",
                "history": [
                    {"role": "user", "content": "Пациент на бисопрололе и амлодипине раздельно"},
                    {"role": "assistant", "content": "Клинический случай …"},
                ],
            },
        )
        roles2 = [m["role"] for m in second["request_body_redacted"]["messages"]]
        check(
            "файлы читаются один раз за диалог, а не каждый ход",
            roles2.count("tool") == 1 and roles2[:4] == ["system", "user", "assistant", "tool"],
            " → ".join(roles2),
        )
        check(
            "ход чтения зафиксирован в записи прогона",
            (second.get("retrieval") or {}).get("delivered_at_turn") == 1
            and (second.get("retrieval") or {}).get("reread_each_turn") is False,
        )

        print("\n8. Статика интерфейса")
        for asset in ("/", "/static/app.js", "/static/styles.css"):
            body = request(f"{base}{asset}", raw=True)
            check(f"отдаётся {asset}", len(body) > 500, f"{len(body)} байт")

    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for name in FAILURES:
            print(f"  — {name}")
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
