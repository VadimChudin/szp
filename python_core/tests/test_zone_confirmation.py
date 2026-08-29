"""
Тесты слоя подтверждения зон.

Ключевой приём: синтетика строится с ЗАРАНЕЕ ИЗВЕСТНОЙ структурой ликвидности.
Цена подолгу стоит на двух уровнях (там обязан появиться узел объёма) и
проскакивает промежуток между ними (там обязана быть пустота). Если модель
этого не различает — она бесполезна, каким бы правдоподобным ни выглядел
её вывод на реальном графике.

Именно этот тест поймал ошибку нормировки: при делении на медиану строк
пустота получала ×0.96 вместо ×0.20, то есть не отличалась от обычного уровня.
"""

import numpy as np
import pandas as pd
import pytest

import config
from liquidity_source import profile_from_bars, profile_from_ticks
from zone_detector import Zone
from zone_confirmation import (
    check_delta,
    check_freshness,
    check_liquidity_pool,
    check_volume_node,
    confirm_zones,
    find_liquidity_pools,
)


HVN_LOW, HVN_HIGH, LVN_MID = 4000.0, 4100.0, 4050.0


def _structured_candles(seed: int = 7) -> pd.DataFrame:
    """
    Свечи с заданной структурой:
      300 свечей около 4000  → плотный узел
       12 свечей на проходе  → пустота около 4050
      300 свечей около 4100  → плотный узел
    """
    rng = np.random.default_rng(seed)
    rows = []
    t = pd.Timestamp("2026-01-01")
    for centre, count in ((HVN_LOW, 300), (LVN_MID, 12), (HVN_HIGH, 300)):
        for _ in range(count):
            o = centre + rng.normal(0, 4)
            c = centre + rng.normal(0, 4)
            rows.append({
                "time": t,
                "open": o,
                "high": max(o, c) + abs(rng.normal(0, 3)),
                "low": min(o, c) - abs(rng.normal(0, 3)),
                "close": c,
                "tick_volume": float(rng.integers(500, 1500)),
            })
            t += pd.Timedelta(hours=4)
    return pd.DataFrame(rows)


# ── Профиль объёма ───────────────────────────────────────────────────────────

def test_profile_separates_nodes_from_voids():
    """Главная проверка: узел и пустота должны попасть по разные стороны порогов."""
    profile = profile_from_bars(_structured_candles())
    assert profile is not None

    node_low = profile.density_ratio(HVN_LOW - 1, HVN_LOW + 1)
    node_high = profile.density_ratio(HVN_HIGH - 1, HVN_HIGH + 1)
    void = profile.density_ratio(LVN_MID - 1, LVN_MID + 1)

    assert node_low >= config.HVN_RATIO, f"узел 4000 не распознан: ×{node_low:.2f}"
    assert node_high >= config.HVN_RATIO, f"узел 4100 не распознан: ×{node_high:.2f}"
    assert void <= config.LVN_RATIO, f"пустота 4050 не распознана: ×{void:.2f}"


def test_fair_share_normalisation_is_not_median():
    """
    Нормировка на среднюю долю, а не на медиану.

    Медиана в перекошенном профиле садится на хвостовые строки и завышает
    плотность в разы, из-за чего пустота перестаёт быть пустотой. Тест
    закрепляет выбор нормировки, чтобы его не «упростили» обратно.
    """
    profile = profile_from_bars(_structured_candles())
    nonzero = profile.volumes[profile.volumes > 0]

    assert profile.fair_share_volume == pytest.approx(
        profile.volumes.sum() / profile.volumes.size)
    # Именно этот разрыв и ломал детекцию пустоты.
    assert profile.fair_share_volume > float(np.median(nonzero))


def test_poc_lands_on_a_real_node():
    profile = profile_from_bars(_structured_candles())
    assert min(abs(profile.poc - HVN_LOW), abs(profile.poc - HVN_HIGH)) < 15.0


def test_value_area_covers_both_nodes():
    profile = profile_from_bars(_structured_candles())
    val, vah = profile.value_area(0.70)
    assert val < HVN_LOW < HVN_HIGH < vah + 5.0


def test_empty_input_returns_none():
    assert profile_from_bars(pd.DataFrame()) is None
    assert profile_from_bars(None) is None
    assert profile_from_ticks(pd.DataFrame({"price": [1.0, 2.0]})) is None  # < 50 тиков


# ── Дельта по тикам ──────────────────────────────────────────────────────────

