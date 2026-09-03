"""
runtime.py — Локальный llama-server: запуск, здоровье, запросы.

Сервер поставляется в составе продукта (llama.cpp, лицензия MIT), поэтому
клиенту не нужно ставить Ollama или что-то ещё. Файл модели скачивается
отдельно, чтобы установщик остался на 48 МБ.

Про окна консоли
----------------
llama-server.exe — консольное приложение. Запуск его напрямую из GUI открыл бы
чёрное окно, а с перезапусками их набегает много. Здесь процесс поднимается
через proc_util (CREATE_NO_WINDOW + скрытый STARTUPINFO), вывод уходит в файл
журнала, а не в консоль. Ни одного окна не появляется.

Жёсткая схема ответа
--------------------
Модель отвечает под GBNF-грамматикой: набор допустимых строк задан на уровне
декодера. Придумать свою цену зоны она физически не может — в грамматике нет
такого поля. Это надёжнее просьбы «отвечай только JSON» в промпте.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import proc_util
from ai import model_catalog

DEFAULT_PORT = 8749
HOST = "127.0.0.1"
STARTUP_TIMEOUT = 180.0
REQUEST_TIMEOUT = 180.0


def base_dir() -> Path:
    """Каталог данных ИИ: модели, журнал сервера."""
    override = os.environ.get("SZP_AI_DIR")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "SmartZonesPro" / "ai"


def models_dir() -> Path:
    return base_dir() / "models"


def model_path(spec: model_catalog.ModelSpec) -> Path:
    return models_dir() / spec.filename


def model_ready(spec: model_catalog.ModelSpec) -> bool:
    """Файл есть и весит правдоподобно (не обрезанная докачка)."""
    path = model_path(spec)
    if not path.exists():
        return False
    try:
        return path.stat().st_size >= int(spec.download_bytes * 0.95)
    except OSError:
        return False


def find_server_binary() -> Path | None:
    """llama-server рядом с exe (сборка) или в каталоге разработчика."""
    override = os.environ.get("SZP_LLAMA_SERVER")
    if override and Path(override).exists():
        return Path(override)

    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).parent)
        roots.append(Path(getattr(sys, "_MEIPASS", ".")))
    roots.append(Path(__file__).resolve().parent.parent / "llama")
    roots.append(base_dir() / "llama")

    for root in roots:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((HOST, port)) != 0


def _pick_port() -> int:
    for port in range(DEFAULT_PORT, DEFAULT_PORT + 20):
        if _port_free(port):
            return port
    return DEFAULT_PORT


@dataclass
class Server:
    process: object | None = None
    port: int = DEFAULT_PORT
    spec: model_catalog.ModelSpec | None = None

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def alive(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None


_server = Server()


def _http_post(url: str, payload: dict, timeout: float) -> dict | None:
    import urllib.error
    import urllib.request
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _healthy(port: int, timeout: float = 3.0) -> bool:
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://{HOST}:{port}/health", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def start(spec: model_catalog.ModelSpec, *, gpu_layers: int = -1,
          context: int | None = None) -> bool:
    """Поднимает сервер, если он ещё не поднят. Окно консоли не появляется."""
    global _server

    if _server.alive() and _healthy(_server.port):
        return True

    binary = find_server_binary()
    if binary is None:
        print("[ai] llama-server не найден — ИИ недоступен")
        return False
    if not model_ready(spec):
        print(f"[ai] модель не скачана: {model_path(spec).name}")
        return False

    port = _pick_port()
    log_path = base_dir() / "llama-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        str(binary),
        "-m", str(model_path(spec)),
        "--host", HOST,
        "--port", str(port),
        "-c", str(context or spec.context),
        "-ngl", str(gpu_layers),
        "--no-webui",
    ]

    try:
        # Журнал вместо консоли: у GUI-процесса консоли нет, а окно нам
        # категорически не нужно.
        log_file = open(log_path, "ab", buffering=0)
        process = proc_util.popen(command, detached=True, capture=False,
                                  stdout=log_file, stderr=log_file)
    except OSError as exc:
        print(f"[ai] не удалось запустить llama-server: {exc}")
        return False

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if process.poll() is not None:
            print(f"[ai] llama-server завершился на старте, "
                  f"подробности в {log_path}")
            return False
        if _healthy(port):
            _server = Server(process=process, port=port, spec=spec)
            print(f"[ai] модель поднята: {spec.title} на порту {port}")
            return True
        time.sleep(1.0)

    print("[ai] llama-server не ответил за отведённое время")
    stop_process(process)
    return False


def stop_process(process) -> None:
    try:
        process.terminate()
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def stop() -> None:
    global _server
    if _server.process is not None:
        stop_process(_server.process)
    _server = Server()


def ready() -> bool:
    return _server.alive() and _healthy(_server.port)


def complete(prompt: str, *, grammar: str | None = None,
             max_tokens: int = 512, temperature: float = 0.2,
             timeout: float = REQUEST_TIMEOUT) -> str | None:
    """Один запрос к модели. None при любой неудаче — вызывающий работает без ИИ."""
    if not ready():
        return None
    payload: dict = {
        "prompt": prompt,
        "n_predict": max_tokens,
        "temperature": temperature,
        "cache_prompt": True,
        "stream": False,
    }
    if grammar:
        payload["grammar"] = grammar
    result = _http_post(f"{_server.url}/completion", payload, timeout)
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    return content.strip() if isinstance(content, str) else None
