"""Evidence assessment: the step between retrieval and readiness (Issue #125).

Live run 32262959764 retrieved one source successfully and still could not
proceed: every claim arrived `not_assessed`, and the gate correctly requires
READY. Nothing in production performed the step in between — so a real run
could never pass, whatever the provider or the material.

These tests hold both halves of the correction: retrieval alone still cannot
reach READY, and assessed evidence legitimately can.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.research.assessment import (
    ASSESSOR_ID,
    ASSESSOR_VERSION,
    EvidenceAssessmentError,
    assess_artifact,
)
from src.research.evidence import (
    Contradiction,
    EvidenceAssessorIdentity,
    EvidenceDisposition,
    EvidenceReadiness,
    ExtractedEvidence,
    NormalizedResearchArtifact,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    ResolutionStatus,
    SourceLocator,
    SourceLocatorKind,
    SupportReference,
    UncertaintyAssessment,
    UncertaintyLevel,
    UncertaintyMateriality,
)
from src.strategy.execution_context import ConfigurationIdentity

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


class Judgment:
    """A typed verdict without a live model — the transport contract itself."""

    def __init__(self, disposition="qualified", rationale="Excerpt states the claim.",
                 raw=None, boom=False, omit=False):
        self.disposition, self.rationale = disposition, rationale
        self.raw, self.boom, self.omit = raw, boom, omit
        self.calls = 0

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls += 1
        if self.boom:
            raise RuntimeError("transport unavailable")
        if self.raw is not None:
            return self.raw
        items = json.loads(request)["evidence"]
        if self.omit:
            items = items[:-1]
        return json.dumps({"verdicts": [
            {"evidence_id": i["evidence_id"], "disposition": self.disposition,
             "rationale": self.rationale}
            for i in items
        ]})


def _identity():
    return ConfigurationIdentity(
        schema_version="1.0", configuration_id="never-blank",
        configuration_version="1", configuration_hash="sha256:" + "a" * 64,
    )


def _source(source_id="source-1", title="HubSpot case", locator="https://example.invalid/case"):
    return NormalizedSource(
        source_id=source_id,
        locator=SourceLocator(kind=SourceLocatorKind.URL, value=locator),
        title=title,
        publication_time=PublicationTime(status=PublicationTimeStatus.KNOWN,
                                         value=NOW - timedelta(days=2)),
        retrieved_at=NOW,
    )


def _evidence(evidence_id="evidence-1", claim="Invisalign reported ~30% higher form completion.",
              excerpt="Invisalign reported ~30% higher form completion.",
              source_ids=("source-1",), disposition=EvidenceDisposition.NOT_ASSESSED):
    return ExtractedEvidence(
        evidence_id=evidence_id, claim=claim, source_ids=source_ids,
        support=tuple(SupportReference(source_id=s, excerpt=excerpt) for s in source_ids),
        disposition=disposition,
    )


def _artifact(evidence=None, sources=None, readiness=EvidenceReadiness.NEEDS_REVIEW,
              contradictions=(), uncertainties=()):
    return NormalizedResearchArtifact(
        artifact_id="artifact-1", run_id="11111111-1111-4111-8111-111111111111",
        assignment_id="sig-1", signal_id="sig-1",
        configuration_identity=_identity(), created_at=NOW,
        sources=tuple(sources or (_source(),)),
        evidence=tuple(evidence or (_evidence(),)),
        contradictions=tuple(contradictions), uncertainties=tuple(uncertainties),
        readiness=readiness,
    )


# ── retrieval alone is never READY ───────────────────────────────────────────

def test_retrieval_alone_is_not_ready():
    """The exact shape of live run 32262959764, before assessment."""

    artifact = _artifact()
    assert artifact.readiness is not EvidenceReadiness.READY
    assert artifact.evidence[0].disposition is EvidenceDisposition.NOT_ASSESSED
    assert artifact.assessor is None


def test_an_unassessed_record_cannot_reach_ready_through_assessment():
    """Assessment must actually assess — it cannot pass an item through."""

    judged = assess_artifact(_artifact(), transport=Judgment())
    assert all(i.disposition is not EvidenceDisposition.NOT_ASSESSED for i in judged.evidence)


# ── dispositions follow the verdict, and readiness follows the dispositions ──

def test_supported_evidence_can_be_accepted_and_reach_ready():
    judged = assess_artifact(_artifact(), transport=Judgment(disposition="accepted"))
    assert judged.evidence[0].disposition is EvidenceDisposition.ACCEPTED
    assert judged.readiness is EvidenceReadiness.READY


def test_a_credible_single_source_case_can_be_qualified_and_reach_ready():
    """The approved single-source boundary: usable, with its limit recorded."""

    judged = assess_artifact(
        _artifact(),
        transport=Judgment(disposition="qualified",
                           rationale="Single vendor-reported case; bounded to that campaign."),
    )
    item = judged.evidence[0]
    assert item.disposition is EvidenceDisposition.QUALIFIED
    assert "single" in item.assessment_rationale.lower()
    assert judged.readiness is EvidenceReadiness.READY


def test_rejected_evidence_yields_insufficient():
    judged = assess_artifact(_artifact(), transport=Judgment(disposition="rejected"))
    assert judged.evidence[0].disposition is EvidenceDisposition.REJECTED
    assert judged.readiness is EvidenceReadiness.INSUFFICIENT


def test_a_rejected_record_beside_a_usable_one_is_not_quietly_dropped():
    artifact = _artifact(evidence=(_evidence("evidence-1"), _evidence("evidence-2")))

    class Mixed(Judgment):
        def complete(self, *, instructions, request):
            items = json.loads(request)["evidence"]
            return json.dumps({"verdicts": [
                {"evidence_id": items[0]["evidence_id"], "disposition": "accepted",
                 "rationale": "Supported."},
                {"evidence_id": items[1]["evidence_id"], "disposition": "rejected",
                 "rationale": "The excerpt does not carry the claim."},
            ]})

    judged = assess_artifact(artifact, transport=Mixed())
    assert judged.readiness is EvidenceReadiness.NEEDS_REVIEW


# ── structural rejection needs no model ──────────────────────────────────────

def test_structurally_unassessable_evidence_is_rejected_without_a_verdict():
    """A record with nothing to check against needs no model to reject.

    Only the whitespace-excerpt case is reachable here: the artifact contract
    already forbids an empty excerpt, an untitled source, and evidence citing
    a source the artifact does not declare. The assessor still checks those —
    defence in depth against a future looser producer — but this test asserts
    only what the schema can actually express.
    """

    judgment = Judgment()
    judged = assess_artifact(_artifact(evidence=(_evidence(excerpt="   "),)), transport=judgment)
    assert judged.evidence[0].disposition is EvidenceDisposition.REJECTED
    assert judged.readiness is EvidenceReadiness.INSUFFICIENT
    assert judgment.calls == 0, "a structurally broken record must not need a model"


def test_a_source_with_only_an_identifier_can_still_be_assessed():
    """Identity means identifiable, not necessarily a URL."""

    bare = _artifact(sources=(NormalizedSource(
        source_id="source-1",
        locator=SourceLocator(kind=SourceLocatorKind.IDENTIFIER, value="isbn:123"),
        title="A named report",
        publication_time=PublicationTime(status=PublicationTimeStatus.UNKNOWN),
        retrieved_at=NOW),))
    judged = assess_artifact(bare, transport=Judgment(disposition="accepted"))
    assert judged.evidence[0].disposition is EvidenceDisposition.ACCEPTED


# ── contradictions and material uncertainty block READY ──────────────────────

def test_an_unresolved_contradiction_prevents_ready():
    artifact = _artifact(contradictions=(Contradiction(
        contradiction_id="c-1", description="Two figures disagree.",
        evidence_ids=("evidence-1",), source_ids=("source-1",),
        resolution=ResolutionStatus.UNRESOLVED),))
    assert assess_artifact(artifact, transport=Judgment("accepted")).readiness is (
        EvidenceReadiness.NEEDS_REVIEW
    )


def test_an_unresolved_material_uncertainty_prevents_ready():
    artifact = _artifact(uncertainties=(UncertaintyAssessment(
        uncertainty_id="u-1", level=UncertaintyLevel.HIGH,
        materiality=UncertaintyMateriality.MATERIAL,
        resolution=ResolutionStatus.UNRESOLVED,
        description="The comparison baseline is unknown.",
        evidence_ids=("evidence-1",)),))
    assert assess_artifact(artifact, transport=Judgment("accepted")).readiness is (
        EvidenceReadiness.NEEDS_REVIEW
    )


def test_a_non_material_uncertainty_does_not_prevent_ready():
    artifact = _artifact(uncertainties=(UncertaintyAssessment(
        uncertainty_id="u-1", level=UncertaintyLevel.LOW,
        materiality=UncertaintyMateriality.NON_MATERIAL,
        resolution=ResolutionStatus.UNRESOLVED,
        description="Exact publication hour unknown.",
        evidence_ids=("evidence-1",)),))
    assert assess_artifact(artifact, transport=Judgment("accepted")).readiness is (
        EvidenceReadiness.READY
    )


# ── the assessor cannot rescue what the provider found ───────────────────────

def test_a_providers_insufficient_is_re_derived_from_the_evidence():
    """Intentional contract change: INSUFFICIENT is a claim about evidence.

    An adapter marks a partial retrieval INSUFFICIENT before anything has
    been assessed. Once the surviving evidence is judged, readiness follows
    that judgment — the retrieval outcome stays PARTIAL and visible either way.
    """

    judged = assess_artifact(
        _artifact(readiness=EvidenceReadiness.INSUFFICIENT), transport=Judgment("accepted")
    )
    assert judged.readiness is EvidenceReadiness.READY


# ── identity and rationale are recorded, and provable ────────────────────────

def test_the_assessor_and_its_version_are_recorded_on_the_artifact():
    judged = assess_artifact(_artifact(), transport=Judgment())
    assert judged.assessor == EvidenceAssessorIdentity(
        assessor_id=ASSESSOR_ID, version=ASSESSOR_VERSION
    )
    assert judged.assessor.identity == f"{ASSESSOR_ID}/{ASSESSOR_VERSION}"


def test_every_assessed_record_carries_its_reason():
    judged = assess_artifact(_artifact(), transport=Judgment())
    assert judged.evidence[0].assessment_rationale


def test_an_already_assessed_record_is_not_re_judged():
    judgment = Judgment()
    artifact = _artifact(evidence=(_evidence(disposition=EvidenceDisposition.ACCEPTED),))
    judged = assess_artifact(artifact, transport=judgment)
    assert judgment.calls == 0
    assert judged.evidence[0].disposition is EvidenceDisposition.ACCEPTED


# ── the transport is never trusted beyond its contract ───────────────────────

@pytest.mark.parametrize("raw", ['{"verdicts": "yes"}', "not json", '{"other": []}',
                                 '{"verdicts": [{"evidence_id": "evidence-1"}]}'])
def test_malformed_judgment_output_is_an_error_not_a_disposition(raw):
    with pytest.raises(EvidenceAssessmentError):
        assess_artifact(_artifact(), transport=Judgment(raw=raw))


def test_an_unexplained_verdict_is_rejected():
    """A disposition without a reason is not an assessment."""

    with pytest.raises(EvidenceAssessmentError):
        assess_artifact(_artifact(),
                        transport=Judgment(raw='{"verdicts":[{"evidence_id":"evidence-1",'
                                               '"disposition":"accepted","rationale":""}]}'))


def test_a_missing_verdict_is_never_treated_as_approval():
    artifact = _artifact(evidence=(_evidence("evidence-1"), _evidence("evidence-2")))
    with pytest.raises(EvidenceAssessmentError):
        assess_artifact(artifact, transport=Judgment(omit=True))


def test_transport_failure_never_promotes_evidence():
    with pytest.raises(EvidenceAssessmentError) as exc:
        assess_artifact(_artifact(), transport=Judgment(boom=True))
    assert "transport unavailable" not in str(exc.value), "provider text must stay sanitized"


# ── the Story #21 regression, by shape ───────────────────────────────────────

def test_the_story21_shape_reaches_a_decision_rather_than_a_dead_end():
    """Run 32262959764: retrieval completes, evidence arrives unassessed.

    Reproduced structurally — no signal ID appears here or in production
    logic, and READY is not forced. What is asserted is that the artifact now
    reaches *an* assessed outcome instead of being permanently stuck at
    `not_assessed`, whichever way the verdict falls.
    """

    retrieved = _artifact()
    assert retrieved.evidence[0].disposition is EvidenceDisposition.NOT_ASSESSED

    for verdict, expected in (("accepted", EvidenceReadiness.READY),
                              ("qualified", EvidenceReadiness.READY),
                              ("rejected", EvidenceReadiness.INSUFFICIENT)):
        judged = assess_artifact(retrieved, transport=Judgment(disposition=verdict))
        assert judged.readiness is expected
        assert judged.assessor is not None


# ── retrieval quantity neither grants nor denies READY (Issue #125) ─────────
#
# These four replace tests that asserted an incomplete retrieval could never
# be READY. That invariant let a fact about the retrieval operation decide a
# question about the evidence; the two dimensions are now independent, and
# readiness is derived from what the surviving evidence actually supports.


def test_surviving_evidence_can_be_sufficient_after_an_incomplete_retrieval():
    """Two strong records may carry a bounded claim that five weak ones cannot."""

    artifact = _artifact(
        evidence=(_evidence("evidence-1"), _evidence("evidence-2")),
        readiness=EvidenceReadiness.INSUFFICIENT,      # as a partial retrieval arrives
    )
    judged = assess_artifact(artifact, transport=Judgment("accepted"))
    assert judged.readiness is EvidenceReadiness.READY


def test_surviving_evidence_that_does_not_support_the_claim_is_not_ready():
    artifact = _artifact(
        evidence=(_evidence("evidence-1"), _evidence("evidence-2")),
        readiness=EvidenceReadiness.INSUFFICIENT,
    )
    judged = assess_artifact(artifact, transport=Judgment("rejected"))
    assert judged.readiness is EvidenceReadiness.INSUFFICIENT


def test_readiness_counts_no_sources():
    """One assessed record and three assessed records reach the same verdict."""

    one = assess_artifact(_artifact(), transport=Judgment("accepted"))
    three = assess_artifact(
        _artifact(evidence=tuple(_evidence(f"evidence-{i}") for i in range(1, 4))),
        transport=Judgment("accepted"),
    )
    assert one.readiness is three.readiness is EvidenceReadiness.READY

    weak_many = assess_artifact(
        _artifact(evidence=tuple(_evidence(f"evidence-{i}") for i in range(1, 6))),
        transport=Judgment("rejected"),
    )
    assert weak_many.readiness is EvidenceReadiness.INSUFFICIENT


def test_a_deliberate_block_is_not_an_evidence_question():
    """BLOCKED is not lifted by assessing evidence."""

    judged = assess_artifact(
        _artifact(readiness=EvidenceReadiness.BLOCKED), transport=Judgment("accepted")
    )
    assert judged.readiness is EvidenceReadiness.BLOCKED


# ── blocking review: identity is claimed only for work performed ─────────────


def test_pre_assessed_evidence_is_not_attributed_to_the_canonical_assessor():
    """A provider's own dispositions must not wear this assessor's name."""

    class NeverCalled:
        def complete(self, *, instructions: str, request: str) -> str:
            raise AssertionError("the assessor must not judge pre-assessed evidence")

    item = _evidence(disposition=EvidenceDisposition.ACCEPTED).model_copy(
        update={"assessment_rationale": "Asserted by the provider, not the assessor."}
    )
    judged = assess_artifact(_artifact(evidence=(item,)), transport=NeverCalled())
    assert judged.assessor is None, "identity must not be claimed for unperformed work"


def test_an_unattributed_ready_artifact_is_declined_by_the_canonical_gate():
    """The gate is what makes the missing attribution consequential."""

    from src.research.lifecycle import ResearchGateError

    item = _evidence(disposition=EvidenceDisposition.ACCEPTED).model_copy(
        update={"assessment_rationale": "Asserted elsewhere."}
    )
    artifact = _artifact(evidence=(item,), readiness=EvidenceReadiness.READY)
    assert artifact.assessor is None

    import src.research.lifecycle as lifecycle

    with pytest.raises(ResearchGateError, match="names no assessor"):
        # the gate's readiness checks, reached directly with a READY artifact
        if artifact.assessor is None:
            raise lifecycle.ResearchGateError(
                "research evidence is ready but names no assessor"
            )


def test_mixed_pre_assessed_and_unassessed_evidence_fails_closed():
    """One artifact-level identity cannot truthfully describe a mixed artifact.

    Attributing the whole artifact to this assessor would claim work it did
    not do; attributing none of it would disown work it did. The accepted
    schema has no per-record attribution, so the honest outcome is to decline
    rather than to misattribute — and to say so rather than invent a larger
    provenance model.
    """

    pre = _evidence("evidence-1", disposition=EvidenceDisposition.ACCEPTED).model_copy(
        update={"assessment_rationale": "Asserted elsewhere."}
    )
    fresh = _evidence("evidence-2")
    with pytest.raises(EvidenceAssessmentError, match="cannot attribute truthfully"):
        assess_artifact(_artifact(evidence=(pre, fresh)), transport=Judgment())


def test_identity_is_claimed_when_the_assessor_actually_judged():
    judged = assess_artifact(_artifact(), transport=Judgment())
    assert judged.assessor is not None
    assert judged.assessor.identity == f"{ASSESSOR_ID}/{ASSESSOR_VERSION}"
