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
from zone_detector import Zone, current_price

SNAPSHOT_FILE = paths.DATA_BRIDGE_DIR / "active_zones_snapshot.json"
EVENT_LOG_FILE = paths.DATA_BRIDGE_DIR / "zone_events.jsonl"
SNAPSHOT_VERSION = "3.0"


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


def _rank(zone: Zone, price: float) -> tuple[int, float]:
    """Higher score wins; at equal score, the closer level wins."""
    return zone.score, -abs(zone.price - price)


def _distance(zone: Zone, price: float) -> float:
    return abs(zone.price - price)


def _slot_window(index: int) -> tuple[float, float]:
    """Допустимое расстояние от цены для слота с номером index (0 = ближайший).

    Набор строится лестницей: ближайшая зона стоит в окне
    ZONE_NEAREST_MIN..ZONE_NEAREST_MAX, каждая следующая — на ZONE_GAP_MIN..
    ZONE_GAP_MAX дальше предыдущей. ZONE_BAND_TOLERANCE даёт запрошенное
    «примерно там», иначе слот часто оставался бы пустым.
    """
    low = config.ZONE_NEAREST_MIN + config.ZONE_GAP_MIN * index
    high = config.ZONE_NEAREST_MAX + config.ZONE_GAP_MAX * index
    slack = (high - low) * config.ZONE_BAND_TOLERANCE
    return max(low - slack, 0.0), high + slack


def _in_display_band(zone: Zone, price: float) -> bool:
    """Зона в пределах максимальной дистанции показа.

    MAX_ZONE_DISTANCE = 0 означает «ограничения нет» (поведение старой версии).
    """
    if config.MAX_ZONE_DISTANCE <= 0:
        return True
    return _distance(zone, price) <= config.MAX_ZONE_DISTANCE


def _mark_display(zone: Zone, side: str, h4: str, new: bool = False) -> None:
    zone.display_side = side
    zone.is_fallback = zone.score < config.MIN_ZONE_SCORE
    zone.state = "ACTIVE"
    zone.last_seen_h4 = h4
    if new or not zone.created_at:
        zone.created_at = _utc_now()


def _invalidate(zones: list[Zone], bars: pd.DataFrame, h4: str) -> list[Zone]:
    active: list[Zone] = []
    for zone in zones:
        removed = False
        for _, bar in bars.iterrows():
            try:
                high, low = float(bar["high"]), float(bar["low"])
                op, close = float(bar["open"]), float(bar["close"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (low <= zone.top and high >= zone.bottom):
                continue
            stamp = _bar_key(bar.get("time", h4))
            zone.test_count += 1
            zone.last_test_at = stamp
            zone.state = "TESTED"
            append_event("zone_tested", zone, h4, test_count=zone.test_count)
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
    """Ближайшие сильные зоны на стороне в пределах MAX_ZONE_DISTANCE.

    Никакой «лестницы» с минимальным отступом: клиент хочет видеть зоны близко
    к цене (напр. 4786 в $1). Отбор — по близости к цене, до ZONES_PER_SIDE штук.
    """
    slots = config.ZONES_PER_SIDE
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

    # Зона, ушедшая за пределы диапазона показа, снимается с графика.
    in_band: list[Zone] = []
    for zone in current:
        if _in_display_band(zone, price):
            in_band.append(zone)
        else:
            append_event("zone_out_of_band", zone, h4,
                         distance=round(_distance(zone, price), 2))
    current = in_band

    visible_ids = {id(zone) for zone in current}
    pool = current + [zone for zone in unmatched if _in_display_band(zone, price)]

    # Склейка близких уровней: в кластере оставляем самый сильный.
    deduped: list[Zone] = []
    for zone in sorted(pool, key=lambda z: (-z.score, _distance(z, price))):
        if any(_same_zone(zone, kept) for kept in deduped):
            continue
        deduped.append(zone)

    # Отбор по БЛИЗОСТИ к цене — ближайшие зоны важнее дальних.
    deduped.sort(key=lambda z: _distance(z, price))
    chosen = deduped[:slots]

    for pick in chosen:
        if id(pick) in visible_ids:
            _mark_display(pick, side, h4)
        else:
            _mark_display(pick, side, h4, new=True)
            append_event("zone_added", pick, h4)

    chosen_ids = {id(zone) for zone in chosen}
    for dropped in current:
        if id(dropped) not in chosen_ids:
            append_event("zone_demoted", dropped, h4, reason="range_slot_limit")

    return sorted(chosen, key=lambda zone: _distance(zone, price))


def update_snapshot(candidates: list[Zone], data: dict, path: Path = SNAPSHOT_FILE,
                    event_path: Path = EVENT_LOG_FILE) -> list[Zone]:
    """Update a six-line snapshot only once per newly closed H4 candle."""
    global EVENT_LOG_FILE
    previous_event_path = EVENT_LOG_FILE
    EVENT_LOG_FILE = event_path
    try:
        h4 = latest_closed_h4(data)
        state = load_snapshot(path)
        current = [_hydrate(item) for item in state.get("zones", [])]
        if h4 and h4 == state.get("last_h4", ""):
            return current[:config.MAX_ZONES_ON_CHART]

        price = current_price(data)
        if price is None:
            save_snapshot(current[:config.MAX_ZONES_ON_CHART], h4, path)
            return current[:config.MAX_ZONES_ON_CHART]

        before = current[:]
        current = _invalidate(current, _new_bars(data, state.get("last_h4", "")), h4)
        invalidated = [zone for zone in before if not any(_same_zone(zone, alive) for alive in current)]
        pool = [zone for zone in _candidate_pool(candidates)
                if not any(_same_zone(zone, removed) for removed in invalidated)]

        above = _choose_side(current, pool, Side.ABOVE, price, h4)
        below = _choose_side(current, pool, Side.BELOW, price, h4)
        if len(above) != config.ZONES_PER_SIDE or len(below) != config.ZONES_PER_SIDE:
            # Жёсткий контракт клиента: 3 сверху + 3 снизу. Если сторона неполная —
            # это видимый дефект, а не тихий перекос: пишем событие в журнал.
            append_event("snapshot_unbalanced", None, h4,
                         above=len(above), below=len(below))
        result = above + below
        save_snapshot(result, h4, path)
        return result
    finally:
        EVENT_LOG_FILE = previous_event_path
