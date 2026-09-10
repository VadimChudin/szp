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
    # Structural evidence is distinct from display/confirmation/lifecycle state.
    score_components: dict = field(default_factory=dict)
    evidence_at: str = ""               # latest contributing candle CLOSE
    lifecycle: dict = field(default_factory=dict)

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
            "score_components": self.score_components,
            "evidence_at": self.evidence_at,
            "lifecycle": self.lifecycle,
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
            score_components=d.get("score_components", {}),
            evidence_at=d.get("evidence_at", ""),
            lifecycle=d.get("lifecycle", {}),
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
    """Partition evidence exactly once, returning original positional indices.

    Every member is within tolerance of the final median. In particular, a
    moving median may not chain a cluster indefinitely across unrelated prices.
    A later price-window query must NEVER reconstruct membership: adjacent
    windows overlap and used to count the same wick in multiple zones.
    """
    tolerance = float(config.CLUSTER_TOLERANCE if tolerance is None else tolerance)
    values = np.asarray(levels, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("Cluster levels must be a finite one-dimensional array")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Cluster tolerance must be finite and nonnegative")
    if not len(values):
        return []
    ordered = np.argsort(values, kind="stable")
    groups, group = [], [int(ordered[0])]
    for idx in ordered[1:]:
        proposed = group + [int(idx)]
        center = float(np.median(values[proposed]))
        if max(center - values[group[0]], values[idx] - center) <= tolerance:
            group = proposed
        else:
            groups.append(group)
            group = [int(idx)]
    groups.append(group)
    return [{"center": float(np.median(values[indices])),
             "count": len(indices), "members": values[indices].tolist(),
             "indices": indices} for indices in groups]


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


def _evidence_zone(members: pd.DataFrame, width: float, fvgs: list[dict]) -> Zone:
    """Score independent source candles, not repeated rows or nearby scores."""
    from market_data import candle_duration

    center = float(members["price"].median())
    zone = Zone(price=round(center, 2), width=width)
    candles = members.drop_duplicates(["tf", "time"])
    zone.touch_count = len(candles)
    zone.sources = sorted(members["tf"].unique())
    for row in members.sort_values(["time", "tf", "wick_type", "price"]).itertuples(index=False):
        zone.wick_points.append({"time": row.time, "price": row.price,
                                 "wick_type": row.wick_type, "tf": row.tf})
    if not candles.empty:
        zone.evidence_at = max(pd.Timestamp(row.time) + candle_duration(row.tf)
                               for row in candles.itertuples(index=False)).isoformat()
    for tf in zone.sources:
        if len(candles[candles["tf"] == tf]) >= 2:
            zone.score_components[tf] = config.TIMEFRAMES[tf]["weight"]
    kinds = set(members["wick_type"])
    if "POC" in kinds:
        zone.score_components["POC"] = 3
        zone.label_suffix = " (Vol POC)"
    elif "HVN" in kinds:
        zone.score_components["HVN"] = 2
        zone.label_suffix = " (Vol HVN)"
    if members["has_volume"].any():
        zone.has_big_player = True
        zone.score_components["volume"] = config.WEIGHT_BIG_PLAYER
    step = float(config.ROUND_LEVEL_STEP)
    if step > 0 and min(center % step, step - center % step) < 2.0:
        zone.is_round_level = True
        zone.score_components["round"] = config.WEIGHT_ROUND_LEVEL
    if any(max(zone.bottom, fvg["bottom"]) <= min(zone.top, fvg["top"]) for fvg in fvgs):
        zone.score_components["FVG"] = config.WEIGHT_FVG
        zone.sources.append("FVG")
    zone.score = sum(zone.score_components.values())
    return zone


def _distinct_zones(zones: list[Zone]) -> list[Zone]:
    """Keep the best real band in an overlap; never invent a midpoint/score."""
    selected = []
    for zone in sorted(zones, key=lambda z: (-z.score, -z.touch_count, z.price)):
        if any(max(zone.bottom, other.bottom) <= min(zone.top, other.top)
               for other in selected):
            continue
        selected.append(zone)
    return selected


def detect_zones(
    data: dict[str, pd.DataFrame],
    volume_flags: dict[str, np.ndarray] | None = None,
    limit_output: bool = True,
    *,
    allow_external_levels: bool = True,
) -> list[Zone]:
    """Detect structural zones from CLOSED OHLC (see market_data contract).

    The live loader enforces closure before ALL indicators/volume flags. Offline
    callers must provide their own causal cutoff. Scores are explainable feature
    weights, NOT probabilities, independent samples, or expected profitability.
    """
    from market_data import candle_duration

    all_levels = []
    normalized = {}
    for tf_label in sorted(data):
        df = data[tf_label].copy()
        if df.empty:
            continue
        if tf_label not in config.TIMEFRAMES:
            raise ValueError(f"Unsupported zone timeframe: {tf_label}")
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(None)
        normalized[tf_label] = df.sort_values("time", kind="stable").reset_index(drop=True)
        flag_by_time = {}
        if volume_flags is not None and tf_label in volume_flags:
            flags = np.asarray(volume_flags[tf_label], dtype=bool)
            if flags.ndim != 1 or len(flags) != len(df):
                raise ValueError(f"{tf_label}: volume flags must align by candle POSITION")
            for stamp, flag in zip(df["time"], flags):
                flag_by_time[stamp] = flag_by_time.get(stamp, False) or bool(flag)
        for row in extract_wick_levels(df).itertuples(index=False):
            all_levels.append({"price": float(row.level), "tf": tf_label,
                               "has_volume": flag_by_time.get(row.time, False),
                               "time": row.time, "wick_type": row.wick_type})

    if allow_external_levels and getattr(config, "FOOTPRINT_LEVELS_IN_ZONES", False) and normalized:
        # This explicitly opt-in live source is never read by the historical evaluator.
        cutoff = max(df["time"].iloc[-1] + candle_duration(tf) for tf, df in normalized.items())
        try:
            from footprint_data import get_collector
            collector = get_collector()
            for key, tf in (("1h", "H1"), ("4h", "H4"), ("1d", "D1")):
                buf = collector.buffers.get(key)
                if not buf or not buf.buffer:
                    continue
                for candle in buf.get_candles():
                    stamp = pd.Timestamp(candle.timestamp, unit="ms")
                    if stamp + candle_duration(tf) > cutoff:
                        continue
                    poc = getattr(candle, "poc_price", None)
                    if poc and math.isfinite(float(poc)):
                        all_levels.append({"price": float(poc), "tf": tf, "has_volume": True,
                                           "time": stamp, "wick_type": "POC"})
                    max_vol = getattr(candle, "poc_volume", 0)
                    if max_vol > 0 and candle.levels:
                        for level, volumes in candle.levels.items():
                            if (volumes.get("buy", 0) + volumes.get("sell", 0) >= max_vol * 0.85
                                    and float(level) != poc and math.isfinite(float(level))):
                                all_levels.append({"price": float(level), "tf": tf, "has_volume": True,
                                                   "time": stamp, "wick_type": "HVN"})
        except Exception as exc:
            print(f"[zone_detector] Footprint evidence unavailable: {exc}")
    if not all_levels:
        return []

    levels = (pd.DataFrame(all_levels)
              .sort_values(["price", "tf", "time", "wick_type"], kind="stable")
              .drop_duplicates(["tf", "time", "wick_type", "price"])
              .reset_index(drop=True))
    width = adaptive_zone_width(normalized)
    if not math.isfinite(width) or width <= 0:
        raise ValueError("Zone width must be finite and positive")
    # Evidence must support the actual drawn band, not an unrelated wider mask.
    clusters = cluster_levels(levels["price"].to_numpy(), min(config.CLUSTER_TOLERANCE, width))
    fvgs = detect_fvgs(normalized["H4"]) if "H4" in normalized else []
    zones = [_evidence_zone(levels.iloc[c["indices"]], width, fvgs) for c in clusters]
    if config.REQUIRE_H4_ANCHOR:
        zones = [z for z in zones if z.score_components.get(config.PRIMARY_TIMEFRAME, 0) > 0]
    strong = _distinct_zones([z for z in zones if z.score >= config.MIN_ZONE_SCORE])
    weak = [] if config.STRONG_ZONES_ONLY else _distinct_zones(
        [z for z in zones if config.FALLBACK_MIN_ZONE_SCORE <= z.score < config.MIN_ZONE_SCORE])
    candidates = _distinct_zones(strong + weak)
    selected = (balance_around_price(strong, weak, current_price(normalized))
                if limit_output else candidates)
    print(f"[zone_detector] {len(clusters)} disjoint evidence clusters -> {len(selected)} zones")
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

    merge_dist = config.CLUSTER_TOLERANCE

    def add(zone: Zone, into: list[Zone]) -> bool:
        if any(abs(zone.price - z.price) <= merge_dist
               or max(zone.bottom, z.bottom) <= min(zone.top, z.top) for z in into):
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
