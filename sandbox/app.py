#!/usr/bin/env python3
"""Песочница тестирования промптов — локальный сервер.

Запуск:  python3 sandbox/app.py
Затем открыть http://127.0.0.1:8765

Сервер слушает только localhost. Ключ API не покидает машину и не отдаётся
в браузер.
"""

from __future__ import annotations

import json
import mimetypes
import socket
import sys
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import annotations, llm, probes, profiles, runlog, runner  # noqa: E402
from core.config import CONFIG, WEB_DIR, ensure_dirs  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    server_version = "PromptSandbox/1.0"

    # --- служебное ---------------------------------------------------------

    def log_message(self, format: str, *args) -> None:  # тише в консоли
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("  %s\n" % (format % args))

    def _send_json(self, data, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _start_sse(self) -> None:
        # Connection: close обязателен. Длина тела заранее неизвестна, поэтому
        # признаком конца потока служит закрытие сокета: без него читатель на
        # стороне браузера никогда не дождётся завершения запроса.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _sse(self, event: str, data) -> None:
        chunk = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        self.wfile.write(chunk.encode("utf-8"))
        self.wfile.flush()

    # --- маршрутизация -----------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path in ("/", "/index.html"):
                return self._serve_static("index.html")
            if path.startswith("/static/"):
                return self._serve_static(path[len("/static/") :])

            if path == "/api/config":
                return self._send_json(CONFIG.public_dict())

            if path == "/api/profiles":
                return self._send_json([p.to_dict() for p in profiles.list_profiles()])

            if path.startswith("/api/profile/"):
                profile = profiles.get_profile(path.rsplit("/", 1)[-1])
                if not profile:
                    return self._send_error_json("Профиль не найден", 404)
                return self._send_json(profile.to_dict())

            if path == "/api/models":
                return self._send_json({"models": llm.list_models()})

            if path == "/api/model-caps":
                model = query.get("model", [""])[0] or CONFIG.default_model
                return self._send_json({"model": model, **llm.model_capabilities(model)})

            if path == "/api/runs":
                return self._send_json(
                    runlog.list_runs(
                        limit=int(query.get("limit", ["200"])[0]),
                        profile=query.get("profile", [""])[0],
                        suite=query.get("suite", [""])[0],
                        only_errors=query.get("errors", [""])[0] == "1",
                    )
                )

            if path.startswith("/api/run/"):
                record = runlog.load_run(path.rsplit("/", 1)[-1])
                if not record:
                    return self._send_error_json("Прогон не найден", 404)
                return self._send_json(record)


            if path == "/api/annotation-meta":
                return self._send_json(annotations.load_categories())

            if path == "/api/annotations":
                return self._send_json(annotations.aggregate())





            return self._send_error_json("Неизвестный маршрут", 404)

        except Exception as exc:
            traceback.print_exc()
            return self._send_error_json(f"{type(exc).__name__}: {exc}", 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()

        try:
            if path == "/api/preview":
                return self._handle_preview(body)
            if path == "/api/chat":
                return self._handle_chat(body)
            if path.startswith("/api/run/") and path.endswith("/annotations"):
                run_id = path.split("/")[3]
                record = annotations.save_annotations(run_id, body.get("annotations") or [])
                if not record:
                    return self._send_error_json("Прогон не найден", 404)
                return self._send_json(
                    {
                        "ok": True,
                        "annotations": record.get("annotations", []),
                        "summary": record.get("annotations_summary", {}),
                    }
                )

            if path == "/api/annotations/digest":
                return self._send_json({"path": str(annotations.write_digest())})

            if path == "/api/probe/stability":
                return self._send_json(
                    probes.stability_probe(
                        body.get("run_id", ""),
                        repeats=int(body.get("repeats") or 5),
                        annotation_index=body.get("annotation_index"),
                        terms=body.get("terms"),
                    )
                )

            if path == "/api/probe/ablation":
                return self._send_json(
                    probes.ablation_probe(
                        body.get("run_id", ""),
                        annotation_index=body.get("annotation_index"),
                        terms=body.get("terms"),
                    )
                )


            return self._send_error_json("Неизвестный маршрут", 404)

        except Exception as exc:
            traceback.print_exc()
            return self._send_error_json(f"{type(exc).__name__}: {exc}", 500)

    # --- обработчики -------------------------------------------------------

    def _handle_preview(self, body: dict) -> None:
        """Состав промпта без обращения к API — сколько токенов и откуда."""
        profile = profiles.get_profile(body.get("profile", ""))
        if not profile:
            return self._send_error_json("Профиль не найден", 404)
        prepared = runner.prepare(
            profile,
            body.get("message", "") or "(пример вопроса)",
            history=body.get("history") or [],
            overrides=body.get("overrides") or {},
            stream=False,
        )
        record = prepared["record"]
        return self._send_json(
            {
                "prompt": record["prompt"],
                "request": record["request"],
                "request_body_redacted": record["request_body_redacted"],
                "git": record["git"],
            }
        )

    def _handle_chat(self, body: dict) -> None:
        profile = profiles.get_profile(body.get("profile", ""))
        if not profile:
            return self._send_error_json("Профиль не найден", 404)

        message = (body.get("message") or "").strip()
        if not message:
            return self._send_error_json("Пустое сообщение", 400)

        prepared = runner.prepare(
            profile,
            message,
            history=body.get("history") or [],
            overrides=body.get("overrides") or {},
        )
        record = prepared["record"]

        self._start_sse()
        self._sse(
            "start",
            {
                "run_id": record["id"],
                "prompt": {
                    "system_tokens": record["prompt"]["system_tokens"],
                    "system_sha256": record["prompt"]["system_sha256"],
                    "blocks": record["prompt"]["blocks"],
                    "deviations": record["prompt"]["deviations"],
                    "clean": record["prompt"]["clean"],
                    "estimated_prompt_tokens": record["prompt"]["estimated_prompt_tokens"],
                    "estimation_method": record["prompt"]["estimation_method"],
                },
                "request": record["request"],
                "git": record["git"],
                "mock": record["mock"],
            },
        )

        engine = llm.mock_completion if CONFIG.effective_mock else llm.stream_completion
        result = None
        for event, payload in engine(prepared["body"], prepared["adaptations"]):
            if event == "delta":
                self._sse("delta", {"text": payload})
            elif event == "meta":
                self._sse("meta", payload)
            elif event in ("done", "error"):
                result = payload

        result = result or llm.LLMResult(error="Пустой ответ клиента")

        final = runner.finalize(
            record,
            result,
            check_set_name=body.get("check_set") or profile.checks or "default",
        )

        self._sse(
            "done",
            {
                "run_id": final["id"],
                "response": final["response"],
                "checks": final["checks"],
                "checks_summary": final["checks_summary"],
                "cost": final["cost"],
                "deviations": final["prompt"]["deviations"],
                "baseline_candidate": final.get("baseline_candidate"),
            },
        )

    # --- статика -----------------------------------------------------------

    def _serve_static(self, relative: str) -> None:
        path = (WEB_DIR / relative).resolve()
        try:
            path.relative_to(WEB_DIR)
        except ValueError:
            return self._send_error_json("Запрещено", 403)
        if not path.exists() or not path.is_file():
            return self._send_error_json("Файл не найден", 404)

        content_type, _ = mimetypes.guess_type(str(path))
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def _port_taken(host: str, port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex((host, port)) == 0


def _sandbox_already_running(host: str, port: int) -> bool:
    """Отличает «порт занят нашей же песочницей» от «занят чужой программой»."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/config", timeout=1) as response:
            return "prompt_token_guard" in response.read().decode("utf-8", errors="replace")
    except Exception:
        return False


def _pick_port(host: str, wanted: int) -> int | None:
    """Ищет свободный порт рядом с желаемым."""
    for candidate in range(wanted + 1, wanted + 21):
        if not _port_taken(host, candidate):
            return candidate
    return None


def _requested_port() -> int:
    """Порт из командной строки: --port 8790. Он главнее настройки в .env."""
    for index, argument in enumerate(sys.argv):
        if argument == "--port" and index + 1 < len(sys.argv):
            try:
                return int(sys.argv[index + 1])
            except ValueError:
                break
        if argument.startswith("--port="):
            try:
                return int(argument.split("=", 1)[1])
            except ValueError:
                break
    return CONFIG.port


def main() -> None:
    ensure_dirs()
    port = _requested_port()

    # Занятый порт — самая частая заминка при запуске, и стандартный traceback
    # Python про неё ничего не объясняет. Разбираемся сами и говорим по-русски.
    if _port_taken(CONFIG.host, port):
        if _sandbox_already_running(CONFIG.host, port):
            print()
            print("Песочница уже запущена — второй раз её поднимать не нужно.")
            print(f"Откройте в браузере:  http://{CONFIG.host}:{port}")
            print()
            print("Чтобы остановить ту, что работает: перейдите в её окно терминала")
            print("и нажмите Ctrl+C.")
            if "--no-browser" not in sys.argv:
                try:
                    webbrowser.open(f"http://{CONFIG.host}:{port}")
                except Exception:
                    pass
            return

        free = _pick_port(CONFIG.host, port)
        if free is None:
            print()
            print(f"Порт {port} занят другой программой, и рядом свободных тоже нет.")
            print("Укажите порт вручную:  SANDBOX_PORT=9000 python3 sandbox/app.py")
            return
        print()
        print(f"Порт {port} занят другой программой — беру следующий свободный: {free}.")
        port = free

    server = ThreadingHTTPServer((CONFIG.host, port), Handler)
    url = f"http://{CONFIG.host}:{port}"

    print("=" * 68)
    print("  ПЕСОЧНИЦА ТЕСТИРОВАНИЯ ПРОМПТОВ")
    print("=" * 68)
    print(f"  Адрес:        {url}")
    print(f"  API:          {CONFIG.base_url}")
    print(f"  Ключ:         {'задан' if CONFIG.has_key else 'НЕ ЗАДАН'}")
    if CONFIG.effective_mock:
        print("  Режим:        MOCK — запросы к API не отправляются")
        print("                (создайте sandbox/.env с OPENAI_API_KEY для реальных прогонов)")
    print(f"  Профилей:     {len(profiles.list_profiles())}")
    print("=" * 68)
    print("  Ctrl+C — остановить")
    print()

    if "--no-browser" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
        server.server_close()


if __name__ == "__main__":
    main()
