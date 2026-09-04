"""
liquidity_source.py — Единый источник данных о ликвидности.

Зачем модуль нужен
------------------
Детектор зон (`zone_detector`) находит уровни по фитилям: там, где цена УЖЕ
отбивалась. Это ответ на вопрос «где был интерес», но не на вопрос «есть ли
интерес сейчас». Зона, построенная по теням двухнедельной давности, может
стоять в ценовой пустоте — тогда она не отработает.

Этот модуль отвечает только за сбор сырья для проверки «жива ли зона»:
профиль реально проторгованного объёма, дельта агрессоров, пулы ликвидности.
Решение о том, жива зона или нет, принимает `zone_confirmation`.

Почему не стакан
----------------
Настоящий биржевой стакан (L2 depth) по споту золота ритейл-брокер не отдаёт:
MT5 `market_book_get()` для CFD в подавляющем большинстве случаев возвращает
пустоту либо синтетику самого брокера. Функция `probe_dom()` ниже проверяет
это честно и однозначно — не угадывая, а спрашивая терминал.

Даже если бы стакан был, для зоны в 300+ пипсов от цены он бесполезен: лимиты
так далеко никто не держит, а те, что стоят, снимаются до подхода цены.
Настоящее подтверждение уровня даёт не книга заявок, а история проторговки:
где реально прошёл объём и где остались неснятые скопления стопов.

Цепочка источников (сверху вниз, первый доступный выигрывает)
-------------------------------------------------------------
  1. MT5 tick history  — реальные тики брокера, `copy_ticks_range`.
     Лучший источник: настоящая цена сделок и настоящий их поток.
  2. MT4 EA tick buffer — tick_buffer.csv от SmartZonesCollector.
  3. Bar-derived profile — распределение tick_volume свечи по её диапазону.
     Аппроксимация, но работает всегда и без внешних зависимостей.

Binance сознательно исключён: XAUUSDT недоступен из РФ (HTTP 451
«restricted location»), то есть у целевого пользователя источник мёртв.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import config


# ─────────────────────────────────────────────────────────────────────────────
#  Профиль объёма
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VolumeProfile:
    """
    Распределение объёма по цене.

    В отличие от свечного графика (объём по времени) профиль отвечает на
    вопрос «на каких ценах реально торговали». Плотные строки профиля (HVN)
    — это узлы ликвидности, разрежённые (LVN) — пустоты, которые цена
    проскакивает без сопротивления.
    """

    prices: np.ndarray          # центр каждой строки профиля
    volumes: np.ndarray         # объём в строке
    row_height: float           # высота строки в долларах
    source: str                 # "mt5_ticks" | "mt4_ticks" | "bars"
    buy_volumes: np.ndarray | None = None    # если источник различает агрессора
    sell_volumes: np.ndarray | None = None

    # ── Производные характеристики ──────────────────────────────────────────

    @property
    def total_volume(self) -> float:
        return float(self.volumes.sum())

    @property
    def poc(self) -> float:
        """Point of Control — цена с максимальным объёмом."""
        if self.volumes.size == 0:
            return float("nan")
        return float(self.prices[int(np.argmax(self.volumes))])

    @property
    def fair_share_volume(self) -> float:
        """
        Сколько объёма пришлось бы на строку, будь он распределён равномерно.

        Это база для сравнения плотности: строка «нормальна», если держит
        свою справедливую долю от общего объёма.

        Медиана здесь не годится, хотя интуитивно кажется уместнее. Профиль
        сильно перекошен: большая часть строк — это хвосты, куда цена
        заглядывала на минуты и оставила крохи объёма. Медиана садится на
        такую крошку, и тогда любой обычный уровень выглядит узлом в тридцать
        раз плотнее нормы, а настоящая пустота — «средней». Проверено на
        синтетике с заранее известной структурой: медиана давала LVN ×0.96
        вместо ×0.20, то есть не отличала пустоту от нормы вообще.
        """
        rows = int(self.volumes.size)
        if rows == 0:
            return 0.0
        return float(self.volumes.sum() / rows)

    def value_area(self, coverage: float = 0.70) -> tuple[float, float]:
        """
        Value Area — диапазон вокруг POC, вмещающий `coverage` объёма.
        Возвращает (VAL, VAH). Классический расчёт: расширяемся от POC в ту
        сторону, где следующая строка толще.
        """
        if self.volumes.size == 0:
            return (float("nan"), float("nan"))

        target = self.total_volume * coverage
        poc_idx = int(np.argmax(self.volumes))
        lo = hi = poc_idx
        acc = float(self.volumes[poc_idx])

        while acc < target and (lo > 0 or hi < self.volumes.size - 1):
            below = float(self.volumes[lo - 1]) if lo > 0 else -1.0
            above = float(self.volumes[hi + 1]) if hi < self.volumes.size - 1 else -1.0
            if above >= below:
                hi += 1
                acc += max(above, 0.0)
            else:
                lo -= 1
                acc += max(below, 0.0)

        return (float(self.prices[lo]), float(self.prices[hi]))

    def volume_in_range(self, bottom: float, top: float) -> float:
        """Суммарный объём в ценовом диапазоне."""
        if self.prices.size == 0:
            return 0.0
        mask = (self.prices >= bottom) & (self.prices <= top)
        return float(self.volumes[mask].sum())

    def density_ratio(self, bottom: float, top: float) -> float:
        """
        Во сколько раз объём в диапазоне превышает свою справедливую долю.

        >1 — узел ликвидности (там торговали активнее, чем «в среднем по
             диапазону»), цене есть обо что опереться;
        <1 — разрежение, цена проходила это место транзитом.

        Делим на число строк в диапазоне, иначе широкая зона выигрывала бы у
        узкой просто за счёт размера, а не за счёт плотности.
        """
        base = self.fair_share_volume
        if base <= 0 or self.prices.size == 0:
            return 0.0

        mask = (self.prices >= bottom) & (self.prices <= top)
        rows = int(mask.sum())
        if rows == 0:
            return 0.0

        return float(self.volumes[mask].sum() / rows / base)

    def delta_in_range(self, bottom: float, top: float) -> float | None:
        """
        Чистая дельта (агрессивные покупки минус продажи) в диапазоне.
        None, если источник не различает агрессора.
        """
        if self.buy_volumes is None or self.sell_volumes is None:
            return None
        mask = (self.prices >= bottom) & (self.prices <= top)
        return float(self.buy_volumes[mask].sum() - self.sell_volumes[mask].sum())

    def nodes(self, hvn_ratio: float = 1.5, lvn_ratio: float = 0.5) -> dict:
        """Списки цен HVN и LVN — для отладки и визуализации."""
        base = self.fair_share_volume
        if base <= 0:
            return {"hvn": [], "lvn": []}
        rel = self.volumes / base
        return {
            "hvn": [round(float(p), 2) for p in self.prices[rel >= hvn_ratio]],
            "lvn": [round(float(p), 2) for p in self.prices[(rel > 0) & (rel <= lvn_ratio)]],
        }


def _row_height(price_range: float) -> float:
    """
    Высота строки профиля.

    Слишком мелкая строка — профиль рассыпается в шум, каждая строка почти
    пустая и медиана теряет смысл. Слишком крупная — узлы и пустоты
    смазываются в одну кашу. Держим порядка 400 строк на диапазон и
    ограничиваем снизу шагом цены инструмента.
    """
    target_rows = 400
    raw = price_range / target_rows if price_range > 0 else config.SYMBOL_POINT
    return max(raw, config.SYMBOL_POINT * 10)


def profile_from_ticks(ticks: pd.DataFrame, source: str = "mt5_ticks") -> VolumeProfile | None:
    """
    Профиль по реальным тикам.

    Ожидает колонки: `price` (обязательно), `volume` (опционально),
    `direction` (опционально: "BUY"/"SELL" — агрессор).

    Классификация агрессора по правилу тика: сделка по ask — покупка,
    по bid — продажа. Если брокер не отдаёт last/flags, используем
    сравнение с предыдущей ценой (tick rule).
    """
    if ticks is None or ticks.empty or "price" not in ticks.columns:
        return None

    prices = ticks["price"].to_numpy(dtype=float)
    prices = prices[np.isfinite(prices)]
    if prices.size < 50:
        return None

    volumes = (
        ticks["volume"].to_numpy(dtype=float)
        if "volume" in ticks.columns
        else np.ones_like(prices)
    )
    volumes = volumes[: prices.size]
    volumes = np.where(np.isfinite(volumes) & (volumes > 0), volumes, 1.0)

    lo, hi = float(prices.min()), float(prices.max())
    rh = _row_height(hi - lo)
    edges = np.arange(lo, hi + rh, rh)
    if edges.size < 2:
        return None

    total, _ = np.histogram(prices, bins=edges, weights=volumes)
    centers = (edges[:-1] + edges[1:]) / 2.0

    buy = sell = None
    if "direction" in ticks.columns:
        d = ticks["direction"].astype(str).str.upper().to_numpy()[: prices.size]
        buy, _ = np.histogram(prices[d == "BUY"], bins=edges, weights=volumes[d == "BUY"])
        sell, _ = np.histogram(prices[d == "SELL"], bins=edges, weights=volumes[d == "SELL"])

    return VolumeProfile(
        prices=centers, volumes=total, row_height=rh,
        source=source, buy_volumes=buy, sell_volumes=sell,
    )


def profile_from_bars(df: pd.DataFrame, source: str = "bars") -> VolumeProfile | None:
    """
    Профиль по свечам — запасной вариант, когда тиков нет.

    Объём свечи размазываем равномерно по её диапазону high-low. Это
    заведомо грубее тиков: внутри свечи объём распределён неравномерно и
    жмётся к телу. Но на горизонте в сотни свечей неравномерности взаимно
    гасятся, и крупные узлы проступают верно.

    Ключевое отличие от `tick_volume` по времени: здесь объём привязан к
    ЦЕНЕ, а не к моменту. Именно это нужно для проверки уровня.
    """
    if df is None or df.empty:
        return None

    need = {"high", "low"}
    if not need.issubset(df.columns):
        return None

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)

    if "tick_volume" in df.columns:
        vols = df["tick_volume"].to_numpy(dtype=float)
    elif "volume" in df.columns:
        vols = df["volume"].to_numpy(dtype=float)
    else:
        vols = np.ones_like(highs)
    vols = np.where(np.isfinite(vols) & (vols > 0), vols, 1.0)

    valid = np.isfinite(highs) & np.isfinite(lows) & (highs >= lows)
    highs, lows, vols = highs[valid], lows[valid], vols[valid]
    if highs.size == 0:
        return None

    lo, hi = float(lows.min()), float(highs.max())
    rh = _row_height(hi - lo)
    edges = np.arange(lo, hi + rh, rh)
    if edges.size < 2:
        return None

    centers = (edges[:-1] + edges[1:]) / 2.0
    acc = np.zeros(centers.size, dtype=float)

    # Векторно: для каждой свечи доля её объёма падает в каждую строку,
    # попавшую в диапазон свечи.
    for h, l, v in zip(highs, lows, vols):
        mask = (centers >= l) & (centers <= h)
        n = int(mask.sum())
        if n == 0:
            # Свеча уже строки профиля — кладём всё в ближайшую.
            acc[int(np.abs(centers - (h + l) / 2.0).argmin())] += v
        else:
            acc[mask] += v / n

    return VolumeProfile(prices=centers, volumes=acc, row_height=rh, source=source)


# ─────────────────────────────────────────────────────────────────────────────
#  Тики из MT5
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ticks_mt5(symbol: str | None = None, days: int | None = None) -> pd.DataFrame | None:
    """
    Реальные тики из терминала MT5.

    Тиков много: сутки по золоту — сотни тысяч записей. Поэтому глубину
    держим отдельным параметром (`TICK_HISTORY_DAYS`), а не тянем всю
    историю свечей — иначе запрос уходит в минуты и вешает GUI.

    Агрессор определяется по флагам сделки, если брокер их отдаёт, иначе
    по правилу тика (сравнение с предыдущей ценой).
    """
    symbol = symbol or config.SYMBOL
    days = days or config.TICK_HISTORY_DAYS

    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None

    try:
        if not mt5.initialize():
            return None

        from data_fetcher import resolve_mt5_symbol
        resolved = resolve_mt5_symbol(symbol)
        if not resolved:
            return None

        end = datetime.now()
        start = end - timedelta(days=days)
        raw = mt5.copy_ticks_range(resolved, start, end, mt5.COPY_TICKS_ALL)
        if raw is None or len(raw) == 0:
            return None

        t = pd.DataFrame(raw)

        # Цена сделки: last, если брокер его публикует, иначе середина спреда.
        if "last" in t.columns and (t["last"] > 0).any():
            price = t["last"].where(t["last"] > 0, (t["bid"] + t["ask"]) / 2.0)
        else:
            price = (t["bid"] + t["ask"]) / 2.0
        t["price"] = price

        t["volume"] = (
            t["volume_real"] if "volume_real" in t.columns and (t["volume_real"] > 0).any()
            else t.get("volume", pd.Series(1.0, index=t.index))
        )
        t["volume"] = t["volume"].where(t["volume"] > 0, 1.0)

        t["direction"] = _classify_aggressor(t, mt5)
        return t[["time", "price", "volume", "direction"]]

    except Exception as exc:  # noqa: BLE001 — источник опционален, не роняем пайплайн
        print(f"[liquidity_source] MT5 ticks unavailable: {exc}")
        return None
    finally:
        try:
            mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass


def _classify_aggressor(t: pd.DataFrame, mt5) -> pd.Series:
    """
    Кто был агрессором в сделке.

    Сначала пробуем флаги MT5 (TICK_FLAG_BUY / TICK_FLAG_SELL) — это прямое
    указание терминала. Если брокер флаги не заполняет (частый случай на
    CFD), падаем на правило тика: цена выросла — инициатива у покупателя.
    """
    if "flags" in t.columns:
        try:
            f = t["flags"].to_numpy(dtype=np.int64)
            is_buy = (f & int(mt5.TICK_FLAG_BUY)) != 0
            is_sell = (f & int(mt5.TICK_FLAG_SELL)) != 0
            if is_buy.any() or is_sell.any():
                return pd.Series(
                    np.where(is_buy, "BUY", np.where(is_sell, "SELL", "NEUTRAL")),
                    index=t.index,
                )
        except Exception:  # noqa: BLE001
            pass

    diff = t["price"].diff()
    return pd.Series(
        np.where(diff > 0, "BUY", np.where(diff < 0, "SELL", "NEUTRAL")),
        index=t.index,
    )


def fetch_ticks_mt4() -> pd.DataFrame | None:
    """Тики из буфера MT4 EA — второй источник, если MT5 недоступен."""
    try:
        from tick_reader import get_tick_reader
        reader = get_tick_reader(config.SYMBOL)
        ticks = reader.read_new_ticks() if hasattr(reader, "read_new_ticks") else None
        if not ticks:
            return None
        return pd.DataFrame([
            {"time": t.dt, "price": t.price, "volume": t.volume, "direction": t.direction}
            for t in ticks
        ])
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Стакан: честная проверка, а не предположение
# ─────────────────────────────────────────────────────────────────────────────

def probe_dom(symbol: str | None = None) -> dict:
    """
    Спрашивает у терминала, отдаёт ли брокер стакан по инструменту.

    Возвращает словарь с однозначным ответом. Нужен именно замер, а не
    догадка: у части брокеров DOM по золоту всё же включён, и тогда его
    можно подмешать в подтверждение ближних зон.
    """
    symbol = symbol or config.SYMBOL
    result = {"available": False, "levels": 0, "reason": "", "sample": []}

    try:
        import MetaTrader5 as mt5
    except ImportError:
        result["reason"] = "MetaTrader5 не установлен"
        return result

    try:
        if not mt5.initialize():
            result["reason"] = f"initialize() failed: {mt5.last_error()}"
            return result

        from data_fetcher import resolve_mt5_symbol
        resolved = resolve_mt5_symbol(symbol)
        if not resolved:
            result["reason"] = f"символ {symbol} не найден у брокера"
            return result

        if not mt5.market_book_add(resolved):
            result["reason"] = f"market_book_add отклонён: {mt5.last_error()}"
            return result

        try:
            import time as _t
            _t.sleep(1.0)  # терминалу нужен тик, чтобы наполнить книгу
            book = mt5.market_book_get(resolved)
        finally:
            mt5.market_book_release(resolved)

        if not book:
            result["reason"] = "брокер не публикует стакан по этому инструменту"
            return result

        result["available"] = True
        result["levels"] = len(book)
        result["reason"] = "стакан доступен"
        result["sample"] = [
            {"type": int(b.type), "price": float(b.price), "volume": float(b.volume)}
            for b in book[:10]
        ]
        return result

    except Exception as exc:  # noqa: BLE001
        result["reason"] = f"ошибка запроса: {exc}"
        return result
    finally:
        try:
            mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass


# ─────────────────────────────────────────────────────────────────────────────
#  Главная точка входа
# ─────────────────────────────────────────────────────────────────────────────

def build_liquidity_profile(data: dict[str, pd.DataFrame]) -> VolumeProfile | None:
    """
    Строит профиль объёма лучшим доступным способом.

    Порядок сознательно жёсткий: тики точнее свечей, и если они есть, брать
    аппроксимацию по свечам нет смысла. Возврат `None` означает, что данных
    нет вообще — тогда подтверждение просто не применяется, а зоны остаются
    такими, какими их построил детектор.
    """
    if config.LIQUIDITY_SOURCE in ("auto", "ticks"):
        ticks = fetch_ticks_mt5()
        if ticks is not None and len(ticks) >= config.MIN_TICKS_FOR_PROFILE:
            profile = profile_from_ticks(ticks, source="mt5_ticks")
            if profile is not None:
                print(f"[liquidity_source] профиль по тикам MT5: {len(ticks)} тиков, "
                      f"{profile.prices.size} строк, POC ${profile.poc:.2f}")
                return profile

        ticks = fetch_ticks_mt4()
        if ticks is not None and len(ticks) >= config.MIN_TICKS_FOR_PROFILE:
            profile = profile_from_ticks(ticks, source="mt4_ticks")
            if profile is not None:
                print(f"[liquidity_source] профиль по тикам MT4: {len(ticks)} тиков")
                return profile

    if config.LIQUIDITY_SOURCE == "ticks":
        print("[liquidity_source] тиков нет, а источник жёстко задан как 'ticks' — профиль не построен")
        return None

    # Свечной запасной вариант: берём самый подробный доступный таймфрейм.
    for tf in ("H1", "H4", "D1"):
        df = data.get(tf)
        if df is not None and not df.empty:
            profile = profile_from_bars(df, source=f"bars:{tf}")
            if profile is not None:
                print(f"[liquidity_source] профиль по свечам {tf}: {len(df)} свечей, "
                      f"{profile.prices.size} строк, POC ${profile.poc:.2f}")
                return profile

    print("[liquidity_source] источников ликвидности нет")
    return None
