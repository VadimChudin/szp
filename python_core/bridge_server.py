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
from datetime import datetime, timedelta

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent))

import accumulation
import applog
import config
import data_fetcher
import paths
from data_fetcher import DataUnavailableError, fetch_from_csv, fetch_all_timeframes
from volume_filter import get_volume_flags_all_tf, calculate_delta, get_delta_at_zone
from zone_detector import current_price, detect_zones
from active_zones import normalize_display_balance, update_snapshot
from sl_model import possible_stop
from telegram_bot import send_telegram_message, send_alert_line, send_zones_update
from footprint_data import get_collector as get_fp_collector
# footprint_window импортируется лениво (содержит webview, блокирует headless)

# Вводим флаг загрузки
is_fp_downloading = False

# Используем централизованную функцию из paths
get_mt4_local_files_dir = paths.find_mt4_local_files_dir

# ── Пути обмена данными ──────────────────────────────────────────────
# MT4 будет писать сюда OHLC, Python будет читать отсюда
BRIDGE_DIR = paths.DATA_BRIDGE_DIR
BRIDGE_DIR.mkdir(parents=True, exist_ok=True)

# Файл с зонами — MT4 будет его читать
ZONES_OUTPUT = paths.ZONES_FILE

# Участки набора позиции крупным участником — отдельный файл, чтобы
# не ломать наивный парсер zones_output.json в индикаторах.
ACCUM_OUTPUT = ZONES_OUTPUT.parent / "accumulation_output.json"

# Файл-флаг: MT4 создаёт его когда записал новые данные
TRIGGER_FILE = paths.TRIGGER_FILE

# Файл-флаг: MT4 создаёт при нажатии кнопки "FP" (содержит таймфрейм)
FOOTPRINT_FLAG = paths.FOOTPRINT_FLAG

# Путь к Common/Files MT4 (EA пишет сюда CSV)
MT4_COMMON_FILES = paths.MT_COMMON_FILES or Path("")

# Через сколько повторять расчёт, если рыночных данных не было
DATA_RETRY_SECONDS = 300

# Путь к локальным CSV для zone_detector
LOCAL_DATA_DIR = paths.LOCAL_DATA_DIR
LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_common_text(path: Path) -> str:
    """Read MT4 ANSI and MT5 UTF-16 text files without leaking null bytes."""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw else "utf-8"
    return raw.decode(encoding, errors="ignore").replace("\x00", "").replace("\ufeff", "").strip()


def collector_live_quote() -> tuple[float | None, str]:
    """Return the live Bid and actual symbol exported by SmartZonesCollector."""
    if not MT4_COMMON_FILES or not MT4_COMMON_FILES.exists():
        return None, ""
    symbol = _read_common_text(MT4_COMMON_FILES / "smartzones_symbol.txt") or config.SYMBOL
    value = _read_common_text(MT4_COMMON_FILES / f"smartzones_quote_{symbol}.txt")
    try:
        quote = float(value.replace(",", "."))
    except (TypeError, ValueError):
        return None, symbol
    return (quote if quote > 0 else None), symbol


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
            # Читаем заголовок для логирования (MT5 пишет CSV в UTF-16)
            with open(src, 'r', encoding=data_fetcher.csv_encoding(src)) as f:
                header = f.readline().strip().lstrip('\ufeff')
            print(f"[bridge] {tf}: Synced from MT4 broker ({header})")
            found = True
        else:
            print(f"[bridge] {tf}: Not found in Common/Files/ ({src.name})")
    
    return found


def read_footprint_timeframe(flag_file: Path) -> str:
    """Читает ТФ из флага кнопки FP.

    MT5-советник пишет файл в UTF-16 (BOM + нулевые байты между символами),
    из-за чего запуск падал с «embedded null character». Декодируем оба
    варианта и оставляем только известные значения.
    """
    try:
        raw = flag_file.read_bytes()
    except OSError as e:
        print(f"[bridge] WARN: Cannot read footprint flag: {e}")
        return "1h"

    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw:
        text = raw.decode("utf-16", errors="ignore")
    else:
        text = raw.decode("utf-8", errors="ignore")

    text = text.replace("\x00", "").replace("\ufeff", "").strip().lower()
    return text if text in ("1h", "4h", "1d") else "1h"


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
    except ImportError:
        print("[bridge] ERROR: yfinance not installed — cannot refresh data")
    except Exception as e:
        print(f"[bridge] WARN: yfinance data refresh failed: {e}")
        print("[bridge] Using cached CSV data (may be stale)")


