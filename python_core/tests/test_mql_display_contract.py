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
        # Цвет зоны теперь градацией по силе (как в старой версии): сильные
        # ярко-красные, слабые и историчные — тусклее. Инпуты переименованы,
        # чтобы старые значения из профиля графика не оживали.
        assert "ZoneColorHigh" in source
        assert "ZoneColorMid" in source
        assert "ZoneColorLow" in source
        assert "ZoneColorStrong" not in source.replace("ZoneColorStrong=clrGold", "")


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
