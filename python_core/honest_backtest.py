"""Detector-only walk-forward research, NOT production pipeline parity.

Time contract: every OHLC ``time`` is the BAR OPEN (MT iTime/rates and
Dukascopy convention), normalized to UTC; naive input is assumed UTC. A bar's
OHLC is available only at ``time + duration`` (H1=1h, H4=4h, D1=24h).
Resampling uses left-closed, left-labelled UTC calendar bins. Decisions occur
immediately after an H4 close; formation includes only fully elapsed bars and
future H1 bars open at or after that cutoff. Broker-local timestamps must be
converted before loading; fixed UTC days are not broker session calendars.

This calls detect_zones(limit_output=True) on historical slices, without
persistent zone state, external liquidity/footprint levels or AI. The detector
receives ``allow_external_levels=False`` even when live footprint ingestion is
enabled in config; research never mutates the shared production configuration.

Retest direction is fixed from the decision price, never a future close.
The touched H1 bar's actual close (plus/minus the fixed spread) is the assumed
entry, not a clamped zone price. A confirmed break before entry invalidates
the trade. Only later bars can hit stop/target; ambiguous OHLC is stop-first.
Touch-bar excursion uses its close only: its high/low may precede the touch.

Limitations: OHLC cannot resolve intrabar order or guarantee a close fill;
spread is stylized, with no slippage, gap execution, commissions or portfolio
simulation. Missing/partial source bars are not repaired. Repeated zones and
possibly overlapping horizons are dependent samples; IS/OOS summaries and
unadjusted significance estimates are descriptive, not proof of an edge.
Explicit yfinance loading is optional; CSV research does not fetch live data.

Usage: python honest_backtest.py --csv H1.csv --horizon 12 --out ../output
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
BAR_DURATION = {"H1": pd.Timedelta(hours=1), "H4": pd.Timedelta(hours=4),
                "D1": pd.Timedelta(days=1)}


def research_metadata() -> dict:
    """Include scope/assumptions even in empty or programmatic reports."""
    return {
        "research_scope": "detector_only",
        "production_pipeline_parity": False,
        "persistent_state": False,
        "external_levels": False,
        "external_levels_policy": "detect_zones(allow_external_levels=False)",
        "ai": False,
        "bar_time_convention": "open_time_utc",
        "availability": "bar_open + timeframe_duration",
        "decision_time": "H4 close",
        "future_h1": "bar_open >= decision_time",
        "entry_model": "touched H1 close +/- fixed spread; no price clamping",
        "direction_model": "fixed at decision price (first H1 open if omitted)",
        "ambiguous_later_bar": "stop_first",
        "touch_bar_excursion": "close_only",
        "limitations": [
            "Detector only: no persistent state, external liquidity/footprint or AI.",
            "UTC fixed-duration bins; broker session calendars are not modeled.",
            "Naive timestamps are assumed UTC; missing/partial bars are not repaired.",
            "OHLC order and close fills are assumptions, not tick-level executions.",
            "No slippage, gap execution, commissions or portfolio accounting.",
            "Repeated zones/overlapping horizons are dependent; p-values are descriptive.",
        ],
    }


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(columns={c: c.lower() for c in frame.columns})
    if "tick_volume" not in frame.columns:
        vol_col = "volume" if "volume" in frame.columns else None
        frame["tick_volume"] = frame[vol_col] if vol_col else 0.0
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
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
    """Aggregate open-stamped H1 bars; e.g. 00,01,02,03 -> H4 open 00.

    A bar at 04:00 belongs to the next bin, never the previous H4 candle.
    Partial bins remain partial; availability is still the nominal bin close.
    """
    grouped = (
        _normalize(frame).set_index("time")
        .resample(rule, label="left", closed="left", origin="start_day")
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
    outcome: str              # bounce | breakout | consolidation | no_touch | invalid
    excursion: float          # уход от зоны после касания, в ATR
    segment: str = "IS"       # IS | OOS
    trade: str = "no_touch"   # target | stop | open | invalid | no_touch (ретест со стопом за зоной)


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


def _touch_context(top: float, bottom: float, future: pd.DataFrame,
                   decision_price: float | None) -> tuple[int | None, bool | None]:
    """Freeze approach before observing any future close.

    The optional fallback preserves helper callers without formation data:
    the first future bar's OPEN is observable before that bar's range/close.
    A decision inside/on the zone has no unambiguous approach; do not guess.
    """
    if future.empty:
        return None, None
    reference = float(future.iloc[0].open if decision_price is None else decision_price)
    above = (True if reference > top else False if reference < bottom else None)
    for i, bar in enumerate(future.itertuples(index=False)):
        if bar.low <= top and bar.high >= bottom:
            return i, above
    return None, above


def _confirmed_break(close: float, top: float, bottom: float, atr: float,
                     approach_from_above: bool) -> bool:
    distance = bottom - close if approach_from_above else close - top
    return distance > config.REACTION_BREAKOUT_ATR * atr


def evaluate_level(price: float, top: float, bottom: float, future: pd.DataFrame,
                   atr: float, *, decision_price: float | None = None
                   ) -> tuple[bool, str, float]:
    """Classify a touched band using only a pre-observation approach price.

    Breakout closes take precedence over bounce excursions. On the touched
    bar only its close is definitely after the touch; its full range is not.
    A gap-confirmed break before the first touch invalidates the original setup.
    ``price`` remains the level centre for compatibility, NOT the decision price.
    """
    touch_idx, approach_from_above = _touch_context(top, bottom, future, decision_price)
    if touch_idx is None:
        return False, "no_touch", 0.0
    if approach_from_above is None:
        return True, "invalid", 0.0
    if any(_confirmed_break(c, top, bottom, atr, approach_from_above)
           for c in future.iloc[:touch_idx]["close"]):
        return True, "invalid", 0.0

    best_away = 0.0
    for i, bar in enumerate(future.iloc[touch_idx:].itertuples(index=False)):
        if _confirmed_break(bar.close, top, bottom, atr, approach_from_above):
            distance = bottom - bar.close if approach_from_above else bar.close - top
            return True, "breakout", distance / atr
        if approach_from_above:
            away = (bar.close if i == 0 else bar.high) - top
        else:
            away = bottom - (bar.close if i == 0 else bar.low)
        best_away = max(best_away, away)

    if best_away > config.REACTION_BOUNCE_ATR * atr:
        return True, "bounce", best_away / atr
    return True, "consolidation", best_away / atr


def simulate_retest_trade(top: float, bottom: float, future: pd.DataFrame,
                          atr: float, spread: float, *,
                          decision_price: float | None = None) -> str:
    """Stylized 1R retest, NOT a production execution/P&L simulation.

    Enter at the first touched H1 bar's actual CLOSE +/- spread. Never repair
    an impossible fill by clamping it to a zone edge. Reject a setup whose
    close confirms a break before/at entry, or whose entry is beyond its stop.
    Entry-bar extremes precede entry and cannot stop/target this trade.
    Later bars with both thresholds hit are stop-first (order is unknowable).
    """
    touch_idx, approach_from_above = _touch_context(top, bottom, future, decision_price)
    if touch_idx is None:
        return "no_touch"
    if approach_from_above is None:
        return "invalid"
    if any(_confirmed_break(c, top, bottom, atr, approach_from_above)
           for c in future.iloc[:touch_idx + 1]["close"]):
        return "invalid"

    close = float(future.iloc[touch_idx].close)
    stop_pad = 0.35 * atr
    if approach_from_above:
        entry = close + spread
        stop = bottom - stop_pad - spread
        risk = entry - stop
        if close <= stop or risk <= 0:
            return "invalid"
        target = entry + risk
    else:
        entry = close - spread
        stop = top + stop_pad + spread
        risk = stop - entry
        if close >= stop or risk <= 0:
            return "invalid"
        target = entry - risk

    for bar in future.iloc[touch_idx + 1:].itertuples(index=False):
        hit_stop = bar.low <= stop if approach_from_above else bar.high >= stop
        hit_target = bar.high >= target if approach_from_above else bar.low <= target
        if hit_stop:
            return "stop"
        if hit_target:
            return "target"
    return "open"


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
    step_h4_bars: int = 3           # Horizons may overlap if longer than step * 4h.
    # Bounded detector history, not persistent production engine state.
    h1_window: int = 700
    h4_window: int = 800
    d1_window: int = 300
    round_step: float = 10.0
    spread: float = 0.20            # $ спред XAU/USD у брокера, учитывается в входе и стопе
    source: str = ""
    rows: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for name in ("horizon_h1_bars", "step_h4_bars", "h1_window", "h4_window", "d1_window"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.warmup_h4_bars, int) or self.warmup_h4_bars < 0:
            raise ValueError("warmup_h4_bars must be a nonnegative integer")
        if not math.isfinite(self.round_step) or self.round_step <= 0:
            raise ValueError("round_step must be positive and finite")
        if not math.isfinite(self.spread) or self.spread < 0:
            raise ValueError("spread must be nonnegative and finite")


def run(frames: dict[str, pd.DataFrame], cfg: RunConfig) -> list[LevelOutcome]:
    cfg.validate()  # Also catch config mutations after construction, before any work.
    frames = {tf: _normalize(frames[tf]) for tf in BAR_DURATION}
    h1, h4 = frames["H1"], frames["H4"]
    rng = random.Random(RANDOM_SEED)
    outcomes: list[LevelOutcome] = []

    eval_points = list(range(cfg.warmup_h4_bars, len(h4), cfg.step_h4_bars))
    split_at = eval_points[int(len(eval_points) * 0.6)] if eval_points else 0

    for position, idx in enumerate(eval_points, 1):
        if position % 50 == 0 or position == 1:
            print(f"[backtest] точка {position}/{len(eval_points)} …", flush=True)
        cut = h4.iloc[idx]["time"] + BAR_DURATION["H4"]
        segment = "IS" if idx < split_at else "OOS"

        formation = {
            tf: frame[frame["time"] + BAR_DURATION[tf] <= cut]
                .tail(getattr(cfg, f"{tf.lower()}_window")).reset_index(drop=True)
            for tf, frame in frames.items()
        }
        if len(formation["H4"]) < 50 or formation["H1"].empty:
            continue

        future = h1[h1["time"] >= cut].head(cfg.horizon_h1_bars).reset_index(drop=True)
        if len(future) < cfg.horizon_h1_bars:
            continue

        atr = atr_of(formation["H1"], config.REACTION_ATR_PERIOD)
        price = float(formation["H1"].iloc[-1]["close"])

        try:
            # Детектор и объёмный фильтр печатают диагностику на каждый вызов —
            # в прогоне из сотен точек это гигабайты лога, поэтому глушим.
            with contextlib.redirect_stdout(io.StringIO()):
                flags = get_volume_flags_all_tf(formation)
                zones = detect_zones(formation, flags, limit_output=True,
                                     allow_external_levels=False)
        except Exception as exc:                      # детектор не должен валить прогон
            print(f"[backtest] WARN detect_zones failed at {cut}: {exc}")
            continue

        for zone in zones:
            touched, result, excursion = evaluate_level(
                zone.price, zone.top, zone.bottom, future, atr, decision_price=price)
            trade = simulate_retest_trade(zone.top, zone.bottom, future, atr, cfg.spread, decision_price=price)
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
                level, level + width, level - width, future, atr, decision_price=price)
            trade = simulate_retest_trade(level + width, level - width, future, atr, cfg.spread, decision_price=price)
            outcomes.append(LevelOutcome("random", str(cut), level, 0.0,
                                         touched, result, excursion, segment, trade))

        for level in round_levels(price, count, cfg.round_step, max_dist):
            touched, result, excursion = evaluate_level(
                level, level + width, level - width, future, atr, decision_price=price)
            trade = simulate_retest_trade(level + width, level - width, future, atr, cfg.spread, decision_price=price)
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
        "trades_invalid": int((part["trade"] == "invalid").sum()),
        "winrate_1R": round(wins / total, 4) if total else 0.0,
        "winrate_1R_ci95": [round(lo, 4), round(hi, 4)],
        "expectancy_R": round((wins - (total - wins)) / total, 4) if total else 0.0,
    }

def summarize(outcomes: list[LevelOutcome]) -> dict:
    frame = pd.DataFrame([asdict(o) for o in outcomes])
    report: dict = {"meta": research_metadata(), "groups": {}, "by_segment": {}}
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
            "invalid": int((touched["outcome"] == "invalid").sum()),
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
    cfg = RunConfig(horizon_h1_bars=args.horizon)  # Validate before optional network I/O.

    if args.csv:
        h1 = load_from_csv(args.csv)
        source = f"CSV {args.csv.name}"
    else:
        h1 = load_from_yfinance(args.ticker, args.period, "1h")
        source = f"yfinance {args.ticker} 1h {args.period} (ПРОКСИ, не спот брокера)"

    frames = {"H1": h1, "H4": resample(h1, "4h"), "D1": resample(h1, "1D")}
    cfg.source = source
    cfg.rows = {k: int(len(v)) for k, v in frames.items()}

    print(f"[backtest] Источник: {source}")
    print(f"[backtest] Свечей: {cfg.rows}")
    print(f"[backtest] Период: {h1['time'].min()} … {h1['time'].max()}")

    outcomes = run(frames, cfg)
    report = summarize(outcomes)
    report["meta"].update({
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
    })

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
