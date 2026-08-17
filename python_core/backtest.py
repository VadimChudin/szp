"""Walk-forward evaluation for zone quality.

The evaluator intentionally separates formation data from outcome data. A zone
at bar i is created from data[:i+1] and is evaluated only on bars i+1...i+h.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

import pandas as pd

from zone_detector import Zone


@dataclass
class ZoneOutcome:
    formed_at: str
    price: float
    score: float
    outcome: str
    max_favorable: float
    max_adverse: float
    horizon: int


def _ts(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def evaluate_zone(zone: Zone, future: pd.DataFrame, horizon: int = 6,
                   reaction_atr: float = 1.0, invalidation_atr: float = 1.0) -> ZoneOutcome:
    """Evaluate a zone on future bars only; no candle after horizon is read."""
    future = future.head(horizon)
    favorable = 0.0
    adverse = 0.0
    outcome = "untested"
    for _, bar in future.iterrows():
        high, low = float(bar["high"]), float(bar["low"])
        touched = low <= zone.top and high >= zone.bottom
        if not touched:
            continue
        close = float(bar["close"])
        if close > zone.top:
            favorable = max(favorable, close - zone.top)
        elif close < zone.bottom:
            favorable = max(favorable, zone.bottom - close)
        else:
            outcome = "tested"
        # A full body close beyond the zone is a deterministic invalidation.
        op = float(bar["open"])
        if (op < zone.bottom and close > zone.top) or (op > zone.top and close < zone.bottom):
            outcome = "invalidated"
            break
        outcome = "reacted" if favorable > 0 else outcome
    return ZoneOutcome(
        formed_at=_ts(future.iloc[0]["time"]) if not future.empty and "time" in future else "",
        price=zone.price,
        score=zone.score,
        outcome=outcome,
        max_favorable=favorable,
        max_adverse=adverse,
        horizon=len(future),
    )


def walk_forward(frame: pd.DataFrame, detector: Callable[[dict], list[Zone]],
                 warmup: int = 100, horizon: int = 6, step: int = 1) -> list[ZoneOutcome]:
    """Run detector on a strict expanding window and score future candles."""
    if frame.empty or len(frame) <= warmup + 1:
        return []
    frame = frame.sort_values("time").reset_index(drop=True) if "time" in frame else frame.reset_index(drop=True)
    results: list[ZoneOutcome] = []
    for index in range(warmup, len(frame) - 1, step):
        formation = frame.iloc[: index + 1].copy()
        future = frame.iloc[index + 1 : index + 1 + horizon].copy()
        zones = detector({"H4": formation})
        for zone in zones:
            result = evaluate_zone(zone, future, horizon=horizon)
            result.formed_at = _ts(formation.iloc[-1].get("time", index))
            results.append(result)
    return results


def summarize(outcomes: list[ZoneOutcome]) -> dict:
    total = len(outcomes)
    reacted = sum(o.outcome == "reacted" for o in outcomes)
    invalidated = sum(o.outcome == "invalidated" for o in outcomes)
    tested = sum(o.outcome == "tested" for o in outcomes)
    return {
        "samples": total,
        "reacted": reacted,
        "tested": tested,
        "invalidated": invalidated,
        "reaction_rate": reacted / total if total else 0.0,
        "invalidation_rate": invalidated / total if total else 0.0,
        "outcomes": [asdict(o) for o in outcomes],
    }
