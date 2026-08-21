from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_mt4_mt5_cap_active_json_at_six():
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        assert "currentZoneCount >= 6" in source
        assert "currentZoneCount != 6" in source
        assert "currentZoneCount < 20" not in source
        assert "zoneFallback" in source
        assert "ZoneColorFallback" in source


def test_mql_uses_schema_four_unique_zone_keys_and_checks_three_plus_three():
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        assert '"\\"schema_version\\":' in source
        assert '"\\"zone_price\\":' in source
        assert 'StringFind(json, "\\"price\\":", searchPos)' not in source
        assert "display contract is not 3+3" in source
        assert "incompatible payload schema" in source


def test_active_zone_drawers_use_horizontal_lines_not_rectangle_ranges():
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        section = source[source.index("void DrawSingleZone"):source.index("// ── 3.", source.index("void DrawSingleZone"))]
        assert "OBJ_HLINE" in section
        assert "OBJ_RECTANGLE" not in section


def test_sl_cloud_uses_python_stop_payload_and_long_short_colors():
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        assert '"\\"stop_price\\":' in source
        assert '"_sl_cloud_"' in source
        assert "C'95,224,190'" in source
        assert "C'239,117,132'" in source
        assert '"_sl_line"' not in source


def test_footprint_uses_the_same_schema_and_stop_cloud():
    source = _source("python_core/footprint_window.py")
    assert "zone_price" in source
    assert "zone_fallback" in source
    assert "stop_price" in source
    assert "stop_anchor_epoch" in source
    assert "anchorEpoch" in source
    assert "const points = 9, columns = 3, rows = 3" in source
    assert "LONG SL " in source
    assert "SHORT SL " in source


def test_collectors_export_the_same_history_depth_as_the_detector():
    expected = {"H1": 720, "H4": 600, "D1": 365}
    collectors = (
        "mql/MT4/Experts/SmartZonesCollector.mq4",
        "mql/MT5/Experts/SmartZonesCollector.mq5",
    )
    for relative in collectors:
        source = _source(relative)
        for timeframe, bars in expected.items():
            assert f"input int      {timeframe}_Bars             = {bars};" in source


def test_installer_deploys_compiled_mql_in_an_isolated_channel_folder():
    source = _source("setup.iss")
    assert "InstallCompiledMqlToTerminals();" in source
    assert "StrongZones.ex4" in source
    assert "SmartZonesCollector.ex4" in source
    assert "StrongZones.ex5" in source
    assert "SmartZonesCollector.ex5" in source
    assert "SmartZonesPro\\{#AppChannel}" in source


def test_collectors_export_live_chart_quote_and_actual_symbol():
    for relative in (
        "mql/MT4/Experts/SmartZonesCollector.mq4",
        "mql/MT5/Experts/SmartZonesCollector.mq5",
    ):
        source = _source(relative)
        assert "ExportLiveQuote();" in source
        assert '"smartzones_quote_" + g_symbolName' in source
        assert '"smartzones_symbol.txt"' in source


def test_indicators_show_reference_price_in_a_visible_upper_stamp():
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        assert '\\"reference_price\\":' in source
        assert "referencePrice" in source
        assert "CORNER_RIGHT_UPPER" in source
        assert "OBJPROP_YDISTANCE, 25" in source


def test_sl_cloud_is_visible_and_reports_created_dots():
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        assert "slCloudCount" in source
        assert '"  sl-dots: "' in source
        assert '"\\"stop_anchor_epoch\\":' in source
        assert "stopAnchorTimes" in source
        assert "int columns = 3" in source
        assert "PeriodSeconds() / 10" in source
        assert "OBJPROP_WIDTH, dot == points / 2 ? 3 : 2" in source


def test_missing_swing_anchor_never_rejects_valid_six_zone_payload():
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        invalid_guard = source[source.index("if(price <= 0"):source.index("ArrayResize(zonePrices", source.index("if(price <= 0"))]
        assert "stopAnchorTime <= 0" not in invalid_guard
        assert "stopAnchorPrice <= 0" not in invalid_guard
        assert "datetime ResolveStopAnchor" in source
        assert "slLocalAnchorCount" in source
        assert '"  sl-local: "' in source
        cloud = source[source.index("void DrawStopCloud"):source.index("void DeleteAllZoneObjects", source.index("void DrawStopCloud"))]
        assert "if(stopPrice <= 0) return;" in cloud
        assert "stopAnchorTimes[index] <= 0" not in cloud
        assert "iLow" in source
        assert "iHigh" in source


def test_indicators_reload_zones_only_when_the_payload_file_changes():
    """A timer tick must not delete and recreate six unchanged chart objects."""
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        assert "bool FileHasChanged()" in source
        assert "lastFileTime == 0 || modified != lastFileTime || size != lastFileSize" in source
        assert "return true;  // Для простоты перечитываем каждый раз" not in source

        timer = source[source.index("void OnTimer()"):source.index("void OnTimer()") + 350]
        assert "if(FileHasChanged())" in timer
        assert "LoadZonesFromFile();" in timer


def test_invalid_payload_does_not_clear_the_last_valid_zone_render():
    """Transient I/O or a rejected payload must leave the previous six lines visible."""
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        loader = source[source.index("void LoadZonesFromFile()"):source.index("bool ValidatePayloadHeader")]
        invalid_header = loader[
            loader.index("if(!ValidatePayloadHeader(content))"):
            loader.index("zonesCalcTime", loader.index("if(!ValidatePayloadHeader(content))"))
        ]
        assert "DeleteAllZoneObjects" not in invalid_header
