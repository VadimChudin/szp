"""Окно отображения зон: границы задаёт полоса, места — реальные уровни.

Регресс, который эти тесты закрывают:
  1. отбор шёл только по score — уровень мог встать вплотную к цене или уйти
     за горизонт;
  2. попытка чинить это фиксированной лестницей ставила зону туда, куда её
     загоняла арифметика шага, а не туда, где есть кластер теней.

Все дистанции здесь выводятся из config, а не захардкожены в долларах: масштаб
окна зависит от PIP_SIZE (у разных брокеров разное число знаков в котировке),
и тесты должны проходить при любом его значении.
"""
from __future__ import annotations

import pandas as pd
import pytest

import active_zones
import config
from zone_detector import Zone


PRICE = 4000.00

MIN_D = config.ZONE_MIN_DISTANCE
MAX_D = config.ZONE_MAX_DISTANCE
SEP = config.ZONE_MIN_SEPARATION


def _h4_frame(price: float = PRICE) -> dict:
    """H4 без касаний зон, чтобы инвалидация не мешала проверке отбора."""
    rows = [{
        "time": pd.Timestamp("2026-08-28 00:00:00") + pd.Timedelta(hours=4 * i),
        "open": price, "high": price + 0.05, "low": price - 0.05, "close": price,
    } for i in range(3)]
    return {"H4": pd.DataFrame(rows), "H1": pd.DataFrame(rows)}


def _zone(offset: float, score: int) -> Zone:
    return Zone(price=round(PRICE + offset, 2), width=config.ZONE_WIDTH,
                score=score, sources=[config.PRIMARY_TIMEFRAME])


def _grid() -> list[Zone]:
    """Плотная сетка кандидатов по обе стороны: шаг — четверть зазора."""
    step = SEP / 4.0
    count = int(MAX_D * 1.3 / step)
    zones = []
    for i in range(1, count + 1):
        for sign in (1, -1):
            zones.append(_zone(step * i * sign,
                               config.MIN_ZONE_SCORE + (i % 5)))
    return zones


def _select(tmp_path, candidates=None) -> list[Zone]:
    return active_zones.update_snapshot(
        _grid() if candidates is None else candidates, _h4_frame(),
        path=tmp_path / "snapshot.json",
        event_path=tmp_path / "events.jsonl",
    )


def test_band_constants_are_consistent():
    """Склейка и ширина зоны обязаны быть мельче зазора, иначе линии сольются."""
    assert MIN_D < MAX_D
    assert config.CLUSTER_TOLERANCE <= SEP
    assert config.ZONE_WIDTH_MAX * 2 <= SEP


def test_every_zone_sits_inside_the_window(tmp_path):
    """Ни одна зона не липнет к цене и ни одна не уходит за горизонт."""
    for zone in _select(tmp_path):
        distance = abs(zone.price - PRICE)
        assert distance >= MIN_D
        assert distance <= MAX_D


def test_window_is_symmetric_up_and_down(tmp_path):
    """Окно отсчитывается от цены в КАЖДУЮ сторону независимо."""
    selected = _select(tmp_path)
    for above in (True, False):
        side = [abs(z.price - PRICE) for z in selected if (z.price > PRICE) == above]
        assert side, "сторона не должна быть пустой при симметричных кандидатах"
        assert min(side) >= MIN_D
        assert max(side) <= MAX_D


def test_zones_do_not_merge_into_one_line(tmp_path):
    selected = _select(tmp_path)
    for above in (True, False):
        side = sorted(z.price for z in selected if (z.price > PRICE) == above)
        for a, b in zip(side, side[1:]):
            assert b - a >= SEP


def test_spacing_is_not_forced_to_a_fixed_step(tmp_path):
    """Главная правка: шаг между зонами задаёт рынок, а не арифметика.

    Сильные уровни стоят на РАЗНЫХ дистанциях — набор обязан их и взять,
    а не выровнять по одинаковому шагу.
    """
    offsets = [MIN_D * 1.1, MIN_D * 1.95, MAX_D * 0.93]
    candidates = [_zone(o, 20 - i) for i, o in enumerate(offsets)] + \
                 [_zone(-o, 20 - i) for i, o in enumerate(offsets)]
    selected = _select(tmp_path, candidates)
    above = sorted(round(abs(z.price - PRICE), 2) for z in selected if z.price > PRICE)
    gaps = [round(b - a, 2) for a, b in zip(above, above[1:])]
    assert above == sorted(round(o, 2) for o in offsets)
    assert len(set(gaps)) > 1, "шаг обязан быть неравномерным"


def test_strongest_levels_win_inside_the_window(tmp_path):
    """Внутри окна решает сила уровня, а не близость к «идеальному» шагу."""
    offsets = [MIN_D * 1.25, MIN_D * 2.0, MIN_D * 3.25]
    scores = [11, 25, 24]
    candidates = [_zone(o, s) for o, s in zip(offsets, scores)] + \
                 [_zone(-o, s) for o, s in zip(offsets, scores)]
    selected = _select(tmp_path, candidates)
    above = sorted((z for z in selected if z.price > PRICE), key=lambda z: -z.score)
    assert [z.score for z in above[:2]] == [25, 24]


def test_zone_outside_window_is_dropped(tmp_path):
    far = _zone(MAX_D * 3, 99)
    glued = _zone(MIN_D * 0.2, 99)
    selected = _select(tmp_path, _grid() + [far, glued])
    prices = [z.price for z in selected]
    assert far.price not in prices, "зона за горизонтом попала на график"
    assert glued.price not in prices, "зона вплотную к цене попала на график"


def test_empty_side_gives_its_slots_to_the_other(tmp_path):
    """Снизу уровней нет — добираем сверху, но без перегруза графика."""
    step = SEP * 1.6
    candidates = [_zone(MIN_D * 1.1 + step * i, 20 - i) for i in range(5)]
    selected = _select(tmp_path, candidates)
    above = [z for z in selected if z.price > PRICE]
    assert len(above) == config.ZONE_MAX_PER_SIDE
    assert len(selected) <= config.MAX_ZONES_ON_CHART


def test_balanced_market_keeps_three_and_three(tmp_path):
    selected = _select(tmp_path)
    assert len([z for z in selected if z.price > PRICE]) == config.ZONES_PER_SIDE
    assert len([z for z in selected if z.price < PRICE]) == config.ZONES_PER_SIDE


def test_no_invented_levels_by_default():
    """«Только зоны»: круглые уровни и боксы крупных игроков выключены."""
    assert config.PROJECT_ROUND_LEVELS is False
    assert config.ACCUMULATION_ENABLED is False
