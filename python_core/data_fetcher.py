"""
data_fetcher.py — Получение свечных данных.

Поддерживает два источника:
  1. MetaTrader5 Python API (требует установленный и запущенный терминал MT5)
  2. CSV-файлы (для offline-тестирования без MT5)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import config

# ── Попытка импорта MetaTrader5 (не фатально если нет) ───────────────
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("[data_fetcher] WARN: MetaTrader5 package not found. Using CSV mode.")


def fetch_from_mt5(symbol: str, timeframe_str: str, bars: int) -> pd.DataFrame:
    """
    Получает свечи из запущенного терминала MetaTrader 5.

    Args:
        symbol: Торговый символ (например "XAUUSD")
        timeframe_str: Строка таймфрейма ("TIMEFRAME_H1", "TIMEFRAME_H4", "TIMEFRAME_D1")
        bars: Количество последних свечей

    Returns:
        DataFrame с колонками: time, open, high, low, close, tick_volume, spread
    """
    if not MT5_AVAILABLE:
        raise RuntimeError("MetaTrader5 package is not installed.")

    # Маппинг строки -> константа MT5
    tf_map = {
        "TIMEFRAME_M5":  mt5.TIMEFRAME_M5,
        "TIMEFRAME_M15": mt5.TIMEFRAME_M15,
        "TIMEFRAME_H1":  mt5.TIMEFRAME_H1,
        "TIMEFRAME_H4":  mt5.TIMEFRAME_H4,
        "TIMEFRAME_D1":  mt5.TIMEFRAME_D1,
    }

    tf = tf_map.get(timeframe_str)
    if tf is None:
        raise ValueError(f"Unknown timeframe: {timeframe_str}")

    # Инициализация терминала (если ещё не инициализирован)
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(
            f"No data for {symbol} {timeframe_str}: {mt5.last_error()}"
        )

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.rename(columns={
        'time': 'time',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'tick_volume': 'tick_volume',
        'spread': 'spread',
        'real_volume': 'real_volume',
    }, inplace=True)
    return df


def fetch_from_csv(symbol: str, timeframe_label: str) -> pd.DataFrame:
    """
    Загружает свечи из CSV-файла.
    Ожидаемое имя файла: {symbol}_{timeframe_label}.csv
    Колонки CSV: time,open,high,low,close,tick_volume
    
    Поддерживает CSV от MT4 EA SmartZonesCollector (с комментариями # в начале)
    и CSV от yfinance download_real_data.py.
    """
    csv_path = Path(config.CSV_DIR) / f"{symbol}_{timeframe_label}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    # Читаем с пропуском комментариев (# broker=..., # symbol=...)
    df = pd.read_csv(csv_path, parse_dates=['time'], comment='#')
    
    # Логируем источник данных
    with open(csv_path, 'r') as f:
        first_line = f.readline().strip()
    if first_line.startswith('#'):
        print(f"  {timeframe_label}: Loaded from BROKER ({first_line})")
    else:
        print(f"  {timeframe_label}: Loaded from CSV (yfinance/other)")
    
    return df


def generate_sample_data(symbol: str = "XAUUSD", bars: int = 500) -> dict[str, pd.DataFrame]:
    """
    Генерирует синтетические данные для тестирования без MT5.
    Создаёт правдоподобные свечи XAU/USD вокруг $2400 с разными таймфреймами.
    Используется для разработки и отладки.

    Returns:
        dict: {"H1": DataFrame, "H4": DataFrame, "D1": DataFrame}
    """
    np.random.seed(42)
    base_price = 2400.0

    result = {}
    for tf_label, tf_cfg in config.TIMEFRAMES.items():
        n = tf_cfg["bars"]

        # Генерируем random walk
        returns = np.random.normal(0, 0.002, n)  # ~0.2% std per candle
        close_prices = base_price * np.cumprod(1 + returns)

        # Генерируем OHLC
        highs = close_prices * (1 + np.abs(np.random.normal(0, 0.003, n)))
        lows = close_prices * (1 - np.abs(np.random.normal(0, 0.003, n)))
        opens = np.roll(close_prices, 1)
        opens[0] = base_price

        # Тиковый объём (случайный, с редкими всплесками)
        tick_vol = np.random.randint(500, 3000, n).astype(float)
        # Вставляем "крупных игроков" — 10% свечей с аномальным объёмом
        big_player_indices = np.random.choice(n, size=n // 10, replace=False)
        tick_vol[big_player_indices] *= 3.0

        # Временные метки
        if tf_label == "H1":
            freq = "1h"
        elif tf_label == "H4":
            freq = "4h"
        else:
            freq = "1D"
        times = pd.date_range(end=datetime.now(), periods=n, freq=freq)

        df = pd.DataFrame({
            'time': times,
            'open': opens,
            'high': highs,
            'low': lows,
            'close': close_prices,
            'tick_volume': tick_vol,
        })
        result[tf_label] = df

    return result


def fetch_all_timeframes(symbol: str = None) -> dict[str, pd.DataFrame]:
    """
    Главная функция — получение данных по всем таймфреймам из ТЗ.

    Returns:
        dict: {"H1": DataFrame, "H4": DataFrame, "D1": DataFrame}
    """
    symbol = symbol or config.SYMBOL
    data = {}

    if config.DATA_SOURCE == "mt5" and MT5_AVAILABLE:
        print(f"[data_fetcher] Fetching from MetaTrader 5 for {symbol}...")
        for tf_label, tf_cfg in config.TIMEFRAMES.items():
            df = fetch_from_mt5(symbol, tf_cfg["mt5_tf"], tf_cfg["bars"])
            data[tf_label] = df
            print(f"  {tf_label}: {len(df)} bars loaded "
                  f"({df['time'].iloc[0]} -> {df['time'].iloc[-1]})")
    elif config.DATA_SOURCE == "csv":
        print(f"[data_fetcher] Loading from CSV for {symbol}...")
        for tf_label in config.TIMEFRAMES:
            df = fetch_from_csv(symbol, tf_label)
            data[tf_label] = df
            print(f"  {tf_label}: {len(df)} bars loaded")
    else:
        print("[data_fetcher] MT5 not available, generating sample data...")
        data = generate_sample_data(symbol)
        for tf_label, df in data.items():
            print(f"  {tf_label}: {len(df)} synthetic bars generated")

    return data


if __name__ == "__main__":
    # Quick test
    candles = fetch_all_timeframes()
    for tf, df in candles.items():
        print(f"\n{tf} — last 3 candles:")
        print(df.tail(3).to_string(index=False))
