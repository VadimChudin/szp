"""
zone_confirmation.py — Проверка, жива ли зона.

Разделение ответственности
--------------------------
`zone_detector` отвечает на вопрос ГДЕ был уровень: ищет фитили, склеивает их
в кластеры, считает структурный score. Этот модуль отвечает на другой вопрос —
РАБОТАЕТ ЛИ уровень сейчас.

Это принципиально разные вещи, и они намеренно не смешаны. Уровень, от которого
цена трижды отбилась в прошлом месяце, структурно силён всегда: фитили никуда не
денутся. Но если объём там давно не проходил, а стопы под ним уже сняли — зона
мертва, сколько бы фитилей её ни формировало.

Поэтому подтверждение НЕ добавляется в `score`. Это отдельное измерение:
    score       — насколько уровень значим структурно  (0..∞, целое)
    confirmation— насколько он жив прямо сейчас        (0..1, дробное)

Четыре независимых проверки
---------------------------
Ни одна из них по отдельности не является достаточной, поэтому берётся
взвешенная сумма. Веса подобраны по принципу «чем прямее измерение, тем
больше вес»: проторгованный объём — это факт, свежесть — производная оценка.

  A. Узел объёма   (вес .40) — стоит ли зона на HVN или в пустоте (LVN).
  B. Пул стопов    (вес .25) — есть ли рядом неснятые равные экстремумы.
  C. Дельта        (вес .20) — кто был агрессором на прошлых касаниях.
  D. Свежесть      (вес .15) — сколько раз уровень уже успели съесть.

Главный сигнал — A. Зона на LVN не отработает почти никогда: там нет ни
лимитных заявок, ни истории сделок, цена проходит такое место транзитом.
Именно эту проверку нельзя было сделать по одним свечам — нужен профиль,
привязанный к цене, а не ко времени.

Режимы работы (config.CONFIRMATION_MODE)
----------------------------------------
  off      — модуль выключен, поведение как до эксперимента.
  annotate — считаем и пишем в JSON/лейбл, но состав зон НЕ меняем.
             Режим по умолчанию: сначала смотрим, что показывает метрика,
             и только потом даём ей право что-то отбрасывать.
  filter   — зоны с вердиктом DEAD убираются из выдачи.
  rerank   — кандидаты сортируются по score * (0.5 + confirmation).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

import config
from liquidity_source import VolumeProfile


# ─────────────────────────────────────────────────────────────────────────────
#  Результат проверки
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Check:
    """Одна проверка: оценка 0..1 плюс человекочитаемая причина."""
    name: str
    value: float
    weight: float
    detail: str = ""

    @property
    def contribution(self) -> float:
        return self.value * self.weight


@dataclass
class ConfirmationReport:
    """Итог по одной зоне."""
    score: float = 0.0                       # 0..1
    verdict: str = "UNKNOWN"                 # LIVE | WATCH | DEAD | UNKNOWN
    checks: list[Check] = field(default_factory=list)
    source: str = ""                         # чем подтверждали

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 3),
            "verdict": self.verdict,
            "source": self.source,
            "checks": [asdict(c) | {"contribution": round(c.contribution, 3)}
                       for c in self.checks],
        }

    @property
    def badge(self) -> str:
        """Короткая метка для подписи на графике."""
        if self.verdict == "UNKNOWN":
            return ""
        mark = {"LIVE": "✓", "WATCH": "~", "DEAD": "✗"}.get(self.verdict, "")
        return f" {mark}{self.score:.2f}"


# ─────────────────────────────────────────────────────────────────────────────
#  A. Узел объёма
# ─────────────────────────────────────────────────────────────────────────────

def check_volume_node(zone, profile: VolumeProfile | None) -> Check:
    """
    Стоит ли зона на реальном узле проторговки.

    Считаем, во сколько раз объём в диапазоне зоны превышает свою
    справедливую долю — то есть долю, которая пришлась бы на этот диапазон
    при равномерном распределении объёма по всей проторгованной истории.

    Отображение плотности в оценку кусочно-линейное:
        ratio <= LVN (0.5)  → 0.0   пустота, зона не удержит
        ratio >= HVN (1.5)  → 1.0   узел, там реально торговали
        между               → линейно
    """
    w = config.CONFIRM_WEIGHT_VOLUME_NODE

    if profile is None:
        return Check("volume_node", 0.5, w, "профиля нет — нейтрально")

    ratio = profile.density_ratio(zone.bottom, zone.top)
    if ratio <= 0:
        return Check("volume_node", 0.0, w, "объёма в диапазоне зоны нет вообще")

    lvn, hvn = config.LVN_RATIO, config.HVN_RATIO
    if ratio <= lvn:
        value = 0.0
        detail = f"LVN ×{ratio:.2f} — пустота, цена проходит транзитом"
    elif ratio >= hvn:
        value = 1.0
        detail = f"HVN ×{ratio:.2f} — плотный узел проторговки"
    else:
        value = (ratio - lvn) / (hvn - lvn)
        detail = f"×{ratio:.2f} — средняя плотность"

    return Check("volume_node", round(value, 3), w, detail)


# ─────────────────────────────────────────────────────────────────────────────
#  B. Пул ликвидности (равные экстремумы)
# ─────────────────────────────────────────────────────────────────────────────

def find_liquidity_pools(df: pd.DataFrame, swing_length: int = 10,
                         tolerance: float | None = None) -> list[dict]:
    """
    Скопления стопов: два и более примерно равных экстремума.

    Смысл: под равными минимумами толпа держит стопы, над равными максимумами
    — тоже. Такое скопление притягивает цену, потому что его выгодно снять.
    Пока пул не снят, он остаётся аргументом за то, что цена туда придёт;
    после снятия аргумент исчезает.

    Алгоритм повторяет подход `smartmoneyconcepts.liquidity` (★1.9k):
    находим свинги, группируем близкие по цене, отмечаем снятые.
    Реализовано локально, чтобы не тянуть pip-зависимость в сборку PyInstaller.
    """
    if df is None or len(df) < swing_length * 2 + 1:
        return []

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    n = len(highs)

    if tolerance is None:
        span = float(np.nanmax(highs) - np.nanmin(lows))
        tolerance = span * config.LIQUIDITY_POOL_RANGE_PCT

    # ── Свинги: экстремум сильнее всех соседей в окне ────────────────────────
    swing_h, swing_l = [], []
    for i in range(swing_length, n - swing_length):
        window_h = highs[i - swing_length: i + swing_length + 1]
        window_l = lows[i - swing_length: i + swing_length + 1]
        if highs[i] == window_h.max():
            swing_h.append((i, highs[i]))
        if lows[i] == window_l.min():
            swing_l.append((i, lows[i]))

    pools = []

    def group(swings, kind):
        used = set()
        for a, (ia, pa) in enumerate(swings):
            if a in used:
                continue
            members = [(ia, pa)]
            used.add(a)
            for b in range(a + 1, len(swings)):
                if b in used:
                    continue
                ib, pb = swings[b]
                if abs(pb - pa) <= tolerance:
                    members.append((ib, pb))
                    used.add(b)
            if len(members) < 2:
                continue  # одиночный экстремум пулом не считаем

            level = float(np.mean([p for _, p in members]))
            last_idx = max(i for i, _ in members)

            # Снят ли пул: после последнего касания цена его пробила.
            after = slice(last_idx + 1, n)
            if kind == "high":
                swept = bool(np.any(highs[after] > level + tolerance))
            else:
                swept = bool(np.any(lows[after] < level - tolerance))

            pools.append({
                "kind": kind,
                "level": round(level, 2),
                "touches": len(members),
                "swept": swept,
                "last_index": last_idx,
            })

    group(swing_h, "high")
    group(swing_l, "low")
    return pools


def check_liquidity_pool(zone, pools: list[dict]) -> Check:
    """
    Есть ли рядом с зоной неснятое скопление стопов.

    Нейтральное значение здесь 0.5, а не 0: отсутствие пула — не улика против
    зоны. Уровень может держаться на одном лишь проторгованном объёме.
    Штрафуем только уже снятый пул: если стопы забрали, магнит исчез.
    """
    w = config.CONFIRM_WEIGHT_LIQUIDITY_POOL

    if not pools:
        return Check("liquidity_pool", 0.5, w, "пулов не найдено — нейтрально")

    reach = max(zone.width * 2.0, config.CLUSTER_TOLERANCE)
    near = [p for p in pools if abs(p["level"] - zone.price) <= reach]

    if not near:
        return Check("liquidity_pool", 0.5, w, "рядом пулов нет — нейтрально")

    fresh = [p for p in near if not p["swept"]]
    if fresh:
        best = max(fresh, key=lambda p: p["touches"])
        value = min(1.0, 0.7 + 0.15 * (best["touches"] - 2))
        return Check("liquidity_pool", round(value, 3), w,
                     f"неснятый пул ${best['level']:.2f}, касаний {best['touches']}")

    best = max(near, key=lambda p: p["touches"])
    return Check("liquidity_pool", 0.25, w,
                 f"пул ${best['level']:.2f} уже снят — магнит отработан")


# ─────────────────────────────────────────────────────────────────────────────
#  C. Дельта на уровне
# ─────────────────────────────────────────────────────────────────────────────

def check_delta(zone, profile: VolumeProfile | None, price: float) -> Check:
    """
    Согласуется ли направление агрессии с ролью зоны.

    Под ценой зона работает как поддержка — там должны были покупать, дельта
    положительная. Над ценой это сопротивление — там продавали, дельта
    отрицательная. Совпадение знака означает, что уровень держали реальными
    сделками, а не просто фитилём.

    Требует источника, различающего агрессора (тики). На свечном профиле
    возвращаем нейтраль, а не выдумываем знак: аппроксимация дельты по
    close-open даёт слишком много ложных срабатываний, чтобы на ней что-то
    строить.
    """
    w = config.CONFIRM_WEIGHT_DELTA

    if profile is None:
        return Check("delta", 0.5, w, "профиля нет — нейтрально")

    delta = profile.delta_in_range(zone.bottom, zone.top)
    if delta is None:
        return Check("delta", 0.5, w, "источник не различает агрессора — нейтрально")

    volume = profile.volume_in_range(zone.bottom, zone.top)
    if volume <= 0:
        return Check("delta", 0.5, w, "объёма на уровне нет — нейтрально")

    skew = delta / volume                    # −1..+1
    is_support = zone.price < price
    aligned = skew if is_support else -skew  # ожидаемый знак приводим к «+»

    value = float(np.clip(0.5 + aligned, 0.0, 1.0))
    role = "поддержка" if is_support else "сопротивление"
    sign = "покупали" if skew > 0 else "продавали"
    return Check("delta", round(value, 3), w,
                 f"{role}, перекос {skew:+.0%} ({sign})")


# ─────────────────────────────────────────────────────────────────────────────
#  D. Свежесть
# ─────────────────────────────────────────────────────────────────────────────

def check_freshness(zone, data: dict[str, pd.DataFrame]) -> Check:
    """
    Сколько раз цена уже съела уровень.

    Каждое касание расходует лимитные заявки, стоявшие на уровне. Первое
    касание встречает полную книгу, третье — остатки. Считаем по H4:
    касание = свеча, чей диапазон задел зону, при этом предыдущая свеча её
    не задевала (иначе одна консолидация даст десяток «касаний»).
    """
    w = config.CONFIRM_WEIGHT_FRESHNESS

    df = data.get("H4")
    if df is None or df.empty:
        return Check("freshness", 0.5, w, "нет H4 — нейтрально")

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    touching = (highs >= zone.bottom) & (lows <= zone.top)

    # Считаем только входы в зону, а не каждую свечу внутри неё.
    entries = int(np.sum(touching[1:] & ~touching[:-1])) + int(touching[0])

    ladder = {0: 1.0, 1: 0.75, 2: 0.45, 3: 0.25}
    value = ladder.get(entries, 0.1)
    return Check("freshness", value, w, f"подходов к зоне: {entries}")


# ─────────────────────────────────────────────────────────────────────────────
#  Сборка
# ─────────────────────────────────────────────────────────────────────────────

def confirm_zone(zone, data: dict[str, pd.DataFrame],
                 profile: VolumeProfile | None,
                 pools: list[dict],
                 price: float) -> ConfirmationReport:
    """Прогоняет все четыре проверки по одной зоне."""
    checks = [
        check_volume_node(zone, profile),
        check_liquidity_pool(zone, pools),
        check_delta(zone, profile, price),
        check_freshness(zone, data),
    ]

    total_weight = sum(c.weight for c in checks) or 1.0
    score = sum(c.contribution for c in checks) / total_weight

    if score >= config.CONFIRM_LIVE_THRESHOLD:
        verdict = "LIVE"
    elif score >= config.CONFIRM_DEAD_THRESHOLD:
        verdict = "WATCH"
    else:
        verdict = "DEAD"

    return ConfirmationReport(
        score=round(score, 3),
        verdict=verdict,
        checks=checks,
        source=profile.source if profile else "none",
    )


def confirm_zones(zones: list, data: dict[str, pd.DataFrame],
                  profile: VolumeProfile | None = None) -> list:
    """
    Главная точка входа: аннотирует зоны подтверждением.

    Возвращает список зон — тот же, отфильтрованный или переупорядоченный,
    в зависимости от `CONFIRMATION_MODE`. В любом режиме, кроме `off`, у
    каждой зоны появляется поле `confirmation` с полным разбором проверок:
    метрику должно быть видно целиком, иначе её невозможно калибровать.
    """
    mode = config.CONFIRMATION_MODE
    if mode == "off" or not zones:
        return zones

    if profile is None:
        from liquidity_source import build_liquidity_profile
        profile = build_liquidity_profile(data)

    df_h4 = data.get("H4")
    pools = find_liquidity_pools(df_h4) if df_h4 is not None else []

    price = float(df_h4["close"].iloc[-1]) if df_h4 is not None and not df_h4.empty else 0.0

    for zone in zones:
        report = confirm_zone(zone, data, profile, pools, price)
        zone.confirmation = report.to_dict()
        zone.confirm_score = report.score
        zone.confirm_verdict = report.verdict
        if config.CONFIRMATION_IN_LABEL:
            zone.label_suffix = f"{zone.label_suffix}{report.badge}"

    _print_report(zones, profile, pools)

    if mode == "filter":
        kept = [z for z in zones if z.confirm_verdict != "DEAD"]
        if not kept:
            # Полная зачистка означает, что порог не откалиброван под этот
            # рынок. Отдать пустой график хуже, чем отдать неподтверждённые
            # зоны, поэтому возвращаем исходный список.
            print("[confirmation] все зоны DEAD — фильтр не применён, порог требует калибровки")
            return zones
        print(f"[confirmation] отфильтровано: {len(zones)} → {len(kept)}")
        return kept

    if mode == "rerank":
        return sorted(zones, key=lambda z: z.score * (0.5 + z.confirm_score), reverse=True)

    return zones


def _print_report(zones: list, profile: VolumeProfile | None, pools: list[dict]) -> None:
    """Разбор в консоль — без него метрику невозможно откалибровать."""
    print()
    print("─" * 78)
    print("  ПОДТВЕРЖДЕНИЕ ЗОН")
    print("─" * 78)

    if profile is not None:
        val, vah = profile.value_area()
        nodes = profile.nodes(config.HVN_RATIO, config.LVN_RATIO)
        print(f"  Источник : {profile.source}")
        print(f"  POC      : ${profile.poc:.2f}   Value Area: ${val:.2f} — ${vah:.2f}")
        print(f"  Узлы     : HVN {len(nodes['hvn'])}, LVN {len(nodes['lvn'])}, "
              f"строк {profile.prices.size} по ${profile.row_height:.2f}")
    else:
        print("  Источник : нет — подтверждение нейтральное")

    fresh_pools = sum(1 for p in pools if not p["swept"])
    print(f"  Пулы     : {len(pools)} всего, {fresh_pools} неснятых")
    print("─" * 78)

    for z in sorted(zones, key=lambda z: -z.price):
        mark = {"LIVE": "✓ LIVE ", "WATCH": "~ WATCH", "DEAD": "✗ DEAD "}.get(
            getattr(z, "confirm_verdict", ""), "  ?    ")
        print(f"  ${z.price:>9.2f}  S:{z.score:<3} {mark} {z.confirm_score:.2f}")
        for c in z.confirmation["checks"]:
            print(f"       {c['name']:<15} {c['value']:.2f} ×{c['weight']:.2f}  {c['detail']}")
    print("─" * 78)
    print()
