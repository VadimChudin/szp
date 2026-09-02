import json

import pandas as pd

import config
from active_zones import update_snapshot
from zone_detector import Zone


def bars(*rows):
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def z(price, score):
    return Zone(price=price, width=1.0, score=score, sources=["H4"])


PRICE = 4000.0
# Смещения в пределах диапазона показа (0..MAX_ZONE_DISTANCE), кратные и различимые.
OFFS = [20.0, 40.0, 60.0, 80.0]


def ladder(below: bool, scores):
    sign = -1 if below else 1
    return [z(round(PRICE + sign * OFFS[i], 2), s) for i, s in enumerate(scores)]


def test_initial_snapshot_has_three_above_and_three_below(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    candidates = ladder(below=True, scores=[16, 15, 14]) + ladder(below=False, scores=[15, 14, 13])
    result = update_snapshot(candidates, data, snap, events)
    assert len(result) == 6
    assert len([x for x in result if x.price < PRICE]) == 3
    assert len([x for x in result if x.price > PRICE]) == 3


def test_nearest_zones_are_selected(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    candidates = ladder(below=False, scores=[11, 12, 13, 14]) + ladder(below=True, scores=[11, 12, 13, 14])
    result = update_snapshot(candidates, data, snap, events)
    above = sorted(abs(x.price - PRICE) for x in result if x.price > PRICE)
    assert above == OFFS[:config.ZONES_PER_SIDE]   # ближайшие, не самые сильные


def test_far_zone_not_selected(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    far = round(PRICE + config.MAX_ZONE_DISTANCE + 100.0, 2)
    candidates = ladder(below=False, scores=[13, 12, 11]) + [z(far, 99)]
    result = update_snapshot(candidates, data, snap, events)
    assert all(x.price != far for x in result)


def test_stronger_candidate_at_same_level_strengthens_zone(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data1 = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    initial = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[11, 12, 13])
    update_snapshot(initial, data1, snap, events)

    data2 = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE),
                        ("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    stronger = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[17, 12, 13])
    result = update_snapshot(stronger, data2, snap, events)
    above = sorted((x for x in result if x.price > PRICE), key=lambda x: x.price)
    assert above[0].price == round(PRICE + OFFS[0], 2)
    assert above[0].score == 17


def test_same_h4_is_idempotent(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    source = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[11, 12, 13])
    initial = update_snapshot(source, data, snap, events)
    again = update_snapshot(source + [z(round(PRICE + config.MAX_ZONE_DISTANCE + 50, 2), 99)], data, snap, events)
    assert [x.price for x in again] == [x.price for x in initial]


def test_body_break_removes_zone_and_does_not_readd_same_cycle(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    level = round(PRICE - OFFS[0], 2)
    first = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    update_snapshot([z(level, 12)], first, snap, events)
    broken = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE),
                         ("2024-01-01T04:00:00", level + 2.0, level + 2.5, level - 2.0, level - 1.5))}
    result = update_snapshot([z(level, 20)], broken, snap, events)
    assert all(x.price != level for x in result)
    assert any(json.loads(line)["event"] == "zone_invalidated" for line in events.read_text().splitlines())


def test_snapshot_persists_between_calls(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    update_snapshot([z(round(PRICE - OFFS[0], 2), 15)], data, snap, events)
    raw = json.loads(snap.read_text())
    assert raw["version"] == "3.0"
    assert raw["zones"][0]["state"] == "ACTIVE"
