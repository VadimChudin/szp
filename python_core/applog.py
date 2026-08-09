"""
applog.py — Логирование в файл для диагностики на ПК клиента.

В windowed-сборке (PyInstaller --windowed) консоли нет, поэтому весь вывод
print() терялся: понять, почему зоны не обновились, было невозможно.
setup() дублирует stdout/stderr в `<DATA_DIR>/logs/smartzonespro.log` и
перехватывает необработанные исключения.
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import TextIO

import paths

LOG_DIR: Path = paths.DATA_DIR / "logs"
LOG_FILE: Path = LOG_DIR / "smartzonespro.log"
MAX_LOG_BYTES = 5 * 1024 * 1024


class _Tee:
    """Пишет в исходный поток (если он есть) и в лог-файл."""

    def __init__(self, stream: TextIO | None, log: TextIO) -> None:
        self._stream = stream
        self._log = log
        self._at_line_start = True

    def write(self, text: str) -> int:
        if self._stream is not None:
            try:
                self._stream.write(text)
            except (OSError, ValueError):
                pass
        try:
            for chunk in text.splitlines(keepends=True):
                if self._at_line_start and chunk.strip():
                    self._log.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ")
                self._log.write(chunk)
                self._at_line_start = chunk.endswith("\n")
            self._log.flush()
        except (OSError, ValueError):
            pass
        return len(text)

    def flush(self) -> None:
        for target in (self._stream, self._log):
            if target is not None:
                try:
                    target.flush()
                except (OSError, ValueError):
                    pass

    def isatty(self) -> bool:
        return bool(self._stream is not None and self._stream.isatty())


_configured = False


def setup() -> Path | None:
    """Включает логирование в файл. Безопасно вызывать повторно."""
    global _configured
    if _configured:
        return LOG_FILE

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
            LOG_FILE.replace(LOG_FILE.with_suffix(".log.old"))
        log = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"[applog] WARN: cannot open log file: {e}")
        return None

    sys.stdout = _Tee(sys.__stdout__, log)
    sys.stderr = _Tee(sys.__stderr__, log)

    def _hook(exc_type, exc, tb) -> None:
        print("[applog] UNHANDLED EXCEPTION:")
        print("".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = _hook
    _configured = True
    print(f"\n{'#' * 60}\n[applog] Session started, log: {LOG_FILE}")
    return LOG_FILE
