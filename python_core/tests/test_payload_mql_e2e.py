import json

from payload_contract import build_health_payload, build_payload
from sl_model import StopCandidate
from zone_detector import Zone


def _zone(price: float, side: str, fallback: bool = False) -> Zone:
    zone = Zone(price=price, width=1.0, score=8 if fallback else 12, sources=["H4"])
    zone.display_side = side
    zone.is_fallback = fallback
    zone.state = "DISPLAY_FALLBACK" if fallback else "ACTIVE"
    return zone


def _stop(zone: Zone) -> StopCandidate:
    long_side = zone.display_side == "BELOW"
    return StopCandidate(
        "BELOW_SUPPORT" if long_side else "ABOVE_RESISTANCE",
        zone.price - 4 if long_side else zone.price + 4,
        71,
        1.5,
        4.0,
        "golden-test",
    )


def _mql_schema_four_prices(serialized: str) -> list[float]:
    """Byte-level equivalent of the MQL strict `zone_price` scan."""
    marker = '"zone_price":'
    cursor = 0
    result = []
    while True:
        position = serialized.find(marker, cursor)
        if position < 0:
            break
        start = position + len(marker)
        end = start
        while end < len(serialized) and serialized[end] not in ",}\n\r":
            end += 1
        result.append(float(serialized[start:end].strip()))
        cursor = position + len(marker)
    return result


def test_python_to_mql_schema_four_roundtrip_keeps_exactly_the_six_zone_prices():
    zones = [
        _zone(110, "ABOVE"), _zone(120, "ABOVE"), _zone(130, "ABOVE", True),
        _zone(90, "BELOW"), _zone(80, "BELOW"), _zone(70, "BELOW", True),
    ]
    payload = build_payload(
        symbol="XAUUSDm",
        producer_build="Experimental-golden",
        reference_price=100,
        reference_source="collector_bid",
        zones=zones,
        stops=[_stop(zone) for zone in zones],
        calculated_at="2026-08-18T00:00:00+00:00",
    )
    serialized = json.dumps(payload, separators=(",", ":"))
    parsed_prices = _mql_schema_four_prices(serialized)

    assert parsed_prices == [110.0, 120.0, 130.0, 90.0, 80.0, 70.0]
    assert len(parsed_prices) == 6
    assert sum(price > 100 for price in parsed_prices) == 3
    assert sum(price < 100 for price in parsed_prices) == 3
    assert '"price":' not in serialized
    assert serialized.count('"stop_price":') == 6


def test_health_payload_references_the_exact_delivered_payload():
    zones = [_zone(110, "ABOVE"), _zone(120, "ABOVE"), _zone(130, "ABOVE"),
             _zone(90, "BELOW"), _zone(80, "BELOW"), _zone(70, "BELOW")]
    payload = build_payload(
        symbol="XAUUSD", producer_build="Experimental-golden", reference_price=100,
        reference_source="collector_bid", zones=zones, stops=[_stop(z) for z in zones],
    )
    health = build_health_payload(
        producer_build="Experimental-golden", symbol="XAUUSD", reference_price=100,
        reference_source="collector_bid", payload=payload,
    )
    assert health["payload_id"] == payload["payload_id"]
    assert health["zone_count"] == 6
    assert health["above_count"] == 3
    assert health["below_count"] == 3
