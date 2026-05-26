"""
Smart Zones Pro — Главная точка входа.
Всё запускается по 1 кнопке. Никаких терминалов.
- Мост (bridge_server) работает в фоне
- Патчинг MT4/MT5 происходит автоматически
- Иконка в трее для управления
- Футпринт по кнопке FP на графике
"""
import sys
import os
import threading
import multiprocessing

# ── Определяем базовую директорию ──────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

# Создаём необходимые папки
data_bridge = os.path.join(os.path.dirname(BASE_DIR), "data_bridge")
os.makedirs(data_bridge, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)


# ── Сплэш-экран (4 секунды при запуске) ───────────────────────────
def show_splash():
    """Показывает заставку с логотипом на 4 секунды."""
    try:
        import tkinter as tk
        
        splash_path = None
        for name in ["splash.gif", "splash.png", "splash.bmp"]:
            p = os.path.join(BASE_DIR, name)
            if os.path.exists(p):
                splash_path = p
                break
        
        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg='#0d1117')
        
        w, h = 520, 380
        ws, hs = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = int((ws/2) - (w/2)), int((hs/2) - (h/2))
        root.geometry(f"{w}x{h}+{x}+{y}")
        
        if splash_path and splash_path.endswith('.gif'):
            frames = []
            try:
                while True:
                    frames.append(tk.PhotoImage(file=splash_path, format=f"gif -index {len(frames)}"))
            except tk.TclError:
                pass
            if frames:
                img_label = tk.Label(root, bg='#0d1117')
                img_label.pack(expand=True, fill='both')
                def animate(idx):
                    img_label.configure(image=frames[idx])
                    root.after(40, animate, (idx + 1) % len(frames))
                animate(0)
        else:
            # Текстовый сплэш если картинки нет
            title = tk.Label(root, text="Smart Zones Pro", fg='#58a6ff', bg='#0d1117',
                           font=("Segoe UI", 28, "bold"))
            title.pack(pady=(80, 10))
            ver = tk.Label(root, text="v1.0", fg='#8b949e', bg='#0d1117',
                          font=("Segoe UI", 14))
            ver.pack()
            status = tk.Label(root, text="Starting services...", fg='#f0883e', bg='#0d1117',
                            font=("Segoe UI", 11))
            status.pack(pady=(40, 0))
        
        # Подпись
        txt = tk.Label(root, text="for Yerassyl Uzakhbayev", fg='#d4a824', bg='#0d1117',
                      font=("Segoe UI", 13, "bold"))
        txt.place(relx=0.5, rely=0.92, anchor='center')
        
        root.after(4000, root.destroy)
        root.lift()
        root.attributes('-topmost', True)
        root.after_idle(root.attributes, '-topmost', False)
        root.mainloop()
    except Exception:
        pass  # Сплэш не критичен


# ── Патчинг MT4/MT5 ──────────────────────────────────────────────
def patch_terminals():
    """Автоматически устанавливает индикаторы и EA во все терминалы MT4/MT5."""
    try:
        from sync_zones_to_mt4 import install_all
        install_all()
    except Exception as e:
        print(f"[app] Patching error (non-fatal): {e}")


# ── Системный трей ──────────────────────────────────────────────
def run_tray(bridge_thread):
    """Иконка в трее: Smart Zones Pro работает в фоне."""
    try:
        import pystray
        from PIL import Image, ImageDraw, ImageFont
        
        # Иконка: синий круг на тёмном фоне
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        dc = ImageDraw.Draw(img)
        dc.ellipse([4, 4, 60, 60], fill=(41, 98, 255))
        dc.text((18, 15), "SZ", fill='white')
        
        def on_footprint(icon, item):
            """Открыть окно футпринта."""
            try:
                import subprocess
                fp_script = os.path.join(BASE_DIR, "smart_zones_tray.py")
                if getattr(sys, 'frozen', False):
                    subprocess.Popen([sys.executable, "--footprint", "4h"])
                else:
                    subprocess.Popen([sys.executable, fp_script, "--footprint", "4h"])
            except Exception as e:
                print(f"[tray] Footprint launch error: {e}")
        
        def on_exit(icon, item):
            icon.stop()
            os._exit(0)
        
        menu = pystray.Menu(
            pystray.MenuItem("Open Footprint", on_footprint),
            pystray.MenuItem("Exit", on_exit),
        )
        
        icon = pystray.Icon("SmartZonesPro", img, "Smart Zones Pro\nRunning in background", menu)
        icon.run()
        
    except ImportError:
        # Без pystray просто ждём
        bridge_thread.join()


# ── ГЛАВНЫЙ ЗАПУСК ────────────────────────────────────────────────
def main():
    # Разбор аргументов
    if "--footprint" in sys.argv:
        # Режим футпринта (вызывается из bridge_server или трея)
        idx = sys.argv.index("--footprint")
        tf = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "4h"
        from footprint_data import get_collector
        collector = get_collector()
        collector.load_all()
        from footprint_window import open_footprint_window
        open_footprint_window(tf)
        return
    
    if "--once" in sys.argv:
        # Одноразовый расчёт зон
        from bridge_server import calculate_and_export_zones
        calculate_and_export_zones()
        return
    
    # ── Полный запуск ──
    # 1. Сплэш
    show_splash()
    
    # 2. Патчинг MT4/MT5 в фоне
    threading.Thread(target=patch_terminals, daemon=True).start()
    
    # 3. Мост (bridge_server) в фоновом потоке
    from bridge_server import run_monitor_loop
    bridge_thread = threading.Thread(target=run_monitor_loop, args=(5,), daemon=True)
    bridge_thread.start()
    
    # 4. Иконка в трее (блокирует главный поток)
    run_tray(bridge_thread)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
