"""
Тесты детерминированного пересчёта (DETERMINISTIC_RECALC).

Сценарий-оригинал из жалобы клиентов: один и тот же брокер, одна версия
сборки — а зоны у всех разные. Причина: снапшот был инкрементальным (старые
зоны держали слоты), тиковая история копилась локально, и состав зависел от
того, когда клиент запустил сборку. Детермин-режим делает закрытие H4
полной пересборкой из свежей детекции: одинаковый вход → одинаковый выход
у всех клиентов, при этом внутри бара снапшот по-прежнему кэшируется и
график не дёргается.
"""

import sys
import types

import pandas as pd
import pytest

import config
from active_zones import update_snapshot
from zone_detector import Zone, detect_zones


def bars(*rows):
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def z(price, score):
    return Zone(price=price, width=1.0, score=score, sources=["H4"])


PRICE = 4000.0


def offsets(count):
    base = (config.ZONE_NEAREST_MIN + config.ZONE_NEAREST_MAX) / 2.0
    step = (config.ZONE_GAP_MIN + config.ZONE_GAP_MAX) / 2.0
    return [round(base + step * i, 2) for i in range(count)]


def ladder(below, scores):
    sign = -1 if below else 1
    return [z(round(PRICE + sign * off, 2), s)
            for off, s in zip(offsets(len(scores)), scores)]


CANDIDATES = ladder(below=True, scores=[16, 15, 14, 13]) + \
    ladder(below=False, scores=[15, 14, 13, 12])


@pytest.fixture
def deterministic(monkeypatch):
    monkeypatch.setattr(config, "DETERMINISTIC_RECALC", True)


def _candidates():
    import copy
    return [copy.deepcopy(c) for c in CANDIDATES]


def test_new_h4_rebuilds_ignoring_carried_zones(tmp_path, deterministic):
    """
    Клиент A живёт со вчерашнего дня (в снапшоте старые зоны), клиент B
    поставил сборку минуту назад. На новой H4 оба обязаны получить
    ОДИНАКОВЫЙ набор — старые зоны не должны влиять на слоты.
    """
    snap_a = tmp_path / "snap_a.json"
    old_bar = bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))
    stale_candidates = ladder(below=True, scores=[9, 9, 9]) + \
        ladder(below=False, scores=[9, 9, 9])
    update_snapshot(stale_candidates, {"H4": old_bar}, snap_a,
                    tmp_path / "ev.jsonl")

    # Новая H4-свеча — у обоих клиентов одинаковые свежие кандидаты.
    new_bar = bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE),
                   ("2024-01-01T08:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))
    client_a = update_snapshot(_candidates(), {"H4": new_bar}, snap_a,
                               tmp_path / "ev.jsonl")

    snap_b = tmp_path / "snap_b.json"  # свежая установка — истории нет
    client_b = update_snapshot(_candidates(), {"H4": new_bar}, snap_b,
                               tmp_path / "ev.jsonl")

    assert sorted(z.price for z in client_a) == sorted(z.price for z in client_b)
    assert len(client_a) == 6


def test_same_h4_bar_keeps_cache(tmp_path, deterministic):
    """Стабильность внутри бара не ломается: тот же H4 — тот же снапшот."""
    snap = tmp_path / "snap.json"
    data = {"H4": bars(("2024-01-01T04:00:00", PRICE, PRICE + 1,
                        PRICE - 1, PRICE))}
    first = update_snapshot(_candidates(), data, snap, tmp_path / "ev.jsonl")
    # Другие кандидаты на том же баре не должны дёргать график.
    weaker = ladder(below=True, scores=[8, 8, 8]) + \
        ladder(below=False, scores=[8, 8, 8])
    second = update_snapshot(weaker, data, snap, tmp_path / "ev.jsonl")
    assert [z.price for z in first] == [z.price for z in second]


def test_carry_still_available_when_disabled(tmp_path, monkeypatch):
    """Старое инкрементальное поведение доступно флагом off."""
    monkeypatch.setattr(config, "DETERMINISTIC_RECALC", False)
    snap = tmp_path / "snap.json"
    bar1 = bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))
    first = update_snapshot(_candidates(), {"H4": bar1}, snap,
                            tmp_path / "ev.jsonl")
    bar2 = bars(("2024-01-01T04:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE),
                ("2024-01-01T08:00:00", PRICE, PRICE + 1, PRICE - 1, PRICE))
    # В carry-режиме пересчёта по расписанию тут нет — зоны удерживаются.
    second = update_snapshot([], {"H4": bar2}, snap, tmp_path / "ev.jsonl")
    assert len(second) >= len(first) - 0  # перенос, а не сброс


# ── Детектор: POC-бонусы не должны зависеть от аптайма клиента ──────────────

@pytest.fixture
def fake_footprint(monkeypatch):
    calls = []
    fake = types.ModuleType("footprint_data")

    def get_collector():
        calls.append(1)
        return types.SimpleNamespace(buffers={})

    fake.get_collector = get_collector
    monkeypatch.setitem(sys.modules, "footprint_data", fake)
    return calls


def _detect():
    t = pd.Timestamp("2024-01-01")
    rows = []
    for i in range(120):
        o = 4000 + (i % 7) - 3
        rows.append({"time": t + pd.Timedelta(hours=4 * i), "open": o,
                     "high": o + 3, "low": o - 3, "close": o + 1,
                     "tick_volume": 1000.0})
    df = pd.DataFrame(rows)
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        detect_zones({"H4": df}, None, limit_output=False)


def test_footprint_skipped_when_deterministic(monkeypatch, fake_footprint):
    monkeypatch.setattr(config, "DETERMINISTIC_RECALC", True)
    monkeypatch.setattr(config, "INCLUDE_FOOTPRINT_POC", True)
    _detect()
    assert fake_footprint == [], "POC-коллектор не должен опрашиваться"


def test_footprint_used_when_allowed(monkeypatch, fake_footprint):
    monkeypatch.setattr(config, "DETERMINISTIC_RECALC", False)
    monkeypatch.setattr(config, "INCLUDE_FOOTPRINT_POC", True)
    _detect()
    assert fake_footprint, "в обычном режиме POC-уровни участвуют"
