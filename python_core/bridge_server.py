"""
bridge_server.py — Мост между MetaTrader 4 и Python Core.

Работает через файловый обмен (без ZeroMQ/DLL):
  1. MT4 Expert Advisor записывает OHLC-данные в CSV (data_bridge/)
  2. Этот скрипт мониторит папку, при обновлении — пересчитывает зоны
  3. Результат записывается в zones_output.json
  4. MT4 индикатор читает JSON и рисует зоны на графике

Использование:
  python bridge_server.py              # Запуск в режиме мониторинга
  python bridge_server.py --once       # Однократный расчёт
"""

import json
import time
import os
import sys
import threading
from pathlib import Path
from datetime import datetime

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent))

import config
import paths
from data_fetcher import fetch_from_csv, fetch_all_timeframes
from volume_filter import get_volume_flags_all_tf, calculate_delta, get_delta_at_zone
from zone_detector import detect_zones
from telegram_bot import send_telegram_message, send_alert_line, send_zones_update
from footprint_data import get_collector as get_fp_collector
# footprint_window импортируется лениво (содержит webview, блокирует headless)

# Вводим флаг загрузки
is_fp_downloading = False

# ── Вспомогательная функция для Telegram ───────────────────────────────
def get_mt4_local_files_dir() -> Path | None:
    terminal_base = paths.MT_TERMINAL_ROOT
    if terminal_base and terminal_base.exists():
        for sub in terminal_base.iterdir():
            if sub.is_dir():
                files_dir = sub / "MQL4" / "Files"
                if files_dir.exists():
                    return files_dir
    return None

# ── Пути обмена данными ──────────────────────────────────────────────
# MT4 будет писать сюда OHLC, Python будет читать отсюда
BRIDGE_DIR = paths.DATA_BRIDGE_DIR
BRIDGE_DIR.mkdir(parents=True, exist_ok=True)

# Файл с зонами — MT4 будет его читать
ZONES_OUTPUT = paths.ZONES_FILE

# Файл-флаг: MT4 создаёт его когда записал новые данные
TRIGGER_FILE = paths.TRIGGER_FILE

# Файл-флаг: MT4 создаёт при нажатии кнопки "FP" (содержит таймфрейм)
FOOTPRINT_FLAG = paths.FOOTPRINT_FLAG

# Путь к Common/Files MT4 (EA пишет сюда CSV)
MT4_COMMON_FILES = paths.MT_COMMON_FILES or Path("")

# Путь к локальным CSV для zone_detector
LOCAL_DATA_DIR = paths.LOCAL_DATA_DIR
LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)


def sync_mt4_broker_data() -> bool:
    """
    Копирует CSV файлы с OHLCV от MT4 EA (брокерские данные) 
    из Common/Files/ в python_core/data/.
    
    Возвращает True если файлы найдены и скопированы.
    """
    import shutil
    
    if not MT4_COMMON_FILES or not MT4_COMMON_FILES.exists():
        print(f"[bridge] MT4 Common/Files not found: {MT4_COMMON_FILES}")
        return False
    
    symbol = config.SYMBOL  # XAUUSD
    found = False
    
    for tf in ["M1", "H1", "H4", "D1"]:
        src = MT4_COMMON_FILES / f"{symbol}_{tf}.csv"
        dst = LOCAL_DATA_DIR / f"{symbol}_{tf}.csv"
        
        if src.exists():
            shutil.copy2(src, dst)
            # Читаем заголовок для логирования
            with open(src, 'r') as f:
                header = f.readline().strip()
            print(f"[bridge] {tf}: Synced from MT4 broker ({header})")
            found = True
        else:
            print(f"[bridge] {tf}: Not found in Common/Files/ ({src.name})")
    
    return found


def refresh_data_source():
    """
    Обновляет CSV данные. Приоритет:
    1. MT4 брокерские CSV (если EA SmartZonesCollector запущен)
    2. yfinance CME GC=F (fallback)
    """
    if sync_mt4_broker_data():
        print("[bridge] Using BROKER data from MT4")
        return
    
    # Fallback: yfinance
    print("[bridge] MT4 data not available, falling back to yfinance CME...")
    try:
        from download_real_data import download_and_save
        download_and_save()
    except Exception as e:
        print(f"[bridge] WARN: Could not refresh any data: {e}")
        print("[bridge] Using cached CSV data")


def sync_to_mt4():
    """Копирует JSON в папку MT4 Common/Files."""
    try:
        from sync_zones_to_mt4 import sync_zones
        sync_zones()
    except Exception as e:
        print(f"[bridge] WARN: Could not sync to MT4: {e}")


