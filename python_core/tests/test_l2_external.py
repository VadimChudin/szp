"""
Тесты внешнего прокси-стакана (l2_external).

Главное, что здесь закрепляется: прокси — это фолбэк, а не замена. Сетевые
вызовы замоканы; парсеры проверяются на консервированных ответах бирж.
Критичные инварианты:
  1. Без цены брокера внешняя книга НЕ используется — калибровка невозможна,
     а врать по ценам хуже, чем честный UNAVAILABLE.
  2. Калибровка сдвигает уровни так, что mid книги совпадает с ценой брокера.
  3. Живой стакан брокера всегда выигрывает у прокси.
"""

from datetime import datetime, timezone

import pytest

import config
import paths
import l2_external
from l2_external import (
    calibrate_to_price,
    fetch_external_book,
    parse_binance,
    parse_kraken,
    parse_okx,
)
from l2_validation import Book, validate_zones_l2
from zone_detector import Zone


MID = 4450.0

OKX_PAYLOAD = {
    "code": "0",
    "data": [{
        "bids": [["4449.80", "12.5", "0", "3"], ["4448.80", "40.0", "0", "5"]],
        "asks": [["4450.20", "10.0", "0", "2"], ["4451.20", "35.0", "0", "4"]],
    }],
}
KRAKEN_PAYLOAD = {
    "error": [],
    "result": {"PAXGUSD": {
        "bids": [["4449.80", "8.5", 1693000000], ["4448.80", "30.0", 1693000001]],
        "asks": [["4450.20", "9.0", 1693000000], ["4451.20", "25.0", 1693000001]],
    }},
}
BINANCE_PAYLOAD = {
    "bids": [["4449.80", "15.0"], ["4448.80", "50.0"]],
    "asks": [["4450.20", "11.0"], ["4451.20", "45.0"]],
}


# ── Парсеры ──────────────────────────────────────────────────────────────────

def test_parse_okx():
    book = parse_okx(OKX_PAYLOAD)
    assert book.bids == [(4449.8, 12.5), (4448.8, 40.0)]
    assert book.asks[0] == (4450.2, 10.0)
    assert book.mid == pytest.approx(4450.0)
    assert book.source == "okx:PAXG-USDT"


def test_parse_kraken():
    book = parse_kraken(KRAKEN_PAYLOAD)
    assert len(book.bids) == 2 and len(book.asks) == 2
    assert book.mid == pytest.approx(4450.0)


def test_parse_binance():
    book = parse_binance(BINANCE_PAYLOAD)
    assert book.bids[1] == (4448.8, 50.0)


def test_parse_garbage_is_empty_not_exception():
    assert parse_okx({}).is_empty
    assert parse_kraken({"result": {}}).is_empty
    assert parse_binance({"bids": "мусор"}).is_empty


# ── Калибровка ───────────────────────────────────────────────────────────────

def test_calibration_shifts_to_broker_scale():
    book = parse_okx(OKX_PAYLOAD)          # mid = 4450.0
    calibrated = calibrate_to_price(book, broker_price=4453.0)
    # Сдвиг +3.0: весь уровень переезжает, структура не меняется.
    assert calibrated.bids[0][0] == pytest.approx(4452.8)
    assert calibrated.asks[0][0] == pytest.approx(4453.2)
    assert calibrated.mid == pytest.approx(4453.0)
    assert calibrated.proxy is True
    assert "proxy:okx" in calibrated.source
    assert "+3.00" in calibrated.source


def test_calibration_requires_broker_price():
    book = parse_okx(OKX_PAYLOAD)
    assert calibrate_to_price(book, None) is None
    assert calibrate_to_price(book, 0) is None


# ── Перебор источников ───────────────────────────────────────────────────────

def test_first_available_source_wins(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return OKX_PAYLOAD

    monkeypatch.setattr(l2_external, "_http_get", fake_get)
    monkeypatch.setattr(config, "L2_EXTERNAL_SOURCE", "auto")
    book = fetch_external_book(broker_price=4450.0)
    assert book is not None and "okx" in book.source
    assert len(calls) == 1, "упавших/лишних запросов быть не должно"


def test_falls_through_dead_sources(monkeypatch):
    def fake_get(url, timeout):
        if "okx" in url:
            raise OSError("451 Unavailable For Legal Reasons")
        return KRAKEN_PAYLOAD

    monkeypatch.setattr(l2_external, "_http_get", fake_get)
    monkeypatch.setattr(config, "L2_EXTERNAL_SOURCE", "auto")
    book = fetch_external_book(broker_price=4450.0)
    assert book is not None and "kraken" in book.source


def test_all_sources_dead_returns_none(monkeypatch):
    monkeypatch.setattr(l2_external, "_http_get",
                        lambda url, timeout: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(config, "L2_EXTERNAL_SOURCE", "auto")
    assert fetch_external_book(broker_price=4450.0) is None


def test_no_broker_price_no_external(monkeypatch):
    """Без цены брокера даже живые источники не опрашиваются."""
    def boom(url, timeout):
        raise AssertionError("запроса быть не должно")

    monkeypatch.setattr(l2_external, "_http_get", boom)
    assert fetch_external_book(broker_price=None) is None


# ── Интеграция со слоем валидации ───────────────────────────────────────────

def test_external_used_when_broker_book_missing(tmp_path, monkeypatch):
    """Нет l2_book.json → прокси кормит валидацию, источник помечен proxy."""
    monkeypatch.setattr(config, "L2_BOOK_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(paths, "DATA_BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(config, "L2_EXTERNAL_SOURCE", "auto")
    monkeypatch.setattr(l2_external, "_http_get",
                        lambda url, timeout: OKX_PAYLOAD)

    zone = Zone(price=MID - 3, width=1.5, score=7)
    zones = validate_zones_l2([zone], price=MID)

    assert zones[0].l2_verdict in ("LIVE", "WATCH", "DEAD")
    assert zones[0].l2["source"].startswith("proxy:")


def test_broker_book_wins_over_proxy(tmp_path, monkeypatch):
    """Живой стакан брокера — всегда приоритет, прокси даже не опрашивается."""
    payload = {
        "symbol": "XAUUSD",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bids": [{"price": MID - 1, "volume": 100}],
        "asks": [{"price": MID + 1, "volume": 100}],
    }
    (tmp_path / "l2_book.json").write_text(__import__("json").dumps(payload))
    monkeypatch.setattr(config, "L2_BOOK_PATH", str(tmp_path / "l2_book.json"))
    monkeypatch.setattr(paths, "DATA_BRIDGE_DIR", tmp_path)

    def boom(url, timeout):
        raise AssertionError("прокси не должен опрашиваться при живом DOM")

    monkeypatch.setattr(l2_external, "_http_get", boom)
    zone = Zone(price=MID - 3, width=1.5, score=7)
    zones = validate_zones_l2([zone], price=MID)
    assert not zones[0].l2["source"].startswith("proxy:")


def test_external_off_keeps_unavailable(tmp_path, monkeypatch):
    """L2_EXTERNAL_SOURCE=off: без своего стакана — честный UNAVAILABLE."""
    monkeypatch.setattr(config, "L2_BOOK_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(paths, "DATA_BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(config, "L2_EXTERNAL_SOURCE", "off")

    def boom(url, timeout):
        raise AssertionError("при off запросов быть не должно")

    monkeypatch.setattr(l2_external, "_http_get", boom)
    zone = Zone(price=MID - 3, width=1.5, score=7)
    zones = validate_zones_l2([zone], price=MID)
    assert zones[0].l2_verdict == "UNAVAILABLE"
