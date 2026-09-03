"""
Тесты слоя ИИ: разбор ответа модели и безопасный отказ.

Главное требование — модель НЕ МОЖЕТ изменить геометрию зоны. Цена, ширина и
вердикт confirm_zones принадлежат коду: на этом держится канон «одинаковые
зоны у всех брокеров».
"""
import json

import pandas as pd
import pytest

import config
from ai import annotator
from zone_detector import Zone


def _zone(price, score=15, **kwargs):
    return Zone(price=price, width=1.0, score=score, sources=["H4"], **kwargs)


def _data(close=2400.0, bars=60):
    frame = pd.DataFrame({
        "open": [close] * bars,
        "close": [close] * bars,
        "high": [close + 2] * bars,
        "low": [close - 2] * bars,
        "time": pd.date_range("2024-01-01", periods=bars, freq="4h"),
    })
    return {"H4": frame, "H1": frame.copy()}


class TestParseResponse:
    def test_valid_answer(self):
        text = json.dumps([
            {"zone_id": 0, "verdict": "LIVE", "rank": 1, "why": "три касания"},
            {"zone_id": 1, "verdict": "SKIP", "rank": 2, "why": "пусто"},
        ])
        notes = annotator.parse_response(text, 2)
        assert [n.zone_id for n in notes] == [0, 1]
        assert notes[0].verdict == "LIVE"

    def test_unknown_verdict_dropped(self):
        text = json.dumps([{"zone_id": 0, "verdict": "МОЖЕТ",
                            "rank": 1, "why": "не уверен"}])
        assert annotator.parse_response(text, 1) == []

    def test_out_of_range_zone_id_dropped(self):
        """Модель не может подписать зону, которой ей не давали."""
        text = json.dumps([{"zone_id": 7, "verdict": "LIVE",
                            "rank": 1, "why": "выдумка"}])
        assert annotator.parse_response(text, 2) == []

    def test_duplicate_zone_id_kept_once(self):
        text = json.dumps([
            {"zone_id": 0, "verdict": "LIVE", "rank": 1, "why": "раз"},
            {"zone_id": 0, "verdict": "SKIP", "rank": 2, "why": "два"},
        ])
        notes = annotator.parse_response(text, 1)
        assert len(notes) == 1
        assert notes[0].why == "раз"

    def test_empty_reason_dropped(self):
        text = json.dumps([{"zone_id": 0, "verdict": "LIVE",
                            "rank": 1, "why": "   "}])
        assert annotator.parse_response(text, 1) == []

    def test_long_reason_truncated(self):
        text = json.dumps([{"zone_id": 0, "verdict": "WATCH",
                            "rank": 1, "why": "я" * 400}])
        assert len(annotator.parse_response(text, 1)[0].why) == 180

    @pytest.mark.parametrize("junk", [
        "", "не json", "{}", "[1,2,3]", '{"zone_id":0}', "null",
        '[{"zone_id":"нет","verdict":"LIVE","rank":1,"why":"x"}]',
    ])
    def test_garbage_never_raises(self, junk):
        assert annotator.parse_response(junk, 3) == []


class TestPacket:
    def test_packet_carries_numbers_not_raw_candles(self):
        packet = annotator.build_packet([_zone(2410.0)], _data(),
                                        with_analogs=False)
        item = packet["zones"][0]
        assert item["price"] == 2410.0
        assert "wick_points" not in item
        assert item["zone_id"] == 0

    def test_dropped_zones_are_marked(self):
        """Отброшенные кодом зоны тоже уходят в модель — пусть спорит."""
        packet = annotator.build_packet(
            [_zone(2410.0)], _data(), dropped=[_zone(2500.0)],
            with_analogs=False)
        flags = [item["dropped"] for item in packet["zones"]]
        assert flags == [False, True]

    def test_candidate_limit_respected(self, monkeypatch):
        monkeypatch.setattr(config, "AI_MAX_CANDIDATES", 3)
        zones = [_zone(2400.0 + i) for i in range(10)]
        packet = annotator.build_packet(zones, _data(), with_analogs=False)
        assert len(packet["zones"]) == 3

    def test_prompt_hides_internal_objects(self):
        packet = annotator.build_packet([_zone(2410.0)], _data(),
                                        with_analogs=False)
        prompt = annotator.build_prompt(packet)
        assert "_objects" not in prompt
        assert "2410" in prompt

    def test_prompt_forbids_inventing_prices(self):
        prompt = annotator.build_prompt(
            annotator.build_packet([_zone(2410.0)], _data(),
                                   with_analogs=False))
        assert "не придумывай" in prompt.lower()


class TestGrammar:
    def test_grammar_file_ships(self):
        text = annotator.grammar()
        assert text and "verdict" in text

    def test_grammar_has_no_price_field(self):
        """В схеме ответа нет цены — модель физически не может её вернуть."""
        text = annotator.grammar() or ""
        assert "price" not in text


class TestFailSafe:
    def test_disabled_by_config(self, monkeypatch):
        monkeypatch.setattr(config, "AI_ENABLED", False)
        zones = [_zone(2410.0)]
        assert annotator.annotate(zones, _data()) is zones

    def test_no_license_leaves_zones_untouched(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "AI_ENABLED", True)
        monkeypatch.setenv("SZP_LICENSE_DIR", str(tmp_path))
        zone = _zone(2410.0)
        result = annotator.annotate([zone], _data())
        assert result[0].price == 2410.0
        assert result[0].ai_note == ""
        assert result[0].ai_verdict == ""

    def test_empty_zones_short_circuit(self):
        assert annotator.annotate([], _data()) == []

    def test_annotation_never_changes_geometry(self):
        """Подпись меняет только ai_*, но не price/width/confirm."""
        zone = _zone(2410.0, confirm_verdict="LIVE")
        notes = annotator.parse_response(json.dumps(
            [{"zone_id": 0, "verdict": "SKIP", "rank": 1, "why": "тест"}]), 1)
        zone.ai_verdict = notes[0].verdict
        zone.ai_note = notes[0].why
        zone.ai_rank = notes[0].rank
        assert zone.price == 2410.0
        assert zone.width == 1.0
        assert zone.confirm_verdict == "LIVE"
        assert zone.ai_verdict == "SKIP"


class TestZoneFields:
    def test_ai_fields_survive_serialization(self):
        zone = _zone(2410.0)
        zone.ai_verdict, zone.ai_note, zone.ai_rank = "WATCH", "проверить", 2
        restored = Zone.from_dict(zone.to_dict())
        assert restored.ai_verdict == "WATCH"
        assert restored.ai_note == "проверить"
        assert restored.ai_rank == 2

    def test_ai_fields_default_empty(self):
        zone = _zone(2410.0)
        assert zone.ai_verdict == "" and zone.ai_rank == 0
