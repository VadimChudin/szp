"""Possible stop/liquidity levels derived from a zone and closed OHLC data.

This module does not place orders and is not a trade signal. It produces an
explainable level outside the zone for charting and risk analysis.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

import config
from zone_detector import Zone


def _epoch_seconds(value: object) -> int:
    """Return a portable UTC epoch for MQL chart-object anchoring."""
    if value is None:
        return 0
    try:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        else:
            stamp = stamp.tz_convert("UTC")
        return int(stamp.timestamp())
    except (TypeError, ValueError, OverflowError):
        return 0


@dataclass
class StopCandidate:
    side: str
    price: float
    probability: int
    buffer: float
    atr: float
    rationale: str
    # Historical swing that justified this stop. Rendering uses this time as
    # the x-axis anchor and keeps price as the exact y-axis risk level.
    anchor_epoch: int = 0
    anchor_price: float = 0.0

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
    anchor_epoch = 0
    anchor_price = 0.0
    if frame is None or frame.empty:
        atr = max(zone.width, config.ZONE_WIDTH)
        low, high = zone.bottom - atr, zone.top + atr
        current_price = current_price if current_price is not None else zone.price
    else:
        atr = _atr(frame, config.ATR_PERIOD)
        atr = max(atr, zone.width, config.SYMBOL_POINT * 10)
        recent = frame.tail(lookback)
        current_price = float(current_price if current_price is not None else frame["close"].iloc[-1])
        buffer = max(atr * 0.25, zone.width * 0.35)
        # The same swing that protects the stop becomes the visual x-axis
        # anchor. It prevents clouds from floating at the chart's right edge.
        if current_price > zone.price:
            swing_index = recent["low"].idxmin()
            swing_row = recent.loc[swing_index]
            swing_low = float(swing_row["low"])
            anchor_price = swing_low
            anchor_epoch = _epoch_seconds(swing_row.get("time", swing_index))
            low = max(zone.bottom - buffer, swing_low - atr * 0.15)
            high = zone.top + buffer
        else:
            swing_index = recent["high"].idxmax()
            swing_row = recent.loc[swing_index]
            swing_high = float(swing_row["high"])
            anchor_price = swing_high
            anchor_epoch = _epoch_seconds(swing_row.get("time", swing_index))
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
    return StopCandidate(
        side,
        round(float(price), 2),
        probability,
        round(float(buffer), 2),
        round(float(atr), 2),
        rationale,
        anchor_epoch=anchor_epoch,
        anchor_price=round(float(anchor_price), 2),
    )
