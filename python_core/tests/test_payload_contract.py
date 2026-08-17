import pytest

from payload_contract import PayloadContractError, build_payload, validate_payload
from sl_model import StopCandidate
from zone_detector import Zone


def _zone(price: float, *, fallback: bool = False) -> Zone:
    zone = Zone(price=price, width=1.0, score=8 if fallback else 12, sources=["H4"])
    zone.is_fallback = fallback
    zone.display_side = "ABOVE" if price > 100 else "BELOW"
    zone.state = "DISPLAY_FALLBACK" if fallback else "ACTIVE"
    return zone


def _stop(price: float) -> StopCandidate:
    return StopCandidate("BELOW_SUPPORT", price, 72, 1.0, 4.0, "test")


def _valid_payload():
    zones = [_zone(110), _zone(120), _zone(130), _zone(90), _zone(80), _zone(70)]
    stops = [_stop(zone.price - 5) for zone in zones]
    return build_payload(
        symbol="XAUUSD",
        producer_build="Experimental-test",
        reference_price=100,
        reference_source="collector_bid",
        zones=zones,
        stops=stops,
        calculated_at="2026-08-18T00:00:00+00:00",
    )


def test_payload_is_mql_safe_and_balanced():
    payload = _valid_payload()
    assert payload["schema_version"] == "4.0"
    assert len(payload["zones"]) == 6
    assert sum(zone["zone_price"] > 100 for zone in payload["zones"]) == 3
    assert sum(zone["zone_price"] < 100 for zone in payload["zones"]) == 3
    for zone in payload["zones"]:
        assert "price" not in zone
        assert zone["stop"]["stop_price"] > 0
        assert "price" not in zone["stop"]


def test_payload_rejects_unbalanced_display():
    payload = _valid_payload()
    payload["zones"][3].update({"zone_price": 140, "zone_top": 141, "zone_bottom": 139})
    with pytest.raises(PayloadContractError, match="unbalanced"):
        validate_payload(payload)


def test_payload_rejects_legacy_generic_price_key():
    payload = _valid_payload()
    payload["zones"][0]["price"] = 110
    with pytest.raises(PayloadContractError, match="generic"):
        validate_payload(payload)


def test_payload_rejects_missing_stop_candidate():
    zones = [_zone(110), _zone(120), _zone(130), _zone(90), _zone(80), _zone(70)]
    with pytest.raises(PayloadContractError, match="exactly one stop"):
        build_payload(
            symbol="XAUUSD",
            producer_build="Experimental-test",
            reference_price=100,
            reference_source="collector_bid",
            zones=zones,
            stops=[_stop(zone) for zone in zones[:-1]],
        )
