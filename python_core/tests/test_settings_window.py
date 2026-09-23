"""Окно настроек: запись .env и структура интерфейса.

Tkinter требует дисплей, поэтому само окно здесь не создаётся: проверяем
чистые функции (update_env) и структуру исходника. Регрессии, которые
закрываются:
  * прокрутки не было — при трёх слотах брокеров и масштабе 125% нижние поля
    уезжали за край окна и были недоступны;
  * окно показывало DATA_SOURCE=mt5, когда в config дефолт dukascopy;
  * MAX_ZONE_DISTANCE_PIPS писался рядом со скопом — две ручки на одну
    величину, старое значение противоречило новому скопу.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import paths
import pytest
import settings_window

SOURCE = Path(settings_window.__file__).read_text(encoding="utf-8")


# ── update_env ──────────────────────────────────────────────────────────────
@pytest.fixture
def env_file(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr(paths, "ENV_FILE", target)
    return target


def test_update_env_creates_file_with_values(env_file):
    assert settings_window.update_env({"ZONE_SCOPE_PIPS": "2000"}) is True
    assert "ZONE_SCOPE_PIPS=2000" in env_file.read_text(encoding="utf-8")


def test_update_env_keeps_comments_and_other_keys(env_file):
    env_file.write_text(
        "# важный комментарий\nDATA_SOURCE=dukascopy\nZONE_SCOPE_PIPS=800\n",
        encoding="utf-8",
    )

    settings_window.update_env({"ZONE_SCOPE_PIPS": "5000"})
    text = env_file.read_text(encoding="utf-8")

    assert "# важный комментарий" in text
    assert "DATA_SOURCE=dukascopy" in text
    assert "ZONE_SCOPE_PIPS=5000" in text
    assert "ZONE_SCOPE_PIPS=800" not in text


def test_update_env_removes_stale_keys(env_file):
    env_file.write_text(
        "ZONE_SCOPE_PIPS=800\nMAX_ZONE_DISTANCE_PIPS=400\n", encoding="utf-8"
    )

    settings_window.update_env(
        {"ZONE_SCOPE_PIPS": "5000"}, removals=("MAX_ZONE_DISTANCE_PIPS",)
    )
    text = env_file.read_text(encoding="utf-8")

    assert "ZONE_SCOPE_PIPS=5000" in text
    assert "MAX_ZONE_DISTANCE_PIPS" not in text


def test_update_env_removal_of_absent_key_is_noop(env_file):
    env_file.write_text("ZONE_SCOPE_PIPS=800\n", encoding="utf-8")
    assert settings_window.update_env({}, removals=("NOPE",)) is True
    assert "ZONE_SCOPE_PIPS=800" in env_file.read_text(encoding="utf-8")


# ── Структура интерфейса ────────────────────────────────────────────────────
def test_window_has_scrollable_content_area():
    assert "tk.Canvas(" in SOURCE
    assert "ttk.Scrollbar(" in SOURCE
    assert 'canvas.configure(scrollregion=canvas.bbox("all"))' in SOURCE
    assert "_bind_mouse_wheel" in SOURCE


def test_buttons_stay_outside_scroll_area():
    """Кнопки закреплены на самом окне, а не внутри прокрутки."""
    build = SOURCE[SOURCE.index("def _build_ui"):]
    buttons_block = build[:build.index("# ── Прокручиваемая область")]
    assert "tk.Frame(self, bg=ui.CARD_BOT)" in buttons_block
    assert 'side="bottom"' in buttons_block


def test_sections_live_in_scrollable_content():
    for section in ("val_box = tk.LabelFrame(content",
                    "zone_box = tk.LabelFrame(content",
                    "tg_box = tk.LabelFrame(content",
                    "brokers_box = tk.LabelFrame(content"):
        assert section in SOURCE, f"секция вне прокрутки: {section}"


def test_data_source_default_matches_config():
    import config

    assert 'self._env.get("DATA_SOURCE", "dukascopy")' in SOURCE
    assert config.DATA_SOURCE in settings_window.DATA_SOURCES


def test_scope_and_limit_are_editable_without_hard_ceiling():
    assert "Любое положительное число" in SOURCE
    assert "1_000_000" not in SOURCE, "вернулся искусственный потолок скопа"
    assert "от 1 до 500" in SOURCE


def test_extra_zone_settings_exposed():
    """MIN_ZONE_SCORE и TEST_INVALIDATES_ZONE больше не правятся руками в .env."""
    assert '"MIN_ZONE_SCORE"' in SOURCE
    assert '"TEST_INVALIDATES_ZONE"' in SOURCE


def test_save_does_not_write_duplicate_scope_knob():
    save_block = SOURCE[SOURCE.index("def _save"):]
    assert '"MAX_ZONE_DISTANCE_PIPS":' not in save_block
    assert 'removals=("MAX_ZONE_DISTANCE_PIPS",)' in save_block


def test_settings_mentions_terminal_input_for_limit():
    """Клиент должен знать, что в терминале лимит задаётся входом индикатора."""
    assert "MaxZonesToDraw" in SOURCE


def _form(*, login="12345", scope="800", tolerance="5.0"):
    def field(value):
        return SimpleNamespace(get=lambda: value)

    form = SimpleNamespace(
        _zone_scope=field(scope), _max_zones=field("6"), _min_score=field("11"),
        _validation_tolerance=field(tolerance), _data_source=field("dukascopy"),
        _validation_mode=field("validate"), _broker_offset=field(True),
        _test_invalidates=field(False), _tg_enabled=field(False),
        _tg_token=field(""), _tg_chat=field(""), _active_var=field(0),
        _broker_vars=[{key: field(value) for key, value in {
            "name": "Broker 1", "server": "", "login": login,
            "password": "", "path": "",
        }.items()}],
        destroy=lambda: None,
    )
    form._collect_brokers = lambda: settings_window.SettingsWindow._collect_brokers(form)
    return form


@pytest.mark.parametrize(("field", "value", "error"), [
    ("login", "12oops", "Broker 1: Login"),
    ("login", "-10", "Broker 1: Login"),
    ("login", "0", "Broker 1: Login"),
    ("scope", "nan", "Скоп"),
    ("scope", "inf", "Скоп"),
    ("tolerance", "oops", "Допуск совпадения"),
    ("tolerance", "0", "Допуск совпадения"),
    ("tolerance", "nan", "Допуск совпадения"),
])
def test_invalid_settings_do_not_write_any_file(env_file, tmp_path, monkeypatch,
                                                field, value, error):
    brokers_file = tmp_path / "brokers.json"
    monkeypatch.setattr(paths, "BROKERS_FILE", brokers_file)
    messages = []
    monkeypatch.setattr(settings_window.messagebox, "showerror", lambda _, msg: messages.append(msg))

    settings_window.SettingsWindow._save(_form(**{field: value}))

    assert messages and error in messages[0]
    assert not env_file.exists()
    assert not brokers_file.exists()


def test_invalid_login_preserves_existing_settings(env_file, tmp_path, monkeypatch):
    brokers_file = tmp_path / "brokers.json"
    env_file.write_text("ZONE_SCOPE_PIPS=800\n", encoding="utf-8")
    brokers_file.write_text('{"active_broker": 0, "brokers": []}\n', encoding="utf-8")
    monkeypatch.setattr(paths, "BROKERS_FILE", brokers_file)
    monkeypatch.setattr(settings_window.messagebox, "showerror", lambda *_: None)

    settings_window.SettingsWindow._save(_form(login="123x"))

    assert env_file.read_text(encoding="utf-8") == "ZONE_SCOPE_PIPS=800\n"
    assert brokers_file.read_text(encoding="utf-8") == '{"active_broker": 0, "brokers": []}\n'


def test_valid_settings_save_login_and_normalized_numbers(env_file, tmp_path, monkeypatch):
    import json

    brokers_file = tmp_path / "brokers.json"
    monkeypatch.setattr(paths, "BROKERS_FILE", brokers_file)
    monkeypatch.setattr(settings_window.messagebox, "showinfo", lambda *_: None)

    settings_window.SettingsWindow._save(_form(login=" 12345 ", scope="800,5",
                                               tolerance="2,5"))

    assert json.loads(brokers_file.read_text(encoding="utf-8"))["brokers"][0]["login"] == 12345
    text = env_file.read_text(encoding="utf-8")
    assert "ZONE_SCOPE_PIPS=800.5" in text
    assert "VALIDATION_TOLERANCE=2.5" in text
