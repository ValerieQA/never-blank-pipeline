"""What the research audience label is, and what it is not (Issue #121).

The discovery layer tags every signal with a coarse taxonomy label —
``agency``, ``founder``, ``unclassified`` and so on. That label describes the
*source item*. It was also being passed to the strategy as an audience
*request*, so a label broader than any configured audience ended the run at
intake: no research artifact, no decision, no reasoning. A useful documented
mechanism and an irrelevant corporate case were rejected identically, for the
same wrong reason.

Deciding whether external evidence supports a bounded claim for the configured
audience is Decision Lens's work, and Decision Lens is built for it — the
relevance taxonomy already distinguishes documented impact and sector evidence
from analogy, and ``PROCEED`` already refuses a judgment resting on analogy
alone. A coarse discovery label must not impersonate that reasoning.

So this module answers one narrow question: *is this label an audience request
at all?* An explicit request is still resolved strictly and still fails closed
when it is unknown or ambiguous — a routing error must never be rescued by a
default. A research-derived label that names no configured audience is simply
not a request, and the strategy's own configured-default path supplies the
identity, recording truthfully that it did.
"""

from __future__ import annotations

from typing import Optional, Protocol

from src.strategy.execution_context import StrategyExecutionError


class _AudienceResolvingView(Protocol):
    def select_audience(self, requested: Optional[str]): ...


#: Assignment origins whose ``target_audience`` comes from the discovery
#: taxonomy rather than from a caller asking for a specific audience. The
#: JSONL adapter maps ``TARGET_AUDIENCE`` straight through and never passes an
#: explicit override, so for these origins the label is always research-derived.
RESEARCH_DERIVED_ORIGINS = frozenset({"jsonl"})


def is_research_derived(origin: str) -> bool:
    return origin in RESEARCH_DERIVED_ORIGINS


def audience_request(assignment, view: _AudienceResolvingView) -> Optional[str]:
    """The audience this run actually requests, or ``None`` to use the default.

    ``None`` is returned only when there is nothing to request — either the
    assignment carries no label, or it carries a research label that names no
    configured audience. In both cases the strategy's configured default takes
    over and records ``selection_source="configured-default"``, so the account
    of the run never claims the research label was the selected audience.

    An explicit request is returned unchanged even when it will fail: that
    failure is the point. Silently substituting a default for a caller who
    asked for a specific audience would turn a routing error into a
    publication about the wrong people.
    """

    label = assignment.target_audience
    if label is None or not str(label).strip():
        return None

    if not is_research_derived(assignment.origin):
        return label                      # explicit request — strict, fail closed

    try:
        view.select_audience(label)
    except StrategyExecutionError:
        # Unknown or ambiguous: the label does not uniquely name a configured
        # audience, so it is source metadata and nothing more. It stays on the
        # assignment, attributable and unrewritten; it just stops routing.
        return None
    return label
