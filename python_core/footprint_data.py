"""
footprint_data.py — Сборщик кластерных данных (футпринтов).

Источники данных:
  - "mt4_ticks" : Реальные тики от MT4 EA (buy/sell из тикового потока брокера)
  - "yfinance"  : Yahoo Finance GC=F Gold Futures (fallback, эмуляция buy/sell)
  - "binance"   : Binance Futures XAUUSDT (крипто, бесплатно)

Архитектура:
  1. Скачиваем OHLCV свечи из выбранного источника.
  2. Для каждой свечи строим «кластерный профиль»: разбиваем диапазон (High-Low)
     на ценовые уровни и распределяем buy/sell объёмы.
  3. Храним данные в кольцевом буфере (deque).
  4. Фоновый поток обновляет буфер каждые N секунд.
"""

import requests
import threading
import time
import os
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import config
SOURCE = config.DATA_SOURCE  # Read from main config instead of hardcoding
# Binance config
BASE_URL = "https://fapi.binance.com"
BINANCE_SYMBOL = "XAUUSDT"

# yfinance config (Gold Futures = реальный XAUUSD)
YF_SYMBOL = "GC=F"
YF_PERIOD = {"1h": "30d", "4h": "60d", "1d": "1y"}
YF_INTERVAL = {"1h": "1h", "4h": "1h", "1d": "1d"}  # 4h собираем из 1h

BUFFER_SIZE = 50
INTERVAL_SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}

# Адаптивный шаг ценового уровня для золота
PRICE_STEP = {
    "1h": 2.0,   # $2.00
    "4h": 5.0,   # $5.00
    "1d": 10.0,  # $10.00
}


class FootprintCandle:
    """Одна кластерная свеча с разбивкой объёмов по ценовым уровням."""

    __slots__ = [
        "time_str", "timestamp", "open", "high", "low", "close",
        "total_volume", "buy_volume", "sell_volume", "delta",
        "trades", "levels", "price_step", "is_real"
    ]

    def __init__(self, kline: list, price_step: float):
        self.timestamp = int(kline[0])
        self.time_str = datetime.fromtimestamp(kline[0] / 1000).strftime("%Y-%m-%d %H:%M")
        
        o = float(kline[1])
        h = float(kline[2])
        l = float(kline[3])
        c = float(kline[4])
        
        # Защита от битых данных (иногда в yfinance Close < Low)
        self.open = o
        self.close = c
        self.high = max(h, o, c)
        self.low = min(l, o, c)
        
        self.total_volume = float(kline[5])
        self.buy_volume = float(kline[9])      # Taker buy volume (реальные покупки)
        self.sell_volume = self.total_volume - self.buy_volume
        self.delta = self.buy_volume - self.sell_volume
        self.trades = int(kline[8])
        self.price_step = price_step
        self.is_real = False  # Эмулированные данные

        # Строим кластерный профиль
        self.levels = self._build_levels()

    @classmethod
    def from_tick_data(cls, tick_candle: dict, price_step: float):
        """
        Создаёт FootprintCandle из реальных тиковых данных (от tick_reader.py).
        
        Args:
            tick_candle: dict от TickReader.build_candle_from_ticks()
            price_step: шаг ценовой сетки
        """
        obj = object.__new__(cls)
        obj.time_str = tick_candle.get("time_str", "")
        obj.timestamp = 0
        obj.open = tick_candle["open"]
        obj.high = tick_candle["high"]
        obj.low = tick_candle["low"]
        obj.close = tick_candle["close"]
        obj.total_volume = tick_candle.get("total_volume", 0)
        obj.buy_volume = tick_candle.get("buy_volume", 0)
        obj.sell_volume = tick_candle.get("sell_volume", 0)
        obj.delta = tick_candle.get("delta", 0)
        obj.trades = 0
        obj.price_step = price_step
        obj.is_real = tick_candle.get("is_real", False)
        obj.levels = tick_candle.get("levels", {})
        return obj

    def _build_levels(self) -> dict:
        """
        Распределяем buy/sell объём по ценовым уровням.

        Реалистичная модель: не на каждом уровне были сделки.
        Используем trades count для определения «заполненности» свечи.
        """
        import random
        import math

        levels = {}
        candle_range = self.high - self.low

        if candle_range < self.price_step:
            lvl = round(self.close / self.price_step) * self.price_step
            levels[lvl] = {
                "buy": round(self.buy_volume, 4),
                "sell": round(self.sell_volume, 4),
                "delta": round(self.delta, 4),
            }
            return levels

        import math
        # Генерируем все возможные уровни, строго синхронно с логикой JS
        start_level = math.floor(self.low / self.price_step) * self.price_step
        end_level = math.ceil(self.high / self.price_step) * self.price_step

        price = start_level
        all_prices = []
        while price <= end_level + self.price_step * 0.5:
            all_prices.append(round(price, 2))
            price += self.price_step

        if not all_prices:
            all_prices = [round(self.close, 2)]

        # Делаем распределение по ВСЕМ уровням диапазона свечи (непрерывный профиль)
        active_list = sorted(set(all_prices))

        rng = random.Random(self.timestamp)

        # ── Распределяем объём по уровням ──
        buy_weights = []
        sell_weights = []

        for p in active_list:
            pos = (p - self.low) / max(candle_range, 0.01)
            pos = max(0, min(1, pos))

            bw = max(0.05, 1.0 - pos * 0.7)
            sw = max(0.05, 0.3 + pos * 0.7)

            # Добавляем случайное колебание (±30%)
            bw *= rng.uniform(0.7, 1.3)
            sw *= rng.uniform(0.7, 1.3)

            buy_weights.append(bw)
            sell_weights.append(sw)

        total_bw = sum(buy_weights) or 1
        total_sw = sum(sell_weights) or 1

        for i, p in enumerate(active_list):
            bv = round(self.buy_volume * buy_weights[i] / total_bw, 4)
            sv = round(self.sell_volume * sell_weights[i] / total_sw, 4)
            levels[p] = {
                "buy": bv,
                "sell": sv,
                "delta": round(bv - sv, 4),
            }

        return levels

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def poc_price(self) -> float:
        """POC — ценовой уровень с максимальным суммарным объёмом (buy+sell)."""
        if not self.levels:
            return (self.high + self.low) / 2.0
        max_vol = 0
        poc = (self.high + self.low) / 2.0
        for price, data in self.levels.items():
            total = data.get("buy", 0) + data.get("sell", 0)
            if total > max_vol:
                max_vol = total
                poc = float(price)
        return poc

    @property
    def poc_volume(self) -> float:
        """Объём на уровне POC."""
        if not self.levels:
            return 0
        return max(
            (data.get("buy", 0) + data.get("sell", 0))
            for data in self.levels.values()
        )

    def __repr__(self):
        direction = "BUY" if self.delta > 0 else "SELL"
        return (f"FP({self.time_str} | {self.open:.1f}->{self.close:.1f} | "
                f"D:{self.delta:+.2f} {direction} | {len(self.levels)} lvls)")


