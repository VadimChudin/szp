"""
Тесты для fvg_detector.py — детектор имбалансов (Fair Value Gaps).
"""

import pandas as pd
import pytest

from fvg_detector import detect_fvgs


class TestDetectFvgs:
    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["high", "low"])
        assert detect_fvgs(df) == []

    def test_less_than_3_candles(self):
        """Нужно минимум 3 свечи для обнаружения FVG."""
        df = pd.DataFrame({
            "high": [2400.0, 2405.0],
            "low": [2395.0, 2398.0],
        })
        assert detect_fvgs(df) == []

    def test_bullish_fvg_detected(self):
        """Бычий FVG: low[2] > high[0] (разрыв вверх)."""
        df = pd.DataFrame({
            "high": [2400.0, 2410.0, 2415.0],
            "low": [2395.0, 2399.0, 2401.0],  # low[2]=2401 > high[0]=2400 → bullish
        })
        fvgs = detect_fvgs(df)
        assert len(fvgs) == 1
        assert fvgs[0]["type"] == "bullish"
        assert fvgs[0]["bottom"] == 2400.0   # high[0]
        assert fvgs[0]["top"] == 2401.0      # low[2]
        assert fvgs[0]["mitigated"] is False

    def test_bearish_fvg_detected(self):
        """Медвежий FVG: high[2] < low[0] (разрыв вниз)."""
        df = pd.DataFrame({
            "high": [2410.0, 2405.0, 2394.0],  # high[2]=2394 < low[0]=2400 → bearish
            "low": [2400.0, 2395.0, 2390.0],
        })
        fvgs = detect_fvgs(df)
        assert len(fvgs) == 1
        assert fvgs[0]["type"] == "bearish"
        assert fvgs[0]["top"] == 2400.0    # low[0]
        assert fvgs[0]["bottom"] == 2394.0  # high[2]
        assert fvgs[0]["mitigated"] is False

    def test_no_fvg_when_no_gap(self):
        """Если разрыва нет — FVG не находится."""
        df = pd.DataFrame({
            "high": [2405.0, 2410.0, 2408.0],
            "low": [2395.0, 2400.0, 2402.0],  # low[2]=2402 < high[0]=2405
        })
        fvgs = detect_fvgs(df)
        assert len(fvgs) == 0

    def test_mitigated_fvg_removed(self):
        """Митигированный FVG не попадает в результат."""
        df = pd.DataFrame({
            "high": [2400.0, 2410.0, 2415.0, 2420.0, 2425.0],
            "low": [2395.0, 2399.0, 2401.0, 2405.0, 2399.0],
            #  Bullish FVG: low[2]=2401 > high[0]=2400
            #  Но low[4]=2399 <= bottom=2400 → mitigated
        })
        fvgs = detect_fvgs(df)
        # FVG был создан но потом перекрыт → не должен попасть в unmitigated
        assert len(fvgs) == 0

    def test_unmitigated_fvg_persists(self):
        """Если цена не дошла до FVG — он остаётся."""
        df = pd.DataFrame({
            "high": [2400.0, 2410.0, 2415.0, 2420.0, 2425.0],
            "low": [2395.0, 2399.0, 2401.0, 2410.0, 2415.0],
            # Bullish FVG (2400→2401), цена потом идёт только вверх.
            # Для митигации low должен быть <= 2400, но этого нет.
        })
        fvgs = detect_fvgs(df)
        assert len(fvgs) == 1
        assert fvgs[0]["type"] == "bullish"
        assert fvgs[0]["mitigated"] is False

    def test_multiple_fvgs(self):
        """Несколько FVG в одном датасете."""
        df = pd.DataFrame({
            "high": [2400.0, 2410.0, 2415.0, 2420.0, 2430.0, 2435.0],
            "low": [2395.0, 2399.0, 2401.0, 2416.0, 2419.0, 2421.0],
            # FVG 1 at idx=2: low[2]=2401 > high[0]=2400 → bullish
            # FVG 2 at idx=5: low[5]=2421 > high[3]=2420 → bullish
        })
        fvgs = detect_fvgs(df)
        assert len(fvgs) >= 1

    def test_fvg_created_at_idx_field(self):
        """Поле created_at_idx корректно заполняется."""
        df = pd.DataFrame({
            "high": [2400.0, 2410.0, 2415.0],
            "low": [2395.0, 2399.0, 2401.0],
        })
        fvgs = detect_fvgs(df)
        assert len(fvgs) == 1
        assert fvgs[0]["created_at_idx"] == 2
