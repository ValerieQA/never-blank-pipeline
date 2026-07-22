"""
Never Blank Strategy Engine — Strategic Pattern Extractor.

Converts raw market signals into strategy-ready PatternRecords.

This is the STRATEGY-LEVEL pattern extractor. It is distinct from the
editorial-level pattern_extractor in src/editorial/pattern_extractor.py:

  src/editorial/pattern_extractor.py
    Input:  a single news/RSS signal
    Output: owner-centered visibility pattern for article generation
    Gate:   rejects signals with no editorial fit

  src/strategy/pattern_extractor.py  (this file)
    Input:  a MarketSignal (richer structure, from market analysis)
    Output: PatternRecord with sales_relevance, content_relevance,
            compound_presence_relevance, business_risk, business_opportunity
    Gate:   rejects signals outside Never Blank's strategic territory

Decision 42: Pattern Extractor built as a full module, not a stub.
Decision 13: Territory = visibility, presence, recognition, customer memory only.
Decision 34: Target segment = small B2B service businesses (agencies, consultants, MSPs).
"""

import json
import uuid
from typing import Optional

from src.strategy.models import Confidence, MarketSignal, PatternRecord
from src.utils.llm_client import chat, model_article
from src.utils.logger import get_logger

log = get_logger("strategy.pattern_extractor")

_SYSTEM = """You are a strategic pattern analyst for Never Blank.

Never Blank's territory: visibility, presence, recognition, customer memory,
consistent communication, owner dependency, and the communication-to-sales
relationship for small B2B service businesses.

Target segment: agencies (digital/web/dev/creative), independent consultants,
and managed service providers (MSPs) — single decision-maker businesses.

Your task: extract a strategic pattern from a market signal.

A strategic pattern is NOT:
- A summary of the news item
- A general business trend
- Advice or a recommendation
- A corporate strategy observation

A strategic pattern IS:
- An observed mechanism in how small B2B service businesses lose or maintain visibility
- A structural cause that repeats across businesses, not an individual company's decision
- Something a business owner in the target segment would recognize in their own situation
- Connected to the cumulative effect of consistent presence (Compound Presence)

REJECTION CRITERIA — return signal_fit: "reject" if:
- The signal is about large company M&A, earnings, or product launches with no owner-level mechanism
- The signal is about AI model releases or chip shortages with no presence/visibility angle
- The signal is generic motivational or tips content with no observable mechanism
- The signal does not connect to visibility, presence, recognition, or customer memory
- The signal is macro-economic with no specific effect on how service businesses stay visible

Return JSON:
{
  "signal_fit": "use" | "reject",
  "rejection_reason": null | "string",
  "pattern_name": "concise name for the pattern",
  "small_business_situation": "what the owner's situation looks like",
  "underlying_mechanism": "the structural cause",
  "customer_behavior": "what customers do or stop doing as a result",
  "business_risk": "concrete commercial risk from this pattern",
  "business_opportunity": "what changes if the owner acts against this pattern",
  "sales_relevance": "why this matters for Never Blank's commercial message",
  "content_relevance": "what kind of article or post this enables",
  "compound_presence_relevance": "how this connects to the cumulative effect of consistent presence",
  "confidence": "high" | "medium" | "low"
}"""


class SignalRejectedError(Exception):
    pass


def extract_strategic_pattern(signal: MarketSignal) -> PatternRecord:
    """
    Extract a strategic PatternRecord from a MarketSignal.

    Raises SignalRejectedError if the signal does not fit Never Blank's territory.
    """
    user = f"""Market signal:

Signal: {signal.signal}
Source: {signal.source}
Source date: {signal.source_date or "unknown"}
Market area: {signal.market_area}
Affected audience: {signal.affected_audience}
Change detected: {signal.change_detected}
Why it matters: {signal.why_it_matters}
Business implication: {signal.business_implication}
Sales implication: {signal.sales_implication}
Compound presence implication: {signal.compound_presence_implication}
Evidence: {json.dumps(signal.evidence)}

Extract the strategic pattern. Return JSON only."""

    raw = chat(_SYSTEM, user, json_mode=True, model=model_article())
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Pattern extractor returned invalid JSON: {exc}") from exc

    if data.get("signal_fit") == "reject":
        reason = data.get("rejection_reason") or "signal does not fit Never Blank strategic territory"
        log.info("Pattern extractor: signal rejected — %s", reason)
        raise SignalRejectedError(reason)

    pattern_id = f"pat-{uuid.uuid4().hex[:12]}"

    try:
        confidence = Confidence(data.get("confidence", "medium"))
    except ValueError:
        confidence = Confidence.MEDIUM

    record = PatternRecord(
        pattern_id=pattern_id,
        pattern_name=data.get("pattern_name", ""),
        observed_signals=[signal.signal],
        small_business_situation=data.get("small_business_situation", ""),
        underlying_mechanism=data.get("underlying_mechanism", ""),
        customer_behavior=data.get("customer_behavior", ""),
        business_risk=data.get("business_risk", ""),
        business_opportunity=data.get("business_opportunity", ""),
        sales_relevance=data.get("sales_relevance", ""),
        content_relevance=data.get("content_relevance", ""),
        compound_presence_relevance=data.get("compound_presence_relevance", ""),
        confidence=confidence,
    )

    log.info(
        "Pattern extractor: pattern extracted — %r (confidence=%s)",
        record.pattern_name[:60], record.confidence.value,
    )
    return record


def extract_patterns_from_signals(
    signals: list[MarketSignal],
) -> tuple[list[PatternRecord], list[dict]]:
    """
    Process a list of market signals. Returns (accepted_patterns, rejected_signals).

    Rejected signals are logged and returned for audit — never silently dropped.
    """
    accepted: list[PatternRecord] = []
    rejected: list[dict] = []

    for signal in signals:
        try:
            pattern = extract_strategic_pattern(signal)
            accepted.append(pattern)
        except SignalRejectedError as exc:
            rejected.append({"signal": signal.signal, "reason": str(exc)})
            log.info("Rejected: %s — %s", signal.signal[:60], exc)
        except Exception as exc:
            rejected.append({"signal": signal.signal, "reason": f"extraction error: {exc}"})
            log.error("Pattern extraction error for signal %r: %s", signal.signal[:40], exc)

    log.info(
        "Pattern extraction complete: %d accepted, %d rejected from %d signals",
        len(accepted), len(rejected), len(signals),
    )
    return accepted, rejected
