"""
ui_theme.py — единая «liquid glass» тема для Tkinter-окон Smart Zones Pro.

Даёт согласованную матовую тёмную палитру, скруглённые «стеклянные» карточки,
скруглённые кнопки и поля ввода. Используется окнами пароля, сплэша и настроек,
чтобы весь интерфейс выглядел в одном стиле.

Скругление углов окна делается через `-transparentcolor` (Windows). На платформах
без этой опции всё мягко деградирует до обычной тёмной карточки.
"""
from __future__ import annotations

import tkinter as tk

# ── Палитра ────────────────────────────────────────────────────────────
CHROMA        = "#ff00ff"          # цвет-ключ для прозрачных углов (Windows)

BG_BASE       = "#0a0b0d"          # фон «пустоты» вокруг карточки (почти чёрный)
CARD_TOP      = "#17191d"          # верх «приподнятой» карточки
CARD_BOT      = "#0e0f11"          # низ / базовый цвет панели
CARD_FLAT     = "#141518"          # усреднённый матовый цвет карточки
CARD_HI       = "#1c1e22"          # активная «пилюля» (чуть светлее)
FIELD_BG      = "#0b0c0e"          # фон полей ввода
STROKE        = "#26282d"          # тонкая обводка
STROKE_SOFT   = "#1a1c1f"

TXT           = "#f2f4f5"          # основной текст (почти белый)
TXT_DIM       = "#8b9096"          # вторичный текст
TXT_MUTE      = "#5f646a"          # подписи секций (капс)
ACCENT        = "#a6e22e"          # основной акцент (лаймово-зелёный)
ACCENT_DK     = "#8fce1f"          # акцент при наведении
ACCENT_GLOW   = "#3f5a12"          # тёмно-зелёное «свечение» для tk
ACCENT_TXT    = "#0b0e08"          # тёмный текст на зелёной кнопке
GOLD          = "#a6e22e"          # бренд-акцент (совместимость → зелёный)
OK            = "#a6e22e"
BAD           = "#f2556b"

FONT          = "Segoe UI"
FONT_MONO     = "Consolas"


def round_rect(cv: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Рисует скруглённый прямоугольник (гладкий полигон) на Canvas."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, **kw)


def make_glass_window(root: tk.Misc, w: int, h: int, *, radius: int = 22,
                      draggable: bool = True) -> tk.Canvas:
    """
    Превращает окно (Tk/Toplevel) в безрамочную «стеклянную» карточку со
    скруглёнными углами и центрирует его. Возвращает Canvas, на котором уже
    нарисована карточка — на него можно класть виджеты через `.create_window`
    или размещать обычные виджеты (у них bg = CARD_FLAT).
    """
    root.overrideredirect(True)
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    ws = root.winfo_screenwidth()
    hs = root.winfo_screenheight()
    x, y = int(ws / 2 - w / 2), int(hs / 2 - h / 2)
    root.geometry(f"{w}x{h}+{x}+{y}")

    transparent_ok = False
    try:
        root.configure(bg=CHROMA)
        root.attributes("-transparentcolor", CHROMA)
        transparent_ok = True
    except tk.TclError:
        root.configure(bg=BG_BASE)

    cv = tk.Canvas(root, width=w, height=h, highlightthickness=0,
                   bg=CHROMA if transparent_ok else BG_BASE)
    cv.pack(fill="both", expand=True)

    # Тень (мягкая, только если есть прозрачность углов)
    if transparent_ok:
        for i, col in enumerate(("#050506", "#08090b", "#0b0c0e")):
            off = 6 - i * 2
            round_rect(cv, off, off + 4, w - off, h - off + 4, radius,
                       fill=col, outline="")

    # Тело карточки + вертикальный «градиент» двумя слоями
    round_rect(cv, 4, 4, w - 4, h - 4, radius, fill=CARD_BOT, outline="")
    round_rect(cv, 4, 4, w - 4, int(h * 0.6), radius, fill=CARD_TOP, outline="")
    round_rect(cv, 4, 4, w - 4, h - 4, radius, fill="", outline=STROKE, width=1)

    if draggable:
        _enable_drag(root, cv)
    return cv


def _enable_drag(root: tk.Misc, widget: tk.Misc):
    st = {"x": 0, "y": 0}

    def press(e):
        st["x"], st["y"] = e.x_root, e.y_root

    def move(e):
        dx, dy = e.x_root - st["x"], e.y_root - st["y"]
        st["x"], st["y"] = e.x_root, e.y_root
        root.geometry(f"+{root.winfo_x() + dx}+{root.winfo_y() + dy}")

    widget.bind("<Button-1>", press, add="+")
    widget.bind("<B1-Motion>", move, add="+")


class GlassButton(tk.Canvas):
    """Скруглённая «стеклянная» кнопка с hover-эффектом."""

    def __init__(self, parent, text, command=None, *, width=120, height=38,
                 kind="primary", radius=14, bg=CARD_FLAT):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bg=bg, cursor="hand2")
        self._cmd = command
        self._bw, self._bh, self._br = width, height, radius
        self._kind = kind
        # (fill, hover_fill, text, outline)
        self._fills = {
            "primary": (ACCENT, ACCENT_DK, ACCENT_TXT, ""),
            "ghost":   (CARD_HI, "#24262b", TXT, STROKE),
            "danger":  (BAD, "#d8465a", "#ffffff", ""),
        }
        self.bind("<Enter>", lambda e: self._render(True))
        self.bind("<Leave>", lambda e: self._render(False))
        self.bind("<Button-1>", self._click)
        self._text = text
        self._render(False)

    def _render(self, hover):
        self.delete("all")
        base, dark, fg, outline = self._fills.get(self._kind, self._fills["ghost"])
        fill = dark if hover else base
        round_rect(self, 1, 1, self._bw - 1, self._bh - 1, self._br,
                   fill=fill, outline=outline, width=1)
        self.create_text(self._bw / 2, self._bh / 2, text=self._text,
                         fill=fg, font=(FONT, 10, "bold"))

    def _click(self, _e):
        if self._cmd:
            self._cmd()


def style_entry(entry: tk.Entry):
    """Единый стиль для tk.Entry (тёмное поле, светлый текст)."""
    entry.configure(bg=FIELD_BG, fg=TXT, insertbackground=ACCENT,
                    relief="flat", highlightthickness=1,
                    highlightbackground=STROKE_SOFT, highlightcolor=ACCENT)
