"""
paths.py — Centralized path resolution for Smart Zones Pro.

Replaces hardcoded `d:\\smart-zones-pro\\...` references everywhere.

BASE_DIR auto-detects:
  - When frozen (PyInstaller .exe): one level above the executable (so that
    `SmartZonesPro.exe` lives in `BASE_DIR\\bin\\` and the data folders stay
    siblings of `bin\\`).
  - When running from source: parent of this file (i.e. the repo root).

Can be overridden via the `SZP_BASE_DIR` environment variable.

All other helpers derive from BASE_DIR and are guaranteed to exist on
first access (directories are created lazily).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _detect_base_dir() -> Path:
    override = os.environ.get("SZP_BASE_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if getattr(sys, "frozen", False):
        # PyInstaller: executable is inside the install dir.
        exe_dir = Path(sys.executable).resolve().parent
        # If running as `…/SmartZonesPro/bin/SmartZonesPro.exe` we want the
        # parent. Otherwise (one-folder build) we use the exe dir itself.
        if exe_dir.name.lower() in {"bin", "app"}:
            return exe_dir.parent
        return exe_dir

    # Running from source: paths.py lives in `<repo>/python_core/paths.py`.
    return Path(__file__).resolve().parent.parent


BASE_DIR: Path = _detect_base_dir()


def _detect_data_dir() -> Path:
    """Каталог для данных, которые приложение ПИШЕТ во время работы.

    В установленной сборке BASE_DIR указывает в Program Files — туда писать
    нельзя (PermissionError [WinError 5]). Поэтому при frozen-сборке пишем в
    пользовательский каталог %LOCALAPPDATA%\\SmartZonesPro. Из исходников —
    в корень репозитория, как раньше. Можно переопределить через SZP_DATA_DIR.
    """
    override = os.environ.get("SZP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if getattr(sys, "frozen", False):
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / "SmartZonesPro"

    return BASE_DIR


# Каталог установки (read-only ресурсы: шаблоны, .env.example, mql/…).
PYTHON_CORE_DIR: Path = BASE_DIR / "python_core"
MQL_DIR: Path = BASE_DIR / "mql"
INSTALLER_DIR: Path = BASE_DIR / "installer"

# Каталог для записи (data_bridge, csv, output, настройки).
DATA_DIR: Path = _detect_data_dir()
DATA_BRIDGE_DIR: Path = DATA_DIR / "data_bridge"
LOCAL_DATA_DIR: Path = DATA_DIR / "data"
OUTPUT_DIR: Path = DATA_DIR / "output"

ZONES_FILE: Path = DATA_BRIDGE_DIR / "zones_output.json"
BROKERS_FILE: Path = DATA_DIR / "brokers.json"
FOOTPRINT_FLAG: Path = DATA_BRIDGE_DIR / "footprint_request.flag"
TRIGGER_FILE: Path = DATA_BRIDGE_DIR / "new_data.flag"

ENV_FILE: Path = DATA_DIR / ".env"

# Windows-only MetaTrader paths (best-effort discovery on other platforms).
APPDATA = Path(os.environ.get("APPDATA", "")) if os.environ.get("APPDATA") else None
MT_TERMINAL_ROOT: Path | None = (
    APPDATA / "MetaQuotes" / "Terminal" if APPDATA else None
)
MT_COMMON_FILES: Path | None = (
    MT_TERMINAL_ROOT / "Common" / "Files" if MT_TERMINAL_ROOT else None
)


def find_mt4_local_files_dir() -> Path | None:
    """Ищет папку MQL4/Files в первом найденном терминале MT4."""
    if MT_TERMINAL_ROOT and MT_TERMINAL_ROOT.exists():
        for sub in MT_TERMINAL_ROOT.iterdir():
            if sub.is_dir():
                files_dir = sub / "MQL4" / "Files"
                if files_dir.exists():
                    return files_dir
    return None


def find_mt_common_files() -> Path | None:
    """Ищет папку Common/Files от MetaTrader 4/5."""
    if MT_COMMON_FILES and MT_COMMON_FILES.exists():
        return MT_COMMON_FILES
    if MT_TERMINAL_ROOT and MT_TERMINAL_ROOT.exists():
        for sub in MT_TERMINAL_ROOT.iterdir():
            if sub.is_dir():
                files_dir = sub / "MQL4" / "Files"
                if files_dir.exists():
                    return files_dir
    return None


def find_all_terminals() -> list[tuple[str, Path]]:
    """Находит ВСЕ установленные терминалы MT4 и MT5 (по хэш-папкам)."""
    terminals: list[tuple[str, Path]] = []
    if MT_TERMINAL_ROOT and MT_TERMINAL_ROOT.exists():
        for sub in MT_TERMINAL_ROOT.iterdir():
            if sub.is_dir():
                if (sub / "MQL4").exists():
                    terminals.append(("MT4", sub))
                if (sub / "MQL5").exists():
                    terminals.append(("MT5", sub))
    return terminals


def ensure_dirs() -> None:
    """Create runtime directories if they don't exist. Safe to call repeatedly."""
    for d in (DATA_BRIDGE_DIR, LOCAL_DATA_DIR, OUTPUT_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            # In read-only deploys we may not be able to create siblings;
            # ignore and let callers handle FileNotFoundError themselves.
            pass


def load_env(override: bool = False) -> None:
    """Load BASE_DIR/.env into os.environ if python-dotenv is available.

    Silent no-op if dotenv isn't installed or the file is missing — config
    falls back to defaults defined in config.py.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=override)


def load_json_file(path: Path, default=None):
    """Безопасно загружает JSON-файл. Возвращает *default* при любой ошибке."""
    if not path.exists():
        return default
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path: Path, data, *, indent: int = 2, default=None,
                   backup: bool = True) -> bool:
    """Атомарно сохраняет JSON-файл и, при возможности, оставляет backup.

    Данные сначала записываются во временный файл в том же каталоге, затем
    заменяют целевой файл одной операцией ``os.replace``. Это не даёт
    MetaTrader прочитать обрезанный JSON во время записи.
    """
    try:
        import json
        import os
        import tempfile

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False,
            ) as tmp:
                json.dump(data, tmp, indent=indent, ensure_ascii=False, default=default)
                tmp.write("\n")
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_name = tmp.name

            if backup and path.exists():
                backup_path = path.with_suffix(path.suffix + ".bak")
                try:
                    backup_path.write_bytes(path.read_bytes())
                except OSError:
                    pass

            os.replace(tmp_name, path)
            tmp_name = None
            return True
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
    except (OSError, TypeError, ValueError):
        return False


ensure_dirs()
load_env()
