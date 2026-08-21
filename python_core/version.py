"""version.py — версия сборки, видимая пользователю.

Номер пишется в build_version.txt на этапе сборки (CI подставляет тег релиза).
Без этого установщик и приложение выглядели одинаково у всех версий, и понять,
какая сборка реально стоит у клиента, было невозможно.
"""
from __future__ import annotations

import sys
from pathlib import Path

FALLBACK = "dev"
DEFAULT_CHANNEL = "Experimental"


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", None)
        return Path(bundle) if bundle else Path(sys.executable).parent
    return Path(__file__).parent


def _build_label() -> str:
    try:
        return (_base_dir() / "build_version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def app_version() -> str:
    """Версия сборки, например ``Experimental-0.0.0.58-deadbee``."""
    return _build_label() or FALLBACK


def app_channel() -> str:
    """Return the installation channel encoded by CI in ``build_version.txt``.

    A channel-specific payload prevents an Experimental indicator from reading
    a stale flat ``zones_output.json`` written by an older Stable installation.
    """
    label = _build_label()
    if label.startswith("Stable-"):
        return "Stable"
    if label.startswith("Experimental-"):
        return "Experimental"
    return DEFAULT_CHANNEL
