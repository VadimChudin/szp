import json

import pandas as pd

import config
from active_zones import update_snapshot
from zone_detector import Zone


PRICE = 4000.0


def bars(*rows):
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def z(price, score):
    return Zone(price=round(price, 2), width=config.ZONE_WIDTH, score=score,
                sources=["H4"])


# Зоны отбираются внутри окна [ZONE_MIN_DISTANCE, ZONE_MAX_DISTANCE] от цены,
# поэтому фикстуры выводятся из config, а не задаются в долларах: масштаб окна
# зависит от PIP_SIZE, и у разных брокеров он разный.
def offsets(count: int) -> list[float]:
    base = config.ZONE_MIN_DISTANCE * 1.25
    step = config.ZONE_MIN_SEPARATION * 1.5
    return [round(base + step * i, 2) for i in range(count)]


def ladder(below: bool, scores: list[int]) -> list[Zone]:
    sign = -1 if below else 1
    return [z(PRICE + sign * o, s) for o, s in zip(offsets(len(scores)), scores)]


def prices(below: bool, count: int) -> list[float]:
    sign = -1 if below else 1
    return sorted(round(PRICE + sign * o, 2) for o in offsets(count))


def quiet_bar(stamp: str):
    return (stamp, PRICE, PRICE + 1, PRICE - 1, PRICE)


def test_initial_snapshot_has_three_above_and_three_below(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(quiet_bar("2024-01-01T04:00:00"))}
    candidates = ladder(below=True, scores=[16, 15, 14, 13]) + \
        ladder(below=False, scores=[15, 14, 13, 12])
    result = update_snapshot(candidates, data, snap, events)
    assert len(result) == 6
    assert len([item for item in result if item.price < PRICE]) == 3
    assert len([item for item in result if item.price > PRICE]) == 3


def test_fallback_is_marked_when_side_lacks_strong_levels(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(quiet_bar("2024-01-01T04:00:00"))}
    candidates = ladder(below=True, scores=[18, 16, 15]) + \
        ladder(below=False, scores=[14, 9, 8])
    result = update_snapshot(candidates, data, snap, events)
    above = [item for item in result if item.price > PRICE]
    assert len(above) == 3
    assert above[0].is_fallback is False
    assert any(item.is_fallback for item in above)


def test_stronger_candidate_at_same_level_strengthens_zone(tmp_path):
    """Score усиливает уровень на месте, но больше не тянет набор из окна.

    Прежде более сильный далёкий кандидат вытеснял хорошо стоящую зону — именно
    так набор и уезжал из ренжа. Теперь расстояние решает, а score — внутри окна.
    """
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data1 = {"H4": bars(quiet_bar("2024-01-01T00:00:00"))}
    initial = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[11, 12, 13])
    update_snapshot(initial, data1, snap, events)

    data2 = {"H4": bars(quiet_bar("2024-01-01T00:00:00"),
                        quiet_bar("2024-01-01T04:00:00"))}
    stronger = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[17, 12, 13])
    result = update_snapshot(stronger, data2, snap, events)

    above = sorted((item for item in result if item.price > PRICE), key=lambda i: i.price)
    assert [item.price for item in above] == prices(below=False, count=3)
    assert above[0].score == 17, "уровень должен усилиться на месте"
    below = sorted((item for item in result if item.price < PRICE), key=lambda i: i.price)
    assert [item.price for item in below] == prices(below=True, count=3), "другая сторона не тронута"


def test_far_stronger_candidate_does_not_pull_set_out_of_band(tmp_path):
    """Главный регресс клиента: сильная зона далеко от цены не должна вытеснять
    зону, стоящую в запрошенном окне."""
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(quiet_bar("2024-01-01T04:00:00"))}
    far_up = PRICE + config.ZONE_MAX_DISTANCE * 3
    far_down = PRICE - config.ZONE_MAX_DISTANCE * 3
    candidates = ladder(below=True, scores=[13, 12, 11]) + \
        ladder(below=False, scores=[11, 12, 13]) + [z(far_up, 99), z(far_down, 99)]
    result = update_snapshot(candidates, data, snap, events)
    result_prices = [item.price for item in result]
    assert round(far_up, 2) not in result_prices
    assert round(far_down, 2) not in result_prices
    assert len(result) == 6


def test_same_h4_is_idempotent(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(quiet_bar("2024-01-01T04:00:00"))}
    source = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[11, 12, 13])
    initial = update_snapshot(source, data, snap, events)
    extra = z(PRICE + config.ZONE_MAX_DISTANCE * 3, 99)
    again = update_snapshot(source + [extra], data, snap, events)
    assert [item.price for item in again] == [item.price for item in initial]


def test_body_break_removes_zone_and_does_not_readd_same_cycle(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    level = round(PRICE - offsets(1)[0], 2)
    first = {"H4": bars(quiet_bar("2024-01-01T00:00:00"))}
    update_snapshot([z(level, 12)], first, snap, events)
    # Свеча проходит зону телом: открытие выше top, закрытие ниже bottom.
    width = config.ZONE_WIDTH
    broken = {"H4": bars(quiet_bar("2024-01-01T00:00:00"),
                         ("2024-01-01T04:00:00", level + width + 1,
                          level + width + 1.5, level - width - 1,
                          level - width - 0.5))}
    result = update_snapshot([z(level, 20)], broken, snap, events)
    assert all(item.price != level for item in result)
    assert any(json.loads(line)["event"] == "zone_invalidated"
               for line in events.read_text().splitlines())


def test_snapshot_persists_between_calls(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(quiet_bar("2024-01-01T00:00:00"))}
    update_snapshot([z(PRICE - offsets(1)[0], 15)], data, snap, events)
    raw = json.loads(snap.read_text())
    assert raw["version"] == "3.0"
    assert raw["zones"][0]["state"] == "ACTIVE"
