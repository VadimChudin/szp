import pandas as pd

from sl_model import possible_stop
from zone_detector import Zone


def frame():
    return pd.DataFrame([
        ("2024-01-01", 100, 104, 96, 101),
        ("2024-01-02", 101, 105, 97, 103),
        ("2024-01-03", 103, 106, 98, 104),
        ("2024-01-04", 104, 107, 99, 105),
        ("2024-01-05", 105, 108, 100, 106),
    ], columns=["time", "open", "high", "low", "close"])


def test_support_stop_is_below_zone():
    result = possible_stop(Zone(price=100, width=1, score=12, touch_count=3), frame(), current_price=106)
    assert result.side == "BELOW_SUPPORT"
    assert result.price < 99
    assert 0 < result.probability <= 92
    assert result.atr > 0


def test_resistance_stop_is_above_zone():
    result = possible_stop(Zone(price=110, width=1, score=8), frame(), current_price=106)
    assert result.side == "ABOVE_RESISTANCE"
    assert result.price > 111
    assert result.rationale


def test_stop_carries_the_time_and_price_of_its_structural_swing_anchor():
    support = possible_stop(Zone(price=100, width=1, score=12), frame(), current_price=106)
    resistance = possible_stop(Zone(price=110, width=1, score=8), frame(), current_price=106)

    assert support.anchor_epoch == int(pd.Timestamp("2024-01-01", tz="UTC").timestamp())
    assert support.anchor_price == 96
    assert resistance.anchor_epoch == int(pd.Timestamp("2024-01-05", tz="UTC").timestamp())
    assert resistance.anchor_price == 108
