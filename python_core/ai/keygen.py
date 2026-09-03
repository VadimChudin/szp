"""
keygen.py — Генератор ключей продукта. НЕ ПОСТАВЛЯЕТСЯ КЛИЕНТАМ.

Этот файл исключён из сборки (см. installer/SmartZonesPro.spec) и запускается
только на машине разработчика.

Порядок работы
--------------
1. Один раз создать пару ключей:

       python -m ai.keygen init

   Приватный seed ложится в szp_signing_key.txt рядом со скриптом. Его нельзя
   терять и нельзя никому передавать: потеря = невозможность выпускать новые
   ключи, утечка = кто угодно сможет выпускать их сам.
   Команда напечатает строку PUBLIC_KEY_HEX для вставки в ai/licensing.py.

2. Клиент нажимает «Подключить ИИ» и присылает код своей машины
   (29 символов, видно в окне).

3. Выпуск ключа:

       python -m ai.keygen issue --code AB12C-... --days 30
       python -m ai.keygen issue --code AB12C-... --days 3
       python -m ai.keygen issue --code AB12C-... --forever
       python -m ai.keygen issue --days 30 --unbound     # без привязки

4. Полученный ключ отдаётся клиенту, он вставляет его в поле.

Проверить ключ перед отправкой:

       python -m ai.keygen check --token SZP1-...
"""
from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
import time
from pathlib import Path

from ai import ed25519, licensing

KEY_FILE = Path(__file__).resolve().parent.parent / "szp_signing_key.txt"
DAY = 86_400


def _load_seed() -> bytes:
    if not KEY_FILE.exists():
        sys.exit(f"Приватный ключ не найден: {KEY_FILE}\n"
                 f"Сначала выполните: python -m ai.keygen init")
    seed = bytes.fromhex(KEY_FILE.read_text(encoding="utf-8").strip())
    if len(seed) != 32:
        sys.exit("Файл приватного ключа повреждён")
    return seed


def cmd_init(args) -> None:
    if KEY_FILE.exists() and not args.force:
        sys.exit(f"Ключ уже существует: {KEY_FILE}\n"
                 f"Перезапись сделает НЕДЕЙСТВИТЕЛЬНЫМИ все выпущенные "
                 f"ключи. Если это действительно нужно — добавьте --force")
    seed = secrets.token_bytes(32)
    KEY_FILE.write_text(seed.hex(), encoding="utf-8")
    try:
        os.chmod(KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    pub = ed25519.public_key(seed)
    print(f"Приватный ключ сохранён: {KEY_FILE}")
    print("Не передавайте этот файл никому и сделайте резервную копию.\n")
    print("Вставьте строку в python_core/ai/licensing.py:\n")
    print(f'PUBLIC_KEY_HEX = "{pub.hex()}"')


def cmd_issue(args) -> None:
    seed = _load_seed()

    if args.forever:
        expires = licensing.FOREVER
    elif args.days:
        expires = int(time.time()) + int(args.days) * DAY
    else:
        sys.exit("Укажите срок: --days N или --forever")

    if args.unbound:
        slots = [b"\x00" * licensing.HW_SLOT_SIZE] * 3
        bound = False
    else:
        if not args.code:
            sys.exit("Нужен код машины клиента: --code ... "
                     "(или --unbound для ключа без привязки)")
        slots = licensing.slots_from_code(args.code)
        if slots is None:
            sys.exit("Код машины не распознан — проверьте, что скопирован "
                     "полностью")
        bound = True

    payload = licensing.Payload(version=1, bound=bound, expires_at=expires,
                                issued_at=int(time.time()), hw_slots=slots)
    signature = ed25519.sign(seed, licensing.pack(payload))
    token = licensing.encode_token(payload, signature)

    term = "бессрочный" if expires == licensing.FOREVER else f"{args.days} дн."
    binding = "без привязки к железу" if not bound else "привязан к машине"
    print(f"Ключ ({term}, {binding}):\n")
    print(token)


def cmd_check(args) -> None:
    seed = _load_seed()
    os.environ["SZP_PUBLIC_KEY"] = ed25519.public_key(seed).hex()
    parts = licensing.split_token(args.token)
    if parts is None:
        sys.exit("Ключ не распознан")
    payload, signature = parts
    valid = ed25519.verify(ed25519.public_key(seed),
                           licensing.pack(payload), signature)
    print(f"Подпись: {'верна' if valid else 'НЕВЕРНА'}")
    if payload.forever:
        print("Срок: бессрочный")
    else:
        left = payload.days_left(int(time.time()))
        print(f"Срок до: {time.strftime('%Y-%m-%d %H:%M', time.localtime(payload.expires_at))}"
              f" (осталось {left:.1f} дн.)")
    print(f"Привязка к железу: {'да' if payload.bound else 'нет'}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="ai.keygen", description="Генератор ключей Smart Zones Pro")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="создать пару ключей")
    init.add_argument("--force", action="store_true",
                      help="перезаписать существующий приватный ключ")
    init.set_defaults(func=cmd_init)

    issue = subparsers.add_parser("issue", help="выпустить ключ клиенту")
    issue.add_argument("--code", help="код машины клиента")
    issue.add_argument("--days", type=int, help="срок действия в днях")
    issue.add_argument("--forever", action="store_true", help="бессрочный")
    issue.add_argument("--unbound", action="store_true",
                       help="без привязки к железу")
    issue.set_defaults(func=cmd_issue)

    check = subparsers.add_parser("check", help="проверить выпущенный ключ")
    check.add_argument("--token", required=True)
    check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
