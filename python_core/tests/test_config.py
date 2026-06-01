"""
Тесты для config.py — вспомогательные функции чтения переменных окружения.
"""

import os
from unittest.mock import patch

import pytest

from config import _env_str, _env_int, _env_float, _env_bool


class TestEnvStr:
    def test_returns_env_value(self):
        with patch.dict(os.environ, {"TEST_VAR": "hello"}):
            assert _env_str("TEST_VAR", "default") == "hello"

    def test_returns_default_when_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_str("MISSING_VAR", "fallback") == "fallback"

    def test_returns_default_when_empty(self):
        with patch.dict(os.environ, {"TEST_VAR": ""}):
            assert _env_str("TEST_VAR", "fallback") == "fallback"


class TestEnvInt:
    def test_returns_int_from_env(self):
        with patch.dict(os.environ, {"TEST_INT": "42"}):
            assert _env_int("TEST_INT", 0) == 42

    def test_returns_default_when_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_int("MISSING", 99) == 99

    def test_returns_default_when_empty(self):
        with patch.dict(os.environ, {"TEST_INT": ""}):
            assert _env_int("TEST_INT", 7) == 7

    def test_returns_default_on_invalid(self):
        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            assert _env_int("TEST_INT", 5) == 5

    def test_negative_number(self):
        with patch.dict(os.environ, {"TEST_INT": "-10"}):
            assert _env_int("TEST_INT", 0) == -10


class TestEnvFloat:
    def test_returns_float_from_env(self):
        with patch.dict(os.environ, {"TEST_F": "3.14"}):
            assert _env_float("TEST_F", 0.0) == pytest.approx(3.14)

    def test_returns_default_when_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_float("MISSING", 1.5) == 1.5

    def test_returns_default_when_empty(self):
        with patch.dict(os.environ, {"TEST_F": ""}):
            assert _env_float("TEST_F", 2.0) == 2.0

    def test_returns_default_on_invalid(self):
        with patch.dict(os.environ, {"TEST_F": "abc"}):
            assert _env_float("TEST_F", 9.9) == 9.9


class TestEnvBool:
    @pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "y", "on"])
    def test_truthy_values(self, value):
        with patch.dict(os.environ, {"TEST_B": value}):
            assert _env_bool("TEST_B", False) is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", "random"])
    def test_falsy_values(self, value):
        with patch.dict(os.environ, {"TEST_B": value}):
            assert _env_bool("TEST_B", True) is False

    def test_returns_default_when_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_bool("MISSING", True) is True
            assert _env_bool("MISSING", False) is False

    def test_returns_default_when_empty(self):
        with patch.dict(os.environ, {"TEST_B": ""}):
            assert _env_bool("TEST_B", True) is True