def sync_to_mt4():
    """Копирует JSON в папку MT4 Common/Files."""
    try:
        from sync_zones_to_mt4 import sync_zones
        sync_zones()
    except Exception as e:
        print(f"[bridge] WARN: Could not sync to MT4: {e}")


def export_accumulation(data):
    """Пишет и развозит по терминалам участки набора позиции."""
    try:
        output = accumulation.build_output(data)
        with open(ACCUM_OUTPUT, "w") as f:
            json.dump(output, f, indent=2)
        print(f"[bridge] Exported {output['count']} accumulation boxes "
              f"({output['timeframe']}) to: {ACCUM_OUTPUT}")
        from sync_zones_to_mt4 import sync_file
        sync_file(ACCUM_OUTPUT)
    except Exception as e:
        print(f"[bridge] WARN: Could not export accumulation boxes: {e}")


def calculate_and_export_zones(refresh_data: bool = True):
    """
    Основная функция: читает данные → считает зоны → пишет JSON для MT4.

    Возвращает список зон, либо None если рыночных данных не было (тогда
    прошлый zones_output.json остаётся нетронутым и расчёт нужно повторить).
    """
    print(f"\n{'='*50}")
    print(f"  Recalculating zones at {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*50}")

    # ── Обновляем данные (MT4 broker → fallback yfinance) ─────────
    if refresh_data:
        refresh_data_source()

    # ── Загрузка данных ──────────────────────────────────────────────
    # Если реальных свечей нет — НЕ перезаписываем zones_output.json: лучше
    # оставить в терминале прошлые зоны, чем уровни по мусорным данным.
    try:
        data = fetch_all_timeframes(config.SYMBOL)
    except DataUnavailableError as e:
        print(f"[bridge] ERROR: no market data, keeping previous zones. {e}")
        return None

    # ── Фильтр крупного игрока ───────────────────────────────────────
    volume_flags = get_volume_flags_all_tf(data)

    # ── Поиск зон ────────────────────────────────────────────────────
    zones = detect_zones(data, volume_flags, limit_output=False)

    # The H1 close can lag the open chart by up to one hour. Collector writes
    # the chart's Bid every 30 seconds, so it is the authoritative reference
    # for the visible three-above / three-below contract.
    reference_price, collector_symbol = collector_live_quote()
    reference_source = "collector_bid" if reference_price is not None else "h1_close"
    if reference_price is None:
        reference_price = current_price(data)
        print(f"[bridge] Live Collector quote unavailable; using H1 close: {reference_price}")
    else:
        print(f"[bridge] Live Collector Bid: {reference_price:.2f} ({collector_symbol})")
        if collector_symbol != config.SYMBOL:
            print(f"[bridge] WARN: Collector symbol {collector_symbol} differs from configured {config.SYMBOL}")
    
    # ── Active H4 snapshot ───────────────────────────────────────────
    # Архивная БД обновляется для истории, но displayed zones живут в
    # incremental snapshot: для того же H4 bar список не пересоздаётся.
    try:
        from persistent_zones import process_persistent_zones
        process_persistent_zones(zones, data)
    except Exception as e:
        print(f"[bridge] WARN: Could not update persistent archive: {e}")
    snapshot_zones = update_snapshot(zones, data, reference_price=reference_price)
    zones = normalize_display_balance(snapshot_zones, reference_price)
    above_count = sum(1 for zone in zones if zone.price > reference_price)
    below_count = sum(1 for zone in zones if zone.price < reference_price)
    if above_count != config.MIN_ZONES_PER_SIDE or below_count != config.MIN_ZONES_PER_SIDE:
        raise RuntimeError(
            f"display balance violation: above={above_count}, below={below_count}, ref={reference_price}"
        )
    print(f"[bridge] Display contract: {above_count} above / {below_count} below ref {reference_price:.2f}")

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
    old_data = paths.load_json_file(ZONES_OUTPUT, default={})
    current_fp_status = old_data.get("fp_status", "Ready")

    zones_for_mt4 = []
    for z in zones:
        zone_data = z.to_dict()
        # Индикатор (StrongZones.mq*) парсит JSON наивно, по ключу "price".
        # wick_points содержат свой "price" на каждую точку — из-за них
        # индикатор насчитывал фантомные зоны с битыми границами (огромные
        # прямоугольники). В файл для MT отдаём только сами зоны, без wick_points.
        zone_data.pop("wick_points", None)
        zone_data["price"] = round(zone_data["price"], 2)
        zone_data["top"] = round(zone_data["top"], 2)
        zone_data["bottom"] = round(zone_data["bottom"], 2)
        zone_data["sources"] = "+".join(sorted(set(z.sources)))
        zone_data["timestamp"] = datetime.now().isoformat()
        # Possible SL is informational only: no order is placed.
        try:
            h4_frame = data.get(config.PRIMARY_TIMEFRAME)
            current = float(h4_frame["close"].iloc[-1]) if h4_frame is not None and not h4_frame.empty else None
            zone_data["sl"] = possible_stop(z, h4_frame, current).to_dict()
        except Exception as exc:
            print(f"[bridge] WARN: SL candidate unavailable: {exc}")

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
        "reference_price": round(reference_price, 2) if reference_price else None,
        "reference_source": reference_source,
        "fp_status": current_fp_status,
        "zones": zones_for_mt4,
    }

    try:
        with open(ZONES_OUTPUT, "w") as f:
            json.dump(output, f, indent=2)
    except OSError as e:
        print(f"[bridge] ERROR: Could not write zones to {ZONES_OUTPUT}: {e}")
        return zones_for_mt4

    print(f"\n[bridge] Exported {len(zones_for_mt4)} zones to: {ZONES_OUTPUT}")

    if zones_for_mt4:
        for i, z in enumerate(zones_for_mt4, 1):
            print(f"  {i}. ${z['price']:.2f} | {z['sources']} | S:{z['score']}")
    else:
        print("  (no strong zones found — market may be flat)")

    # ── Синхронизация в MT4 ──────────────────────────────────────────
    sync_to_mt4()

    # ── Участки набора позиции крупным участником ────────────────────
    export_accumulation(data)

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
    applog.setup()
    print(f"[bridge] Started monitoring loop (interval: {interval_seconds}s)")
    print(f"[bridge] Watching: {BRIDGE_DIR}")
    print(f"[bridge] Output:   {ZONES_OUTPUT}")
    print(f"[bridge] Press Ctrl+C to stop\n")

    # Первый расчёт при старте
    data_ok = calculate_and_export_zones() is not None

    last_calc_time = time.time()
    last_attempt_time = last_calc_time

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

            # Флаг новых данных от MT4 больше НЕ пересчитывает зоны.
            # По просьбе клиента зоны обновляются строго раз в 4 часа —
            # только на закрытии свечи H4 (см. блок ниже). Иначе они
            # перерисовывались по 2–3 раза в час. Флаг просто снимаем.
            if TRIGGER_FILE.exists():
                TRIGGER_FILE.unlink()

            # ── Проверяем запрос на футпринт от MT4 ──────────────────
            # MT4 пишет через FILE_COMMON → ищем в Common/Files
            common_base = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal" / "Common" / "Files"
            common_fp_flag = common_base / "footprint_request.flag"
            
            if common_fp_flag.exists():
                print(f"\n[bridge] MT4 requested Footprint window.")
                tf = read_footprint_timeframe(common_fp_flag)
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
            # Зоны определяются на 4h, в течение тех же 4 часов новые зоны не строятся.
            # Считаем по времени БРОКЕРА (UTC + BROKER_UTC_OFFSET), т.к. H4-свечи
            # закрываются по серверному времени брокера, а не по времени ПК.
            broker_now = datetime.utcnow() + timedelta(hours=config.BROKER_UTC_OFFSET)
            # H4 свечи закрываются в 0:00, 4:00, 8:00, 12:00, 16:00, 20:00 (время брокера)
            current_h4_slot = broker_now.hour // 4
            
            if not hasattr(run_monitor_loop, '_last_h4_slot'):
                run_monitor_loop._last_h4_slot = current_h4_slot
            
            if current_h4_slot != run_monitor_loop._last_h4_slot:
                run_monitor_loop._last_h4_slot = current_h4_slot
                print(f"\n[bridge] H4 candle closed (broker {broker_now.strftime('%H:%M')}). Recalculating zones...")
                data_ok = calculate_and_export_zones() is not None
                last_calc_time = time.time()
                last_attempt_time = last_calc_time
            elif not data_ok and time.time() - last_attempt_time > DATA_RETRY_SECONDS:
                # Данных не было (терминал не запущен / не залогинен). Ждать
                # следующего закрытия H4 нельзя — иначе зоны в терминале
                # останутся протухшими до 4 часов. Пробуем снова.
                print("\n[bridge] Retrying zone calculation after data failure...")
                data_ok = calculate_and_export_zones() is not None
                last_attempt_time = time.time()
                if data_ok:
                    last_calc_time = last_attempt_time

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
