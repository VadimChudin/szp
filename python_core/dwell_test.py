"""dwell_test.py — тормозит ли зона цену?

Предыдущий тест показал, что «у уровня что-то произошло» — метрика пустая:
цена постоянно дёргается, поэтому случайные линии дают такой же процент.

Здесь метрика другая и по делу: зона должна ЗАДЕРЖИВАТЬ цену.
Мерим по M15-свечам, после первого касания уровня:

  • dwell_minutes — сколько минут цена провела в полосе уровня
                    (сколько M15-свечей своим диапазоном пересекли полосу);
  • stalled_15/30/60/120 — была ли проторговка не меньше N минут;
  • returned — цена ушла от полосы больше чем на 1·ATR и ВЕРНУЛАСЬ в неё;
  • speed_ratio — во сколько раз медленнее цена идёт внутри полосы, чем вне
                  неё (в ATR за 15 минут). > 1 означает торможение.

Контроль тот же: случайные уровни и круглые числа, полоса той же ширины,
правила идентичные. Зоны строятся только по прошлым свечам.

M15 у yfinance доступен за 60 дней, поэтому окно замеров — последние ~60 дней,
а история для детектора берётся из двухлетнего H1.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
from honest_backtest import (RANDOM_SEED, atr_of, load_from_yfinance, random_levels,
                             resample, round_levels, two_proportion_p, wilson_interval)
from volume_filter import get_volume_flags_all_tf
from zone_detector import detect_zones

M15_PER_HOUR = 4


@dataclass
class DwellRow:
    group: str
    formed_at: str
    price: float
    score: float
    touched: bool
    dwell_minutes: int
    returned: bool
    speed_in: float
    speed_out: float
    segment: str


def measure_dwell(top: float, bottom: float, future: pd.DataFrame, atr: float,
                  pad_atr: float = 0.10) -> tuple[bool, int, bool, float, float]:
    """Считает время проторговки в полосе уровня и скорость внутри/вне полосы."""
    lo = bottom - pad_atr * atr
    hi = top + pad_atr * atr

    touch_idx = None
    for i, bar in enumerate(future.itertuples(index=False)):
        if bar.low <= hi and bar.high >= lo:
            touch_idx = i
            break
    if touch_idx is None:
        return False, 0, False, 0.0, 0.0

    after = future.iloc[touch_idx:]
    inside_bars = 0
    inside_travel = 0.0
    outside_bars = 0
    outside_travel = 0.0
    left_far = False
    returned = False

    for bar in after.itertuples(index=False):
        intersects = bar.low <= hi and bar.high >= lo
        travel = float(bar.high - bar.low)
        if intersects:
            inside_bars += 1
            inside_travel += travel
            if left_far:
                returned = True
        else:
            outside_bars += 1
            outside_travel += travel
            distance = bar.low - hi if bar.low > hi else lo - bar.high
            if distance >= atr:
                left_far = True

    speed_in = (inside_travel / inside_bars / atr) if inside_bars else 0.0
    speed_out = (outside_travel / outside_bars / atr) if outside_bars else 0.0
    return True, inside_bars * 15, returned, speed_in, speed_out


def run(h1: pd.DataFrame, h4: pd.DataFrame, d1: pd.DataFrame, m15: pd.DataFrame,
        horizon_hours: int, step_h4: int) -> list[DwellRow]:
    rng = random.Random(RANDOM_SEED)
    rows: list[DwellRow] = []

    m15_start, m15_end = m15["time"].min(), m15["time"].max()
    usable = h4[(h4["time"] > m15_start) & (h4["time"] < m15_end)].reset_index(drop=True)
    points = list(range(0, len(usable) - 1, step_h4))
    split_at = points[int(len(points) * 0.6)] if points else 0
    horizon_bars = horizon_hours * M15_PER_HOUR

    print(f"[dwell] окно замеров: {m15_start} … {m15_end}, точек: {len(points)}", flush=True)

    for position, idx in enumerate(points, 1):
        if position % 20 == 0 or position == 1:
            print(f"[dwell] точка {position}/{len(points)} …", flush=True)
        cut = usable.iloc[idx]["time"]
        segment = "IS" if idx < split_at else "OOS"

        formation = {
            "H1": h1[h1["time"] <= cut].tail(700).reset_index(drop=True),
            "H4": h4[h4["time"] <= cut].tail(800).reset_index(drop=True),
            "D1": d1[d1["time"] <= cut].tail(300).reset_index(drop=True),
        }
        if len(formation["H4"]) < 50 or formation["H1"].empty:
            continue

        future = m15[m15["time"] > cut].head(horizon_bars).reset_index(drop=True)
        if len(future) < horizon_bars:
            continue

        atr = atr_of(formation["H1"], config.REACTION_ATR_PERIOD)
        price = float(formation["H1"].iloc[-1]["close"])

        try:
            with contextlib.redirect_stdout(io.StringIO()):
                flags = get_volume_flags_all_tf(formation)
                zones = detect_zones(formation, flags, limit_output=True)
        except Exception as exc:
            print(f"[dwell] WARN detect_zones failed at {cut}: {exc}")
            continue

        for zone in zones:
            touched, dwell, returned, s_in, s_out = measure_dwell(
                zone.top, zone.bottom, future, atr)
            rows.append(DwellRow("zones", str(cut), zone.price, zone.score,
                                 touched, dwell, returned, s_in, s_out, segment))

        width = zones[0].width if zones else config.ZONE_WIDTH
        count = max(len(zones), 1)
        max_dist = config.MAX_ZONE_DISTANCE

        for level in random_levels(price, count, max_dist, rng):
            touched, dwell, returned, s_in, s_out = measure_dwell(
                level + width, level - width, future, atr)
            rows.append(DwellRow("random", str(cut), level, 0.0,
                                 touched, dwell, returned, s_in, s_out, segment))

        for level in round_levels(price, count, 10.0, max_dist):
            touched, dwell, returned, s_in, s_out = measure_dwell(
                level + width, level - width, future, atr)
            rows.append(DwellRow("round", str(cut), level, 0.0,
                                 touched, dwell, returned, s_in, s_out, segment))

    return rows


def summarize(rows: list[DwellRow]) -> dict:
    frame = pd.DataFrame([asdict(r) for r in rows])
    report: dict = {"groups": {}, "thresholds": {}, "significance": {}}
    if frame.empty:
        return report

    touched = frame[frame["touched"]]
    for group in ("zones", "random", "round"):
        part = touched[touched["group"] == group]
        whole = frame[frame["group"] == group]
        if part.empty:
            continue
        moving = part[part["speed_out"] > 0]
        report["groups"][group] = {
            "levels": int(len(whole)),
            "touched": int(len(part)),
            "touch_rate": round(len(part) / len(whole), 4),
            "median_dwell_minutes": int(part["dwell_minutes"].median()),
            "mean_dwell_minutes": round(float(part["dwell_minutes"].mean()), 1),
            "returned_rate": round(float(part["returned"].mean()), 4),
            "slowdown_ratio": round(float((moving["speed_out"] / moving["speed_in"]).median()), 3)
            if len(moving) else 0.0,
        }

    for minutes in (15, 30, 60, 120, 240):
        block = {}
        for group in ("zones", "random", "round"):
            part = touched[touched["group"] == group]
            if part.empty:
                continue
            hits = int((part["dwell_minutes"] >= minutes).sum())
            lo, hi = wilson_interval(hits, len(part))
            block[group] = {
                "rate": round(hits / len(part), 4),
                "hits": hits,
                "n": int(len(part)),
                "ci95": [round(lo, 4), round(hi, 4)],
            }
        if "zones" in block and "random" in block:
            block["p_zones_vs_random"] = round(two_proportion_p(
                block["zones"]["hits"], block["zones"]["n"],
                block["random"]["hits"], block["random"]["n"]), 6)
        if "zones" in block and "round" in block:
            block["p_zones_vs_round"] = round(two_proportion_p(
                block["zones"]["hits"], block["zones"]["n"],
                block["round"]["hits"], block["round"]["n"]), 6)
        report["thresholds"][f">={minutes}min"] = block

    zr = touched[touched["group"] == "zones"]
    rr = touched[touched["group"] == "random"]
    if not zr.empty and not rr.empty:
        report["significance"]["returned_p"] = round(two_proportion_p(
            int(zr["returned"].sum()), len(zr), int(rr["returned"].sum()), len(rr)), 6)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Тормозит ли зона цену (проторговка/возврат)")
    parser.add_argument("--ticker", default="GC=F")
    parser.add_argument("--horizon", type=int, default=48, help="часов после формирования")
    parser.add_argument("--step", type=int, default=3, help="шаг оценки в H4-барах")
    parser.add_argument("--out", type=Path, default=Path("/home/user/dwell"))
    args = parser.parse_args()

    h1 = load_from_yfinance(args.ticker, "2y", "1h")
    m15 = load_from_yfinance(args.ticker, "60d", "15m")
    h4, d1 = resample(h1, "4h"), resample(h1, "1D")

    print(f"[dwell] H1 {len(h1)}, H4 {len(h4)}, D1 {len(d1)}, M15 {len(m15)}")

    rows = run(h1, h4, d1, m15, args.horizon, args.step)
    report = summarize(rows)
    report["meta"] = {
        "source": f"yfinance {args.ticker} (H1 2y для зон, M15 60d для замеров; ПРОКСИ, не спот брокера)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_hours": args.horizon,
        "m15_bars": int(len(m15)),
        "min_zone_score": config.MIN_ZONE_SCORE,
        "nearest_zone_pips": [config.ZONE_NEAREST_MIN_PIPS, config.ZONE_NEAREST_MAX_PIPS],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "dwell_test.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame([asdict(r) for r in rows]).to_csv(args.out / "dwell_levels.csv", index=False)

    print(json.dumps(report["groups"], indent=2, ensure_ascii=False))
    print(json.dumps(report["thresholds"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
