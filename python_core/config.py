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


# ── Торговый инструмент ─────────────────────────────────────────────────────
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

# ── Таймфреймы для анализа ──────────────────────────────────────────────────
# Глубина истории: 100 свечей H4 — это всего ~2.5 недели, поэтому уровни
# находились только там, где цена ходила недавно. Берём ~4 месяца по H4 и год
# по D1, чтобы в анализ попадали крупные уровни выше текущей цены.
TIMEFRAMES = {
    "H1": {"mt5_tf": "TIMEFRAME_H1", "weight": 2, "bars": _env_int("BARS_H1", 720)},
    "H4": {"mt5_tf": "TIMEFRAME_H4", "weight": 3, "bars": _env_int("BARS_H4", 600)},
    "D1": {"mt5_tf": "TIMEFRAME_D1", "weight": 4, "bars": _env_int("BARS_D1", 365)},
}

# Главный таймфрейм для пересчёта и отбора.
PRIMARY_TIMEFRAME = "H4"
# Жёсткая привязка к H4 (зона без H4-подтверждения выбрасывается) вместе с
# пониженным весом H1 срезала большую часть уровней: в первых версиях этого
# фильтра не было и зоны отрабатывали. H4 остаётся главным через вес (3) и
# пересчёт по закрытию H4-свечи.
REQUIRE_H4_ANCHOR = _env_bool("REQUIRE_H4_ANCHOR", False)

# ── Весовая система (Scoring) ───────────────────────────────────────────────
# Каждый критерий добавляет баллы к зоне
WEIGHT_H1_WICK       = 2    # Тень свечи H1 касается уровня
WEIGHT_H4_WICK       = 3    # Тень свечи H4 касается уровня
WEIGHT_D1_WICK       = 4    # Тень свечи D1 касается уровня
WEIGHT_BIG_PLAYER    = 2    # Аномальный объём на уровне (крупный игрок)
WEIGHT_ROUND_LEVEL   = 1    # Круглый уровень (XX00.00 или XX50.00)
WEIGHT_FVG           = 5    # Зона совпадает с неперекрытым имбалансом (FVG)

# Минимальный суммарный вес для отображения зоны
MIN_ZONE_SCORE = _env_int("MIN_ZONE_SCORE", 11)

# ── Параметры кластеризации ─────────────────────────────────────────────────
# Допуск (tolerance) для склейки теней в один уровень.
# Если два фитиля отличаются менее чем на CLUSTER_TOLERANCE, они считаются
# касающимися одного уровня.
CLUSTER_TOLERANCE = 5.0          # В долларах (для XAU/USD). ~50 пунктов.
# Ниже, в блоке «Полоса отображения зон», CLUSTER_TOLERANCE пересчитывается под
# запрошенный шаг между зонами: склейка не имеет права быть шире шага, иначе три
# зоны на стороне схлопываются в одну.

# ── Ширина зоны ─────────────────────────────────────────────────────────────
ZONE_WIDTH = 1.0                 # ±$1.0 от центра кластера
ZONE_WIDTH_MODE = _env_str("ZONE_WIDTH_MODE", "atr")  # fixed | atr | regime
ATR_PERIOD = _env_int("ATR_PERIOD", 14)
ATR_MULTIPLIER = _env_float("ATR_MULTIPLIER", 0.5)
ZONE_WIDTH_MIN = _env_float("ZONE_WIDTH_MIN", 0.50)
ZONE_WIDTH_MAX = _env_float("ZONE_WIDTH_MAX", 8.00)
REGIME_ATR_LOW = _env_float("REGIME_ATR_LOW", 2.0)
REGIME_ATR_HIGH = _env_float("REGIME_ATR_HIGH", 6.0)

# ── Жизненный цикл active H4-зон ────────────────────────────────────────────
# Касание фитилём — это реакция, не смерть зоны. Снимаем только close-through
# телом H4 (см. LEGACY_BREAKOUT_MIN), как в старой версии.
TEST_INVALIDATES_ZONE = _env_bool("TEST_INVALIDATES_ZONE", False)
ZONE_EVENT_LOG_ENABLED = _env_bool("ZONE_EVENT_LOG_ENABLED", True)

# ── Фильтр "Крупный игрок" (Volume) ────────────────────────────────────────
# Свеча считается "крупной", если её тиковый объём превышает 
# среднее за VOLUME_LOOKBACK свечей в VOLUME_THRESHOLD_MULT раз.
VOLUME_LOOKBACK = 20             # Период для среднего объёма
VOLUME_THRESHOLD_MULT = 1.5      # Множитель: V > avg(V, 20) * 1.5

