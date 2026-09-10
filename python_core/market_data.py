"""Input contract for the structural zone engine.

``time`` is the candle OPEN time, never its close. UTC feeds become naive UTC
for compatibility with the rest of the engine. Collector CSVs use the broker's
clock; their explicit ``is_closed`` flag is authoritative without guessing a
broker/DST offset. A replay's explicit ``as_of`` must use the input clock.

No prices are repaired, interpolated, or silently chosen from conflicting bars.
A bad closed candle rejects that source; the loader may try another source.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}
OHLC = ("open", "high", "low", "close")


def candle_duration(timeframe: str) -> pd.Timedelta:
    try:
        return pd.Timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    except KeyError as exc:
        raise ValueError(f"Unsupported candle timeframe: {timeframe}") from exc


def naive_utc(value) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("Missing candle cutoff")
    return stamp.tz_convert(None) if stamp.tzinfo is not None else stamp


def closed_ohlcv(frame: pd.DataFrame, timeframe: str, *, as_of=None) -> pd.DataFrame:
    """Return sorted, unique, finite CLOSED bars without mutating the caller.

    Explicit ``is_closed=0`` always excludes a forming bar, even if the local
    clock says otherwise. Plain UTC OHLC is available only at time + duration.
    Identical duplicated observations are idempotent; conflicting duplicates
    are a data error, not an invitation to pick whichever arrived last.
    """
    duration = candle_duration(timeframe)
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["time", *OHLC, "tick_volume"])
    required = {"time", *OHLC}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{timeframe}: missing OHLC columns {sorted(missing)}")
    out = frame.copy(deep=True)
    out["time"] = pd.to_datetime(out["time"], utc=True, errors="raise").dt.tz_convert(None)
    if out["time"].isna().any():
        raise ValueError(f"{timeframe}: missing candle time")

    available = pd.Series(True, index=out.index)
    if "is_closed" in out:
        flags = out["is_closed"].astype(str).str.strip().str.lower()
        if not flags.isin({"0", "1", "false", "true", "0.0", "1.0"}).all():
            raise ValueError(f"{timeframe}: invalid is_closed flag")
        available &= flags.isin({"1", "true", "1.0"})
    broker_clock = bool(frame.attrs.get("broker_clock", False))
    if broker_clock and "is_closed" not in out:
        raise ValueError(f"{timeframe}: broker-clock bars require is_closed")
    if as_of is not None or not broker_clock:
        cutoff = naive_utc(as_of if as_of is not None else pd.Timestamp.now(tz="UTC"))
        available &= out["time"] + duration <= cutoff
    out = out.loc[available].copy()
    if "tick_volume" not in out:
        out["tick_volume"] = 0.0  # Missing volume is unavailable evidence, not a spike.
    numeric = [*OHLC, "tick_volume"]
    out[numeric] = out[numeric].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(out[numeric].to_numpy(dtype=float)).all():
        raise ValueError(f"{timeframe}: non-finite closed OHLC/volume")
    if (out[list(OHLC)] <= 0).any().any() or (out["tick_volume"] < 0).any():
        raise ValueError(f"{timeframe}: nonpositive price or negative volume")
    if ((out["high"] < out[["open", "close", "low"]].max(axis=1)).any()
            or (out["low"] > out[["open", "close", "high"]].min(axis=1)).any()):
        raise ValueError(f"{timeframe}: inconsistent OHLC bounds")
    out = out.drop_duplicates(subset=["time", *numeric])
    if out["time"].duplicated().any():
        raise ValueError(f"{timeframe}: conflicting candles at the same open time")
    out = out.sort_values("time", kind="stable").reset_index(drop=True)
    out.attrs.update(frame.attrs)
    out.attrs["closed_only"] = True
    out.attrs["timeframe"] = timeframe
    return out


def closed_data(data: dict[str, pd.DataFrame], *, as_of=None) -> dict[str, pd.DataFrame]:
    """Apply the same availability cutoff to every timeframe."""
    # One clock read prevents different timeframes straddling a bar boundary.
    cutoff = as_of if as_of is not None else pd.Timestamp.now(tz="UTC")
    return {
        tf: closed_ohlcv(frame, tf, as_of=(as_of if frame.attrs.get("broker_clock") else cutoff))
        for tf, frame in data.items()
    }
