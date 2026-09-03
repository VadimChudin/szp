"""
downloader.py — Скачивание файла модели с докачкой.

Установщик остаётся 48 МБ, а модель (от 1.4 до 20 ГБ) приезжает отдельно при
первом включении ИИ. На медленном канале это десятки минут, поэтому:
  • докачка с места обрыва через HTTP Range — повторно тянуть 9 ГБ недопустимо;
  • прогресс виден в интерфейсе, иначе пользователь решит, что всё зависло;
  • файл собирается в .part и переименовывается только после проверки размера,
    чтобы недокачанный файл никогда не выглядел готовым.

Качается с Hugging Face, репозитории Qwen открыты (Apache 2.0), токен не нужен.
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

from ai import model_catalog, runtime

CHUNK = 1024 * 1024
USER_AGENT = "SmartZonesPro/6.0"


@dataclass
class Progress:
    state: str = "idle"        # idle | downloading | done | error
    downloaded: int = 0
    total: int = 0
    speed_mb_s: float = 0.0
    message: str = ""

    @property
    def percent(self) -> float:
        return (self.downloaded / self.total * 100.0) if self.total else 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["percent"] = round(self.percent, 1)
        data["downloaded_gib"] = round(self.downloaded / model_catalog.GIB, 2)
        data["total_gib"] = round(self.total / model_catalog.GIB, 2)
        return data


_progress = Progress()
_thread: threading.Thread | None = None
_cancel = threading.Event()


def progress() -> Progress:
    return _progress


def busy() -> bool:
    return _thread is not None and _thread.is_alive()


def cancel() -> None:
    _cancel.set()


def _download(spec: model_catalog.ModelSpec) -> None:
    global _progress
    target = runtime.model_path(spec)
    part = target.with_suffix(target.suffix + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)

    have = part.stat().st_size if part.exists() else 0
    _progress = Progress(state="downloading", downloaded=have,
                         total=spec.download_bytes,
                         message=f"Скачивание {spec.title}")

    headers = {"User-Agent": USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"

    request = urllib.request.Request(spec.url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            # Сервер проигнорировал Range — начинаем файл заново.
            if have and response.status != 206:
                have = 0
                part.unlink(missing_ok=True)

            declared = response.headers.get("Content-Length")
            if declared:
                total = int(declared) + have
                _progress.total = max(total, spec.download_bytes)

            mode = "ab" if have else "wb"
            started = time.time()
            since = have
            with open(part, mode) as handle:
                while not _cancel.is_set():
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    have += len(chunk)
                    _progress.downloaded = have
                    elapsed = time.time() - started
                    if elapsed > 0:
                        _progress.speed_mb_s = round(
                            (have - since) / elapsed / (1024 * 1024), 1)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        _progress.state = "error"
        _progress.message = (f"Не удалось скачать модель: {exc}. "
                             f"Нажмите ещё раз — загрузка продолжится "
                             f"с места обрыва.")
        return

    if _cancel.is_set():
        _progress.state = "idle"
        _progress.message = "Загрузка остановлена"
        return

    if have < int(spec.download_bytes * 0.95):
        _progress.state = "error"
        _progress.message = ("Файл скачан не полностью — нажмите ещё раз "
                             "для докачки")
        return

    try:
        part.replace(target)
    except OSError as exc:
        _progress.state = "error"
        _progress.message = f"Не удалось сохранить модель: {exc}"
        return

    _progress.state = "done"
    _progress.message = f"{spec.title} готова к работе"


def start(spec: model_catalog.ModelSpec) -> bool:
    """Запускает загрузку в фоне. False — если уже качается."""
    global _thread
    if busy():
        return False
    if runtime.model_ready(spec):
        globals()["_progress"] = Progress(
            state="done", downloaded=spec.download_bytes,
            total=spec.download_bytes,
            message=f"{spec.title} уже скачана")
        return True
    _cancel.clear()
    _thread = threading.Thread(target=_download, args=(spec,), daemon=True)
    _thread.start()
    return True
