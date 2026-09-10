"""Causal contracts for the detector-only research harness, not production parity."""
import json
import sys

import pandas as pd
import pytest

import honest_backtest as hb
from zone_detector import Zone


def bars(rows):
    frame = pd.DataFrame(rows, columns=hb.OHLC)
    frame.insert(0, "time", pd.date_range("2024-01-01", periods=len(rows), freq="h", tz="UTC"))
    frame["tick_volume"] = 1.0
    return frame


def history():
    h1 = bars([(103.0, 104.0, 102.0, 103.0)] * 240)
    return {"H1": h1, "H4": hb.resample(h1, "4h"), "D1": hb.resample(h1, "1D")}


def capture_run(monkeypatch, frames, *, failing=False):
    snapshots, evaluations, trades = [], [], []
    live_footprint_setting = hb.config.FOOTPRINT_LEVELS_IN_ZONES

    def detector(formation, flags, limit_output=True, *, allow_external_levels=True):
        assert limit_output is True
        assert allow_external_levels is False
        assert hb.config.FOOTPRINT_LEVELS_IN_ZONES is live_footprint_setting
        snapshots.append({tf: frame.copy(deep=True) for tf, frame in formation.items()})
        if failing:
            raise RuntimeError("injected detector failure")
        return [Zone(price=100.0, width=1.0, score=10, sources=["H4"])]

    def evaluate(price, top, bottom, future, atr, *, decision_price=None):
        evaluations.append((future.copy(deep=True), decision_price))
        return False, "no_touch", 0.0

    def trade(top, bottom, future, atr, spread, *, decision_price=None):
        trades.append((future.copy(deep=True), decision_price))
        return "no_touch"

    monkeypatch.setattr(hb, "detect_zones", detector)
    monkeypatch.setattr(hb, "get_volume_flags_all_tf", lambda formation: {})
    monkeypatch.setattr(hb, "evaluate_level", evaluate)
    monkeypatch.setattr(hb, "simulate_retest_trade", trade)
    cfg = hb.RunConfig(warmup_h4_bars=50, step_h4_bars=999, horizon_h1_bars=4)
    outcomes = hb.run(frames, cfg)
    return snapshots, evaluations, trades, outcomes


