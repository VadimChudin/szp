"""Отбор зон: ближайшие сильные зоны в диапазоне скопа от цены.

Требование: показывать реальные зоны недалеко от цены (в т.ч. вплотную),
без квоты по сторонам; дальние за скопом — не показывать.
"""
from __future__ import annotations

import pandas as pd

import active_zones
import pytest

import config
from zone_detector import Zone


PRICE = 4000.00

@pytest.fixture(autouse=True)
def _wide_corridor(monkeypatch, request):
    """Коридор расширяем локально, иначе синтетические уровни отсекаются по скопу."""
    if request.node.name == "test_range_config_is_sane":
        return          # этот тест проверяет сами значения конфига, не слоты
    monkeypatch.setattr(config, "MAX_ZONE_DISTANCE", 200.0)
    monkeypatch.setattr(config, "ZONE_WINDOW_ATR", 0.0)
    monkeypatch.setattr(config, "ZONE_SCOPE_PIPS", 0.0)



def _h4_frame(price: float = PRICE) -> dict:
    """H4/H1 без касаний зон, чтобы инвалидация не мешала проверке отбора."""
    rows = [{
        "time": pd.Timestamp("2026-08-28 00:00:00") + pd.Timedelta(hours=4 * i),
        "open": price, "high": price + 0.05, "low": price - 0.05, "close": price,
    } for i in range(3)]
    return {"H4": pd.DataFrame(rows), "H1": pd.DataFrame(rows)}


def _zone(offset: float, score: int = 15) -> Zone:
    return Zone(price=round(PRICE + offset, 2), width=config.ZONE_WIDTH,
                score=score, sources=[config.PRIMARY_TIMEFRAME])


def _select(candidates, tmp_path):
    return active_zones.update_snapshot(
        candidates, _h4_frame(),
        path=tmp_path / "snapshot.json",
        event_path=tmp_path / "events.jsonl",
    )


def test_range_config_is_sane():
    # 0 означает «коридора нет» (поведение старой версии) — это валидно.
    assert config.MAX_ZONE_DISTANCE >= 0
    assert config.MAX_ZONE_DISTANCE == config.MAX_ZONE_DISTANCE_PIPS * config.PIP_SIZE
    assert config.ZONE_WINDOW_ATR >= 0
    assert config.MAX_ZONES_ON_CHART >= 1


def test_zone_close_to_price_is_shown(tmp_path):
    """Клиентский кейс 4786: зона вплотную к цене должна показываться.

    $8 от цены — ближе старого порога «лестницы» (~$17.5), который её ронял.
    Разносим стороны так, чтобы они не попали в один кластер (CLUSTER_TOLERANCE).
    """
    near_up = _zone(+8.0)
    near_down = _zone(-8.0)
    selected = _select([near_up, near_down], tmp_path)
    prices = [round(z.price, 2) for z in selected]
    assert round(PRICE + 8.0, 2) in prices
    assert round(PRICE - 8.0, 2) in prices


def test_far_zone_is_dropped(tmp_path):
    far = _zone(config.MAX_ZONE_DISTANCE + 50.0, score=99)  # далеко за диапазоном
    near = _zone(+10.0)
    selected = _select([far, near], tmp_path)
    assert all(z.price != far.price for z in selected)
    assert any(round(z.price, 2) == round(PRICE + 10.0, 2) for z in selected)


def test_nearest_zones_selected_up_to_total_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_ZONES_ON_CHART", 6)
    ups = [_zone(+d) for d in (10, 30, 50, 70)]
    downs = [_zone(-d) for d in (10, 30, 50, 70)]
    selected = _select(ups + downs, tmp_path)
    distances = sorted(abs(z.price - PRICE) for z in selected)
    assert len(selected) == 6
    assert distances == [10, 10, 30, 30, 50, 50]


def test_no_invented_levels_by_default():
    assert config.PROJECT_ROUND_LEVELS is False
    assert config.ACCUMULATION_ENABLED is False
