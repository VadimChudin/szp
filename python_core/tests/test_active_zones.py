import json

import pandas as pd

from active_zones import update_snapshot
from zone_detector import Zone


def bars(*rows):
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def z(price, score):
    return Zone(price=price, width=1.0, score=score, sources=["H4"])


# Зоны отбираются лестницей внутри полосы 200-300 пипсов от цены, поэтому
# фикстуры стоят на шаге $2.5 от цены 100 ($2.5 = 250 пипсов при PIP_SIZE=0.01).
# Прежние уровни 70/80/90/110/120/130 лежали далеко за полосой и на график
# больше не попадают by design.
def ladder(below: bool, scores: list[int]) -> list[Zone]:
    sign = -1 if below else 1
    return [z(100 + sign * (2.5 + 2.5 * i), score) for i, score in enumerate(scores)]


def test_initial_snapshot_has_three_above_and_three_below(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    candidates = ladder(below=True, scores=[16, 15, 14, 13]) + \
        ladder(below=False, scores=[15, 14, 13, 12])
    result = update_snapshot(candidates, data, snap, events)
    assert len(result) == 6
    assert len([item for item in result if item.price < 100]) == 3
    assert len([item for item in result if item.price > 100]) == 3


def test_fallback_is_marked_when_side_lacks_strong_levels(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    candidates = ladder(below=True, scores=[18, 16, 15]) + \
        ladder(below=False, scores=[14, 9, 8])
    result = update_snapshot(candidates, data, snap, events)
    above = [item for item in result if item.price > 100]
    assert len(above) == 3
    assert above[0].is_fallback is False
    assert any(item.is_fallback for item in above)


def test_stronger_candidate_at_same_level_strengthens_zone(tmp_path):
    """Score усиливает уровень на месте, но больше не тянет набор из полосы.

    Прежде более сильный далёкий кандидат вытеснял хорошо стоящую зону — именно
    так набор и уезжал из ренжа. Теперь расстояние решает, а score — внутри слота.
    """
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data1 = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    initial = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[11, 12, 13])
    update_snapshot(initial, data1, snap, events)

    data2 = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100),
                        ("2024-01-01T04:00:00", 100, 101, 99, 100))}
    stronger = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[17, 12, 13])
    result = update_snapshot(stronger, data2, snap, events)

    above = sorted((item for item in result if item.price > 100), key=lambda item: item.price)
    assert [item.price for item in above] == [102.5, 105.0, 107.5]
    assert above[0].score == 17, "уровень должен усилиться на месте"
    below = sorted((item for item in result if item.price < 100), key=lambda item: item.price)
    assert [item.price for item in below] == [92.5, 95.0, 97.5], "другая сторона не тронута"


def test_far_stronger_candidate_does_not_pull_set_out_of_band(tmp_path):
    """Главный регресс клиента: сильная зона далеко от цены не должна вытеснять
    зону, стоящую в запрошенном ренже."""
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    candidates = ladder(below=True, scores=[13, 12, 11]) + \
        ladder(below=False, scores=[11, 12, 13]) + [z(160.0, 99), z(40.0, 99)]
    result = update_snapshot(candidates, data, snap, events)
    prices = [item.price for item in result]
    assert 160.0 not in prices and 40.0 not in prices
    assert len(result) == 6


def test_same_h4_is_idempotent(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", 100, 101, 99, 100))}
    source = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[11, 12, 13])
    initial = update_snapshot(source, data, snap, events)
    again = update_snapshot(source + [z(110.0, 99)], data, snap, events)
    assert [item.price for item in again] == [item.price for item in initial]


def test_body_break_removes_zone_and_does_not_readd_same_cycle(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    first = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    update_snapshot([z(95.0, 12)], first, snap, events)
    # Свеча проходит зону 95 телом: открытие выше top, закрытие ниже bottom.
    broken = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100),
                         ("2024-01-01T04:00:00", 97, 97.5, 93, 93.5))}
    result = update_snapshot([z(95.0, 20)], broken, snap, events)
    assert all(item.price != 95.0 for item in result)
    assert any(json.loads(line)["event"] == "zone_invalidated" for line in events.read_text().splitlines())


def test_snapshot_persists_between_calls(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T00:00:00", 100, 101, 99, 100))}
    update_snapshot([z(97.5, 15)], data, snap, events)
    raw = json.loads(snap.read_text())
    assert raw["version"] == "3.0"
    assert raw["zones"][0]["state"] == "ACTIVE"
