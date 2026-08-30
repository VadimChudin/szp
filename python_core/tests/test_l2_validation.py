"""
Тесты L2-валидации зон (стакан / DOM).

Ключевой приём — как и в тестах подтверждения: стакан строится с ЗАРАНЕЕ
ИЗВЕСТНОЙ структурой. У поддержки стоит толстая bid-стена, книга тяжелее
снизу. Если модель этого не различает — она бесполезна, каким бы
правдоподобным ни выглядел её вывод на живом стакане.

Отдельно закреплены два контракта, которые легко сломать рефакторингом:
  1. В payload зоны не должно быть ключа "price" внутри l2 — индикатор
     MT4/MT5 парсит zones_output.json наивно, и лишний "price" породит
     фантомную зону (та же ловушка, что с wick_points).
  2. UNAVAILABLE — не ноль. Без стакана (MT4, брокер без DOM, протухший
     снапшот) зоны получают нейтраль и НЕ отбрасываются даже в filter-режиме.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import config
import paths
from zone_detector import Zone
from l2_validation import (
    Book,
    L2Report,
    check_imbalance,
    check_persistence,
    check_wall,
    load_book,
    validate_zone_l2,
    validate_zones_l2,
)

MID = 4450.0


def _book_payload(bids, asks, age_sec: float = 0):
    """Снапшот стакана в формате l2_book.json (контракт с EA)."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_sec)
    return {
        "symbol": "XAUUSD",
        "timestamp": ts.isoformat(),
        "tick_bid": MID - 0.2,
        "tick_ask": MID + 0.2,
        "depth_levels": len(bids) + len(asks),
        "bids": [{"price": p, "volume": v} for p, v in bids],
        "asks": [{"price": p, "volume": v} for p, v in asks],
    }


def _flat_book(wall_price=None, wall_volume=0.0, side="bids",
               heavy="bids"):
    """
    Книга с уровнями каждый $1 и медианным объёмом 100.
    wall_price/wall_volume — где стоит стена; heavy — какая сторона тяжелее.
    """
    bid_vol, ask_vol = (150.0, 50.0) if heavy == "bids" else (50.0, 150.0)
    bids, asks = [], []
    for i in range(1, 16):
        bids.append((MID - i, bid_vol))
        asks.append((MID + i, ask_vol))
    if wall_price is not None:
        target = bids if side == "bids" else asks
        for idx, (p, v) in enumerate(target):
            if abs(p - wall_price) < 0.01:
                target[idx] = (p, wall_volume)
                break
        else:
            target.append((wall_price, wall_volume))
    return bids, asks


