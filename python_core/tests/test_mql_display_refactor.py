"""Source-contract checks, not a substitute for MetaEditor compilation."""
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[2]

@pytest.fixture(params=['MT4', 'MT5'])
def source(request):
    ext = 'mq4' if request.param == 'MT4' else 'mq5'
    return (ROOT / 'mql' / request.param / 'Indicators' / f'StrongZones.{ext}').read_text(encoding='utf-8')

def test_draws_actual_zone_bounds(source):
    # Клиент: только чёткие сплошные линии. Пунктирная рамка зоны удалена,
    # DrawZoneBounds остался как уборщик старых "_band" объектов.
    assert 'DrawZoneBounds(baseName, top, bottom, zoneColor);' in source
    fn = source[source.index('void DrawZoneBounds'):]
    fn = fn[:fn.index('\n}\n') + 3]
    assert 'OBJ_RECTANGLE' not in fn
    assert 'STYLE_DOT' not in fn
    assert 'ObjectDelete' in fn
    assert 'baseName + "_band"' in source

def test_label_follows_theme_and_chart_scale(source):
    assert 'CHART_COLOR_FOREGROUND' in source
    assert 'CHART_HEIGHT_IN_PIXELS' in source
    assert 'void PlaceZonePriceLabels()' in source
    assert 'OBJ_TEXT' in source
    assert 'ANCHOR_LEFT' in source
    assert 'PeriodSeconds() * 10' not in source
    assert 'if(id == CHARTEVENT_CHART_CHANGE)' in source
    assert 'PlaceZonePriceLabels();' in source
    fn = source[source.index('void PlaceZonePriceLabels()'):source.index('void DrawZoneBounds')]
    assert 'OBJ_LABEL' not in fn
    assert 'CORNER_RIGHT' not in fn

def test_empty_array_clears_objects_before_short_file_guard(source):
    loader = source[source.index('void LoadZonesFromFile('):]
    assert loader.index('if(compact == "[]")') < loader.index('if(StringLen(content) < 10)')
    block = loader[loader.index('if(compact == "[]")'):loader.index('if(StringLen(content) < 10)')]
    assert 'currentZoneCount = 0;' in block
    assert 'DeleteStaleZoneObjects(0);' in block
    assert 'ChartRedraw();' in block
