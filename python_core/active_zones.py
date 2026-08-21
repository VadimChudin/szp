"""Incremental, side-aware lifecycle for visible Smart Zones.

The detector provides real candidates. This module owns exactly three slots above
and three slots below the current price. The snapshot is only changed after a
new closed H4 candle; it never rebuilds the visible set on every refresh.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

import config
import paths
from zone_detector import Zone, current_price, projected_levels

SNAPSHOT_FILE = paths.DATA_BRIDGE_DIR / "active_zones_snapshot.json"
EVENT_LOG_FILE = paths.DATA_BRIDGE_DIR / "zone_events.jsonl"
SNAPSHOT_VERSION = "3.1"


class Side:
    ABOVE = "ABOVE"
    BELOW = "BELOW"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bar_key(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _same_zone(a: Zone, b: Zone) -> bool:
    """Prevent nearby duplicate lines while keeping distinct price levels."""
    tolerance = max(config.CLUSTER_TOLERANCE, a.width * 2.0, b.width * 2.0)
    return abs(a.price - b.price) <= tolerance


def _serialize(zone: Zone) -> dict:
    return zone.to_dict()


def _hydrate(data: dict) -> Zone:
    return Zone.from_dict(data)


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
        "zones": [_serialize(zone) for zone in zones],
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
                        "side": zone.display_side, "fallback": zone.is_fallback,
                        "state": zone.state})
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
    return "" if frame.empty else _bar_key(frame.iloc[-1].get("time", ""))


def _new_bars(data: dict, last_h4: str) -> pd.DataFrame:
    frame = _h4_frame(data)
    if frame.empty or not last_h4 or "time" not in frame.columns:
        return frame.tail(1)
    try:
        return frame[pd.to_datetime(frame["time"]) > pd.Timestamp(last_h4)]
    except (TypeError, ValueError):
        return frame.tail(1)


def _side(zone: Zone, price: float) -> str:
    return Side.ABOVE if zone.price >= price else Side.BELOW


def _outside_active_window(zone: Zone, price: float | None) -> bool:
    """True when a visible level has moved outside the 10–15% live window."""
    if price is None or price <= 0:
        return False
    return abs(zone.price - price) / price * 100.0 > config.ACTIVE_ZONE_MAX_DISTANCE_PCT


def _rank(zone: Zone, price: float) -> tuple[int, float]:
    """Higher score wins; at equal score, the closer level wins."""
    return zone.score, -abs(zone.price - price)


def _mark_display(zone: Zone, side: str, h4: str, new: bool = False) -> None:
    zone.display_side = side
    zone.is_fallback = zone.score < config.MIN_ZONE_SCORE
    zone.state = "ACTIVE"
    zone.last_seen_h4 = h4
    if new or not zone.created_at:
        zone.created_at = _utc_now()


def _invalidate(zones: list[Zone], bars: pd.DataFrame, h4: str,
                reference_price: float | None) -> list[Zone]:
    """Remove only on a new H4 review, never on an intrabar price tick.

    A wick/test remains visible. A zone is removed when an H4 body closes past
    its boundary by a small width-based buffer, or when the live price has
    moved beyond the configured 10–15% visibility window.
    """
    active: list[Zone] = []
    for zone in zones:
        if _outside_active_window(zone, reference_price):
            zone.state = "EXPIRED_DISTANCE"
            zone.invalidated_at = h4
            zone.invalidation_reason = "outside_active_window"
            append_event("zone_invalidated", zone, h4, reason=zone.invalidation_reason,
                         distance_limit_pct=config.ACTIVE_ZONE_MAX_DISTANCE_PCT)
            continue

        removed = False
        for _, bar in bars.iterrows():
            try:
                high, low = float(bar["high"]), float(bar["low"])
                op, close = float(bar["open"]), float(bar["close"])
            except (KeyError, TypeError, ValueError):
                continue
            stamp = _bar_key(bar.get("time", h4))
            buffer = max(zone.width * config.ZONE_BREAK_BUFFER_WIDTHS,
                         config.SYMBOL_POINT * 10)
            close_below = close < zone.bottom - buffer and op >= zone.bottom - buffer
            close_above = close > zone.top + buffer and op <= zone.top + buffer
            body_break = close_below or close_above
            overlaps_zone = low <= zone.top and high >= zone.bottom
            if not overlaps_zone and not body_break:
                continue

            if(overlaps_zone):
                zone.test_count += 1
                zone.last_test_at = stamp
                zone.state = "TESTED"
                append_event("zone_tested", zone, h4, test_count=zone.test_count)

            if body_break or config.TEST_INVALIDATES_ZONE:
                zone.state = "INVALIDATED"
                zone.invalidated_at = stamp
                zone.invalidation_reason = "h4_close_breakout" if body_break else "confirmed_test"
                append_event("zone_invalidated", zone, h4, reason=zone.invalidation_reason)
                removed = True
                break
        if not removed:
            active.append(zone)
    return active


def _candidate_pool(candidates: Iterable[Zone]) -> list[Zone]:
    result: list[Zone] = []
    for candidate in candidates:
        if "PROJ" in candidate.label_suffix:
            continue
        if any(_same_zone(candidate, known) for known in result):
            # Preserve the strongest real candidate within a duplicate cluster.
            known = next(known for known in result if _same_zone(candidate, known))
            if candidate.score > known.score:
                result[result.index(known)] = copy.deepcopy(candidate)
            continue
        result.append(copy.deepcopy(candidate))
    return result


def _choose_side(existing: list[Zone], candidates: list[Zone], side: str,
                 price: float, h4: str) -> list[Zone]:
    slots = config.MIN_ZONES_PER_SIDE
    current = [zone for zone in existing if _side(zone, price) == side]
    candidates = [zone for zone in candidates if _side(zone, price) == side]

    # Keep one object per real level; a stronger fresh candidate updates it.
    unmatched: list[Zone] = []
    for candidate in candidates:
        match = next((zone for zone in current if _same_zone(zone, candidate)), None)
        if match is None:
            unmatched.append(candidate)
            continue
        if candidate.score > match.score:
            preserved_created = match.created_at
            match.__dict__.update(copy.deepcopy(candidate.__dict__))
            match.created_at = preserved_created or _utc_now()
            append_event("zone_strengthened", match, h4)
        _mark_display(match, side, h4)

    # Remove only excess lines from this side, never because the opposite side
    # has better scores. This preserves the 3+3 shape.
    current.sort(key=lambda zone: _rank(zone, price), reverse=True)
    for dropped in current[slots:]:
        append_event("zone_demoted", dropped, h4, reason="side_slot_limit")
    current = current[:slots]

    for candidate in sorted(unmatched, key=lambda zone: _rank(zone, price), reverse=True):
        if len(current) < slots:
            _mark_display(candidate, side, h4, new=True)
            current.append(candidate)
            append_event("zone_added", candidate, h4)
            continue
        weakest = min(current, key=lambda zone: _rank(zone, price))
        if _rank(candidate, price) > _rank(weakest, price):
            current.remove(weakest)
            append_event("zone_replaced", candidate, h4,
                         replaced_price=round(weakest.price, 2), replaced_score=weakest.score)
            _mark_display(candidate, side, h4, new=True)
            current.append(candidate)

    # The visible contract is absolute: exactly three lines must remain on
    # each side. At a new high/low the detector may have no historical wick
    # beyond price, so derive only the missing slots from projected round
    # levels. They are explicitly marked fallback and therefore render red.
    if len(current) < slots:
        for fallback in projected_levels(
            price,
            above=(side == Side.ABOVE),
            # Request a small surplus: nearby projected prices may merge with
            # real levels and otherwise leave a side with fewer than 3 slots.
            count=slots - len(current) + 3,
            force=True,
        ):
            if any(_same_zone(fallback, known) for known in current):
                continue
            _mark_display(fallback, side, h4, new=True)
            fallback.is_fallback = True
            current.append(fallback)
            append_event("zone_projected_fallback", fallback, h4)
            if len(current) >= slots:
                break

    for zone in current:
        _mark_display(zone, side, h4)
    return sorted(current, key=lambda zone: _rank(zone, price), reverse=True)[:slots]


def normalize_display_balance(zones: Iterable[Zone], price: float | None) -> list[Zone]:
    """Return exactly the configured visible slots on each side of *price*.

    The persisted H4 snapshot intentionally stays stable between candle closes,
    but a fast live move can leave all of its old levels on one visual side.
    This final export-only guard never mutates the snapshot: it preserves the
    strongest real levels on each side and fills only missing slots with red
    projected fallback levels.
    """
    if price is None or price <= 0:
        return list(zones)[:config.MAX_ZONES_ON_CHART]

    slots = config.MIN_ZONES_PER_SIDE
    visible: list[Zone] = []
    for side in (Side.ABOVE, Side.BELOW):
        real = [copy.deepcopy(zone) for zone in zones if _side(zone, price) == side]
        real.sort(key=lambda zone: _rank(zone, price), reverse=True)
        selected = real[:slots]
        for zone in selected:
            zone.display_side = side
            zone.is_fallback = zone.score < config.MIN_ZONE_SCORE

        if len(selected) < slots:
            for fallback in projected_levels(
                price,
                above=(side == Side.ABOVE),
                count=slots - len(selected),
                force=True,
            ):
                if any(_same_zone(fallback, known) for known in selected):
                    continue
                fallback.display_side = side
                fallback.is_fallback = True
                fallback.state = "DISPLAY_FALLBACK"
                selected.append(fallback)
                if len(selected) >= slots:
                    break
        visible.extend(selected)

    return visible[:config.MAX_ZONES_ON_CHART]


def update_snapshot(candidates: list[Zone], data: dict, path: Path = SNAPSHOT_FILE,
                    event_path: Path = EVENT_LOG_FILE,
                    reference_price: float | None = None) -> list[Zone]:
    """Update a six-line snapshot only once per newly closed H4 candle."""
    global EVENT_LOG_FILE
    previous_event_path = EVENT_LOG_FILE
    EVENT_LOG_FILE = event_path
    try:
        h4 = latest_closed_h4(data)
        state = load_snapshot(path)
        snapshot_contract_changed = state.get("version") != SNAPSHOT_VERSION
        current = [_hydrate(item) for item in state.get("zones", [])]
        if h4 and h4 == state.get("last_h4", "") and not snapshot_contract_changed:
            return current[:config.MAX_ZONES_ON_CHART]
        if snapshot_contract_changed and current:
            append_event(
                "snapshot_contract_rebuilt",
                h4=h4,
                previous_version=str(state.get("version", "unknown")),
                new_version=SNAPSHOT_VERSION,
            )
            current = []

        price = reference_price if reference_price is not None and reference_price > 0 else current_price(data)
        if price is None:
            save_snapshot(current[:config.MAX_ZONES_ON_CHART], h4, path)
            return current[:config.MAX_ZONES_ON_CHART]

        before = current[:]
        current = _invalidate(
            current,
            _new_bars(data, state.get("last_h4", "")),
            h4,
            price,
        )
        invalidated = [zone for zone in before if not any(_same_zone(zone, alive) for alive in current)]
        pool = [zone for zone in _candidate_pool(candidates)
                if not _outside_active_window(zone, price)
                and not any(_same_zone(zone, removed) for removed in invalidated)]

        above = _choose_side(current, pool, Side.ABOVE, price, h4)
        below = _choose_side(current, pool, Side.BELOW, price, h4)
        result = above + below
        save_snapshot(result, h4, path)
        return result
    finally:
        EVENT_LOG_FILE = previous_event_path
