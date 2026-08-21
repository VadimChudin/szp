import json

import pandas as pd

from active_zones import normalize_display_balance, update_snapshot
from zone_detector import Zone


def bars(*rows):
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def z(price, score):
    return Zone(price=price, width=1.0, score=score, sources=["H4"])


def test_initial_snapshot_has_three_above_and_three_below(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    candidates = [z(82 + i * 3, 16 - i) for i in range(4)] + [z(106 + i * 3, 15 - i) for i in range(4)]
    result = update_snapshot(candidates, data, snap, events)
    assert len(result) == 6
    assert len([item for item in result if item.price < 100]) == 3
    assert len([item for item in result if item.price > 100]) == 3


def test_fallback_is_marked_when_side_lacks_strong_levels(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    candidates = [z(70, 18), z(80, 16), z(90, 15)] + [z(110, 14), z(120, 9), z(130, 8)]
    result = update_snapshot(candidates, data, snap, events)
    above = [item for item in result if item.price > 100]
    assert len(above) == 3
    assert above[0].is_fallback is False
    assert any(item.is_fallback for item in above)


def test_higher_score_replaces_only_weakest_on_same_side(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "ACTIVE_ZONE_MAX_DISTANCE_PCT", 50.0)
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data1 = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    initial = [z(82, 11), z(88, 12), z(94, 13), z(106, 11), z(112, 12), z(118, 13)]
    update_snapshot(initial, data1, snap, events)
    data2 = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100), ("2024-01-01T04:00:00", 100, 101, 99, 100))}
    result = update_snapshot(initial + [z(124, 15)], data2, snap, events)
    above_prices = [item.price for item in result if item.price > 100]
    below_prices = [item.price for item in result if item.price < 100]
    assert 106 not in above_prices and 124 in above_prices
    assert below_prices == [94, 88, 82]


def test_same_h4_is_idempotent(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    source = [z(70, 11), z(80, 12), z(90, 13), z(110, 11), z(120, 12), z(130, 13)]
    initial = update_snapshot(source, data, snap, events)
    again = update_snapshot(source + [z(140, 99)], data, snap, events)
    assert [item.price for item in again] == [item.price for item in initial]


def test_body_break_removes_zone_and_does_not_readd_same_cycle(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "ACTIVE_ZONE_MAX_DISTANCE_PCT", 50.0)
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    first = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    update_snapshot([z(70, 12)], first, snap, events)
    broken = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100), ("2024-01-01T04:00:00", 60, 72, 59, 72))}
    result = update_snapshot([z(70, 20)], broken, snap, events)
    assert all(item.price != 70 for item in result)
    assert any(json.loads(line)["event"] == "zone_invalidated" for line in events.read_text().splitlines())


def test_snapshot_persists_between_calls(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    update_snapshot([z(70, 15)], data, snap, events)
    raw = json.loads(snap.read_text())
    assert raw["version"] == "3.1"
    assert raw["zones"][0]["state"] == "ACTIVE"


def test_display_guard_rebalances_all_above_snapshot_with_red_lower_fallbacks():
    visible = normalize_display_balance(
        [z(1100, 18), z(1150, 16), z(1200, 14), z(1250, 13), z(1300, 12), z(1350, 11)],
        price=1000,
    )
    above = [item for item in visible if item.price > 1000]
    below = [item for item in visible if item.price < 1000]

    assert len(visible) == 6
    assert len(above) == 3
    assert len(below) == 3
    assert all(item.is_fallback for item in below)
    assert all(item.state == "DISPLAY_FALLBACK" for item in below)


def test_missing_upper_side_is_completed_by_red_projected_fallbacks(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 1000, 1001, 999, 1000))}
    candidates = [z(700, 18), z(800, 16), z(900, 14)]

    result = update_snapshot(candidates, data, snap, events)
    above = [item for item in result if item.price > 1000]
    below = [item for item in result if item.price < 1000]

    assert len(result) == 6
    assert len(above) == 3
    assert len(below) == 3
    assert all(item.is_fallback for item in above)
    assert all("PROJ" in item.label_suffix for item in above)


def test_snapshot_contract_upgrade_rebuilds_unbalanced_legacy_snapshot_immediately(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    legacy_zones = [z(700, 18), z(800, 16), z(900, 14), z(850, 13), z(750, 12), z(650, 11)]
    snap.write_text(json.dumps({
        "version": "3.0",
        "last_h4": "2024-01-01T04:00:00",
        "zones": [zone.to_dict() for zone in legacy_zones],
    }))
    data = {"H4": bars(("2024-01-01T04:00:00", 1000, 1001, 999, 1000))}

    result = update_snapshot([], data, snap, events)

    assert len(result) == 6
    assert len([item for item in result if item.price > 1000]) == 3
    assert len([item for item in result if item.price < 1000]) == 3
    assert json.loads(snap.read_text())["version"] == "3.1"
    assert any(json.loads(line)["event"] == "snapshot_contract_rebuilt"
               for line in events.read_text().splitlines())


def test_breakout_is_applied_only_after_a_new_closed_h4(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "ACTIVE_ZONE_MAX_DISTANCE_PCT", 50.0)
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    initial = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    candidates = [z(70, 13), z(80, 14), z(90, 15), z(110, 15), z(120, 14), z(130, 13)]
    before = update_snapshot(candidates, initial, snap, events, reference_price=100)

    # A changed quote inside the same H4 slot cannot erase zones prematurely.
    same_h4 = {"H4": bars(("2024-01-01T00:00:00", 95, 96, 60, 65))}
    unchanged = update_snapshot(candidates, same_h4, snap, events, reference_price=100)
    assert [item.price for item in unchanged] == [item.price for item in before]

    # The next closed H4 confirms the body breakout and triggers replacement.
    next_h4 = {"H4": bars(
        ("2024-01-01T00:00:00", 100, 101, 99, 100),
        ("2024-01-01T04:00:00", 95, 96, 60, 65),
    )}
    result = update_snapshot(candidates + [z(55, 20), z(45, 19)],
                             next_h4, snap, events, reference_price=100)
    below = [item.price for item in result if item.price < 100]
    assert 90 not in below and 80 not in below and 70 not in below
    # A fresh real candidate replaces the broken cluster; remaining slots are
    # filled without restoring the obsolete levels.
    assert 55 in below
    assert len(below) == 3


def test_zone_outside_live_distance_window_is_removed_on_next_h4(tmp_path, monkeypatch):
    import config

    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    candidates = [z(70, 16), z(80, 15), z(90, 14), z(110, 14), z(120, 15), z(130, 16)]
    first = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    monkeypatch.setattr(config, "ACTIVE_ZONE_MAX_DISTANCE_PCT", 50.0)
    update_snapshot(candidates, first, snap, events, reference_price=100)

    monkeypatch.setattr(config, "ACTIVE_ZONE_MAX_DISTANCE_PCT", 10.0)
    second = {"H4": bars(
        ("2024-01-01T00:00:00", 100, 101, 99, 100),
        ("2024-01-01T04:00:00", 100, 102, 98, 100),
    )}
    result = update_snapshot(candidates + [z(94, 20)], second, snap, events, reference_price=100)

    assert 70 not in [item.price for item in result]
    assert 94 in [item.price for item in result]
    logged = [json.loads(line) for line in events.read_text().splitlines()]
    assert any(event.get("reason") == "outside_active_window" for event in logged)
