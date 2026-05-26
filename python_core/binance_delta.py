"""
binance_delta.py — Получение РЕАЛЬНОЙ дельты объёма с Binance Futures (бесплатно).

Binance предоставляет агрегированные сделки (aggTrades) с указанием,
кто был maker (лимитный ордер) и кто taker (рыночный).
Это позволяет посчитать НАСТОЯЩУЮ дельту, а не аппроксимацию.

Инструмент: XAUUSDT (фьючерс на золото)
API: Публичный, без ключей, бесплатный.
"""

import requests
import time
from datetime import datetime, timedelta

# ── Binance Futures API (публичный, без ключей) ───────────────────────
BASE_URL = "https://fapi.binance.com"

# Фьючерс на золото
SYMBOL = "XAUUSDT"

def get_klines(symbol: str = SYMBOL, interval: str = "4h", limit: int = 100) -> list[dict]:
    """
    Получает свечи (klines) с Binance Futures.
    
    Binance kline содержит:
      - Общий объём (volume)
      - Объём покупок taker (taker_buy_volume) — это РЕАЛЬНЫЕ рыночные покупки
    
    Дельта = taker_buy_volume - taker_sell_volume
    taker_sell_volume = volume - taker_buy_volume
    
    Args:
        symbol: Торговая пара (XAUUSDT)
        interval: Таймфрейм ("1h", "4h", "1d")
        limit: Количество свечей (макс 1500)
    
    Returns:
        list[dict] с полями: time, open, high, low, close, volume, 
                             buy_volume, sell_volume, delta
    """
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        raw = response.json()
    except Exception as e:
        print(f"[binance] ERROR: Failed to fetch klines: {e}")
        return []
    
    candles = []
    for k in raw:
        # Binance kline format:
        # [0] Open time, [1] Open, [2] High, [3] Low, [4] Close, 
        # [5] Volume, [6] Close time, [7] Quote asset volume,
        # [8] Number of trades, [9] Taker buy base asset volume,
        # [10] Taker buy quote asset volume, [11] Ignore
        
        total_vol = float(k[5])
        buy_vol = float(k[9])      # Реальный объём покупок (taker buys)
        sell_vol = total_vol - buy_vol  # Реальный объём продаж
        delta = buy_vol - sell_vol  # НАСТОЯЩАЯ дельта!
        
        candles.append({
            "time": datetime.fromtimestamp(k[0] / 1000).strftime("%Y-%m-%d %H:%M"),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": total_vol,
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "delta": delta,
            "trades": int(k[8]),
        })
    
    print(f"[binance] Fetched {len(candles)} candles for {symbol} ({interval})")
    return candles


def get_realtime_delta(symbol: str = SYMBOL, hours: int = 4) -> dict:
    """
    Получает суммарную реальную дельту за последние N часов.
    
    Returns:
        {
            "total_delta": float,       # > 0 = покупатели доминируют
            "buy_volume": float,        # Общий объём покупок
            "sell_volume": float,       # Общий объём продаж
            "dominant": "BUYERS" | "SELLERS",
            "delta_percent": float,     # Насколько сильно доминирует (%)
            "total_trades": int,        # Общее число сделок
        }
    """
    # Берём свечи за нужный период
    if hours <= 1:
        interval = "5m"
        limit = 12  # 12 × 5m = 60 min
    elif hours <= 4:
        interval = "15m"
        limit = 16  # 16 × 15m = 4h
    elif hours <= 24:
        interval = "1h"
        limit = 24
    else:
        interval = "4h"
        limit = min(hours // 4, 500)
    
    candles = get_klines(symbol, interval, limit)
    if not candles:
        return {"total_delta": 0, "dominant": "UNKNOWN", "delta_percent": 0}
    
    total_buy = sum(c["buy_volume"] for c in candles)
    total_sell = sum(c["sell_volume"] for c in candles)
    total_delta = total_buy - total_sell
    total_trades = sum(c["trades"] for c in candles)
    total_vol = total_buy + total_sell
    
    delta_pct = (total_delta / total_vol * 100) if total_vol > 0 else 0
    dominant = "BUYERS" if total_delta > 0 else "SELLERS"
    
    result = {
        "total_delta": round(total_delta, 4),
        "buy_volume": round(total_buy, 4),
        "sell_volume": round(total_sell, 4),
        "dominant": dominant,
        "delta_percent": round(delta_pct, 2),
        "total_trades": total_trades,
    }
    
    return result


def get_delta_for_zone(zone_price: float, symbol: str = SYMBOL) -> dict:
    """
    Получает реальную дельту в окрестности ценовой зоны.
    
    Проходит по последним 4h-свечам и считает суммарную дельту
    только для тех свечей, где цена касалась нашей зоны (±$3).
    
    Args:
        zone_price: Центр зоны (например, 2350.00)
        
    Returns:
        dict с полями: zone_delta, zone_buy, zone_sell, dominant, candles_in_zone
    """
    candles = get_klines(symbol, "1h", limit=200)
    if not candles:
        return {"zone_delta": 0, "dominant": "UNKNOWN"}
    
    zone_tolerance = 3.0  # ±$3 от центра зоны
    
    zone_buy = 0
    zone_sell = 0
    in_zone_count = 0
    
    for c in candles:
        # Проверяем, касалась ли свеча нашей зоны
        if c["low"] <= zone_price + zone_tolerance and c["high"] >= zone_price - zone_tolerance:
            zone_buy += c["buy_volume"]
            zone_sell += c["sell_volume"]
            in_zone_count += 1
    
    zone_delta = zone_buy - zone_sell
    dominant = "BUYERS" if zone_delta > 0 else "SELLERS"
    
    return {
        "zone_delta": round(zone_delta, 4),
        "zone_buy": round(zone_buy, 4),
        "zone_sell": round(zone_sell, 4),
        "dominant": dominant,
        "candles_in_zone": in_zone_count,
    }


if __name__ == "__main__":
    print("=" * 50)
    print("  Binance Real Delta — XAUUSDT Futures")
    print("=" * 50)
    
    # 1. Общая дельта за 4 часа
    print("\n Дельта за последние 4 часа:")
    delta = get_realtime_delta(hours=4)
    status_sym = "[+]" if delta["dominant"] == "BUYERS" else "[-]"
    print(f"  {status_sym} {delta['dominant']} доминируют")
    print(f"  Дельта: {delta['total_delta']:+.4f}")
    print(f"  Перекос: {delta['delta_percent']:+.2f}%")
    print(f"  Buy: {delta['buy_volume']:.4f} | Sell: {delta['sell_volume']:.4f}")
    print(f"  Сделок: {delta['total_trades']}")
    
    # 2. Последние свечи с дельтой
    print("\n Последние 5 свечей (H4):")
    candles = get_klines(interval="4h", limit=5)
    for c in candles:
        d = c["delta"]
        status_sym = "[+]" if d > 0 else "[-]"
        print(f"  {c['time']} | O:{c['open']:.2f} C:{c['close']:.2f} | "
              f"delta:{d:+.4f} {status_sym} | Trades:{c['trades']}")
