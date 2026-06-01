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
    try:
        return [Zone.from_dict(d) for d in data.get("archived", [])]
    except Exception as e:
        print(f"[persistent] Failed to load DB: {e}")
        return []

def save_db(zones: list[Zone]):
    z_dicts = [z.to_dict() for z in zones]
    data = {
        "version": "1.0",
        "last_update": datetime.now().isoformat(),
        "archived": z_dicts,
    }
    if not paths.save_json_file(DB_FILE, data, indent=4, default=default_serializer):
        print(f"[persistent] Failed to save DB: {DB_FILE}")

def get_h4_closes(all_data: dict[str, pd.DataFrame]) -> list[tuple[float, float]]:
    # Returns a list of tuples (open, close) for the last N H4 candles
    if "H4" in all_data and not all_data["H4"].empty:
        df = all_data["H4"]
        tail = df.tail(15)  # Analyze last 15 H4 candles for invalidation
        return list(zip(tail['open'], tail['close']))
    return []

def process_persistent_zones(current_zones: list[Zone], all_data: dict[str, pd.DataFrame]) -> list[Zone]:
    db_zones = load_db()
    
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
                    merged = True
                    break
            if not merged:
                db_zones.append(copy.deepcopy(cz))
                print(f"[persistent] New Titanic Zone archived: ${cz.price:.2f} (S: {cz.score})")
    
    # 2. Invalidation checking (Burning broken zones)
    h4_candles = get_h4_closes(all_data)
    valid_db_zones = []
    
    for dz in db_zones:
        invalidated = False
        if h4_candles:
            breakouts = 0
            for op, cl in h4_candles:
                # If the body is completely across the zone (clear breakout without closing inside)
                zone_top = dz.top + (dz.width * 2) # Adding buffer
                zone_bottom = dz.bottom - (dz.width * 2)
                
                # Full body breakout Up
                if op < zone_bottom and cl > zone_top:
                    breakouts += 1
                # Full body breakout Down
                elif op > zone_top and cl < zone_bottom:
                    breakouts += 1
            
            if breakouts >= 2:
                print(f"[persistent] Zone at ${dz.price:.2f} burned (broken {breakouts} times by H4)")
                invalidated = True
                
        if not invalidated:
            valid_db_zones.append(dz)

    # Save active persistent zones
    save_db(valid_db_zones)
    
    # 3. Finally, mix them with current zones to render
    final_output = []
    final_output.extend(current_zones)
    
    # Add db zones that are not already in current zones
    for dz in valid_db_zones:
        found = False
        for cz in final_output:
            if abs(cz.price - dz.price) <= config.ZONE_WIDTH * 2:
                found = True
                break
        if not found:
            # Mark it as historic
            dz.label_suffix = " HIST"
            
            # Reduce historical score gradually based on age or just cap it
            dz.score = max(8, dz.score - 2) # Slightly weaken historical unconfirmed zones
            
            final_output.append(dz)
            
    # Sort by score (strongest first), then limit to MAX_ZONES_ON_CHART
    final_output.sort(key=lambda x: x.score, reverse=True)
    final_output = final_output[:config.MAX_ZONES_ON_CHART]
    return final_output
