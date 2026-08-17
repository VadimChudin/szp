"""Strict, versioned payload shared by Python Bridge and MQL renderers.

MQL cannot safely consume a document where nested fields reuse generic names
such as ``price``.  This module deliberately gives every displayed concept a
unique key and validates the entire top-level ``zones`` array before delivery.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

import config
from sl_model import StopCandidate
from zone_detector import Zone

SCHEMA_VERSION = "4.0"
PAYLOAD_KIND = "szp_active_zones"


class PayloadContractError(ValueError):
    """A payload cannot be safely rendered by StrongZones."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def zone_record(zone: Zone, stop: StopCandidate | None = None) -> dict[str, Any]:
    """Convert a domain zone to a flat, MQL-safe top-level DTO."""
    record: dict[str, Any] = {
        "zone_price": round(float(zone.price), 2),
        "zone_top": round(float(zone.top), 2),
        "zone_bottom": round(float(zone.bottom), 2),
        "zone_score": int(zone.score),
        "zone_label": zone.label,
        "zone_sources": "+".join(sorted(set(zone.sources))),
        "zone_has_big_player": bool(zone.has_big_player),
        "zone_fallback": bool(zone.is_fallback),
        "zone_kind": "display_fallback" if zone.state == "DISPLAY_FALLBACK" else "real",
        "zone_side": zone.display_side,
        "zone_state": zone.state,
    }
    if stop is not None:
        record["stop"] = {
            "stop_side": stop.side,
            "stop_price": round(float(stop.price), 2),
            "stop_probability": int(stop.probability),
            "stop_buffer": round(float(stop.buffer), 2),
            "stop_atr": round(float(stop.atr), 2),
            "stop_rationale": stop.rationale,
        }
    return record


def _side_counts(records: Iterable[dict[str, Any]], reference_price: float) -> tuple[int, int]:
    above = sum(float(item["zone_price"]) > reference_price for item in records)
    below = sum(float(item["zone_price"]) < reference_price for item in records)
    return above, below


def validate_payload(payload: dict[str, Any]) -> None:
    """Reject ambiguous, stale-schema or unbalanced payloads before sync."""
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise PayloadContractError("unsupported schema version")
    if payload.get("payload_kind") != PAYLOAD_KIND:
        raise PayloadContractError("unexpected payload kind")
    if not isinstance(payload.get("producer_build"), str) or not payload["producer_build"]:
        raise PayloadContractError("producer_build is required")
    reference = payload.get("reference_price")
    if not isinstance(reference, (int, float)) or reference <= 0:
        raise PayloadContractError("reference_price must be positive")
    zones = payload.get("zones")
    if not isinstance(zones, list) or len(zones) != config.MAX_ZONES_ON_CHART:
        raise PayloadContractError("payload must contain exactly six display zones")

    required = {
        "zone_price", "zone_top", "zone_bottom", "zone_score", "zone_label",
        "zone_sources", "zone_has_big_player", "zone_fallback", "zone_kind",
        "zone_side", "zone_state", "stop",
    }
    for item in zones:
        if not isinstance(item, dict) or not required.issubset(item):
            raise PayloadContractError("incomplete zone record")
        if "price" in item:
            raise PayloadContractError("generic zone price key is forbidden")
        stop = item["stop"]
        if not isinstance(stop, dict) or "stop_price" not in stop or "price" in stop:
            raise PayloadContractError("MQL-safe stop record is required")
        if not (float(item["zone_bottom"]) <= float(item["zone_price"]) <= float(item["zone_top"])):
            raise PayloadContractError("invalid zone bounds")

    above, below = _side_counts(zones, float(reference))
    required_per_side = config.MIN_ZONES_PER_SIDE
    if above != required_per_side or below != required_per_side:
        raise PayloadContractError(
            f"unbalanced display contract: above={above}, below={below}, ref={reference}"
        )


def build_payload(*, symbol: str, producer_build: str, reference_price: float,
                  reference_source: str, zones: Iterable[Zone],
                  stops: Iterable[StopCandidate | None], calculated_at: str | None = None,
                  fp_status: str = "Ready") -> dict[str, Any]:
    zone_list = list(zones)
    stop_list = list(stops)
    if len(zone_list) != len(stop_list):
        raise PayloadContractError("every display zone must have exactly one stop candidate")
    records = [zone_record(zone, stop) for zone, stop in zip(zone_list, stop_list)]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "payload_kind": PAYLOAD_KIND,
        "payload_id": uuid4().hex,
        "producer_build": producer_build,
        "symbol": symbol,
        "calculated_at": calculated_at or _utc_now(),
        "reference_price": round(float(reference_price), 2),
        "reference_source": reference_source,
        "zone_count": len(records),
        "fp_status": fp_status,
        "zones": records,
    }
    validate_payload(payload)
    return payload


def build_health_payload(*, producer_build: str, symbol: str, reference_price: float,
                         reference_source: str, payload: dict[str, Any]) -> dict[str, Any]:
    above, below = _side_counts(payload["zones"], float(reference_price))
    return {
        "schema_version": SCHEMA_VERSION,
        "health_kind": "szp_bridge_health",
        "updated_at": _utc_now(),
        "producer_build": producer_build,
        "symbol": symbol,
        "reference_price": round(float(reference_price), 2),
        "reference_source": reference_source,
        "payload_id": payload["payload_id"],
        "payload_calculated_at": payload["calculated_at"],
        "zone_count": len(payload["zones"]),
        "above_count": above,
        "below_count": below,
        "status": "healthy",
    }
