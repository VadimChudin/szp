"""
annotator.py — ИИ-слой: подписи и ранжирование уже посчитанных зон.

Что делает
----------
Раз в закрытую свечу H4 берёт готовые зоны, отдаёт модели их цифры и получает
обратно человеческую формулировку и порядок важности. Записывает результат в
поля ai_verdict / ai_note / ai_rank.

Что НЕ делает
-------------
Не считает цену зоны, не меняет ширину, окно показа, вердикт confirm_zones и
уровень SL. Геометрия принадлежит коду: канон «одинаковые зоны у всех
брокеров» строится на детекторе и эталоне Dukascopy, а модель недетерминирована
и разошлась бы между запусками.

Воронка
-------
В модель уходят не все зоны, а до AI_MAX_CANDIDATES кандидатов — включая те,
что код отбросил. Иначе модель просто соглашается с кодом; пусть спорит:
«зону 4812 срезали по score, но там три касания и покупатели в зоне».

Отказ безопасен
---------------
Нет ключа, нет модели, таймаут, ответ не по схеме — функция возвращает зоны
неизменными. Ни одна ветка не бросает исключение наружу.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import config

GRAMMAR_FILE = Path(__file__).resolve().parent / "zone_note.gbnf"

VERDICTS = ("LIVE", "WATCH", "SKIP")

SYSTEM_PROMPT = """Ты — ассистент трейдера в индикаторе Smart Zones Pro.
Тебе дают уже посчитанные зоны поддержки и сопротивления по золоту (XAU/USD).

Твоя работа:
1. Оценить, стоит ли смотреть на каждую зону сегодня: LIVE, WATCH или SKIP.
2. Расставить порядок важности: rank 1 — самая интересная зона.
3. Коротко объяснить причину, опираясь ТОЛЬКО на приведённые цифры.

Строгие запреты:
- не придумывай цены, уровни, проценты и даты, которых нет во входных данных;
- не давай торговых рекомендаций и не называй точки входа;
- объяснение — одна фраза до 180 символов на русском языке.

Что означают поля:
- score: структурная сила уровня (сколько таймфреймов, объём, касания);
- confirm: вердикт проверки живости уровня по текущему рынку;
- reaction: как цена вела себя у зоны в последний раз;
- dist_atr: удалённость от текущей цены в единицах ATR;
- analog: историческая статистика по этой полосе цен;
  significant=false означает «не лучше случайного уровня» — не выдавай такую
  статистику за подтверждение;
- dropped=true: код убрал зону с графика, скажи, согласен ли ты.

