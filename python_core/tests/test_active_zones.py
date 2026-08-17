import json
from pathlib import Path

import pandas as pd

from active_zones import update_snapshot
from zone_detector import Zone


def bars(*rows):
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def z(price, score):
    return Zone(price=price, width=1.0, score=score, sources=["H4"])


def test_new_stronger_candidate_replaces_only_weakest(tmp_path):
    snap = tmp_path / "snapshot.json"
    events = tmp_path / "events.jsonl"
    data1 = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    current = [z(1000 + i * 20, i + 2) for i in range(5)]
    result = update_snapshot(current, data1, snap, events)
    assert sorted(x.score for x in result) == [2, 3, 4, 5, 6]

    data2 = {"H4": bars(
        ("2024-01-01T00:00:00", 100, 101, 99, 100),
        ("2024-01-01T04:00:00", 100, 101, 99, 100),
    )}
    result = update_snapshot(current + [z(1200, 7)], data2, snap, events)
    assert sorted(x.score for x in result) == [3, 4, 5, 6, 7]
    assert 1000 not in [x.price for x in result]


def test_same_h4_is_idempotent_and_weaker_candidate_does_not_replace(tmp_path):
    snap = tmp_path / "snapshot.json"
    events = tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    initial = update_snapshot([z(1000 + i * 20, i + 2) for i in range(5)], data, snap, events)
    again = update_snapshot([z(1300, 99)], data, snap, events)
    assert [x.price for x in again] == [x.price for x in initial]


def test_body_break_removes_zone(tmp_path):
    snap = tmp_path / "snapshot.json"
    events = tmp_path / "events.jsonl"
    first = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    update_snapshot([z(1000, 12)], first, snap, events)
    broken = {"H4": bars(
        ("2024-01-01T00:00:00", 100, 101, 99, 100),
        ("2024-01-01T04:00:00", 990, 1010, 989, 1010),
    )}
    result = update_snapshot([], broken, snap, events)
    assert result == []
    lines = events.read_text().splitlines()
    assert any(json.loads(line)["event"] == "zone_invalidated" for line in lines)


def test_snapshot_persists_between_calls(tmp_path):
    snap = tmp_path / "snapshot.json"
    events = tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    update_snapshot([z(2400, 15)], data, snap, events)
    raw = json.loads(snap.read_text())
    assert raw["version"] == "2.0"
    assert raw["zones"][0]["state"] == "ACTIVE"


def test_initial_snapshot_balances_both_sides(tmp_path):
    snap = tmp_path / "snapshot.json"
    events = tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    candidates = [z(90 + i, 20 - i) for i in range(8)] + [z(110 + i, 12 - i) for i in range(8)]
    result = update_snapshot(candidates, data, snap, events)
    assert any(item.price < 100 for item in result)
    assert any(item.price > 100 for item in result)
