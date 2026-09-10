"""Static MT4/MT5 rendering contracts; these do not execute or compile MQL."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
INDICATORS = (
    ROOT / "mql/MT4/Indicators/StrongZones.mq4",
    ROOT / "mql/MT5/Indicators/StrongZones.mq5",
)
CURRENT_PARTS = {
    "_line", "_top", "_bottom", "_text", "_zakrep", "_badge",
    "_sl_line", "_sl_label",
}


def _code(source):
    """Ignore comments without confusing quoted JSON keys with source syntax."""
    return re.sub(
        r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
        lambda match: match[0] if match[0].startswith('"') else "",
        source,
        flags=re.S,
    )


def _function(source, name):
    source = _code(source)
    signature = re.search(rf"\b{re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    assert signature, f"Missing function {name}"
    tail = source[signature.end():]
    depth = 1
    for token in re.finditer(r'"(?:\\.|[^"\\])*"|[{}]', tail):
        if token[0] == "{":
            depth += 1
        elif token[0] == "}":
            depth -= 1
        if depth == 0:
            return tail[:token.start()]
    raise AssertionError(f"Unclosed function {name}")


@pytest.fixture(params=INDICATORS, ids=("MT4", "MT5"))
def source(request):
    return request.param.read_text(encoding="utf-8")


def test_active_zones_and_optional_bounds_remain_solid_full_width_lines(source):
    main = _function(source, "DrawSingleZone")
    bounds = _function(source, "DrawZoneBounds")
    assert "DrawZoneBounds(baseName, top, bottom, zoneColor);" in main
    for body, name, price in (
        (main, "lineName", "price"),
        (bounds, "topName", "top"),
        (bounds, "botName", "bottom"),
    ):
        assert f"EnsureObject({name}, OBJ_HLINE, 0, {price});" in body
        assert f"MovePointIfChanged({name}, 0, 0, {price});" in body
        assert f"SetIntIfChanged({name}, OBJPROP_STYLE, STYLE_SOLID);" in body
        assert "OBJ_RECTANGLE" not in body
        assert not re.search(r"\bSTYLE_(?:DASH\w*|DOT)\b", body)
    assert "!ShowZoneBounds" in bounds
    assert "top <= bottom" in bounds
    assert "ObjectDelete(0, bandName);" in bounds  # Historical broad band.


def test_auxiliary_boxes_remain_opt_in_and_legacy_inputs_are_retained(source):
    code = _code(source)
    for name in ("ShowRectangles", "ShowAccumulation", "ShowSL"):
        assert re.search(rf"input\s+bool\s+{name}\s*=\s*false\s*;", code)
    assert re.search(r"input\s+int\s+ZoneHistoryBars\s*=", code)


def test_object_reuse_rejects_stale_rectangle_types_without_recreating_lines(source):
    ensure = _function(source, "EnsureObject")
    assert "bool exists = (ObjectFind(0, name) >= 0);" in ensure
    assert "if(exists && (ENUM_OBJECT)ObjectGetInteger(0, name, OBJPROP_TYPE) != type)" in ensure
    assert "if(!ObjectDelete(0, name)) return false;" in ensure
    assert "exists = false;" in ensure
    assert "if(!exists && !ObjectCreate(0, name, type, 0, t1, p1)) return false;" in ensure
    assert "return !exists;" in ensure


def test_reused_zone_objects_clear_selection_as_well_as_selectability(source):
    ensure = _function(source, "EnsureObject")
    for prop in ("SELECTED", "SELECTABLE"):
        statement = f"SetIntIfChanged(name, OBJPROP_{prop}, false);"
        assert statement in ensure
        assert ensure.index("ObjectCreate(") < ensure.index(statement) < ensure.index("return !exists;")


def test_stale_children_are_removed_even_for_active_zone_indices(source):
    cleanup = _function(source, "DeleteStaleZoneObjects")
    assert set(re.findall(r'suffix\s*==\s*"([^"]+)"', cleanup)) == CURRENT_PARTS
    assert "if(idx >= keepCount || !currentPart)" in cleanup
    # Never treat accumulation, build stamps, controls, or arbitrary user names
    # as indexed zone parts, even when their names happen to start with SZP_.
    for guard in (
        "if(StringFind(name, accumPrefix) == 0) continue;",
        "if(StringFind(name, buildPrefix) == 0) continue;",
        "if(IntegerToString(idx) != idxStr) continue;",
    ):
        assert guard in cleanup
    assert re.search(r"if\(StringFind\(name, zonePrefix\) != 0\)\s+continue;", cleanup)


def test_disabled_accumulation_cleans_restored_boxes_without_count_guard(source):
    loader = _function(source, "LoadAccumulationFromFile")
    disabled = re.search(r"if\(!ShowAccumulation\)\s*\{([^{}]*)\}", loader).group(1)
    assert "DeleteAccumulationObjects();" in disabled
    assert "accumCount" not in disabled
    assert 'lastAccumRaw = "";' in disabled
    assert "return;" in disabled


def test_empty_accumulation_snapshot_reaches_cleanup_before_redraw(source):
    loader = _function(source, "LoadAccumulationFromFile")
    for whitespace in (" ", r"\r", r"\n", r"\t"):
        assert f'StringReplace(compact, "{whitespace}", "");' in loader
    guard = 'if(StringLen(content) < 10 && compact != "[]") return;'
    assert guard in loader  # [] used to return here, retaining the old boxes.
    assert "if(StringLen(content) < 10) return;" not in loader
    cache = loader.index("if(content == lastAccumRaw) return;")
    snapshot = loader.index("lastAccumRaw = content;")
    cleanup = loader.index("DeleteAccumulationObjects();", snapshot)
    assert loader.index(guard) < cache < snapshot < cleanup < loader.index("ChartRedraw(")


def test_opt_in_accumulation_has_explicit_solid_unselected_style(source):
    loader = _function(source, "LoadAccumulationFromFile")
    for prop, value in (
        ("STYLE", "STYLE_SOLID"), ("WIDTH", "1"), ("FILL", "true"),
        ("BACK", "true"), ("SELECTED", "false"), ("SELECTABLE", "false"),
    ):
        assert f"ObjectSetInteger(0, name, OBJPROP_{prop}, {value});" in loader
    assert re.search(r"if\(!ObjectCreate\((?:0, )?name, OBJ_RECTANGLE, 0, t1, top, t2, bottom\)\) continue;", loader)
    assert "if(t1 <= 0 || top <= 0 || bottom <= 0 || top <= bottom) continue;" in loader
    assert "if(t2 <= t1) t2 = t1 + PeriodSeconds();" in loader


def test_zone_geometry_and_reaction_state_stay_data_driven(source):
    parser = _function(source, "ParseZonesJSON")
    main = _function(source, "DrawSingleZone")
    for array, value in (
        ("zonePrices", "price"), ("zoneTops", "top"), ("zoneBottoms", "bottom"),
        ("zoneScores", "score"), ("zoneFallback", "fallback"),
        ("zoneReaction", "reaction"), ("zoneReactionDir", "reactionDir"),
    ):
        assert re.search(rf"{array}\[currentZoneCount\]\s*=\s*{value};", parser)
    assert "if(fallback) zoneColor = ZoneColorLow;" in main
    assert 'if(ShowZakrep && reaction == "BREAKOUT")' in main
    assert "if(ShowReactionTag" in main


def test_shared_rendering_helpers_have_mt4_mt5_parity():
    sources = [p.read_text(encoding="utf-8") for p in INDICATORS]
    for name in ("EnsureObject", "DrawZoneBounds"):
        bodies = [re.sub(r"\s+", "", _function(s, name)) for s in sources]
        assert bodies[0] == bodies[1], name
