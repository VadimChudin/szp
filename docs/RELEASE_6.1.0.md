# Smart Zones Pro Experimental 6.1.0-rc1

Causal and display fixes on top of `0f13e09`. **Not a stable replacement for 6.0.2.**

## Logic
- Closed-candle contract: forming bars are excluded (`is_closed` in collector CSV).
- Zone evidence is partitioned once; overlapping clusters no longer share the same wick.
- Confirmation filter no longer reintroduces `DEAD` zones to fill the chart.
- Reaction side is taken from the approach before contact, not the last close.
- Honest backtest uses bar-open time and H4-close availability; detector-only, not live-pipeline parity.

## Display
- Stale accumulation boxes are removed on empty snapshots.
- Object reuse checks type and clears selection so leftover dashed rectangles do not linger.

## Verification
- `python -m pytest -q python_core/tests` passed locally (440+).
- `ruff check python_core --select F,E9` passed.
- No MetaTrader compile/visual confirmation in this environment.

Installer is published only after GitHub Actions on `experiment/szp-6.1.0-rc1` succeeds.
