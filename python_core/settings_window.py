"""
settings_window.py — Окно настроек Smart Zones Pro (Tkinter).

Позволяет клиенту настроить всё из иконки в трее, без открытия футпринта
и без ручного редактирования файлов:
  - подключение к брокеру MT5 (server / login / password / путь к MT5) — пишется
    в `brokers.json` (до 3 слотов, можно выбрать активный);
  - источник данных `DATA_SOURCE` и параметры Telegram — пишутся в `.env`.

Запускается как отдельный процесс (`app_entry.py --settings`), чтобы Tkinter
работал в своём главном потоке и не конфликтовал с иконкой pystray.
"""
import os
import tkinter as tk
from tkinter import ttk, messagebox

import paths
import ui_theme as ui

DATA_SOURCES = ["mt5", "csv", "yfinance", "binance", "mt4_ticks", "dukascopy"]
BROKER_SLOTS = 3

_DEFAULT_BROKERS = {
    "active_broker": 0,
    "brokers": [
        {"name": f"Broker {i + 1}", "server": "", "login": 0, "password": "", "path": ""}
        for i in range(BROKER_SLOTS)
    ],
}


# ── brokers.json ──────────────────────────────────────────────────────
def load_brokers() -> dict:
    data = paths.load_json_file(paths.BROKERS_FILE, default=None)
    if not isinstance(data, dict) or "brokers" not in data:
        return {k: (v[:] if isinstance(v, list) else v) for k, v in _DEFAULT_BROKERS.items()}
    brokers = list(data.get("brokers", []))
    while len(brokers) < BROKER_SLOTS:
        brokers.append({"name": f"Broker {len(brokers) + 1}", "server": "",
                        "login": 0, "password": "", "path": ""})
    return {"active_broker": int(data.get("active_broker", 0) or 0), "brokers": brokers}


def save_brokers(data: dict) -> bool:
    return paths.save_json_file(paths.BROKERS_FILE, data, indent=4)


# ── .env ──────────────────────────────────────────────────────────────
def _read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if paths.ENV_FILE.exists():
        try:
            for line in paths.ENV_FILE.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, _, val = stripped.partition("=")
                values[key.strip()] = val.strip()
        except OSError as e:
            print(f"[settings] WARN: could not read .env: {e}")
    return values


def update_env(updates: dict[str, str]) -> bool:
    """Обновляет/добавляет ключи в .env, сохраняя остальные строки и комментарии."""
    lines: list[str] = []
    if paths.ENV_FILE.exists():
        try:
            lines = paths.ENV_FILE.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            print(f"[settings] WARN: could not read .env: {e}")
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)
    for key, val in remaining.items():
        out.append(f"{key}={val}")
    try:
        paths.ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        paths.ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
        return True
    except OSError as e:
        print(f"[settings] ERROR: could not write .env: {e}")
        return False


