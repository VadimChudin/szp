"""`.env.example` не должен менять поведение относительно дефолтов config.py.

Регрессия: пример содержал DATA_SOURCE=mt5 при дефолте dukascopy и
TEST_INVALIDATES_ZONE=true при дефолте false. Клиент копировал пример в .env и
получал другой источник данных и другой жизненный цикл зон, чем документировано.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = ROOT / ".env.example"
CONFIG = ROOT / "python_core" / "config.py"

_ENV_CALL = re.compile(
    r'_env_(?:int|float|bool|str)\(\s*"([A-Z0-9_]+)"\s*,\s*([^)]+?)\s*\)'
)


def _example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _config_defaults() -> dict[str, str]:
    source = CONFIG.read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in _ENV_CALL.finditer(source)}


def _equivalent(example: str, default: str) -> bool:
    default = default.strip().strip('"').strip("'")
    try:
        return abs(float(example) - float(default)) < 1e-9
    except ValueError:
        pass
    truthy = {"1", "true", "yes", "on"}
    falsy = {"0", "false", "no", "off"}
    low_example, low_default = example.lower(), default.lower()
    if low_example in truthy and low_default in truthy | {"true"}:
        return True
    if low_example in falsy and low_default in falsy | {"false"}:
        return True
    return low_example == low_default


def test_example_values_match_config_defaults():
    defaults = _config_defaults()
    drift = [
        f"{key}: .env.example={value!r}, config default={defaults[key]!r}"
        for key, value in _example_values().items()
        if key in defaults and not _equivalent(value, defaults[key])
    ]
    assert not drift, "пример расходится с дефолтами:\n" + "\n".join(drift)


def test_example_has_no_keys_config_never_reads():
    source = CONFIG.read_text(encoding="utf-8")
    defaults = _config_defaults()
    dead = [
        key for key in _example_values()
        if key not in defaults and not re.search(rf"\b{key}\b", source)
    ]
    assert not dead, f"мёртвые ключи в .env.example: {dead}"


def test_example_does_not_duplicate_scope_knob():
    """MAX_ZONE_DISTANCE_PIPS считается как половина скопа — второй ручки нет."""
    assert "MAX_ZONE_DISTANCE_PIPS" not in _example_values()


def test_example_documents_free_scope_without_per_side_knob():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "ZONE_SCOPE_PIPS" in text
    # Ручки квоты по сторонам в примере быть не должно: её нет и в config.
    assert "ZONES_PER_SIDE" not in _example_values()
    assert "ZONES_PER_SIDE=" not in text