# ── Круглые уровни ──────────────────────────────────────────────────────────
ROUND_LEVEL_STEP = 50.0          # Шаг круглого уровня ($50 для золота = XX00 и XX50)

# ── Ограничение вывода ──────────────────────────────────────────────────────
# Единственный источник истины для отображения: три линии сверху и три снизу.
# Старые .env могли содержать MAX_ZONES_ON_CHART=5; его намеренно игнорируем,
# чтобы установленная сборка не возвращалась к несимметричному списку.
ZONES_PER_SIDE = _env_int("ZONES_PER_SIDE", 3)
MIN_ZONES_PER_SIDE = ZONES_PER_SIDE
# Клиент попросил вернуть поведение старой версии: никакой лестницы по
# расстоянию, просто сильнейшие зоны (топ по score), слабые — тусклее.
# Лестница остаётся в коде и включается флагом, чтобы можно было вернуться.
USE_ZONE_LADDER = _env_bool("USE_ZONE_LADDER", False)
# Жизненный цикл зон как в старой версии: сжигание после N пробоев телом H4,
# историчные зоны помечаются HIST и слабеют, без возрастного истечения.
LEGACY_ZONE_LIFECYCLE = _env_bool("LEGACY_ZONE_LIFECYCLE", True)
LEGACY_BREAKOUT_LOOKBACK = _env_int("LEGACY_BREAKOUT_LOOKBACK", 15)  # последние H4 свечи
LEGACY_BREAKOUT_MIN = _env_int("LEGACY_BREAKOUT_MIN", 2)             # пробоев для сжигания
LEGACY_ARCHIVE_MIN_SCORE = _env_int("LEGACY_ARCHIVE_MIN_SCORE", 12)  # «титаник»-зоны в архив
LEGACY_HIST_SCORE_PENALTY = _env_int("LEGACY_HIST_SCORE_PENALTY", 2) # насколько слабеет HIST
LEGACY_HIST_SCORE_FLOOR = _env_int("LEGACY_HIST_SCORE_FLOOR", 8)     # ниже не опускаем
# В окне 0..900 пунктов с каждой стороны показываем ВСЕ подходящие зоны,
# а не 3+3 слота. Верхняя граница — защита от сотен линий, не контракт.
MAX_ZONES_ON_CHART = _env_int("MAX_ZONES_ON_CHART", 80)

# ── Полоса отображения зон (главное требование клиента) ─────────────────────
# Раньше отбор шёл ТОЛЬКО по score: расстояние от цены не ограничивалось ни
# снизу, ни сверху, поэтому уровень мог встать в пяти пипсах от цены или в
# полутора тысячах. Теперь набор строится лестницей от цены:
#
#   слот 0 (ближайшая зона):  ZONE_NEAREST_MIN_PIPS .. ZONE_NEAREST_MAX_PIPS
#   слот k (k = 1, 2, ...):   предыдущая зона + ZONE_GAP_MIN_PIPS .. ZONE_GAP_MAX_PIPS
#
# Так выполняется и «ближайшая 200-300», и «шаг между ними 200-300».
# На клиентском терминале 1 pip по золоту = $0.1, значит слоты — это $20-30.
PIP_SIZE = _env_float("PIP_SIZE", 0.1)           # $ в одном пипсе XAU/USD
ZONE_NEAREST_MIN_PIPS = _env_float("ZONE_NEAREST_MIN_PIPS", 200.0)
ZONE_NEAREST_MAX_PIPS = _env_float("ZONE_NEAREST_MAX_PIPS", 300.0)
ZONE_GAP_MIN_PIPS = _env_float("ZONE_GAP_MIN_PIPS", 200.0)
ZONE_GAP_MAX_PIPS = _env_float("ZONE_GAP_MAX_PIPS", 300.0)
# «Примерно там»: допуск на растяжение окна слота, когда идеального кандидата
# в полосе нет. 0.25 = разрешаем отойти на 25% от ширины окна.
ZONE_BAND_TOLERANCE = _env_float("ZONE_BAND_TOLERANCE", 0.25)