# ── UI ────────────────────────────────────────────────────────────────
class SettingsWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Smart Zones Pro — Settings")
        self.geometry("560x780")
        self.minsize(520, 640)
        self.configure(bg=ui.CARD_BOT, padx=18, pady=18)
        self._style_ttk()

        self._brokers = load_brokers()
        self._env = _read_env()
        self._broker_vars: list[dict[str, tk.Variable]] = []
        self._active_var = tk.IntVar(value=self._brokers.get("active_broker", 0))

        self._build_ui()

    def _style_ttk(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("TCombobox", fieldbackground=ui.FIELD_BG, background=ui.CARD_FLAT,
                     foreground=ui.TXT, arrowcolor=ui.TXT_DIM, borderwidth=0,
                     padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", ui.FIELD_BG)],
               foreground=[("readonly", ui.TXT)])

    def _label(self, parent, text, **kw):
        return tk.Label(parent, text=text, fg=ui.TXT, bg=parent["bg"],
                        font=(ui.FONT, 9), anchor="w", **kw)

    def _build_ui(self):
        tk.Label(self, text="Smart Zones Pro", fg=ui.TXT, bg=ui.CARD_BOT,
                 font=(ui.FONT, 17, "bold")).pack(anchor="w")
        tk.Label(self, text="NoName Trader · подключение брокера и источник данных",
                 fg=ui.GOLD, bg=ui.CARD_BOT, font=(ui.FONT, 9, "bold")).pack(anchor="w", pady=(0, 12))

        # ── Data source ──
        ds_frame = tk.Frame(self, bg=ui.CARD_BOT)
        ds_frame.pack(fill="x", pady=(0, 8))
        self._label(ds_frame, "Источник данных (DATA_SOURCE):").pack(side="left")
        self._data_source = tk.StringVar(value=self._env.get("DATA_SOURCE", "mt5"))
        ttk.Combobox(ds_frame, textvariable=self._data_source, values=DATA_SOURCES,
                     state="readonly", width=14).pack(side="left", padx=8)

        # ── Buttons (pinned to bottom so they're always visible) ──
        btns = tk.Frame(self, bg=ui.CARD_BOT)
        btns.pack(side="bottom", fill="x", pady=(12, 0))
        ui.GlassButton(btns, "Сохранить", command=self._save, width=150,
                       height=40, kind="primary", bg=ui.CARD_BOT).pack(side="left")
        ui.GlassButton(btns, "Закрыть", command=self.destroy, width=110,
                       height=40, kind="ghost", bg=ui.CARD_BOT).pack(side="right")

        # ── Telegram (also pinned above the buttons) ──
        tg_box = tk.LabelFrame(self, text=" Telegram alerts ", fg=ui.TXT_DIM,
                               bg=ui.CARD_BOT, font=(ui.FONT, 9, "bold"),
                               bd=1, relief="solid", padx=10, pady=10)
        tg_box.pack(side="bottom", fill="x", pady=8)
        self._tg_enabled = tk.BooleanVar(
            value=str(self._env.get("ENABLE_TELEGRAM", "false")).lower() in {"1", "true", "yes", "on"})
        tk.Checkbutton(tg_box, text="Enable Telegram", variable=self._tg_enabled,
                       fg=ui.TXT, bg=ui.CARD_BOT, selectcolor=ui.FIELD_BG,
                       activebackground=ui.CARD_BOT, activeforeground=ui.TXT,
                       font=(ui.FONT, 9)).pack(anchor="w")
        self._tg_token = tk.StringVar(value=self._env.get("TELEGRAM_BOT_TOKEN", ""))
        self._tg_chat = tk.StringVar(value=self._env.get("TELEGRAM_CHAT_ID", ""))
        self._row(tg_box, "Bot token", self._tg_token)
        self._row(tg_box, "Chat id", self._tg_chat)

        # ── Brokers (takes the remaining space) ──
        brokers_box = tk.LabelFrame(self, text=" MT5 Brokers ", fg=ui.TXT_DIM,
                                    bg=ui.CARD_BOT, font=(ui.FONT, 9, "bold"),
                                    bd=1, relief="solid", padx=10, pady=10)
        brokers_box.pack(fill="both", expand=True, pady=8)

        for i, b in enumerate(self._brokers["brokers"][:BROKER_SLOTS]):
            slot = tk.Frame(brokers_box, bg=ui.CARD_FLAT, padx=10, pady=8,
                            highlightthickness=1, highlightbackground=ui.STROKE_SOFT)
            slot.pack(fill="x", pady=5)
            top = tk.Frame(slot, bg=ui.CARD_FLAT)
            top.pack(fill="x")
            tk.Radiobutton(top, text="Active", variable=self._active_var, value=i,
                           fg=ui.OK, bg=ui.CARD_FLAT, selectcolor=ui.FIELD_BG,
                           activebackground=ui.CARD_FLAT, activeforeground=ui.OK,
                           font=(ui.FONT, 8, "bold")).pack(side="right")
            vars_ = {
                "name": tk.StringVar(value=str(b.get("name", ""))),
                "server": tk.StringVar(value=str(b.get("server", ""))),
                "login": tk.StringVar(value=str(b.get("login", "") or "")),
                "password": tk.StringVar(value=str(b.get("password", ""))),
                "path": tk.StringVar(value=str(b.get("path", ""))),
            }
            self._broker_vars.append(vars_)
            self._row(slot, "Name", vars_["name"])
            self._row(slot, "Server", vars_["server"])
            self._row(slot, "Login", vars_["login"])
            self._row(slot, "Password", vars_["password"], show="*")
            self._row(slot, "MT5 Path (optional)", vars_["path"])

    def _row(self, parent, label, var, show=None):
        row = tk.Frame(parent, bg=parent["bg"])
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, fg=ui.TXT_DIM, bg=parent["bg"], width=18,
                 anchor="w", font=(ui.FONT, 8)).pack(side="left")
        entry = tk.Entry(row, textvariable=var, show=show, font=(ui.FONT, 9))
        ui.style_entry(entry)
        entry.pack(side="left", fill="x", expand=True, ipady=3)

    def _collect_brokers(self) -> dict:
        brokers = []
        for vars_ in self._broker_vars:
            login_raw = vars_["login"].get().strip()
            try:
                login = int(login_raw) if login_raw else 0
            except ValueError:
                login = 0
            brokers.append({
                "name": vars_["name"].get().strip(),
                "server": vars_["server"].get().strip(),
                "login": login,
                "password": vars_["password"].get(),
                "path": vars_["path"].get().strip(),
            })
        return {"active_broker": int(self._active_var.get()), "brokers": brokers}

    def _save(self):
        ok_brokers = save_brokers(self._collect_brokers())
        ok_env = update_env({
            "DATA_SOURCE": self._data_source.get(),
            "ENABLE_TELEGRAM": "true" if self._tg_enabled.get() else "false",
            "TELEGRAM_BOT_TOKEN": self._tg_token.get().strip(),
            "TELEGRAM_CHAT_ID": self._tg_chat.get().strip(),
        })
        if ok_brokers and ok_env:
            messagebox.showinfo(
                "Saved",
                "Настройки сохранены.\nИзменения вступят в силу при следующем "
                "пересчёте зон / перезапуске приложения.")
            self.destroy()
        else:
            messagebox.showerror(
                "Error",
                f"Не удалось сохранить настройки:\n"
                f"brokers.json: {'ok' if ok_brokers else 'FAIL'} ({paths.BROKERS_FILE})\n"
                f".env: {'ok' if ok_env else 'FAIL'} ({paths.ENV_FILE})")


def open_settings_window():
    """Открыть окно настроек (блокирует до закрытия — запускать в своём процессе)."""
    SettingsWindow().mainloop()


if __name__ == "__main__":
    open_settings_window()
