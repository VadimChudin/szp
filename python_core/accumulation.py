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

    raw: list[AccumulationBox] = []
    for end in range(window - 1, len(data)):
        start = end - window + 1
        chunk = data.iloc[start:end + 1]

        expected_volume = avg_volume.iloc[end] * window
        typical = typical_range.iloc[end]
        if not expected_volume or pd.isna(expected_volume) or pd.isna(typical) or typical <= 0:
            continue

        chunk_volume = float(volume.iloc[start:end + 1].sum())
        if chunk_volume < expected_volume * config.ACCUMULATION_VOLUME_MULT:
            continue

        chunk_range = float(chunk["high"].max() - chunk["low"].min())
        if chunk_range > typical * window * config.ACCUMULATION_MAX_RANGE_MULT:
            continue

        bodies_top = float(chunk[["open", "close"]].max(axis=1).max())
        bodies_bottom = float(chunk[["open", "close"]].min(axis=1).min())
        raw.append(AccumulationBox(
            time_from=chunk["time"].iloc[0],
            time_to=chunk["time"].iloc[-1],
            top=bodies_top,
            bottom=bodies_bottom,
            volume_ratio=chunk_volume / expected_volume,
        ))

    return _merge(raw)[-config.ACCUMULATION_MAX_BOXES:]


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
