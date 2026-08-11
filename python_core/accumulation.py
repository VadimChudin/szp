"""
accumulation.py — Поиск участков набора позиции крупным участником.

Признак набора: на нескольких соседних свечах прошёл аномально большой объём,
но цена почти не сдвинулась (крупный игрок «впитывает» рынок, не разгоняя его).
Такие участки индикатор рисует небольшими фиолетовыми прямоугольниками.

Результат пишется в отдельный файл `accumulation_output.json`, чтобы не менять
формат `zones_output.json`, который индикаторы парсят наивным поиском по ключам.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import pandas as pd

import config


@dataclass
class AccumulationBox:
    """Один участок набора позиции (прямоугольник на графике)."""
    time_from: datetime
    time_to: datetime
    top: float
    bottom: float
    volume_ratio: float

    def to_dict(self) -> dict:
        # Время свечей приходит из терминала клиента, т.е. это время сервера
        # брокера — в MT его достаточно привести к datetime из epoch.
        return {
            "t1": int(pd.Timestamp(self.time_from).timestamp()),
            "t2": int(pd.Timestamp(self.time_to).timestamp()),
            "top": round(float(self.top), 2),
            "bottom": round(float(self.bottom), 2),
            "vol_ratio": round(float(self.volume_ratio), 2),
        }


def _volume_series(df: pd.DataFrame) -> pd.Series:
    for col in ("real_volume", "tick_volume", "volume"):
        if col in df.columns and df[col].fillna(0).sum() > 0:
            return df[col].astype(float)
    return pd.Series(0.0, index=df.index)


def detect_accumulations(df: pd.DataFrame) -> list[AccumulationBox]:
    """Ищет участки «объём большой, а цена стоит» на переданных свечах."""
    window = max(2, config.ACCUMULATION_WINDOW)
    if df is None or len(df) < window + config.VOLUME_LOOKBACK:
        return []

    data = df.tail(config.ACCUMULATION_LOOKBACK_BARS).reset_index(drop=True)
    volume = _volume_series(data)
    if volume.sum() <= 0:
        return []

    avg_volume = volume.rolling(config.VOLUME_LOOKBACK, min_periods=2).mean()
    candle_range = (data["high"] - data["low"]).astype(float)
    typical_range = candle_range.rolling(config.VOLUME_LOOKBACK, min_periods=2).median()

    # Ширина свечи: правый край прямоугольника должен закрывать последнюю
    # свечу участка, а не заканчиваться на её открытии.
    bar_delta = pd.to_datetime(data["time"]).diff().median()
    if pd.isna(bar_delta):
        bar_delta = pd.Timedelta(0)

    raw: list[AccumulationBox] = []
    # Кандидаты «почти прошедшие» пороги: у разных брокеров tick_volume ведёт
    # себя по-разному, и фиксированные пороги давали ровно 0 участков.
    runners_up: list[tuple[float, AccumulationBox]] = []
    best_vol_ratio = 0.0
    best_range_ratio = 0.0
    for end in range(window - 1, len(data)):
        start = end - window + 1
        chunk = data.iloc[start:end + 1]

        expected_volume = avg_volume.iloc[end] * window
        typical = typical_range.iloc[end]
        if not expected_volume or pd.isna(expected_volume) or pd.isna(typical) or typical <= 0:
            continue

        chunk_volume = float(volume.iloc[start:end + 1].sum())
        vol_ratio = chunk_volume / expected_volume
        chunk_range = float(chunk["high"].max() - chunk["low"].min())
        range_ratio = chunk_range / (typical * window)
        best_vol_ratio = max(best_vol_ratio, vol_ratio)
        if best_range_ratio == 0.0 or range_ratio < best_range_ratio:
            best_range_ratio = range_ratio

        # Цена обязана стоять на месте: широкий ход на объёме — это импульс,
        # а не набор позиции, послаблений тут быть не может.
        if range_ratio > config.ACCUMULATION_MAX_RANGE_MULT:
            continue
        if vol_ratio < config.ACCUMULATION_FALLBACK_MIN_VOL:
            continue

        bodies_top = float(chunk[["open", "close"]].max(axis=1).max())
        bodies_bottom = float(chunk[["open", "close"]].min(axis=1).min())
        # Плоский участок даёт прямоугольник нулевой высоты (невидим на графике).
        min_height = typical * 0.35
        if bodies_top - bodies_bottom < min_height:
            mid = (bodies_top + bodies_bottom) / 2.0
            bodies_top = mid + min_height / 2.0
            bodies_bottom = mid - min_height / 2.0
        box = AccumulationBox(
            time_from=chunk["time"].iloc[0],
            time_to=pd.Timestamp(chunk["time"].iloc[-1]) + bar_delta,
            top=bodies_top,
            bottom=bodies_bottom,
            volume_ratio=vol_ratio,
        )

        if vol_ratio >= config.ACCUMULATION_VOLUME_MULT:
            raw.append(box)
        else:
            runners_up.append((vol_ratio / max(range_ratio, 0.01), box))

    fallback = 0
    if not raw and runners_up:
        # Лучше показать самые «объёмные при стоящей цене» участки, чем не
        # показать ничего: пороги подобраны на одних данных, а брокеры разные.
        runners_up.sort(key=lambda item: item[0], reverse=True)
        best = [box for _, box in runners_up[:config.ACCUMULATION_FALLBACK_BOXES]]
        best.sort(key=lambda b: b.time_from)
        raw = best
        fallback = len(best)

    boxes = _merge(raw)[-config.ACCUMULATION_MAX_BOXES:]
    # Диагностика в клиентский лог: без неё непонятно, пороги строгие или
    # участков набора действительно нет.
    print(f"[accumulation] {len(data)} bars, candidates={len(raw)}, boxes={len(boxes)}"
          f"{' (fallback)' if fallback else ''} "
          f"(best vol x{best_vol_ratio:.2f} >= x{config.ACCUMULATION_VOLUME_MULT}, "
          f"tightest range x{best_range_ratio:.2f} <= x{config.ACCUMULATION_MAX_RANGE_MULT})")
    return boxes


def _merge(boxes: Iterable[AccumulationBox]) -> list[AccumulationBox]:
    """Склеивает пересекающиеся по времени окна в один прямоугольник."""
    merged: list[AccumulationBox] = []
    for box in boxes:
        if merged and box.time_from <= merged[-1].time_to:
            prev = merged[-1]
            merged[-1] = AccumulationBox(
                time_from=prev.time_from,
                time_to=max(prev.time_to, box.time_to),
                top=max(prev.top, box.top),
                bottom=min(prev.bottom, box.bottom),
                volume_ratio=max(prev.volume_ratio, box.volume_ratio),
            )
        else:
            merged.append(box)
    return merged


def build_output(data: dict[str, pd.DataFrame]) -> dict:
    """Готовит содержимое accumulation_output.json по свечам нужного ТФ."""
    tf = config.ACCUMULATION_TIMEFRAME
    boxes = detect_accumulations(data.get(tf)) if config.ACCUMULATION_ENABLED else []
    return {
        "symbol": config.SYMBOL,
        "timeframe": tf,
        "calculated_at": datetime.now().isoformat(),
        "count": len(boxes),
        "boxes": [b.to_dict() for b in boxes],
    }
