from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_mt4_mt5_cap_active_json_at_six():
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        assert "currentZoneCount < 6" in source
        assert "currentZoneCount < 20" not in source
        assert "zoneFallback" in source
        assert "ZoneColorFallback" in source


def test_active_zone_drawers_use_horizontal_lines_not_rectangle_ranges():
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        section = source[source.index("void DrawSingleZone"):source.index("// ── 3.", source.index("void DrawSingleZone"))]
        assert "OBJ_HLINE" in section
        assert "OBJ_RECTANGLE" not in section


def test_sl_is_violet_and_separate_from_red_fallback():
    for relative in ("mql/MT4/Indicators/StrongZones.mq4", "mql/MT5/Indicators/StrongZones.mq5"):
        source = _source(relative)
        assert "C'189,167,255'" in source
        assert '"_sl_line"' in source


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
