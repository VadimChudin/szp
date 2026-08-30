"""
l2_validation.py — Валидация зон по стакану (Level 2 / DOM).

Чем этот слой отличается от zone_confirmation
---------------------------------------------
`zone_confirmation` смотрит в ПРОШЛОЕ: профиль проторгованного объёма, пулы
уже стоявших стопов, дельта уже прошедших касаний. Это доказательства того,
что уровень когда-то работал. Этот модуль смотрит в НАСТОЯЩЕЕ: какие лимитные
заявки стоят в стакане прямо сейчас. Стакан — единственное место, где видны
намерения до того, как они стали сделками.

Как и подтверждение, L2 НЕ добавляется в score. Это третье независимое
измерение:
    score        — насколько уровень значим структурно  (история)
    confirmation — работал ли он недавно                (прошлое)
    l2           — стоит ли кто-то на нём заявками      (настоящее)

Откуда берётся стакан
---------------------
MT5 Collector EA подписывается на стакан (MarketBookAdd) и на каждое
изменение (с троттлингом) пишет снапшот в l2_book.json. MT4 стакана не имеет,
поэтому там слой всегда UNAVAILABLE — и это не мягкий нейтралитет, а честное
«данных нет»: в режиме filter такие зоны НЕ отбрасываются.

Ограничения, которые важно понимать
-----------------------------------
1. У многих брокеров XAU/USD — синтетический или пустой стакан. Пустая книга
   даёт UNAVAILABLE, а не нулевой скор: отсутствие данных не улика.
2. Видимая глубина часто покрывает лишь несколько долларов от цены, а зоны
   живут в $20–90. Тогда проверка «стена» возвращает нейтраль, и рабочими
   остаются перекос книги и стойкость стен у краёв.
3. Стакан — самый подвижный источник: заявки снимают (спуфинг). Поэтому
   проверка C сравнивает снапшот с предыдущим: стена, которую сняли при
   подходе цены, штрафуется, а не засчитывается.

Три проверки
------------
  A. Стена на зоне   (вес .45) — крупная лимитная заявка в диапазоне зоны
                     на правильной стороне (bid для поддержки, ask для
                     сопротивления) относительно медианного уровня книги.
  B. Перекос книги   (вес .30) — суммарный перевес bid/ask в окне
                     ±L2_IMBALANCE_REACH_USD от mid; знак должен совпадать
                     с ролью зоны.
  C. Стойкость стены (вес .25) — стена из прошлого снапшота всё ещё стоит
                     (держится → бонус) или её сняли (pulled → штраф,
                     это спуфинг-фильтр).

Режимы (config.L2_MODE): off | annotate (умолчание) | filter | rerank.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import config
import paths


# Прошлый снапшот стакана — для проверки стойкости стен (спуфинг-фильтр).
# Живёт рядом с zones_output.json, перезаписывается после каждой валидации.
def _prev_book_path() -> Path:
    return paths.DATA_BRIDGE_DIR / "l2_book_prev.json"


# ─────────────────────────────────────────────────────────────────────────────
#  Стакан
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Book:
    """Снапшот стакана: bids/asks — списки (цена, объём), объём > 0."""
    bids: list[tuple[float, float]] = field(default_factory=list)
    asks: list[tuple[float, float]] = field(default_factory=list)
    timestamp: datetime | None = None
    source: str = "none"
    # True, если книга из внешнего источника (PAXG-прокси), а не из DOM
    # брокера. Отчёт помечает такие проверки, чтобы прокси не приняли за
    # брокерский стакан.
    proxy: bool = False

    @property
    def mid(self) -> float | None:
        if self.bids and self.asks:
            return (max(p for p, _ in self.bids) + min(p for p, _ in self.asks)) / 2
        return None

    @property
    def is_empty(self) -> bool:
        return not self.bids and not self.asks

    def age_sec(self) -> float | None:
        if self.timestamp is None:
            return None
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()

    def side_volume_in_range(self, side: str, lo: float, hi: float) -> float:
        """Суммарный объём заявок стороны ('bids'/'asks') в ценовом диапазоне."""
        levels = self.bids if side == "bids" else self.asks
        return sum(v for p, v in levels if lo <= p <= hi)

    def median_level_volume(self, side: str) -> float:
        """Медианный объём одного уровня стороны — базис для оценки стены."""
        levels = self.bids if side == "bids" else self.asks
        if not levels:
            return 0.0
        vols = sorted(v for _, v in levels)
        n = len(vols)
        return vols[n // 2] if n % 2 else (vols[n // 2 - 1] + vols[n // 2]) / 2


def _parse_book(raw: dict, source: str) -> Book:
    def side(key):
        out = []
        for lvl in raw.get(key) or []:
            try:
                p, v = float(lvl["price"]), float(lvl["volume"])
            except (KeyError, TypeError, ValueError):
                continue
            if v > 0:
                out.append((p, v))
        return out

    ts = None
    raw_ts = raw.get("timestamp")
    if raw_ts:
        try:
            ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            ts = None
    return Book(bids=side("bids"), asks=side("asks"), timestamp=ts, source=source)


def _candidate_paths() -> list[Path]:
    """Где искать l2_book.json, в порядке приоритета."""
    cands: list[Path] = []
    if config.L2_BOOK_PATH:
        cands.append(Path(config.L2_BOOK_PATH))
    cands.append(paths.DATA_BRIDGE_DIR / "l2_book.json")
    try:
        # EA пишет снапшот с флагом FILE_COMMON — как и все остальные файлы
        # обмена (тики, OHLCV, флаги), чтобы Python не искал терминалы.
        common = paths.find_mt_common_files()
        if common is not None:
            cands.append(common / "l2_book.json")
    except Exception:
        pass  # поиск терминалов — опционален, его отказ не должен ронять слой
    return cands


def load_book() -> Book | None:
    """
    Читает самый свежий доступный снапшот стакана.

    None — книги нет нигде. Book с is_empty или протухший по L2_MAX_AGE_SEC —
    вернётся, и вызывающий код сам решит: оба случая дают вердикт UNAVAILABLE,
    но с разной причиной в detail.
    """
    best: Book | None = None
    for path in _candidate_paths():
        try:
            if not path.is_file():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        book = _parse_book(raw, source=str(path))
        if best is None:
            best = book
        elif book.timestamp and (best.timestamp is None
                                 or book.timestamp > best.timestamp):
            best = book
    return best


def _load_prev_book() -> Book | None:
    try:
        path = _prev_book_path()
        if not path.is_file():
            return None
        return _parse_book(json.loads(path.read_text(encoding="utf-8")),
                           source=str(path))
    except (OSError, ValueError):
        return None


def _rotate_book(book: Book) -> None:
    """Текущий снапшот становится предыдущим для следующего пересчёта."""
    if book is None or book.is_empty or book.source == "none":
        return
    try:
        src = Path(book.source)
        if src.is_file() and src.resolve() != _prev_book_path().resolve():
            shutil.copyfile(src, _prev_book_path())
    except OSError:
        pass  # спуфинг-фильтр деградирует до нейтрали — не критично


# ─────────────────────────────────────────────────────────────────────────────
#  Результат
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class L2Check:
    """Одна проверка: оценка 0..1 плюс человекочитаемая причина."""
    name: str
    value: float
    weight: float
    detail: str = ""

    @property
    def contribution(self) -> float:
        return self.value * self.weight


@dataclass
class L2Report:
    """Итог L2-валидации по одной зоне."""
    score: float = 0.5
    verdict: str = "UNAVAILABLE"          # LIVE | WATCH | DEAD | UNAVAILABLE
    checks: list[L2Check] = field(default_factory=list)
    source: str = "none"
    reason: str = ""                      # почему UNAVAILABLE, если так

    def to_dict(self) -> dict:
        # ВНИМАНИЕ: в этом словаре не должно быть ключа "price" ни на одном
        # уровне вложенности — индикатор MT4/MT5 парсит zones_output.json
        # наивно, по ключу "price", и лишний ключ породит фантомную зону
        # (та же ловушка, из-за которой из экспорта вырезали wick_points).
        return {
            "score": round(self.score, 3),
            "verdict": self.verdict,
            "source": self.source,
            "reason": self.reason,
            "checks": [asdict(c) | {"contribution": round(c.contribution, 3)}
                       for c in self.checks],
        }

    @property
    def badge(self) -> str:
        """Короткая метка для подписи на графике."""
        if self.verdict == "UNAVAILABLE":
            return ""
        mark = {"LIVE": "✓", "WATCH": "~", "DEAD": "✗"}.get(self.verdict, "")
        return f" L2{mark}{self.score:.2f}"


# ─────────────────────────────────────────────────────────────────────────────
#  A. Стена на зоне
# ─────────────────────────────────────────────────────────────────────────────

def check_wall(zone, book: Book, price: float) -> L2Check:
    """
    Стоит ли в диапазоне зоны крупная лимитная заявка на правильной стороне.

    Поддержка держится на bid-стенах, сопротивление — на ask-стенах. «Крупная»
    — относительно медианного уровня своей стороны книги: абсолютные объёмы
    у брокеров различаются на порядки, поэтому нормируем на саму книгу.

    Стакан покрывает лишь несколько долларов от цены, а зоны стоят дальше —
    тогда в диапазоне зоны просто нет уровней книги. Это НЕ ноль: возвращаем
    нейтраль с явной причиной, чтобы отсутствие покрытия не путали со
    слабостью зоны.
    """
    w = config.L2_WEIGHT_WALL
    is_support = zone.price < price
    side = "bids" if is_support else "asks"

    median = book.median_level_volume(side)
    if median <= 0:
        return L2Check("wall", 0.5, w, f"сторона {side} пуста — нейтрально")

    side_vol = book.side_volume_in_range(side, zone.bottom, zone.top)
    if side_vol <= 0:
        return L2Check("wall", 0.5, w,
                       "стакан не достаёт до зоны — нейтрально")

    # Сколько уровней книги попало в диапазон зоны — стена оценивается на
    # один уровень, иначе широкая зона выигрывала бы просто за счёт ширины.
    levels = book.bids if side == "bids" else book.asks
    in_range = [(p, v) for p, v in levels if zone.bottom <= p <= zone.top]
    peak = max(v for _, v in in_range)
    ratio = peak / median

    strong, weak = config.L2_WALL_STRONG, config.L2_WALL_WEAK
    value = min(1.0, max(0.0, (ratio - weak) / (strong - weak)))

    role = "bid" if is_support else "ask"
    if ratio >= strong:
        detail = f"{role}-стена ×{ratio:.1f} от медианы — на зоне стоят"
    elif ratio <= weak:
        detail = f"{role} на зоне обычный (×{ratio:.1f}) — стены нет"
    else:
        detail = f"{role} на зоне повышен (×{ratio:.1f})"
    return L2Check("wall", round(value, 3), w, detail)


# ─────────────────────────────────────────────────────────────────────────────
#  B. Перекос книги
# ─────────────────────────────────────────────────────────────────────────────

def check_imbalance(zone, book: Book, price: float) -> L2Check:
    """
    Совпадает ли перевес заявок у цены с ролью зоны.

    В окне ±L2_IMBALANCE_REACH_USD от mid считаем суммарные объёмы обеих
    сторон. У поддержки книга должна быть тяжелее снизу (bid > ask): лимитные
    покупатели реально стоят под ценой, а не наоборот. Это контекстная
    проверка — одна она зону не убеждает, но конфликт знаков (поддержка при
    тяжёлой ask-стороне) честно штрафует.
    """
    w = config.L2_WEIGHT_IMBALANCE

    mid = book.mid
    if mid is None:
        return L2Check("imbalance", 0.5, w, "книга односторонняя — нейтрально")

    reach = config.L2_IMBALANCE_REACH_USD
    bid_vol = book.side_volume_in_range("bids", mid - reach, mid + reach)
    ask_vol = book.side_volume_in_range("asks", mid - reach, mid + reach)
    total = bid_vol + ask_vol
    if total <= 0:
        return L2Check("imbalance", 0.5, w, "у цены заявок нет — нейтрально")

    skew = (bid_vol - ask_vol) / total        # −1..+1
    is_support = zone.price < price
    aligned = skew if is_support else -skew   # ожидаемый знак приводим к «+»
    value = min(1.0, max(0.0, 0.5 + aligned))

    role = "поддержка" if is_support else "сопротивление"
    heavier = "bid" if skew > 0 else "ask"
    return L2Check("imbalance", round(value, 3), w,
                   f"{role}, книга тяжелее по {heavier} ({skew:+.0%})")


# ─────────────────────────────────────────────────────────────────────────────
#  C. Стойкость стены (спуфинг-фильтр)
# ─────────────────────────────────────────────────────────────────────────────

def check_persistence(zone, book: Book, prev: Book | None,
                      price: float) -> L2Check:
    """
    Держится ли стена между снапшотами.

    Спуфинг — главный способ обмануть по стакану: выставить огромную заявку,
    а при подходе цены снять. Один снапшот спуфинг не отличает, поэтому
    сравниваем с прошлым пересчётом:
      стена была и осталась (объём ≥ половины прошлого) → 1.0, заявка честная
      стена была и исчезла                            → 0.1, вероятный спуфинг
      стены не было и нет / нет прошлого снапшота     → 0.5, нейтрально
    """
    w = config.L2_WEIGHT_PERSISTENCE

    if prev is None or prev.is_empty:
        return L2Check("persistence", 0.5, w, "прошлого снапшота нет — нейтрально")

    is_support = zone.price < price
    side = "bids" if is_support else "asks"
    median = prev.median_level_volume(side)
    if median <= 0:
        return L2Check("persistence", 0.5, w, "в прошлой книге сторона пуста — нейтрально")

    prev_vol = prev.side_volume_in_range(side, zone.bottom, zone.top)
    if prev_vol < median * config.L2_WALL_STRONG:
        return L2Check("persistence", 0.5, w, "стены на зоне не было — нейтрально")

    cur_vol = book.side_volume_in_range(side, zone.bottom, zone.top)
    if cur_vol >= prev_vol * 0.5:
        return L2Check("persistence", 1.0, w,
                       "стена держится между снапшотами — заявка честная")
    return L2Check("persistence", 0.1, w,
                   f"стену сняли (было {prev_vol:.0f}, стало {cur_vol:.0f}) — "
                   "вероятный спуфинг")


# ─────────────────────────────────────────────────────────────────────────────
#  Сборка
# ─────────────────────────────────────────────────────────────────────────────

def validate_zone_l2(zone, book: Book, prev: Book | None,
                     price: float) -> L2Report:
    """Прогоняет все три проверки по одной зоне."""
    checks = [
        check_wall(zone, book, price),
        check_imbalance(zone, book, price),
        check_persistence(zone, book, prev, price),
    ]

    total_weight = sum(c.weight for c in checks) or 1.0
    score = sum(c.contribution for c in checks) / total_weight

    if score >= config.L2_LIVE_THRESHOLD:
        verdict = "LIVE"
    elif score >= config.L2_DEAD_THRESHOLD:
        verdict = "WATCH"
    else:
        verdict = "DEAD"

    return L2Report(score=round(score, 3), verdict=verdict,
                    checks=checks, source=book.source)


def _unavailable_report(reason: str, source: str = "none") -> L2Report:
    return L2Report(score=0.5, verdict="UNAVAILABLE", source=source,
                    reason=reason)


def validate_zones_l2(zones: list, price: float | None = None) -> list:
    """
    Главная точка входа: аннотирует зоны результатом L2-валидации.

    Возвращает список зон — тот же, отфильтрованный или переупорядоченный,
    в зависимости от `L2_MODE`. В любом режиме, кроме off, у каждой зоны
    появляются поля `l2` / `l2_score` / `l2_verdict`.

    Принцип «отсутствие стакана — не приговор»: UNAVAILABLE-зоны не
    отбрасываются даже в режиме filter. Иначе у брокера с пустым стаканом
    или на MT4 график просто опустел бы.
    """
    mode = config.L2_MODE
    if mode == "off" or not zones:
        return zones

    book = load_book()
    if price is None:
        price = book.mid if book and book.mid else None

    broker_reason = None
    if book is None:
        broker_reason = "l2_book.json не найден — EA не пишет стакан"
    elif book.is_empty:
        broker_reason = "стакан пуст — брокер не транслирует DOM"
    else:
        age = book.age_sec()
        if age is not None and age > config.L2_MAX_AGE_SEC:
            broker_reason = f"снапшоту {age:.0f}с — протух"

    # Фолбэк на внешний прокси-стакан (PAXG): своего DOM нет — не значит,
    # что стакана нет вообще. Книга калибруется сдвигом к цене брокера и
    # помечается proxy. Без цены калибровка невозможна — не врём по ценам.
    if broker_reason is not None:
        book = None
        if config.L2_EXTERNAL_SOURCE != "off" and price is not None:
            try:
                from l2_external import fetch_external_book
                book = fetch_external_book(price)
            except Exception as e:
                print(f"[l2] внешний стакан не удался: {e}")
        if book is None:
            report = _unavailable_report(broker_reason)
            for zone in zones:
                zone.l2, zone.l2_score, zone.l2_verdict = (
                    report.to_dict(), report.score, report.verdict)
            print(f"[l2] {broker_reason} — слой в UNAVAILABLE")
            return zones

    if price is None:
        # Без цены не определить сторону зоны — валидировать нечего.
        report = _unavailable_report("нет текущей цены", source=book.source)
        for zone in zones:
            zone.l2, zone.l2_score, zone.l2_verdict = (
                report.to_dict(), report.score, report.verdict)
        return zones

    prev = _load_prev_book()
    for zone in zones:
        report = validate_zone_l2(zone, book, prev, price)
        zone.l2 = report.to_dict()
        zone.l2_score = report.score
        zone.l2_verdict = report.verdict
        if config.L2_IN_LABEL:
            zone.label_suffix = f"{zone.label_suffix}{report.badge}"

    _rotate_book(book)
    _print_report(zones, book, price)

    if mode == "filter":
        kept = [z for z in zones if z.l2_verdict != "DEAD"]
        if not kept:
            # Полная зачистка означает, что порог не откалиброван или стакан
            # врёт. Пустой график хуже непроверенных зон — отдаём как было.
            print("[l2] все зоны DEAD — фильтр не применён, порог требует калибровки")
            return zones
        print(f"[l2] отфильтровано: {len(zones)} → {len(kept)}")
        return kept

    if mode == "rerank":
        return sorted(zones, key=lambda z: z.score * (0.5 + z.l2_score),
                      reverse=True)

    return zones


def _print_report(zones: list, book: Book, price: float) -> None:
    """Разбор в консоль — без него слой невозможно откалибровать."""
    print()
    print("─" * 78)
    print("  L2-ВАЛИДАЦИЯ (СТАКАН)")
    print("─" * 78)
    print(f"  Источник : {book.source}")
    print(f"  Глубина  : {len(book.bids)} bid / {len(book.asks)} ask, "
          f"mid ${book.mid:.2f}" if book.mid else "  книга односторонняя")
    print("─" * 78)
    for z in sorted(zones, key=lambda z: -z.price):
        mark = {"LIVE": "✓ LIVE ", "WATCH": "~ WATCH", "DEAD": "✗ DEAD "}.get(
            getattr(z, "l2_verdict", ""), "  ?    ")
        print(f"  ${z.price:>9.2f}  S:{z.score:<3} {mark} {z.l2_score:.2f}")
        for c in z.l2.get("checks", []):
            print(f"       {c['name']:<12} {c['value']:.2f} ×{c['weight']:.2f}  {c['detail']}")
    print("─" * 78)
    print()
