"""
broker_normalize.py — Единые зоны на всех брокерах через независимый эталон Dukascopy.

Проблема: у разных брокеров (RoboForex, и др.) цена XAU/USD отличается на оффсет
(обычно < $1, но бывает и больше), поэтому одни и те же зоны «не ложатся» на график
другого брокера и выглядят по-разному.

Решение (по выбору клиента):
  • ВАЛИДАЦИЯ (по умолчанию): зоны считаются на данных брокера, но на график
    попадают только те, что подтверждены эталонным фидом Dukascopy.
  • КАНОН: зоны считаются целиком по Dukascopy (одинаковые у всех брокеров),
    а при отрисовке сдвигаются на оффсет брокера.
  • ОФФСЕТ: линия зоны сдвигается на (цена брокера − цена Dukascopy), чтобы точно
    лечь на график брокера (у RoboForex XAU почти равен споту, но сдвиг безопасен).

Модуль best-effort: если Dukascopy недоступен, возвращаем зоны без изменений
(валидация не роняет расчёт).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd

import config


# ── Настройки (переопределяются через config/.env) ──────────────────────────
def _cfg(name: str, default):
    return getattr(config, name, default)


VALIDATION_MODE = _cfg("VALIDATION_MODE", "validate")   # validate | canonical | off
VALIDATION_TOLERANCE = _cfg("VALIDATION_TOLERANCE", 5.0)  # $ — допуск совпадения зоны
BROKER_OFFSET_ENABLED = _cfg("BROKER_OFFSET_ENABLED", True)
DUKA_SYMBOL = _cfg("DUKA_SYMBOL", "XAUUSD")
DUKA_DAYS = _cfg("DUKA_DAYS", 5)


# ── Получение эталонных OHLC из Dukascopy ───────────────────────────────────
def _mid_price(df: pd.DataFrame) -> pd.Series:
    if "mid" in df.columns:
        return df["mid"]
    if "ask" in df.columns and "bid" in df.columns:
        return (df["ask"] + df["bid"]) / 2.0
    if "close" in df.columns:
        return df["close"]
    raise ValueError("no price column in Dukascopy ticks")


def fetch_canonical_ohlc(symbol: str = None, days: int = None) -> dict[str, pd.DataFrame]:
    """Скачивает тики Dukascopy и собирает H1/H4 OHLC. Возвращает {H1, H4}."""
    symbol = symbol or DUKA_SYMBOL
    days = days or DUKA_DAYS
    try:
        from dukascopy_loader import DukascopyLoader
        loader = DukascopyLoader(max_workers=5)
        ticks = loader.fetch_history(symbol, days_back=days)
        if ticks is None or ticks.empty:
            return {}
        df = ticks.copy()
        if "time" not in df.columns:
            return {}
        df["time"] = pd.to_datetime(df["time"], utc=True)
        if df["time"].dt.tz is not None:
            df["time"] = df["time"].dt.tz_convert(None)
        df["price"] = _mid_price(df).astype(float)
        df = df.set_index("time").sort_index()

        def _ohlc(rule: str) -> pd.DataFrame:
            g = df["price"].resample(rule).agg(["first", "max", "min", "last"]).dropna()
            g = g.rename(columns={"first": "open", "max": "high",
                                  "min": "low", "last": "close"}).reset_index()
            return g

        h1 = _ohlc("1h")
        h4 = _ohlc("4h")
        out = {}
        if not h1.empty:
            out["H1"] = h1
        if not h4.empty:
            out["H4"] = h4
        return out
    except Exception as exc:
        print(f"[broker_normalize] WARN: Dukascopy fetch failed: {exc}")
        return {}


def canonical_zones(data: dict[str, pd.DataFrame]) -> list:
    """Зоны, посчитанные по эталонному фиду Dukascopy."""
    try:
        from zone_detector import detect_zones
        zones = detect_zones(data, None, limit_output=False)
        return [z for z in zones if z.score >= config.MIN_ZONE_SCORE]
    except Exception as exc:
        print(f"[broker_normalize] WARN: canonical zone calc failed: {exc}")
        return []


# ── Валидация брокерских зон эталоном ───────────────────────────────────────
def validate_zones(broker_zones: list, canonical: list,
                   tolerance: float = None) -> list:
    """Оставляет брокерские зоны, рядом с которыми есть эталонная зона."""
    tolerance = tolerance if tolerance is not None else VALIDATION_TOLERANCE
    if not canonical:
        # Эталона нет — не режем брокерские зоны (best-effort).
        return broker_zones
    canon_prices = [z.price for z in canonical]
    kept = []
    for z in broker_zones:
        if any(abs(z.price - cp) <= tolerance for cp in canon_prices):
            kept.append(z)
    return kept


# ── Оффсет брокера ──────────────────────────────────────────────────────────
def compute_offset(broker_price: float | None, canonical_price: float | None) -> float:
    """Сдвиг линии: цена брокера − цена эталона. 0 если данных нет."""
    if broker_price is None or canonical_price is None or canonical_price <= 0:
        return 0.0
    return float(broker_price - canonical_price)


def current_price(data: dict) -> float | None:
    for tf in ("H1", "H4", "D1"):
        df = data.get(tf)
        if df is not None and not df.empty and "close" in df.columns:
            return float(df["close"].iloc[-1])
    return None


def shift_zone(zone, offset: float):
    """Сдвигает цену зоны на оффсет (для точного наложения на брокера).

    top/bottom — read-only свойства, производные от price/width, поэтому
    достаточно сдвинуть price, границы пересчитаются сами.
    """
    if not offset:
        return
    zone.price = round(zone.price + offset, 2)


# ── Главная точка входа ─────────────────────────────────────────────────────
def normalize_broker_zones(broker_zones: list, broker_data: dict) -> list:
    """Применяет выбранный режим к брокерским зонам. Возвращает итоговые зоны."""
    mode = VALIDATION_MODE
    if mode == "off":
        return broker_zones

    source = (getattr(config, "DATA_SOURCE", "") or "").strip().lower()
    # Детектор уже посчитал зоны по полному OHLC Dukascopy — не пересчитывать
    # за 5 дней. Нужен только сдвиг на цену брокера.
    if source in ("dukascopy", "duka"):
        zones = list(broker_zones)
        print(f"[broker_normalize] using detector zones as canonical ({len(zones)})")
        if BROKER_OFFSET_ENABLED:
            try:
                from data_fetcher import broker_spot_price
                live = broker_spot_price()
            except Exception as exc:
                print(f"[broker_normalize] WARN: broker spot failed: {exc}")
                live = None
            duka_price = current_price(broker_data)
            offset = compute_offset(live, duka_price)
            if offset:
                print(f"[broker_normalize] offset {offset:+.2f}$ applied "
                      f"(broker {live:.2f} vs duka {duka_price:.2f})")
                for z in zones:
                    shift_zone(z, offset)
        return zones

    canonical_data = fetch_canonical_ohlc()
    if not canonical_data:
        print("[broker_normalize] No canonical data — returning broker zones unchanged")
        return broker_zones

    if mode == "canonical":
        zones = canonical_zones(canonical_data)
        print(f"[broker_normalize] canonical mode: {len(zones)} zones from Dukascopy")
    else:
        canonical = canonical_zones(canonical_data)
        zones = validate_zones(broker_zones, canonical)
        print(f"[broker_normalize] validate: kept {len(zones)}/{len(broker_zones)} "
              f"(canonical pool {len(canonical)})")

    if BROKER_OFFSET_ENABLED:
        broker_price = current_price(broker_data)
        canon_price = current_price(canonical_data)
        offset = compute_offset(broker_price, canon_price)
        if offset:
            print(f"[broker_normalize] offset {offset:+.2f}$ applied "
                  f"(broker {broker_price:.2f} vs duka {canon_price:.2f})")
            for z in zones:
                shift_zone(z, offset)

    return zones
