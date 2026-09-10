import pandas as pd
import pytest

from zone_detector import Zone
from zone_reaction import Reaction, classify_reaction, classify_zone


def frame(rows):
    return pd.DataFrame(rows, columns=['open', 'high', 'low', 'close'])


BASE = [(4000, 4002, 3998, 4001)] * 20
UP = BASE + [(4001, 4006, 4000, 4005), (4005, 4011, 4004, 4009),
             (4009, 4020, 4008, 4018), (4018, 4026, 4017, 4025)]


def test_breakout_is_not_relabelled_as_bounce_by_final_price():
    result = classify_reaction(4012, 4010, frame(UP))
    assert (result.type, result.direction) == (Reaction.BREAKOUT, 'UP')


def test_display_side_cannot_reverse_the_original_approach():
    zone = Zone(price=4011, width=1, display_side='BELOW')
    result = classify_zone(zone, {'H1': frame(UP)})
    assert result.type == Reaction.BREAKOUT


def test_contiguous_contact_is_one_test_not_several():
    bars = BASE + [(4001, 4011, 4000, 4005)] * 4
    assert classify_reaction(4012, 4010, frame(bars), 'ABOVE').touches == 1


def test_old_interaction_expires(monkeypatch):
    import config
    monkeypatch.setattr(config, 'REACTION_WINDOW_AFTER', 3)
    result = classify_reaction(4012, 4010, frame(UP + [(4025, 4027, 4023, 4025)] * 8))
    assert result.type == Reaction.NONE


@pytest.mark.parametrize('top,bottom', [(4010, 4012), (4010, 4010), (float('nan'), 4010)])
def test_bad_geometry_does_not_emit_a_signal(top, bottom):
    assert classify_reaction(top, bottom, frame(UP)).type == Reaction.NONE
