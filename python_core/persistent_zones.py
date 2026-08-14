import json
import copy
from pathlib import Path
import pandas as pd

from zone_detector import Zone
import config
import paths

from datetime import datetime

DB_FILE = (paths.MT_COMMON_FILES / "persistent_zones_db.json") if paths.MT_COMMON_FILES else (paths.DATA_BRIDGE_DIR / "persistent_zones_db.json")

def default_serializer(obj):
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return str(obj)

def load_db() -> list[Zone]:
    data = paths.load_json_file(DB_FILE, default={})
    if not data:
        return []

    zones = []
    for i, z_dict in enumerate(data.get("archived", [])):
        try:
            zones.append(Zone.from_dict(z_dict))
        except (KeyError, TypeError) as e:
            print(f"[persistent] WARN: Skipping malformed zone #{i} in DB: {e}")
    return zones

def save_db(zones: list[Zone]):
    z_dicts = [z.to_dict() for z in zones]
    data = {
        "version": "1.0",
        "last_update": datetime.now().isoformat(),
        "archived": z_dicts,
    }
    if not paths.save_json_file(DB_FILE, data, indent=4, default=default_serializer):
        print(f"[persistent] ERROR: Failed to save DB to {DB_FILE}")

def get_h4_closes(all_data: dict[str, pd.DataFrame]) -> list[tuple[float, float]]:
    """(open, close) по недавней истории H4.

    По всей истории считать нельзя: зона сгорала сразу в том же пересчёте,
    в котором была архивирована — цена когда-то проходила через любой уровень.
    """
    if "H4" in all_data and not all_data["H4"].empty:
        df = all_data["H4"].tail(config.PERSISTENT_BREAKOUT_LOOKBACK)
        return list(zip(df['open'], df['close']))
    return []

def get_current_price(all_data: dict[str, pd.DataFrame]) -> float | None:
    for tf in ("H1", "H4", "D1"):
        df = all_data.get(tf)
        if df is not None and not df.empty:
            return float(df['close'].iloc[-1])
    return None

def is_too_far(zone: Zone, current_price: float | None) -> bool:
    """Зона слишком далеко от текущей цены (график ушёл) — не показываем."""
    if config.MAX_ZONE_DISTANCE_PCT <= 0:
        return False
    if current_price is None or current_price <= 0:
        return False
    return abs(zone.price - current_price) / current_price * 100.0 > config.MAX_ZONE_DISTANCE_PCT

def _age_days(zone: Zone) -> float:
    if not zone.archived_at:
        return 0.0
    try:
        seen = datetime.fromisoformat(zone.archived_at)
    except ValueError:
        return 0.0
    return (datetime.now() - seen).total_seconds() / 86400.0

def process_persistent_zones(current_zones: list[Zone], all_data: dict[str, pd.DataFrame]) -> list[Zone]:
    db_zones = load_db()
    now_iso = datetime.now().isoformat()
    current_price = get_current_price(all_data)

    # 1. Merge currently detected strong zones into DB
    for cz in current_zones:
        if cz.score >= 12: # Threshold for "Titanic" zones
            merged = False
            for dz in db_zones:
                if abs(cz.price - dz.price) <= config.ZONE_WIDTH * 2:
                    # Update DB zone with latest attributes if score is better
                    if cz.score >= dz.score:
                        dz.score = cz.score
                        dz.sources = cz.sources
                        dz.touch_count = cz.touch_count
                        dz.has_big_player = cz.has_big_player
                        dz.label_suffix = cz.label_suffix
                    dz.archived_at = now_iso   # зона снова подтверждена
                    merged = True
                    break
            if not merged:
                archived = copy.deepcopy(cz)
                archived.archived_at = now_iso
                db_zones.append(archived)
                print(f"[persistent] New Titanic Zone archived: ${cz.price:.2f} (S: {cz.score})")

    # 2. Invalidation: пробой телом H4 либо истёкший срок жизни
    h4_candles = get_h4_closes(all_data)
    valid_db_zones = []

    for dz in db_zones:
        # Зона, подтверждённая детектором в этом пересчёте, актуальна по определению.
        if dz.archived_at == now_iso:
            valid_db_zones.append(dz)
            continue

        if not dz.archived_at:
            # Зоны из старых версий БД без метки времени — считаем увиденными
            # сейчас, иначе они никогда не протухнут.
            dz.archived_at = now_iso

        breakouts = 0
        for op, cl in h4_candles:
            # If the body is completely across the zone (clear breakout without closing inside)
            zone_top = dz.top + (dz.width * 2) # Adding buffer
            zone_bottom = dz.bottom - (dz.width * 2)

            if op < zone_bottom and cl > zone_top:      # Full body breakout Up
                breakouts += 1
            elif op > zone_top and cl < zone_bottom:    # Full body breakout Down
                breakouts += 1

        if breakouts >= config.PERSISTENT_BREAKOUT_MIN:
            print(f"[persistent] Zone at ${dz.price:.2f} burned (H4 body broke it {breakouts}x)")
            continue

        age = _age_days(dz)
        if 0 < config.PERSISTENT_ZONE_MAX_AGE_DAYS < age:
            print(f"[persistent] Zone at ${dz.price:.2f} expired "
                  f"(not confirmed for {age:.1f} days)")
            continue

        valid_db_zones.append(dz)

    # Save active persistent zones
    save_db(valid_db_zones)

    # 3. Свежие зоны всегда приоритетнее архивных: раньше общий список
    # сортировался по score и резался до MAX_ZONES_ON_CHART, поэтому старые
    # архивные зоны вытесняли свежие и на графике оставались только протухшие.
    # Свежие зоны не фильтруем по удалённости: детектор только что посчитал их
    # по текущим свечам, и отброс по 5% съедал половину уровней.
    fresh = sorted(current_zones, key=lambda z: z.score, reverse=True)

    historic = []
    for dz in valid_db_zones:
        if is_too_far(dz, current_price):
            continue
        if any(abs(z.price - dz.price) <= config.ZONE_WIDTH * 2 for z in fresh):
            continue
        dz.label_suffix = " HIST"
        # Reduce historical score gradually based on age or just cap it
        dz.score = max(8, dz.score - 2) # Slightly weaken historical unconfirmed zones
        historic.append(dz)

    historic.sort(key=lambda z: z.score, reverse=True)

    return (fresh + historic)[:config.MAX_ZONES_ON_CHART]
