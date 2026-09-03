"""
tools.py — Инструменты, которые модель может дёрнуть. Считает КОД.

Разделение ответственности жёсткое: цифры считает Python, модель только
решает, какой инструмент нужен, и читает готовый результат. Спрашивать у
языковой модели «сколько раз отбивало от 4786» бессмысленно — она придумает
и даты, и проценты.

Главный инструмент — historical_analog: сколько раз цена исторически заходила
в эту полосу и чем это заканчивалось. Опирается на honest_backtest, где уже
реализованы классификация исхода и статистика.

Про ворота значимости
---------------------
Любой процент без базы сравнения — анекдот. Поэтому та же процедура прогоняется
по случайным уровням на похожем удалении, и результат отдаётся с двусторонним
z-тестом. Если зоны не лучше случайных уровней — инструмент честно сообщает,
что сигнала нет, вместо красивой, но пустой цифры.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, asdict

import pandas as pd

import config
from honest_backtest import (atr_of, evaluate_level, two_proportion_p,
                             wilson_interval)

MIN_TOUCHES = 8
DEFAULT_LOOKAHEAD = 12
BASELINE_LEVELS = 24


@dataclass
class AnalogReport:
    """Историческая статистика по одной полосе цен."""
    touches: int = 0
    bounce_rate: float = 0.0
    breakout_rate: float = 0.0
    consolidation_rate: float = 0.0
    avg_excursion_atr: float = 0.0
    ci_low: float = 0.0
    ci_high: float = 0.0
    baseline_rate: float = 0.0
    baseline_touches: int = 0
    p_value: float = 1.0
    significant: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        if self.touches < MIN_TOUCHES:
            return f"истории мало: {self.touches} касаний"
        verdict = ("лучше случайных уровней" if self.significant
                   else "не отличается от случайного уровня")
        return (f"{self.touches} касаний, отбой {self.bounce_rate:.0%} "
                f"(±{(self.ci_high - self.ci_low) / 2:.0%}), {verdict}")


def _frame(data: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    for key in ("H4", "H1", "D1"):
        frame = data.get(key)
        if frame is not None and not frame.empty:
            if {"open", "high", "low", "close"}.issubset(frame.columns):
                return frame.reset_index(drop=True)
    return None


def _outcomes(frame: pd.DataFrame, price: float, width: float, atr: float,
              lookahead: int) -> list[tuple[str, float]]:
    """Исходы всех исторических касаний полосы.

    После каждого касания перескакиваем на lookahead свечей вперёд: иначе одно
    длинное касание посчитается десять раз и статистика раздуется.
    """
    top, bottom = price + width, price - width
    results: list[tuple[str, float]] = []
    index = 0
    limit = len(frame) - lookahead
    while index < limit:
        bar = frame.iloc[index]
        try:
            low, high = float(bar["low"]), float(bar["high"])
        except (KeyError, TypeError, ValueError):
            index += 1
            continue
        if low <= top and high >= bottom:
            future = frame.iloc[index:index + lookahead]
            _, outcome, excursion = evaluate_level(price, top, bottom,
                                                   future, atr)
            if outcome != "no_touch":
                results.append((outcome, float(excursion)))
            index += lookahead
        else:
            index += 1
    return results


def _baseline(frame: pd.DataFrame, price: float, width: float, atr: float,
              lookahead: int, seed: int = 7) -> tuple[int, int]:
    """Случайные уровни на похожем удалении — база для сравнения."""
    rng = random.Random(seed)
    try:
        last = float(frame["close"].iloc[-1])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0, 0
    spread = max(abs(price - last), atr * 4) or atr * 4

    hits = total = 0
    for _ in range(BASELINE_LEVELS):
        offset = rng.uniform(-spread, spread)
        level = last + offset
        if abs(level - price) <= width * 2:
            continue  # это сама зона, а не независимая база
        for outcome, _excursion in _outcomes(frame, level, width, atr,
                                             lookahead):
            total += 1
            if outcome == "bounce":
                hits += 1
    return hits, total


def historical_analog(price: float, width: float,
                      data: dict[str, pd.DataFrame], *,
                      lookahead: int = DEFAULT_LOOKAHEAD) -> AnalogReport:
    """Как исторически отрабатывала эта полоса цен.

    Возвращает отчёт всегда: при нехватке данных — с пометкой в note и
    significant=False. Молчаливых нулей быть не должно, иначе модель примет
    отсутствие данных за отрицательный сигнал.
    """
    frame = _frame(data)
    if frame is None or len(frame) < lookahead * 2:
        return AnalogReport(note="нет истории для расчёта")

    width = float(width or getattr(config, "ZONE_WIDTH", 1.0)) or 1.0
    atr = atr_of(frame, int(getattr(config, "ATR_PERIOD", 14)))
    outcomes = _outcomes(frame, float(price), width, atr, lookahead)

    total = len(outcomes)
    if total == 0:
        return AnalogReport(note="цена ни разу не заходила в эту полосу")

    bounces = sum(1 for outcome, _ in outcomes if outcome == "bounce")
    breaks = sum(1 for outcome, _ in outcomes if outcome == "breakout")
    consolidations = sum(1 for outcome, _ in outcomes
                         if outcome == "consolidation")
    excursions = [value for _, value in outcomes]

    low, high = wilson_interval(bounces, total)
    base_hits, base_total = _baseline(frame, float(price), width, atr,
                                      lookahead)
    p_value = two_proportion_p(bounces, total, base_hits, base_total)

    report = AnalogReport(
        touches=total,
        bounce_rate=bounces / total,
        breakout_rate=breaks / total,
        consolidation_rate=consolidations / total,
        avg_excursion_atr=sum(excursions) / len(excursions),
        ci_low=low,
        ci_high=high,
        baseline_rate=(base_hits / base_total) if base_total else 0.0,
        baseline_touches=base_total,
        p_value=p_value,
    )
    report.significant = bool(
        total >= MIN_TOUCHES and base_total >= MIN_TOUCHES
        and p_value < 0.05 and report.bounce_rate > report.baseline_rate)
    if total < MIN_TOUCHES:
        report.note = "касаний слишком мало для вывода"
    elif not report.significant:
        report.note = "статистически не отличается от случайного уровня"
    return report


def delta_at_zone(price: float, data: dict[str, pd.DataFrame]) -> dict:
    """Перевес покупателей или продавцов у уровня. Тонкая обёртка."""
    try:
        from volume_filter import get_delta_at_zone
        value = get_delta_at_zone(price, data)
        if isinstance(value, dict):
            return value
        return {"delta": float(value)}
    except Exception as exc:
        return {"error": str(exc)}


REGISTRY = {
    "historical_analog": historical_analog,
    "delta_at_zone": delta_at_zone,
}