@pytest.mark.parametrize("rule,hours", [("4h", 4), ("1D", 24)])
def test_resample_preserves_open_labels_and_boundary_membership(rule, hours):
    source = bars([(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(49)])
    source["tick_volume"] = range(1, 50)
    result = hb.resample(source.iloc[::-1], rule)  # Also require chronological aggregation.
    assert result.iloc[0].time == source.iloc[0].time
    assert result.iloc[1].time == source.iloc[hours].time
    assert result.iloc[0].open == 100
    assert result.iloc[0].close == 100.5 + hours - 1
    assert result.iloc[0].high == 101 + hours - 1
    assert result.iloc[0].low == 99
    assert result.iloc[0].tick_volume == sum(range(1, hours + 1))
    assert result.iloc[1].open == 100 + hours
    assert result.iloc[0].time + pd.Timedelta(hours=hours) == result.iloc[1].time


def test_normalization_keeps_utc_open_time_not_close_time():
    source = bars([(100, 102, 99, 101)])
    source["time"] = ["2024-01-01T03:00:00+03:00"]
    result = hb._normalize(source)
    assert result.iloc[0].time == pd.Timestamp("2024-01-01T00:00:00Z")
    assert str(result.time.dt.tz) == "UTC"


def test_h4_close_cutoff_uses_only_available_formation_and_includes_boundary_h1(monkeypatch):
    frames = history()
    cut = frames["H4"].iloc[50].time + pd.Timedelta(hours=4)
    # A future close must never become the decision price, even for controls.
    frames["H1"].loc[frames["H1"].time == cut, "close"] = 9999.0
    snapshots, evaluations, trades, outcomes = capture_run(monkeypatch, frames)
    assert len(snapshots) == 1
    formation = snapshots[0]
    for tf, duration in hb.BAR_DURATION.items():
        assert (formation[tf].time + duration <= cut).all()
    assert formation["H4"].iloc[-1].time == cut - pd.Timedelta(hours=4)
    assert formation["H1"].iloc[-1].time == cut - pd.Timedelta(hours=1)
    assert formation["D1"].iloc[-1].time == cut.normalize() - pd.Timedelta(days=1)
    assert {out.group for out in outcomes} == {"zones", "random", "round"}
    assert all(pd.Timestamp(out.formed_at) == cut for out in outcomes)
    for future, decision_price in evaluations + trades:
        assert future.iloc[0].time == cut
        assert len(future) == 4
        assert (future.time >= cut).all()
        assert decision_price == 103.0


@pytest.mark.parametrize("tf", ["H1", "H4", "D1"])
def test_mutating_not_yet_available_bars_cannot_change_detector_inputs(monkeypatch, tf):
    frames = history()
    cut = frames["H4"].iloc[50].time + pd.Timedelta(hours=4)
    before, _, _, _ = capture_run(monkeypatch, frames)
    changed = {key: frame.copy(deep=True) for key, frame in frames.items()}
    unseen = changed[tf].time + hb.BAR_DURATION[tf] > cut
    assert unseen.any()
    changed[tf].loc[unseen, hb.OHLC] += 10000
    after, _, _, _ = capture_run(monkeypatch, changed)
    assert len(before) == len(after) == 1
    for key in hb.BAR_DURATION:
        pd.testing.assert_frame_equal(before[0][key], after[0][key])


@pytest.mark.parametrize("decision,row", [
    (103, (103, 104, 97, 97.5)),
    (97, (97, 103, 96, 102.5)),
])
def test_first_future_close_cannot_flip_approach_into_a_bounce(monkeypatch, decision, row):
    monkeypatch.setattr(hb.config, "REACTION_BREAKOUT_ATR", 0.5)
    result = hb.evaluate_level(100, 101, 99, bars([row]), 2, decision_price=decision)
    assert result == (True, "breakout", 0.75)
    # Legacy helper callers use the first OPEN, never the first CLOSE.
    assert hb.evaluate_level(100, 101, 99, bars([row]), 2) == result
    assert hb.simulate_retest_trade(101, 99, bars([row]), 2, 0, decision_price=decision) == "invalid"


@pytest.mark.parametrize("decision,rows", [
    (103, [(103, 103, 100, 100), (100, 102, 99.2, 102)]),
    (97, [(97, 100, 97, 100), (100, 100.8, 98, 98)]),
])
def test_trade_direction_comes_from_decision_not_touch_bar_close(decision, rows):
    assert hb.simulate_retest_trade(101, 99, bars(rows), 2, 0, decision_price=decision) == "target"
    assert hb.simulate_retest_trade(101, 99, bars(rows), 2, 0) == "target"


@pytest.mark.parametrize("decision,rows", [
    (103, [(103, 103, 98.7, 98.8), (98.8, 99.5, 98.5, 99.4)]),
    (97, [(97, 101.3, 97, 101.2), (101.2, 101.5, 100.5, 100.6)]),
])
def test_fill_uses_actual_close_not_invented_zone_edge(monkeypatch, decision, rows):
    monkeypatch.setattr(hb.config, "REACTION_BREAKOUT_ATR", 0.5)
    # Actual closes imply a 0.5 risk and hit 1R. Clamped edge prices imply
    # a 0.7 risk and would leave these trades open instead.
    assert hb.simulate_retest_trade(101, 99, bars(rows), 2, 0, decision_price=decision) == "target"


@pytest.mark.parametrize("decision,row,spread", [
    (103, (103, 103, 98, 98.2), 0),
    (97, (97, 102, 97, 101.8), 0),
    (103, (103, 103, 97.9, 98), 0.2),
    (97, (97, 102.1, 97, 102), 0.2),
])
def test_close_beyond_stop_is_invalid_not_clamped_or_rescued_by_spread(monkeypatch, decision, row, spread):
    monkeypatch.setattr(hb.config, "REACTION_BREAKOUT_ATR", 0.5)
    assert hb.simulate_retest_trade(101, 99, bars([row]), 2, spread, decision_price=decision) == "invalid"


def test_gap_confirmed_break_before_touch_invalidates_original_setup(monkeypatch):
    monkeypatch.setattr(hb.config, "REACTION_BREAKOUT_ATR", 0.5)
    future = bars([(97, 98, 96, 97), (97, 101, 97, 100)])
    assert hb.simulate_retest_trade(101, 99, future, 2, 0, decision_price=103) == "invalid"
    assert hb.evaluate_level(100, 101, 99, future, 2, decision_price=103) == (True, "invalid", 0.0)


@pytest.mark.parametrize("decision", [103, 97])
def test_ambiguous_later_ohlc_bar_is_stop_first(decision):
    future = bars([(decision, 104, 96, 100), (100, 104, 96, 100)])
    assert hb.simulate_retest_trade(101, 99, future, 2, 0, decision_price=decision) == "stop"


@pytest.mark.parametrize("decision", [103, 97])
def test_entry_bar_extremes_cannot_exit_trade_or_invent_post_touch_excursion(decision):
    future = bars([(decision, 120, 80, 100)])
    assert hb.simulate_retest_trade(101, 99, future, 2, 0, decision_price=decision) == "open"
    assert hb.evaluate_level(100, 101, 99, future, 2, decision_price=decision) == (True, "consolidation", 0.0)


def test_inside_zone_decision_does_not_guess_a_trade_direction():
    future = bars([(100, 101, 99, 100)])
    assert hb.simulate_retest_trade(101, 99, future, 2, 0, decision_price=100) == "invalid"
    assert hb.evaluate_level(100, 101, 99, future, 2, decision_price=100) == (True, "invalid", 0.0)


def test_empty_future_has_no_touch():
    future = bars([])
    assert hb.simulate_retest_trade(101, 99, future, 2, 0, decision_price=103) == "no_touch"
    assert hb.evaluate_level(100, 101, 99, future, 2, decision_price=103) == (False, "no_touch", 0.0)


@pytest.mark.parametrize("name", ["horizon_h1_bars", "step_h4_bars"])
@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_invalid_horizon_or_step_fails_before_data_access(name, value):
    with pytest.raises(ValueError, match=name):
        hb.RunConfig(**{name: value})
    cfg = hb.RunConfig()
    setattr(cfg, name, value)
    with pytest.raises(ValueError, match=name):
        hb.run({}, cfg)


@pytest.mark.parametrize("name,value", [
    ("round_step", 0), ("warmup_h4_bars", -1), ("h1_window", 0), ("spread", -0.1),
])
def test_other_unusable_run_parameters_fail_fast(name, value):
    with pytest.raises(ValueError, match=name):
        hb.RunConfig(**{name: value})


@pytest.mark.parametrize("failing", [False, True])
def test_run_passes_offline_flag_without_mutating_config_even_on_failure(monkeypatch, failing):
    monkeypatch.setattr(hb.config, "FOOTPRINT_LEVELS_IN_ZONES", True)
    snapshots, _, _, _ = capture_run(monkeypatch, history(), failing=failing)
    assert snapshots
    assert hb.config.FOOTPRINT_LEVELS_IN_ZONES is True


def test_missing_offline_detector_api_never_falls_back_to_live_ingestion(monkeypatch, capsys):
    """An old detector must fail closed until the parent API update is applied."""
    calls = []

    def legacy_detector(data, flags, limit_output=True):
        calls.append("unsafe legacy detector")
        raise AssertionError("must not retry without allow_external_levels=False")

    monkeypatch.setattr(hb.config, "FOOTPRINT_LEVELS_IN_ZONES", True)
    monkeypatch.setattr(hb, "detect_zones", legacy_detector)
    monkeypatch.setattr(hb, "get_volume_flags_all_tf", lambda formation: {})
    cfg = hb.RunConfig(warmup_h4_bars=50, step_h4_bars=999, horizon_h1_bars=4)
    assert hb.run(history(), cfg) == []
    assert calls == []
    assert "allow_external_levels" in capsys.readouterr().out
    assert hb.config.FOOTPRINT_LEVELS_IN_ZONES is True


def test_summary_labels_detector_only_and_counts_rejected_entries():
    empty_meta = hb.summarize([])["meta"]
    assert empty_meta["research_scope"] == "detector_only"
    assert empty_meta["production_pipeline_parity"] is False
    assert empty_meta["external_levels"] is False
    assert empty_meta["persistent_state"] is False
    assert empty_meta["ai"] is False
    assert empty_meta["limitations"]
    report = hb.summarize([
        hb.LevelOutcome("zones", "2024-01-01T04:00:00Z", 100, 10, True, "invalid", 0,
                        trade="invalid")
    ])
    assert report["groups"]["zones"]["trades_invalid"] == 1
    assert report["groups"]["zones"]["invalid"] == 1
    assert report["groups"]["zones"]["trades_closed"] == 0


def test_cli_preserves_research_metadata_in_json(monkeypatch, tmp_path):
    source = tmp_path / "h1.csv"
    bars([(100, 101, 99, 100)] * 24).to_csv(source, index=False)
    out = tmp_path / "report"
    monkeypatch.setattr(sys, "argv", ["honest_backtest.py", "--csv", str(source), "--out", str(out)])
    hb.main()
    report = json.loads((out / "honest_backtest.json").read_text())
    assert report["meta"]["research_scope"] == "detector_only"
    assert report["meta"]["bar_time_convention"] == "open_time_utc"
    assert report["meta"]["production_pipeline_parity"] is False
    assert report["meta"]["source"] == "CSV h1.csv"


def test_cli_zero_horizon_fails_before_optional_market_download(monkeypatch):
    def no_download(*args, **kwargs):
        pytest.fail("configuration must be validated before market data I/O")

    monkeypatch.setattr(hb, "load_from_yfinance", no_download)
    monkeypatch.setattr(sys, "argv", ["honest_backtest.py", "--horizon", "0"])
    with pytest.raises(ValueError, match="horizon_h1_bars"):
        hb.main()
