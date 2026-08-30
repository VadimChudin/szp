import json

import pandas as pd
import pytest

import config
import active_zones
from active_zones import update_snapshot
from zone_detector import Zone


@pytest.fixture(autouse=True)
def _carry_mode(monkeypatch):
    """Эти тесты проверяют инкрементальную carry-механику снапшота —
    закрепляем её явно: DETERMINISTIC_RECALC по умолчанию включён и
    пересобирает снапшот на каждой новой H4-свече без переноса. Детермин-
    режим покрыт в test_deterministic_recalc.py."""
    monkeypatch.setattr(config, "DETERMINISTIC_RECALC", False)


def bars(*rows):
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def z(price, score):
    return Zone(price=price, width=1.0, score=score, sources=["H4"])


PRICE = 4000.0


# Зоны отбираются лестницей внутри полосы 200-300 пипсов от цены, поэтому
# фикстуры выводятся из config: первый слот ~250 пипсов от цены и дальше тот же шаг.
def offsets(count: int) -> list[float]:
    base = (config.ZONE_NEAREST_MIN + config.ZONE_NEAREST_MAX) / 2.0
    step = (config.ZONE_GAP_MIN + config.ZONE_GAP_MAX) / 2.0
    return [round(base + step * i, 2) for i in range(count)]


def ladder(below: bool, scores: list[int]) -> list[Zone]:
    sign = -1 if below else 1
    return [z(round(PRICE + sign * off, 2), score) for off, score in zip(offsets(len(scores)), scores)]


def test_initial_snapshot_has_three_above_and_three_below(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    candidates = ladder(below=True, scores=[16, 15, 14, 13]) + \
        ladder(below=False, scores=[15, 14, 13, 12])
    result = update_snapshot(candidates, data, snap, events)
    assert len(result) == 6
    assert len([item for item in result if item.price < PRICE]) == 3
    assert len([item for item in result if item.price > PRICE]) == 3


def test_fallback_is_marked_when_side_lacks_strong_levels(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    candidates = ladder(below=True, scores=[18, 16, 15]) + \
        ladder(below=False, scores=[14, 9, 8])
    result = update_snapshot(candidates, data, snap, events)
    above = [item for item in result if item.price > PRICE]
    assert len(above) == 3
    assert above[0].is_fallback is False
    assert any(item.is_fallback for item in above)


def test_stronger_candidate_at_same_level_strengthens_zone(tmp_path):
    """Score усиливает уровень на месте, но больше не тянет набор из полосы.

    Прежде более сильный далёкий кандидат вытеснял хорошо стоящую зону — именно
    так набор и уезжал из ренжа. Теперь расстояние решает, а score — внутри слота.
    """
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data1 = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    initial = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[11, 12, 13])
    update_snapshot(initial, data1, snap, events)

    data2 = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE),
                        ("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    stronger = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[17, 12, 13])
    result = update_snapshot(stronger, data2, snap, events)

    above = sorted((item for item in result if item.price > PRICE), key=lambda item: item.price)
    expected_above = [round(PRICE + off, 2) for off in offsets(3)]
    assert [item.price for item in above] == expected_above
    assert above[0].score == 17, "уровень должен усилиться на месте"
    below = sorted((item for item in result if item.price < PRICE), key=lambda item: item.price)
    expected_below = sorted(round(PRICE - off, 2) for off in offsets(3))
    assert [item.price for item in below] == expected_below, "другая сторона не тронута"


def test_far_stronger_candidate_does_not_pull_set_out_of_band(tmp_path):
    """Главный регресс клиента: сильная зона далеко от цены не должна вытеснять
    зону, стоящую в запрошенном ренже."""
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    far_up = round(PRICE + config.ZONE_BAND_OUTER_MAX * 2, 2)
    far_down = round(PRICE - config.ZONE_BAND_OUTER_MAX * 2, 2)
    candidates = ladder(below=True, scores=[13, 12, 11]) + \
        ladder(below=False, scores=[11, 12, 13]) + [z(far_up, 99), z(far_down, 99)]
    result = update_snapshot(candidates, data, snap, events)
    prices = [item.price for item in result]
    assert far_up not in prices and far_down not in prices
    assert len(result) == 6


def test_same_h4_is_idempotent(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    source = ladder(below=True, scores=[11, 12, 13]) + ladder(below=False, scores=[11, 12, 13])
    initial = update_snapshot(source, data, snap, events)
    again = update_snapshot(source + [z(round(PRICE + config.ZONE_BAND_OUTER_MAX * 2, 2), 99)], data, snap, events)
    assert [item.price for item in again] == [item.price for item in initial]


def test_body_break_removes_zone_and_does_not_readd_same_cycle(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    level = round(PRICE - offsets(1)[0], 2)
    first = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    update_snapshot([z(level, 12)], first, snap, events)
    # Свеча проходит зону телом: открытие выше top, закрытие ниже bottom.
    broken = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE),
                         ("2024-01-01T04:00:00", level + 2.0, level + 2.5, level - 2.0, level - 1.5))}
    result = update_snapshot([z(level, 20)], broken, snap, events)
    assert all(item.price != level for item in result)
    assert any(json.loads(line)["event"] == "zone_invalidated" for line in events.read_text().splitlines())