def calculate_and_export_zones(refresh_data: bool = True):
    """
    Основная функция: читает данные → считает зоны → пишет JSON для MT4.
    """
    print(f"\n{'='*50}")
    print(f"  Recalculating zones at {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*50}")

    # ── Обновляем данные (MT4 broker → fallback yfinance) ─────────
    if refresh_data:
        refresh_data_source()

    # ── Загрузка данных ──────────────────────────────────────────────
    data = fetch_all_timeframes(config.SYMBOL)

    # ── Фильтр крупного игрока ───────────────────────────────────────
    volume_flags = get_volume_flags_all_tf(data)

    # ── Поиск зон ────────────────────────────────────────────────────
    zones = detect_zones(data, volume_flags)
    
    # ── Подмешивание "Вечных" исторических зон (и их инвалидация) ────
    try:
        from persistent_zones import process_persistent_zones
        zones = process_persistent_zones(zones, data)
    except Exception as e:
        print(f"[bridge] WARN: Could not process persistent zones: {e}")

    # ── Дельта-анализ (Футпринт Dukascopy/MT4) ──────
    flow_delta = None
    try:
        collector = get_fp_collector()
        buf = collector.buffers.get("4h")
        if buf and not buf.buffer:
            buf.load_initial()
        if buf and buf.buffer:
            last_c = buf.buffer[-1]
            tot_vol = last_c.total_volume or 1
            flow_delta = {
                'dominant': "BUY" if last_c.delta > 0 else "SELL",
                'delta_percent': (last_c.delta / tot_vol) * 100
            }
            print(f"[bridge] LIVE Flow delta: {flow_delta['dominant']} ({flow_delta['delta_percent']:+.2f}%)")
    except Exception as e:
        print(f"[bridge] Flow unavailable ({e}), using OHLC approximation")

    # Fallback: аппроксимация дельты по OHLC
    delta_df = None
    if 'H4' in data:
        delta_df = calculate_delta(data['H4'])
    elif 'H1' in data:
        delta_df = calculate_delta(data['H1'])

    # ── Формируем JSON для MT4 ───────────────────────────────────
    # Считываем уже существующий zones_output.json чтобы не затереть fp_status
    current_fp_status = "Ready"
    if ZONES_OUTPUT.exists():
        try:
            with open(ZONES_OUTPUT, "r") as f:
                old_data = json.load(f)
                current_fp_status = old_data.get("fp_status", "Ready")
        except: pass

    zones_for_mt4 = []
    for z in zones:
        zone_data = {
            "price": round(z.price, 2),
            "top": round(z.top, 2),
            "bottom": round(z.bottom, 2),
            "score": z.score,
            "sources": "+".join(sorted(set(z.sources))),
            "label": z.label,
            "has_big_player": z.has_big_player,
            "is_round_level": z.is_round_level,
            "touch_count": z.touch_count,
            "timestamp": datetime.now().isoformat(),
        }

        # Добавляем дельту для каждой зоны
        if delta_df is not None:
            delta_info = get_delta_at_zone(delta_df, z.price)
            zone_data["delta"] = delta_info
        
        zones_for_mt4.append(zone_data)

    # ── Записываем JSON ──────────────────────────────────────────────
    output = {
        "symbol": config.SYMBOL,
        "calculated_at": datetime.now().isoformat(),
        "zone_count": len(zones_for_mt4),
        "min_score": config.MIN_ZONE_SCORE,
        "fp_status": current_fp_status,
        "zones": zones_for_mt4,
    }

    with open(ZONES_OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n[bridge] Exported {len(zones_for_mt4)} zones to: {ZONES_OUTPUT}")

    if zones_for_mt4:
        for i, z in enumerate(zones_for_mt4, 1):
            print(f"  {i}. ${z['price']:.2f} | {z['sources']} | S:{z['score']}")
    else:
        print("  (no strong zones found — market may be flat)")

    # ── Синхронизация в MT4 ──────────────────────────────────────────
    sync_to_mt4()

    # ── Telegram: краткая сводка по зонам (если бот настроен) ────────
    try:
        send_zones_update(zones_for_mt4)
    except Exception as e:
        print(f"[bridge] telegram zones-update skipped: {e}")

    return zones_for_mt4


def run_monitor_loop(interval_seconds: int = 5):
    """
    Бесконечный цикл мониторинга.
    Ждёт появления файла-флага от MT4, пересчитывает зоны.
    Также пересчитывает каждые 4 часа автоматически (на закрытие H4).
    """
    print(f"[bridge] Started monitoring loop (interval: {interval_seconds}s)")
    print(f"[bridge] Watching: {BRIDGE_DIR}")
    print(f"[bridge] Output:   {ZONES_OUTPUT}")
    print(f"[bridge] Press Ctrl+C to stop\n")

    # Первый расчёт при старте
    calculate_and_export_zones()

    last_calc_time = time.time()

    # Инициализация параметров для Telegram
    mt4_files = get_mt4_local_files_dir()
    alert_path = mt4_files / "tg_alerts.txt" if mt4_files else None
    last_alert_size = 0
    if alert_path and alert_path.exists():
        last_alert_size = alert_path.stat().st_size
        print(f"[telegram] Monitoring alerts at: {alert_path}")
    elif alert_path:
        print(f"[telegram] Alerts file not created yet (will monitor): {alert_path}")

    while True:
        try:
            # Проверяем алерт-файл от MT4 для Telegram
            if alert_path and alert_path.exists():
                curr_size = alert_path.stat().st_size
                if curr_size > last_alert_size:
                    with open(alert_path, 'r', encoding='utf-8') as f:
                        f.seek(last_alert_size)
                        new_text = f.read().strip()
                        if new_text:
                            for line in new_text.split('\n'):
                                if line.strip():
                                    send_alert_line(line.strip())
                    last_alert_size = curr_size
                elif curr_size < last_alert_size:
                    last_alert_size = curr_size # Файл был перезаписан или очищен

            # Проверяем файл-флаг от MT4 для пересчета зон
            if TRIGGER_FILE.exists():
                print(f"\n[bridge] Trigger detected! MT4 sent new data.")
                TRIGGER_FILE.unlink()  # Удаляем флаг
                calculate_and_export_zones()
                last_calc_time = time.time()

            # ── Проверяем запрос на футпринт от MT4 ──────────────────
            # MT4 пишет через FILE_COMMON → ищем в Common/Files
            common_base = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal" / "Common" / "Files"
            common_fp_flag = common_base / "footprint_request.flag"
            
            if common_fp_flag.exists():
                print(f"\n[bridge] MT4 requested Footprint window.")
                with open(common_fp_flag, 'r') as f:
                    tf = f.read().strip()
                if not tf: tf = "1h"
                common_fp_flag.unlink()
                
                global is_fp_downloading
                if not is_fp_downloading:
                    is_fp_downloading = True
                    
                    def bg_fp_launcher(timeframe):
                        global is_fp_downloading
                        print(f"[bridge] Launching Footprint window for {timeframe}...")
                        try:
                            import subprocess
                            if getattr(sys, 'frozen', False):
                                subprocess.Popen([sys.executable, "--footprint", timeframe])
                            else:
                                fp_script = Path(__file__).parent / "smart_zones_tray.py"
                                subprocess.Popen([sys.executable, str(fp_script), "--footprint", timeframe])
                        except Exception as e:
                            print(f"[bridge] Failed to launch UI: {e}")
                        is_fp_downloading = False

                    threading.Thread(target=bg_fp_launcher, args=(tf,), daemon=True).start()
                else:
                    print(f"[bridge] Footprint already downloading, ignored duplicate click.")

            # Автоматический пересчёт ТОЛЬКО на закрытии H4 свечи
            # Зоны определяются на 4h, в течение тех же 4 часов новые зоны не строятся
            now = datetime.now()
            # H4 свечи закрываются в 0:00, 4:00, 8:00, 12:00, 16:00, 20:00 (по серверному времени)
            current_h4_slot = now.hour // 4
            
            if not hasattr(run_monitor_loop, '_last_h4_slot'):
                run_monitor_loop._last_h4_slot = current_h4_slot
            
            if current_h4_slot != run_monitor_loop._last_h4_slot:
                run_monitor_loop._last_h4_slot = current_h4_slot
                print(f"\n[bridge] H4 candle closed ({now.strftime('%H:%M')}). Recalculating zones...")
                calculate_and_export_zones()
                last_calc_time = time.time()

            time.sleep(interval_seconds)

        except KeyboardInterrupt:
            print("\n[bridge] Stopped by user.")
            break
        except Exception as e:
            print(f"\n[bridge] ERROR: {e}")
            time.sleep(30)  # Ждём 30 сек при ошибке


if __name__ == "__main__":
    if "--once" in sys.argv:
        calculate_and_export_zones(refresh_data=False)
    elif "--footprint" in sys.argv:
        # Тестовый запуск окна футпринта
        fp = get_fp_collector()
        fp.load_all()
        fp.start_background_updates(60)
        open_footprint_window("4h")
    else:
        run_monitor_loop()
