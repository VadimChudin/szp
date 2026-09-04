"""
Страж против окон консоли.

Жалоба клиента: при работе софта поверх графика выскакивали десятки чёрных
окон. Причина — subprocess.Popen из GUI-сборки PyInstaller: у оконного
процесса нет консоли, и Windows создаёт новую на каждый запуск. Патчер
терминалов вызывает metaeditor для КАЖДОГО найденного терминала, отсюда и
«2000 окон».

Тест следит, чтобы regression не вернулся: весь запуск процессов идёт через
proc_util, который гасит окно двумя способами сразу.
"""
import re
import subprocess
from pathlib import Path


import proc_util

CORE = Path(__file__).resolve().parent.parent

# Файлы, которым можно упоминать subprocess напрямую.
ALLOWED = {"proc_util.py"}

# Тесты и сам страж не участвуют.
SKIP_DIRS = {"tests", "__pycache__", "duka_cache"}


def _sources():
    for path in CORE.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.relative_to(CORE).parts):
            continue
        if path.name in ALLOWED:
            continue
        yield path


class TestNoDirectSubprocess:
    def test_no_popen_outside_proc_util(self):
        """Прямой Popen открывает чёрное окно — только через proc_util."""
        offenders = []
        pattern = re.compile(r"subprocess\.(Popen|run|call|check_output)")
        for path in _sources():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number, line in enumerate(text.splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    continue
                if pattern.search(line):
                    offenders.append(f"{path.name}:{number}")
        assert not offenders, (
            "Запуск процессов минуя proc_util откроет окно консоли: "
            + ", ".join(offenders))

    def test_known_launchers_use_proc_util(self):
        """Места, где раньше выскакивали окна, должны звать proc_util."""
        for name in ("app_entry.py", "bridge_server.py",
                     "smart_zones_tray.py", "sync_zones_to_mt4.py"):
            text = (CORE / name).read_text(encoding="utf-8")
            assert "proc_util" in text, f"{name} запускает процессы напрямую"


class TestHiddenFlags:
    def test_windows_flags_include_create_no_window(self, monkeypatch):
        monkeypatch.setattr(proc_util, "IS_WINDOWS", True)
        monkeypatch.setattr(subprocess, "STARTUPINFO",
                            lambda: type("S", (), {"dwFlags": 0,
                                                   "wShowWindow": None})(),
                            raising=False)
        monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 1,
                            raising=False)
        kwargs = proc_util.hidden_kwargs()
        assert kwargs["creationflags"] & proc_util.CREATE_NO_WINDOW
        # Второй барьер: окно скрыто и через STARTUPINFO.
        assert kwargs["startupinfo"].wShowWindow == 0

    def test_detached_adds_process_group(self, monkeypatch):
        monkeypatch.setattr(proc_util, "IS_WINDOWS", True)
        monkeypatch.setattr(subprocess, "STARTUPINFO",
                            lambda: type("S", (), {"dwFlags": 0,
                                                   "wShowWindow": None})(),
                            raising=False)
        monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 1,
                            raising=False)
        kwargs = proc_util.hidden_kwargs(detached=True)
        assert kwargs["creationflags"] & proc_util.CREATE_NEW_PROCESS_GROUP

    def test_no_flags_on_other_platforms(self, monkeypatch):
        monkeypatch.setattr(proc_util, "IS_WINDOWS", False)
        assert proc_util.hidden_kwargs() == {}


class TestActualLaunch:
    def test_popen_swallows_output_by_default(self):
        """Запись в отсутствующую консоль роняет дочерний процесс."""
        process = proc_util.popen(["python3", "-c", "print('hi')"])
        assert process.wait(timeout=30) == 0
        assert process.stdout is None

    def test_run_captures_text(self):
        result = proc_util.run(["python3", "-c", "print('ok')"], timeout=30)
        assert result.returncode == 0
        assert result.stdout.strip() == "ok"

    def test_capture_mode_gives_pipes(self):
        process = proc_util.popen(["python3", "-c", "print('piped')"],
                                  capture=True)
        out, _ = process.communicate(timeout=30)
        assert b"piped" in out
