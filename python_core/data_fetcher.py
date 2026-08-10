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


# Длительность свечи по таймфреймам — допуск к возрасту данных.
TF_BAR_HOURS = {"M1": 1.0, "M5": 1.0, "M15": 1.0, "H1": 1.0, "H4": 4.0, "D1": 24.0}

# Золото торгуется вс. 22:00 UTC → пт. 21:00 UTC.
MARKET_CLOSE_HOUR_UTC = 21
MARKET_OPEN_HOUR_UTC = 22


class DataUnavailableError(RuntimeError):
    """Ни один источник не дал пригодных свечей.

    Осознанно поднимаем ошибку вместо возврата синтетики: лучше оставить в MT
    прошлые зоны, чем нарисовать уровни по случайным данным.
    """


def _normalize(name: str) -> str:
    return "".join(ch for ch in name.upper() if ch.isalnum())


def resolve_mt5_symbol(symbol: str) -> str:
    """Возвращает реальное имя символа у брокера.

    У брокеров золото называется XAUUSD, XAUUSD.m, XAUUSDm, GOLD и т.п.
    Ищем точное совпадение, затем совпадение по базовому имени с суффиксом,
    затем по алиасам из config.SYMBOL_ALIASES.
    """
    if mt5.symbol_info(symbol) is not None:
        mt5.symbol_select(symbol, True)
        return symbol

    available = mt5.symbols_get() or ()
    bases = [symbol] + [a for a in config.SYMBOL_ALIASES if a != symbol]

    for base in bases:
        nb = _normalize(base)
        if not nb:
            continue
        matches = [s.name for s in available if _normalize(s.name).startswith(nb)]
        if matches:
            # Самое короткое имя — обычно основной инструмент, а не производные
            # вроде XAUUSD.fix / XAUUSD-ECN.
            best = sorted(matches, key=len)[0]
            mt5.symbol_select(best, True)
            print(f"[data_fetcher] Symbol '{symbol}' resolved to broker symbol '{best}'")
            return best

    raise DataUnavailableError(
        f"Symbol '{symbol}' not found at broker (tried aliases: {bases})"
    )


def market_reference_time(now: datetime) -> datetime:
    """Момент, от которого считаем свежесть данных.

    Золото не торгуется с вечера пятницы до вечера воскресенья: в выходные
    последняя свеча «стареет» на десятки часов, и проверка свежести
    забраковывала совершенно нормальные данные — зоны не обновлялись вообще.
    Пока рынок закрыт, отсчитываем возраст от закрытия пятницы.
    """
    weekday = now.weekday()  # 0 = понедельник
    closed = (weekday == 5
              or (weekday == 4 and now.hour >= MARKET_CLOSE_HOUR_UTC)
              or (weekday == 6 and now.hour < MARKET_OPEN_HOUR_UTC))
    if not closed:
        return now
    friday = (now - timedelta(days=(weekday - 4) % 7)).replace(
        hour=MARKET_CLOSE_HOUR_UTC, minute=0, second=0, microsecond=0)
    return min(now, friday)


def data_age_hours(df: pd.DataFrame, reference: datetime | None = None) -> float:
    """Возраст последней свечи в часах (по UTC). inf, если времени нет."""
    if df is None or df.empty or "time" not in df.columns:
        return float("inf")
    last = pd.to_datetime(df["time"].iloc[-1])
    if last.tzinfo is not None:
        last = last.tz_convert(None)
    ref = reference if reference is not None else market_reference_time(datetime.utcnow())
    return (ref - last.to_pydatetime()).total_seconds() / 3600.0


