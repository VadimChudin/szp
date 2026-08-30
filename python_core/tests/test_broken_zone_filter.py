"""
Тесты фильтра пробитых уровней (filter_broken_zones).

Сценарий-оригинал взят с живого графика: одна гигантская медвежья свеча H4
прошила сразу три старых уровня поддержки, а детектор честно вернул их снова —
на графике стояли «затычки»: линии, через которые цена уже прошла телом.
Фильтр закрывает дыру между контрактом «пробой телом = зоны нет» (он работал
только для видимого снапшота) и кандидатами детектора.
"""

import pandas as pd
import pytest

import config
from zone_detector import Zone, filter_broken_zones


def _bars(rows):
    """rows: (open, high, low, close); время — подряд по 4 часа."""
    t = pd.Timestamp("2026-06-01")
    out = []
    for op, hi, lo, cl in rows:
        out.append({"time": t, "open": op, "high": hi, "low": lo,
                    "close": cl, "tick_volume": 1000.0})
        t += pd.Timedelta(hours=4)
    return pd.DataFrame(out)


def _touched_zone(price: float, touch_time) -> Zone:
    zone = Zone(price=price, width=2.0, score=12)
    zone.wick_points.append({"time": touch_time, "price": price,
                             "wick_type": "lower", "tf": "H4"})
    return zone


def test_body_broken_zone_is_removed():
    """Проход телом после последнего касания = уровень съеден."""
    zone = _touched_zone(4508.0, pd.Timestamp("2026-06-01 00:00"))
    df = _bars([
        (4508.0, 4512.0, 4504.0, 4509.0),   # касание, отбой — бар 0 (после него touch)
        (4510.0, 4515.0, 4506.0, 4511.0),   # обычный бар над зоной
        (4550.0, 4555.0, 4455.0, 4460.0),   # обвал: тело прошило зону насквозь
        (4462.0, 4470.0, 4455.0, 4465.0),   # цена осталась ниже
    ])
    kept = filter_broken_zones([zone], df)
    assert kept == [], "уровень, прошитый телом H4, не должен возвращаться"


def test_wick_penetration_is_not_a_break():
    """Тень зашла за зону, но тело не прошло — контракт это не пробой."""
    zone = _touched_zone(4508.0, pd.Timestamp("2026-06-01 00:00"))
    df = _bars([
        (4510.0, 4515.0, 4506.0, 4511.0),
        (4512.0, 4514.0, 4498.0, 4509.0),   # тень до 4498, тело выдержало
    ])
    assert filter_broken_zones([zone], df) == [zone]


def test_reclaimed_zone_survives():
    """Прошили вниз, потом телом вернулись наверх — уровень возвращён."""
    zone = _touched_zone(4508.0, pd.Timestamp("2026-06-01 00:00"))
    df = _bars([
        (4510.0, 4515.0, 4506.0, 4511.0),
        (4511.0, 4513.0, 4490.0, 4495.0),   # пробой вниз
        (4495.0, 4520.0, 4492.0, 4516.0),   # телом обратно через зону (reclaim)
    ])
    assert filter_broken_zones([zone], df) == [zone]


def test_break_before_last_touch_is_irrelevant():
    """Пробой ДО последнего касания ничего не значит: уровень потом отработал."""
    zone = _touched_zone(4508.0, pd.Timestamp("2026-06-01 08:00"))
    df = _bars([
        (4510.0, 4514.0, 4490.0, 4495.0),   # пробой вниз (бар 0)
        (4495.0, 4518.0, 4493.0, 4514.0),   # возврат (бар 1)
        (4512.0, 4516.0, 4505.0, 4513.0),   # бар 2 — здесь последнее касание
        (4513.0, 4517.0, 4507.0, 4512.0),   # после касания пробоя нет
    ])
    assert filter_broken_zones([zone], df) == [zone]


def test_zone_without_wick_points_is_untouched():
    """Внешние/проецируемые зоны проверять нечем — не трогаем."""
    zone = Zone(price=4508.0, width=2.0, score=7)
    df = _bars([(4550.0, 4555.0, 4455.0, 4460.0)])
    assert filter_broken_zones([zone], df) == [zone]


def test_empty_history_keeps_everything():
    zone = _touched_zone(4508.0, pd.Timestamp("2026-06-01 00:00"))
    assert filter_broken_zones([zone], pd.DataFrame()) == [zone]
    assert filter_broken_zones([zone], None) == [zone]


def test_untouched_zone_below_price_survives():
    """Обычный рабочий случай: зона под ценой, пробоев не было — остаётся."""
    zone = _touched_zone(4425.0, pd.Timestamp("2026-06-01 00:00"))
    df = _bars([
        (4430.0, 4435.0, 4424.0, 4432.0),
        (4432.0, 4440.0, 4430.0, 4438.0),
        (4438.0, 4450.0, 4435.0, 4448.0),
    ])
    assert filter_broken_zones([zone], df) == [zone]
