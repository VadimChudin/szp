"""
Тесты для volume_filter.py — фильтр крупного игрока и расчёт дельты.
"""

import numpy as np
import pandas as pd
import pytest

from volume_filter import (
    detect_big_player_candles,
    get_volume_flags_all_tf,
    calculate_delta,
    get_delta_at_zone,
)
import config


# ── detect_big_player_candles ─────────────────────────────────────────────

class TestDetectBigPlayerCandles:
    def test_returns_bool_array(self, sample_ohlcv_df):
        result = detect_big_player_candles(sample_ohlcv_df)
        assert isinstance(result, np.ndarray)
        assert result.dtype == bool
        assert len(result) == len(sample_ohlcv_df)

    def test_no_tick_volume_returns_all_false(self):
        """Без колонки tick_volume — все False."""
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=10, freq="1h"),
            "open": [2400.0] * 10,
            "high": [2405.0] * 10,
            "low": [2395.0] * 10,
            "close": [2401.0] * 10,
        })
        result = detect_big_player_candles(df)
        assert not result.any()

    def test_volume_spike_detected(self):
        """Аномальный всплеск объёма должен быть отмечен."""
        n = 30
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=n, freq="1h"),
            "open": [2400.0] * n,
            "high": [2410.0] * n,
            "low": [2390.0] * n,
            "close": [2405.0] * n,
            "tick_volume": [1000.0] * n,
        })
        # Последняя свеча — объём × 5 (гарантированный spike)
        df.loc[df.index[-1], "tick_volume"] = 5000.0
        result = detect_big_player_candles(df)
        assert result.iloc[-1] if hasattr(result, 'iloc') else result[-1]

    def test_absorption_pattern(self):
        """Высокий объём + маленькое тело = absorption."""
        n = 30
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=n, freq="1h"),
            "open": [2400.0] * n,
            "high": [2410.0] * n,
            "low": [2390.0] * n,
            "close": [2405.0] * n,
            "tick_volume": [1000.0] * n,
        })
        # Свеча с маленьким телом (body_ratio < 0.3) и повышенным объёмом
        idx = n - 1
        df.loc[idx, "open"] = 2400.0
        df.loc[idx, "close"] = 2401.0   # body = 1, range = 20, ratio = 0.05
        df.loc[idx, "tick_volume"] = 1500.0  # > avg * 1.3
        result = detect_big_player_candles(df)
        assert result[idx]

    def test_wick_rejection_pattern(self):
        """Длинный фитиль + объём = wick rejection."""
        n = 30
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=n, freq="1h"),
            "open": [2400.0] * n,
            "high": [2410.0] * n,
            "low": [2390.0] * n,
            "close": [2405.0] * n,
            "tick_volume": [1000.0] * n,
        })
        # Длинный нижний фитиль (wick_ratio > 0.5) + volume > avg * 1.2
        idx = n - 1
        df.loc[idx, "open"] = 2408.0
        df.loc[idx, "close"] = 2409.0
        df.loc[idx, "high"] = 2410.0
        df.loc[idx, "low"] = 2390.0   # lower wick = 18/20 = 0.9
        df.loc[idx, "tick_volume"] = 1300.0  # > avg * 1.2
        result = detect_big_player_candles(df)
        assert result[idx]

    def test_first_lookback_candles_not_flagged(self, sample_ohlcv_df):
        """Первые VOLUME_LOOKBACK свечей не могут быть отмечены (нет истории)."""
        result = detect_big_player_candles(sample_ohlcv_df)
        lookback = config.VOLUME_LOOKBACK
        assert not result[:lookback].any()


# ── get_volume_flags_all_tf ───────────────────────────────────────────────

class TestGetVolumeFlagsAllTf:
    def test_returns_dict_with_same_keys(self, multi_tf_data):
        result = get_volume_flags_all_tf(multi_tf_data)
        assert set(result.keys()) == set(multi_tf_data.keys())

    def test_each_value_is_bool_array(self, multi_tf_data):
        result = get_volume_flags_all_tf(multi_tf_data)
        for tf, flags in result.items():
            assert isinstance(flags, np.ndarray)
            assert flags.dtype == bool
            assert len(flags) == len(multi_tf_data[tf])


# ── calculate_delta ───────────────────────────────────────────────────────