def _write_book(tmp_path, monkeypatch, payload, name="l2_book.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(config, "L2_BOOK_PATH", str(path))
    # Прев-снапшот и ротация — в изолированную папку, не в репозиторий.
    monkeypatch.setattr(paths, "DATA_BRIDGE_DIR", tmp_path)
    return path


@pytest.fixture
def l2_off(monkeypatch):
    """Гасим L2 после теста и отвязываем от реальных путей машины."""
    monkeypatch.setattr(config, "L2_BOOK_PATH", "")
    yield


# ── A. Стена на зоне ─────────────────────────────────────────────────────────

def test_wall_on_support_scores_high():
    """Толстая bid-стена в диапазоне поддержки — максимальный балл."""
    bids, asks = _flat_book(wall_price=MID - 3, wall_volume=1000.0)
    book = Book(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
    zone = Zone(price=MID - 3, width=1.5, score=7)

    check = check_wall(zone, book, price=MID)
    assert check.value == pytest.approx(1.0)
    assert "стоят" in check.detail


def test_wall_on_wrong_side_scores_low():
    """Ask-стена над поддержкой не засчитывается: сторона должна совпадать."""
    bids, asks = _flat_book(wall_price=MID - 3, wall_volume=1000.0,
                            side="asks", heavy="asks")
    book = Book(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
    zone = Zone(price=MID - 3, width=1.5, score=7)

    check = check_wall(zone, book, price=MID)
    # В bid-стороне возле зоны только плоские 150 — медиана тоже 150.
    assert check.value == pytest.approx(0.0)
    assert "стены нет" in check.detail


def test_wall_beyond_book_coverage_is_neutral():
    """Зона за пределами видимой глубины — нейтраль, а не ноль."""
    bids, asks = _flat_book()
    book = Book(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
    far_zone = Zone(price=MID - 40, width=1.5, score=7)  # книга кончается на −15

    check = check_wall(far_zone, book, price=MID)
    assert check.value == pytest.approx(0.5)
    assert "не достаёт" in check.detail


# ── B. Перекос книги ─────────────────────────────────────────────────────────

def test_imbalance_aligned_with_support():
    bids, asks = _flat_book(heavy="bids")
    book = Book(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
    support = Zone(price=MID - 5, width=1.5, score=7)

    check = check_imbalance(support, book, price=MID)
    assert check.value == pytest.approx(1.0)


def test_imbalance_conflicting_with_support():
    """Поддержка при тяжёлой ask-стороне — конфликт знаков, штраф."""
    bids, asks = _flat_book(heavy="asks")
    book = Book(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
    support = Zone(price=MID - 5, width=1.5, score=7)

    check = check_imbalance(support, book, price=MID)
    assert check.value == pytest.approx(0.0)


# ── C. Стойкость стены (спуфинг-фильтр) ─────────────────────────────────────

def _book_with_wall(wall_volume: float) -> Book:
    bids, asks = _flat_book(wall_price=MID - 3, wall_volume=wall_volume)
    return Book(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))


def test_persistent_wall_is_honest():
    zone = Zone(price=MID - 3, width=1.5, score=7)
    check = check_persistence(zone, _book_with_wall(900.0),
                              _book_with_wall(1000.0), price=MID)
    assert check.value == pytest.approx(1.0)
    assert "держится" in check.detail


def test_pulled_wall_is_spoofing():
    """Стену сняли между снапшотами — классический спуфинг, штраф."""
    zone = Zone(price=MID - 3, width=1.5, score=7)
    check = check_persistence(zone, _book_with_wall(100.0),
                              _book_with_wall(1000.0), price=MID)
    assert check.value == pytest.approx(0.1)
    assert "спуфинг" in check.detail


def test_no_prev_snapshot_is_neutral():
    zone = Zone(price=MID - 3, width=1.5, score=7)
    check = check_persistence(zone, _book_with_wall(1000.0), None, price=MID)
    assert check.value == pytest.approx(0.5)


# ── Сквозная валидация ───────────────────────────────────────────────────────

def test_full_report_live_zone(tmp_path, monkeypatch):
    """Стена + перекос + стойкость — зона должна получить LIVE."""
    payload = _book_payload(*_flat_book(wall_price=MID - 3,
                                        wall_volume=1000.0))
    _write_book(tmp_path, monkeypatch, payload)
    # Прошлый снапшот с той же стеной — стойкость максимальна.
    (tmp_path / "l2_book_prev.json").write_text(json.dumps(payload),
                                                encoding="utf-8")
    zone = Zone(price=MID - 3, width=1.5, score=7)
    zones = validate_zones_l2([zone], price=MID)

    assert len(zones) == 1
    assert zone.l2_verdict == "LIVE"
    assert zone.l2_score >= config.L2_LIVE_THRESHOLD
    # Ротация: текущий снапшот стал предыдущим для следующего пересчёта.
    assert (tmp_path / "l2_book_prev.json").is_file()


def test_unavailable_when_no_book(tmp_path, monkeypatch, l2_off):
    """Нет файла — UNAVAILABLE с нейтралью, а не выдуманный ноль."""
    monkeypatch.setattr(config, "L2_EXTERNAL_SOURCE", "off")
    monkeypatch.setattr(config, "L2_BOOK_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(paths, "DATA_BRIDGE_DIR", tmp_path)
    zone = Zone(price=MID - 3, width=1.5, score=7)
    validate_zones_l2([zone], price=MID)

    assert zone.l2_verdict == "UNAVAILABLE"
    assert zone.l2_score == pytest.approx(0.5)


def test_unavailable_when_book_empty(tmp_path, monkeypatch):
    """Брокер без DOM: книга пустая — UNAVAILABLE, а не штраф зонам."""
    monkeypatch.setattr(config, "L2_EXTERNAL_SOURCE", "off")
    _write_book(tmp_path, monkeypatch, _book_payload([], []))
    zone = Zone(price=MID - 3, width=1.5, score=7)
    validate_zones_l2([zone], price=MID)

    assert zone.l2_verdict == "UNAVAILABLE"
    assert "не транслирует" in zone.l2["reason"]


def test_unavailable_when_book_stale(tmp_path, monkeypatch):
    """Протухший снапшот нельзя отличить от мёртвого EA — не доверяем."""
    monkeypatch.setattr(config, "L2_EXTERNAL_SOURCE", "off")
    payload = _book_payload(*_flat_book(), age_sec=config.L2_MAX_AGE_SEC + 60)
    _write_book(tmp_path, monkeypatch, payload)
    zone = Zone(price=MID - 3, width=1.5, score=7)
    validate_zones_l2([zone], price=MID)

    assert zone.l2_verdict == "UNAVAILABLE"
    assert "протух" in zone.l2["reason"]


# ── Режимы ───────────────────────────────────────────────────────────────────

def test_filter_drops_dead_but_keeps_unavailable(tmp_path, monkeypatch):
    """
    DEAD отбрасываем, UNAVAILABLE — никогда. Иначе у брокера с пустым
    стаканом или на MT4 график просто опустел бы.
    """
    monkeypatch.setattr(config, "L2_MODE", "filter")

    # DEAD: конфликтная книга (ask тяжелее) + стены нет + стену сняли.
    # Рядом кладём живую зону, чтобы не сработала защита от полной зачистки.
    payload = _book_payload(*_flat_book(wall_price=MID - 6,
                                        wall_volume=1000.0, heavy="asks"))
    _write_book(tmp_path, monkeypatch, payload)
    prev = _book_payload(*_flat_book(wall_price=MID - 3, wall_volume=1000.0,
                                     heavy="asks"))
    (tmp_path / "l2_book_prev.json").write_text(json.dumps(prev),
                                                encoding="utf-8")
    dead_zone = Zone(price=MID - 3, width=1.5, score=7)
    live_zone = Zone(price=MID - 6, width=1.5, score=7)
    zones = validate_zones_l2([dead_zone, live_zone], price=MID)
    assert zones == [live_zone], "конфликтная зона должна быть отфильтрована"
    assert live_zone.l2_verdict in ("LIVE", "WATCH")

    # UNAVAILABLE: книги нет — зона проходит.
    monkeypatch.setattr(config, "L2_BOOK_PATH", str(tmp_path / "missing.json"))
    zone = Zone(price=MID - 3, width=1.5, score=7)
    zones = validate_zones_l2([zone], price=MID)
    assert len(zones) == 1


def test_filter_full_clear_guard(tmp_path, monkeypatch):
    """Если ВСЕ зоны DEAD — фильтр отказывается и возвращает исходные."""
    monkeypatch.setattr(config, "L2_MODE", "filter")
    payload = _book_payload(*_flat_book(heavy="asks"))
    _write_book(tmp_path, monkeypatch, payload)
    prev = _book_payload(*_flat_book(wall_price=MID - 3, wall_volume=1000.0,
                                     heavy="asks"))
    (tmp_path / "l2_book_prev.json").write_text(json.dumps(prev),
                                                encoding="utf-8")
    zones_in = [Zone(price=MID - 3, width=1.5, score=7),
                Zone(price=MID - 4.5, width=1.5, score=5)]
    zones = validate_zones_l2(list(zones_in), price=MID)
    if all(z.l2_verdict == "DEAD" for z in zones):
        # Сработала защита от полной зачистки: вернулись обе зоны.
        assert len(zones) == 2


def test_rerank_promotes_l2_live(tmp_path, monkeypatch):
    """В rerank живая по стакану зона обгоняет равную по score мёртвую."""
    monkeypatch.setattr(config, "L2_MODE", "rerank")
    payload = _book_payload(*_flat_book(wall_price=MID - 3,
                                        wall_volume=1000.0))
    _write_book(tmp_path, monkeypatch, payload)
    (tmp_path / "l2_book_prev.json").write_text(json.dumps(payload),
                                                encoding="utf-8")
    live = Zone(price=MID - 3, width=1.5, score=7)
    dead = Zone(price=MID + 3, width=1.5, score=7)  # стены сверху нет,
    # перекос bid — сопротивлению вредит
    zones = validate_zones_l2([dead, live], price=MID)
    assert zones[0] is live


def test_off_mode_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "L2_MODE", "off")
    zone = Zone(price=MID - 3, width=1.5, score=7)
    zones = validate_zones_l2([zone], price=MID)
    assert zones == [zone]
    assert zone.l2 == {}


# ── Контракты сериализации ───────────────────────────────────────────────────

def test_no_price_key_anywhere_in_l2_payload(tmp_path, monkeypatch):
    """
    Индикатор MT4/MT5 парсит zones_output.json наивно, по ключу "price".
    Ключ "price" внутри l2 породит фантомную зону — как было с wick_points.
    """
    payload = _book_payload(*_flat_book(wall_price=MID - 3,
                                        wall_volume=1000.0))
    _write_book(tmp_path, monkeypatch, payload)
    zone = Zone(price=MID - 3, width=1.5, score=7)
    validate_zones_l2([zone], price=MID)

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                assert k != "price", f"ключ 'price' найден в l2 payload"
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(zone.l2)


def test_zone_roundtrip_preserves_l2():
    """to_dict/from_dict обязаны не терять L2-поля (снапшот ↔ диск)."""
    zone = Zone(price=4400.0, width=1.5, score=8)
    zone.l2 = L2Report(score=0.82, verdict="LIVE", source="test").to_dict()
    zone.l2_score = 0.82
    zone.l2_verdict = "LIVE"

    restored = Zone.from_dict(zone.to_dict())
    assert restored.l2_score == pytest.approx(0.82)
    assert restored.l2_verdict == "LIVE"
    assert restored.l2["score"] == pytest.approx(0.82)


def test_badge_format():
    assert L2Report(score=0.82, verdict="LIVE").badge == " L2✓0.82"
    assert L2Report(score=0.5, verdict="WATCH").badge == " L2~0.50"
    assert L2Report(score=0.2, verdict="DEAD").badge == " L2✗0.20"
    # UNAVAILABLE в подпись не лезет — мусор на графике не нужен.
    assert L2Report(verdict="UNAVAILABLE").badge == ""


def test_label_suffix_badge(tmp_path, monkeypatch):
    """Метка L2 попадает в подпись зоны при L2_IN_LABEL=true."""
    monkeypatch.setattr(config, "L2_IN_LABEL", True)
    payload = _book_payload(*_flat_book(wall_price=MID - 3,
                                        wall_volume=1000.0))
    _write_book(tmp_path, monkeypatch, payload)
    (tmp_path / "l2_book_prev.json").write_text(json.dumps(payload),
                                                encoding="utf-8")
    zone = Zone(price=MID - 3, width=1.5, score=7)
    validate_zones_l2([zone], price=MID)
    assert "L2" in zone.label_suffix