# Те же величины в долларах — с ними работает весь остальной код.
ZONE_NEAREST_MIN = ZONE_NEAREST_MIN_PIPS * PIP_SIZE
ZONE_NEAREST_MAX = ZONE_NEAREST_MAX_PIPS * PIP_SIZE
ZONE_GAP_MIN = ZONE_GAP_MIN_PIPS * PIP_SIZE
ZONE_GAP_MAX = ZONE_GAP_MAX_PIPS * PIP_SIZE

# Дальняя граница набора: за ней зона уже не «в ренже» и снимается с графика.
ZONE_BAND_OUTER_MAX = (ZONE_NEAREST_MAX + ZONE_GAP_MAX * (ZONES_PER_SIDE - 1)) * (
    1.0 + ZONE_BAND_TOLERANCE
)

# Склейка близких уровней и ширина зоны обязаны быть мельче шага между зонами,
# иначе три зоны на стороне сливаются в одну линию. При клиентском PIP_SIZE=0.1
# шаг равен $20, поэтому склейка и ширина обязаны оставаться существенно меньше —
# это убирает схлопывание набора в одну область.
CLUSTER_TOLERANCE = _env_float("CLUSTER_TOLERANCE", min(CLUSTER_TOLERANCE, ZONE_GAP_MIN * 0.4))
ZONE_WIDTH_MAX = min(ZONE_WIDTH_MAX, ZONE_GAP_MIN * 0.35)
ZONE_WIDTH_MIN = min(ZONE_WIDTH_MIN, ZONE_WIDTH_MAX * 0.5)
ZONE_WIDTH = min(ZONE_WIDTH, ZONE_WIDTH_MAX)
# Запасной порог: если с одной стороны сильных зон нет, берём лучшие из более
# слабых кандидатов (только чтобы заполнить пустую сторону).
FALLBACK_MIN_ZONE_SCORE = _env_int("FALLBACK_MIN_ZONE_SCORE", 7)

# ── Только сильные зоны (требование клиента) ───────────────────────────────
# True: показываем ТОЛЬКО зоны score >= MIN_ZONE_SCORE. Если сильных зон нет —
# график остаётся пустым, слабые уровни НЕ достраиваются «для заполнения 3+3».
# Клиент: «алгоритм должен только находить сильные зоны; если их нет — не строить».
STRONG_ZONES_ONLY = _env_bool("STRONG_ZONES_ONLY", True)

# ── Единые зоны на всех брокерах (валидация/канон по Dukascopy) ─────────────
# Проблема: у разных брокеров цена XAU/USD отличается на оффсет, зоны «не ложатся».
# Решение — независимый эталон Dukascopy (см. broker_normalize.py):
#   VALIDATION_MODE = validate   # оставлять только зоны, подтверждённые Dukascopy
#   VALIDATION_MODE = canonical  # считать зоны целиком по Dukascopy (одинаково у всех)
#   VALIDATION_MODE = off        # выключить (как раньше)
# Зоны считаем по Dukascopy, на график брокера сдвигаем линию (цена брокера − Duka).
VALIDATION_MODE = _env_str("VALIDATION_MODE", "canonical")
VALIDATION_TOLERANCE = _env_float("VALIDATION_TOLERANCE", 5.0)  # $ допуск совпадения
BROKER_OFFSET_ENABLED = _env_bool("BROKER_OFFSET_ENABLED", True)  # сдвиг на цену брокера
DUKA_SYMBOL = _env_str("DUKA_SYMBOL", "XAUUSD")
DUKA_DAYS = _env_int("DUKA_DAYS", 5)  # короткая выборка для валидации/оффсета
# Глубина тиков Dukascopy для OHLC. 100 дней покрывает H1 720 и H4 600.
# Больше (до 365) — полная D1-история, первая загрузка дольше, дальше кэш.
DUKA_OHLC_DAYS = _env_int("DUKA_OHLC_DAYS", 100)

# ── Диапазон отображения зон (требование клиента) ──────────────────────────
# Показываем сильные зоны в пределах 0…MAX_ZONE_DISTANCE_PIPS пунктов от цены,
# В ОБЕ стороны, начиная от самых близких. Никакой «лестницы» с минимальным
# отступом — близкие к цене зоны (напр. 4786 в $1 от цены) обязаны показываться.
# Как в старой версии: ограничения по расстоянию НЕТ вообще. Зона живёт там,
# где её нашёл детектор, отбор идёт только по силе (score) и лимиту на графике.
# Окно показа: k × ATR(H1). 0 пунктов = только ATR (дефолт).
# Положительный MAX_ZONE_DISTANCE_PIPS — жёсткий потолок в пунктах поверх ATR.
ZONE_WINDOW_ATR = _env_float("ZONE_WINDOW_ATR", 10.0)
MAX_ZONE_DISTANCE_PIPS = _env_float("MAX_ZONE_DISTANCE_PIPS", 0.0)
MAX_ZONE_DISTANCE = MAX_ZONE_DISTANCE_PIPS * PIP_SIZE

