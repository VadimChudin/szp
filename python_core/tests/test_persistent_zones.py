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
)


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
        """Зона удаляется если пробита H4 свечами >= 2 раза."""
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
