"""Incremental H4 zone lifecycle.

The detector discovers candidates; this module owns the displayed snapshot.
The snapshot changes only on a new closed H4 bar. Existing zones are kept
unless they are invalidated or a strictly stronger candidate replaces the
weakest active zone.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

import config
import paths
from zone_detector import Zone, balance_around_price, current_price

SNAPSHOT_FILE = paths.DATA_BRIDGE_DIR / "active_zones_snapshot.json"
EVENT_LOG_FILE = paths.DATA_BRIDGE_DIR / "zone_events.jsonl"
SNAPSHOT_VERSION = "2.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bar_key(value) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _zone_key(zone: Zone, tolerance: float | None = None) -> float:
    return round(zone.price / (tolerance or max(zone.width, config.ZONE_WIDTH, 0.01)))


def _same_zone(a: Zone, b: Zone) -> bool:
    return abs(a.price - b.price) <= max(a.width, b.width, config.CLUSTER_TOLERANCE * 3.0)


def _serialize(zone: Zone) -> dict:
    data = zone.to_dict()
    data.update({
        "state": getattr(zone, "state", "ACTIVE"),
        "test_count": getattr(zone, "test_count", 0),
        "created_at": getattr(zone, "created_at", ""),
        "last_test_at": getattr(zone, "last_test_at", ""),
        "invalidated_at": getattr(zone, "invalidated_at", ""),
        "invalidation_reason": getattr(zone, "invalidation_reason", ""),
        "last_seen_h4": getattr(zone, "last_seen_h4", ""),
    })
    return data


def _hydrate(data: dict) -> Zone:
    zone = Zone.from_dict(data)
    for name, default in (
        ("state", "ACTIVE"), ("test_count", 0), ("created_at", ""),
        ("last_test_at", ""), ("invalidated_at", ""),
        ("invalidation_reason", ""), ("last_seen_h4", ""),
    ):
        setattr(zone, name, data.get(name, default))
    return zone


def load_snapshot(path: Path = SNAPSHOT_FILE) -> dict:
    data = paths.load_json_file(path, default={})
    if not isinstance(data, dict):
        return {"version": SNAPSHOT_VERSION, "last_h4": "", "zones": []}
    return data


def save_snapshot(zones: Iterable[Zone], last_h4: str, path: Path = SNAPSHOT_FILE) -> None:
    zones = list(zones)
    payload = {
        "version": SNAPSHOT_VERSION,
        "updated_at": _utc_now(),
        "last_h4": last_h4,
        "zone_count": len(zones),
        "zones": [_serialize(z) for z in zones],
    }
    paths.save_json_file(path, payload, indent=2)


def append_event(event: str, zone: Zone | None = None,
                 h4: str = "", path: Path | None = None, **extra) -> None:
    path = path or EVENT_LOG_FILE
    if not config.ZONE_EVENT_LOG_ENABLED:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": _utc_now(), "event": event, "h4": h4}
    if zone is not None:
        payload.update({"price": round(zone.price, 2), "score": zone.score,
                        "state": getattr(zone, "state", "ACTIVE")})
    payload.update(extra)
    with path.open("a", encoding="utf-8") as handle:
        import json
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _h4_frame(data: dict) -> pd.DataFrame:
    frame = data.get("H4")
    if frame is None or frame.empty:
        return pd.DataFrame()
    return frame.sort_values("time") if "time" in frame.columns else frame


def latest_closed_h4(data: dict) -> str:
    frame = _h4_frame(data)
    if frame.empty:
        return ""
    # The fetcher supplies closed candles. The bridge decides when a new H4
    # slot has closed; this value is the stable id persisted in the snapshot.
    return _bar_key(frame.iloc[-1].get("time", ""))


def _new_bars(data: dict, last_h4: str) -> pd.DataFrame:
    frame = _h4_frame(data)
    if frame.empty or not last_h4 or "time" not in frame.columns:
        return frame.tail(1)
    try:
        pivot = pd.Timestamp(last_h4)
        return frame[pd.to_datetime(frame["time"]) > pivot]
    except (TypeError, ValueError):
        return frame.tail(1)


def _invalidate(zones: list[Zone], bars: pd.DataFrame, h4: str) -> list[Zone]:
    active = []
    for zone in zones:
        removed = False
        for _, bar in bars.iterrows():
            try:
                high, low = float(bar["high"]), float(bar["low"])
                op, close = float(bar["open"]), float(bar["close"])
            except (KeyError, TypeError, ValueError):
                continue
            touched = low <= zone.top and high >= zone.bottom
            if not touched:
                continue
            stamp = _bar_key(bar.get("time", h4))
            zone.test_count = int(getattr(zone, "test_count", 0)) + 1
            zone.last_test_at = stamp
            zone.state = "TESTED"
            append_event("zone_tested", zone, h4, test_count=zone.test_count)
            # A completed H4 candle that enters the zone is a confirmed test.
            # A body closing beyond the full range is a hard invalidation.
            body_break = (op < zone.bottom and close > zone.top) or (op > zone.top and close < zone.bottom)
            if body_break or config.TEST_INVALIDATES_ZONE:
                zone.state = "INVALIDATED"
                zone.invalidated_at = stamp
                zone.invalidation_reason = "body_breakout" if body_break else "confirmed_test"
                append_event("zone_invalidated", zone, h4, reason=zone.invalidation_reason)
                removed = True
                break
        if not removed:
            active.append(zone)
    return active


def _candidate_pool(candidates: Iterable[Zone]) -> list[Zone]:
    result: list[Zone] = []
    for candidate in sorted(candidates, key=lambda z: z.score, reverse=True):
        if "PROJ" in getattr(candidate, "label_suffix", ""):
            continue
        if any(_same_zone(candidate, existing) for existing in result):
            continue
        result.append(copy.deepcopy(candidate))
    return result


def update_snapshot(candidates: list[Zone], data: dict, path: Path = SNAPSHOT_FILE,
                    event_path: Path = EVENT_LOG_FILE) -> list[Zone]:
    """Apply one incremental update. Idempotent for the same closed H4 bar."""
    global EVENT_LOG_FILE
    previous_event_path = EVENT_LOG_FILE
    EVENT_LOG_FILE = event_path
    try:
        h4 = latest_closed_h4(data)
        state = load_snapshot(path)
        last_h4 = state.get("last_h4", "")
        current = [_hydrate(item) for item in state.get("zones", [])]
        if h4 and h4 == last_h4:
            return current[: config.MAX_ZONES_ON_CHART]

        bars = _new_bars(data, last_h4)
        before_invalidation = current[:]
        current = _invalidate(current, bars, h4)
        invalidated = [z for z in before_invalidation
                       if not any(_same_zone(z, active) for active in current)]
        candidates = [candidate for candidate in _candidate_pool(candidates)
                      if not any(_same_zone(candidate, removed) for removed in invalidated)]

        # On initial fill, use the existing side-balancer so a strong cluster
        # below price cannot occupy every slot. Later updates preserve current
        # zones and use the same side preference only for empty slots.
        if not current:
            if not candidates:
                save_snapshot([], h4, path)
                return []
            price = current_price(data)
            strong = [z for z in candidates if z.score >= config.MIN_ZONE_SCORE]
            weak = [z for z in candidates if z.score < config.MIN_ZONE_SCORE]
            current = [z for z in balance_around_price(strong, weak, price)
                       if "PROJ" not in getattr(z, "label_suffix", "")]
            selected_keys = {_zone_key(z) for z in current}
            # If one side has no candidates, fill remaining slots with the
            # strongest non-duplicate candidates instead of stopping at quota.
            for candidate in candidates:
                if len(current) >= config.MAX_ZONES_ON_CHART:
                    break
                if _zone_key(candidate) not in selected_keys and not any(_same_zone(candidate, z) for z in current):
                    current.append(candidate)
                    selected_keys.add(_zone_key(candidate))
            for zone in current:
                zone.created_at = _utc_now()
                zone.last_seen_h4 = h4
                zone.state = "ACTIVE"
                append_event("zone_added", zone, h4)
            current.sort(key=lambda z: z.score, reverse=True)
            save_snapshot(current[:config.MAX_ZONES_ON_CHART], h4, path)
            return current[:config.MAX_ZONES_ON_CHART]

        # Refresh only a matching zone's score/metadata when the candidate is
        # genuinely stronger. Unmatched candidates compete for empty slots.
        for candidate in candidates:
            match = next((z for z in current if _same_zone(z, candidate)), None)
            if match is not None:
                if candidate.score > match.score:
                    old_score = match.score
                    match.__dict__.update(copy.deepcopy(candidate.__dict__))
                    match.state = "ACTIVE"
                    match.created_at = getattr(match, "created_at", "") or _utc_now()
                    append_event("zone_strengthened", match, h4, old_score=old_score)
                match.last_seen_h4 = h4
                continue
            if len(current) < config.MAX_ZONES_ON_CHART:
                price = current_price(data)
                quota = min(config.MIN_ZONES_PER_SIDE, config.MAX_ZONES_ON_CHART // 2)
                above = candidate.price > price if price is not None else False
                above_count = sum(z.price > price for z in current) if price is not None else 0
                below_count = sum(z.price < price for z in current) if price is not None else len(current)
                side_needed = (above and above_count < quota) or ((not above) and below_count < quota)
                if side_needed or len(current) >= config.MAX_ZONES_ON_CHART - 1:
                    candidate.created_at = _utc_now()
                    candidate.last_seen_h4 = h4
                    candidate.state = "ACTIVE"
                    current.append(candidate)
                    append_event("zone_added", candidate, h4)
                continue
            weakest = min(current, key=lambda z: z.score)
            if candidate.score > weakest.score:
                current.remove(weakest)
                append_event("zone_replaced", candidate, h4, replaced_price=weakest.price,
                             replaced_score=weakest.score)
                candidate.created_at = _utc_now()
                candidate.last_seen_h4 = h4
                candidate.state = "ACTIVE"
                current.append(candidate)

        current.sort(key=lambda z: z.score, reverse=True)
        current = current[: config.MAX_ZONES_ON_CHART]
        save_snapshot(current, h4, path)
        return current
    finally:
        EVENT_LOG_FILE = previous_event_path
