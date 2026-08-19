"""Evidence assessment — the step between retrieval and readiness (Issue #125).

Retrieval answers *what did we find*. This answers *is what we found sound
enough to reason from*. It does not answer whether the evidence is relevant to
the configured audience — that is Decision Lens — and it does not judge the
article that gets written — that is editorial acceptance. Collapsing any of
those into this one would let a soundness question be settled by a relevance
answer, or the reverse.

Until now nothing performed this step: adapters correctly default every claim
to ``not_assessed`` (they have no assessment policy), and the gate correctly
requires READY, so a real run could never pass. The gap was structural, not a
provider defect, and changing provider would not have closed it.

Two things are deliberately separated inside the assessor as well:

- **structural checks**, which are deterministic and can reject on their own —
  a claim with no traceable support, a source with no identity or locator;
- **the semantic judgment** of whether an excerpt actually supports its claim,
  which no rule can decide and which is therefore delegated to a typed verdict
  behind a narrow transport, exactly as editorial review already is.

A model saying "this looks credible" is not an assessment. The transport must
return a disposition and a bounded reason, and nothing it returns is trusted
beyond that shape.
"""

from __future__ import annotations

import json
from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.research.evidence import (
    EvidenceAssessorIdentity,
    EvidenceDisposition,
    EvidenceReadiness,
    ExtractedEvidence,
    NormalizedResearchArtifact,
    NormalizedSource,
    ResolutionStatus,
    UncertaintyMateriality,
)

ASSESSOR_ID = "never-blank-evidence-assessor"
ASSESSOR_VERSION = "1.0"

#: Dispositions that may contribute to a READY artifact. `qualified` is the
#: honest home of a credible single-source case: usable, with its limitation
#: recorded rather than dissolved.
USABLE_DISPOSITIONS = frozenset({EvidenceDisposition.ACCEPTED, EvidenceDisposition.QUALIFIED})


class EvidenceAssessmentError(RuntimeError):
    """Assessment could not be performed. Never a promotion of evidence."""


class _AssessmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceVerdict(_AssessmentModel):
    """One typed judgment about one evidence record."""

    evidence_id: str = Field(min_length=1)
    disposition: EvidenceDisposition
    rationale: str = Field(min_length=1, max_length=600)


class EvidenceJudgmentTransport(Protocol):
    """Narrow injectable boundary to the evidence judgment model."""

    def complete(self, *, instructions: str, request: str) -> str: ...


JUDGMENT_INSTRUCTIONS = """\
You assess retrieved research evidence. For each item you receive its claim
and the bounded excerpts cited as support for it.

Decide only this: does the cited support actually establish the claim?

  accepted  — the support establishes the claim as stated.
  qualified — the support establishes the claim within a real limitation you
              must name: a single source, an interested party reporting its
              own result, a dated or narrow context.
  rejected  — the support does not establish the claim, or the claim says more
              than the support carries.

Judge only what the excerpt shows. Do not use outside knowledge, do not assume
what the source probably meant, and never treat a confident tone as evidence.
A claim that is likely true but unsupported by its own excerpt is `rejected`.

Return ONLY one valid JSON object, no text outside it:

{"verdicts": [{"evidence_id": "...", "disposition": "accepted | qualified | rejected", "rationale": "one bounded sentence, checkable against the excerpt"}]}
"""


def _structural_rejection(
    item: ExtractedEvidence, sources: dict[str, NormalizedSource]
) -> Optional[str]:
    """A reason this item cannot be assessed at all, decided without a model."""

    if not (item.claim or "").strip():
        return "the record carries no claim"
    if not item.support:
        return "the claim cites no supporting excerpt"
    if any(not (ref.excerpt or "").strip() for ref in item.support):
        return "a cited excerpt is empty"
    for source_id in item.source_ids:
        source = sources.get(source_id)
        if source is None:
            return f"the claim cites source {source_id!r}, which the artifact does not declare"
        if not (source.title or "").strip():
            return f"source {source_id!r} has no identifiable title"
        if not (source.locator.value or "").strip():
            return f"source {source_id!r} has no locator"
    return None


#: A deliberate block is not an evidence question, so assessing evidence
#: cannot lift it. Every other readiness is re-derived from the assessment:
#: how much was retrieved is a fact about the operation, not about whether
#: what arrived supports the claim (Issue #125).
_NOT_AN_EVIDENCE_QUESTION = frozenset({EvidenceReadiness.BLOCKED})


def _readiness_for(
    evidence: tuple[ExtractedEvidence, ...],
    artifact: NormalizedResearchArtifact,
) -> EvidenceReadiness:
    """Readiness follows from the assessment; it is never chosen directly.

    Nothing here counts sources. Two strong records can be sufficient where
    five weak ones are not, and a retrieval that missed half of what it asked
    for may still have obtained what the claim needs — that judgment belongs
    to the evidence, and the retrieval outcome is recorded separately.
    """

    if artifact.readiness in _NOT_AN_EVIDENCE_QUESTION:
        return artifact.readiness

    if not evidence:
        return EvidenceReadiness.INSUFFICIENT
    if not any(item.disposition in USABLE_DISPOSITIONS for item in evidence):
        return EvidenceReadiness.INSUFFICIENT
    if any(item.disposition not in USABLE_DISPOSITIONS for item in evidence):
        # A rejected or conflicting record among usable ones is a real finding,
        # not something to drop quietly so the rest can pass.
        return EvidenceReadiness.NEEDS_REVIEW
    if any(c.resolution is ResolutionStatus.UNRESOLVED for c in artifact.contradictions):
        return EvidenceReadiness.NEEDS_REVIEW
    if any(
        u.materiality is UncertaintyMateriality.MATERIAL
        and u.resolution is ResolutionStatus.UNRESOLVED
        for u in artifact.uncertainties
    ):
        return EvidenceReadiness.NEEDS_REVIEW
    return EvidenceReadiness.READY


