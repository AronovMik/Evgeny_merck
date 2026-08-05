#!/usr/bin/env python3
"""Самопроверка песочницы: python3 sandbox/selftest.py

Поднимает сервер в mock-режиме на свободном порту, прогоняет весь цикл
(чат → лог прогона → разметка → пробы → набор тестов → сравнение) и печатает
отчёт. К API не обращается и денег не тратит.

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

        aggregate = request(f"{base}/api/annotations")
        check("срез по замечаниям строится", aggregate["total"] == 1, f"категорий: {len(aggregate['by_category'])}")

        print("\n5. Пробы процесса")
        stability = request(f"{base}/api/probe/stability", {"run_id": run_id, "annotation_index": 0, "repeats": 3})
        check("проба на стабильность отработала", len(stability["repeats"]) == 3, stability["verdict"][:70])
        ablation = request(f"{base}/api/probe/ablation", {"run_id": run_id, "annotation_index": 0})
        check("проба абляцией отработала", len(ablation["variants"]) == 2, ablation["verdict"][:70])

        print("\n6. Набор регресс-тестов")
        suites = request(f"{base}/api/suites")
        check("набор разобран", suites and len(suites[0]["items"]) >= 5, f"пунктов: {len(suites[0]['items']) if suites else 0}")
        suite_id = suites[0]["id"]
        events = parse_sse(
            request(
                f"{base}/api/suite/run",
                {"suite": suite_id, "profile": "repo-instructions", "label": "selftest-a"},
                raw=True,
            )
        )
        check("прогон набора завершился", "done" in events)
        report = events["done"][0]
        check("итоги посчитаны", report["summary"]["items"] == len(suites[0]["items"]), json.dumps(report["summary"], ensure_ascii=False))

        parse_sse(
            request(
                f"{base}/api/suite/run",
                {"suite": suite_id, "profile": "baseline-empty", "label": "selftest-b"},
                raw=True,
            )
        )
        comparison = request(f"{base}/api/suite/compare?suite={suite_id}&a=selftest-a&b=selftest-b")
        check(
            "сравнение двух меток строится",
            len(comparison["rows"]) > 0,
            f"улучшений {comparison['totals']['improved']}, регрессий {comparison['totals']['regressed']}",
        )

        print("\n7. Сравнение прогонов")
        runs = request(f"{base}/api/runs?limit=5")
        check("журнал прогонов заполняется", len(runs) >= 2, f"записей: {len(runs)}")
        diff = request(f"{base}/api/compare?a={runs[1]['id']}&b={runs[0]['id']}")
        check("диф считается", "verdict" in diff["diff"], diff["diff"]["verdict"][:70])

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