# На графике только зоны, у которых уже есть/идёт реакция:
# отскок, проторговка (консолидация) или подход/касание. NONE и BREAKOUT скрываем.
DISPLAY_REACTION_TYPES = tuple(
    s.strip().upper()
    for s in _env_str(
        "DISPLAY_REACTION_TYPES",
        "BOUNCE,CONSOLIDATION,APPROACHING",
    ).split(",")
    if s.strip()
)

# ── Реакция цены на зону (zone_reaction.py) ────────────────────────────────
# Классификация: отскок / консолидация / пробой. Пороги в единицах ATR,
# чтобы фильтровать шум (идея из pymarket-structure), пробой — по закрытию
# за уровень (идея из neurotrader888).
REACTION_ENABLED = _env_bool("REACTION_ENABLED", True)
# Таймфрейм для «закрепа» за зоной: клиент смотрит закрепление на H1.
REACTION_TIMEFRAME = _env_str("REACTION_TIMEFRAME", "H1")
REACTION_LOOKBACK_BARS = _env_int("REACTION_LOOKBACK_BARS", 60)   # сколько баров анализировать
REACTION_ATR_PERIOD = _env_int("REACTION_ATR_PERIOD", 14)        # период ATR (масштаб шума)
REACTION_WINDOW_AFTER = _env_int("REACTION_WINDOW_AFTER", 8)     # баров после касания на исход
REACTION_BREAKOUT_ATR = _env_float("REACTION_BREAKOUT_ATR", 0.5)  # пробой: закрытие > k·ATR за зоной
REACTION_BOUNCE_ATR = _env_float("REACTION_BOUNCE_ATR", 0.75)     # отскок: уход прочь > k·ATR
REACTION_CONSOLIDATION_ATR = _env_float("REACTION_CONSOLIDATION_ATR", 1.2)  # консолидация: разброс закрытий < k·ATR
REACTION_MIN_CONSOLIDATION_BARS = _env_int("REACTION_MIN_CONSOLIDATION_BARS", 3)  # мин. баров подряд у зоны
REACTION_APPROACH_ATR = _env_float("REACTION_APPROACH_ATR", 0.6)  # «подходит»: ближе k·ATR к зоне
# Когда цена на историческом максимуме, над ней теней просто нет — детектор
# физически не может найти уровень, и график остаётся пустым сверху. В этом
# случае проецируем ближайшие круглые уровни (шаг ROUND_LEVEL_STEP).
# Клиент просил «только зоны, ничего лишнего»: расчётный круглый уровень — это
# не зона, под ним на графике нет ни одной тени. Выключено по умолчанию.
PROJECT_ROUND_LEVELS = _env_bool("PROJECT_ROUND_LEVELS", False)
# Ближе этого расстояния (в % от цены) круглый уровень бесполезен.
PROJECTED_LEVEL_MIN_DISTANCE_PCT = _env_float("PROJECTED_LEVEL_MIN_DISTANCE_PCT", 0.25)
ZONE_COLOR_STRONG = "#FF0000"    # Ярко-красный для сильных зон (score >= 9)
ZONE_COLOR_MEDIUM = "#FF4D4D"    # Средне-красный (score 7-8)
ZONE_COLOR_WEAK   = "#FF9999"    # Бледно-красный (score < 7)

# ── Binance Futures (для реальной дельты объёма) ────────────────────────────
# ВНИМАНИЕ: fapi.binance.com отдаёт HTTP 451 «Service unavailable from a
# restricted location» для РФ. У целевого пользователя источник недоступен,
# поэтому в подтверждении зон он не участвует — дельта берётся из тиков MT5.
BINANCE_BASE_URL = "https://fapi.binance.com"
BINANCE_SYMBOL = "XAUUSDT"

