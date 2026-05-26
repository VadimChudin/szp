import os
import sys
import threading
import time
from pathlib import Path
from PIL import Image, ImageDraw

import pystray
from pystray import MenuItem as item

# Важно: добавляем путь для импорта
sys.path.insert(0, str(Path(__file__).parent))
import bridge_server

def create_image():
    # Создаем простую иконку, если нет готовой .ico
    # Рисуем букву "Z" на красном фоне
    image = Image.new('RGB', (64, 64), color=(30, 30, 30))
    dc = ImageDraw.Draw(image)
    dc.rectangle(
        [10, 10, 54, 54],
        outline=(255, 60, 60),
        width=4
    )
    # Z-линия
    dc.line([20, 20, 44, 20, 20, 44, 44, 44], fill=(255, 255, 255), width=4)
    return image

icon_global = None

def patch_action(icon, item):
    import subprocess
    patch_script = Path(__file__).parent / "installer_gui.py"
    subprocess.Popen([sys.executable, str(patch_script)])

def on_exit(icon, item):
    global icon_global
    icon.stop()
    os._exit(0)  # Жесткий выход, чтобы убить все потоки

def start_tray():
    global icon_global
    
    menu = pystray.Menu(
        item('Status: Running (Bridge Sync)', lambda: None, enabled=False),
        item('Patch MT4 Terminals', patch_action),
        item('Exit Smart Zones', on_exit)
    )

    icon_global = pystray.Icon("SmartZonesPro", create_image(), "Smart Zones Pro", menu)
    
    # Запускаем bridge monitor в фоновом потоке
    threading.Thread(target=bridge_server.run_monitor_loop, args=(5,), daemon=True).start()
    
    icon_global.run()

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--footprint", type=str, help="Launch footprint window for timeframe")
    args, unknown = parser.parse_known_args()
    
    if args.footprint:
        import footprint_window
        footprint_window.open_footprint_window(args.footprint)
    else:
        start_tray()
