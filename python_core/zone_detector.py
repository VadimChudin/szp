"""
zone_detector.py — Ядро алгоритма.

Отвечает за:
  1. Извлечение уровней теней (верхний/нижний фитиль каждой свечи)
  2. Кластеризацию близких уровней в "зоны"
  3. Подсчёт количества касаний каждой зоны из разных таймфреймов
"""

import math

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
import config
from fvg_detector import detect_fvgs


def _json_safe_wick(wick: dict) -> dict:
    """Convert a wick-point dict into a JSON-serializable form.

    `wick_points` carry pandas/numpy values (e.g. a Timestamp in ``time``)
    that ``json.dump`` cannot encode. Normalize them so the exported
    ``zones_output.json`` (read by the MT4/MT5 indicator) is always valid.
    """
    safe = {}
    for key, value in wick.items():
        if isinstance(value, pd.Timestamp):
            safe[key] = value.isoformat()
        elif isinstance(value, np.generic):
            safe[key] = value.item()
        else:
            safe[key] = value
    return safe


@dataclass
class Zone:
    """Одна обнаруженная зона (уровень поддержки/сопротивления)."""
    price: float                          # Центральная цена зоны
    width: float = config.ZONE_WIDTH      # Ширина зоны (±width от price)
    score: int = 0                        # Суммарный вес (баллы)
    sources: list[str] = field(default_factory=list)  # Откуда зона: ["H1", "H4"]
    touch_count: int = 0                  # Сколько всего касаний
    has_big_player: bool = False          # Есть ли аномальный объём
    is_round_level: bool = False          # Круглый уровень
    # Фитили, сформировавшие зону: [(time, price, wick_type, tf_label), ...]
    wick_points: list = field(default_factory=list)
    label_suffix: str = ""                # Подпись для институциональных объемов
    # Когда зону последний раз подтвердил свежий расчёт (ISO-строка). Нужна
    # архивным «вечным» зонам, чтобы протухшие снимались по сроку жизни.
    archived_at: str = ""
    # Инкрементальный H4 lifecycle для отображаемого snapshot.
    state: str = "ACTIVE"                 # ACTIVE | TESTED | INVALIDATED
    test_count: int = 0
    created_at: str = ""
    last_test_at: str = ""
    invalidated_at: str = ""
    invalidation_reason: str = ""
    last_seen_h4: str = ""
    display_side: str = ""             # ABOVE | BELOW относительно текущей цены
    is_fallback: bool = False           # слабый, но реальный уровень для заполнения 3+3
    # ── Слой подтверждения (zone_confirmation) ───────────────────────────────
    # Держится отдельно от score сознательно: score говорит, насколько уровень
    # значим структурно, confirm_score — жив ли он сейчас. Сильный по структуре
    # уровень может стоять в ценовой пустоте, и одно суммарное число это бы
    # скрыло. Пустой словарь означает, что слой выключен или не отработал.
    confirmation: dict = field(default_factory=dict)
    confirm_score: float = 0.0          # 0..1
    confirm_verdict: str = ""           # LIVE | WATCH | DEAD

    # ── Слой ИИ (ai/annotator) ─────────────────────────────────────────────
    # Заполняется локальной моделью и НИКОГДА не влияет на price/width/state:
    # геометрию считает код, иначе канон «одинаковые зоны у всех брокеров»
    # разошёлся бы между запусками. Пустые значения = ИИ выключен или молчит.
    ai_verdict: str = ""                # LIVE | WATCH | SKIP
    ai_note: str = ""                   # одна фраза для подписи на графике
    ai_rank: int = 0                    # 1 — самая интересная зона, 0 — нет

    @property
    def top(self) -> float:
        return self.price + self.width

    @property
    def bottom(self) -> float:
        return self.price - self.width

    @property
    def label(self) -> str:
        """Текстовая подпись для графика: '2386.50 | H4+D1 | S:8'"""
        src = "+".join(sorted(set(self.sources)))
        bp = " BP" if self.has_big_player else ""
        rl = " RL" if self.is_round_level else ""
        return f"{self.price:.2f} | {src}{bp}{rl}{self.label_suffix} | S:{self.score}"

    def to_dict(self) -> dict:
        """Serialize zone to a JSON-ready dictionary."""
        return {
            "price": self.price,
            "top": self.top,
            "bottom": self.bottom,
            "width": self.width,
            "score": self.score,
            "sources": self.sources,
            "label": self.label,
            "has_big_player": self.has_big_player,
            "is_round_level": self.is_round_level,
            "touch_count": self.touch_count,
            "wick_points": [_json_safe_wick(w) for w in self.wick_points],
            "label_suffix": self.label_suffix,
            "archived_at": self.archived_at,
            "state": self.state,
            "test_count": self.test_count,
            "created_at": self.created_at,
            "last_test_at": self.last_test_at,
            "invalidated_at": self.invalidated_at,
            "invalidation_reason": self.invalidation_reason,
            "last_seen_h4": self.last_seen_h4,
            "display_side": self.display_side,
            "is_fallback": self.is_fallback,
            "confirmation": self.confirmation,
            "confirm_score": self.confirm_score,
            "confirm_verdict": self.confirm_verdict,
            "ai_verdict": self.ai_verdict,
            "ai_note": self.ai_note,
            "ai_rank": self.ai_rank,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Zone":
        """Deserialize zone from a dictionary."""
        return cls(
            price=d["price"],
            width=d.get("width", config.ZONE_WIDTH),
            score=d.get("score", 0),
            sources=d.get("sources", []),
            touch_count=d.get("touch_count", 0),
            has_big_player=d.get("has_big_player", False),
            is_round_level=d.get("is_round_level", False),
            wick_points=d.get("wick_points", []),
            label_suffix=d.get("label_suffix", ""),
            archived_at=d.get("archived_at", ""),
            state=d.get("state", "ACTIVE"),
            test_count=d.get("test_count", 0),
            created_at=d.get("created_at", ""),
            last_test_at=d.get("last_test_at", ""),
            invalidated_at=d.get("invalidated_at", ""),
            invalidation_reason=d.get("invalidation_reason", ""),
            last_seen_h4=d.get("last_seen_h4", ""),
            display_side=d.get("display_side", ""),
            is_fallback=d.get("is_fallback", False),
            confirmation=d.get("confirmation", {}),
            confirm_score=d.get("confirm_score", 0.0),
            confirm_verdict=d.get("confirm_verdict", ""),
            ai_verdict=d.get("ai_verdict", ""),
            ai_note=d.get("ai_note", ""),
            ai_rank=d.get("ai_rank", 0),
        )

    def __repr__(self):
        return f"Zone({self.label})"


def extract_wick_levels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Из каждой свечи извлекает уровни верхнего и нижнего фитиля.

    Верхний фитиль = High (если тело не касается High, т.е. есть тень сверху)
    Нижний фитиль = Low (если тело не касается Low, т.е. есть тень снизу)

    Фитиль считается значимым, если его длина >= 30% от полного диапазона свечи.
    Это отсекает свечи-марибозу (без теней), которые не формируют уровни.

    Returns:
        DataFrame с колонками: level, wick_type ("upper"/"lower"),
                               time, tick_volume, candle_range
    """
    records = []
    for _, row in df.iterrows():
        full_range = row['high'] - row['low']
        if full_range < config.SYMBOL_POINT * 10:
            continue  # Skip doji/micro candles

        body_top = max(row['open'], row['close'])
        body_bottom = min(row['open'], row['close'])

        upper_wick = row['high'] - body_top
        lower_wick = body_bottom - row['low']

        min_wick = full_range * 0.15  # Минимальная длина фитиля

        # Нижний фитиль → потенциальная поддержка
        if lower_wick >= min_wick:
            records.append({
                'level': row['low'],
                'wick_type': 'lower',
                'time': row['time'],
                'tick_volume': row.get('tick_volume', 0),
                'candle_range': full_range,
            })

        # Верхний фитиль → потенциальное сопротивление
        if upper_wick >= min_wick:
            records.append({
                'level': row['high'],
                'wick_type': 'upper',
                'time': row['time'],
                'tick_volume': row.get('tick_volume', 0),
                'candle_range': full_range,
            })

    return pd.DataFrame(records)


def cluster_levels(levels: np.ndarray, tolerance: float = None) -> list[dict]:
    """
    Кластеризует близкие ценовые уровни в группы.

    Алгоритм: жадная кластеризация.
      1. Сортируем уровни по цене.
      2. Идём по отсортированному массиву.
      3. Если следующий уровень отличается от текущего ядра кластера
         менее чем на tolerance — добавляем в кластер.
      4. Иначе закрываем кластер и начинаем новый.

    Args:
        levels: np.array цен фитилей
        tolerance: максимальное расхождение для объединения в кластер

    Returns:
        list of dict: [{"center": float, "count": int, "members": list}, ...]
    """
    if tolerance is None:
        tolerance = config.CLUSTER_TOLERANCE

    if len(levels) == 0:
        return []

    sorted_levels = np.sort(levels)
    clusters = []
    current_cluster = [sorted_levels[0]]

    for i in range(1, len(sorted_levels)):
        # Сравниваем с медианой текущего кластера
        cluster_center = np.median(current_cluster)
        if sorted_levels[i] - cluster_center <= tolerance:
            current_cluster.append(sorted_levels[i])
        else:
            clusters.append({
                "center": float(np.median(current_cluster)),
                "count": len(current_cluster),
                "members": list(current_cluster),
            })
            current_cluster = [sorted_levels[i]]

    # Последний кластер
    if current_cluster:
        clusters.append({
            "center": float(np.median(current_cluster)),
            "count": len(current_cluster),
            "members": list(current_cluster),
        })

    return clusters


def adaptive_zone_width(data: dict[str, pd.DataFrame]) -> float:
    """Return a bounded width based on closed H4 volatility."""
    base = float(config.ZONE_WIDTH)
    if config.ZONE_WIDTH_MODE == "fixed":
        return base
    frame = data.get(config.PRIMARY_TIMEFRAME)
    if frame is None or frame.empty or not {"high", "low", "close"}.issubset(frame.columns):
        return base
    tr = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - frame["close"].shift(1)).abs(),
        (frame["low"] - frame["close"].shift(1)).abs(),
    ], axis=1).max(axis=1).dropna()
    if tr.empty:
        return base
    atr = float(tr.tail(config.ATR_PERIOD).mean())
    if config.ZONE_WIDTH_MODE == "regime":
        regime_mult = 0.75 if atr <= config.REGIME_ATR_LOW else 1.25 if atr >= config.REGIME_ATR_HIGH else 1.0
        atr *= regime_mult
    width = atr * float(config.ATR_MULTIPLIER)
    return max(float(config.ZONE_WIDTH_MIN), min(float(config.ZONE_WIDTH_MAX), width))


def detect_zones(
    data: dict[str, pd.DataFrame],
    volume_flags: dict[str, np.ndarray] | None = None,
    limit_output: bool = True,
) -> list[Zone]:
    """
    Главная функция поиска зон.

    Алгоритм:
      1. Для каждого таймфрейма (H1, H4, D1) извлекаем уровни фитилей.
      2. Объединяем все уровни в единый массив.
      3. Кластеризуем близкие уровни.
      4. Для каждого кластера считаем Score на основе:
         - из каких таймфреймов пришли касания (H1=+2, H4=+3, D1=+4)
         - есть ли свечи с аномальным объёмом (BigPlayer=+2)
         - круглый ли уровень (+1)
      5. Фильтруем по MIN_ZONE_SCORE.

    Args:
        data: {"H1": DataFrame, "H4": DataFrame, "D1": DataFrame}
        volume_flags: {"H1": bool_array, ...} — True для свечей с аномальным объёмом.
                      Если None, объёмный фильтр не применяется.

    Returns:
        list[Zone]: Отсортированный по score (desc) список сильных зон.
    """
    # ── Шаг 1: Собираем все уровни со всех таймфреймов ───────────────
    all_levels = []  # list of (price, timeframe_label, has_volume_flag)

    for tf_label, df in data.items():
        wicks = extract_wick_levels(df)
        if wicks.empty:
            continue

        # Проверяем объёмные флаги
        vol_flags = None
        if volume_flags and tf_label in volume_flags:
            vol_flags = volume_flags[tf_label]

        for idx, row in wicks.iterrows():
            has_vol = False
            if vol_flags is not None:
                # Ищем индекс свечи по времени
                candle_idx = df.index[df['time'] == row['time']]
                if len(candle_idx) > 0 and candle_idx[0] < len(vol_flags):
                    has_vol = bool(vol_flags[candle_idx[0]])

            all_levels.append({
                'price': row['level'],
                'tf': tf_label,
                'has_volume': has_vol,
                'time': row['time'],
                'wick_type': row['wick_type'],
            })

    # ── Шаг 1.5: Добавляем эталонные уровни из Footprint (POC) ───────
    if getattr(config, "FOOTPRINT_LEVELS_IN_ZONES", False):
        try:
            from footprint_data import get_collector
            # Используем кэшированный синглтон (данные уже загружены bridge_server'ом)
            collector = get_collector()
        
            for tf_key, tf_label in [("1h", "H1"), ("4h", "H4"), ("1d", "D1")]:
                buf = collector.buffers.get(tf_key)
                if buf and buf.buffer:
                    candles = buf.get_candles()
                    for c in candles:
                        # Добавляем POC свечи (уровень максимального объема)
                        poc = getattr(c, 'poc_price', None)
                        if poc:
                            all_levels.append({
                                'price': poc,
                                'tf': tf_label,
                                'has_volume': True,
                                'time': pd.Timestamp(c.timestamp, unit='ms'),
                                'wick_type': 'POC',
                            })
                    
                        # High Volume Nodes (экстремальные объемы)
                        max_vol = getattr(c, 'poc_volume', 1)
                        if max_vol > 0 and c.levels:
                            for price_lvl, vData in c.levels.items():
                                tot = vData.get("buy", 0) + vData.get("sell", 0)
                                if tot >= max_vol * 0.85 and float(price_lvl) != poc:
                                    all_levels.append({
                                        'price': float(price_lvl),
                                        'tf': tf_label,
                                        'has_volume': True,
                                        'time': pd.Timestamp(c.timestamp, unit='ms'),
                                        'wick_type': 'HVN',
                                    })
        except Exception as e:
            print(f"[zone_detector] Could not extract Footprint POCs: {e}")

    if not all_levels:
        print("[zone_detector] No wick or footprint levels found.")
        return []

    levels_df = pd.DataFrame(all_levels)

    # ── Шаг 2: Кластеризация ────────────────────────────────────────
    price_array = levels_df['price'].values
    clusters = cluster_levels(price_array)

    # ── Шаг 2.5: Поиск FVG (Имбалансов) ─────────────────────────────
    all_fvgs = []
    # Основные имбалансы ищем на H4 (наиболее значимые)
    if "H4" in data:
        all_fvgs.extend(detect_fvgs(data["H4"]))

    # ── Шаг 3: Скоринг каждого кластера ──────────────────────────────
    zones = []
    detected_width = adaptive_zone_width(data)
    for cluster in clusters:
        center = cluster['center']
        tolerance = config.CLUSTER_TOLERANCE

        # Какие уровни попали в этот кластер?
        mask = (levels_df['price'] >= center - tolerance) & \
               (levels_df['price'] <= center + tolerance)
        members = levels_df[mask]

        if members.empty:
            continue

        zone = Zone(price=round(center, 2), width=detected_width)
        zone.touch_count = len(members)

        # Сохраняем точки фитилей для визуализации
        for _, m in members.iterrows():
            zone.wick_points.append({
                'time': m['time'],
                'price': m['price'],
                'wick_type': m['wick_type'],
                'tf': m['tf'],
            })

        # Считаем вес по таймфреймам
        tf_set = set(members['tf'].values)
        for tf in tf_set:
            zone.sources.append(tf)
            weight = config.TIMEFRAMES[tf]["weight"]
            # Добавляем вес за каждое уникальное касание из этого TF
            tf_touches = members[members['tf'] == tf]
            # Минимум 2 касания с одного TF для засчитывания
            if len(tf_touches) >= 2:
                zone.score += weight

        # ── БОНУС: Институциональный объем (Footprint POC/HVN) ────────
        w_types = members['wick_type'].values
        if 'POC' in w_types:
            zone.score += 3
            zone.label_suffix = " (Vol POC)"
        elif 'HVN' in w_types:
            zone.score += 2
            zone.label_suffix = " (Vol HVN)"

        # Бонус за крупного игрока
        if members['has_volume'].any():
            zone.has_big_player = True
            zone.score += config.WEIGHT_BIG_PLAYER

        # Бонус за круглый уровень
        remainder = center % config.ROUND_LEVEL_STEP
        if remainder < 2.0 or (config.ROUND_LEVEL_STEP - remainder) < 2.0:
            zone.is_round_level = True
            zone.score += config.WEIGHT_ROUND_LEVEL

        # Бонус за FVG (Имбаланс)
        for fvg in all_fvgs:
            # Зона (z_bot ... z_top) пересекается с FVG (bottom ... top)
            z_top = center + tolerance
            z_bot = center - tolerance
            if max(z_bot, fvg['bottom']) <= min(z_top, fvg['top']):
                zone.score += config.WEIGHT_FVG
                zone.sources.append("FVG")
                break

        zones.append(zone)

    # ── Шаг 4: Фильтрация и сортировка ───────────────────────────────
    strong_zones = [z for z in zones if z.score >= config.MIN_ZONE_SCORE]
    
    # ── Шаг 4.5: Агрегация (слияние) близких зон для уменьшения шума ────
    merged_zones = []
    strong_zones.sort(key=lambda z: z.price)
    
    # Расстояние для "склеивания" зон — агрессивное слияние чтобы оставить только точные уровни
    MERGE_DIST = config.CLUSTER_TOLERANCE * 3.0  
    
    for z in strong_zones:
        if not merged_zones:
            merged_zones.append(z)
        else:
            prev = merged_zones[-1]
            if abs(z.price - prev.price) <= MERGE_DIST:
                # Объединяем зоны: берем средневзвешенную цену
                total_touch = prev.touch_count + z.touch_count
                if total_touch > 0:
                    prev.price = round((prev.price * prev.touch_count + z.price * z.touch_count) / total_touch, 2)
                else:
                    prev.price = round((prev.price + z.price) / 2.0, 2)
                
                # Запрещаем зоне "разбухать"! Оставляем фиксированную толщину.
                prev.width = detected_width
                prev.score = prev.score + z.score // 2  # Складываем баллы
                prev.touch_count += z.touch_count
                prev.sources = list(set(prev.sources + z.sources))
                prev.has_big_player = prev.has_big_player or z.has_big_player
                prev.is_round_level = prev.is_round_level or z.is_round_level
                prev.wick_points.extend(z.wick_points)
            else:
                merged_zones.append(z)
                
    strong_zones = merged_zones

    # ── Шаг 4.6: Привязка к H4 (главный таймфрейм, меньше шума) ─────────
    # Клиент просил, чтобы главным был H4 и не было «шума» от мелких уровней.
    # Оставляем только зоны, подтверждённые H4; H1/D1/FVG остаются как
    # усиление, но сами по себе зону не создают.
    if config.REQUIRE_H4_ANCHOR:
        h4_zones = [z for z in strong_zones if config.PRIMARY_TIMEFRAME in z.sources]
        if h4_zones:
            strong_zones = h4_zones

    strong_zones.sort(key=lambda z: z.score, reverse=True)

    # ── Шаг 4.7: Зоны нужны и над ценой, и под ней ─────────────────────
    weak_pool = [z for z in zones
                 if config.FALLBACK_MIN_ZONE_SCORE <= z.score < config.MIN_ZONE_SCORE]
    if config.REQUIRE_H4_ANCHOR:
        weak_pool = [z for z in weak_pool if config.PRIMARY_TIMEFRAME in z.sources]
    # Клиент просит только сильные зоны: слабые НЕ достраиваем «для заполнения».
    # Если сильных зон нет — список пуст, и на графике ничего не рисуется.
    if config.STRONG_ZONES_ONLY:
        weak_pool = []
    if not limit_output:
        # Для incremental snapshot bridge нужен полный pool кандидатов.
        # Иначе ранний лимит в пять зон мог скрыть новый сильный уровень.
        candidates = strong_zones + weak_pool
        candidates.sort(key=lambda z: z.score, reverse=True)
        selected = candidates
    else:
        selected = balance_around_price(strong_zones, weak_pool, current_price(data))

    print(f"[zone_detector] Found {len(zones)} raw clusters -> "
          f"{len(selected)} strong zones (score >= {config.MIN_ZONE_SCORE})")

    return selected


def current_price(data: dict) -> float | None:
    """Последняя цена закрытия (H1 точнее всего отражает текущий рынок)."""
    for tf in ("H1", config.PRIMARY_TIMEFRAME, "D1"):
        df = data.get(tf)
        if df is not None and not df.empty and "close" in df.columns:
            return float(df["close"].iloc[-1])
    return None


def balance_around_price(strong: list[Zone], weak: list[Zone],
                         price: float | None) -> list[Zone]:
    """Берёт реальные зоны в пределах лимита графика, без квоты 3+3.

    Сначала сильные уровни, затем слабые — чтобы добрать лимит, если сильных
    меньше MAX_ZONES_ON_CHART. Пустую сторону не заполняем выдуманными линиями.
    """
    limit = max(0, int(getattr(config, "MAX_ZONES_ON_CHART", 6) or 0))
    if price is None or price <= 0:
        return strong[:limit]

    merge_dist = config.CLUSTER_TOLERANCE * 3.0

    def add(zone: Zone, into: list[Zone]) -> bool:
        if any(abs(zone.price - z.price) <= merge_dist for z in into):
            return False
        into.append(zone)
        return True

    selected: list[Zone] = []
    for zone in strong:
        if len(selected) >= limit:
            break
        add(zone, selected)
    for zone in weak:
        if len(selected) >= limit:
            break
        add(zone, selected)

    selected.sort(key=lambda z: z.score, reverse=True)
    return selected[:limit]


def projected_levels(price: float, above: bool, count: int) -> list[Zone]:
    """Ближайшие круглые уровни за ценой.

    На историческом максимуме теней над ценой нет физически, и любой отбор
    оставляет верх графика пустым. Круглые уровни ($XX00/$XX50) — то, от чего
    рынок реально реагирует в такой ситуации.
    """
    if not config.PROJECT_ROUND_LEVELS or count <= 0:
        return []

    step = config.ROUND_LEVEL_STEP
    gap = price * config.PROJECTED_LEVEL_MIN_DISTANCE_PCT / 100.0
    levels = []
    edge = price + gap if above else price - gap
    start = math.ceil(edge / step) if above else math.floor(edge / step)
    for i in range(count):
        level = (start + i if above else start - i) * step
        if level <= 0:
            break
        levels.append(Zone(
            price=round(level, 2),
            width=float(config.ZONE_WIDTH),
            score=config.FALLBACK_MIN_ZONE_SCORE,
            sources=[config.PRIMARY_TIMEFRAME],
            is_round_level=True,
            label_suffix=" PROJ",
        ))
    return levels


if __name__ == "__main__":
    # Quick test с синтетическими данными
    from data_fetcher import generate_sample_data
    data = generate_sample_data()
    zones = detect_zones(data)
    for z in zones:
        print(f"  {z}")