# ── Подтверждение зон по ликвидности (экспериментальный слой) ──────────────
# Детектор находит уровни по фитилям — это ответ на вопрос «где цена уже
# отбивалась». Но фитиль двухнедельной давности не гарантирует, что уровень
# жив сейчас: если объём там больше не проходит, а стопы под ним сняли, зона
# не отработает. Слой подтверждения отвечает именно на этот второй вопрос.
#
# Подтверждение НЕ добавляется в score. Это отдельное измерение:
#   score        — структурная значимость уровня (сколько фитилей, каких ТФ)
#   confirmation — жив ли он прямо сейчас (0..1)
# Смешивать их нельзя: сильный по структуре уровень может быть мёртвым, и
# суммарное число это бы замаскировало.
#
#   off      — слой выключен, поведение как до эксперимента
#   annotate — считаем и показываем, состав зон не меняем (по умолчанию)
#   filter   — зоны с вердиктом DEAD убираются
#   rerank   — кандидаты сортируются по score * (0.5 + confirmation)
CONFIRMATION_MODE = _env_str("CONFIRMATION_MODE", "filter")
# Метка подтверждения в подписи: выкл. — на графике только линия и цена.
CONFIRMATION_IN_LABEL = _env_bool("CONFIRMATION_IN_LABEL", False)

# Веса проверок. Чем прямее измерение, тем больше вес: проторгованный объём —
# это факт из истории сделок, свежесть — производная оценка.
CONFIRM_WEIGHT_VOLUME_NODE    = _env_float("CONFIRM_WEIGHT_VOLUME_NODE", 0.40)
CONFIRM_WEIGHT_LIQUIDITY_POOL = _env_float("CONFIRM_WEIGHT_LIQUIDITY_POOL", 0.25)
CONFIRM_WEIGHT_DELTA          = _env_float("CONFIRM_WEIGHT_DELTA", 0.20)
CONFIRM_WEIGHT_FRESHNESS      = _env_float("CONFIRM_WEIGHT_FRESHNESS", 0.15)

# Пороги вердикта. Зона между порогами — WATCH: показываем, но не полагаемся.
CONFIRM_LIVE_THRESHOLD = _env_float("CONFIRM_LIVE_THRESHOLD", 0.65)
CONFIRM_DEAD_THRESHOLD = _env_float("CONFIRM_DEAD_THRESHOLD", 0.40)

# ── Профиль объёма ─────────────────────────────────────────────────────────
# Во сколько раз объём на уровне должен превышать свою «справедливую долю»
# (общий объём ÷ число строк профиля), чтобы уровень считался узлом (HVN),
# и ниже какой доли — пустотой (LVN).
# Нормировка именно на среднюю долю, а не на медиану: профиль сильно перекошен
# хвостами, где цена оставила крохи объёма, и медиана садится на эту крошку.
# На синтетике с заранее заданной пустотой медиана давала ×0.96 («норма»)
# вместо ×0.20 — то есть не отличала пустоту от обычного уровня.
HVN_RATIO = _env_float("HVN_RATIO", 1.5)
LVN_RATIO = _env_float("LVN_RATIO", 0.5)

#   auto  — тики, если есть; иначе профиль по свечам
#   ticks — только реальные тики (профиль не строится, если их нет)
#   bars  — только свечная аппроксимация (быстро, не трогает терминал)
LIQUIDITY_SOURCE = _env_str("LIQUIDITY_SOURCE", "auto")
# Глубина тиковой истории. Сутки по золоту — сотни тысяч тиков, поэтому
# держим отдельным параметром: запрос на месяц вешает терминал минутами.
TICK_HISTORY_DAYS = _env_int("TICK_HISTORY_DAYS", 5)
MIN_TICKS_FOR_PROFILE = _env_int("MIN_TICKS_FOR_PROFILE", 5000)

# Допуск, в пределах которого экстремумы считаются «равными» и образуют пул
# стопов — в долях от полного диапазона истории.
LIQUIDITY_POOL_RANGE_PCT = _env_float("LIQUIDITY_POOL_RANGE_PCT", 0.005)


def zone_color_for_score(score: int) -> tuple[str, float]:
    """Возвращает (hex_color, alpha) для зоны по её score."""
    if score >= 9:
        return ZONE_COLOR_STRONG, 0.15
    if score >= 7:
        return ZONE_COLOR_MEDIUM, 0.10
    return ZONE_COLOR_WEAK, 0.07


# ── Данные ──────────────────────────────────────────────────────────────────
# Источник свечей для детектора. dukascopy — эталон (зоны одинаковые на всех
# брокерах). mt5/csv — старый порядок, Duka остаётся в цепочке как fallback.
DATA_SOURCE = _env_str("DATA_SOURCE", "dukascopy")
CSV_DIR = str(LOCAL_DATA_DIR)    # Каталог с CSV (вычисляется из BASE_DIR)

