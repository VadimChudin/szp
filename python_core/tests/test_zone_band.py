"""Окно отображения зон: границы задаёт полоса, места — реальные уровни.

Регресс, который эти тесты закрывают:
  1. отбор шёл только по score — уровень мог встать вплотную к цене или уйти
     за горизонт;
  2. попытка чинить это фиксированной лестницей 200-300 пипсов ставила зону
     туда, куда её загоняла арифметика шага, а не туда, где есть кластер теней.

Правильная модель: полоса ограничивает расстояние от цены, внутри полосы
побеждает сила уровня, а расстояние между зонами получается НЕРАВНОМЕРНЫМ.
"""
from __future__ import annotations

import pandas as pd
import pytest

import active_zones
import config
from zone_detector import Zone


PRICE = 3300.00


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
    """Плотная сетка кандидатов по обе стороны от цены, шаг $0.25."""
    zones = []
    for step in range(1, 60):
        for sign in (1, -1):
            zones.append(_zone(0.25 * step * sign,
                               config.MIN_ZONE_SCORE + (step % 5)))
    return zones


def _select(tmp_path, candidates=None) -> list[Zone]:
    return active_zones.update_snapshot(
        _grid() if candidates is None else candidates, _h4_frame(),
        path=tmp_path / "snapshot.json",
        event_path=tmp_path / "events.jsonl",
    )


def test_band_constants_are_consistent():
    """Склейка и ширина зоны обязаны быть мельче зазора, иначе линии сольются."""
    assert config.ZONE_MIN_DISTANCE < config.ZONE_MAX_DISTANCE
    assert config.CLUSTER_TOLERANCE < config.ZONE_MIN_SEPARATION
    assert config.ZONE_WIDTH_MAX * 2 <= config.ZONE_MIN_SEPARATION


def test_every_zone_sits_inside_the_window(tmp_path):
    """Ни одна зона не липнет к цене и ни одна не уходит за горизонт."""
    for zone in _select(tmp_path):
        distance = abs(zone.price - PRICE)
        assert distance >= config.ZONE_MIN_DISTANCE
        assert distance <= config.ZONE_MAX_DISTANCE


def test_zones_do_not_merge_into_one_line(tmp_path):
    selected = _select(tmp_path)
    for above in (True, False):
        side = sorted(z.price for z in selected if (z.price > PRICE) == above)
        for a, b in zip(side, side[1:]):
            assert b - a >= config.ZONE_MIN_SEPARATION


def test_spacing_is_not_forced_to_a_fixed_step(tmp_path):
    """Главная правка: шаг между зонами задаёт рынок, а не арифметика.

    Кандидаты стоят так, что сильные уровни лежат на РАЗНЫХ дистанциях. Набор
    обязан их и взять, а не выровнять по одинаковому шагу.
    """
    candidates = [_zone(2.2, 20), _zone(3.9, 19), _zone(8.4, 18),
                  _zone(-2.6, 20), _zone(-4.3, 19), _zone(-8.8, 18)]
    selected = _select(tmp_path, candidates)
    above = sorted(round(abs(z.price - PRICE), 2) for z in selected if z.price > PRICE)
    gaps = [round(b - a, 2) for a, b in zip(above, above[1:])]
    assert above == [2.2, 3.9, 8.4]
    assert len(set(gaps)) > 1, "шаг обязан быть неравномерным"


def test_strongest_levels_win_inside_the_window(tmp_path):
    """Внутри окна решает сила уровня, а не близость к «идеальному» шагу."""
    candidates = [_zone(2.5, 11), _zone(4.0, 25), _zone(6.5, 24),
                  _zone(-2.5, 11), _zone(-4.0, 25), _zone(-6.5, 24)]
    selected = _select(tmp_path, candidates)
    above = sorted((z for z in selected if z.price > PRICE),
                   key=lambda z: -z.score)
    assert [z.score for z in above[:2]] == [25, 24]


def test_zone_outside_window_is_dropped(tmp_path):
    far = _zone(config.ZONE_MAX_DISTANCE * 3, 99)
    glued = _zone(config.ZONE_MIN_DISTANCE * 0.2, 99)
    selected = _select(tmp_path, _grid() + [far, glued])
    prices = [z.price for z in selected]
    assert far.price not in prices, "зона за горизонтом попала на график"
    assert glued.price not in prices, "зона вплотную к цене попала на график"


def test_empty_side_gives_its_slots_to_the_other(tmp_path):
    """Снизу уровней нет — добираем сверху, но без перегруза графика."""
    candidates = [_zone(2.2, 20), _zone(3.9, 19), _zone(5.6, 18),
                  _zone(7.3, 17), _zone(8.9, 16)]
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
