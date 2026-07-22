"""
Never Blank Strategy Engine — Market Analyzer (Phase 2).

Bridge between the research layer (discover.py signal dicts) and the strategy
layer (MarketSignal → PatternRecord via strategic pattern_extractor).

Traceability: every ContentPlanItem can trace back to:
  ContentPlanItem.market_signal
    → research signal HEADLINE + SOURCE_URL
      → PatternRecord.pattern_id + observed_signals
        → MarketSignal.source + source_date

discover.py output dict keys:
  SIGNAL_ID, HEADLINE, SOURCE_URL, SOURCE_DATE, REGION, INDUSTRY,
  SIGNAL_TYPE, raw_summary, discovery_confidence, SOURCE_NAME
"""

from __future__ import annotations

import json
from typing import Optional

from src.strategy.models import Confidence, MarketSignal, PatternRecord
from src.strategy.pattern_extractor import (
    SignalRejectedError,
    extract_strategic_pattern,
)
from src.utils.logger import get_logger

log = get_logger("strategy.market_analyzer")


def _confidence(value: str) -> Confidence:
    try:
        return Confidence(value.lower())
    except (ValueError, AttributeError):
        return Confidence.MEDIUM


def discover_signal_to_market_signal(signal: dict) -> MarketSignal:
    """
    Convert a discover.py enriched signal dict to a MarketSignal.

    Field mapping:
      HEADLINE                  → signal
      SOURCE_URL                → source
      SOURCE_DATE               → source_date
      INDUSTRY                  → market_area
      raw_summary               → change_detected + why_it_matters
      SIGNAL_TYPE               → affected_audience (approximate)
      discovery_confidence      → confidence
    """
    raw_summary = signal.get("raw_summary", "")
    headline    = signal.get("HEADLINE", "")

    # Combine headline + summary for richer signal description
    full_signal = f"{headline}. {raw_summary}".strip(" .")

    return MarketSignal(
        signal=full_signal,
        source=signal.get("SOURCE_URL", signal.get("SOURCE_NAME", "")),
        source_date=signal.get("SOURCE_DATE"),
        market_area=signal.get("INDUSTRY", "small business"),
        affected_audience=f"{signal.get('SIGNAL_TYPE', 'small business owners')} — {signal.get('REGION', 'US')}",
        change_detected=raw_summary[:300] if raw_summary else headline,
        why_it_matters=raw_summary[300:600] if len(raw_summary) > 300 else "",
        business_implication="",     # enriched by LLM in pattern_extractor
        sales_implication="",
        compound_presence_implication="",
        confidence=_confidence(signal.get("discovery_confidence", "medium")),
        freshness=signal.get("SOURCE_DATE", "unknown"),
        evidence=[signal.get("SOURCE_URL", "")] if signal.get("SOURCE_URL") else [],
    )


def analyze_signals(
    signals: list[dict],
) -> tuple[list[PatternRecord], list[dict]]:
    """
    Convert research signals to strategic patterns.

    Args:
        signals: list of enriched signal dicts from discover.py

    Returns:
        (accepted_patterns, rejected_log)

    Rejected signals are logged and returned — never silently dropped.
    Each rejected entry: {"signal_id": ..., "headline": ..., "reason": ...}
    """
    if not signals:
        log.info("market_analyzer: no signals to analyze")
        return [], []

    accepted: list[PatternRecord] = []
    rejected: list[dict] = []

    for raw in signals:
        signal_id  = raw.get("SIGNAL_ID", "unknown")
        source_url = raw.get("SOURCE_URL", "")
        headline   = raw.get("HEADLINE", "")[:80]

        try:
            market_signal = discover_signal_to_market_signal(raw)
            pattern       = extract_strategic_pattern(market_signal)
            # Inject traceability: link pattern back to the originating research signal.
            pattern = pattern.model_copy(update={
                "source_signal_ids": [signal_id],
                "source_urls": [source_url] if source_url else [],
            })
            accepted.append(pattern)
            log.info("market_analyzer: accepted — %r", pattern.pattern_name[:60])
        except SignalRejectedError as exc:
            rejected.append({
                "signal_id": signal_id,
                "headline":  headline,
                "reason":    str(exc),
            })
            log.info("market_analyzer: rejected signal %s — %s", signal_id, exc)
        except Exception as exc:
            rejected.append({
                "signal_id": signal_id,
                "headline":  headline,
                "reason":    f"extraction error: {exc}",
            })
            log.error("market_analyzer: error on signal %s: %s", signal_id, exc)

    log.info(
        "market_analyzer: %d accepted, %d rejected from %d signals",
        len(accepted), len(rejected), len(signals),
    )
    return accepted, rejected


def patterns_to_strategy_context(patterns: list[PatternRecord]) -> dict:
    """
    Summarize extracted patterns into strategy-level context dict.
    Used to inform Strategy Selection (Phase 3) and content planning.
    """
    if not patterns:
        return {"patterns": [], "dominant_mechanism": "", "compound_presence_themes": []}

    # Rank by confidence
    high    = [p for p in patterns if p.confidence.value == "high"]
    medium  = [p for p in patterns if p.confidence.value == "medium"]
    ranked  = (high + medium) or patterns

    dominant = ranked[0] if ranked else patterns[0]

    return {
        "patterns": [
            {
                "pattern_id":             p.pattern_id,
                "pattern_name":           p.pattern_name,
                "small_business_situation": p.small_business_situation,
                "underlying_mechanism":   p.underlying_mechanism,
                "business_risk":          p.business_risk,
                "sales_relevance":        p.sales_relevance,
                "compound_presence_relevance": p.compound_presence_relevance,
                "confidence":             p.confidence.value,
            }
            for p in ranked[:10]
        ],
        "dominant_mechanism":        dominant.underlying_mechanism,
        "compound_presence_themes": [p.compound_presence_relevance for p in ranked[:5] if p.compound_presence_relevance],
        "total_patterns":           len(patterns),
    }
