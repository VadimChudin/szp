"""
l2_external.py — Внешний стакан как прокси-L2 для валидации зон.

Зачем это нужно
---------------
У спотового XAU/USD нет централизованного стакана: DOM, который показывает
брокер, — его внутренняя книга, и у части брокеров она пустая или
синтетическая. Тогда `l2_validation` честно уходит в UNAVAILABLE, и слой
не работает вообще. Этот модуль закрывает дыру: публичные REST-эндпоинты
криптобирж отдают НАСТОЯЩИЙ стакан по PAXG — токену, обеспеченному золотом
(1 PAXG ≈ 1 тройская унция). Лимитные заявки там живые, и поведение книги
(стены, перекосы, снятие заявок) переносится на золото почти один в один.

Два ограничения, которые нужно держать в голове
-----------------------------------------------
1. ЦЕНЫ НЕ СОВПАДАЮТ: PAXG торгуется со своим небольшим спредом к споту
   (обычно $1–5). Поэтому книга калибруется сдвигом: все уровни смещаются
   на (брокерская mid − внешняя mid). Без цены брокера калибровать нечего —
   и внешний источник не используется, это было бы враньё по ценам.
2. ОБЪЁМЫ НЕСРАВНИМЫ: у PAXG свои лоты. Проверки слоя это переживают,
   потому что нормируются на саму книгу (стена — к медиане уровня, перекос —
   к сумме сторон), но абсолютные цифры в деталях — внешние.

Внешняя книга — всегда ФОЛБЭК: если стакан брокера живой, внешний источник
не трогается. Каждая зона, проверенная по прокси, помечается в отчёте
(source начинается с "proxy:"), чтобы никто не принял её за брокерский DOM.

Источники перебираются в порядке L2_EXTERNAL_SOURCE=auto: okx → kraken →
binance. Binance из РФ отдаёт HTTP 451 — это не ошибка, просто переходим
к следующему.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

import config
from l2_validation import Book


# ─────────────────────────────────────────────────────────────────────────────
#  Парсеры ответов бирж (чистые функции — тестируются без сети)
# ─────────────────────────────────────────────────────────────────────────────

def parse_okx(payload: dict) -> Book:
    """OKX /api/v5/market/books: data[0].bids/asks = [[price, vol, ...], ...]."""
    data = (payload.get("data") or [{}])[0]

    def side(key):
        out = []
        for row in data.get(key) or []:
            try:
                p, v = float(row[0]), float(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if v > 0:
                out.append((p, v))
        return out

    return Book(bids=side("bids"), asks=side("asks"),
                timestamp=datetime.now(timezone.utc), source="okx:PAXG-USDT")


def parse_kraken(payload: dict) -> Book:
    """Kraken /0/public/Depth: result.<pair>.bids/asks = [[price, vol, ts], ...]."""
    result = payload.get("result") or {}
    pair = next(iter(result.values()), {})

    def side(key):
        out = []
        for row in pair.get(key) or []:
            try:
                p, v = float(row[0]), float(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if v > 0:
                out.append((p, v))
        return out

    return Book(bids=side("bids"), asks=side("asks"),
                timestamp=datetime.now(timezone.utc), source="kraken:PAXGUSD")


def parse_binance(payload: dict) -> Book:
    """Binance Futures /fapi/v1/depth: bids/asks = [[price, qty], ...]."""
    def side(key):
        out = []
        for row in payload.get(key) or []:
            try:
                p, v = float(row[0]), float(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if v > 0:
                out.append((p, v))
        return out

    return Book(bids=side("bids"), asks=side("asks"),
                timestamp=datetime.now(timezone.utc), source="binance:PAXGUSDT")


SOURCES = {
    "okx": ("https://www.okx.com/api/v5/market/books?instId=PAXG-USDT&sz=20",
            parse_okx),
    "kraken": ("https://api.kraken.com/0/public/Depth?pair=PAXGUSD&count=25",
               parse_kraken),
    "binance": ("https://fapi.binance.com/fapi/v1/depth?symbol=PAXGUSDT&limit=20",
                parse_binance),
}
# Порядок перебора в режиме auto. Binance последний: из РФ он отдаёт 451,
# и быстрее получить книгу с биржи, которая ответит сразу.
AUTO_ORDER = ("okx", "kraken", "binance")


# ─────────────────────────────────────────────────────────────────────────────
#  Калибровка
# ─────────────────────────────────────────────────────────────────────────────

def calibrate_to_price(book: Book, broker_price: float) -> Book | None:
    """
    Сдвигает все уровни внешней книги к ценовой шкале брокера.

    PAXG торгуется со спредом к споту, поэтому «стена на 4450» в книге PAXG
    без калибровки могла бы означать 4447 у брокера — валидация мазала бы
    мимо зон. Сдвиг = брокерская mid − внешняя mid; относительная структура
    книги (где стены, какой перекос) при сдвиге не меняется.
    """
    mid = book.mid
    if mid is None or broker_price is None or broker_price <= 0:
        return None
    offset = broker_price - mid
    return Book(
        bids=[(round(p + offset, 2), v) for p, v in book.bids],
        asks=[(round(p + offset, 2), v) for p, v in book.asks],
        timestamp=book.timestamp,
        source=f"proxy:{book.source} (Δ{offset:+.2f})",
        proxy=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Загрузка
# ─────────────────────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SmartZonesPro/4"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_external_book(broker_price: float | None) -> Book | None:
    """
    Пробует источники по очереди, возвращает откалиброванную книгу или None.

    None — нормальный исход: сети нет, все биржи недоступны, книги пустые.
    Слой валидации на это отвечает UNAVAILABLE, как и на отсутствие своего
    стакана.
    """
    if broker_price is None or broker_price <= 0:
        return None  # без цены брокера калибровка невозможна — не врём по ценам

    names = AUTO_ORDER if config.L2_EXTERNAL_SOURCE == "auto" \
        else (config.L2_EXTERNAL_SOURCE,)
    timeout = config.L2_EXTERNAL_TIMEOUT_SEC

    for name in names:
        entry = SOURCES.get(name)
        if entry is None:
            print(f"[l2] неизвестный внешний источник: {name}")
            return None
        url, parse = entry
        try:
            book = parse(_http_get(url, timeout))
        except Exception as e:
            # 451/таймаут/битый JSON — всё одинаково: источник недоступен,
            # переходим к следующему.
            print(f"[l2] внешний источник {name} недоступен ({type(e).__name__})")
            continue
        if book.is_empty or book.mid is None:
            print(f"[l2] внешний источник {name}: книга пуста")
            continue
        calibrated = calibrate_to_price(book, broker_price)
        if calibrated is not None:
            print(f"[l2] внешний стакан: {calibrated.source}, "
                  f"{len(calibrated.bids)} bid / {len(calibrated.asks)} ask")
            return calibrated
    return None
