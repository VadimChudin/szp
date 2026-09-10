"""Behavioral regressions for the 6.1 structural evidence contract."""
from __future__ import annotations

import contextlib
import io

import numpy as np
import pandas as pd
import pytest

import config
from data_fetcher import fetch_from_csv
from market_data import candle_duration, closed_data, closed_ohlcv
from volume_filter import get_volume_flags_all_tf
from zone_detector import Zone, _distinct_zones, _evidence_zone, cluster_levels, detect_zones


def frame(tf="H1", n=4, start="2024-01-01"):
    return pd.DataFrame({
        "time": pd.date_range(start, periods=n, freq=candle_duration(tf)),
        "open": [100.0] * n, "high": [102.0] * n,
        "low": [98.0] * n, "close": [100.5] * n,
        "tick_volume": [100.0] * n,
    })


@pytest.mark.parametrize("tf", ["M1", "M5", "M15", "H1", "H4", "D1"])
def test_bars_become_available_at_close_not_open(tf):
    raw = frame(tf)
    cutoff = raw.time.iloc[1] + candle_duration(tf)
    got = closed_ohlcv(raw, tf, as_of=cutoff)
    assert list(got.time) == list(raw.time.iloc[:2])
    before = closed_ohlcv(raw, tf, as_of=cutoff - pd.Timedelta(microseconds=1))
    assert len(before) == 1
    assert len(raw) == 4  # no in-place truncation


def test_explicit_forming_marker_wins_over_the_clock():
    raw = frame()
    raw["is_closed"] = [1, 1, 1, 0]
    assert len(closed_ohlcv(raw, "H1", as_of="2025-01-01")) == 3


def test_broker_clock_uses_authoritative_terminal_flag():
    raw = frame(start="2099-01-01")
    raw["is_closed"] = [True, True, True, False]
    raw.attrs["broker_clock"] = True
    assert len(closed_ohlcv(raw, "H1")) == 3
    # A replay cutoff is explicit and uses the same clock as the source.
    assert len(closed_ohlcv(raw, "H1", as_of="2099-01-01 01:00")) == 1


def test_broker_clock_without_closure_evidence_is_rejected():
    raw = frame()
    raw.attrs["broker_clock"] = True
    with pytest.raises(ValueError, match="require is_closed"):
        closed_ohlcv(raw, "H1")


def test_old_collector_csv_conservatively_excludes_bar_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CSV_DIR", str(tmp_path))
    path = tmp_path / "XAUUSD_H1.csv"
    path.write_text("# broker=Example, symbol=XAUUSD\n" + frame().to_csv(index=False))
    raw = fetch_from_csv("XAUUSD", "H1")
    assert raw.attrs["broker_clock"]
    assert list(raw.is_closed) == [True, True, True, False]
    assert len(closed_ohlcv(raw, "H1")) == 3


def test_offsets_and_unsorted_rows_are_normalized_without_mutation():
    raw = frame().iloc[::-1].copy()
    raw["time"] = pd.to_datetime(raw["time"]).dt.tz_localize("Europe/Moscow")
    original = raw.copy(deep=True)
    out = closed_ohlcv(raw, "H1", as_of="2024-01-02T00:00:00Z")
    assert out.time.is_monotonic_increasing
    assert out.time.iloc[0] == pd.Timestamp("2023-12-31 21:00")
    pd.testing.assert_frame_equal(raw, original)


@pytest.mark.parametrize("column,value", [
    ("close", np.nan), ("high", np.inf), ("low", -np.inf),
    ("tick_volume", -1), ("close", 0), ("high", 99), ("low", 101),
])
def test_malformed_closed_candle_rejects_source(column, value):
    raw = frame()
    raw.loc[0, column] = value
    with pytest.raises(ValueError):
        closed_ohlcv(raw, "H1", as_of="2024-01-02")


def test_invalid_future_values_do_not_contaminate_past():
    raw = frame()
    raw.loc[3, "close"] = np.nan
    out = closed_ohlcv(raw, "H1", as_of="2024-01-01 02:00")
    assert len(out) == 2


def test_duplicate_closed_observation_is_idempotent_but_conflict_fails():
    raw = frame()
    identical = pd.concat([raw, raw.iloc[[0]]])
    out = closed_ohlcv(identical, "H1", as_of="2024-01-02")
    pd.testing.assert_frame_equal(out, raw)
    conflicting = identical.copy()
    conflicting.iloc[-1, conflicting.columns.get_loc("close")] = 100.7
    with pytest.raises(ValueError, match="conflicting candles"):
        closed_ohlcv(conflicting, "H1", as_of="2024-01-02")


def test_malformed_closure_flag_is_not_silently_truthy():
    raw = frame()
    raw["is_closed"] = [1, 1, "pending", 0]
    with pytest.raises(ValueError, match="invalid is_closed"):
        closed_ohlcv(raw, "H1")


@pytest.mark.parametrize("seed", range(8))
def test_cluster_partition_has_no_duplicate_or_out_of_radius_members(seed):
    values = np.random.default_rng(seed).uniform(50, 120, 250)
    clusters = cluster_levels(values, tolerance=5)
    used = [i for c in clusters for i in c["indices"]]
    assert sorted(used) == list(range(len(values)))
    for cluster in clusters:
        assert max(abs(v - cluster["center"]) for v in cluster["members"]) <= 5 + 1e-10


