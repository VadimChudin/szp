"""Проверяет полосу отображения зон: 3+3, ближняя 200-300 пипсов, шаг 200-300.

Регресс, который эти тесты закрывают: отбор шёл только по score, поэтому уровни
уезжали из ренжа и слипались в пучок (CLUSTER_TOLERANCE был шире шага).
"""
from __future__ import annotations

import pandas as pd
import pytest

import active_zones
import config
from zone_detector import Zone


PRICE = 3300.00


def _h4_frame(price: float = PRICE) -> dict:
    """H4 без касаний зон, чтобы инвалидация не мешала проверке отбора."""
    rows = [{
        "time": pd.Timestamp("2026-08-28 00:00:00") + pd.Timedelta(hours=4 * i),
        "open": price, "high": price + 0.05, "low": price - 0.05, "close": price,
    } for i in range(3)]
    return {"H4": pd.DataFrame(rows), "H1": pd.DataFrame(rows)}


def _candidates() -> list[Zone]:
    """Плотная сетка кандидатов по обе стороны от цены, шаг $0.25."""
    zones = []
    for step in range(1, 60):
        for sign in (1, -1):
            offset = 0.25 * step * sign
            zones.append(Zone(price=round(PRICE + offset, 2),
                              width=config.ZONE_WIDTH,
                              score=config.MIN_ZONE_SCORE + (step % 5),
                              sources=[config.PRIMARY_TIMEFRAME]))
    return zones


def _select(tmp_path) -> list[Zone]:
    return active_zones.update_snapshot(
        _candidates(), _h4_frame(),
        path=tmp_path / "snapshot.json",
        event_path=tmp_path / "events.jsonl",
    )


def test_band_constants_are_consistent():
    """Склейка и ширина зоны обязаны быть мельче шага, иначе набор схлопнется."""
    assert config.ZONE_GAP_MIN == pytest.approx(config.ZONE_GAP_MIN_PIPS * config.PIP_SIZE)
    assert config.CLUSTER_TOLERANCE < config.ZONE_GAP_MIN
    assert config.ZONE_WIDTH_MAX * 2 < config.ZONE_GAP_MIN


def test_three_zones_each_side(tmp_path):
    selected = _select(tmp_path)
    above = [z for z in selected if z.price > PRICE]
    below = [z for z in selected if z.price < PRICE]
    assert len(above) == config.ZONES_PER_SIDE
    assert len(below) == config.ZONES_PER_SIDE
    assert len(selected) == config.MAX_ZONES_ON_CHART


def test_nearest_zone_sits_in_requested_band(tmp_path):
    selected = _select(tmp_path)
    tolerance = 1.0 + config.ZONE_BAND_TOLERANCE
    for above in (True, False):
        side = [z for z in selected if (z.price > PRICE) == above]
        nearest = min(abs(z.price - PRICE) for z in side)
        assert nearest >= config.ZONE_NEAREST_MIN * (1.0 - config.ZONE_BAND_TOLERANCE)
        assert nearest <= config.ZONE_NEAREST_MAX * tolerance


def test_gap_between_zones_in_requested_band(tmp_path):
    selected = _select(tmp_path)
    for above in (True, False):
        side = sorted((abs(z.price - PRICE) for z in selected
                       if (z.price > PRICE) == above))
        gaps = [b - a for a, b in zip(side, side[1:])]
        assert gaps, "на стороне должно быть больше одной зоны"
        for gap in gaps:
            assert gap >= config.ZONE_GAP_MIN * (1.0 - config.ZONE_BAND_TOLERANCE)
            assert gap <= config.ZONE_GAP_MAX * (1.0 + config.ZONE_BAND_TOLERANCE)


def test_zone_outside_band_is_dropped(tmp_path):
    """Уровень далеко за горизонтом не должен попадать на график."""
    far = Zone(price=PRICE + config.ZONE_BAND_OUTER_MAX * 5,
               width=config.ZONE_WIDTH, score=99,
               sources=[config.PRIMARY_TIMEFRAME])
    selected = active_zones.update_snapshot(
        _candidates() + [far], _h4_frame(),
        path=tmp_path / "snapshot.json",
        event_path=tmp_path / "events.jsonl",
    )
    assert all(z.price != far.price for z in selected), "зона вне полосы попала на график"


def test_no_invented_levels_by_default():
    """«Только зоны»: круглые уровни и боксы крупных игроков выключены."""
    assert config.PROJECT_ROUND_LEVELS is False
    assert config.ACCUMULATION_ENABLED is False
