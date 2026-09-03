"""
Тесты лицензирования ИИ: подпись, срок, привязка к железу, откат часов.

Эти проверки важнее остальных: ошибка здесь означает либо бесплатный доступ
к платной функции, либо заблокированный ИИ у честно заплатившего клиента.
"""
import os
import tempfile
import time

import pytest

from ai import ed25519, licensing

SEED = bytes.fromhex("42" * 32)
DAY = 86_400


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Свой каталог лицензии и известный публичный ключ на каждый тест."""
    monkeypatch.setenv("SZP_LICENSE_DIR", str(tmp_path))
    monkeypatch.setenv("SZP_PUBLIC_KEY", ed25519.public_key(SEED).hex())
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", "")
    monkeypatch.setattr(licensing, "_time_anchor", 0)


def _slots():
    return licensing.hardware_slots()


def _issue(*, days=None, forever=False, slots=None, bound=True, seed=SEED):
    if forever:
        expires = licensing.FOREVER
    else:
        expires = int(time.time()) + int(days) * DAY
    payload = licensing.Payload(
        version=1, bound=bound, expires_at=expires,
        issued_at=int(time.time()),
        hw_slots=slots if slots is not None else _slots())
    signature = ed25519.sign(seed, licensing.pack(payload))
    return licensing.encode_token(payload, signature)


class TestEd25519:
    def test_rfc8032_vector(self):
        """Эталонный вектор RFC 8032 — гарантия, что реализация не своя."""
        seed = bytes.fromhex(
            "9d61b19deffd5a60ba844af492ec2cc4"
            "4449c5697b326919703bac031cae7f60")
        pub = ed25519.public_key(seed)
        assert pub.hex() == ("d75a980182b10ab7d54bfed3c964073a"
                             "0ee172f3daa62325af021a68f707511a")
        assert ed25519.verify(pub, b"", ed25519.sign(seed, b""))

    def test_signature_is_message_bound(self):
        pub = ed25519.public_key(SEED)
        signature = ed25519.sign(SEED, b"zone")
        assert ed25519.verify(pub, b"zone", signature)
        assert not ed25519.verify(pub, b"zonf", signature)

    def test_verify_never_raises(self):
        assert ed25519.verify(b"", b"", b"") is False
        assert ed25519.verify(b"\x00" * 32, b"x", b"\x00" * 64) is False

    def test_small_order_keys_rejected(self):
        """Обнулённый ключ иначе принимал бы любую подпись."""
        assert ed25519.is_weak_key(b"\x00" * 32) is True
        assert ed25519.is_weak_key(ed25519.public_key(SEED)) is False
        # Подпись с R малого порядка тоже отвергается.
        pub = ed25519.public_key(SEED)
        forged = b"\x00" * 32 + b"\x00" * 32
        assert ed25519.verify(pub, b"x", forged) is False

    def test_corrupted_public_key_locks_ai(self, monkeypatch):
        monkeypatch.setenv("SZP_PUBLIC_KEY", "00" * 32)
        assert licensing.public_key_bytes() is None
        assert licensing.verify_token(_issue(days=30)).state == \
            licensing.NO_PUBLIC_KEY


class TestTokenFormat:
    def test_payload_roundtrip(self):
        payload = licensing.Payload(1, True, 1893456000, 1700000000,
                                    [b"abcdef", b"123456", b"ZYXWVU"])
        restored = licensing.unpack(licensing.pack(payload))
        assert restored.expires_at == payload.expires_at
        assert restored.hw_slots == payload.hw_slots
        assert restored.bound is True

    def test_machine_code_roundtrip(self):
        """Код машины должен нести сами слоты: генератор их восстанавливает."""
        assert licensing.slots_from_code(licensing.machine_code()) == _slots()

    def test_token_survives_spacing_and_case(self):
        token = _issue(days=30)
        messy = token.lower().replace("-", " ")
        assert licensing.verify_token(messy).ok


class TestVerdicts:
    def test_valid_month_key(self):
        assert licensing.verify_token(_issue(days=30)).state == licensing.VALID

    def test_three_day_key(self):
        status = licensing.verify_token(_issue(days=3))
        assert status.ok
        assert 2.5 < status.payload.days_left(int(time.time())) <= 3.0

    def test_forever_key(self):
        status = licensing.verify_token(_issue(forever=True))
        assert status.ok
        assert status.payload.forever
        assert "бессрочный" in status.message

    def test_expired_key_rejected(self):
        assert licensing.verify_token(_issue(days=-1)).state == licensing.EXPIRED

    def test_foreign_signature_rejected(self):
        """Ключ, выпущенный другим приватным ключом, не подходит."""
        other = bytes.fromhex("77" * 32)
        status = licensing.verify_token(_issue(days=30, seed=other))
        assert status.state == licensing.BAD_SIGNATURE

    def test_tampered_payload_rejected(self):
        token = _issue(days=1)
        tampered = token[:-4] + ("ZZZZ" if not token.endswith("ZZZZ") else "YYYY")
        assert licensing.verify_token(tampered).state != licensing.VALID

    def test_garbage_and_empty(self):
        assert licensing.verify_token("привет").state == licensing.MALFORMED
        assert licensing.verify_token("").state == licensing.NONE

    def test_without_public_key_ai_locked(self, monkeypatch):
        monkeypatch.delenv("SZP_PUBLIC_KEY", raising=False)
        assert licensing.verify_token(_issue(days=30)).state == \
            licensing.NO_PUBLIC_KEY


class TestHardwareBinding:
    def test_wrong_machine_rejected(self):
        alien = [b"\x01" * 6, b"\x02" * 6, b"\x03" * 6]
        status = licensing.verify_token(_issue(days=30, slots=alien))
        assert status.state == licensing.WRONG_MACHINE

    def test_two_of_three_is_enough(self):
        """Замена диска не должна убивать оплаченную лицензию."""
        slots = _slots()
        changed = [slots[0], slots[1], b"\x09" * 6]
        assert licensing.verify_token(_issue(days=30, slots=changed)).ok

    def test_one_of_three_not_enough(self):
        slots = _slots()
        changed = [slots[0], b"\x08" * 6, b"\x09" * 6]
        assert licensing.verify_token(_issue(days=30, slots=changed)).state == \
            licensing.WRONG_MACHINE

    def test_unbound_key_works_anywhere(self):
        token = _issue(days=30, slots=[b"\x00" * 6] * 3, bound=False)
        assert licensing.verify_token(token).ok

    def test_empty_slots_do_not_count_as_match(self):
        """Нулевой слот не должен «совпадать» с нулевым и давать зачёт."""
        empty = [b"\x00" * 6] * 3
        assert licensing.slots_match(empty, empty) is False


class TestClockProtection:
    def test_expiry_uses_external_anchor(self):
        """Часы назад — но якорь Dukascopy показывает настоящее время."""
        token = _issue(days=1)
        future = int(time.time()) + 5 * DAY
        licensing.set_time_anchor(future)
        assert licensing.verify_token(token).state == licensing.EXPIRED

    def test_anchor_never_moves_backwards(self):
        licensing.set_time_anchor(2_000_000_000)
        licensing.set_time_anchor(1_000)
        assert licensing._effective_now() >= 2_000_000_000

    def test_rollback_detected_after_activation(self, monkeypatch):
        assert licensing.activate(_issue(days=30)).ok
        assert licensing.current_status().ok

        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() - 400 * DAY)
        status = licensing.current_status()
        assert status.clock_tampered is True

    def test_last_seen_survives_rollback(self, monkeypatch):
        """После отката времени срок считается от максимума виденного."""
        licensing.activate(_issue(days=1))
        licensing.current_status()
        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() - 10 * DAY)
        # Действующее время не «уехало» назад вместе с часами.
        assert licensing._effective_now() >= int(real()) - DAY


class TestStorage:
    def test_activate_then_status(self):
        token = _issue(days=30)
        assert licensing.activate(token).ok
        assert licensing.stored_token() == token
        assert licensing.ai_enabled() is True

    def test_bad_key_is_not_saved(self):
        licensing.activate("SZP1-NOPE")
        assert licensing.stored_token() == ""
        assert licensing.ai_enabled() is False

    def test_deactivate_turns_ai_off(self):
        licensing.activate(_issue(days=30))
        licensing.deactivate()
        assert licensing.ai_enabled() is False
        assert licensing.current_status().state == licensing.NONE

    def test_expired_key_disables_ai_automatically(self):
        """Истёк срок — продукт сам возвращается в обычный режим."""
        token = _issue(days=30)
        licensing.activate(token)
        licensing.set_time_anchor(int(time.time()) + 60 * DAY)
        assert licensing.ai_enabled() is False
