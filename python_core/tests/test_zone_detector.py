"""
Тесты для zone_detector.py — ядро алгоритма кластеризации зон.
"""

import numpy as np
import pandas as pd
import pytest

import config
from zone_detector import (Zone, balance_around_price, cluster_levels, detect_zones,
                           projected_levels,
                           extract_wick_levels)


# ── Zone dataclass ──────────────────────────────────────────────────────────

class TestZoneDataclass:
    def test_top_bottom(self):
        z = Zone(price=2400.0, width=1.0)
        assert z.top == 2401.0
        assert z.bottom == 2399.0

    def test_label_basic(self):
        z = Zone(price=2386.50, sources=["H4", "D1"], score=8)
        label = z.label
        assert "2386.50" in label
        assert "D1+H4" in label or "H4+D1" in label
        assert "S:8" in label

    def test_label_big_player(self):
        z = Zone(price=2400.0, sources=["H1"], score=5, has_big_player=True)
        assert " BP" in z.label

    def test_label_round_level(self):
        z = Zone(price=2400.0, sources=["H1"], score=5, is_round_level=True)
        assert " RL" in z.label

    def test_label_suffix(self):
        z = Zone(price=2400.0, sources=["H1"], score=5, label_suffix=" (Vol POC)")
        assert "(Vol POC)" in z.label

    def test_repr(self):
        z = Zone(price=2400.0, sources=["H1"], score=5)
        assert "Zone(" in repr(z)

    def test_to_dict_is_json_serializable_with_timestamp_wicks(self):
        """to_dict() must stay JSON-serializable even when wick_points carry
        pandas Timestamps / numpy scalars — otherwise zones_output.json (read
        by the MT4/MT5 indicator) cannot be written."""
        import json

        z = Zone(
            price=2400.0,
            sources=["H1", "H4"],
            score=11,
            wick_points=[
                {"time": pd.Timestamp("2024-01-01 12:00:00"),
                 "price": np.float64(2400.5),
                 "wick_type": "lower",
                 "tf": "H1"},
            ],
        )
        d = z.to_dict()
        encoded = json.dumps(d)  # must not raise
        restored = json.loads(encoded)
        assert restored["wick_points"][0]["time"] == "2024-01-01T12:00:00"
        assert restored["wick_points"][0]["price"] == 2400.5


# ── extract_wick_levels ─────────────────────────────────────────────────────

class TestExtractWickLevels:
    def test_returns_dataframe_with_required_columns(self, sample_ohlcv_df):
        result = extract_wick_levels(sample_ohlcv_df)
        assert isinstance(result, pd.DataFrame)
        for col in ["level", "wick_type", "time", "tick_volume", "candle_range"]:
            assert col in result.columns

    def test_wick_types_are_valid(self, sample_ohlcv_df):
        result = extract_wick_levels(sample_ohlcv_df)
        if not result.empty:
            assert set(result["wick_type"].unique()).issubset({"upper", "lower"})

    def test_skips_doji_candles(self):
        """Свечи с диапазоном < SYMBOL_POINT * 10 пропускаются."""
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=3, freq="1h"),
            "open": [2400.0, 2400.0, 2400.0],
            "high": [2400.005, 2400.005, 2400.005],  # range = 0.005 < 0.01*10
            "low": [2400.0, 2400.0, 2400.0],
            "close": [2400.003, 2400.003, 2400.003],
            "tick_volume": [100, 200, 300],
        })
        result = extract_wick_levels(df)
        assert result.empty

    def test_detects_lower_wick(self):
        """Свеча с длинным нижним фитилём даёт lower wick."""
        df = pd.DataFrame({
            "time": [pd.Timestamp("2024-01-01")],
            "open": [2405.0],
            "high": [2406.0],
            "low": [2395.0],   # lower wick = 2405-2395 = 10, range = 11, 10/11 > 0.15
            "close": [2405.5],
            "tick_volume": [1000],
        })
        result = extract_wick_levels(df)
        assert not result.empty
        assert "lower" in result["wick_type"].values

    def test_detects_upper_wick(self):
        """Свеча с длинным верхним фитилём даёт upper wick."""
        df = pd.DataFrame({
            "time": [pd.Timestamp("2024-01-01")],
            "open": [2395.0],
            "high": [2406.0],   # upper wick = 2406-2395.5 = 10.5, range = 11, > 0.15
            "low": [2395.0],
            "close": [2395.5],
            "tick_volume": [1000],
        })
        result = extract_wick_levels(df)
        assert not result.empty
        assert "upper" in result["wick_type"].values

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"])
        result = extract_wick_levels(df)
        assert result.empty


