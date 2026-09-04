"""honest_backtest.py — честный walk-forward тест качества зон Smart Zones Pro.

Что здесь «честного» и почему это важно проверять именно так:

1. НЕТ ЗАГЛЯДЫВАНИЯ В БУДУЩЕЕ. Зоны на момент T строятся ТОЛЬКО из свечей до T
   включительно (детектор получает срез данных, а не весь файл). Исход считается
   ТОЛЬКО по свечам после T.
2. ГОНЯЕТСЯ РАБОЧАЯ ЛОГИКА. Используется тот же zone_detector.detect_zones с
   limit_output=True — то есть ровно те 3+3 зоны, которые клиент видит на графике,
   а не «идеальный» отбор ради красивой цифры.
3. УСЛОВНАЯ МЕТРИКА. Считаем реакцию только по зонам, до которых цена реально
   дошла (touch). Иначе процент можно раздуть далёкими уровнями, которых цена
   никогда не касалась.
4. ЕСТЬ КОНТРОЛЬНАЯ ГРУППА. Те же правила применяются к случайным уровням и к
   круглым числам в том же диапазоне. Без контроля «75% реакций» ничего не
   означает: цена в принципе часто разворачивается.
5. НЕЗАВИСИМЫЕ ВЫБОРКИ. Точки оценки разнесены на горизонт, окна не
   перекрываются, поэтому доверительный интервал не занижен.
6. IN-SAMPLE / OUT-OF-SAMPLE. Пороги реакции берутся из config (их никто не
   подгонял под OOS-часть), результат отдельно показан на первых 60% и
   последних 40% истории.
7. ЧЕСТНАЯ ОГОВОРКА ПРО ДАННЫЕ. Инструмент источника указывается в отчёте.
   Спот XAU/USD у брокера и фьючерс золота — не одно и то же.

Запуск:
    python honest_backtest.py                       # источник по умолчанию (yfinance GC=F)
    python honest_backtest.py --csv path/to.csv     # свои свечи (time,open,high,low,close,tick_volume)
    python honest_backtest.py --horizon 12 --out ../output
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import random
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
from volume_filter import get_volume_flags_all_tf
from zone_detector import detect_zones

RANDOM_SEED = 20260902

# ── Загрузка данных ───────────────────────────────────────────────────────────
OHLC = ["open", "high", "low", "close"]


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(columns={c: c.lower() for c in frame.columns})
    if "tick_volume" not in frame.columns:
        vol_col = "volume" if "volume" in frame.columns else None
        frame["tick_volume"] = frame[vol_col] if vol_col else 0.0
    frame["time"] = pd.to_datetime(frame["time"], utc=True).dt.tz_localize(None)
    frame = frame[["time", *OHLC, "tick_volume"]].dropna()
    return frame.sort_values("time").reset_index(drop=True)


def load_from_yfinance(ticker: str, period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    if raw.empty:
        raise RuntimeError(f"yfinance вернул пустой набор для {ticker}")
    raw = raw.reset_index()
    raw = raw.rename(columns={raw.columns[0]: "time", "Volume": "tick_volume"})
    return _normalize(raw)


def load_from_csv(path: Path) -> pd.DataFrame:
    return _normalize(pd.read_csv(path))


def resample(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    grouped = (
        frame.set_index("time")
        .resample(rule, label="right", closed="right")
        .agg({"open": "first", "high": "max", "low": "min",
              "close": "last", "tick_volume": "sum"})
        .dropna()
        .reset_index()
    )
    return grouped


# ── Оценка исхода одного уровня ───────────────────────────────────────────────
@dataclass
class LevelOutcome:
    group: str                # zones | random | round
    formed_at: str
    price: float
    score: float
    touched: bool
    outcome: str              # bounce | breakout | consolidation | no_touch
    excursion: float          # уход от зоны после касания, в ATR
    segment: str = "IS"       # IS | OOS
    trade: str = "no_touch"   # target | stop | open | no_touch (ретест со стопом за зоной)


def atr_of(frame: pd.DataFrame, period: int) -> float:
    if len(frame) < period + 1:
        return float((frame["high"] - frame["low"]).mean() or 1.0)
    tr = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - frame["close"].shift(1)).abs(),
        (frame["low"] - frame["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    value = float(tr.tail(period).mean())
    return value if value > 0 else 1.0


def evaluate_level(price: float, top: float, bottom: float, future: pd.DataFrame,
                   atr: float) -> tuple[bool, str, float]:
    """Классифицирует исход по будущим свечам. Порогов «на глаз» нет — они из config.

    bounce        — цена коснулась и ушла прочь более чем на REACTION_BOUNCE_ATR·ATR,
                    не закрывшись телом за уровень.
    breakout      — закрытие за уровнем дальше REACTION_BREAKOUT_ATR·ATR (это и есть
                    «закреп за зоной», по которому клиент принимает решение).
    consolidation — коснулась, но ни ухода, ни закрепа: разброс закрытий сжат.
    """
    bounce_need = config.REACTION_BOUNCE_ATR * atr
    break_need = config.REACTION_BREAKOUT_ATR * atr

    touch_idx = None
    for i, bar in enumerate(future.itertuples(index=False)):
        if bar.low <= top and bar.high >= bottom:
            touch_idx = i
            break
    if touch_idx is None:
        return False, "no_touch", 0.0

    after = future.iloc[touch_idx:]
    approach_from_above = bool(future.iloc[0].close > top)

    best_away = 0.0
    for bar in after.itertuples(index=False):
        # Закреп (пробой по закрытию) проверяем первым: он «сильнее» отскока.
        if bar.close > top and (bar.close - top) > break_need and not approach_from_above:
            return True, "breakout", (bar.close - top) / atr
        if bar.close < bottom and (bottom - bar.close) > break_need and approach_from_above:
            return True, "breakout", (bottom - bar.close) / atr
        if approach_from_above:
            best_away = max(best_away, bar.high - top)
        else:
            best_away = max(best_away, bottom - bar.low)

    if best_away > bounce_need:
        return True, "bounce", best_away / atr
    return True, "consolidation", best_away / atr



# ── Решающий тест: ретест зоны, стоп за зоной, цель 1R ────────────────────────
def simulate_retest_trade(top: float, bottom: float, future: pd.DataFrame,
                          atr: float, spread: float) -> str:
    """Единственная метрика, которая отличает рабочий уровень от случайной линии.

    Правило нарочно тупое и одинаковое для всех групп, без подгонки:
      • вход — когда цена коснулась уровня (ретест), в сторону от уровня;
      • стоп — за уровнем на STOP_ATR·ATR (плюс спред);
      • цель — 1R от входа;
      • если ни стоп, ни цель не сработали до конца горизонта — исход "open".

    Направление берётся из того, с какой стороны цена подошла: подошла сверху →
    уровень как поддержка → лонг; подошла снизу → как сопротивление → шорт.
    Никакого выбора направления «по факту» нет, это и делает тест честным.
    """
    stop_pad = 0.35 * atr

    touch_idx = None
    for i, bar in enumerate(future.itertuples(index=False)):
        if bar.low <= top and bar.high >= bottom:
            touch_idx = i
            break
    if touch_idx is None:
        return "no_touch"

    approach_from_above = bool(future.iloc[0].close > top)
    entry_bar = future.iloc[touch_idx]

    if approach_from_above:                      # поддержка → лонг
        entry = max(float(entry_bar.close), bottom) + spread
        stop = bottom - stop_pad - spread
        risk = entry - stop
        if risk <= 0:
            return "invalid"
        target = entry + risk
        for bar in future.iloc[touch_idx + 1:].itertuples(index=False):
            hit_stop = bar.low <= stop
            hit_target = bar.high >= target
            if hit_stop and hit_target:
                return "stop"                    # неоднозначный бар считаем против себя
            if hit_stop:
                return "stop"
            if hit_target:
                return "target"
        return "open"

    entry = min(float(entry_bar.close), top) - spread          # сопротивление → шорт
    stop = top + stop_pad + spread
    risk = stop - entry
    if risk <= 0:
        return "invalid"
    target = entry - risk
    for bar in future.iloc[touch_idx + 1:].itertuples(index=False):
        hit_stop = bar.high >= stop
        hit_target = bar.low <= target
        if hit_stop and hit_target:
            return "stop"
        if hit_stop:
            return "stop"
        if hit_target:
            return "target"
    return "open"

# ── Контрольные группы ────────────────────────────────────────────────────────
def random_levels(price: float, count: int, max_distance: float,
                  rng: random.Random) -> list[float]:
    """Случайные уровни в том же коридоре, что и зоны: честное сравнение."""
    levels = []
    for _ in range(count):
        offset = rng.uniform(-max_distance, max_distance)
        if abs(offset) < max_distance * 0.05:
            offset = math.copysign(max_distance * 0.05, offset or 1.0)
        levels.append(round(price + offset, 2))
    return levels


def round_levels(price: float, count: int, step: float, max_distance: float) -> list[float]:
    """Круглые числа — популярная «бесплатная» альтернатива зонам."""
    levels = []
    base = math.floor(price / step) * step
    k = 1
    while len(levels) < count and k * step <= max_distance:
        levels.append(round(base + k * step, 2))
        if len(levels) < count:
            levels.append(round(base - k * step, 2))
        k += 1
    return levels[:count]


# ── Статистика ────────────────────────────────────────────────────────────────
def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - spread), min(1.0, centre + spread)


def two_proportion_p(s1: int, n1: int, s2: int, n2: int) -> float:
    """Двусторонний z-тест разности пропорций. Без него любые проценты — анекдот."""
    if n1 == 0 or n2 == 0:
        return 1.0
    p1, p2 = s1 / n1, s2 / n2
    pooled = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (p1 - p2) / se
    return math.erfc(abs(z) / math.sqrt(2))


# ── Основной прогон ───────────────────────────────────────────────────────────
@dataclass
class RunConfig:
    horizon_h1_bars: int = 12       # сколько H1-свечей смотрим после формирования
    warmup_h4_bars: int = 180       # минимум истории для детектора
    step_h4_bars: int = 3           # шаг оценки: окна не перекрываются (3*4ч = 12ч)
    # Ограничение окна формирования. В продакшене детектор тоже работает не по
    # всей истории, а по последним N свечам, поэтому это не «подгонка», а
    # воспроизведение реальных условий (и прогон укладывается в разумное время).
    h1_window: int = 700
    h4_window: int = 800
    d1_window: int = 300
    round_step: float = 10.0
    spread: float = 0.20            # $ спред XAU/USD у брокера, учитывается в входе и стопе
    source: str = ""
    rows: dict = field(default_factory=dict)


def run(frames: dict[str, pd.DataFrame], cfg: RunConfig) -> list[LevelOutcome]:
    h1, h4 = frames["H1"], frames["H4"]
    rng = random.Random(RANDOM_SEED)
    outcomes: list[LevelOutcome] = []

    eval_points = list(range(cfg.warmup_h4_bars, len(h4) - 1, cfg.step_h4_bars))
    split_at = eval_points[int(len(eval_points) * 0.6)] if eval_points else 0

    for position, idx in enumerate(eval_points, 1):
        if position % 50 == 0 or position == 1:
            print(f"[backtest] точка {position}/{len(eval_points)} …", flush=True)
        cut = h4.iloc[idx]["time"]
        segment = "IS" if idx < split_at else "OOS"

        formation = {
            "H1": h1[h1["time"] <= cut].tail(cfg.h1_window).reset_index(drop=True),
            "H4": h4[h4["time"] <= cut].tail(cfg.h4_window).reset_index(drop=True),
            "D1": frames["D1"][frames["D1"]["time"] <= cut].tail(cfg.d1_window).reset_index(drop=True),
        }
        if len(formation["H4"]) < 50 or formation["H1"].empty:
            continue

        future = h1[h1["time"] > cut].head(cfg.horizon_h1_bars).reset_index(drop=True)
        if len(future) < cfg.horizon_h1_bars:
            continue

        atr = atr_of(formation["H1"], config.REACTION_ATR_PERIOD)
        price = float(formation["H1"].iloc[-1]["close"])

        try:
            # Детектор и объёмный фильтр печатают диагностику на каждый вызов —
            # в прогоне из сотен точек это гигабайты лога, поэтому глушим.
            with contextlib.redirect_stdout(io.StringIO()):
                flags = get_volume_flags_all_tf(formation)
                zones = detect_zones(formation, flags, limit_output=True)
        except Exception as exc:                      # детектор не должен валить прогон
            print(f"[backtest] WARN detect_zones failed at {cut}: {exc}")
            continue

        for zone in zones:
            touched, result, excursion = evaluate_level(
                zone.price, zone.top, zone.bottom, future, atr)
            trade = simulate_retest_trade(zone.top, zone.bottom, future, atr, cfg.spread)
            outcomes.append(LevelOutcome("zones", str(cut), zone.price, zone.score,
                                         touched, result, excursion, segment, trade))

        # Контроль строится с тем же количеством уровней и той же шириной.
        width = zones[0].width if zones else config.ZONE_WIDTH
        # Коридор зон может быть отключён (0 = без ограничения), но случайным
        # и круглым уровням нужен конечный диапазон, иначе сравнивать не с чем.
        max_dist = config.MAX_ZONE_DISTANCE if config.MAX_ZONE_DISTANCE > 0 else 90.0
        count = max(len(zones), 1)

        for level in random_levels(price, count, max_dist, rng):
            touched, result, excursion = evaluate_level(
                level, level + width, level - width, future, atr)
            trade = simulate_retest_trade(level + width, level - width, future, atr, cfg.spread)
            outcomes.append(LevelOutcome("random", str(cut), level, 0.0,
                                         touched, result, excursion, segment, trade))

        for level in round_levels(price, count, cfg.round_step, max_dist):
            touched, result, excursion = evaluate_level(
                level, level + width, level - width, future, atr)
            trade = simulate_retest_trade(level + width, level - width, future, atr, cfg.spread)
            outcomes.append(LevelOutcome("round", str(cut), level, 0.0,
                                         touched, result, excursion, segment, trade))

    return outcomes



def _trade_block(part: pd.DataFrame) -> dict:
    """Итог по правилу «ретест + стоп за зоной + 1R». Незакрытые сделки не
    считаем ни победой, ни поражением — иначе цифра врёт."""
    if "trade" not in part.columns:
        return {}
    closed = part[part["trade"].isin(["target", "stop"])]
    wins = int((closed["trade"] == "target").sum())
    total = int(len(closed))
    lo, hi = wilson_interval(wins, total)
    return {
        "trades_closed": total,
        "trades_open": int((part["trade"] == "open").sum()),
        "winrate_1R": round(wins / total, 4) if total else 0.0,
        "winrate_1R_ci95": [round(lo, 4), round(hi, 4)],
        "expectancy_R": round((wins - (total - wins)) / total, 4) if total else 0.0,
    }

def summarize(outcomes: list[LevelOutcome]) -> dict:
    frame = pd.DataFrame([asdict(o) for o in outcomes])
    report: dict = {"groups": {}, "by_segment": {}}
    if frame.empty:
        return report

    def block(part: pd.DataFrame) -> dict:
        touched = part[part["touched"]]
        reacted = touched[touched["outcome"].isin(["bounce", "breakout"])]
        lo, hi = wilson_interval(len(reacted), len(touched))
        return {
            "levels": int(len(part)),
            "touched": int(len(touched)),
            "touch_rate": round(len(touched) / len(part), 4) if len(part) else 0.0,
            "reacted": int(len(reacted)),
            "reaction_rate_given_touch": round(len(reacted) / len(touched), 4) if len(touched) else 0.0,
            "ci95": [round(lo, 4), round(hi, 4)],
            "bounce": int((touched["outcome"] == "bounce").sum()),
            "breakout": int((touched["outcome"] == "breakout").sum()),
            "consolidation": int((touched["outcome"] == "consolidation").sum()),
            "median_excursion_atr": round(float(touched["excursion"].median()), 3) if len(touched) else 0.0,
            **_trade_block(part),
        }

    for group in ("zones", "random", "round"):
        part = frame[frame["group"] == group]
        if not part.empty:
            report["groups"][group] = block(part)

    for segment in ("IS", "OOS"):
        seg = frame[frame["segment"] == segment]
        report["by_segment"][segment] = {
            g: block(seg[seg["group"] == g])
            for g in ("zones", "random", "round") if not seg[seg["group"] == g].empty
        }

    zt = frame[(frame["group"] == "zones") & frame["touched"]]
    rt = frame[(frame["group"] == "random") & frame["touched"]]
    ot = frame[(frame["group"] == "round") & frame["touched"]]

    def hits(part: pd.DataFrame) -> int:
        return int(part["outcome"].isin(["bounce", "breakout"]).sum())

    def closed(group: str) -> tuple[int, int]:
        part = frame[(frame["group"] == group) & frame["trade"].isin(["target", "stop"])]
        return int((part["trade"] == "target").sum()), len(part)

    zw, zn = closed("zones")
    rw, rn = closed("random")
    ow, on = closed("round")

    report["significance"] = {
        "zones_vs_random_p": round(two_proportion_p(hits(zt), len(zt), hits(rt), len(rt)), 6),
        "zones_vs_round_p": round(two_proportion_p(hits(zt), len(zt), hits(ot), len(ot)), 6),
        "trade_1R_zones_vs_random_p": round(two_proportion_p(zw, zn, rw, rn), 6),
        "trade_1R_zones_vs_round_p": round(two_proportion_p(zw, zn, ow, on), 6),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Честный walk-forward тест зон")
    parser.add_argument("--csv", type=Path, default=None,
                        help="свои свечи H1 (time,open,high,low,close,tick_volume)")
    parser.add_argument("--ticker", default="GC=F", help="тикер yfinance (по умолчанию фьючерс золота)")
    parser.add_argument("--period", default="2y")
    parser.add_argument("--horizon", type=int, default=12, help="H1-свечей после формирования")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "output")
    args = parser.parse_args()

    if args.csv:
        h1 = load_from_csv(args.csv)
        source = f"CSV {args.csv.name}"
    else:
        h1 = load_from_yfinance(args.ticker, args.period, "1h")
        source = f"yfinance {args.ticker} 1h {args.period} (ПРОКСИ, не спот брокера)"

    frames = {"H1": h1, "H4": resample(h1, "4h"), "D1": resample(h1, "1D")}
    cfg = RunConfig(horizon_h1_bars=args.horizon, source=source)
    cfg.rows = {k: int(len(v)) for k, v in frames.items()}

    print(f"[backtest] Источник: {source}")
    print(f"[backtest] Свечей: {cfg.rows}")
    print(f"[backtest] Период: {h1['time'].min()} … {h1['time'].max()}")

    outcomes = run(frames, cfg)
    report = summarize(outcomes)
    report["meta"] = {
        "source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": cfg.rows,
        "period": [str(h1["time"].min()), str(h1["time"].max())],
        "horizon_h1_bars": cfg.horizon_h1_bars,
        "step_h4_bars": cfg.step_h4_bars,
        "min_zone_score": config.MIN_ZONE_SCORE,
        "strong_zones_only": config.STRONG_ZONES_ONLY,
        "max_zone_distance_pips": config.MAX_ZONE_DISTANCE_PIPS,
        "reaction_bounce_atr": config.REACTION_BOUNCE_ATR,
        "reaction_breakout_atr": config.REACTION_BREAKOUT_ATR,
        "spread_usd": cfg.spread,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "honest_backtest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame([asdict(o) for o in outcomes]).to_csv(
        args.out / "honest_backtest_levels.csv", index=False)

    print(json.dumps(report["groups"], indent=2, ensure_ascii=False))
    print(json.dumps(report.get("significance", {}), indent=2))
    print(f"[backtest] Отчёт: {args.out / 'honest_backtest.json'}")


if __name__ == "__main__":
    main()
