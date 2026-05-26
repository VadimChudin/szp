"""
volume_filter.py — Фильтр "Крупный игрок".

Определяет свечи с аномальным тиковым объёмом.
Если тиковый объём свечи превышает скользящее среднее за N периодов
в THRESHOLD раз — считаем, что на этой свече работал крупный участник.

В будущем сюда можно добавить:
  - Реальный OI с CME (фьючерсы на золото)
  - Дельту объёма с Binance Futures (XAU/USDT)
  - Данные Level 2 order book
"""

import pandas as pd
import numpy as np
import config


def detect_big_player_candles(df: pd.DataFrame) -> np.ndarray:
    """
    Для каждой свечи определяет признак крупного игрока.

    Используются 3 паттерна (любой из них = Big Player):

    1. VOLUME SPIKE — объём свечи > среднего × 1.5
       Логика: аномальный всплеск объёма = кто-то крупный влил деньги.

    2. ABSORPTION — высокий объём + маленькое тело свечи
       Логика: цена не двинулась несмотря на огромный объём →
       крупный лимитный ордер поглотил рыночные ордера.
       Условие: volume > avg * 1.3 AND body_ratio < 0.3

    3. WICK REJECTION — длинный фитиль + повышенный объём
       Логика: цена ткнулась в уровень и резко отскочила,
       значит на уровне стоял крупный лимитник.
       Условие: wick > 50% от range AND volume > avg * 1.2

    Args:
        df: DataFrame со столбцами 'open', 'high', 'low', 'close', 'tick_volume'

    Returns:
        np.ndarray[bool]: True = крупный игрок.
    """
    if 'tick_volume' not in df.columns:
        print("[volume_filter] WARN: no tick_volume column, returning all False")
        return np.zeros(len(df), dtype=bool)

    vol = df['tick_volume'].values.astype(float)
    opens = df['open'].values.astype(float)
    highs = df['high'].values.astype(float)
    lows  = df['low'].values.astype(float)
    closes = df['close'].values.astype(float)

    lookback = config.VOLUME_LOOKBACK
    threshold = config.VOLUME_THRESHOLD_MULT

    flags = np.zeros(len(vol), dtype=bool)
    reasons = {"spike": 0, "absorption": 0, "wick_reject": 0}

    for i in range(lookback, len(vol)):
        avg_vol = np.mean(vol[i - lookback : i])
        if avg_vol <= 0:
            continue

        full_range = highs[i] - lows[i]
        if full_range <= 0:
            continue

        body = abs(closes[i] - opens[i])
        body_ratio = body / full_range  # 0 = doji, 1 = marubozu

        upper_wick = highs[i] - max(opens[i], closes[i])
        lower_wick = min(opens[i], closes[i]) - lows[i]
        max_wick = max(upper_wick, lower_wick)
        wick_ratio = max_wick / full_range  # доля самого длинного фитиля

        # Паттерн 1: VOLUME SPIKE
        if vol[i] > avg_vol * threshold:
            flags[i] = True
            reasons["spike"] += 1
            continue

        # Паттерн 2: ABSORPTION (объём повышен, но свеча маленькая)
        if vol[i] > avg_vol * 1.3 and body_ratio < 0.3:
            flags[i] = True
            reasons["absorption"] += 1
            continue

        # Паттерн 3: WICK REJECTION (длинный фитиль + объём)
        if wick_ratio > 0.5 and vol[i] > avg_vol * 1.2:
            flags[i] = True
            reasons["wick_reject"] += 1
            continue

    big_count = np.sum(flags)
    pct = (big_count / len(flags)) * 100 if len(flags) > 0 else 0
    print(f"[volume_filter] {big_count}/{len(flags)} candles flagged "
          f"as Big Player ({pct:.1f}%)")
    print(f"  Reasons: spike={reasons['spike']}, "
          f"absorption={reasons['absorption']}, "
          f"wick_reject={reasons['wick_reject']}")

    return flags


def get_volume_flags_all_tf(data: dict[str, pd.DataFrame]) -> dict[str, np.ndarray]:
    """
    Применяет фильтр крупного игрока ко всем таймфреймам.

    Args:
        data: {"H1": DataFrame, "H4": DataFrame, "D1": DataFrame}

    Returns:
        {"H1": bool_array, "H4": bool_array, "D1": bool_array}
    """
    result = {}
    for tf_label, df in data.items():
        print(f"[volume_filter] Processing {tf_label}...")
        result[tf_label] = detect_big_player_candles(df)
    return result