def test_delta_recovers_aggressor_side():
    """На 4000 намеренно покупают, на 4100 намеренно продают."""
    rng = np.random.default_rng(3)
    n = 40_000
    price = np.concatenate([rng.normal(HVN_LOW, 3, n // 2),
                            rng.normal(HVN_HIGH, 3, n // 2)])
    direction = np.where(
        price < LVN_MID,
        rng.choice(["BUY", "SELL"], n, p=[0.72, 0.28]),
        rng.choice(["BUY", "SELL"], n, p=[0.28, 0.72]),
    )
    profile = profile_from_ticks(pd.DataFrame(
        {"price": price, "volume": np.ones(n), "direction": direction}))

    assert profile.delta_in_range(HVN_LOW - 2, HVN_LOW + 2) > 0
    assert profile.delta_in_range(HVN_HIGH - 2, HVN_HIGH + 2) < 0


def test_delta_check_rewards_alignment():
    """Поддержка, на которой покупали, должна получить оценку выше нейтрали."""
    rng = np.random.default_rng(11)
    n = 20_000
    price = rng.normal(HVN_LOW, 3, n)
    direction = rng.choice(["BUY", "SELL"], n, p=[0.75, 0.25])
    profile = profile_from_ticks(pd.DataFrame(
        {"price": price, "volume": np.ones(n), "direction": direction}))

    zone = Zone(price=HVN_LOW, width=2.0)
    # Цена выше зоны → зона работает как поддержка → покупки её подтверждают.
    assert check_delta(zone, profile, price=HVN_HIGH).value > 0.5
    # Та же зона над ценой была бы сопротивлением — покупки её опровергают.
    assert check_delta(zone, profile, price=3900.0).value < 0.5


def test_delta_is_neutral_without_aggressor_data():
    profile = profile_from_bars(_structured_candles())
    check = check_delta(Zone(price=HVN_LOW, width=1.0), profile, price=HVN_HIGH)
    assert check.value == 0.5


# ── Пулы ликвидности ─────────────────────────────────────────────────────────

def test_equal_extremes_form_a_pool():
    """Три одинаковых минимума подряд обязаны собраться в один пул."""
    rows = []
    t = pd.Timestamp("2026-01-01")
    for i in range(120):
        # Каждая 20-я свеча уходит ровно на 3990 — равные минимумы.
        low = 3990.0 if i % 20 == 0 else 4010.0 + (i % 7)
        rows.append({"time": t, "open": 4020.0, "high": 4030.0,
                     "low": low, "close": 4025.0, "tick_volume": 1000.0})
        t += pd.Timedelta(hours=4)

    pools = find_liquidity_pools(pd.DataFrame(rows), swing_length=5)
    lows = [p for p in pools if p["kind"] == "low" and abs(p["level"] - 3990.0) < 5]
    assert lows, "равные минимумы не собрались в пул"
    assert lows[0]["touches"] >= 2


def test_single_extreme_is_not_a_pool():
    """Одиночный экстремум — не скопление стопов."""
    rng = np.random.default_rng(5)
    rows = []
    t = pd.Timestamp("2026-01-01")
    for i in range(100):
        base = 4000.0 + i * 2.0  # монотонный тренд, равных экстремумов нет
        rows.append({"time": t, "open": base, "high": base + 5,
                     "low": base - 5, "close": base + 1, "tick_volume": 1000.0})
        t += pd.Timedelta(hours=4)
    pools = find_liquidity_pools(pd.DataFrame(rows), swing_length=5)
    assert all(p["touches"] >= 2 for p in pools)


def test_swept_pool_scores_below_fresh_pool():
    zone = Zone(price=4000.0, width=2.0)
    fresh = [{"kind": "low", "level": 4000.0, "touches": 3, "swept": False, "last_index": 10}]
    swept = [{"kind": "low", "level": 4000.0, "touches": 3, "swept": True, "last_index": 10}]
    assert check_liquidity_pool(zone, fresh).value > check_liquidity_pool(zone, swept).value


def test_absent_pool_is_neutral_not_penalised():
    """Нет пула — не улика против зоны: уровень может держаться на объёме."""
    assert check_liquidity_pool(Zone(price=4000.0, width=2.0), []).value == 0.5


# ── Свежесть ─────────────────────────────────────────────────────────────────

def test_untouched_zone_is_fresher_than_worn_one():
    df = _structured_candles()
    untouched = check_freshness(Zone(price=4500.0, width=1.0), {"H4": df})
    worn = check_freshness(Zone(price=HVN_LOW, width=1.0), {"H4": df})
    assert untouched.value > worn.value
    assert untouched.value == 1.0


def test_consolidation_counts_as_one_approach():
    """Десять свечей внутри зоны — это один подход, а не десять."""
    rows = []
    t = pd.Timestamp("2026-01-01")
    for i in range(60):
        inside = 20 <= i < 30            # непрерывный заход в зону
        centre = 4000.0 if inside else 4200.0
        rows.append({"time": t, "open": centre, "high": centre + 2,
                     "low": centre - 2, "close": centre, "tick_volume": 1000.0})
        t += pd.Timedelta(hours=4)

    check = check_freshness(Zone(price=4000.0, width=3.0), {"H4": pd.DataFrame(rows)})
    assert "подходов к зоне: 1" in check.detail


# ── Режимы работы ────────────────────────────────────────────────────────────

def _three_zones():
    return [Zone(price=HVN_LOW, width=1.0, score=12),
            Zone(price=LVN_MID, width=1.0, score=12),
            Zone(price=HVN_HIGH, width=1.0, score=11)]


def test_off_mode_does_not_touch_zones(monkeypatch):
    monkeypatch.setattr(config, "CONFIRMATION_MODE", "off")
    zones = _three_zones()
    out = confirm_zones(zones, {"H4": _structured_candles()})
    assert out is zones
    assert all(z.confirmation == {} for z in out)


def test_annotate_mode_keeps_every_zone(monkeypatch):
    """Режим по умолчанию обязан быть безопасным: считает, но не выбрасывает."""
    monkeypatch.setattr(config, "CONFIRMATION_MODE", "annotate")
    df = _structured_candles()
    out = confirm_zones(_three_zones(), {"H4": df},
                        profile=profile_from_bars(df))
    assert len(out) == 3
    assert all(z.confirm_verdict in {"LIVE", "WATCH", "DEAD"} for z in out)
    assert all(z.confirmation["checks"] for z in out)


def test_zone_in_the_void_is_marked_dead(monkeypatch):
    monkeypatch.setattr(config, "CONFIRMATION_MODE", "annotate")
    df = _structured_candles()
    out = confirm_zones(_three_zones(), {"H4": df}, profile=profile_from_bars(df))
    by_price = {z.price: z for z in out}

    assert by_price[LVN_MID].confirm_verdict == "DEAD"
    assert by_price[HVN_LOW].confirm_score > by_price[LVN_MID].confirm_score
    assert by_price[HVN_HIGH].confirm_score > by_price[LVN_MID].confirm_score


def test_filter_mode_drops_dead_zones(monkeypatch):
    monkeypatch.setattr(config, "CONFIRMATION_MODE", "filter")
    df = _structured_candles()
    out = confirm_zones(_three_zones(), {"H4": df}, profile=profile_from_bars(df))
    assert LVN_MID not in [z.price for z in out]


def test_filter_never_returns_an_empty_chart(monkeypatch):
    """
    Если порог отсекает всё, отдаём исходный список.

    Пустой график хуже неподтверждённых зон: трейдер остаётся вообще без
    ориентиров и не понимает, сломался индикатор или рынок такой.
    """
    monkeypatch.setattr(config, "CONFIRMATION_MODE", "filter")
    monkeypatch.setattr(config, "CONFIRM_DEAD_THRESHOLD", 0.99)
    monkeypatch.setattr(config, "CONFIRM_LIVE_THRESHOLD", 0.999)
    df = _structured_candles()
    out = confirm_zones(_three_zones(), {"H4": df}, profile=profile_from_bars(df))
    assert len(out) == 3


def test_rerank_mode_preserves_all_zones(monkeypatch):
    monkeypatch.setattr(config, "CONFIRMATION_MODE", "rerank")
    df = _structured_candles()
    out = confirm_zones(_three_zones(), {"H4": df}, profile=profile_from_bars(df))
    assert len(out) == 3
    ranks = [z.score * (0.5 + z.confirm_score) for z in out]
    assert ranks == sorted(ranks, reverse=True)


def test_confirmation_never_changes_structural_score(monkeypatch):
    """
    Инвариант: слой подтверждения не трогает score.

    score отвечает на вопрос «насколько уровень значим структурно»,
    confirmation — «жив ли он сейчас». Смешение этих измерений в одно число
    скрыло бы случай «сильный уровень в мёртвой зоне».
    """
    monkeypatch.setattr(config, "CONFIRMATION_MODE", "annotate")
    df = _structured_candles()
    zones = _three_zones()
    before = [z.score for z in zones]
    confirm_zones(zones, {"H4": df}, profile=profile_from_bars(df))
    assert [z.score for z in zones] == before


def test_zone_serialises_confirmation_roundtrip(monkeypatch):
    monkeypatch.setattr(config, "CONFIRMATION_MODE", "annotate")
    df = _structured_candles()
    zone = confirm_zones([Zone(price=HVN_LOW, width=1.0, score=12)],
                         {"H4": df}, profile=profile_from_bars(df))[0]

    restored = Zone.from_dict(zone.to_dict())
    assert restored.confirm_verdict == zone.confirm_verdict
    assert restored.confirm_score == zone.confirm_score
    assert restored.confirmation == zone.confirmation


def test_missing_profile_degrades_to_neutral():
    """Нет источника ликвидности — зоны проходят, оценки нейтральные."""
    zone = Zone(price=HVN_LOW, width=1.0)
    assert check_volume_node(zone, None).value == 0.5
    assert check_delta(zone, None, price=HVN_HIGH).value == 0.5
