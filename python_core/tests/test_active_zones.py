import json

import pandas as pd

from active_zones import update_snapshot
from zone_detector import Zone


def bars(*rows):
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def z(price, score):
    return Zone(price=price, width=1.0, score=score, sources=["H4"])


def test_initial_snapshot_has_three_above_and_three_below(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    candidates = [z(70 + i * 5, 16 - i) for i in range(6)] + [z(130 + i * 5, 15 - i) for i in range(6)]
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


def test_higher_score_replaces_only_weakest_on_same_side(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data1 = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    initial = [z(70, 11), z(80, 12), z(90, 13), z(110, 11), z(120, 12), z(130, 13)]
    update_snapshot(initial, data1, snap, events)
    data2 = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100), ("2024-01-01T04:00:00", 100, 101, 99, 100))}
    result = update_snapshot(initial + [z(140, 15)], data2, snap, events)
    above_prices = [item.price for item in result if item.price > 100]
    below_prices = [item.price for item in result if item.price < 100]
    assert 110 not in above_prices and 140 in above_prices
    assert below_prices == [90, 80, 70]


def test_same_h4_is_idempotent(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    source = [z(70, 11), z(80, 12), z(90, 13), z(110, 11), z(120, 12), z(130, 13)]
    initial = update_snapshot(source, data, snap, events)
    again = update_snapshot(source + [z(140, 99)], data, snap, events)
    assert [item.price for item in again] == [item.price for item in initial]


def test_body_break_removes_zone_and_does_not_readd_same_cycle(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    first = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    update_snapshot([z(70, 12)], first, snap, events)
    broken = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100), ("2024-01-01T04:00:00", 60, 71, 59, 71))}
    result = update_snapshot([z(70, 20)], broken, snap, events)
    assert all(item.price != 70 for item in result)
    assert any(json.loads(line)["event"] == "zone_invalidated" for line in events.read_text().splitlines())


def test_snapshot_persists_between_calls(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    update_snapshot([z(70, 15)], data, snap, events)
    raw = json.loads(snap.read_text())
    assert raw["version"] == "3.0"
    assert raw["zones"][0]["state"] == "ACTIVE"
