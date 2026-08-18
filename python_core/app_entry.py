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
import hashlib
import threading
import traceback
import multiprocessing
import json
from datetime import datetime, timezone

# ── Определяем базовую директорию ──────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)


# ── Защита паролем при запуске ─────────────────────────────────────
# SHA-256 правильного пароля (не сам пароль). Приложение не запустится,
# пока не введён пароль, чьим хэшем является эта строка.
# Чтобы сменить пароль — посчитайте SHA-256 нового и впишите сюда.
# По умолчанию пароль: Satpayeva82/2
EXPECTED_PWD_SHA256 = "42459edc1f376dd9b7d045b2f33372a2b775f693a260c591c9d182807b34171f"


def ask_password() -> bool:
    """Окно ввода пароля при старте. True — пароль верный, иначе False."""
    import tkinter as tk
    import ui_theme as ui

    state = {"ok": False, "attempts": 0}

    root = tk.Tk()
    root.title("Smart Zones Pro — protected access")
    W, H = 400, 300
    cv = ui.make_glass_window(root, W, H, radius=24)
    # A password prompt must not be hidden behind MetaTrader or a splash.
    root.deiconify()
    root.lift()
    try:
        root.attributes("-topmost", True)
        root.after(350, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass

    cv.create_text(W / 2, 56, text="Smart Zones Pro", fill=ui.TXT,
                   font=(ui.FONT, 20, "bold"))
    cv.create_text(W / 2, 82, text=f"NoName Trader  •  v{version.app_version()}",
                   fill=ui.GOLD, font=(ui.FONT, 10, "bold"))
    cv.create_text(W / 2, 118, text="Введите пароль доступа", fill=ui.TXT_DIM,
                   font=(ui.FONT, 11))

    entry = tk.Entry(root, show="•", justify='center', width=22,
                     font=(ui.FONT, 13))
    ui.style_entry(entry)
    cv.create_window(W / 2, 158, window=entry, height=38)
    entry.focus_set()

    err_id = cv.create_text(W / 2, 192, text="", fill=ui.BAD, font=(ui.FONT, 9))

    def submit(event=None):
        pwd = entry.get()
        if hashlib.sha256(pwd.encode("utf-8")).hexdigest() == EXPECTED_PWD_SHA256:
            state["ok"] = True
            root.destroy()
            return
        state["attempts"] += 1
        entry.delete(0, tk.END)
        if state["attempts"] >= 3:
            cv.itemconfigure(err_id, text="Слишком много попыток. Закрытие…")
            root.after(1200, root.destroy)
        else:
            cv.itemconfigure(err_id, text="Неверный пароль. Попробуйте ещё раз.")

    def cancel():
        root.destroy()

    login_btn = ui.GlassButton(root, "Войти", command=submit, width=140,
                               height=42, kind="primary")
    exit_btn = ui.GlassButton(root, "Выход", command=cancel, width=100,
                              height=42, kind="ghost")
    cv.create_window(W / 2 - 58, 244, window=login_btn)
    cv.create_window(W / 2 + 72, 244, window=exit_btn)

    entry.bind("<Return>", submit)
    root.bind("<Escape>", lambda e: cancel())
    root.mainloop()
    return state["ok"]

# Создаём необходимые папки в каталоге для записи (в установленной сборке это
# %LOCALAPPDATA%\SmartZonesPro, а не Program Files — иначе PermissionError).
import paths
import version
paths.ensure_dirs()


# ── Сплэш-экран (4 секунды при запуске) ───────────────────────────
def show_splash():
    """Показывает «стеклянную» заставку на 4 секунды."""
    try:
        import tkinter as tk
        import ui_theme as ui

        root = tk.Tk()
        W, H = 520, 320
        cv = ui.make_glass_window(root, W, H, radius=28, draggable=False)

        # Логотип-«ромб» в акцентном свечении
        cv.create_oval(W / 2 - 46, 66, W / 2 + 46, 158,
                       fill="", outline=ui.ACCENT, width=2)
        cv.create_text(W / 2, 112, text="◆", fill=ui.GOLD,
                       font=(ui.FONT, 34, "bold"))

        cv.create_text(W / 2, 196, text="Smart Zones Pro", fill=ui.TXT,
                       font=(ui.FONT, 26, "bold"))
        cv.create_text(W / 2, 228, text="Professional Footprint & Zones",
                       fill=ui.TXT_DIM, font=(ui.FONT, 11))
        status_id = cv.create_text(W / 2, 262, text="Starting services…",
                                   fill=ui.ACCENT, font=(ui.FONT, 10))

        cv.create_text(W / 2, H - 30,
                       text=f"NoName Trader  •  v{version.app_version()}",
                       fill=ui.GOLD, font=(ui.FONT, 13, "bold"))

        dots = {"n": 0}

        def tick():
            dots["n"] = (dots["n"] + 1) % 4
            cv.itemconfigure(status_id,
                             text="Starting services" + "." * dots["n"])
            root.after(350, tick)

        tick()
        root.after(4000, root.destroy)
        root.lift()
        try:
            root.attributes('-topmost', True)
            root.after_idle(root.attributes, '-topmost', False)
        except tk.TclError:
            pass
        root.mainloop()
    except Exception as e:
        print(f"[app] Splash screen skipped: {e}")


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
        
        def on_settings(icon, item):
            """Открыть окно настроек (брокер MT5 / источник данных / Telegram)."""
            try:
                import subprocess
                settings_script = os.path.join(BASE_DIR, "settings_window.py")
                if getattr(sys, 'frozen', False):
                    subprocess.Popen([sys.executable, "--settings"])
                else:
                    subprocess.Popen([sys.executable, settings_script])
            except Exception as e:
                print(f"[tray] Settings launch error: {e}")
        
        def on_exit(icon, item):
            icon.stop()
            os._exit(0)
        
        menu = pystray.Menu(
            pystray.MenuItem("Settings", on_settings),
            pystray.MenuItem("Open Footprint", on_footprint),
            pystray.MenuItem("Exit", on_exit),
        )
        
        icon = pystray.Icon(
            "SmartZonesPro", img,
            f"Smart Zones Pro v{version.app_version()}\nRunning in background",
            menu,
        )
        icon.run()
        
    except ImportError:
        # Без pystray просто ждём
        bridge_thread.join()


# ── ГЛАВНЫЙ ЗАПУСК ────────────────────────────────────────────────
def run_startup_diagnostics():
    """Fast non-interactive check used by CI and support diagnostics."""
    modules = ("pystray", "PIL", "bridge_server", "sync_zones_to_mt4", "settings_window")
    report = {
        "ok": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_dir": BASE_DIR,
        "frozen": bool(getattr(sys, "frozen", False)),
        "build": version.app_version(),
        "modules": [],
    }
    try:
        import importlib
        for name in modules:
            importlib.import_module(name)
            report["modules"].append(name)
    except Exception as exc:
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
    report_path = paths.DATA_DIR / "startup_diagnostics.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[app] startup diagnostics:", json.dumps(report, ensure_ascii=False))
    if not report["ok"]:
        raise RuntimeError(report["error"])


