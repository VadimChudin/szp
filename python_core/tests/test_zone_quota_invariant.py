"""Инвариант: квоты «3 сверху + 3 снизу» нет ни в одном режиме отбора.

Клиентское требование v6: на графике действует один общий лимит
MAX_ZONES_ON_CHART, скоп задаёт видимую область. Вся квота может уйти на одну
сторону, если реальные уровни есть только сверху или только снизу.

Эти тесты закрывают возврат старого поведения — как через код, так и через .env.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import active_zones
import config
from zone_detector import Zone, balance_around_price

ROOT = Path(__file__).resolve().parents[2]
PRICE = 4000.0


def _zone(offset: float, score: int = 15) -> Zone:
    return Zone(price=round(PRICE + offset, 2), width=1.0, score=score, sources=["H4"])


def _h4(price: float = PRICE) -> dict:
    rows = [{
        "time": pd.Timestamp("2026-08-28 00:00:00") + pd.Timedelta(hours=4 * i),
        "open": price, "high": price + 0.05, "low": price - 0.05, "close": price,
    } for i in range(3)]
    return {"H4": pd.DataFrame(rows), "H1": pd.DataFrame(rows)}


# ── Конфигурация ────────────────────────────────────────────────────────────
def test_config_has_no_per_side_quota_knobs():
    """ZONES_PER_SIDE / MIN_ZONES_PER_SIDE удалены целиком."""
    assert not hasattr(config, "ZONES_PER_SIDE")
    assert not hasattr(config, "MIN_ZONES_PER_SIDE")


def test_chart_limit_is_configurable_range():
    assert 1 <= config.MAX_ZONES_ON_CHART <= 500


def test_scope_is_free_positive_number():
    """Скоп — любое положительное число, верхнего потолка нет."""
    assert config.ZONE_SCOPE_PIPS >= 0
    if config.ZONE_SCOPE_PIPS > 0:
        expected_half = config.ZONE_SCOPE_PIPS / 2.0
        assert config.MAX_ZONE_DISTANCE_PIPS == pytest.approx(expected_half) \
            or config.MAX_ZONE_DISTANCE_PIPS > 0


def test_no_quota_arithmetic_left_in_sources():
    """В коде отбора не осталось делений лимита по сторонам (limit // 2)."""
    for relative in ("python_core/zone_detector.py", "python_core/active_zones.py",
                     "python_core/persistent_zones.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "limit // 2" not in source, f"{relative}: вернулась квота по сторонам"
        assert "MIN_ZONES_PER_SIDE" not in source
        assert "ZONES_PER_SIDE" not in source


# ── H4-снапшот (USE_ZONE_LADDER=True) ──────────────────────────────────────
def test_snapshot_gives_whole_limit_to_one_side(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_ZONES_ON_CHART", 6)
    monkeypatch.setattr(config, "MAX_ZONE_DISTANCE", 200.0)
    monkeypatch.setattr(config, "ZONE_WINDOW_ATR", 0.0)
    monkeypatch.setattr(config, "ZONE_SCOPE_PIPS", 0.0)

    candidates = [_zone(+d, 20 - i) for i, d in enumerate((10, 20, 30, 40, 50, 60))]
    result = active_zones.update_snapshot(
        candidates, _h4(),
        path=tmp_path / "snapshot.json",
        event_path=tmp_path / "events.jsonl",
    )

    assert len(result) == 6
    assert all(z.price > PRICE for z in result), "снапшот всё ещё требует зоны снизу"


# ── Legacy-путь (по умолчанию) ─────────────────────────────────────────────
def test_detector_balance_gives_whole_limit_to_one_side(monkeypatch):
    monkeypatch.setattr(config, "MAX_ZONES_ON_CHART", 4)
    strong = [_zone(+d, 20 - i) for i, d in enumerate((10, 30, 50, 70))]

    selected = balance_around_price(strong, [], price=PRICE)

    assert len(selected) == 4
    assert all(z.price > PRICE for z in selected)


def test_detector_does_not_invent_levels_to_fill_limit(monkeypatch):
    """Если реальных зон меньше лимита — рисуем сколько есть."""
    monkeypatch.setattr(config, "MAX_ZONES_ON_CHART", 6)
    strong = [_zone(+10.0, 20)]

    selected = balance_around_price(strong, [], price=PRICE)

    assert len(selected) == 1
    assert config.PROJECT_ROUND_LEVELS is False


# ── Терминал ───────────────────────────────────────────────────────────────
def test_terminal_cap_matches_python_limit_semantics():
    """Индикаторы читают лимит из входа, а не из жёсткой шестёрки."""
    for relative in ("mql/MT4/Indicators/StrongZones.mq4",
                     "mql/MT5/Indicators/StrongZones.mq5"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "currentZoneCount < 6" not in source
        assert "currentZoneCount < ZoneDrawCap()" in source
