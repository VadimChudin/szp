"""Reproduce the current StrongZones MQL string parser collision.

The indicator scans every occurrence of the literal JSON key "price" and does
not restrict the scan to entries in the top-level zones array. Each zone exported
by bridge_server also contains a nested sl.price field, which therefore consumes
a visible slot.
"""
from __future__ import annotations

import json


def mql_price_slots(payload: str, limit: int = 6) -> list[float]:
    """Python equivalent of the current `StringFind(..., \"price\":)` loop."""
    values: list[float] = []
    cursor = 0
    marker = '"price":'
    while len(values) < limit:
        position = payload.find(marker, cursor)
        if position < 0:
            break
        start = position + len(marker)
        end = start
        while end < len(payload) and payload[end] not in ",}\n\r":
            end += 1
        values.append(float(payload[start:end].strip()))
        cursor = position + 10
    return values


def main() -> None:
    zones = []
    for i, zone_price in enumerate((4700, 4750, 4800, 4500, 4450, 4400), start=1):
        zones.append({
            "price": zone_price,
            "top": zone_price + 2,
            "bottom": zone_price - 2,
            "score": 12,
            "label": f"Z{i}",
            "is_fallback": False,
            "sl": {"side": "ABOVE_RESISTANCE", "price": zone_price + 20},
        })
    payload = json.dumps({"zones": zones}, separators=(",", ":"))
    visible = mql_price_slots(payload)
    expected = [zone["price"] for zone in zones]
    print("Expected six top-level zone prices:", expected)
    print("Actual first six values consumed by MQL scan:", visible)
    print("Nested SL values incorrectly consumed:", visible[1::2])
    assert visible == [4700.0, 4720.0, 4750.0, 4770.0, 4800.0, 4820.0]


if __name__ == "__main__":
    main()