def show_fatal_startup_error(exc: BaseException):
    """Windowed builds have no console: persist and show every early failure."""
    details = traceback.format_exc()
    try:
        error_path = paths.DATA_DIR / "startup_error.log"
        error_path.write_text(details, encoding="utf-8")
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Smart Zones Pro — startup error",
            "The application could not start.\n\n"
            "Details were saved to startup_error.log in the Smart Zones Pro data folder.\n\n"
            f"{type(exc).__name__}: {exc}",
        )
        root.destroy()
    except Exception:
        pass


def main():
    # Лог в файл: в windowed-сборке консоли нет, без него причину сбоя
    # (нет данных от терминала, не найден символ и т.п.) увидеть невозможно.
    import applog
    applog.setup()
    print(f"[app] Smart Zones Pro build v{version.app_version()}")

    # Non-interactive process/package verification. Must run before dialogs.
    if "--diagnostics" in sys.argv:
        run_startup_diagnostics()
        return

    # Разбор аргументов
    if "--settings" in sys.argv:
        # Окно настроек (вызывается из трея)
        from settings_window import open_settings_window
        open_settings_window()
        return
    
    if "--footprint" in sys.argv:
        # Режим футпринта (вызывается из bridge_server или трея)
        idx = sys.argv.index("--footprint")
        tf = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "4h"
        from footprint_data import get_collector
        from footprint_window import open_footprint_window
        try:
            collector = get_collector()
            collector.load_all()
            open_footprint_window(tf)
        except Exception as e:
            # Окно не открывалось «молча»: дочерний процесс падал, а в лог
            # попадало только сообщение о его запуске.
            print(f"[footprint] FAILED to open window ({tf}): {e}")
            print(traceback.format_exc())
        return
    
    if "--once" in sys.argv:
        # Одноразовый расчёт зон
        from bridge_server import calculate_and_export_zones
        calculate_and_export_zones()
        return
    
    # ── Полный запуск ──
    # Protected access is mandatory. The password window is deliberately
    # raised above the terminal; only a successful login starts Bridge/tray.
    if not ask_password():
        print("[app] Access denied or cancelled at password gate.")
        return

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
    try:
        main()
    except BaseException as exc:
        show_fatal_startup_error(exc)
        raise
