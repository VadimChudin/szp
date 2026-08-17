import pandas as pd

from backtest import walk_forward, summarize
from zone_detector import Zone, adaptive_zone_width


def frame():
    rows = []
    for i in range(30):
        rows.append((f"2024-01-{i + 1:02d} 00:00:00", 100 + i, 103 + i, 97 + i, 101 + i))
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def test_adaptive_width_is_bounded():
    width = adaptive_zone_width({"H4": frame()})
    import config
    assert config.ZONE_WIDTH_MIN <= width <= config.ZONE_WIDTH_MAX


def test_walk_forward_uses_future_only():
    calls = []
    data = frame()

    def detector(window):
        calls.append(len(window["H4"]))
        return [Zone(price=100.0, width=1.0, score=10, sources=["H4"])]

    outcomes = walk_forward(data, detector, warmup=10, horizon=2, step=5)
    assert calls and calls[0] == 11
    assert all(a < len(data) for a in calls)
    assert summarize(outcomes)["samples"] == len(outcomes)
