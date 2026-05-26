"""
Smart Zones Pro — Конфигурация
Все параметры алгоритма собраны здесь для удобной калибровки.

Чувствительные значения (Telegram токен, путь установки и т.д.)
читаются из `.env` рядом с приложением. См. `.env.example` для шаблона.
"""

import os

# Загружает `.env` рядом с приложением, инициализирует пути.
from paths import (  # noqa: F401  (paths is imported for its side effects too)
    BASE_DIR,
    DATA_BRIDGE_DIR,
    LOCAL_DATA_DIR,
    OUTPUT_DIR,
    ZONES_FILE,
)


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


# ── Торговый инструмент ──────────────────────────────────────────────
SYMBOL = _env_str("SYMBOL", "XAUUSD")        # Символ в MetaTrader (у RoboForex именно так)
SYMBOL_POINT = 0.01                          # Минимальный шаг цены для золота
BROKER_UTC_OFFSET = _env_int("BROKER_UTC_OFFSET", 3)  # Смещение времени брокера (Обычно +3)

# ── Таймфреймы для анализа ───────────────────────────────────────────
TIMEFRAMES = {
    "H1": {"mt5_tf": "TIMEFRAME_H1", "weight": 2, "bars": 200},
    "H4": {"mt5_tf": "TIMEFRAME_H4", "weight": 3, "bars": 100},
    "D1": {"mt5_tf": "TIMEFRAME_D1", "weight": 4, "bars": 60},
}

# ── Весовая система (Scoring) ────────────────────────────────────────
# Каждый критерий добавляет баллы к зоне
WEIGHT_H1_WICK       = 2    # Тень свечи H1 касается уровня
WEIGHT_H4_WICK       = 3    # Тень свечи H4 касается уровня
WEIGHT_D1_WICK       = 4    # Тень свечи D1 касается уровня
WEIGHT_BIG_PLAYER    = 2    # Аномальный объём на уровне (крупный игрок)
WEIGHT_ROUND_LEVEL   = 1    # Круглый уровень (XX00.00 или XX50.00)
WEIGHT_FVG           = 5    # Зона совпадает с неперекрытым имбалансом (FVG)

# Минимальный суммарный вес для отображения зоны
MIN_ZONE_SCORE = _env_int("MIN_ZONE_SCORE", 11)

# ── Параметры кластеризации ──────────────────────────────────────────
# Допуск (tolerance) для склейки теней в один уровень.
# Если два фитиля отличаются менее чем на CLUSTER_TOLERANCE, они считаются
# касающимися одного уровня.
CLUSTER_TOLERANCE = 5.0          # В долларах (для XAU/USD). ~50 пунктов.

# ── Ширина зоны ──────────────────────────────────────────────────────
ZONE_WIDTH = 1.0                 # ±$1.0 от центра кластера
ZONE_WIDTH_MODE = "fixed"        # "fixed" | "atr" — динамическая через ATR(14)
ATR_PERIOD = 14
ATR_MULTIPLIER = 0.5             # zone_width = ATR * multiplier

# ── Фильтр "Крупный игрок" (Volume) ─────────────────────────────────
# Свеча считается "крупной", если её тиковый объём превышает 
# среднее за VOLUME_LOOKBACK свечей в VOLUME_THRESHOLD_MULT раз.
VOLUME_LOOKBACK = 20             # Период для среднего объёма
VOLUME_THRESHOLD_MULT = 1.5      # Множитель: V > avg(V, 20) * 1.5

# ── Круглые уровни ───────────────────────────────────────────────────
ROUND_LEVEL_STEP = 50.0          # Шаг круглого уровня ($50 для золота = XX00 и XX50)

# ── Ограничение вывода ────────────────────────────────────────────────
MAX_ZONES_ON_CHART = _env_int("MAX_ZONES_ON_CHART", 5)
ZONE_COLOR_STRONG = "#FF0000"    # Ярко-красный для сильных зон (score >= 9)
ZONE_COLOR_MEDIUM = "#FF4D4D"    # Средне-красный (score 7-8)
ZONE_COLOR_WEAK   = "#FF9999"    # Бледно-красный (score < 7)

# ── Данные ───────────────────────────────────────────────────────────
# Источник данных для алгоритма. "mt5" будет тянуть данные напрямую от терминала
# в скрытом фоновом режиме. "csv" - через EA.
DATA_SOURCE = _env_str("DATA_SOURCE", "mt5")
CSV_DIR = str(LOCAL_DATA_DIR)    # Каталог с CSV (вычисляется из BASE_DIR)

# ── ZeroMQ (для связи с MetaTrader) ─────────────────────────────────
ZMQ_HOST = _env_str("ZMQ_HOST", "tcp://127.0.0.1")
ZMQ_PORT = _env_int("ZMQ_PORT", 5555)

# ── Telegram Алерты ──────────────────────────────────────────────────
ENABLE_TELEGRAM    = _env_bool("ENABLE_TELEGRAM", False)
TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = _env_str("TELEGRAM_CHAT_ID", "")