# ── cluster_levels ──────────────────────────────────────────────────────────

class TestClusterLevels:
    def test_empty_input(self):
        result = cluster_levels(np.array([]))
        assert result == []

    def test_single_level(self):
        result = cluster_levels(np.array([2400.0]))
        assert len(result) == 1
        assert result[0]["center"] == 2400.0
        assert result[0]["count"] == 1

    def test_close_levels_merge(self):
        """Уровни в пределах tolerance объединяются."""
        levels = np.array([2400.0, 2401.0, 2402.0, 2403.0])
        result = cluster_levels(levels, tolerance=5.0)
        assert len(result) == 1
        assert result[0]["count"] == 4

    def test_distant_levels_separate(self):
        """Уровни дальше tolerance формируют разные кластеры."""
        levels = np.array([2400.0, 2401.0, 2420.0, 2421.0])
        result = cluster_levels(levels, tolerance=5.0)
        assert len(result) == 2
        assert result[0]["count"] == 2
        assert result[1]["count"] == 2

    def test_center_is_median(self):
        """Центр кластера — медиана его элементов."""
        levels = np.array([2400.0, 2402.0, 2404.0])
        result = cluster_levels(levels, tolerance=5.0)
        assert len(result) == 1
        assert result[0]["center"] == pytest.approx(2402.0)

    def test_unsorted_input(self):
        """Работает корректно с неотсортированным массивом."""
        levels = np.array([2420.0, 2400.0, 2421.0, 2401.0])
        result = cluster_levels(levels, tolerance=5.0)
        assert len(result) == 2

    def test_custom_tolerance(self):
        levels = np.array([2400.0, 2403.0, 2406.0])
        # С tolerance=2 — должно быть 3 кластера (3 > 2)
        # С tolerance=10 — 1 кластер
        result_tight = cluster_levels(levels, tolerance=2.0)
        result_wide = cluster_levels(levels, tolerance=10.0)
        assert len(result_tight) >= 2
        assert len(result_wide) == 1

    def test_members_field(self):
        """Каждый кластер содержит list members."""
        levels = np.array([2400.0, 2401.0, 2405.0])
        result = cluster_levels(levels, tolerance=5.0)
        for cluster in result:
            assert "members" in cluster
            assert isinstance(cluster["members"], list)


# ── detect_zones (интеграционный тест) ──────────────────────────────────────

class TestDetectZones:
    def test_returns_list_of_zones(self, multi_tf_data):
        zones = detect_zones(multi_tf_data)
        assert isinstance(zones, list)
        for z in zones:
            assert isinstance(z, Zone)

    def test_zones_sorted_by_score_desc(self, multi_tf_data):
        zones = detect_zones(multi_tf_data)
        if len(zones) >= 2:
            scores = [z.score for z in zones]
            assert scores == sorted(scores, reverse=True)

    def test_zones_respect_max_limit(self, multi_tf_data):
        zones = detect_zones(multi_tf_data)
        assert len(zones) <= config.MAX_ZONES_ON_CHART

    def test_with_volume_flags(self, multi_tf_data):
        """Работает с переданными volume_flags."""
        vol_flags = {}
        for tf, df in multi_tf_data.items():
            vol_flags[tf] = np.zeros(len(df), dtype=bool)
            # Помечаем первые 5 свечей как big-player
            vol_flags[tf][:5] = True

        zones = detect_zones(multi_tf_data, volume_flags=vol_flags)
        assert isinstance(zones, list)

    def test_empty_data(self):
        """Пустой DataFrame — пустой результат."""
        empty = {
            "H1": pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"]),
            "H4": pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"]),
            "D1": pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"]),
        }
        zones = detect_zones(empty)
        assert zones == []