# Синтетические (случайные) свечи допустимы ТОЛЬКО для отладки. В продакшене
# по ним считались зоны «из воздуха» — каждый пересчёт давал другой результат,
# уровни не совпадали с графиком. Теперь требуется явное разрешение.
ALLOW_SAMPLE_DATA = _env_bool("ALLOW_SAMPLE_DATA", False)

# Максимальный возраст последней свечи, при котором данные считаем свежими.
# Если данные старше — пробуем следующий источник и пишем предупреждение
# (иначе зоны считались по устаревшим CSV и «отставали» от графика).
MAX_DATA_AGE_HOURS = _env_float("MAX_DATA_AGE_HOURS", 12.0)

# ── Актуальность зон ────────────────────────────────────────────────────────
# Архивные («вечные») зоны в первых версиях жили, пока их не пробьют, и именно
# они давали уровни там, где цена уже давно не ходила. Срок жизни и фильтр
# удалённости вычищали их и оставляли на графике 2-3 уровня, поэтому по
# умолчанию оба ограничения выключены (0 = не применять).
PERSISTENT_ZONE_MAX_AGE_DAYS = _env_float("PERSISTENT_ZONE_MAX_AGE_DAYS", 0.0)
MAX_ZONE_DISTANCE_PCT = _env_float("MAX_ZONE_DISTANCE_PCT", 0.0)
# Пробой архивной зоны ищем только в недавней истории и требуем повторности:
# при проверке по всей истории любая зона «сгорала» в том же пересчёте, в котором
# была добавлена, и архив зон не работал вообще.
PERSISTENT_BREAKOUT_LOOKBACK = _env_int("PERSISTENT_BREAKOUT_LOOKBACK", 15)
PERSISTENT_BREAKOUT_MIN = _env_int("PERSISTENT_BREAKOUT_MIN", 2)

# ── Набор позиции крупным участником ────────────────────────────────────────
# Участок набора = аномально большой объём при почти стоящей цене.
# Рисуется маленькими фиолетовыми прямоугольниками, отключается в настройках
# индикатора (ShowAccumulation) или через ACCUMULATION_ENABLED=0.
# Клиент просил убрать крупных игроков с графика — боксы набора позиции больше
# не рисуются по умолчанию (включается ACCUMULATION_ENABLED=1).
ACCUMULATION_ENABLED = _env_bool("ACCUMULATION_ENABLED", False)
# Считаем на H4: клиент смотрит H4, а участки по H1 занимали меньше одной свечи
# графика и были не видны.
ACCUMULATION_TIMEFRAME = _env_str("ACCUMULATION_TIMEFRAME", "H4")
ACCUMULATION_WINDOW = _env_int("ACCUMULATION_WINDOW", 3)          # свечей в участке
ACCUMULATION_VOLUME_MULT = _env_float("ACCUMULATION_VOLUME_MULT", 1.4)
ACCUMULATION_MAX_RANGE_MULT = _env_float("ACCUMULATION_MAX_RANGE_MULT", 0.8)
ACCUMULATION_LOOKBACK_BARS = _env_int("ACCUMULATION_LOOKBACK_BARS", 200)
ACCUMULATION_MAX_BOXES = _env_int("ACCUMULATION_MAX_BOXES", 12)
# Если ни один участок не прошёл пороги (у разных брокеров совершенно разный
# характер tick_volume), показываем лучшие участки по отношению объёма к ходу
# цены — иначе фиолетовых прямоугольников у клиента не появляется вообще.
ACCUMULATION_FALLBACK_BOXES = _env_int("ACCUMULATION_FALLBACK_BOXES", 3)
ACCUMULATION_FALLBACK_MIN_VOL = _env_float("ACCUMULATION_FALLBACK_MIN_VOL", 1.05)

# ── ZeroMQ (для связи с MetaTrader) ─────────────────────────────────────────
ZMQ_HOST = _env_str("ZMQ_HOST", "tcp://127.0.0.1")
ZMQ_PORT = _env_int("ZMQ_PORT", 5555)

# ── Telegram Алерты ─────────────────────────────────────────────────────────
ENABLE_TELEGRAM    = _env_bool("ENABLE_TELEGRAM", False)
TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = _env_str("TELEGRAM_CHAT_ID", "")
