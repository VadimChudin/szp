"""version.py — версия сборки, видимая пользователю.

Номер пишется в build_version.txt на этапе сборки (CI подставляет тег релиза).
Без этого установщик и приложение выглядели одинаково у всех версий, и понять,
какая сборка реально стоит у клиента, было невозможно.
"""
from __future__ import annotations

import sys
from pathlib import Path

FALLBACK = "dev"


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", None)
        return Path(bundle) if bundle else Path(sys.executable).parent
    return Path(__file__).parent


def app_version() -> str:
    """Версия сборки, например '1.5'. 'dev' — запуск из исходников."""
    try:
        text = (_base_dir() / "build_version.txt").read_text(encoding="utf-8")
    except OSError:
        return FALLBACK
    version = text.strip()
    return version or FALLBACK
