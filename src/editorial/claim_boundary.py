"""The claim boundary a run's decision imposes on its own writing (Issue #131).

The Decision Lens already decides what a run may claim: an explicit
``EditorialClaimMode`` and, in bounded mode, the restrictions the judgment bound
itself to. Until this module that decision reached ``decision.json`` and stopped
there — the stages that write and rewrite the article had no representation of
it, so an article could be told to generalize into audience-level statements
with nothing saying where generalization stops.

This module derives one deterministic text block from two already-validated
artifacts — the canonical decision and the current-run research — and nothing
else. It contains no signal, brand, company, sector or audience vocabulary: the
rules come from the declared claim mode, the supported facts come from the
accepted evidence, and the restrictions come from the judgment. A different
lens profile with different content produces a different block through the same
code.

It is prompt material, not a gate. It cannot make an article truthful; it gives
the writer and the reviser the same authoritative picture the reviewer already
has, so "do not invent facts" becomes checkable rather than aspirational.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from src.editorial.decision_contract import (
    DecisionLensDecisionArtifact,
    EditorialClaimMode,
)
from src.research.evidence import EvidenceDisposition, NormalizedResearchArtifact


#: Dispositions whose evidence may be quoted as established fact. Anything else
#: — rejected, conflicting, not yet assessed — is deliberately absent from the
#: supported set rather than presented with a caveat, because a caveat is
#: something a model can drop.
_SUPPORTABLE = frozenset({EvidenceDisposition.ACCEPTED, EvidenceDisposition.QUALIFIED})

_UNIVERSAL_RULES = (
    "Every factual assertion must trace to one of the supported facts below.",
    "Use the supported figures exactly as recorded. Do not round, soften, "
    "approximate or restate them as ranges.",
    "Attribute each supported fact to the context it was recorded in. Do not "
    "attribute it to a different publisher, platform or programme.",
    "Anything not in the supported facts is your own interpretation and must "
    "read as one: an observation, a question, a hypothesis or a decision "
    "prompt, never as an established fact about the world.",
)

_BOUNDED_RULES = (
    "The supported facts describe the context they were observed in and no "
    "other. Do not restate an outcome observed elsewhere as an outcome "
    "observed for the reader's situation.",
    "You may address the reader's situation only as a question, observation, "
    "hypothesis or decision prompt raised by the supported facts.",
    "Do not assert what readers in that situation typically do, receive, "
    "experience or believe unless a supported fact establishes it. Illustrative "
    "situations must read as hypothetical, not as reported behaviour.",
)

_DIRECT_RULES = (
    "You may address the reader's situation directly where a supported fact "
    "establishes it, and only that far.",
)


class SupportedFact(BaseModel):
    """One evidence item the article is allowed to state as fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    claim: str
    source_ids: tuple[str, ...]
    excerpts: tuple[str, ...] = ()


class ClaimBoundary(BaseModel):
    """What this run may claim, derived from its own decision and evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_mode: EditorialClaimMode
    restrictions: tuple[str, ...]
    supported_facts: tuple[SupportedFact, ...]

    @property
    def rules(self) -> tuple[str, ...]:
        mode_rules = (
            _BOUNDED_RULES
            if self.claim_mode is EditorialClaimMode.BOUNDED_EXTERNAL_CASE
            else _DIRECT_RULES
        )
        return _UNIVERSAL_RULES + mode_rules


def build_claim_boundary(
    decision: DecisionLensDecisionArtifact,
    research: NormalizedResearchArtifact,
) -> ClaimBoundary:
    """Derive the boundary from the run's own validated artifacts.

    Only evidence the decision actually cited is offered as supported fact.
    Evidence present in the run but uncited is not support the decision relied
    on, and presenting it as such would let an article rest on material the
    Decision Lens never weighed.
    """

    cited = set(decision.evidence_ids)
    facts = tuple(
        SupportedFact(
            evidence_id=item.evidence_id,
            claim=item.claim,
            source_ids=tuple(item.source_ids),
            excerpts=tuple(
                support.excerpt for support in item.support if support.excerpt.strip()
            ),
        )
        for item in research.evidence
        if item.evidence_id in cited and item.disposition in _SUPPORTABLE
    )
    return ClaimBoundary(
        claim_mode=decision.judgment.claim_mode,
        restrictions=tuple(
            item for item in decision.judgment.restrictions if item.strip()
        ),
        supported_facts=facts,
    )


def render_claim_boundary(boundary: ClaimBoundary) -> str:
    """Render the boundary as deterministic prompt text.

    Stable ordering and exact quoting matter: the same boundary must produce
    the same text in generation and in revision, or the two halves of the run
    would be working from different pictures of the truth.
    """

    lines = [
        "",
        "CLAIM BOUNDARY — binding for this article "
        f"(claim mode: {boundary.claim_mode.value}).",
        "",
        "Supported facts (the only material you may state as fact):",
        json.dumps(
            [fact.model_dump(mode="json") for fact in boundary.supported_facts],
            ensure_ascii=False,
        ),
        "",
        "Rules:",
    ]
    lines.extend(f"- {rule}" for rule in boundary.rules)
    if boundary.restrictions:
        lines.append("")
        lines.append("Restrictions recorded by the Decision Lens for this run:")
        lines.extend(f"- {item}" for item in boundary.restrictions)
    lines.append("")
    return "\n".join(lines)


def claim_boundary_text(
    decision: DecisionLensDecisionArtifact | None,
    research: NormalizedResearchArtifact | None,
) -> str | None:
    """Convenience for callers that may legitimately have neither artifact.

    Returns ``None`` when the boundary cannot be derived, so a caller adds
    nothing rather than an empty or half-built block. Non-canonical callers
    (legacy dictionary paths, VI) keep their exact prior prompts.
    """

    if decision is None or research is None:
        return None
    return render_claim_boundary(build_claim_boundary(decision, research))
