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
        print(f"[config] WARN: invalid integer for {name}={raw!r}, using default {default}")
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[config] WARN: invalid float for {name}={raw!r}, using default {default}")
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

# У разных брокеров золото называется по-разному: XAUUSD, XAUUSD.m, XAUUSDm,
# GOLD, GOLD.spot… Если точного совпадения с SYMBOL нет, ищем среди этих
# базовых имён (с любым суффиксом брокера). Иначе запрос свечей падал с
# ошибкой и зоны не обновлялись вообще.
SYMBOL_ALIASES = [
    s.strip() for s in _env_str("SYMBOL_ALIASES", "XAUUSD,GOLD,XAUUSD.,GOLDSPOT,XAU").split(",")
    if s.strip()
]

# ── Таймфреймы для анализа ───────────────────────────────────────────
TIMEFRAMES = {
    "H1": {"mt5_tf": "TIMEFRAME_H1", "weight": 1, "bars": 200},
    "H4": {"mt5_tf": "TIMEFRAME_H4", "weight": 3, "bars": 100},
    "D1": {"mt5_tf": "TIMEFRAME_D1", "weight": 4, "bars": 60},
}

# Главный таймфрейм. Зона отображается только если её подтверждает H4 —
# H1/D1/FVG лишь усиливают H4-зону, но сами по себе зоны не создают. Это
# убирает «шум» из мелких H1-уровней. Отключается через REQUIRE_H4_ANCHOR=0.
PRIMARY_TIMEFRAME = "H4"
REQUIRE_H4_ANCHOR = _env_bool("REQUIRE_H4_ANCHOR", True)

# ── Весовая система (Scoring) ────────────────────────────────────────
# Каждый критерий добавляет баллы к зоне
WEIGHT_H1_WICK       = 1    # Тень свечи H1 касается уровня (H1 менее важен, чем H4)
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

# ── Binance Futures (для реальной дельты объёма) ─────────────────────
BINANCE_BASE_URL = "https://fapi.binance.com"
BINANCE_SYMBOL = "XAUUSDT"


def zone_color_for_score(score: int) -> tuple[str, float]:
    """Возвращает (hex_color, alpha) для зоны по её score."""
    if score >= 9:
        return ZONE_COLOR_STRONG, 0.15
    if score >= 7:
        return ZONE_COLOR_MEDIUM, 0.10
    return ZONE_COLOR_WEAK, 0.07


# ── Данные ───────────────────────────────────────────────────────────
# Источник данных для алгоритма. "mt5" будет тянуть данные напрямую от терминала
# в скрытом фоновом режиме. "csv" - через EA.
DATA_SOURCE = _env_str("DATA_SOURCE", "mt5")
CSV_DIR = str(LOCAL_DATA_DIR)    # Каталог с CSV (вычисляется из BASE_DIR)

# Синтетические (случайные) свечи допустимы ТОЛЬКО для отладки. В продакшене
# по ним считались зоны «из воздуха» — каждый пересчёт давал другой результат,
# уровни не совпадали с графиком. Теперь требуется явное разрешение.
ALLOW_SAMPLE_DATA = _env_bool("ALLOW_SAMPLE_DATA", False)

# Максимальный возраст последней свечи, при котором данные считаем свежими.
# Если данные старше — пробуем следующий источник и пишем предупреждение
# (иначе зоны считались по устаревшим CSV и «отставали» от графика).
MAX_DATA_AGE_HOURS = _env_float("MAX_DATA_AGE_HOURS", 12.0)

# ── Актуальность зон ─────────────────────────────────────────────────
# «Вечные» (архивные) зоны не должны висеть бесконечно: снимаем их по сроку
# жизни и по удалению от текущей цены. Свежие зоны всегда приоритетнее.
PERSISTENT_ZONE_MAX_AGE_DAYS = _env_float("PERSISTENT_ZONE_MAX_AGE_DAYS", 14.0)
# Фильтр удалённости применяется только к архивным зонам: свежие зоны детектор
# только что нашёл по реальным свечам, отбрасывать их по расстоянию нельзя —
# иначе на графике вместо MAX_ZONES_ON_CHART остаётся 2-3 уровня.
MAX_ZONE_DISTANCE_PCT = _env_float("MAX_ZONE_DISTANCE_PCT", 10.0)
# Пробой архивной зоны ищем только в недавней истории и требуем повторности:
# при проверке по всей истории любая зона «сгорала» в том же пересчёте, в котором
# была добавлена, и архив зон не работал вообще.
PERSISTENT_BREAKOUT_LOOKBACK = _env_int("PERSISTENT_BREAKOUT_LOOKBACK", 60)
PERSISTENT_BREAKOUT_MIN = _env_int("PERSISTENT_BREAKOUT_MIN", 2)

# ── Набор позиции крупным участником ────────────────────────────────
# Участок набора = аномально большой объём при почти стоящей цене.
# Рисуется маленькими фиолетовыми прямоугольниками, отключается в настройках
# индикатора (ShowAccumulation) или через ACCUMULATION_ENABLED=0.
ACCUMULATION_ENABLED = _env_bool("ACCUMULATION_ENABLED", True)
# Считаем на H4: клиент смотрит H4, а участки по H1 занимали меньше одной свечи
# графика и были не видны.
ACCUMULATION_TIMEFRAME = _env_str("ACCUMULATION_TIMEFRAME", "H4")
ACCUMULATION_WINDOW = _env_int("ACCUMULATION_WINDOW", 3)          # свечей в участке
ACCUMULATION_VOLUME_MULT = _env_float("ACCUMULATION_VOLUME_MULT", 1.4)
ACCUMULATION_MAX_RANGE_MULT = _env_float("ACCUMULATION_MAX_RANGE_MULT", 0.8)
ACCUMULATION_LOOKBACK_BARS = _env_int("ACCUMULATION_LOOKBACK_BARS", 200)
ACCUMULATION_MAX_BOXES = _env_int("ACCUMULATION_MAX_BOXES", 12)

# ── ZeroMQ (для связи с MetaTrader) ─────────────────────────────────
ZMQ_HOST = _env_str("ZMQ_HOST", "tcp://127.0.0.1")
ZMQ_PORT = _env_int("ZMQ_PORT", 5555)

# ── Telegram Алерты ──────────────────────────────────────────────────
ENABLE_TELEGRAM    = _env_bool("ENABLE_TELEGRAM", False)
TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = _env_str("TELEGRAM_CHAT_ID", "")
