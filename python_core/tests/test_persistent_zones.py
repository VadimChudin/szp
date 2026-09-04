"""
Тесты для persistent_zones.py — хранение и обработка исторических зон.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import config
from zone_detector import Zone
from persistent_zones import (
    default_serializer,
    load_db,
    save_db,
    get_h4_closes,
    process_persistent_zones,
    process_legacy_zones,
    display_window,
)
from zone_reaction import ReactionResult, Reaction


class TestDefaultSerializer:
    def test_datetime_serialized(self):
        from datetime import datetime
        dt = datetime(2024, 6, 15, 12, 30, 0)
        assert default_serializer(dt) == "2024-06-15T12:30:00"

    def test_timestamp_serialized(self):
        ts = pd.Timestamp("2024-06-15 12:30:00")
        assert "2024-06-15" in default_serializer(ts)

    def test_fallback_to_str(self):
        assert default_serializer(42) == "42"
        assert default_serializer([1, 2]) == "[1, 2]"


class TestLoadSaveDb:
    def test_load_empty_file(self, tmp_path):
        """Несуществующий файл → пустой список."""
        fake_db = tmp_path / "nonexistent.json"
        with patch("persistent_zones.DB_FILE", fake_db):
            result = load_db()
        assert result == []

    def test_save_and_load_roundtrip(self, tmp_path):
        """Сохранение и загрузка зон — данные сохраняются."""
        fake_db = tmp_path / "zones_db.json"

        zones = [
            Zone(price=2400.0, width=1.0, score=12, sources=["H1", "H4"],
                 touch_count=5, has_big_player=True, is_round_level=True),
            Zone(price=2350.0, width=1.0, score=10, sources=["D1"],
                 touch_count=3, has_big_player=False, is_round_level=False),
        ]

        with patch("persistent_zones.DB_FILE", fake_db):
            save_db(zones)
            loaded = load_db()

        assert len(loaded) == 2
        assert loaded[0].price == 2400.0
        assert loaded[0].score == 12
        assert loaded[0].sources == ["H1", "H4"]
        assert loaded[0].has_big_player is True
        assert loaded[1].price == 2350.0

    def test_save_creates_valid_json(self, tmp_path):
        """Файл содержит валидный JSON с version и last_update."""
        fake_db = tmp_path / "zones_db.json"
        zones = [Zone(price=2400.0)]

        with patch("persistent_zones.DB_FILE", fake_db):
            save_db(zones)

        with open(fake_db) as f:
            data = json.load(f)
        assert "version" in data
        assert "last_update" in data
        assert "archived" in data
        assert len(data["archived"]) == 1

    def test_load_corrupted_file(self, tmp_path):
        """Битый JSON → пустой список (без исключений)."""
        fake_db = tmp_path / "zones_db.json"
        fake_db.write_text("not valid json{{{")

        with patch("persistent_zones.DB_FILE", fake_db):
            result = load_db()
        assert result == []


class TestGetH4Closes:
    def test_with_h4_data(self):
        df = pd.DataFrame({
            "open": [2400.0, 2405.0, 2410.0],
            "close": [2405.0, 2410.0, 2415.0],
            "high": [2410.0, 2415.0, 2420.0],
            "low": [2395.0, 2400.0, 2405.0],
            "time": pd.date_range("2024-01-01", periods=3, freq="4h"),
        })
        result = get_h4_closes({"H4": df})
        assert len(result) == 3
        assert result[0] == (2400.0, 2405.0)

    def test_without_h4_data(self):
        result = get_h4_closes({"H1": pd.DataFrame()})
        assert result == []

    def test_empty_h4(self):
        result = get_h4_closes({"H4": pd.DataFrame(columns=["open", "close"])})
        assert result == []


class TestProcessPersistentZones:
    @pytest.fixture(autouse=True)
    def _no_atr_window(self, monkeypatch):
        monkeypatch.setattr(config, "ZONE_WINDOW_ATR", 0.0)
        monkeypatch.setattr(config, "ZONE_SCOPE_PIPS", 0.0)
        monkeypatch.setattr(config, "REACTION_ENABLED", False)

    def test_weak_zones_not_archived(self, tmp_path):
        """Зоны со score < 12 не попадают в архив."""
        fake_db = tmp_path / "zones_db.json"
        current = [Zone(price=2400.0, score=8, sources=["H1"])]
        data = {"H4": pd.DataFrame(columns=["open", "close", "high", "low", "time"])}

        with patch("persistent_zones.DB_FILE", fake_db):
            result = process_persistent_zones(current, data)

        assert isinstance(result, list)

    def test_strong_zones_archived(self, tmp_path):
        """Зоны со score >= 12 попадают в архив."""
        fake_db = tmp_path / "zones_db.json"
        current = [Zone(price=2400.0, score=15, sources=["H1", "H4", "D1"],
                        touch_count=10, has_big_player=True)]
        data = {"H4": pd.DataFrame(columns=["open", "close", "high", "low", "time"])}

        with patch("persistent_zones.DB_FILE", fake_db):
            process_persistent_zones(current, data)
            db = load_db()

        assert len(db) == 1
        assert db[0].price == 2400.0

    def test_invalidation_by_breakout(self, tmp_path):
        """Зона удаляется если её пробило телом H4."""
        fake_db = tmp_path / "zones_db.json"

        # Создаём зону в БД
        db_zone = Zone(price=2400.0, width=1.0, score=14, sources=["H4"],
                       touch_count=6, has_big_player=True)
        with patch("persistent_zones.DB_FILE", fake_db):
            save_db([db_zone])

        # H4 данные с 2 пробоями (open ниже zone_bottom-buffer, close выше zone_top+buffer)
        zone_bottom = 2400.0 - 1.0 - 2.0  # 2397
        zone_top = 2400.0 + 1.0 + 2.0     # 2403
        h4_df = pd.DataFrame({
            "open": [zone_bottom - 1] * 15,
            "close": [zone_top + 1] * 15,
            "high": [zone_top + 5] * 15,
            "low": [zone_bottom - 5] * 15,
            "time": pd.date_range("2024-01-01", periods=15, freq="4h"),
        })
        data = {"H4": h4_df}

        with patch("persistent_zones.DB_FILE", fake_db):
            result = process_persistent_zones([], data)

        # Зона должна быть удалена (burned)
        with patch("persistent_zones.DB_FILE", fake_db):
            remaining = load_db()
        assert len(remaining) == 0

    def test_expired_zone_removed(self, tmp_path, monkeypatch):
        """Архивная зона снимается, если её давно не подтверждал расчёт."""
        from datetime import datetime, timedelta
        monkeypatch.setattr(config, "PERSISTENT_ZONE_MAX_AGE_DAYS", 14.0)
        fake_db = tmp_path / "zones_db.json"
        old = datetime.now() - timedelta(days=config.PERSISTENT_ZONE_MAX_AGE_DAYS + 1)
        stale = Zone(price=2400.0, score=14, sources=["H4"],
                     archived_at=old.isoformat())
        data = {"H4": pd.DataFrame(columns=["open", "close", "high", "low", "time"])}

        with patch("persistent_zones.DB_FILE", fake_db):
            save_db([stale])
            result = process_persistent_zones([], data)
            remaining = load_db()

        assert remaining == []
        assert result == []

    def test_far_archived_zone_not_shown(self, tmp_path, monkeypatch):
        """Архивная зона далеко от текущей цены не выводится (график ушёл)."""
        from datetime import datetime, timedelta
        monkeypatch.setattr(config, "MAX_ZONE_DISTANCE_PCT", 10.0)
        fake_db = tmp_path / "zones_db.json"
        far = 2400.0 * (1 + config.MAX_ZONE_DISTANCE_PCT / 100.0 * 2)
        seen = (datetime.now() - timedelta(days=1)).isoformat()
        archived = Zone(price=far, score=15, sources=["H4"], archived_at=seen)
        data = {"H1": pd.DataFrame({"close": [2400.0], "open": [2400.0],
                                    "high": [2401.0], "low": [2399.0],
                                    "time": pd.date_range("2024-01-01", periods=1)})}

        with patch("persistent_zones.DB_FILE", fake_db):
            save_db([archived])
            result = process_persistent_zones([Zone(price=2400.0, score=13, sources=["H4"])], data)

        assert [z.price for z in result] == [2400.0]

    def test_far_fresh_zone_is_shown(self, tmp_path, monkeypatch):
        """Свежую зону детектора нельзя отбрасывать по удалённости от цены."""
        monkeypatch.setattr(config, "MAX_ZONE_DISTANCE_PCT", 10.0)
        fake_db = tmp_path / "zones_db.json"
        far = 2400.0 * (1 + config.MAX_ZONE_DISTANCE_PCT / 100.0 * 2)
        current = [Zone(price=far, score=15, sources=["H4"]),
                   Zone(price=2400.0, score=13, sources=["H4"])]
        data = {"H1": pd.DataFrame({"close": [2400.0], "open": [2400.0],
                                    "high": [2401.0], "low": [2399.0],
                                    "time": pd.date_range("2024-01-01", periods=1)})}

        with patch("persistent_zones.DB_FILE", fake_db):
            result = process_persistent_zones(current, data)

        assert [z.price for z in result] == [far, 2400.0]

    def test_fresh_zones_have_priority_over_historic(self, tmp_path):
        """Свежие зоны не вытесняются архивными с более высоким score."""
        from datetime import datetime
        fake_db = tmp_path / "zones_db.json"
        archived = [
            Zone(price=2300.0 + i, score=20, sources=["H4"],
                 archived_at=datetime.now().isoformat())
            for i in range(config.MAX_ZONES_ON_CHART)
        ]
        current = [Zone(price=2400.0, score=9, sources=["H4"])]
        data = {"H4": pd.DataFrame(columns=["open", "close", "high", "low", "time"])}

        with patch("persistent_zones.DB_FILE", fake_db):
            save_db(archived)
            result = process_persistent_zones(current, data)

        assert 2400.0 in [z.price for z in result]

    def test_output_limited_to_max_zones(self, tmp_path):
        """Вывод ограничен config.MAX_ZONES_ON_CHART."""
        fake_db = tmp_path / "zones_db.json"
        # Создаём больше зон чем лимит
        current = [
            Zone(price=2400.0 + i * 20, score=15, sources=["H4"], touch_count=5)
            for i in range(config.MAX_ZONES_ON_CHART + 5)
        ]
        data = {"H4": pd.DataFrame(columns=["open", "close", "high", "low", "time"])}

        with patch("persistent_zones.DB_FILE", fake_db):
            result = process_persistent_zones(current, data)

        assert len(result) <= config.MAX_ZONES_ON_CHART


class TestProcessLegacyZonesDisplay:
    def _h4(self, close=2400.0):
        return {
            "H4": pd.DataFrame({
                "open": [close],
                "close": [close],
                "high": [close + 1],
                "low": [close - 1],
                "time": pd.date_range("2024-01-01", periods=1, freq="4h"),
            }),
            "H1": pd.DataFrame({
                "open": [close],
                "close": [close],
                "high": [close + 1],
                "low": [close - 1],
                "time": pd.date_range("2024-01-01", periods=1, freq="h"),
            }),
        }

    def test_atr_window_hides_far_zones(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "zones_db.json"
        monkeypatch.setattr(config, "ZONE_WINDOW_ATR", 10.0)
        monkeypatch.setattr(config, "ZONE_SCOPE_PIPS", 0.0)
        monkeypatch.setattr(config, "MAX_ZONE_DISTANCE", 0.0)
        monkeypatch.setattr(config, "REACTION_ENABLED", False)
        data = self._h4(2400.0)
        # ATR of the 1-bar fixture is 2.0 → window $20
        data["H1"] = pd.DataFrame({
            "open": [2400.0],
            "close": [2400.0],
            "high": [2401.0],
            "low": [2399.0],
            "time": pd.date_range("2024-01-01", periods=1, freq="h"),
        })
        near = Zone(price=2410.0, score=15, sources=["H4"], width=1.0)
        far = Zone(price=2500.0, score=20, sources=["H4"], width=1.0)
        with patch("persistent_zones.DB_FILE", fake_db):
            result = process_legacy_zones([near, far], data)
        prices = [z.price for z in result]
        assert 2410.0 in prices
        assert 2500.0 not in prices
        assert display_window(data) == pytest.approx(20.0)

    def test_hides_zones_beyond_900_pips(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "zones_db.json"
        monkeypatch.setattr(config, "ZONE_WINDOW_ATR", 0.0)
        monkeypatch.setattr(config, "ZONE_SCOPE_PIPS", 1800.0)  # 900 вверх и 900 вниз
        monkeypatch.setattr(config, "MAX_ZONE_DISTANCE_PIPS", 900.0)
        monkeypatch.setattr(config, "MAX_ZONE_DISTANCE", 90.0)
        monkeypatch.setattr(config, "REACTION_ENABLED", False)
        near = Zone(price=2410.0, score=15, sources=["H4"], width=1.0)
        far = Zone(price=2600.0, score=20, sources=["H4"], width=1.0)
        with patch("persistent_zones.DB_FILE", fake_db):
            result = process_legacy_zones([near, far], self._h4(2400.0))
        prices = [z.price for z in result]
        assert 2410.0 in prices
        assert 2600.0 not in prices

    def test_custom_scope_is_half_each_side(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "zones_db.json"
        monkeypatch.setattr(config, "ZONE_WINDOW_ATR", 0.0)
        monkeypatch.setattr(config, "ZONE_SCOPE_PIPS", 2400.0)  # ±1200 pips
        monkeypatch.setattr(config, "PIP_SIZE", 0.1)
        monkeypatch.setattr(config, "MAX_ZONES_ON_CHART", 6)
        monkeypatch.setattr(config, "REACTION_ENABLED", False)
        data = self._h4(2400.0)
        assert display_window(data) == pytest.approx(120.0)
        inside = Zone(price=2519.0, score=15, sources=["H4"], width=1.0)
        outside = Zone(price=2521.0, score=20, sources=["H4"], width=1.0)
        with patch("persistent_zones.DB_FILE", fake_db):
            result = process_legacy_zones([inside, outside], data)
        prices = [z.price for z in result]
        assert 2519.0 in prices
        assert 2521.0 not in prices

    def test_scope_800_is_400_each_side(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "zones_db.json"
        monkeypatch.setattr(config, "ZONE_WINDOW_ATR", 0.0)
        monkeypatch.setattr(config, "ZONE_SCOPE_PIPS", 800.0)
        monkeypatch.setattr(config, "PIP_SIZE", 0.1)
        monkeypatch.setattr(config, "MAX_ZONES_ON_CHART", 6)
        monkeypatch.setattr(config, "REACTION_ENABLED", False)
        data = self._h4(2400.0)
        assert display_window(data) == pytest.approx(40.0)  # 400 pips * $0.1
        inside = Zone(price=2439.0, score=15, sources=["H4"], width=1.0)
        outside = Zone(price=2441.0, score=20, sources=["H4"], width=1.0)
        with patch("persistent_zones.DB_FILE", fake_db):
            result = process_legacy_zones([inside, outside], data)
        prices = [z.price for z in result]
        assert 2439.0 in prices
        assert 2441.0 not in prices

    def test_does_not_invent_zones_when_fewer_than_limit(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "zones_db.json"
        monkeypatch.setattr(config, "ZONE_WINDOW_ATR", 0.0)
        monkeypatch.setattr(config, "ZONE_SCOPE_PIPS", 800.0)
        monkeypatch.setattr(config, "MAX_ZONES_ON_CHART", 6)
        monkeypatch.setattr(config, "REACTION_ENABLED", False)
        only = Zone(price=2405.0, score=16, sources=["H4"], width=1.0)
        with patch("persistent_zones.DB_FILE", fake_db):
            result = process_legacy_zones([only], self._h4(2400.0))
        assert [z.price for z in result] == [2405.0]

    def test_keeps_only_reaction_zones(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "zones_db.json"
        monkeypatch.setattr(config, "MAX_ZONE_DISTANCE", 0.0)
        monkeypatch.setattr(config, "ZONE_WINDOW_ATR", 0.0)
        monkeypatch.setattr(config, "ZONE_SCOPE_PIPS", 0.0)
        monkeypatch.setattr(config, "REACTION_ENABLED", True)
        monkeypatch.setattr(
            config, "DISPLAY_REACTION_TYPES",
            ("BOUNCE", "CONSOLIDATION", "APPROACHING"),
        )
        bounce = Zone(price=2390.0, score=14, sources=["H4"], width=1.0)
        consol = Zone(price=2410.0, score=13, sources=["H4"], width=1.0)
        dead = Zone(price=2420.0, score=20, sources=["H4"], width=1.0)
        broken = Zone(price=2380.0, score=18, sources=["H4"], width=1.0)

        def fake_classify(zone, data):
            mapping = {
                2390.0: Reaction.BOUNCE,
                2410.0: Reaction.CONSOLIDATION,
                2420.0: Reaction.NONE,
                2380.0: Reaction.BREAKOUT,
            }
            return ReactionResult(type=mapping[zone.price])

        with patch("persistent_zones.DB_FILE", fake_db), \
             patch("zone_reaction.classify_zone", side_effect=fake_classify):
            result = process_legacy_zones(
                [bounce, consol, dead, broken], self._h4(2400.0)
            )
        prices = [z.price for z in result]
        assert 2390.0 in prices
        assert 2410.0 in prices
        assert 2420.0 not in prices
        assert 2380.0 not in prices


def test_scope_splits_any_value_in_half(monkeypatch):
    monkeypatch.setattr(config, "ZONE_WINDOW_ATR", 0.0)
    monkeypatch.setattr(config, "PIP_SIZE", 0.1)
    data = {"H1": pd.DataFrame({"high": [2401.0], "low": [2399.0], "close": [2400.0]})}
    for scope, expected in ((200.0, 10.0), (800.0, 40.0), (2400.0, 120.0)):
        monkeypatch.setattr(config, "ZONE_SCOPE_PIPS", scope)
        assert display_window(data) == pytest.approx(expected)
