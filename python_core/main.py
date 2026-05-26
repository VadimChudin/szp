"""
main.py — Точка входа Smart Zones Pro (Python Core).

Оркестрирует полный пайплайн:
  1. Получение данных (data_fetcher)
  2. Фильтрация крупных игроков (volume_filter)
  3. Поиск и скоринг зон (zone_detector)
  4. Визуализация (visualizer)

Использование:
  python main.py                  # Полный пайплайн с генерацией графика
  python main.py --no-plot        # Только расчёт зон (без графика)
"""

import sys
import json
from datetime import datetime

import config
from data_fetcher import fetch_all_timeframes
from volume_filter import get_volume_flags_all_tf
from zone_detector import detect_zones
from visualizer import plot_zones_mplfinance


def run_pipeline(plot: bool = True) -> list[dict]:
    """
    Запускает полный пайплайн обнаружения зон.

    Returns:
        list[dict]: Список зон в JSON-ready формате
                    (для отправки в MetaTrader через ZeroMQ)
    """
    print("=" * 60)
    print(f"  Smart Zones Pro — {config.SYMBOL}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── 1. Получение данных ──────────────────────────────────────────
    print("\n[1/4] Fetching candle data...")
    data = fetch_all_timeframes(config.SYMBOL)

    # ── 2. Фильтр крупного игрока ────────────────────────────────────
    print("\n[2/4] Detecting Big Player activity...")
    volume_flags = get_volume_flags_all_tf(data)

    # ── 3. Поиск зон ────────────────────────────────────────────────
    print("\n[3/4] Detecting strong zones...")
    zones = detect_zones(data, volume_flags)
    
    try:
        from persistent_zones import process_persistent_zones
        zones = process_persistent_zones(zones, data)
        print("  |-- Mixed with Persistent/Historical DB")
    except Exception as e:
        print(f"  |-- WARN: Could not process persistent zones: {e}")

    if not zones:
        print("\n⚠ No strong zones detected (market may be flat / in noise).")
        print("  Waiting for next H4 close...")
        return []

    # Вывод найденных зон в консоль
    print(f"\n{'─' * 50}")
    print(f"  STRONG ZONES DETECTED: {len(zones)}")
    print(f"{'─' * 50}")
    for i, z in enumerate(zones, 1):
        strength = "🔴🔴🔴" if z.score >= 9 else "🔴🔴" if z.score >= 7 else "🔴"
        print(f"  {i}. {z.label}  {strength}")
        print(f"     Range: ${z.bottom:.2f} — ${z.top:.2f}")
        print(f"     Touches: {z.touch_count}")
    print(f"{'─' * 50}\n")

    # ── 4. Визуализация ──────────────────────────────────────────────
    if plot:
        print("[4/4] Generating chart...")
        for tf_label in ["H4", "H1"]:
            if tf_label in data:
                chart_path = plot_zones_mplfinance(
                    data[tf_label],
                    zones,
                    title=f"Smart Zones Pro — {config.SYMBOL}",
                    timeframe_label=tf_label,
                )
    else:
        print("[4/4] Skipping chart generation (--no-plot)")

    # ── Формируем JSON-ответ (для ZeroMQ / MetaTrader) ───────────────
    zones_json = []
    for z in zones:
        zones_json.append({
            "price": z.price,
            "top": z.top,
            "bottom": z.bottom,
            "score": z.score,
            "sources": z.sources,
            "label": z.label,
            "has_big_player": z.has_big_player,
            "is_round_level": z.is_round_level,
            "touch_count": z.touch_count,
        })

    # Сохраняем JSON для отладки
    import os
    out_dir = r"d:\smart-zones-pro\output"
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "last_zones.json")
    with open(json_path, "w") as f:
        json.dump(zones_json, f, indent=2)
    print(f"[main] Zones saved to {json_path}")

    return zones_json


if __name__ == "__main__":
    no_plot = "--no-plot" in sys.argv
    zones = run_pipeline(plot=not no_plot)
