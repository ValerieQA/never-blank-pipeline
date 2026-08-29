"""Wednesday's restored July research package (#211).

The discovery half of the July restoration: RSS over the July feed set, the
inclusive July selector, and the July enrichment and angle stages, producing
the historical 46-field signal that ``wednesday_july`` generation consumes.

Isolated on purpose (#205): it carries Never Blank's Wednesday research
philosophy and must not be refactored into the shared pipeline, reconciled
with Monday, or kept in sync with ``scripts/research/``.
"""

from src.never_blank.wednesday_july.research.pipeline import (
    DELIBERATELY_UNUSED_CURRENT_RESEARCH,
    JULY_RESEARCH_STAGE_ORDER,
    SCHEMA_DEFAULTS,
    make_signal_id,
    run_wednesday_research,
)

__all__ = [
    "DELIBERATELY_UNUSED_CURRENT_RESEARCH",
    "JULY_RESEARCH_STAGE_ORDER",
    "SCHEMA_DEFAULTS",
    "make_signal_id",
    "run_wednesday_research",
]
