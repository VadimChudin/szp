"""Тесты нормализации зон по эталону Dukascopy (broker_normalize)."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config  # noqa: E402
from broker_normalize import (  # noqa: E402
    compute_offset, current_price, shift_zone, validate_zones,
)
from zone_detector import Zone  # noqa: E402


def z(price, score=15):
    return Zone(price=price, width=config.ZONE_WIDTH, score=score, sources=["H4"])


def test_validate_keeps_matching_keeps_drops_nonmatching():
    broker = [z(4000.0), z(4100.0), z(3900.0)]
    canonical = [z(4001.0), z(4102.0)]  # tolerance 5 -> 4000,4100 match; 3900 нет
    kept = validate_zones(broker, canonical, tolerance=5.0)
    prices = [round(x.price, 2) for x in kept]
    assert 4000.0 in prices
    assert 4100.0 in prices
    assert 3900.0 not in prices


def test_validate_empty_canonical_keeps_all():
    broker = [z(4000.0), z(4100.0)]
    kept = validate_zones(broker, [], tolerance=5.0)
    assert len(kept) == 2  # best-effort: эталона нет — не режем


def test_compute_offset():
    assert compute_offset(4002.0, 4000.0) == pytest.approx(2.0)
    assert compute_offset(None, 4000.0) == 0.0
    assert compute_offset(4000.0, None) == 0.0
    assert compute_offset(4000.0, 0.0) == 0.0


def test_shift_zone_applies_offset():
    zone = z(4000.0)
    shift_zone(zone, 2.0)
    assert zone.price == pytest.approx(4002.0)
    # top/bottom — производные свойства: пересчитались от нового price
    assert zone.top == pytest.approx(zone.price + zone.width)
    assert zone.bottom == pytest.approx(zone.price - zone.width)


def test_shift_zone_zero_offset_noop():
    zone = z(4000.0)
    before = zone.price
    shift_zone(zone, 0.0)
    assert zone.price == before


def test_current_price():
    df = pd.DataFrame({"close": [10.0, 20.0, 30.0]})
    assert current_price({"H1": df}) == 30.0
    assert current_price({}) is None


def test_config_defaults():
    assert config.VALIDATION_MODE in ("validate", "canonical", "off")
    assert config.VALIDATION_TOLERANCE > 0
    assert isinstance(config.BROKER_OFFSET_ENABLED, bool)
