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
VALIDATION_MODES = ["validate", "canonical", "off"]
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
        self.configure(bg=ui.CARD_BOT, padx=22, pady=20)
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
                 font=(ui.FONT, 19, "bold")).pack(anchor="w")
        tk.Label(self, text="MARKET DATA  /  SETTINGS",
                 fg=ui.AQUA, bg=ui.CARD_BOT,
                 font=(ui.FONT, 8, "bold")).pack(anchor="w", pady=(3, 18))

        # ── Data source ──
        ds_frame = tk.Frame(self, bg=ui.CARD_BOT)
        ds_frame.pack(fill="x", pady=(0, 8))
        self._label(ds_frame, "Источник данных (DATA_SOURCE):").pack(side="left")
        self._data_source = tk.StringVar(value=self._env.get("DATA_SOURCE", "mt5"))
        ttk.Combobox(ds_frame, textvariable=self._data_source, values=DATA_SOURCES,
                     state="readonly", width=14).pack(side="left", padx=8)

        # ── Валидация зон по внешнему эталону (Dukascopy) ──
        # Клиент просил возможность ВЫКЛЮЧАТЬ валидацию: раньше режим задавался
        # только переменной VALIDATION_MODE в .env, руками.
        val_box = tk.LabelFrame(self, text="  ВАЛИДАЦИЯ ЗОН (DUKASCOPY)  ", fg=ui.AQUA,
                                bg=ui.CARD_BOT, font=(ui.FONT, 8, "bold"),
                                bd=1, relief="solid", padx=10, pady=10)
        val_box.pack(fill="x", pady=8)

        val_row = tk.Frame(val_box, bg=ui.CARD_BOT)
        val_row.pack(fill="x")
        self._label(val_row, "Режим (VALIDATION_MODE):").pack(side="left")
        self._validation_mode = tk.StringVar(
            value=str(self._env.get("VALIDATION_MODE", "validate")).strip().lower())
        ttk.Combobox(val_row, textvariable=self._validation_mode, values=VALIDATION_MODES,
                     state="readonly", width=14).pack(side="left", padx=8)

        tk.Label(val_box, text=("validate — показывать только зоны, подтверждённые эталонным фидом\n"
                                "canonical — считать зоны целиком по Dukascopy (одинаковы у всех брокеров)\n"
                                "off — без валидации, зоны как их посчитал брокерский фид"),
                 fg=ui.TXT_DIM, bg=ui.CARD_BOT, font=(ui.FONT, 8),
                 justify="left", anchor="w").pack(fill="x", pady=(6, 4))

        self._broker_offset = tk.BooleanVar(
            value=str(self._env.get("BROKER_OFFSET_ENABLED", "true")).lower() in {"1", "true", "yes", "on"})
        tk.Checkbutton(val_box, text="Сдвигать линии на оффсет брокера (BROKER_OFFSET_ENABLED)",
                       variable=self._broker_offset,
                       fg=ui.TXT, bg=ui.CARD_BOT, selectcolor=ui.FIELD_BG,
                       activebackground=ui.CARD_BOT, activeforeground=ui.TXT,
                       font=(ui.FONT, 9)).pack(anchor="w")

        self._validation_tolerance = tk.StringVar(
            value=str(self._env.get("VALIDATION_TOLERANCE", "5.0")))
        self._row(val_box, "Допуск совпадения, $", self._validation_tolerance)

        # ── Скоп и число красных линий ──
        zone_box = tk.LabelFrame(self, text="  ЗОНЫ НА ГРАФИКЕ  ", fg=ui.AQUA,
                                 bg=ui.CARD_BOT, font=(ui.FONT, 8, "bold"),
                                 bd=1, relief="solid", padx=10, pady=10)
        zone_box.pack(fill="x", pady=8)
        self._zone_scope = tk.StringVar(
            value=str(self._env.get("ZONE_SCOPE_PIPS", "800")))
        self._max_zones = tk.StringVar(
            value=str(self._env.get("MAX_ZONES_ON_CHART", "6")))
        self._row(zone_box, "Скоп, пункты", self._zone_scope)
        tk.Label(zone_box,
                 text="Любое положительное число. Половина вверх и половина вниз от цены.",
                 fg=ui.TXT_DIM, bg=ui.CARD_BOT, font=(ui.FONT, 8),
                 justify="left", wraplength=520, anchor="w").pack(fill="x", pady=(0, 4))
        self._row(zone_box, "Макс. зон на графике", self._max_zones)
        tk.Label(zone_box,
                 text="Общий лимит, без схемы 3+3. Если реальных зон меньше — рисуем сколько есть.",
                 fg=ui.TXT_DIM, bg=ui.CARD_BOT, font=(ui.FONT, 8),
                 justify="left", wraplength=520, anchor="w").pack(fill="x")

        # ── Buttons (pinned to bottom so they're always visible) ──
        btns = tk.Frame(self, bg=ui.CARD_BOT)
        btns.pack(side="bottom", fill="x", pady=(12, 0))
        ui.GlassButton(btns, "Сохранить", command=self._save, width=150,
                       height=40, kind="primary", bg=ui.CARD_BOT).pack(side="left")
        ui.GlassButton(btns, "Закрыть", command=self.destroy, width=110,
                       height=40, kind="ghost", bg=ui.CARD_BOT).pack(side="right")

        # ── Telegram (also pinned above the buttons) ──
        tg_box = tk.LabelFrame(self, text="  TELEGRAM ALERTS  ", fg=ui.AQUA,
                               bg=ui.CARD_BOT, font=(ui.FONT, 8, "bold"),
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
        brokers_box = tk.LabelFrame(self, text="  MT5 BROKERS  ", fg=ui.AQUA,
                                    bg=ui.CARD_BOT, font=(ui.FONT, 8, "bold"),
                                    bd=1, relief="solid", padx=10, pady=10)
        brokers_box.pack(fill="both", expand=True, pady=8)

        active_now = self._active_var.get()
        for i, b in enumerate(self._brokers["brokers"][:BROKER_SLOTS]):
            is_active = (i == active_now)
            slot_bg = ui.CARD_HI if is_active else ui.CARD_FLAT
            # Обёртка + зелёная «свечащаяся» полоса слева у активного слота.
            wrap = tk.Frame(brokers_box, bg=ui.CARD_BOT)
            wrap.pack(fill="x", pady=5)
            tk.Frame(wrap, bg=ui.AQUA if is_active else ui.STROKE_SOFT,
                     width=3).pack(side="left", fill="y")
            slot = tk.Frame(wrap, bg=slot_bg, padx=10, pady=8,
                            highlightthickness=1,
                            highlightbackground=ui.STROKE if is_active else ui.STROKE_SOFT)
            slot.pack(side="left", fill="x", expand=True)
            top = tk.Frame(slot, bg=slot_bg)
            top.pack(fill="x")
            tk.Radiobutton(top, text="Active", variable=self._active_var, value=i,
                           fg=ui.AQUA, bg=slot_bg, selectcolor=ui.FIELD_BG,
                           activebackground=slot_bg, activeforeground=ui.AQUA,
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
        try:
            scope_raw = self._zone_scope.get().replace(" ", "").replace(",", ".")
            max_raw = self._max_zones.get().replace(" ", "")
            scope = float(scope_raw)
            max_zones = int(max_raw)
            if scope <= 0:
                raise ValueError("Скоп должен быть больше 0")
            if not 1 <= max_zones <= 500:
                raise ValueError("Количество зон должно быть от 1 до 500")
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc))
            return

        ok_brokers = save_brokers(self._collect_brokers())
        ok_env = update_env({
            "DATA_SOURCE": self._data_source.get(),
            "VALIDATION_MODE": self._validation_mode.get().strip().lower(),
            "BROKER_OFFSET_ENABLED": "true" if self._broker_offset.get() else "false",
            "VALIDATION_TOLERANCE": self._validation_tolerance.get().strip() or "5.0",
            "ZONE_SCOPE_PIPS": f"{scope:g}",
            "MAX_ZONE_DISTANCE_PIPS": f"{scope / 2.0:g}",
            "MAX_ZONES_ON_CHART": str(max_zones),
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