@pytest.mark.parametrize("values,tolerance", [([1, np.nan], 1), ([1, np.inf], 1),
                                               ([1, 2], -1), ([1, 2], np.inf)])
def test_invalid_cluster_parameters_fail_explicitly(values, tolerance):
    with pytest.raises(ValueError):
        cluster_levels(np.array(values), tolerance)


@pytest.fixture
def permissive(monkeypatch):
    monkeypatch.setattr(config, "ZONE_WIDTH_MODE", "fixed")
    monkeypatch.setattr(config, "ZONE_WIDTH", 2.0)
    monkeypatch.setattr(config, "MIN_ZONE_SCORE", 1)
    monkeypatch.setattr(config, "STRONG_ZONES_ONLY", True)
    monkeypatch.setattr(config, "REQUIRE_H4_ANCHOR", False)
    monkeypatch.setattr(config, "FOOTPRINT_LEVELS_IN_ZONES", False)


def test_one_candle_two_wicks_is_one_evidence_bar(permissive, monkeypatch):
    monkeypatch.setattr(config, "ZONE_WIDTH", 4.0)
    out = detect_zones({"H1": frame(n=1)}, limit_output=False)
    assert len(out) == 1
    assert out[0].touch_count == 1
    assert "H1" not in out[0].score_components
    assert len(out[0].wick_points) == 2


def test_volume_flags_are_positional_not_dataframe_index_labels(permissive):
    raw = frame()
    shifted = raw.copy()
    shifted.index = [10, 20, 30, 40]
    flags = {"H1": np.array([False, True, False, False])}
    a = detect_zones({"H1": raw}, flags, limit_output=False)
    b = detect_zones({"H1": shifted}, flags, limit_output=False)
    assert [z.to_dict() for z in a] == [z.to_dict() for z in b]
    assert any(z.has_big_player for z in b)
    with pytest.raises(ValueError, match="align by candle POSITION"):
        detect_zones({"H1": raw}, {"H1": np.ones(2)})


def test_repeated_rows_do_not_inflate_structural_score(permissive):
    raw = frame()
    unique = detect_zones({"H1": raw}, limit_output=False)
    duplicates = detect_zones({"H1": pd.concat([raw, raw])}, limit_output=False)
    assert [z.to_dict() for z in unique] == [z.to_dict() for z in duplicates]


def test_actual_overlap_never_creates_an_unobserved_midpoint_or_sum():
    strong = Zone(price=100, width=7, score=12, touch_count=3)
    near = Zone(price=109, width=7, score=11, touch_count=100)
    selected = _distinct_zones([near, strong])
    assert [(z.price, z.score) for z in selected] == [(100, 12)]
    assert strong.width == 7


def test_h4_anchor_is_a_requirement_not_a_best_effort_hint(permissive, monkeypatch):
    assert detect_zones({"H1": frame()}, limit_output=False)
    monkeypatch.setattr(config, "REQUIRE_H4_ANCHOR", True)
    assert detect_zones({"H1": frame()}, limit_output=False) == []


def test_fvg_bonus_requires_intersection_with_drawn_zone():
    evidence = pd.DataFrame([{"price": 100, "tf": "H1", "has_volume": False,
                              "time": pd.Timestamp("2024-01-01"), "wick_type": "lower"}])
    zone = _evidence_zone(evidence, 1, [{"bottom": 104, "top": 106}])
    assert "FVG" not in zone.score_components
    assert zone.evidence_at == "2024-01-01T01:00:00"
    assert zone.score == sum(zone.score_components.values())


def test_same_cutoff_is_invariant_to_future_data_and_dictionary_order(permissive):
    data = {tf: frame(tf, n=80) for tf in ("H1", "H4", "D1")}
    cutoff = pd.Timestamp("2024-01-03")
    prefix = {tf: df[df.time + candle_duration(tf) <= cutoff] for tf, df in data.items()}
    poisoned = {tf: df.copy() for tf, df in reversed(list(data.items()))}
    for tf, df in poisoned.items():
        df.loc[df.time + candle_duration(tf) > cutoff, ["high", "close"]] = 999999.0
    a, b = closed_data(prefix, as_of=cutoff), closed_data(poisoned, as_of=cutoff)
    with contextlib.redirect_stdout(io.StringIO()):
        za = detect_zones(a, get_volume_flags_all_tf(a), limit_output=False)
        zb = detect_zones(b, get_volume_flags_all_tf(b), limit_output=False)
    assert za
    assert [z.to_dict() for z in za] == [z.to_dict() for z in zb]
    assert all(z.score == sum(z.score_components.values()) for z in za)


def test_new_evidence_and_lifecycle_round_trip():
    zone = Zone(price=100, evidence_at="2024-01-01T04:00:00",
                score_components={"H4": 3}, lifecycle={"origin_side": "BELOW"})
    restored = Zone.from_dict(zone.to_dict())
    assert restored.to_dict() == zone.to_dict()
