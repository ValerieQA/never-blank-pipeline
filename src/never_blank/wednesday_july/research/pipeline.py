"""Wednesday research — the July 6 2026 discovery path, restored (#211).

The other half of the restoration. #207/#208 restored the July *generation*
core and #209/#210 wired it into the publication lifecycle, but both began
from an already-existing signal. The signal itself was still produced by the
current shared research path, whose feed set and selector are precisely what
made the Versant specimen unreachable (#206):

* ``218719a`` (2026-07-21) replaced CNBC/Bloomberg/TechCrunch/Ars with
  small-business feeds — removing the feed the specimen came from;
* ``a557855`` (2026-07-21) rewrote the selector to **"ALWAYS REJECT … Large
  company M&A"**, where July's said *"Be inclusive — prefer false positives
  over missed signals."*

This module restores July's stage order over July's own feed set:

    RSS fetch/parse  (requests + xml.etree.ElementTree, no Exa)
      → select_indices      "be inclusive"
      → enrich_candidates   REGION/INDUSTRY/SIGNAL_TYPE/raw_summary
      → score               (July Stage 3, preserved)
      → enrich_signal       the 17-field case contract
      → generate_angles     POTENTIAL_HOOK, NEVER_BLANK_ANGLE, BLOG_ANGLE …
      → the historical 46-field signal

The result is the object ``wednesday_july.generate_wednesday_article``
already consumes. Nothing here imports the current Monday selector, source
eligibility, pattern extractor, owner-protagonist policy, the canonical
Decision Lens, or the current SMB feed configuration — asserted by test.

Only current technical infrastructure is shared: ``llm_client`` supplies the
provider client, per-stage model routing, the run call budget (#171) and the
retry ceiling (#170); ``requests`` and logging are unchanged.
"""

from __future__ import annotations

from typing import Callable, Optional

from src.never_blank.wednesday_july.research.angles import add_angles
from src.never_blank.wednesday_july.research.discover import (
    make_signal_id,
    run_discovery,
)
from src.never_blank.wednesday_july.research.enrich import enrich_candidates
from src.never_blank.wednesday_july.research.score import score_candidates
from src.utils.logger import get_logger

log = get_logger("never_blank.wednesday_july.research")

#: July's stage order, exposed so a regression can assert the shape.
JULY_RESEARCH_STAGE_ORDER = (
    "discovery",          # RSS fetch/parse → select_indices → enrich_candidates
    "scoring",
    "enrichment",         # enrich_signal
    "angles",             # generate_angles
)

#: Current shared research behaviour this path deliberately does not use.
#: Named so the omissions are recorded decisions, not oversights.
DELIBERATELY_UNUSED_CURRENT_RESEARCH = (
    "ExaResearchAdapter",
    "scripts.research.discover",          # current selector + SMB feed set
    "config/research_sources.yaml",       # current small-business feeds
    "select_eligible_signal",             # current role eligibility judgment
    "pattern_extractor",
)

#: The historical 46-field signal defaults, copied verbatim from
#: ``scripts/research/run_daily_research.py`` at ``c7d3a23``. Every field the
#: July product carried is preserved — including the ones current code does
#: not read — because the signal contract is the product, not an internal
#: convenience.
SCHEMA_DEFAULTS = {
    "CORE_FACT": "", "WHY_IT_MATTERS_TO_BUSINESS": "", "BUSINESS_RESPONSES_OBSERVED": "",
    "REAL_COMPANY_EXAMPLE": None, "PROBLEM_FACED": "", "RESPONSE_TAKEN": "",
    "OUTCOME_IF_KNOWN": "unknown", "SOURCE_FOR_CASE": None, "BUSINESS_LESSON": "",
    "DID_IT_WORK": "unknown", "EVIDENCE_OF_OUTCOME": "", "TIME_HORIZON": "",
    "COUNTER_EXAMPLE": "", "WHY_THIS_CASE_IS_INTERESTING": "",
    "ARTICLE_READINESS_SCORE": "0", "TARGET_AUDIENCE": "", "PRIMARY_CHANNEL": "",
    "CORE_TENSION": "", "LINKEDIN_ANGLE": "", "BLOG_ANGLE": "", "THREADS_ANGLE": "",
    "STORY_ANGLE": "", "DISCUSSION_POTENTIAL": "", "SIGNAL_STRENGTH": "",
    "CHANNEL_FIT_SCORE": "0", "POTENTIAL_HOOK": "", "INTERESTING_QUESTION": "",
    "NEVER_BLANK_ANGLE": "", "POSSIBLE_SIGNATURE_LINE": "", "SOURCE_QUALITY": "",
    "CONFIDENCE": "low", "RECOMMENDED_FOR_ARTICLE": "false",
    "NOTES": "", "APPROVED_OVERRIDE": "", "score_reason": "",
    "raw_summary": "", "discovery_confidence": "",
}


def run_wednesday_research(
    seen_ids: Optional[set] = None,
    *,
    discovery: Callable = run_discovery,
    scorer: Callable = score_candidates,
    enricher: Callable = enrich_candidates,
    angler: Callable = add_angles,
) -> list[dict]:
    """Produce historical-shape Wednesday signals from the July feed set.

    Returns a list of 46-field signals, newest discovery first, each ready
    for ``generate_wednesday_article``. Returns ``[]`` when discovery finds
    nothing new — publishing nothing is a correct outcome, exactly as it was
    in July.

    The stage callables are injectable so the orchestration can be exercised
    without network or paid calls; production uses the July defaults.
    """

    seen = set(seen_ids or ())

    log.info("=== Wednesday July research — Stage 1: Discovery ===")
    candidates = discovery(seen)
    if not candidates:
        log.info("No new Wednesday candidates — research complete")
        return []

    fresh = [c for c in candidates if c.get("SIGNAL_ID") not in seen]
    log.info(
        "Wednesday candidates: %d discovered, %d unseen", len(candidates), len(fresh)
    )
    if not fresh:
        return []

    log.info("=== Stage 3: Scoring ===")
    scored = scorer(fresh)

    log.info("=== Stage 4: Enrichment (%d candidates) ===", len(scored))
    enriched = enricher(scored)

    log.info("=== Stage 5: Angles ===")
    with_angles = angler(enriched)

    signals = []
    for signal in with_angles:
        full = dict(SCHEMA_DEFAULTS)
        full.update(signal)
        signals.append(full)

    log.info("Wednesday July research produced %d signals", len(signals))
    return signals


__all__ = [
    "DELIBERATELY_UNUSED_CURRENT_RESEARCH",
    "JULY_RESEARCH_STAGE_ORDER",
    "SCHEMA_DEFAULTS",
    "make_signal_id",
    "run_wednesday_research",
]