def max_age_hours(tf_label: str) -> float:
    """Допустимый возраст последней свечи для таймфрейма.

    Время свечи — это её ОТКРЫТИЕ, поэтому свежая дневная свеча уже к обеду
    «старше» 12 часов. Общий лимит на все ТФ отбраковывал нормальные данные
    во второй половине дня (возраст считался как max по H1/H4/D1), и зоны
    полдня не пересчитывались вообще.
    """
    return config.MAX_DATA_AGE_HOURS + TF_BAR_HOURS.get(tf_label, 1.0)


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

    broker_symbol = resolve_mt5_symbol(symbol)

    rates = mt5.copy_rates_from_pos(broker_symbol, tf, 0, bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(
            f"No data for {broker_symbol} {timeframe_str}: {mt5.last_error()}"
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


def csv_encoding(csv_path: Path) -> str:
    """MT5-советник пишет CSV в UTF-16 — без этого файл не парсится."""
    with open(csv_path, "rb") as f:
        head = f.read(4)
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    return "utf-8"


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

    encoding = csv_encoding(csv_path)

    # Читаем с пропуском комментариев (# broker=..., # symbol=...)
    df = pd.read_csv(csv_path, parse_dates=['time'], comment='#', encoding=encoding)

    # Логируем источник данных
    with open(csv_path, 'r', encoding=encoding) as f:
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
    problems: list[str] = []

    for name, loader in _source_chain(symbol):
        try:
            data = loader()
        except Exception as e:
            problems.append(f"{name}: {e}")
            print(f"[data_fetcher] Source '{name}' failed: {e}")
            continue

        missing = [tf for tf in config.TIMEFRAMES if tf not in data or data[tf].empty]
        if missing:
            problems.append(f"{name}: no data for {', '.join(missing)}")
            print(f"[data_fetcher] Source '{name}' incomplete (missing {missing})")
            continue

        reference = market_reference_time(datetime.utcnow())
        ages = {tf: data_age_hours(df, reference) for tf, df in data.items()}
        stale = {tf: age for tf, age in ages.items() if age > max_age_hours(tf)}
        if stale:
            detail = ", ".join(f"{tf} {age:.1f}h > {max_age_hours(tf):.0f}h"
                               for tf, age in stale.items())
            problems.append(f"{name}: stale ({detail})")
            print(f"[data_fetcher] Source '{name}' is STALE ({detail})")
            continue

        print(f"[data_fetcher] Using source '{name}' (candle age: " +
              ", ".join(f"{tf} {age:.1f}h" for tf, age in ages.items()) + ")")
        for tf_label, df in data.items():
            print(f"  {tf_label}: {len(df)} bars "
                  f"({df['time'].iloc[0]} -> {df['time'].iloc[-1]})")
        return data

    if config.ALLOW_SAMPLE_DATA:
        print("[data_fetcher] WARN: no real data, generating SYNTHETIC sample data "
              "(ALLOW_SAMPLE_DATA=1) — zones will NOT match the chart")
        return generate_sample_data(symbol)

    raise DataUnavailableError(
        "No usable candle data. Tried: " + "; ".join(problems) +
        ". Check that MetaTrader is running and logged in (or that "
        "SmartZonesCollector is attached to a chart)."
    )


def _source_chain(symbol: str):
    """Источники данных по приоритету: терминал → CSV от советника → yfinance.

    Раньше при недоступном MT5 код молча уходил в generate_sample_data() и
    считал зоны по случайным свечам. Теперь каждый источник проверяется на
    полноту и свежесть, а синтетика — только по явному флагу.
    """
    def from_mt5():
        if not MT5_AVAILABLE:
            raise DataUnavailableError("MetaTrader5 package not installed")
        return {
            tf_label: fetch_from_mt5(symbol, tf_cfg["mt5_tf"], tf_cfg["bars"])
            for tf_label, tf_cfg in config.TIMEFRAMES.items()
        }

    def from_csv():
        return {tf_label: fetch_from_csv(symbol, tf_label)
                for tf_label in config.TIMEFRAMES}

    def from_yfinance():
        from download_real_data import download_and_save
        download_and_save()
        return from_csv()

    chain = [("csv", from_csv), ("mt5", from_mt5)] \
        if config.DATA_SOURCE == "csv" else [("mt5", from_mt5), ("csv", from_csv)]
    chain.append(("yfinance", from_yfinance))
    return chain


if __name__ == "__main__":
    # Quick test
    candles = fetch_all_timeframes()
    for tf, df in candles.items():
        print(f"\n{tf} — last 3 candles:")
        print(df.tail(3).to_string(index=False))