class TestCalculateDelta:
    def test_adds_required_columns(self, sample_ohlcv_df):
        result = calculate_delta(sample_ohlcv_df)
        assert "delta" in result.columns
        assert "cvd" in result.columns
        assert "delta_pct" in result.columns

    def test_delta_pct_in_range(self, sample_ohlcv_df):
        """delta_pct должен быть в диапазоне [-1, 1]."""
        result = calculate_delta(sample_ohlcv_df)
        assert (result["delta_pct"] >= -1.0).all()
        assert (result["delta_pct"] <= 1.0).all()

    def test_cvd_is_cumulative(self, sample_ohlcv_df):
        """CVD = кумулятивная сумма delta."""
        result = calculate_delta(sample_ohlcv_df)
        expected_cvd = np.cumsum(result["delta"].values)
        np.testing.assert_array_almost_equal(result["cvd"].values, expected_cvd)

    def test_bullish_candle_positive_delta(self):
        """Бычья свеча (close > open) даёт положительную дельту."""
        df = pd.DataFrame({
            "time": [pd.Timestamp("2024-01-01")],
            "open": [2390.0],
            "high": [2410.0],
            "low": [2385.0],
            "close": [2408.0],  # Сильный бычий close
            "tick_volume": [1000.0],
        })
        result = calculate_delta(df)
        assert result["delta"].iloc[0] > 0

    def test_bearish_candle_negative_delta(self):
        """Медвежья свеча (close < open) даёт отрицательную дельту."""
        df = pd.DataFrame({
            "time": [pd.Timestamp("2024-01-01")],
            "open": [2408.0],
            "high": [2410.0],
            "low": [2385.0],
            "close": [2390.0],  # Сильный медвежий close
            "tick_volume": [1000.0],
        })
        result = calculate_delta(df)
        assert result["delta"].iloc[0] < 0

    def test_zero_range_candle(self):
        """Свеча с нулевым диапазоном — delta = 0."""
        df = pd.DataFrame({
            "time": [pd.Timestamp("2024-01-01")],
            "open": [2400.0],
            "high": [2400.0],
            "low": [2400.0],
            "close": [2400.0],
            "tick_volume": [1000.0],
        })
        result = calculate_delta(df)
        assert result["delta"].iloc[0] == 0.0


# ── get_delta_at_zone ─────────────────────────────────────────────────────

class TestGetDeltaAtZone:
    def test_returns_expected_keys(self, sample_ohlcv_df):
        df = calculate_delta(sample_ohlcv_df)
        result = get_delta_at_zone(df, zone_price=2400.0)
        assert "total_delta" in result
        assert "buy_count" in result
        assert "sell_count" in result
        assert "dominant" in result

    def test_dominant_values(self, sample_ohlcv_df):
        df = calculate_delta(sample_ohlcv_df)
        result = get_delta_at_zone(df, zone_price=2400.0)
        assert result["dominant"] in ("BUYERS", "SELLERS", "NEUTRAL")

    def test_no_touches_neutral(self):
        """Если ни одна свеча не касается зоны — NEUTRAL."""
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=5, freq="1h"),
            "open": [2400.0] * 5,
            "high": [2405.0] * 5,
            "low": [2395.0] * 5,
            "close": [2401.0] * 5,
            "tick_volume": [1000.0] * 5,
            "delta": [100.0] * 5,
        })
        # Зона далеко от цены
        result = get_delta_at_zone(df, zone_price=2500.0, tolerance=5.0)
        assert result["dominant"] == "NEUTRAL"
        assert result["total_delta"] == 0

    def test_touching_candles_counted(self):
        """Свечи, касающиеся зоны, учитываются."""
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=5, freq="1h"),
            "open": [2400.0] * 5,
            "high": [2405.0] * 5,
            "low": [2395.0] * 5,
            "close": [2403.0] * 5,
            "tick_volume": [1000.0] * 5,
            "delta": [50.0, -30.0, 20.0, -10.0, 40.0],
        })
        result = get_delta_at_zone(df, zone_price=2400.0, tolerance=5.0)
        assert result["total_delta"] == 70.0  # 50-30+20-10+40
        assert result["buy_count"] == 3
        assert result["sell_count"] == 2
        assert result["dominant"] == "BUYERS"
