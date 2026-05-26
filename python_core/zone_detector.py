"""
zone_detector.py — Ядро алгоритма.

Отвечает за:
  1. Извлечение уровней теней (верхний/нижний фитиль каждой свечи)
  2. Кластеризацию близких уровней в "зоны"
  3. Подсчёт количества касаний каждой зоны из разных таймфреймов
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
import config
from fvg_detector import detect_fvgs


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


def detect_zones(
    data: dict[str, pd.DataFrame],
    volume_flags: dict[str, np.ndarray] | None = None,
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
    for cluster in clusters:
        center = cluster['center']
        tolerance = config.CLUSTER_TOLERANCE

        # Какие уровни попали в этот кластер?
        mask = (levels_df['price'] >= center - tolerance) & \
               (levels_df['price'] <= center + tolerance)
        members = levels_df[mask]

        if members.empty:
            continue

        zone = Zone(price=round(center, 2))
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
                prev.width = config.ZONE_WIDTH
                prev.score = prev.score + z.score // 2  # Складываем баллы
                prev.touch_count += z.touch_count
                prev.sources = list(set(prev.sources + z.sources))
                prev.has_big_player = prev.has_big_player or z.has_big_player
                prev.is_round_level = prev.is_round_level or z.is_round_level
                prev.wick_points.extend(z.wick_points)
            else:
                merged_zones.append(z)
                
    strong_zones = merged_zones
    strong_zones.sort(key=lambda z: z.score, reverse=True)

    # Ограничиваем количество зон
    strong_zones = strong_zones[:config.MAX_ZONES_ON_CHART]

    print(f"[zone_detector] Found {len(zones)} raw clusters -> "
          f"{len(strong_zones)} strong zones (score >= {config.MIN_ZONE_SCORE})")

    return strong_zones


if __name__ == "__main__":
    # Quick test с синтетическими данными
    from data_fetcher import generate_sample_data
    data = generate_sample_data()
    zones = detect_zones(data)
    for z in zones:
        print(f"  {z}")
