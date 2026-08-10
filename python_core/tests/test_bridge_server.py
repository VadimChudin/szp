"""
Тесты для bridge_server.py — чтение флага кнопки FP.
"""

import bridge_server


class TestReadFootprintTimeframe:
    def test_utf16_flag_from_mt5(self, tmp_path):
        """MT5 пишет флаг в UTF-16 — раньше запуск падал с embedded null."""
        flag = tmp_path / "footprint_request.flag"
        flag.write_bytes("4h".encode("utf-16"))
        assert bridge_server.read_footprint_timeframe(flag) == "4h"

    def test_plain_ansi_flag_from_mt4(self, tmp_path):
        flag = tmp_path / "footprint_request.flag"
        flag.write_text("1d")
        assert bridge_server.read_footprint_timeframe(flag) == "1d"

    def test_unknown_value_falls_back(self, tmp_path):
        flag = tmp_path / "footprint_request.flag"
        flag.write_text("garbage")
        assert bridge_server.read_footprint_timeframe(flag) == "1h"

    def test_missing_file_falls_back(self, tmp_path):
        assert bridge_server.read_footprint_timeframe(tmp_path / "nope.flag") == "1h"
