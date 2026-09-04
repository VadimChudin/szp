"""Empirical score calibration from walk-forward outcomes."""
from __future__ import annotations

from collections import defaultdict

from backtest import ZoneOutcome


def calibrate(outcomes: list[ZoneOutcome], bucket_size: int = 2,
              min_samples: int = 10) -> dict:
    buckets = defaultdict(list)
    for outcome in outcomes:
        bucket = int(outcome.score // bucket_size) * bucket_size
        buckets[bucket].append(outcome)
    report = {}
    for bucket, rows in sorted(buckets.items()):
        reacted = sum(row.outcome == "reacted" for row in rows)
        report[str(bucket)] = {
            "score_min": bucket,
            "score_max": bucket + bucket_size - 1,
            "samples": len(rows),
            "reactions": reacted,
            "reaction_rate": reacted / len(rows) if rows else 0.0,
            "reliable": len(rows) >= min_samples,
        }
    return {
        "bucket_size": bucket_size,
        "min_samples": min_samples,
        "buckets": report,
        "recommended": recommended_weights(report),
    }


def recommended_weights(report: dict) -> dict:
    """Return monotonic empirical multipliers, never silently change scoring."""
    reliable = [v for v in report.values() if v.get("reliable")]
    if not reliable:
        return {}
    baseline = max(sum(v["reaction_rate"] for v in reliable) / len(reliable), 0.01)
    return {
        str(v["score_min"]): round(v["reaction_rate"] / baseline, 4)
        for v in reliable
    }
