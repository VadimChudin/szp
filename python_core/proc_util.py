"""
proc_util.py — Запуск дочерних процессов без окон консоли.

Проблема: GUI-сборка PyInstaller (windowed) не имеет родительской консоли.
На каждый `subprocess.Popen` Windows создаёт НОВОЕ чёрное окно консоли, и при
работе софта их набегали десятки: футпринт, настройки, патчер терминалов,
llama-server. Пользователь видел мусор поверх графика.

Решение: единая точка запуска. Гасим окно двумя способами сразу —
CREATE_NO_WINDOW в creationflags и STARTF_USESHOWWINDOW/SW_HIDE в STARTUPINFO.
По отдельности каждый способ на части конфигураций Windows даёт осечку.

Дополнительно stdout/stderr по умолчанию уходят в DEVNULL: у процесса без
консоли запись в несуществующий дескриптор роняет дочерний процесс.

Правило для всего проекта: НИКОГДА не вызывать subprocess напрямую,
только через proc_util.popen / proc_util.run. Тест
test_no_console_windows.py следит за этим.
"""
from __future__ import annotations

import subprocess
import sys

# Windows creation flags (значения из winbase.h; на других ОС не применяются).
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

IS_WINDOWS = sys.platform == "win32"


def _startupinfo():
    """STARTUPINFO со скрытым окном. None на не-Windows."""
    if not IS_WINDOWS:
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0  # SW_HIDE
    return info


def hidden_kwargs(detached: bool = False) -> dict:
    """Аргументы для subprocess, гасящие окно консоли.

    detached=True — процесс переживает закрытие родителя (нужно для
    llama-server, чтобы он не умирал вместе с окном футпринта).
    """
    if not IS_WINDOWS:
        return {}
    flags = CREATE_NO_WINDOW
    if detached:
        flags |= CREATE_NEW_PROCESS_GROUP
    return {"creationflags": flags, "startupinfo": _startupinfo()}


def popen(cmd, *, detached: bool = False, capture: bool = False, **kwargs):
    """subprocess.Popen без окна консоли.

    capture=False (по умолчанию) — вывод в DEVNULL: у GUI-процесса нет
    консоли, и дочерний процесс упадёт при первой же записи в stdout.
    """
    kwargs.update(hidden_kwargs(detached=detached))
    if not capture:
        kwargs.setdefault("stdout", subprocess.DEVNULL)
        kwargs.setdefault("stderr", subprocess.DEVNULL)
    else:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.Popen(cmd, **kwargs)


def run(cmd, *, timeout: float | None = None, **kwargs):
    """subprocess.run без окна консоли. Вывод захватывается как текст."""
    kwargs.update(hidden_kwargs())
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run(cmd, timeout=timeout, **kwargs)
