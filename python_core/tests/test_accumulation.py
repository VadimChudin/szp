"""
Тесты для accumulation.py — участки набора позиции крупным участником.
"""

import pandas as pd
import pytest

import config
from accumulation import build_output, detect_accumulations


def _candles(volumes: list[float], ranges: list[float], base: float = 2400.0) -> pd.DataFrame:
    rows = []
    for i, (vol, rng) in enumerate(zip(volumes, ranges)):
        open_ = base
        close = base + rng * 0.2
        rows.append({
            "time": pd.Timestamp("2024-06-01") + pd.Timedelta(hours=i),
            "open": open_,
            "high": max(open_, close) + rng * 0.4,
            "low": min(open_, close) - rng * 0.4,
            "close": close,
            "tick_volume": vol,
        })
    return pd.DataFrame(rows)


class TestDetectAccumulations:
    def test_quiet_market_has_no_boxes(self):
        n = config.VOLUME_LOOKBACK + 20
        df = _candles([1000.0] * n, [2.0] * n)
        assert detect_accumulations(df) == []

    def test_high_volume_narrow_range_detected(self):
        n = config.VOLUME_LOOKBACK + 20
        volumes = [1000.0] * n
        ranges = [2.0] * n
        # Три свечи: объём втрое, диапазон вдвое уже — классическое поглощение.
        for i in (n - 3, n - 2, n - 1):
            volumes[i] = 3000.0
            ranges[i] = 0.4
        boxes = detect_accumulations(_candles(volumes, ranges))
        assert len(boxes) == 1
        assert boxes[0].volume_ratio > 1.8
        assert boxes[0].top >= boxes[0].bottom

    def test_high_volume_with_wide_range_ignored(self):
        """Объём большой, но цена улетела — это не набор, а импульс."""
        n = config.VOLUME_LOOKBACK + 20
        volumes = [1000.0] * n
        ranges = [2.0] * n
        for i in (n - 3, n - 2, n - 1):
            volumes[i] = 4000.0
            ranges[i] = 30.0
        assert detect_accumulations(_candles(volumes, ranges)) == []

    def test_too_little_history(self):
        assert detect_accumulations(_candles([1000.0] * 5, [2.0] * 5)) == []

    def test_no_volume_data(self):
        n = config.VOLUME_LOOKBACK + 20
        df = _candles([0.0] * n, [2.0] * n)
        assert detect_accumulations(df) == []


class TestBuildOutput:
    def test_disabled_gives_empty_boxes(self, monkeypatch):
        monkeypatch.setattr(config, "ACCUMULATION_ENABLED", False)
        n = config.VOLUME_LOOKBACK + 20
        data = {config.ACCUMULATION_TIMEFRAME: _candles([5000.0] * n, [0.2] * n)}
        out = build_output(data)
        assert out["count"] == 0
        assert out["boxes"] == []

    def test_box_dict_shape(self):
        n = config.VOLUME_LOOKBACK + 20
        volumes = [1000.0] * n
        ranges = [2.0] * n
        for i in (n - 3, n - 2, n - 1):
            volumes[i] = 3000.0
            ranges[i] = 0.4
        data = {config.ACCUMULATION_TIMEFRAME: _candles(volumes, ranges)}
        out = build_output(data)
        assert out["count"] == 1
        box = out["boxes"][0]
        assert set(box) == {"t1", "t2", "top", "bottom", "vol_ratio"}
        assert isinstance(box["t1"], int) and box["t1"] > 0
        assert box["t2"] >= box["t1"]
        assert box["top"] >= box["bottom"]

    def test_missing_timeframe_is_safe(self):
        assert build_output({})["count"] == 0


class TestBoxGeometry:
    def test_box_covers_last_candle_and_has_height(self):
        """Правый край — конец последней свечи, высота не нулевая."""
        n = config.VOLUME_LOOKBACK + 20
        volumes = [1000.0] * n
        ranges = [2.0] * n
        for i in (n - 3, n - 2, n - 1):
            volumes[i] = 3000.0
            ranges[i] = 0.4
        df = _candles(volumes, ranges)
        box = detect_accumulations(df)[0]
        bar = pd.Timedelta(hours=1)
        assert box.time_to == pd.Timestamp(df["time"].iloc[-1]) + bar
        assert box.top > box.bottom