Ответ — только массив JSON, по одному объекту на каждую зону из входа."""


@dataclass
class Annotation:
    zone_id: int
    verdict: str
    rank: int
    why: str


def grammar() -> str | None:
    try:
        return GRAMMAR_FILE.read_text(encoding="utf-8")
    except OSError:
        return None


def _zone_features(zone, index: int, price: float, atr: float,
                   dropped: bool) -> dict:
    """Только те цифры, на которые человек реально смотрит глазами.

    Сырьё (wick_points, тики) осознанно не отдаём: модель утонет в шуме, а
    качество ранжирования упадёт.
    """
    features: dict = {
        "zone_id": index,
        "price": round(float(getattr(zone, "price", 0.0)), 2),
        "side": "выше цены" if float(getattr(zone, "price", 0)) > price
                else "ниже цены",
        "score": int(getattr(zone, "score", 0) or 0),
        "sources": "+".join(sorted(set(getattr(zone, "sources", []) or []))),
        "touches": int(getattr(zone, "touch_count", 0) or 0),
        "tests": int(getattr(zone, "test_count", 0) or 0),
        "big_player": bool(getattr(zone, "has_big_player", False)),
        "round_level": bool(getattr(zone, "is_round_level", False)),
        "state": str(getattr(zone, "state", "") or ""),
        "confirm": str(getattr(zone, "confirm_verdict", "") or "нет данных"),
        "confirm_score": round(float(getattr(zone, "confirm_score", 0.0) or 0), 2),
        "dropped": dropped,
    }
    if atr > 0:
        distance = abs(float(getattr(zone, "price", 0.0)) - price)
        features["dist_atr"] = round(distance / atr, 2)
    reaction = getattr(zone, "reaction_type", "") or ""
    if reaction:
        features["reaction"] = str(reaction)
    return features


def build_packet(zones: list, data: dict, *, dropped: list | None = None,
                 with_analogs: bool = True) -> dict:
    """Готовит вход для модели: цена, ATR и список зон-кандидатов."""
    from persistent_zones import _atr_h1, get_current_price

    price = get_current_price(data) or 0.0
    atr = _atr_h1(data, int(getattr(config, "ATR_PERIOD", 14)))

    limit = int(getattr(config, "AI_MAX_CANDIDATES", 20))
    candidates = [(zone, False) for zone in zones]
    for zone in (dropped or []):
        candidates.append((zone, True))
    candidates = candidates[:limit]

    analog_budget = int(getattr(config, "AI_ANALOG_CALLS", 3))
    items = []
    for index, (zone, is_dropped) in enumerate(candidates):
        features = _zone_features(zone, index, price, atr, is_dropped)
        if with_analogs and analog_budget > 0:
            try:
                from ai import tools
                report = tools.historical_analog(
                    float(getattr(zone, "price", 0.0)),
                    float(getattr(zone, "width", 0.0) or config.ZONE_WIDTH),
                    data)
                features["analog"] = {
                    "touches": report.touches,
                    "bounce_rate": round(report.bounce_rate, 2),
                    "baseline_rate": round(report.baseline_rate, 2),
                    "significant": report.significant,
                    "note": report.note,
                }
                analog_budget -= 1
            except Exception as exc:
                features["analog"] = {"error": str(exc)}
        items.append(features)

    return {
        "current_price": round(float(price), 2),
        "atr_h1": round(float(atr), 2),
        "zones": items,
        "_objects": [zone for zone, _ in candidates],
    }


def build_prompt(packet: dict) -> str:
    payload = {key: value for key, value in packet.items()
               if not key.startswith("_")}
    return (f"{SYSTEM_PROMPT}\n\nВходные данные:\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=1)}\n\n"
            f"Ответ:\n")


def parse_response(text: str, count: int) -> list[Annotation]:
    """Разбор ответа. Любая нестыковка -> пустой список, зоны не меняются."""
    if not text:
        return []
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(raw, list):
        return []

    result: list[Annotation] = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            zone_id = int(item.get("zone_id", -1))
            verdict = str(item.get("verdict", "")).upper()
            rank = int(item.get("rank", 0))
            why = str(item.get("why", "")).strip()
        except (TypeError, ValueError):
            continue
        if zone_id < 0 or zone_id >= count or zone_id in seen:
            continue
        if verdict not in VERDICTS or not why:
            continue
        seen.add(zone_id)
        result.append(Annotation(zone_id, verdict, max(1, rank), why[:180]))
    return result


def annotate(zones: list, data: dict, *, dropped: list | None = None) -> list:
    """Главная точка входа. Возвращает те же зоны, что получила."""
    if not zones or not getattr(config, "AI_ENABLED", False):
        return zones

    try:
        from ai import licensing
        if not licensing.ai_enabled():
            return zones
    except Exception as exc:
        print(f"[ai] лицензия недоступна, работаем без ИИ: {exc}")
        return zones

    try:
        from ai import hw_profile, model_catalog, runtime

        profile = hw_profile.build_profile()
        spec = profile.model
        if spec is None or not runtime.model_ready(spec):
            return zones
        layers = model_catalog.gpu_layers(spec, profile.vram_gib)
        if not runtime.start(spec, gpu_layers=layers):
            return zones

        packet = build_packet(zones, data, dropped=dropped)
        objects = packet.get("_objects", [])
        answer = runtime.complete(
            build_prompt(packet), grammar=grammar(),
            max_tokens=int(getattr(config, "AI_MAX_TOKENS", 700)))
        notes = parse_response(answer or "", len(objects))
        if not notes:
            print("[ai] ответ модели не по схеме — зоны без подписей")
            return zones

        for note in notes:
            zone = objects[note.zone_id]
            zone.ai_verdict = note.verdict
            zone.ai_note = note.why
            zone.ai_rank = note.rank
        print(f"[ai] подписано зон: {len(notes)}")
    except Exception as exc:
        print(f"[ai] слой отключён из-за ошибки: {exc}")
    return zones
