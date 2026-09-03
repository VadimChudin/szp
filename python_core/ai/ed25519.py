"""
ed25519.py — Подпись Ed25519 на чистом Python (RFC 8032).

Зачем не библиотека: в проекте нет `cryptography`/PyNaCl, а тянуть их только
ради проверки лицензии — это новая зависимость в PyInstaller (hidden imports,
нативные .dll, лишний повод для антивируса). Проверка выполняется раз в час,
скорость чистого Python (~10 мс) не имеет значения.

Асимметричность — суть схемы: в клиенте лежит только ПУБЛИЧНЫЙ ключ. Даже
полностью разобрав приложение, сгенерировать новый ключ невозможно —
приватный ключ есть только в генераторе на машине разработчика.

Реализация — эталонная из RFC 8032 (расширенные однородные координаты).
Функция sign() нужна только генератору ключей; клиент вызывает verify().
"""
from __future__ import annotations

import hashlib

# ── Параметры кривой edwards25519 ───────────────────────────────────────────
P = 2 ** 255 - 19
Q = 2 ** 252 + 27742317777372353535851937790883648493


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _sha512_modq(data: bytes) -> int:
    return int.from_bytes(_sha512(data), "little") % Q


def _modp_inv(x: int) -> int:
    return pow(x, P - 2, P)


D = -121665 * _modp_inv(121666) % P
_SQRT_M1 = pow(2, (P - 1) // 4, P)


def _recover_x(y: int, sign: int) -> int | None:
    if y >= P:
        return None
    x2 = (y * y - 1) * _modp_inv(D * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * _SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_G_Y = 4 * _modp_inv(5) % P
_G_X = _recover_x(_G_Y, 0)
G = (_G_X, _G_Y, 1, _G_X * _G_Y % P)

_NEUTRAL = (0, 1, 1, 0)


def _point_add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % P
    B = (a[1] + a[0]) * (b[1] + b[0]) % P
    C = 2 * a[3] * b[3] * D % P
    E = 2 * a[2] * b[2] % P
    f, g, h, i = B - A, E - C, E + C, B + A
    return (f * g % P, h * i % P, g * h % P, f * i % P)


def _point_mul(scalar: int, point):
    result = _NEUTRAL
    while scalar > 0:
        if scalar & 1:
            result = _point_add(result, point)
        point = _point_add(point, point)
        scalar >>= 1
    return result


def _point_equal(a, b) -> bool:
    if (a[0] * b[2] - b[0] * a[2]) % P != 0:
        return False
    return (a[1] * b[2] - b[1] * a[2]) % P == 0


def _point_compress(point) -> bytes:
    inv = _modp_inv(point[2])
    x = point[0] * inv % P
    y = point[1] * inv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _point_decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _secret_expand(secret: bytes):
    if len(secret) != 32:
        raise ValueError("seed must be exactly 32 bytes")
    digest = _sha512(secret)
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= (1 << 254)
    return scalar, digest[32:]


# ── Публичный API ───────────────────────────────────────────────────────────
def public_key(seed: bytes) -> bytes:
    """32-байтовый публичный ключ из 32-байтового seed."""
    scalar, _ = _secret_expand(seed)
    return _point_compress(_point_mul(scalar, G))


def sign(seed: bytes, message: bytes) -> bytes:
    """64-байтовая подпись. Только для генератора ключей."""
    scalar, prefix = _secret_expand(seed)
    pub = _point_compress(_point_mul(scalar, G))
    r = _sha512_modq(prefix + message)
    big_r = _point_compress(_point_mul(r, G))
    h = _sha512_modq(big_r + pub + message)
    s = (r + h * scalar) % Q
    return big_r + int.to_bytes(s, 32, "little")


# Точки малого порядка. На них проверка подписи выполняется тождественно, и
# обнулённый или подменённый на такую точку публичный ключ принимал бы ЛЮБУЮ
# подпись. Атакующий этот ключ не выбирает — он вшит в сборку, — но повреждение
# файла разблокировало бы ИИ всем. Список тот же, что отвергает libsodium.
_SMALL_ORDER = frozenset(bytes.fromhex(value) for value in (
    "0100000000000000000000000000000000000000000000000000000000000000",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000080",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    "edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
))


def is_weak_key(data: bytes) -> bool:
    """Точка малого порядка — такой ключ или подпись принимать нельзя."""
    return bytes(data) in _SMALL_ORDER


def verify(pub: bytes, message: bytes, signature: bytes) -> bool:
    """Проверка подписи. Никогда не бросает — только True/False."""
    try:
        if len(pub) != 32 or len(signature) != 64:
            return False
        if is_weak_key(pub) or is_weak_key(signature[:32]):
            return False
        point_a = _point_decompress(pub)
        if point_a is None:
            return False
        big_r = signature[:32]
        point_r = _point_decompress(big_r)
        if point_r is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= Q:
            return False
        h = _sha512_modq(big_r + pub + message)
        return _point_equal(_point_mul(s, G),
                            _point_add(point_r, _point_mul(h, point_a)))
    except Exception:
        return False
