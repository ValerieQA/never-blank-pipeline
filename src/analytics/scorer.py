"""
Never Blank Analytics — Scoring Layer (Phase 4D.3).

Converts a normalized AnalyticsRecord into a single analytics_score (0.0–1.0)
that can be written back to PublishedEntry via history.update_entry().

Design decisions:
- Scoring is the ONLY place that calls update_entry(). Collectors never do.
- The formula version is recorded alongside the score so that historical scores
  can be recomputed when the formula changes without touching the collectors.
- score=None means no scoreable metrics were available (not zero performance).
- Weights are defined per-platform because what matters on LinkedIn
  (link_clicks, profile_visits) differs from what matters on Instagram (saves, reach).

Extending:
  To change the formula: bump SCORER_VERSION, update _weights or _score_record().
  All previously scored entries retain their version tag and can be re-scored
  by running the orchestrator again — update_entry() overwrites existing values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.strategy.models import AnalyticsRecord, MetricValue
from src.utils.logger import get_logger

log = get_logger("analytics.scorer")

SCORER_VERSION = "v1"

# Per-platform metric weights. Keys match AnalyticsRecord field names.
# Values are relative importance weights (need not sum to 1 — normalized internally).
# A missing platform falls back to _DEFAULT_WEIGHTS.
_PLATFORM_WEIGHTS: dict[str, dict[str, float]] = {
    "instagram": {
        "reach":         1.5,
        "saves":         2.0,   # saves = strongest signal of resonance on Instagram
        "likes":         1.0,
        "comments":      1.5,
        "shares":        1.5,
        "profile_visits": 0.5,
        "link_clicks":   1.0,
    },
    "facebook": {
        "reach":         1.5,
        "likes":         1.0,
        "comments":      1.5,
        "shares":        2.0,   # shares = primary amplification signal on Facebook
        "link_clicks":   1.5,
        "website_sessions": 1.0,
    },
    "linkedin": {
        "impressions":   1.0,
        "likes":         1.0,
        "comments":      2.0,   # comments on LinkedIn = high-value engagement signal
        "shares":        1.5,
        "link_clicks":   2.0,
        "profile_visits": 1.0,
        "website_sessions": 1.5,
    },
    "threads": {
        "likes":         1.0,
        "comments":      2.0,
        "shares":        1.5,
        "reach":         1.0,
    },
    "telegram": {
        "views":         1.0,
        "shares":        2.0,
        "link_clicks":   1.5,
    },
    "blog": {
        "views":         1.0,
        "website_sessions": 1.5,
        "link_clicks":   2.0,   # link_clicks from blog = lead-adjacent signal
        "leads":         3.0,
        "qualified_leads": 5.0,
    },
}

_DEFAULT_WEIGHTS: dict[str, float] = {
    "impressions": 1.0,
    "reach":       1.0,
    "views":       1.0,
    "likes":       1.0,
    "comments":    1.5,
    "shares":      1.5,
    "saves":       1.5,
    "link_clicks": 2.0,
    "leads":       3.0,
}


def _numeric(v: MetricValue) -> Optional[float]:
    """Return numeric value or None for sentinel/missing values."""
    if v is None or v == "not_collected":
        return None
    return float(v)


def _score_record(record: AnalyticsRecord) -> Optional[float]:
    """
    Compute a normalized score for one AnalyticsRecord.

    Strategy: weighted sum of available metrics, normalized against a
    platform-typical ceiling to produce a 0.0–1.0 score.

    Returns None if no weighted metric has a numeric value (cannot score).

    The ceiling is empirical — deliberately conservative so that
    above-average content scores > 0.5 and exceptional content approaches 1.0.
    Ceilings will need calibration once real data flows in (bump SCORER_VERSION).
    """
    weights = _PLATFORM_WEIGHTS.get(record.platform, _DEFAULT_WEIGHTS)

    # Platform engagement ceilings for normalization (empirical, v1 estimates).
    # These represent "solid performing" content — not viral outliers.
    _CEILINGS: dict[str, dict[str, float]] = {
        "instagram": {"reach": 1500, "saves": 80,   "likes": 200, "comments": 30,  "shares": 40,  "profile_visits": 60,  "link_clicks": 20},
        "facebook":  {"reach": 2000, "likes": 150,  "comments": 25, "shares": 60,  "link_clicks": 80, "website_sessions": 50},
        "linkedin":  {"impressions": 3000, "likes": 100, "comments": 30, "shares": 20,  "link_clicks": 60, "profile_visits": 100, "website_sessions": 40},
        "threads":   {"likes": 150,  "comments": 30, "shares": 40,  "reach": 1000},
        "telegram":  {"views": 500,  "shares": 30,   "link_clicks": 40},
        "blog":      {"views": 600,  "website_sessions": 400, "link_clicks": 50, "leads": 5, "qualified_leads": 2},
    }
    ceilings = _CEILINGS.get(record.platform, {})

    weighted_sum = 0.0
    weight_total = 0.0

    for field, weight in weights.items():
        value = _numeric(getattr(record, field, None))
        if value is None:
            continue
        ceiling = ceilings.get(field, max(value, 1.0))  # fallback: treat value as ceiling (score=1.0)
        normalized = min(value / ceiling, 1.0)           # cap at 1.0
        weighted_sum += normalized * weight
        weight_total += weight

    if weight_total == 0.0:
        return None

    return round(weighted_sum / weight_total, 4)


def score_records(records: list[AnalyticsRecord]) -> list[dict]:
    """
    Score a list of AnalyticsRecord objects.

    Returns a list of patch dicts ready for history.update_entry():
        [
            {
                "content_id": "...",
                "analytics_score": 0.74,
                "analytics_fetched_at": "2026-08-15T12:00:00+00:00",
                "analytics_version": "v1",
            },
            ...
        ]

    Records that cannot be scored (no numeric metrics) are excluded
    from the output — their PublishedEntry remains with analytics_score=None.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    patches: list[dict] = []

    for record in records:
        score = _score_record(record)
        if score is None:
            log.info(
                "scorer: no scoreable metrics for content_id=%s platform=%s — skipping",
                record.content_id, record.platform,
            )
            continue
        patches.append({
            "content_id":          record.content_id,
            "analytics_score":     score,
            "analytics_fetched_at": now,
            "analytics_version":   SCORER_VERSION,
        })
        log.info(
            "scorer: content_id=%s platform=%s score=%.4f version=%s",
            record.content_id, record.platform, score, SCORER_VERSION,
        )

    return patches
