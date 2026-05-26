"""
telegram_bot.py — отправка уведомлений в Telegram.

Минимальный модуль на чистом requests.sendMessage (без aiogram / asyncio):
этого достаточно для триггеров типа "цена приблизилась к зоне" и дневных сводок.

Использует значения из .env (через config.py):
  ENABLE_TELEGRAM, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

import requests

import config


# ── Низкий уровень ────────────────────────────────────────────────────

def _is_configured() -> bool:
    if not config.ENABLE_TELEGRAM:
        return False
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN.strip() in {"", "ВАШ_ТОКЕН"}:
        return False
    if not config.TELEGRAM_CHAT_ID or str(config.TELEGRAM_CHAT_ID).strip() in {"", "ВАШ_ЧАТ_ID"}:
        return False
    return True


def send_telegram_message(text: str, *, parse_mode: str = "HTML",
                         disable_preview: bool = True) -> bool:
    """Отправляет текстовое сообщение в заданный чат Telegram.

    Возвращает True если сообщение ушло, False иначе (включая случай когда
    Telegram отключён или не настроен — в этом случае ошибки не считаются).
    """
    if not _is_configured():
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[telegram] send failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"[telegram] response: {e.response.text}")
        return False


# ── Высокий уровень: красивые сообщения ───────────────────────────────

_ALERT_RE = re.compile(
    r"ALERT:\s*Price\s+(?P<price>[-\d.]+)\s+is\s+(?P<dist>[-\d.]+)\$\s+"
    r"(?P<dir>ABOVE|BELOW)\s+zone\s+(?P<zone>[-\d.]+)\s*\(S:(?P<score>\d+)\)",
    re.IGNORECASE,
)


def format_alert(line: str, symbol: Optional[str] = None) -> str:
    """Превращает строку алерта от MT4 в красиво отформатированный HTML."""
    sym = symbol or config.SYMBOL
    m = _ALERT_RE.search(line)
    if not m:
        # Fallback — просто моноширинный код
        return f"🚨 <b>Smart Zones — {sym}</b>\n<code>{line.strip()}</code>"

    d = m.groupdict()
    arrow = "🔻" if d["dir"].upper() == "BELOW" else "🔺"
    score = int(d["score"])
    if score >= 13:
        stars = "⭐⭐⭐"
    elif score >= 11:
        stars = "⭐⭐"
    elif score >= 9:
        stars = "⭐"
    else:
        stars = ""

    parts = [
        f"🚨 <b>{sym} — Zone Alert</b>",
        f"{arrow} Price <b>{d['price']}</b> is <b>{d['dist']}$</b> {d['dir'].lower()} zone <b>{d['zone']}</b>",
        f"Score: <b>{score}</b> {stars}".rstrip(),
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>",
    ]
    return "\n".join(parts)


def send_alert_line(line: str, *, symbol: Optional[str] = None) -> bool:
    """Отправить одну строку алерта из tg_alerts.txt — с красивым форматированием."""
    return send_telegram_message(format_alert(line, symbol=symbol))


def send_zones_update(zones: Iterable[dict], *, symbol: Optional[str] = None) -> bool:
    """Краткая сводка по только что пересчитанным зонам."""
    sym = symbol or config.SYMBOL
    zlist = list(zones)
    if not zlist:
        return False

    head = f"📊 <b>{sym} — Zones updated</b> ({len(zlist)})"
    rows = []
    for z in zlist[: config.MAX_ZONES_ON_CHART]:
        price = z.get("price", 0)
        score = z.get("score", 0)
        sources = z.get("sources") or z.get("label") or ""
        bp = " 🐋" if z.get("has_big_player") or z.get("big_player") else ""
        rows.append(f"• <b>{price:.2f}</b>  S:{score}  <i>{sources}</i>{bp}")

    body = "\n".join(rows)
    footer = f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
    return send_telegram_message(f"{head}\n{body}\n{footer}")


def send_test_message() -> bool:
    """Проверка что бот настроен корректно."""
    msg = (
        "✅ <b>Smart Zones Pro — test</b>\n"
        f"Bot is connected. Symbol: <b>{config.SYMBOL}</b>\n"
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
    )
    return send_telegram_message(msg)


# ── Локальный тест ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing Telegram Integration...")
    print(f"  ENABLE_TELEGRAM = {config.ENABLE_TELEGRAM}")
    print(f"  TOKEN configured = {bool(config.TELEGRAM_BOT_TOKEN)}")
    print(f"  CHAT_ID configured = {bool(config.TELEGRAM_CHAT_ID)}")
    if not _is_configured():
        print("  → Telegram is NOT configured. Edit .env and rerun.")
    else:
        ok = send_test_message()
        print(f"  → send_test_message returned: {ok}")
