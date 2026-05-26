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

PYTHON_CORE_DIR: Path = BASE_DIR / "python_core"
DATA_BRIDGE_DIR: Path = BASE_DIR / "data_bridge"
LOCAL_DATA_DIR: Path = PYTHON_CORE_DIR / "data"
OUTPUT_DIR: Path = BASE_DIR / "output"
MQL_DIR: Path = BASE_DIR / "mql"
INSTALLER_DIR: Path = BASE_DIR / "installer"

ZONES_FILE: Path = DATA_BRIDGE_DIR / "zones_output.json"
BROKERS_FILE: Path = PYTHON_CORE_DIR / "brokers.json"
FOOTPRINT_FLAG: Path = DATA_BRIDGE_DIR / "footprint_request.flag"
TRIGGER_FILE: Path = DATA_BRIDGE_DIR / "new_data.flag"

ENV_FILE: Path = BASE_DIR / ".env"

# Windows-only MetaTrader paths (best-effort discovery on other platforms).
APPDATA = Path(os.environ.get("APPDATA", "")) if os.environ.get("APPDATA") else None
MT_TERMINAL_ROOT: Path | None = (
    APPDATA / "MetaQuotes" / "Terminal" if APPDATA else None
)
MT_COMMON_FILES: Path | None = (
    MT_TERMINAL_ROOT / "Common" / "Files" if MT_TERMINAL_ROOT else None
)


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


ensure_dirs()
load_env()