def calculate_delta(df: pd.DataFrame) -> pd.DataFrame:
    """
    Рассчитывает приблизительную дельту объёма для каждой свечи.

    Формула (стандартное приближение без тиковых данных):
        Delta = Volume × (Close - Open) / (High - Low)

    Если дельта > 0 — покупатели доминируют (бычий pressure).
    Если дельта < 0 — продавцы доминируют (медвежий pressure).

    Дополнительно рассчитывается кумулятивная дельта (CVD) —
    накопленная сумма дельт. Растущий CVD = покупки преобладают.

    Args:
        df: DataFrame с OHLCV данными

    Returns:
        DataFrame с добавленными колонками:
          - 'delta': дельта на каждой свече
          - 'cvd': кумулятивная дельта (cumulative volume delta)
          - 'delta_pct': дельта как % от объёма (-1.0 до +1.0)
    """
    result = df.copy()

    vol = df['tick_volume'].values.astype(float)
    opens = df['open'].values.astype(float)
    highs = df['high'].values.astype(float)
    lows = df['low'].values.astype(float)
    closes = df['close'].values.astype(float)

    delta = np.zeros(len(df))
    delta_pct = np.zeros(len(df))

    for i in range(len(df)):
        full_range = highs[i] - lows[i]
        if full_range > 0 and vol[i] > 0:
            # Доля покупок: (close - low) / range
            # Доля продаж: (high - close) / range
            # Delta = Volume * ((close - low) - (high - close)) / range
            #       = Volume * (2*close - high - low) / range
            buy_ratio = (closes[i] - lows[i]) / full_range
            sell_ratio = (highs[i] - closes[i]) / full_range
            delta_pct[i] = buy_ratio - sell_ratio  # от -1.0 до +1.0
            delta[i] = vol[i] * delta_pct[i]

    result['delta'] = delta
    result['delta_pct'] = delta_pct
    result['cvd'] = np.cumsum(delta)

    return result


def get_delta_at_zone(df: pd.DataFrame, zone_price: float, tolerance: float = 5.0) -> dict:
    """
    Анализирует дельту на свечах, которые касались зоны.

    Позволяет понять: на данном уровне покупатели или продавцы сильнее?

    Args:
        df: DataFrame с колонкой 'delta' (после calculate_delta)
        zone_price: цена зоны
        tolerance: допуск в $

    Returns:
        dict с результатами:
          - total_delta: суммарная дельта на зоне
          - buy_count: сколько свечей с положительной дельтой
          - sell_count: сколько с отрицательной
          - dominant: "BUYERS" или "SELLERS"
    """
    # Свечи, которые касались зоны (low <= zone <= high)
    mask = (df['low'] <= zone_price + tolerance) & (df['high'] >= zone_price - tolerance)
    touching = df[mask]

    if touching.empty or 'delta' not in touching.columns:
        return {"total_delta": 0, "buy_count": 0, "sell_count": 0, "dominant": "NEUTRAL"}

    total_delta = touching['delta'].sum()
    buy_count = int((touching['delta'] > 0).sum())
    sell_count = int((touching['delta'] < 0).sum())
    dominant = "BUYERS" if total_delta > 0 else "SELLERS" if total_delta < 0 else "NEUTRAL"

    return {
        "total_delta": round(total_delta, 0),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "dominant": dominant,
    }


if __name__ == "__main__":
    from data_fetcher import generate_sample_data
    data = generate_sample_data()
    flags = get_volume_flags_all_tf(data)
    for tf, f in flags.items():
        print(f"{tf}: {np.sum(f)} big player candles out of {len(f)}")

    # Тест дельты
    print("\n--- Delta Analysis ---")
    for tf, df in data.items():
        df_delta = calculate_delta(df)
        last_cvd = df_delta['cvd'].iloc[-1]
        last_delta = df_delta['delta'].iloc[-1]
        print(f"{tf}: Last delta={last_delta:+.0f}, CVD={last_cvd:+.0f}")
