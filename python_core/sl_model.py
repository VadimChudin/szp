"""Possible stop/liquidity levels derived from a zone and closed OHLC data.

This module does not place orders and is not a trade signal. It produces an
explainable level outside the zone for charting and risk analysis.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

import config
from zone_detector import Zone


@dataclass
class StopCandidate:
    side: str
    price: float
    probability: int
    buffer: float
    atr: float
    rationale: str

    def to_dict(self) -> dict:
        return asdict(self)


def _atr(frame: pd.DataFrame, period: int = 14) -> float:
    if frame is None or frame.empty or not {"high", "low", "close"}.issubset(frame.columns):
        return 0.0
    prev = frame["close"].shift(1)
    tr = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - prev).abs(),
        (frame["low"] - prev).abs(),
    ], axis=1).max(axis=1).dropna()
    return float(tr.tail(period).mean()) if not tr.empty else 0.0


def possible_stop(zone: Zone, frame: pd.DataFrame, current_price: float | None = None,
                  lookback: int = 40) -> StopCandidate:
    """Return the nearest valid structural stop outside the zone."""
    if frame is None or frame.empty:
        atr = max(zone.width, config.ZONE_WIDTH)
        low, high = zone.bottom - atr, zone.top + atr
        current_price = current_price if current_price is not None else zone.price
    else:
        atr = _atr(frame, config.ATR_PERIOD)
        atr = max(atr, zone.width, config.SYMBOL_POINT * 10)
        recent = frame.tail(lookback)
        swing_low = float(recent["low"].min())
        swing_high = float(recent["high"].max())
        current_price = float(current_price if current_price is not None else frame["close"].iloc[-1])
        buffer = max(atr * 0.25, zone.width * 0.35)
        if current_price > zone.price:
            low = max(zone.bottom - buffer, swing_low - atr * 0.15)
            high = zone.top + buffer
        else:
            low = zone.bottom - buffer
            high = min(zone.top + buffer, swing_high + atr * 0.15)
    support = current_price > zone.price
    buffer = max(atr * 0.25, zone.width * 0.35)
    if support:
        price = min(low, zone.bottom - buffer)
        side = "BELOW_SUPPORT"
        rationale = "zone_bottom_plus_ATR_and_swing_buffer"
    else:
        price = max(high, zone.top + buffer)
        side = "ABOVE_RESISTANCE"
        rationale = "zone_top_plus_ATR_and_swing_buffer"
    touches = int(getattr(zone, "touch_count", 0))
    probability = min(92, 35 + min(24, touches * 4) + (16 if zone.score >= 13 else 11 if zone.score >= 11 else 6 if zone.score >= 9 else 0))
    return StopCandidate(side, round(float(price), 2), probability, round(float(buffer), 2), round(float(atr), 2), rationale)
