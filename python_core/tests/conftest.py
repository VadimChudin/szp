"""
Общая конфигурация для тестов Smart Zones Pro.

Добавляет python_core в sys.path и устанавливает
переменные окружения, необходимые для импорта модулей.
"""

import sys
import os
from pathlib import Path

# Устанавливаем SZP_BASE_DIR до любого импорта модулей проекта
PYTHON_CORE = Path(__file__).resolve().parent.parent
REPO_ROOT = PYTHON_CORE.parent
os.environ.setdefault("SZP_BASE_DIR", str(REPO_ROOT))

# Добавляем python_core в путь
sys.path.insert(0, str(PYTHON_CORE))

import pytest
import pandas as pd
import numpy as np


@pytest.fixture
def sample_ohlcv_df():
    """Создаёт простой DataFrame с OHLCV-данными для тестов."""
    np.random.seed(42)
    n = 50
    base = 2400.0
    times = pd.date_range("2024-01-01", periods=n, freq="1h")
    closes = base + np.cumsum(np.random.randn(n) * 2)
    highs = closes + np.abs(np.random.randn(n) * 3)
    lows = closes - np.abs(np.random.randn(n) * 3)
    opens = np.roll(closes, 1)
    opens[0] = base
    tick_vol = np.random.randint(500, 3000, n).astype(float)

    return pd.DataFrame({
        "time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "tick_volume": tick_vol,
    })


@pytest.fixture
def multi_tf_data(sample_ohlcv_df):
    """Создаёт данные для нескольких таймфреймов."""
    np.random.seed(123)
    n_h4 = 30
    n_d1 = 15
    base = 2400.0

    def make_df(n, freq):
        times = pd.date_range("2024-01-01", periods=n, freq=freq)
        closes = base + np.cumsum(np.random.randn(n) * 3)
        highs = closes + np.abs(np.random.randn(n) * 5)
        lows = closes - np.abs(np.random.randn(n) * 5)
        opens = np.roll(closes, 1)
        opens[0] = base
        tick_vol = np.random.randint(500, 5000, n).astype(float)
        return pd.DataFrame({
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "tick_volume": tick_vol,
        })

    return {
        "H1": sample_ohlcv_df,
        "H4": make_df(n_h4, "4h"),
        "D1": make_df(n_d1, "1D"),
    }
