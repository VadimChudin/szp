"""
zone_reaction.py — Классификация РЕАКЦИИ цены на зону.

zone_detector отвечает ГДЕ уровень, zone_confirmation — ЖИВ ли он.
Этот модуль отвечает на третий вопрос: КАК цена реагирует на зону прямо сейчас.

Три типа реакции (то, что просил клиент):
  • BOUNCE        — отскок: цена дошла до зоны и развернулась (rejection),
                    не закрывшись за неё телом. support → отскок вверх, resistance → вниз.
  • CONSOLIDATION — консолидация: цена «залипла» в зоне, диапазон сжат (< k·ATR),
                    нет решительного выхода в течение нескольких баров.
  • BREAKOUT      — пробой / «выстрел»: тело свечи закрылось за зоной и цена
                    ушла дальше > k·ATR (правило close-cross из neurotrader888).

Плюс служебные:
  • APPROACHING   — цена рядом с зоной (< k·ATR), но взаимодействия ещё нет.
  • NONE          — зона далеко, реакции нет.

Идеи заимствованы из open-source:
  - neurotrader888/TechnicalAnalysisAutomation — пробой = close пересёк уровень.
  - fortunato/pymarket-structure — ATR-порог как фильтр шума (break/retest).
  - day0market/support_resistance — счёт касаний (peak_count) как сила уровня.

Модуль чистый: принимает границы зоны и OHLC-DataFrame, ничего не пишет на диск.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config


# ── Типы реакции ──────────────────────────────────────────────────────────
class Reaction:
    BOUNCE = "BOUNCE"
    CONSOLIDATION = "CONSOLIDATION"
    BREAKOUT = "BREAKOUT"
    APPROACHING = "APPROACHING"
    NONE = "NONE"


@dataclass
class ReactionResult:
    type: str = Reaction.NONE
    direction: str = ""        # "UP" | "DOWN" | ""
    strength: float = 0.0      # 0..1 — насколько выражена реакция
    bars_since: int = -1       # сколько баров назад произошло касание (-1 = не было)
    touches: int = 0           # касаний зоны в окне анализа
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "direction": self.direction,
            "strength": round(self.strength, 3),
            "bars_since": self.bars_since,
            "touches": self.touches,
            "detail": self.detail,
        }


# ── Параметры (с безопасными дефолтами, переопределяемы через config) ───────
def _cfg(name: str, default):
    return getattr(config, name, default)


def _atr(df: pd.DataFrame, period: int) -> float:
    """Классический ATR по последним `period` барам. Fallback — средний размах."""
    if df is None or len(df) < 2:
        return 0.0
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.tail(period).mean()
    if not atr or atr != atr:  # NaN guard
        atr = float((high - low).tail(period).mean() or 0.0)
    return float(atr)


def _norm_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    cols = {c.lower(): c for c in df.columns}
    need = ("open", "high", "low", "close")
    if not all(c in cols for c in need):
        return pd.DataFrame()
    out = df.rename(columns={cols[c]: c for c in need})
    if "time" in cols:
        out = out.rename(columns={cols["time"]: "time"})
        try:
            out = out.sort_values("time")
        except Exception:
            pass
    return out.reset_index(drop=True)


def classify_reaction(
    zone_top: float,
    zone_bottom: float,
    df: pd.DataFrame,
    side: str = "",
) -> ReactionResult:
    """
    Классифицирует, как цена реагирует на зону [zone_bottom, zone_top].

    side: "ABOVE" (сопротивление, зона выше цены) | "BELOW" (поддержка, ниже) | ""
          Если не задан — определяется по положению последней цены.
    """
    df = _norm_ohlc(df)
    if df.empty or zone_top <= 0 or zone_bottom <= 0:
        return ReactionResult(detail="no data")

    lookback = int(_cfg("REACTION_LOOKBACK_BARS", 60))
    atr_period = int(_cfg("REACTION_ATR_PERIOD", 14))
    brk_atr = float(_cfg("REACTION_BREAKOUT_ATR", 0.5))
    bounce_atr = float(_cfg("REACTION_BOUNCE_ATR", 0.75))
    consol_atr = float(_cfg("REACTION_CONSOLIDATION_ATR", 1.2))
    min_consol = int(_cfg("REACTION_MIN_CONSOLIDATION_BARS", 3))
    approach_atr = float(_cfg("REACTION_APPROACH_ATR", 0.6))

    df = df.tail(lookback).reset_index(drop=True)
    n = len(df)
    atr = _atr(df, atr_period)
    if atr <= 0:
        return ReactionResult(detail="flat atr")

    center = (zone_top + zone_bottom) / 2.0
    price = float(df["close"].iloc[-1])
    if side not in ("ABOVE", "BELOW"):
        side = "ABOVE" if center >= price else "BELOW"

    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()

    def touched(i: int) -> bool:
        return l[i] <= zone_top and h[i] >= zone_bottom

    touches = sum(1 for i in range(n) if touched(i))

    # Последнее касание зоны в окне
    last_touch = -1
    for i in range(n - 1, -1, -1):
        if touched(i):
            last_touch = i
            break

    if last_touch < 0:
        # Взаимодействия нет — может, цена только подходит
        dist = min(abs(price - zone_top), abs(price - zone_bottom))
        if price > zone_top or price < zone_bottom:
            if dist <= approach_atr * atr:
                d = "DOWN" if price > zone_top else "UP"
                return ReactionResult(Reaction.APPROACHING, d,
                                      strength=max(0.0, 1 - dist / (approach_atr * atr)),
                                      bars_since=-1, touches=touches,
                                      detail=f"approaching ({dist:.2f}$ ~ {dist/atr:.2f} ATR)")
        return ReactionResult(Reaction.NONE, touches=touches, detail="no interaction")

    bars_since = n - 1 - last_touch

    # ── 1. BREAKOUT: тело закрылось за зоной ЧЕРЕЗ неё (> brk_atr·ATR) ────────
    # Направление пробоя задаётся стороной подхода (правило close-cross из
    # neurotrader888): сопротивление пробивают ВВЕРХ, поддержку — ВНИЗ.
    # Уход в «свою» сторону — это отскок, а не пробой.
    for i in range(last_touch, n):
        if side == "ABOVE" and c[i] > zone_top + brk_atr * atr:      # сопротивление пробито вверх
            over = c[i] - zone_top
            return ReactionResult(
                Reaction.BREAKOUT, "UP", strength=max(0.3, min(1.0, over / (2.0 * atr))),
                bars_since=n - 1 - i, touches=touches,
                detail=f"body closed {over:.2f}$ ({over/atr:.2f} ATR) above resistance")
        if side == "BELOW" and c[i] < zone_bottom - brk_atr * atr:   # поддержка пробита вниз
            over = zone_bottom - c[i]
            return ReactionResult(
                Reaction.BREAKOUT, "DOWN", strength=max(0.3, min(1.0, over / (2.0 * atr))),
                bars_since=n - 1 - i, touches=touches,
                detail=f"body closed {over:.2f}$ ({over/atr:.2f} ATR) below support")

    # ── 2. BOUNCE: rejection у зоны + уход прочь > bounce_atr·ATR без пробоя ──
    # support (BELOW): цена ткнулась снизу-вверх в зону и отскочила ВВЕРХ.
    # resistance (ABOVE): ткнулась и отскочила ВНИЗ.
    post_high = h[last_touch:].max()
    post_low = l[last_touch:].min()
    if side == "BELOW":
        move_away = price - zone_top
        rejection = (post_low <= zone_top) and (price > zone_top)
        if rejection and move_away >= bounce_atr * atr:
            return ReactionResult(
                Reaction.BOUNCE, "UP", strength=min(1.0, move_away / (2.0 * atr)),
                bars_since=bars_since, touches=touches,
                detail=f"bounced up {move_away:.2f}$ ({move_away/atr:.2f} ATR) from support")
    else:  # ABOVE
        move_away = zone_bottom - price
        rejection = (post_high >= zone_bottom) and (price < zone_bottom)
        if rejection and move_away >= bounce_atr * atr:
            return ReactionResult(
                Reaction.BOUNCE, "DOWN", strength=min(1.0, move_away / (2.0 * atr)),
                bars_since=bars_since, touches=touches,
                detail=f"bounced down {move_away:.2f}$ ({move_away/atr:.2f} ATR) from resistance")

    # ── 3. CONSOLIDATION: цена «залипла» у зоны, диапазон сжат ───────────────
    # Берём серию ПОДРЯД идущих касаний с конца — так тренд-бары до входа в
    # зону не попадают в окно и не раздувают диапазон.
    run = 0
    for i in range(n - 1, -1, -1):
        if touched(i):
            run += 1
        else:
            break
    seg_bars = run
    if seg_bars >= 1:
        seg_c = c[n - seg_bars:]
        # Диапазон по ЗАКРЫТИЯМ: консолидация — это кучные закрытия у зоны,
        # одиночные вики не должны ломать классификацию.
        seg_range = float(seg_c.max() - seg_c.min())
    else:
        seg_range = float("inf")
    near_zone = abs(price - center) <= max(zone_top - zone_bottom, atr)
    if (seg_bars >= min_consol and seg_range <= consol_atr * atr and near_zone):
        tightness = 1.0 - min(1.0, seg_range / (consol_atr * atr))
        return ReactionResult(
            Reaction.CONSOLIDATION, "", strength=max(0.3, tightness),
            bars_since=bars_since, touches=touches,
            detail=f"range {seg_range:.2f}$ ({seg_range/atr:.2f} ATR) over {seg_bars} bars")

    # ── Иначе: касание есть, но исход ещё не определился ─────────────────────
    return ReactionResult(
        Reaction.APPROACHING, "", strength=0.2,
        bars_since=bars_since, touches=touches,
        detail="touched, outcome pending")


def classify_zone(zone, data: dict) -> ReactionResult:
    """Обёртка для объекта Zone и словаря данных {tf: DataFrame}.

    Таймфрейм закрепа берётся из config.REACTION_TIMEFRAME (клиент смотрит H1).
    """
    tf = _cfg("REACTION_TIMEFRAME", None) or _cfg("PRIMARY_TIMEFRAME", "H4")
    df = data.get(tf)
    if df is None or (hasattr(df, "empty") and df.empty):
        for alt in ("H1", "H4", "D1"):
            if data.get(alt) is not None and not data[alt].empty:
                df = data[alt]
                break
    side = getattr(zone, "display_side", "") or ""
    return classify_reaction(zone.top, zone.bottom, df, side)
