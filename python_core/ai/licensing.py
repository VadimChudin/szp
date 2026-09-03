"""
licensing.py — Офлайн-лицензии для ИИ-слоя.

Схема
-----
Ключ продукта — это подписанный токен. Внутри: срок действия и отпечаток
машины. В приложении лежит только публичный ключ Ed25519, поэтому проверить
подпись можно, а выпустить новый ключ — нет. Приватный ключ живёт только в
генераторе (ai/keygen.py) на машине разработчика.

Формат токена (компактный, вставляется копипастой):

    SZP1-XXXXX-XXXXX-...        base32 Crockford, группы по 5

    payload (28 байт)           подпись (64 байта)
    ├ ver     1B                └ Ed25519 над payload
    ├ flags   1B  bit0 = привязан к железу
    ├ exp     4B  unix-время, 0 = навсегда
    ├ issued  4B  unix-время выпуска
    └ hw      18B три отпечатка по 6 байт (или нули)

Привязка к железу: 2 из 3
-------------------------
Отпечаток собирается из трёх независимых компонентов (machine GUID, серийник
системного диска, модель CPU). Совпадения двух достаточно. Жёсткая привязка
ко всем трём ломала бы лицензию при замене диска или переустановке Windows —
это поток жалоб вместо защиты.

Защита от отката часов
----------------------
Клиент может перевести системное время назад и получить «навсегда» бесплатно.
Три барьера:
  1. `exp` внутри подписи — в файле его не поправить;
  2. `last_seen` — максимальное когда-либо виденное время, хранится с HMAC;
  3. внешний якорь — время последней свечи Dukascopy, его открутить нельзя.
Действующее время = max(системное, якорь, last_seen). Откат часов назад
просто не влияет на расчёт срока.

Взлом
-----
Подпись подделать нельзя, но пропатчить проверку в бинаре — можно, как в любом
клиентском софте. Схема защищает от передачи ключа знакомым и от «вечной
триалки», а не от реверс-инженера. Больше усилий здесь не оправдано.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from ai import ed25519

# ── Публичный ключ ──────────────────────────────────────────────────────────
# Заполняется один раз: `python -m ai.keygen init` печатает строку для вставки.
# Пустое значение = ИИ заблокирован (ключи ещё не выпускались).
PUBLIC_KEY_HEX = ""

TOKEN_PREFIX = "SZP1"
PAYLOAD_SIZE = 28
SIGNATURE_SIZE = 64
HW_SLOT_SIZE = 6

FOREVER = 0
CLOCK_TOLERANCE_SEC = 86_400  # сутки на часовые пояса и лёгкий дрейф

# base32 Crockford: без I, L, O, U — не спутать с 1, 0
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {c: i for i, c in enumerate(_ALPHABET)}
_DECODE.update({"I": 1, "L": 1, "O": 0})

# ── Статусы ─────────────────────────────────────────────────────────────────
VALID = "VALID"
NONE = "NONE"
MALFORMED = "MALFORMED"
BAD_SIGNATURE = "BAD_SIGNATURE"
EXPIRED = "EXPIRED"
WRONG_MACHINE = "WRONG_MACHINE"
NO_PUBLIC_KEY = "NO_PUBLIC_KEY"

_MESSAGES = {
    VALID: "ИИ активен",
    NONE: "Ключ продукта не введён",
    MALFORMED: "Ключ повреждён — проверьте, что скопирован полностью",
    BAD_SIGNATURE: "Ключ недействителен",
    EXPIRED: "Срок действия ключа истёк",
    WRONG_MACHINE: "Ключ выпущен для другого компьютера",
    NO_PUBLIC_KEY: "Сборка без публичного ключа — ИИ недоступен",
}


@dataclass
class Payload:
    """Расшифрованное содержимое ключа."""
    version: int = 1
    bound: bool = True
    expires_at: int = FOREVER
    issued_at: int = 0
    hw_slots: list[bytes] = field(default_factory=list)

    @property
    def forever(self) -> bool:
        return self.expires_at == FOREVER

    def days_left(self, now: int) -> float | None:
        if self.forever:
            return None
        return max(0.0, (self.expires_at - now) / 86_400.0)


@dataclass
class Status:
    """Итог проверки. `ok` — единственное, что решает, включать ли ИИ."""
    state: str = NONE
    payload: Payload | None = None
    clock_tampered: bool = False

    @property
    def ok(self) -> bool:
        return self.state == VALID

    @property
    def message(self) -> str:
        text = _MESSAGES.get(self.state, self.state)
        if self.ok and self.payload:
            if self.payload.forever:
                return "ИИ активен — бессрочный ключ"
            left = self.payload.days_left(_effective_now())
            return f"ИИ активен — осталось {left:.1f} дн."
        return text

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "state": self.state,
            "message": self.message,
            "forever": bool(self.payload and self.payload.forever),
            "expires_at": self.payload.expires_at if self.payload else 0,
            "clock_tampered": self.clock_tampered,
        }


# ── Кодирование токена ──────────────────────────────────────────────────────
def _b32_encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    total_bits = len(raw) * 8
    chars = (total_bits + 4) // 5
    out = []
    for shift in range(chars - 1, -1, -1):
        out.append(_ALPHABET[(number >> (shift * 5)) & 0x1F])
    return "".join(out)


def _b32_decode(text: str, size: int) -> bytes | None:
    number = 0
    for char in text:
        value = _DECODE.get(char.upper())
        if value is None:
            return None
        number = (number << 5) | value
    try:
        return number.to_bytes(size, "big")
    except OverflowError:
        return None


def _group(text: str, size: int = 5) -> str:
    return "-".join(text[i:i + size] for i in range(0, len(text), size))


def encode_token(payload: Payload, signature: bytes) -> str:
    """Собирает человекочитаемый ключ. Используется генератором."""
    return f"{TOKEN_PREFIX}-{_group(_b32_encode(pack(payload) + signature))}"


def pack(payload: Payload) -> bytes:
    """payload -> 28 байт, ровно те, что подписываются."""
    slots = list(payload.hw_slots)[:3]
    while len(slots) < 3:
        slots.append(b"\x00" * HW_SLOT_SIZE)
    blob = bytes([payload.version, 0x01 if payload.bound else 0x00])
    blob += int(payload.expires_at).to_bytes(4, "big")
    blob += int(payload.issued_at).to_bytes(4, "big")
    for slot in slots:
        blob += slot[:HW_SLOT_SIZE].ljust(HW_SLOT_SIZE, b"\x00")
    return blob


def unpack(blob: bytes) -> Payload | None:
    if len(blob) != PAYLOAD_SIZE:
        return None
    slots = [blob[10 + i * HW_SLOT_SIZE:10 + (i + 1) * HW_SLOT_SIZE]
             for i in range(3)]
    return Payload(
        version=blob[0],
        bound=bool(blob[1] & 0x01),
        expires_at=int.from_bytes(blob[2:6], "big"),
        issued_at=int.from_bytes(blob[6:10], "big"),
        hw_slots=slots,
    )


def split_token(text: str) -> tuple[Payload, bytes] | None:
    """Ключ -> (payload, подпись). None, если строка не похожа на ключ."""
    if not text:
        return None
    cleaned = "".join(ch for ch in str(text).strip().upper()
                      if ch.isalnum())
    if cleaned.startswith(TOKEN_PREFIX):
        cleaned = cleaned[len(TOKEN_PREFIX):]
    raw = _b32_decode(cleaned, PAYLOAD_SIZE + SIGNATURE_SIZE)
    if raw is None:
        return None
    payload = unpack(raw[:PAYLOAD_SIZE])
    if payload is None or payload.version != 1:
        return None
    return payload, raw[PAYLOAD_SIZE:]


# ── Отпечаток машины ────────────────────────────────────────────────────────
def _slot(value: str | None) -> bytes:
    """Компонент -> 6 байт. Пустой компонент даёт нули и в зачёт не идёт."""
    if not value:
        return b"\x00" * HW_SLOT_SIZE
    return hashlib.sha256(str(value).strip().lower().encode()).digest()[:HW_SLOT_SIZE]


def _machine_guid() -> str | None:
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Cryptography")
            with key:
                return winreg.QueryValueEx(key, "MachineGuid")[0]
        except Exception:
            return None
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            return Path(path).read_text().strip() or None
        except OSError:
            continue
    return None


def _volume_serial() -> str | None:
    """Серийник системного тома. Через ctypes — без вызова wmic и без окон."""
    if sys.platform == "win32":
        try:
            import ctypes
            serial = ctypes.c_ulong(0)
            root = os.environ.get("SystemDrive", "C:") + "\\"
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root), None, 0, ctypes.byref(serial),
                None, None, None, 0)
            return str(serial.value) if ok and serial.value else None
        except Exception:
            return None
    try:
        stat = os.stat("/")
        return str(stat.st_dev)
    except OSError:
        return None


def _cpu_id() -> str | None:
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            with key:
                name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
            return f"{name}|{os.cpu_count()}"
        except Exception:
            pass
    model = platform.processor() or platform.machine()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return f"{model}|{os.cpu_count()}" if model else None


def hardware_slots() -> list[bytes]:
    """Три отпечатка текущей машины в фиксированном порядке."""
    return [_slot(_machine_guid()), _slot(_volume_serial()), _slot(_cpu_id())]


def machine_code() -> str:
    """Код машины, который клиент присылает для выпуска ключа.

    Внутри — те самые три отпечатка по 6 байт, а не их хеш: генератор должен
    восстановить слоты, чтобы вписать их в ключ. 18 байт -> 29 символов.
    """
    return _group(_b32_encode(b"".join(hardware_slots())), 5)


def slots_from_code(code: str) -> list[bytes] | None:
    """Обратная операция для генератора ключей."""
    cleaned = "".join(ch for ch in str(code or "").strip().upper()
                      if ch.isalnum())
    raw = _b32_decode(cleaned, 3 * HW_SLOT_SIZE)
    if raw is None:
        return None
    return [raw[i * HW_SLOT_SIZE:(i + 1) * HW_SLOT_SIZE] for i in range(3)]


def slots_match(token_slots: list[bytes], machine_slots: list[bytes]) -> bool:
    """Политика 2-из-3. Нулевые слоты в зачёт не идут."""
    empty = b"\x00" * HW_SLOT_SIZE
    hits = sum(1 for a, b in zip(token_slots, machine_slots)
               if a == b and a != empty)
    return hits >= 2


# ── Хранение и защита времени ───────────────────────────────────────────────
def storage_dir() -> Path:
    override = os.environ.get("SZP_LICENSE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "SmartZonesPro"


def _license_file() -> Path:
    return storage_dir() / "license.dat"


def _state_file() -> Path:
    return storage_dir() / "license.state"


def _state_mac(body: str) -> str:
    key = b"".join(hardware_slots()) + b"szp-license-state"
    return hmac.new(key, body.encode(), hashlib.sha256).hexdigest()[:32]


def _read_state() -> dict:
    try:
        raw = json.loads(_state_file().read_text(encoding="utf-8"))
        body = json.dumps(raw.get("data", {}), sort_keys=True)
        if not hmac.compare_digest(raw.get("mac", ""), _state_mac(body)):
            return {}
        return raw.get("data", {})
    except (OSError, ValueError, TypeError):
        return {}


def _write_state(data: dict) -> None:
    try:
        storage_dir().mkdir(parents=True, exist_ok=True)
        body = json.dumps(data, sort_keys=True)
        _state_file().write_text(
            json.dumps({"data": data, "mac": _state_mac(body)}),
            encoding="utf-8")
    except OSError:
        pass


_time_anchor: int = 0


def set_time_anchor(timestamp: int | float | None) -> None:
    """Внешний источник времени — время последней свечи Dukascopy.

    Его нельзя открутить локально, поэтому он и закрывает дыру с часами.
    """
    global _time_anchor
    try:
        value = int(timestamp or 0)
    except (TypeError, ValueError):
        return
    if value > _time_anchor:
        _time_anchor = value


def _effective_now() -> int:
    """max(системное, якорь, последнее виденное) — откат назад бесполезен."""
    now = int(time.time())
    seen = int(_read_state().get("last_seen", 0) or 0)
    return max(now, _time_anchor, seen)


def _remember_now(now: int) -> bool:
    """Обновляет last_seen. True, если обнаружен откат часов."""
    state = _read_state()
    seen = int(state.get("last_seen", 0) or 0)
    tampered = int(time.time()) < seen - CLOCK_TOLERANCE_SEC
    if now > seen or tampered:
        state["last_seen"] = max(now, seen)
        if tampered:
            state["clock_tampered"] = True
        _write_state(state)
    return tampered or bool(state.get("clock_tampered"))


# ── Проверка ────────────────────────────────────────────────────────────────
def public_key_bytes() -> bytes | None:
    text = (PUBLIC_KEY_HEX or os.environ.get("SZP_PUBLIC_KEY", "")).strip()
    if len(text) != 64:
        return None
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        return None
    # Повреждённый или вырожденный ключ принимал бы любую подпись — считаем,
    # что публичного ключа нет вовсе, и честно блокируем ИИ.
    if ed25519.is_weak_key(raw):
        return None
    return raw


def verify_token(token: str, *, now: int | None = None,
                 machine_slots: list[bytes] | None = None) -> Status:
    """Чистая проверка ключа без обращения к диску. Удобно тестировать."""
    pub = public_key_bytes()
    if pub is None:
        return Status(state=NO_PUBLIC_KEY)
    if not token:
        return Status(state=NONE)

    parts = split_token(token)
    if parts is None:
        return Status(state=MALFORMED)
    payload, signature = parts

    if not ed25519.verify(pub, pack(payload), signature):
        return Status(state=BAD_SIGNATURE, payload=payload)

    if payload.bound:
        slots = machine_slots if machine_slots is not None else hardware_slots()
        if not slots_match(payload.hw_slots, slots):
            return Status(state=WRONG_MACHINE, payload=payload)

    moment = _effective_now() if now is None else int(now)
    if not payload.forever and moment >= payload.expires_at:
        return Status(state=EXPIRED, payload=payload)

    return Status(state=VALID, payload=payload)


def activate(token: str) -> Status:
    """Проверяет ключ и, если он годен, сохраняет. Вызывается из интерфейса."""
    status = verify_token(token)
    if status.ok:
        try:
            storage_dir().mkdir(parents=True, exist_ok=True)
            _license_file().write_text(token.strip(), encoding="utf-8")
        except OSError as exc:
            print(f"[license] WARN: не удалось сохранить ключ: {exc}")
    return status


def stored_token() -> str:
    try:
        return _license_file().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def deactivate() -> None:
    for path in (_license_file(), _state_file()):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def current_status() -> Status:
    """Статус сохранённого ключа. Единственная точка правды для ИИ-слоя."""
    token = stored_token()
    if not token:
        return Status(state=NONE)
    moment = _effective_now()
    status = verify_token(token, now=moment)
    status.clock_tampered = _remember_now(moment)
    if status.clock_tampered and not status.payload:
        return status
    return status


def ai_enabled() -> bool:
    """Истёк ключ — ИИ выключается сам, продукт работает в обычном режиме."""
    try:
        return current_status().ok
    except Exception as exc:
        print(f"[license] проверка не удалась, ИИ выключен: {exc}")
        return False
