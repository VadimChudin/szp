"""
Тесты для data_fetcher.py — цепочка источников данных и проверка свежести.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest

import config
import data_fetcher
from data_fetcher import DataUnavailableError, data_age_hours, fetch_all_timeframes


def _frame(hours_old: float) -> pd.DataFrame:
    last = datetime.utcnow() - timedelta(hours=hours_old)
    times = pd.date_range(end=last, periods=3, freq="1h")
    return pd.DataFrame({
        "time": times,
        "open": [2400.0, 2401.0, 2402.0],
        "high": [2405.0, 2406.0, 2407.0],
        "low": [2395.0, 2396.0, 2397.0],
        "close": [2401.0, 2402.0, 2403.0],
        "tick_volume": [100, 120, 140],
    })


def _dataset(hours_old: float) -> dict[str, pd.DataFrame]:
    return {tf: _frame(hours_old) for tf in config.TIMEFRAMES}


class TestDataAgeHours:
    def test_fresh(self):
        assert data_age_hours(_frame(2)) == pytest.approx(2, abs=0.1)

    def test_empty_is_infinite(self):
        assert data_age_hours(pd.DataFrame()) == float("inf")


class TestMaxAgeHours:
    def test_daily_bar_gets_full_day_of_slack(self):
        """Время свечи — её открытие: D1 к вечеру «старше» общего лимита."""
        assert data_fetcher.max_age_hours("D1") == config.MAX_DATA_AGE_HOURS + 24
        assert data_fetcher.max_age_hours("H1") == config.MAX_DATA_AGE_HOURS + 1

    def test_daily_candle_from_this_morning_is_fresh(self, monkeypatch):
        """Полдня данные считались протухшими из-за дневной свечи."""
        monkeypatch.setattr(data_fetcher, "_source_chain", lambda symbol: [
            ("mt5", lambda: {**_dataset(1), "D1": _frame(20)}),
        ])
        assert set(fetch_all_timeframes("XAUUSD")) == set(config.TIMEFRAMES)


class TestMarketReferenceTime:
    def test_trading_day_uses_now(self):
        now = datetime(2026, 6, 17, 15, 0)  # среда
        assert data_fetcher.market_reference_time(now) == now

    def test_weekend_falls_back_to_friday_close(self):
        for now in (datetime(2026, 6, 20, 12, 0),   # суббота
                    datetime(2026, 6, 21, 12, 0),   # воскресенье
                    datetime(2026, 6, 19, 23, 0)):  # пятница после закрытия
            assert data_fetcher.market_reference_time(now) == datetime(2026, 6, 19, 21, 0)

    def test_weekend_data_is_not_stale(self, monkeypatch):
        """В выходные свечи «стареют» на десятки часов — это не повод не считать."""
        saturday = datetime(2026, 6, 20, 12, 0)
        friday_close = datetime(2026, 6, 19, 20, 0)
        frame = _frame(0)
        frame["time"] = pd.date_range(end=friday_close, periods=3, freq="1h")
        assert data_fetcher.data_age_hours(
            frame, data_fetcher.market_reference_time(saturday)) == pytest.approx(1, abs=0.1)


class TestFetchAllTimeframes:
    def test_raises_when_no_source_works(self, monkeypatch):
        """Без реальных данных поднимается ошибка, а не синтетика."""
        def boom():
            raise RuntimeError("terminal offline")

        monkeypatch.setattr(data_fetcher, "_source_chain",
                            lambda symbol: [("mt5", boom)])
        monkeypatch.setattr(config, "ALLOW_SAMPLE_DATA", False)

        with pytest.raises(DataUnavailableError):
            fetch_all_timeframes("XAUUSD")

    def test_stale_source_skipped_for_fresh_one(self, monkeypatch):
        """Устаревший источник пропускается в пользу свежего."""
        monkeypatch.setattr(data_fetcher, "_source_chain", lambda symbol: [
            ("stale", lambda: _dataset(config.MAX_DATA_AGE_HOURS + 10)),
            ("fresh", lambda: _dataset(1)),
        ])

        data = fetch_all_timeframes("XAUUSD")
        assert data_age_hours(data["H4"]) < config.MAX_DATA_AGE_HOURS

    def test_incomplete_source_skipped(self, monkeypatch):
        """Источник без части таймфреймов не используется."""
        monkeypatch.setattr(data_fetcher, "_source_chain", lambda symbol: [
            ("partial", lambda: {"H1": _frame(1)}),
            ("full", lambda: _dataset(1)),
        ])

        data = fetch_all_timeframes("XAUUSD")
        assert set(data) == set(config.TIMEFRAMES)

    def test_sample_data_only_when_allowed(self, monkeypatch):
        """Синтетика возвращается только при ALLOW_SAMPLE_DATA=1."""
        monkeypatch.setattr(data_fetcher, "_source_chain", lambda symbol: [])
        monkeypatch.setattr(config, "ALLOW_SAMPLE_DATA", True)

        data = fetch_all_timeframes("XAUUSD")
        assert set(data) == set(config.TIMEFRAMES)


class TestCsvEncoding:
    def test_detects_utf16_from_mt5_collector(self, tmp_path):
        path = tmp_path / "XAUUSD_H4.csv"
        path.write_bytes("# broker=RoboForex\ntime,open\n".encode("utf-16"))
        assert data_fetcher.csv_encoding(path) == "utf-16"

    def test_plain_utf8_csv(self, tmp_path):
        path = tmp_path / "XAUUSD_H4.csv"
        path.write_text("time,open\n")
        assert data_fetcher.csv_encoding(path) == "utf-8"