class FootprintBuffer:
    """
    Кольцевой буфер футпринтов для одного таймфрейма.
    Хранит ровно BUFFER_SIZE свечей. При добавлении новой — старейшая вылетает.
    """

    def __init__(self, interval: str, buffer_size: int = BUFFER_SIZE):
        self.interval = interval
        self.price_step = PRICE_STEP.get(interval, 1.0)
        self.buffer: deque[FootprintCandle] = deque(maxlen=buffer_size)
        self.last_timestamp: int = 0
        self._lock = threading.Lock()

    def load_initial(self, progress_cb=None) -> int:
        """Загружает начальную партию свечей."""
        if SOURCE == "mt5":
            count = self._load_from_mt5(progress_cb=progress_cb)
            if count > 0: return count
            print("[footprint] MT5 fetch failed, fallback to yfinance...")
            return self._load_yfinance()

        if SOURCE == "dukascopy_mt4":
            count = self._load_from_hybrid_engine(progress_cb=progress_cb)
            if count > 0: return count
            print("[footprint] Hybrid engine failed, fallback to CSV...")
        
        if SOURCE in ("yfinance", "mt4_ticks", "dukascopy_mt4"):
            return self._load_yfinance()
        return self._load_binance()

    def _load_from_hybrid_engine(self, progress_cb=None) -> int:
        from dukascopy_loader import DukascopyLoader
        from tick_reader import get_tick_reader
        from data_fetcher import fetch_from_csv
        import pandas as pd
        import numpy as np
        import config
        from datetime import timezone
        import math
        
        loader = DukascopyLoader(max_workers=5)
        # Для D1 тянем 5 дней (было 15) для экономии ресурсов
        days_back = 4 if self.interval in ["1h", "4h"] else 5
        
        # 1. Тянем историю тиков из швейцарского банка
        df_duka = loader.fetch_history(config.SYMBOL, days_back=days_back, progress_cb=progress_cb)
        
        # ── КРИТИЧНО: Приводим Dukascopy к "broker time" (naive) ──────────
        broker_offset = getattr(config, 'BROKER_UTC_OFFSET', 0)
        if not df_duka.empty:
            df_duka['time'] = df_duka['time'] + pd.Timedelta(hours=broker_offset)
            df_duka['time'] = df_duka['time'].dt.tz_localize(None)  # убираем tzinfo
            print(f"[footprint] Dukascopy shifted +{broker_offset}h → broker time. ")
        
        # 2. Вытягиваем границы свечей из MT4
        try:
            tf_map = {"1h": "H1", "4h": "H4", "1d": "D1"}
            tf_label = tf_map.get(self.interval, self.interval)
            df_candles = fetch_from_csv(config.SYMBOL, tf_label)
            if len(df_candles) > BUFFER_SIZE:
                df_candles = df_candles.iloc[-BUFFER_SIZE:]
        except Exception as e:
            print(f"[footprint] Failed to read MT4 CSV: {e}")
            return 0
            
        if df_candles.empty: return 0
        
        if df_candles['time'].dt.tz is not None:
            df_candles['time'] = df_candles['time'].dt.tz_localize(None)
            
        # 3. Читаем свежие "живые" тики из запущенного MT4
        reader = get_tick_reader(config.SYMBOL)
        live_ticks = reader.read_all()
        
        # Попытка загрузить M1 историю для реконструкции пропущенных участков (чтобы свечи не были пустыми)
        m1_df = None
        try:
            m1_df = fetch_from_csv(config.SYMBOL, "M1")
            if m1_df['time'].dt.tz is not None:
                m1_df['time'] = m1_df['time'].dt.tz_localize(None)
        except Exception as e:
            print(f"[footprint] Failed to read M1 CSV for fallback: {e}")
        
        # Векторизированная обработка истории Dukascopy
        if not df_duka.empty:
            # ── Гарантируем что time — naive datetime (broker-time) ────
            if df_duka['time'].dt.tz is not None:
                df_duka['time'] = df_duka['time'].dt.tz_localize(None)
            
            df_duka['lvl'] = np.floor(df_duka['bid'] / self.price_step) * self.price_step
            df_duka['lvl'] = df_duka['lvl'].round(2)
            
            # BUY/SELL по направлению тика (tick volume = 1)
            price_diff = df_duka['bid'].diff()
            df_duka['buy'] = np.where(price_diff > 0, 1.0, 0.0)
            df_duka['sell'] = np.where(price_diff < 0, 1.0, 0.0)
            # Нейтральные тики (цена не изменилась) — 0.5/0.5
            neutral = price_diff == 0
            df_duka.loc[neutral, 'buy'] = 0.5
            df_duka.loc[neutral, 'sell'] = 0.5
            
            print(f"[footprint] Dukascopy ready: {len(df_duka)} ticks, "
                  f"tz={df_duka['time'].dtype}, "
                  f"range={df_duka['time'].min()} .. {df_duka['time'].max()}")

        with self._lock:

            for i, row in df_candles.iterrows():
                # ── Все временные метки — naive broker-time ──
                t_start = row['time']
                if hasattr(t_start, 'tzinfo') and t_start.tzinfo is not None:
                    t_start = t_start.replace(tzinfo=None)
                    
                if i < len(df_candles)-1:
                    t_end = df_candles.iloc[i+1]['time']
                else:
                    t_end = pd.Timestamp.now() + pd.Timedelta(hours=broker_offset)
                if hasattr(t_end, 'tzinfo') and t_end.tzinfo is not None:
                    t_end = t_end.replace(tzinfo=None)
                
                o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
                vol = float(row.get("tick_volume", row.get("volume", 0)))
                time_str = t_start.strftime("%Y-%m-%d %H:%M")
                
                levels = {}
                is_real = False
                total_buy = 0.0
                total_sell = 0.0
                
                # A. Пытаемся использовать живые тики MT4
                # t_start - это naive datetime от брокера. Чтобы timestamp совпал с TimeCurrent MT4,
                # мы обязаны приравнять его к UTC перед конвертацией, иначе ОС-timezone сдвинет его на 3 часа!
                t_start_ms = t_start.replace(tzinfo=timezone.utc).timestamp() * 1000
                t_end_ms = t_end.replace(tzinfo=timezone.utc).timestamp() * 1000
                live_mask = [tk for tk in live_ticks if t_start_ms <= tk.timestamp_ms < t_end_ms]
                
                if live_mask:
                    is_real = True
                    for tk in live_mask:
                        lvl_p = round(math.floor(tk.bid / self.price_step) * self.price_step, 2)
                        if lvl_p not in levels:
                            levels[lvl_p] = {"buy": 0.0, "sell": 0.0, "delta": 0.0}
                        if tk.direction == "BUY":
                            levels[lvl_p]["buy"] += tk.volume; levels[lvl_p]["delta"] += tk.volume; total_buy += tk.volume
                        elif tk.direction == "SELL":
                            levels[lvl_p]["sell"] += tk.volume; levels[lvl_p]["delta"] -= tk.volume; total_sell += tk.volume
                
                # B. Dukascopy история (naive broker-time vs naive broker-time)
                elif not df_duka.empty:
                    mk = (df_duka['time'] >= t_start) & (df_duka['time'] < t_end)
                    slice_df = df_duka.loc[mk]
                    if not slice_df.empty:
                        is_real = True
                        grp = slice_df.groupby('lvl')[['buy', 'sell']].sum()
                        for lvl_p, row_gr in grp.iterrows():
                            b_v = float(row_gr['buy']); s_v = float(row_gr['sell'])
                            levels[round(lvl_p, 2)] = {"buy": b_v, "sell": s_v, "delta": b_v - s_v}
                            total_buy += b_v; total_sell += s_v
                    # Диагностика: сколько тиков упало в каждую свечу
                    if i < 5 or i == len(df_candles)-1:
                        print(f"  candle {time_str}: {len(slice_df)} ticks, {len(levels)} levels, buy={total_buy:.0f} sell={total_sell:.0f}")
                
                # Заполняем пустоты
                if is_real:
                    p_lvl = math.floor(l / self.price_step) * self.price_step
                    end_lvl = math.floor(h / self.price_step) * self.price_step
                    while p_lvl <= end_lvl + self.price_step * 0.1:
                        rounded = round(p_lvl, 2)
                        if rounded not in levels: levels[rounded] = {"buy": 0.0, "sell": 0.0, "delta": 0.0}
                        p_lvl += self.price_step
                
                if is_real:
                    raw_data = {"open": o, "high": h, "low": l, "close": c, "total_volume": total_buy + total_sell, "buy_volume": total_buy, "sell_volume": total_sell, "delta": total_buy - total_sell, "levels": levels, "is_real": True, "time_str": time_str}
                    candle = FootprintCandle.from_tick_data(raw_data, self.price_step)
                    candle.timestamp = int(t_start.timestamp() * 1000)
                    self.buffer.append(candle)
                else:
                    # ФОЛЛБЭК НА M1 (пользователь хочет видеть свечи, а не пустоту "хуета", если нет тиков!)
                    m1_candles_list = []
                    if m1_df is not None and not m1_df.empty:
                        mask = (m1_df['time'] >= t_start) & (m1_df['time'] < t_end)
                        for _, m1_row in m1_df.loc[mask].iterrows():
                            m1_candles_list.append({
                                "open": float(m1_row["open"]), "high": float(m1_row["high"]),
                                "low": float(m1_row["low"]),  "close": float(m1_row["close"]),
                                "volume": float(m1_row.get("tick_volume", m1_row.get("volume", 0)))
                            })
                    
                    ohlc = {"open": o, "high": h, "low": l, "close": c}
                    tick_candle = reader.build_candle_from_ticks(
                        ohlc, [], self.price_step,
                        time_str=time_str,
                        m1_candles=m1_candles_list
                    )
                    # build_candle_from_ticks внутри ставит is_real=True для M1, пусть так и будет, чтобы отображалось 
                    candle = FootprintCandle.from_tick_data(tick_candle, self.price_step)
                    candle.timestamp = int(t_start.timestamp() * 1000)
                    self.buffer.append(candle)
                    
            if self.buffer:
                self.last_timestamp = self.buffer[-1].timestamp
        
        print(f"[footprint] Hybrid Engine {self.interval}: loaded {len(self.buffer)} candles.")
        return len(self.buffer)

    def _load_from_mt5(self, progress_cb=None) -> int:
        import MetaTrader5 as mt5
        import config
        from datetime import datetime
        import math
        
        if not mt5.initialize():
            print("[mt5] initialize() failed")
            return 0
            
        tf_map = {"1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1}
        mt5_tf = tf_map.get(self.interval, mt5.TIMEFRAME_H1)
        
        rates = mt5.copy_rates_from_pos(config.SYMBOL, mt5_tf, 0, BUFFER_SIZE)
        if rates is None or len(rates) == 0:
            print("[mt5] copy_rates failed")
            return 0
            
        from collections import defaultdict
        
        with self._lock:
            self.buffer.clear()
            for i, row in enumerate(rates):
                if progress_cb: progress_cb(i / len(rates))
                
                t_start_ms = int(row['time']) * 1000
                t_start_dt = datetime.fromtimestamp(row['time'])
                time_str = t_start_dt.strftime("%Y-%m-%d %H:%M")
                
                if i < len(rates) - 1:
                    t_end = int(rates[i+1]['time'])
                else:
                    t_end = int(time.time())
                t_end_dt = datetime.fromtimestamp(t_end)
                    
                o, h, l, c = float(row['open']), float(row['high']), float(row['low']), float(row['close'])
                
                levels = {}
                total_buy = 0.0
                total_sell = 0.0
                
                ticks = mt5.copy_ticks_range(config.SYMBOL, t_start_dt, t_end_dt, mt5.COPY_TICKS_ALL)
                
                if ticks is not None and len(ticks) > 0:
                    prev_bid = ticks[0]['bid']
                    for tk in ticks:
                        bid = tk['bid']
                        if bid > prev_bid:
                            direction = "BUY"
                        elif bid < prev_bid:
                            direction = "SELL"
                        else:
                            direction = "NEUTRAL"
                        prev_bid = bid
                        
                        vol = 1.0  # Форекс тики не имеют объема (он равен 0.0)
                        lvl_p = round(math.floor(bid / self.price_step) * self.price_step, 2)
                        
                        if lvl_p not in levels:
                            levels[lvl_p] = {"buy": 0.0, "sell": 0.0, "delta": 0.0}
                            
                        # По умолчанию делим объем тика, если нет четкого направления
                        if direction == "BUY":
                            levels[lvl_p]["buy"] += vol
                            levels[lvl_p]["delta"] += vol
                            total_buy += vol
                        elif direction == "SELL":
                            levels[lvl_p]["sell"] += vol
                            levels[lvl_p]["delta"] -= vol
                            total_sell += vol
                        else:
                            # Оставляем нейтральный тик
                            pass
                            
                else:
                    # Фейковое распределение, если тиков нет
                    vol = float(row['tick_volume'])
                    buy_ratio = 0.55 if c >= o else 0.45
                    buy_vol = vol * buy_ratio
                    sell_vol = vol - buy_vol
                    
                    start_lvl = math.floor(l / self.price_step) * self.price_step
                    end_lvl = math.floor(h / self.price_step) * self.price_step
                    cells = round((end_lvl - start_lvl) / self.price_step) + 1
                    
                    if cells > 0:
                        b_cell = buy_vol / cells
                        s_cell = sell_vol / cells
                        p = start_lvl
                        while p <= end_lvl + self.price_step * 0.1:
                            px = round(p, 2)
                            levels[px] = {"buy": b_cell, "sell": s_cell, "delta": b_cell-s_cell}
                            p += self.price_step
                        total_buy = buy_vol
                        total_sell = sell_vol
                        
                raw_data = {
                    "open": o, "high": h, "low": l, "close": c,
                    "total_volume": total_buy + total_sell,
                    "buy_volume": total_buy, "sell_volume": total_sell,
                    "delta": total_buy - total_sell,
                    "levels": levels,
                    "is_real": True if (ticks is not None and len(ticks) > 0) else False,
                    "time_str": time_str
                }
                
                candle = FootprintCandle.from_tick_data(raw_data, self.price_step)
                candle.timestamp = t_start_ms
                self.buffer.append(candle)
                
            if self.buffer:
                self.last_timestamp = self.buffer[-1].timestamp
                
        print(f"[footprint] MT5 Engine {self.interval}: loaded {len(self.buffer)} candles.")
        return len(self.buffer)

    def _load_mt4_ticks(self) -> int:
        """
        Загрузка из MT4: OHLCV каркас из брокерских CSV + реальные тики.
        
        Архитектура:
          1. Читаем OHLCV CSV (записанный EA SmartZonesCollector)
          2. Читаем tick_buffer.csv (тики от EA)
          3. Для каждой свечи находим тики за её период
          4. Строим реальный кластерный профиль из тиков
          5. Свечи без тиков помечаются is_real=False
        """
        from tick_reader import get_tick_reader
        import pandas as pd
        import paths as _paths

        MT4_COMMON = _paths.MT_COMMON_FILES

        # Ищем OHLCV CSV от EA
        tf_map = {"1h": "H1", "4h": "H4", "1d": "D1"}
        tf_label = tf_map.get(self.interval, "H1")

        # Пробуем найти CSV (XAUUSD_H1.csv, XAUUSD_H4.csv и т.д.)
        csv_path = None
        search_dirs = [d for d in (MT4_COMMON, _paths.LOCAL_DATA_DIR) if d]
        for pattern_dir in search_dirs:
            if not pattern_dir.exists():
                continue
            for f in pattern_dir.glob(f"*_{tf_label}.csv"):
                csv_path = f
                break
            if csv_path:
                break
        
        if not csv_path or not csv_path.exists():
            print(f"[footprint] {self.interval}: No broker CSV found for {tf_label}")
            return 0
        
        # Читаем OHLCV
        try:
            df = pd.read_csv(csv_path, comment='#', parse_dates=['time'])
        except Exception as e:
            print(f"[footprint] Error reading {csv_path}: {e}")
            return 0
        
        if df.empty:
            return 0
        
        # Читаем тики
        reader = get_tick_reader()
        ticks = reader.read_all() if reader.is_available else []
        
        # Загружаем M1 свечи для исторической реконструкции
        m1_path = csv_path.with_name(csv_path.name.replace(tf_label, "M1"))
        m1_df = None
        if m1_path.exists():
            try:
                m1_df = pd.read_csv(m1_path, comment='#', parse_dates=['time'])
            except Exception as e:
                print(f"[footprint] Error reading M1 file {m1_path}: {e}")
        
        # Определяем длительность одной свечи
        candle_duration = {"1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1)}
        duration = candle_duration.get(self.interval, timedelta(hours=1))
        
        with self._lock:
            self.buffer.clear()
            
            for _, row in df.tail(BUFFER_SIZE).iterrows():
                candle_time = pd.to_datetime(row['time'])
                candle_end = candle_time + duration
                
                ohlc = {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("tick_volume", 0)),
                }
                
                # Находим тики за период этой свечи
                candle_ticks = reader.get_ticks_for_period(
                    candle_time.to_pydatetime(),
                    candle_end.to_pydatetime()
                ) if ticks else []
                
                # Фильтруем M1 свечи для реконструкции, если тиков нет
                m1_candles_list = []
                if not candle_ticks and m1_df is not None and not m1_df.empty:
                    mask = (m1_df['time'] >= candle_time) & (m1_df['time'] < candle_end)
                    m1_subset = m1_df.loc[mask]
                    for _, m1_row in m1_subset.iterrows():
                        m1_candles_list.append({
                            "open": float(m1_row["open"]),
                            "high": float(m1_row["high"]),
                            "low": float(m1_row["low"]),
                            "close": float(m1_row["close"]),
                            "volume": float(m1_row.get("tick_volume", 0)),
                        })
                
                # Строим свечу
                tick_candle = reader.build_candle_from_ticks(
                    ohlc, candle_ticks, self.price_step,
                    time_str=candle_time.strftime("%Y-%m-%d %H:%M"),
                    m1_candles=m1_candles_list
                )
                
                fp_candle = FootprintCandle.from_tick_data(tick_candle, self.price_step)
                self.buffer.append(fp_candle)
            
            if self.buffer:
                self.last_timestamp = int(datetime.now().timestamp() * 1000)
        
        real_count = sum(1 for c in self.buffer if c.is_real)
        est_count = len(self.buffer) - real_count
        print(f"[footprint] {self.interval}: loaded {len(self.buffer)} candles from MT4 broker "
              f"(REAL: {real_count}, EST: {est_count}, step ${self.price_step})")
        return len(self.buffer)

    def _load_binance(self) -> int:
        """Загрузка с Binance Futures."""
        url = f"{BASE_URL}/fapi/v1/klines"
        params = {
            "symbol": BINANCE_SYMBOL,
            "interval": self.interval,
            "limit": min(BUFFER_SIZE, 1500),
        }

        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            print(f"[footprint] ERROR loading {self.interval} from Binance: {e}")
            return 0

        with self._lock:
            self.buffer.clear()
            for k in raw:
                candle = FootprintCandle(k, self.price_step)
                self.buffer.append(candle)
            if self.buffer:
                self.last_timestamp = self.buffer[-1].timestamp

        print(f"[footprint] {self.interval}: loaded {len(self.buffer)} candles "
              f"from Binance (step ${self.price_step})")
        return len(self.buffer)

    def _load_yfinance(self) -> int:
        """Загрузка с Yahoo Finance (Gold Futures GC=F)."""
        try:
            import yfinance as yf
        except ImportError:
            print("[footprint] yfinance not installed! pip install yfinance")
            return self._load_binance()

        period = YF_PERIOD.get(self.interval, "30d")
        yf_interval = YF_INTERVAL.get(self.interval, "1h")

        try:
            ticker = yf.Ticker(YF_SYMBOL)
            df = ticker.history(period=period, interval=yf_interval)
            df = df.dropna()
        except Exception as e:
            print(f"[footprint] ERROR loading {self.interval} from yfinance: {e}")
            return self._load_binance()

        if df.empty:
            print(f"[footprint] No yfinance data for {self.interval}, fallback to Binance")
            return self._load_binance()

        # Если 4h — агрегируем из 1h свечей
        if self.interval == "4h" and yf_interval == "1h":
            df = self._aggregate_4h(df)

        with self._lock:
            self.buffer.clear()
            for idx, row in df.tail(BUFFER_SIZE).iterrows():
                ts = int(idx.timestamp() * 1000) if hasattr(idx, 'timestamp') else 0
                vol = float(row.get("Volume", 0))
                trades_est = max(10, int(vol / 10))
                # Эмулируем buy/sell разделение (60/40 для бычьих, 40/60 для медвежьих)
                o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
                buy_ratio = 0.55 if c >= o else 0.45
                kline = [
                    ts,           # 0: open time
                    o,            # 1: open
                    h,            # 2: high
                    l,            # 3: low
                    c,            # 4: close
                    vol,          # 5: volume
                    0,            # 6: close time
                    0,            # 7: quote volume
                    trades_est,   # 8: trades
                    vol * buy_ratio,  # 9: taker buy volume
                ]
                candle = FootprintCandle(kline, self.price_step)
                dt_str = idx.strftime("%Y-%m-%d %H:%M") if hasattr(idx, 'strftime') else str(idx)
                candle.time_str = dt_str
                self.buffer.append(candle)

            if self.buffer:
                self.last_timestamp = self.buffer[-1].timestamp

        print(f"[footprint] {self.interval}: loaded {len(self.buffer)} candles "
              f"from Yahoo Finance GC=F (step ${self.price_step})")
        return len(self.buffer)

    @staticmethod
    def _aggregate_4h(df):
        """Агрегирует 1h свечи в 4h."""
        import pandas as pd
        df = df.copy()
        df.index = pd.to_datetime(df.index)
        # Группируем по 4-часовым интервалам
        agg = df.resample("4h").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).dropna()
        return agg

    def update(self):
        """
        Проверяет новые свечи и добавляет их.
        Возвращает количество добавленных/обновленных свечей.
        """
        if SOURCE == "yfinance":
            return 0  # yfinance не имеет real-time, перезагружаем полностью

        if SOURCE == "mt5":
            import MetaTrader5 as mt5
            import config
            import time
            from datetime import datetime
            import math
            import pandas as pd
            
            if not mt5.initialize():
                return 0
                
            tf_map = {"1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1}
            mt5_tf = tf_map.get(self.interval, mt5.TIMEFRAME_H1)
            
            rates = mt5.copy_rates_from_pos(config.SYMBOL, mt5_tf, 0, 3)
            if rates is None or len(rates) == 0:
                return 0
                
            added_or_updated = 0
            with self._lock:
                for i, row in enumerate(rates):
                    t_start_ms = int(row['time']) * 1000
                    t_start_dt = datetime.fromtimestamp(row['time'])
                    time_str = t_start_dt.strftime("%Y-%m-%d %H:%M")
                    
                    if i < len(rates) - 1:
                        t_end = int(rates[i+1]['time'])
                    else:
                        t_end = int(time.time())
                    t_end_dt = datetime.fromtimestamp(t_end)
                        
                    o, h, l, c = float(row['open']), float(row['high']), float(row['low']), float(row['close'])
                    
                    levels = {}
                    total_buy = 0.0
                    total_sell = 0.0
                    
                    ticks = mt5.copy_ticks_range(config.SYMBOL, t_start_dt, t_end_dt, mt5.COPY_TICKS_ALL)
                    
                    if ticks is not None and len(ticks) > 0:
                        prev_bid = ticks[0]['bid']
                        for tk in ticks:
                            bid = tk['bid']
                            if bid > prev_bid:
                                direction = "BUY"
                            elif bid < prev_bid:
                                direction = "SELL"
                            else:
                                direction = "NEUTRAL"
                            prev_bid = bid
                            
                            vol = 1.0
                            lvl_p = round(math.floor(bid / self.price_step) * self.price_step, 2)
                            
                            if lvl_p not in levels:
                                levels[lvl_p] = {"buy": 0.0, "sell": 0.0, "delta": 0.0}
                                
                            if direction == "BUY":
                                levels[lvl_p]["buy"] += vol
                                levels[lvl_p]["delta"] += vol
                                total_buy += vol
                            elif direction == "SELL":
                                levels[lvl_p]["sell"] += vol
                                levels[lvl_p]["delta"] -= vol
                                total_sell += vol
                    else:
                        vol = float(row['tick_volume'])
                        buy_ratio = 0.55 if c >= o else 0.45
                        buy_vol = vol * buy_ratio
                        sell_vol = vol - buy_vol
                        
                        start_lvl = math.floor(l / self.price_step) * self.price_step
                        end_lvl = math.floor(h / self.price_step) * self.price_step
                        cells = round((end_lvl - start_lvl) / self.price_step) + 1
                        
                        if cells > 0:
                            b_cell = buy_vol / cells
                            s_cell = sell_vol / cells
                            p = start_lvl
                            while p <= end_lvl + self.price_step * 0.1:
                                px = round(p, 2)
                                levels[px] = {"buy": b_cell, "sell": s_cell, "delta": b_cell-s_cell}
                                p += self.price_step
                            total_buy = buy_vol
                            total_sell = sell_vol
                            
                    raw_data = {
                        "open": o, "high": h, "low": l, "close": c,
                        "total_volume": total_buy + total_sell,
                        "buy_volume": total_buy, "sell_volume": total_sell,
                        "delta": total_buy - total_sell,
                        "levels": levels,
                        "is_real": True if (ticks is not None and len(ticks) > 0) else False,
                        "time_str": time_str
                    }
                    
                    candle = FootprintCandle.from_tick_data(raw_data, self.price_step)
                    candle.timestamp = t_start_ms
                    
                    if len(self.buffer) > 0 and self.buffer[-1].time_str == time_str:
                        self.buffer[-1] = candle
                        added_or_updated += 1
                    else:
                        is_duplicate = False
                        for existing in self.buffer:
                            if existing.time_str == time_str:
                                is_duplicate = True
                                break
                        if not is_duplicate:
                            self.buffer.append(candle)
                            added_or_updated += 1
                            
                if self.buffer:
                    self.last_timestamp = self.buffer[-1].timestamp
            return added_or_updated

        # --- BINANCE FALLBACK ---
        url = f"{BASE_URL}/fapi/v1/klines"
        params = {
            "symbol": BINANCE_SYMBOL,
            "interval": self.interval,
            "startTime": self.last_timestamp + 1,
            "limit": 10,
        }

        try:
            import requests # type: ignore
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            print(f"[footprint] ERROR updating {self.interval}: {e}")
            return 0

        added = 0
        with self._lock:
            for k in raw:
                ts = int(k[0])
                if ts > self.last_timestamp:
                    candle = FootprintCandle(k, self.price_step)
                    self.buffer.append(candle)  # deque.maxlen автоматически удаляет старые
                    self.last_timestamp = ts
                    added += 1

        if added > 0:
            print(f"[footprint] {self.interval}: +{added} new candle(s) from Binance, "
                  f"total {len(self.buffer)}")
        return added

    def get_candles(self) -> list[FootprintCandle]:
        """Возвращает копию текущего буфера (потокобезопасно)."""
        with self._lock:
            return list(self.buffer)

    def __len__(self):
        return len(self.buffer)


class FootprintCollector:
    """
    Главный менеджер футпринтов.
    Управляет буферами для всех таймфреймов и фоновым потоком обновления.
    """

    def __init__(self, intervals: list[str] = None):
        if intervals is None:
            intervals = ["1h", "4h", "1d"]

        self.buffers: dict[str, FootprintBuffer] = {}
        for ivl in intervals:
            self.buffers[ivl] = FootprintBuffer(ivl)

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def load_all(self, progress_cb=None):
        """Загружает начальные данные для всех таймфреймов."""
        print("[footprint] Loading initial data from Hybrid Dukascopy engine...")
        for ivl, buf in self.buffers.items():
            buf.load_initial(progress_cb=progress_cb)
            time.sleep(0.3)  # Не спамим API

    def start_background_updates(self, check_interval: int = 30):
        """Запускает фоновый поток обновления."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._update_loop,
            args=(check_interval,),
            daemon=True,
            name="FootprintUpdater",
        )
        self._thread.start()
        print(f"[footprint] Background updater started (every {check_interval}s)")

    def stop(self):
        """Останавливает фоновый поток."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            print("[footprint] Background updater stopped")

    def _update_loop(self, check_interval: int):
        """Фоновый цикл: проверяет новые свечи для каждого TF."""
        while self._running:
            for ivl, buf in self.buffers.items():
                try:
                    buf.update()
                except Exception as e:
                    print(f"[footprint] Update error ({ivl}): {e}")
                time.sleep(0.2)
            time.sleep(check_interval)

    def get_footprint(self, interval: str) -> list[FootprintCandle]:
        """Получает текущий буфер футпринтов для указанного TF."""
        buf = self.buffers.get(interval)
        if buf is None:
            print(f"[footprint] Unknown interval: {interval}")
            return []
        return buf.get_candles()

    def get_stats(self) -> dict:
        """Статистика по буферам."""
        return {ivl: len(buf) for ivl, buf in self.buffers.items()}


# ── Глобальный экземпляр (singleton) ─────────────────────────────────
_collector: Optional[FootprintCollector] = None


def get_collector() -> FootprintCollector:
    """Возвращает (или создает) глобальный экземпляр коллектора."""
    global _collector
    if _collector is None:
        _collector = FootprintCollector(["1h", "4h", "1d"])
    return _collector


# ── Тест ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    collector = get_collector()
    collector.load_all()

    print("\n--- Stats ---")
    for ivl, count in collector.get_stats().items():
        print(f"  {ivl}: {count} candles in buffer")

    # Показать последние 3 свечи каждого TF
    for ivl in ["1h", "4h", "1d"]:
        candles = collector.get_footprint(ivl)
        print(f"\n--- {ivl} (last 3) ---")
        for c in candles[-3:]:
            print(f"  {c}")
            # Показать топ-3 уровня по объёму
            sorted_lvls = sorted(c.levels.items(),
                                 key=lambda x: x[1]["buy"] + x[1]["sell"],
                                 reverse=True)
            for price, data in sorted_lvls[:3]:
                print(f"    ${price:.2f}: BUY {data['buy']:.2f} | "
                      f"SELL {data['sell']:.2f} | D:{data['delta']:+.2f}")