def test_snapshot_persists_between_calls(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    update_snapshot([z(round(PRICE - offsets(1)[0], 2), 15)], data, snap, events)
    raw = json.loads(snap.read_text())
    assert raw["version"] == active_zones.SNAPSHOT_VERSION
    assert raw["zones"][0]["state"] == "ACTIVE"


def test_touch_does_not_remove_zone_by_default(tmp_path):
    """Касание ≠ пробой: зона живёт после теста (клиентский регресс «нет зон снизу»)."""
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    level = round(PRICE - offsets(1)[0], 2)
    first = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    update_snapshot([z(level, 12)], first, snap, events)
    # Тень задела зону, тело не пробило — зона обязана остаться.
    touched = {"H4": bars(("2024-01-01T00:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE),
                          ("2024-01-01T04:00:00", PRICE, PRICE + 0.5, level - 0.5, PRICE - 1))}
    result = update_snapshot([z(level, 12)], touched, snap, events)
    assert any(item.price == level for item in result)


def test_empty_side_filled_with_extended_candidates(tmp_path):
    """В полосе снизу уровней нет — сторона добирается ближайшими реальными EXT."""
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    far_below = [z(round(PRICE - config.ZONE_BAND_OUTER_MAX * (1.5 + i), 2), 12 + i) for i in range(3)]
    candidates = ladder(below=False, scores=[15, 14, 13]) + far_below
    result = update_snapshot(candidates, data, snap, events)
    below = [item for item in result if item.price < PRICE]
    assert len(below) == config.ZONES_PER_SIDE
    assert all(item.is_fallback for item in below)
    assert any(json.loads(line)["event"] == "zone_added_extended"
               for line in events.read_text().splitlines())


def test_stale_snapshot_out_of_band_rebuilds_immediately(tmp_path):
    """Регресс клиента: снапшот старой сборки (зоны вплотную к цене, все сверху)
    не должен дожить до следующей H4-свечи — пересчёт сразу."""
    import config as cfg
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    # Имитация снапшота от старой сборки: зона в $2 от цены (вне полосы).
    stale = {"version": active_zones.SNAPSHOT_VERSION, "last_h4": "2024-01-01T04:00:00",
             "zones": [z(PRICE + 2.0, 20).to_dict()]}
    snap.write_text(json.dumps(stale))
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    candidates = ladder(below=True, scores=[13, 12, 11]) + ladder(below=False, scores=[11, 12, 13])
    result = update_snapshot(candidates, data, snap, events)
    assert all(abs(item.price - PRICE) >= cfg.ZONE_NEAREST_MIN * (1 - cfg.ZONE_BAND_TOLERANCE)
               for item in result), "протухшая зона вне полосы выжила"
    assert any(json.loads(line)["event"] == "snapshot_stale_band"
               for line in events.read_text().splitlines())


def test_foreign_version_snapshot_is_discarded(tmp_path):
    snap, events = tmp_path / "snapshot.json", tmp_path / "events.jsonl"
    stale = {"version": "2.9", "last_h4": "2024-01-01T04:00:00",
             "zones": [z(PRICE + 2.0, 20).to_dict()]}
    snap.write_text(json.dumps(stale))
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))}
    candidates = ladder(below=True, scores=[13, 12, 11]) + ladder(below=False, scores=[11, 12, 13])
    result = update_snapshot(candidates, data, snap, events)
    assert len(result) == 6
    assert any(json.loads(line)["event"] == "snapshot_version_reset"
               for line in events.read_text().splitlines())
