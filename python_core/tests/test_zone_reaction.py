"""Тесты классификатора реакции цены на зону (zone_reaction)."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from zone_reaction import classify_reaction, Reaction  # noqa: E402


def _mk(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


BASE = [(4000, 4002, 3998, 4001)] * 20
DOWNTREND = [
    (4030, 4031, 4025, 4026), (4026, 4027, 4020, 4021), (4021, 4022, 4014, 4015),
    (4015, 4016, 4008, 4009), (4009, 4010, 4003, 4004),
] * 2


def test_breakout_up_through_resistance():
    rows = BASE + [(4001, 4006, 4000, 4005), (4005, 4011, 4004, 4009),
                   (4009, 4020, 4008, 4018), (4018, 4026, 4017, 4025)]
    r = classify_reaction(4012, 4010, _mk(rows), "ABOVE")
    assert r.type == Reaction.BREAKOUT
    assert r.direction == "UP"


def test_breakout_down_through_support():
    rows = BASE + [(4000, 4001, 3994, 3996), (3996, 3997, 3990, 3992),
                   (3992, 3993, 3982, 3984), (3984, 3985, 3976, 3978)]
    r = classify_reaction(3992, 3990, _mk(rows), "BELOW")
    assert r.type == Reaction.BREAKOUT
    assert r.direction == "DOWN"


def test_bounce_up_from_support():
    rows = BASE + [(4000, 4001, 3993, 3995), (3995, 3996, 3990, 3992),
                   (3993, 3999, 3992, 3998), (3999, 4008, 3998, 4007)]
    r = classify_reaction(3992, 3990, _mk(rows), "BELOW")
    assert r.type == Reaction.BOUNCE
    assert r.direction == "UP"


def test_consolidation_inside_zone():
    rows = DOWNTREND + [(4002, 4004, 4000, 4003), (4003, 4004, 4001, 4002),
                        (4002, 4003, 4000, 4001), (4001, 4003, 4000, 4002),
                        (4002, 4003, 4001, 4002)]
    r = classify_reaction(4003, 3999, _mk(rows), "BELOW")
    assert r.type == Reaction.CONSOLIDATION


def test_none_when_zone_far():
    r = classify_reaction(4200, 4198, _mk(BASE), "ABOVE")
    assert r.type == Reaction.NONE


def test_empty_data_is_safe():
    r = classify_reaction(4000, 3998, _mk([]), "ABOVE")
    assert r.type == Reaction.NONE


def test_to_dict_shape():
    rows = BASE + [(4001, 4006, 4000, 4005), (4005, 4011, 4004, 4009),
                   (4009, 4020, 4008, 4018), (4018, 4026, 4017, 4025)]
    d = classify_reaction(4012, 4010, _mk(rows), "ABOVE").to_dict()
    assert set(d) == {"type", "direction", "strength", "bars_since", "touches", "detail"}
    assert 0.0 <= d["strength"] <= 1.0
