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


def test_footprint_reads_same_zones_file_as_terminal(tmp_path, monkeypatch):
    """Footprint и MT4/MT5 читают ОДИН файл зон — синхронизация по определению."""
    import json
    import footprint_window
    import paths
    zones_file = tmp_path / "zones_output.json"
    zones_file.write_text(json.dumps({
        "current_price": 4456.0,
        "zones": [{"price": 4476.0, "top": 4477.0, "bottom": 4475.0, "score": 14},
                  {"price": 4436.0, "top": 4437.0, "bottom": 4435.0, "score": 12}],
    }))
    monkeypatch.setattr(footprint_window, "ZONES_FILE", zones_file)
    zones = footprint_window._load_zones()
    assert len(zones) == 2
    assert {z["price"] for z in zones} == {4476.0, 4436.0}
    # Изменение файла видно при следующем чтении без перезапуска окна
    zones_file.write_text(json.dumps({"zones": [{"price": 4400.0, "top": 4401.0,
                                                 "bottom": 4399.0, "score": 10}]}))
    assert len(footprint_window._load_zones()) == 1


def test_sl_levels_not_exported_by_default():
    """Клиентский контракт «только зоны»: sl-поля нет в JSON — рисовать нечего."""
    import config
    assert config.EXPORT_SL_LEVELS is False


def test_footprint_sl_render_is_gated():
    """Footprint рисует SL только при явном show_sl=true в payload."""
    src = open("python_core/footprint_window.py", encoding="utf-8").read()
    assert 'DATA.show_sl === true && z.sl' in src
    assert '"show_sl": False' in src