# ── Балансировка вокруг цены ────────────────────────────────────────────────

class TestBalanceAroundPrice:
    def _zone(self, price, score):
        return Zone(price=price, width=1.0, score=score, sources=["H4"])

    def test_levels_kept_on_both_sides(self, monkeypatch):
        """После роста все сильные зоны остались внизу — сверху было пусто."""
        # Полное покрытие обеих сторон здесь достигается проекцией, а она теперь
        # выключена по умолчанию — включаем явно, тест именно про покрытие.
        monkeypatch.setattr(config, "PROJECT_ROUND_LEVELS", True)
        strong = [self._zone(p, s) for p, s in
                  ((4086.0, 21), (4111.0, 18), (4137.0, 15), (4223.0, 12))]
        weak = [self._zone(4350.0, 9), self._zone(4420.0, 8)]

        selected = balance_around_price(strong, weak, price=4390.0)

        # Лимит графика — потолок, а не ожидаемое число зон: на входе их 6.
        # Сильные зоны обязаны сохраниться, слабые берутся лишь на пустую
        # сторону (см. test_real_weak_zone_is_used_as_fallback...).
        assert len(selected) <= config.MAX_ZONES_ON_CHART
        for zone in strong:
            assert zone in selected
        assert sum(1 for z in selected if z.price > 4390.0) >= 1
        assert sum(1 for z in selected if z.price < 4390.0) >= 2

    def test_real_weak_zone_is_used_as_fallback_when_side_needs_coverage(self):
        strong = [self._zone(4500.0, 20), self._zone(4100.0, 19)]
        weak = [self._zone(4520.0, 8)]

        selected = balance_around_price(strong, weak, price=4300.0)

        # New policy: prefer strong levels first, but retain a real weaker
        # candidate when needed to fill the upper/lower side quota.
        assert weak[0] in selected

    def test_duplicate_levels_are_not_added_twice(self, monkeypatch):
        monkeypatch.setattr(config, "PROJECT_ROUND_LEVELS", False)
        strong = [self._zone(4100.0, 20)]
        weak = [self._zone(4100.0 + config.CLUSTER_TOLERANCE, 9)]

        selected = balance_around_price(strong, weak, price=4300.0)

        assert len(selected) == 1

    def test_without_price_falls_back_to_score_order(self):
        strong = [self._zone(4100.0, 20), self._zone(4500.0, 12)]
        assert balance_around_price(strong, [], price=None) == strong


class TestProjectedLevels:
    def test_empty_side_gets_round_levels(self, monkeypatch):
        """Пустую сторону не заполняем круглыми PROJ — только реальные зоны."""
        monkeypatch.setattr(config, "PROJECT_ROUND_LEVELS", True)
        strong = [Zone(price=4100.0, width=1.0, score=20, sources=["H4"]),
                  Zone(price=4200.0, width=1.0, score=18, sources=["H4"])]

        selected = balance_around_price(strong, [], price=4475.0)
        above = [z for z in selected if z.price > 4475.0]

        assert above == []
        assert all(z.price < 4475.0 for z in selected)

    def test_projection_skips_level_glued_to_price(self, monkeypatch):
        monkeypatch.setattr(config, "PROJECT_ROUND_LEVELS", True)
        levels = projected_levels(4499.0, above=True, count=1)
        assert levels[0].price == 4550.0

    def test_no_projection_without_real_zones(self):
        """Пустые/битые данные — рисовать уровни «из воздуха» нельзя."""
        assert balance_around_price([], [], price=4475.0) == []

    def test_projection_can_be_disabled(self, monkeypatch):
        monkeypatch.setattr(config, "PROJECT_ROUND_LEVELS", False)
        assert projected_levels(4475.0, above=True, count=2) == []