def _verdicts(
    pending: list[ExtractedEvidence], transport: EvidenceJudgmentTransport
) -> dict[str, EvidenceVerdict]:
    request = json.dumps(
        {
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "claim": item.claim,
                    "support": [ref.excerpt for ref in item.support],
                }
                for item in pending
            ]
        },
        ensure_ascii=False,
    )
    try:
        raw = transport.complete(instructions=JUDGMENT_INSTRUCTIONS, request=request)
    except Exception as exc:  # noqa: BLE001 — sanitized, never the provider's text
        raise EvidenceAssessmentError(
            f"evidence judgment transport failed ({type(exc).__name__})"
        ) from None

    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        verdicts = tuple(EvidenceVerdict.model_validate(v) for v in payload["verdicts"])
    except (ValidationError, ValueError, TypeError, KeyError):
        raise EvidenceAssessmentError(
            "evidence judgment output does not satisfy the assessment contract"
        ) from None

    by_id = {v.evidence_id: v for v in verdicts}
    missing = [item.evidence_id for item in pending if item.evidence_id not in by_id]
    if missing:
        raise EvidenceAssessmentError(
            f"evidence judgment returned no verdict for {missing!r}"
        )
    return by_id


def assess_artifact(
    artifact: NormalizedResearchArtifact,
    *,
    transport: EvidenceJudgmentTransport,
    assessor: EvidenceAssessorIdentity | None = None,
) -> NormalizedResearchArtifact:
    """Return the same artifact with its evidence assessed and readiness set.

    Records already carrying a disposition are left alone — this assesses what
    retrieval left `not_assessed`, and does not overrule a judgment already
    made. Readiness is derived from the result, never asserted.

    The assessor's identity is claimed only for work it performed. An artifact
    whose records were all assessed elsewhere is returned unattributed, so the
    canonical gate declines it rather than accepting someone else's judgment
    under this assessor's name.
    """

    identity = assessor or EvidenceAssessorIdentity(
        assessor_id=ASSESSOR_ID, version=ASSESSOR_VERSION
    )
    sources = {source.source_id: source for source in artifact.sources}
    preassessed = tuple(
        item.evidence_id for item in artifact.evidence
        if item.disposition is not EvidenceDisposition.NOT_ASSESSED
    )
    unassessed = tuple(
        item.evidence_id for item in artifact.evidence
        if item.disposition is EvidenceDisposition.NOT_ASSESSED
    )
    if preassessed and unassessed:
        # One artifact-level identity cannot say "this assessor judged these
        # records but not those". Rather than attribute work falsely — the
        # precise thing the gate exists to prevent — the mixed case fails
        # closed. Representing mixed provenance truthfully would need a
        # per-record attribution the accepted schema does not have.
        raise EvidenceAssessmentError(
            "artifact mixes pre-assessed and unassessed evidence, which this "
            f"contract cannot attribute truthfully: assessed={preassessed!r}, "
            f"unassessed={unassessed!r}"
        )

    assessed: list[ExtractedEvidence] = []
    pending: list[ExtractedEvidence] = []
    for item in artifact.evidence:
        if item.disposition is not EvidenceDisposition.NOT_ASSESSED:
            assessed.append(item)
            continue
        reason = _structural_rejection(item, sources)
        if reason is not None:
            assessed.append(
                item.model_copy(update={
                    "disposition": EvidenceDisposition.REJECTED,
                    "assessment_rationale": f"Not assessable: {reason}.",
                })
            )
            continue
        pending.append(item)

    if pending:
        by_id = _verdicts(pending, transport)
        for item in pending:
            verdict = by_id[item.evidence_id]
            assessed.append(
                item.model_copy(update={
                    "disposition": verdict.disposition,
                    "assessment_rationale": verdict.rationale,
                })
            )

    ordered = tuple(
        next(a for a in assessed if a.evidence_id == item.evidence_id)
        for item in artifact.evidence
    )
    return artifact.model_copy(update={
        "evidence": ordered,
        # Claimed only for work actually done. Nothing to assess means nothing
        # to attribute, and the artifact keeps whatever attribution it arrived
        # with — which for an unattributed artifact means the gate declines it.
        "assessor": identity if unassessed else artifact.assessor,
        "readiness": _readiness_for(ordered, artifact),
    })


class LlmChatEvidenceJudgmentTransport:
    """Production judgment transport backed by the repository LLM client."""

    def complete(self, *, instructions: str, request: str) -> str:
        from src.utils.llm_client import chat, model_enrich

        return chat(system=instructions, user=request, json_mode=True, model=model_enrich())
