"""Issue #89 / Story #13: explicit editorial acceptance and one controlled revision.

All scenarios use injected fake reviewer/revision transports through the real
canonical production path (`scripts/generate_and_publish.main`) or the real
acceptance boundary functions. No live LLM calls, no parallel test-only
orchestration.
"""

from __future__ import annotations

import json
import sys
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial.editorial_acceptance import (
    EditorialAcceptanceError,
    EditorialAcceptanceRubric,
    EditorialDisposition,
    EditorialReview,
    run_editorial_acceptance,
)
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import (
    _entry_patches,
    _evaluator,
    _model_output,
)
from tests.test_research_artifact_lifecycle import ReadyProvider


RUBRIC = EditorialAcceptanceRubric.load()


def _review_payload(
    *,
    disposition: str = "accept",
    failed: list[str] | None = None,
    guidance: str = "",
) -> dict:
    return {
        "disposition": disposition,
        "failed_criterion_ids": failed or [],
        "rationale": "Deterministic test verdict.",
        "revision_guidance": guidance,
    }


class FakeReviewTransport:
    """Returns scripted payloads in sequence; records every request."""

    def __init__(self, *payloads: object) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls.append({"instructions": instructions, "request": request})
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return payload
        return json.dumps(payload)


class FakeRevisionTransport:
    def __init__(self, payload: object = "Revised article body with fixes applied.") -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls.append({"instructions": instructions, "request": request})
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _run_entry(tmp_path, *, reviewer, revisor=None, dry_run=True):
    """Drive the real canonical entrypoint with real acceptance boundary code."""

    argv, patches = _entry_patches(tmp_path, dry_run=dry_run)
    del patches["run_editorial_acceptance"]  # exercise the real gate
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(
            research_provider=ReadyProvider(),
            decision_evaluator=evaluator,
            editorial_reviewer=reviewer,
            article_revisor=revisor or FakeRevisionTransport(),
        )
    return code, patches


def _generated(tmp_path) -> dict:
    return json.loads(next(tmp_path.glob("*/runs/*/generated.json")).read_text())


def _audit(tmp_path) -> dict:
    """The run-scoped editorial acceptance audit record (single source of truth)."""

    records = list(tmp_path.glob("*/runs/*/editorial_acceptance.json"))
    assert len(records) == 1
    data = json.loads(records[0].read_text())
    assert data["run_id"] == records[0].parent.name  # run identity preserved
    return data


def _assert_no_publication_effects(tmp_path, patches):
    """Zero packaging/publication effects — the audit artifact is NOT one of them."""

    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    assert not list(tmp_path.glob("*/runs/*/generated.json"))
    assert not list(tmp_path.glob("*/runs/*/publication_results.json"))


# ===========================================================================
# 1–2. ACCEPT paths through the real entrypoint
# ===========================================================================


def test_strong_article_is_accepted_and_continues(tmp_path):
    reviewer = FakeReviewTransport(_review_payload())
    revisor = FakeRevisionTransport()
    code, patches = _run_entry(tmp_path, reviewer=reviewer, revisor=revisor)
    assert code == 0
    assert len(reviewer.calls) == 1
    assert revisor.calls == []  # no revision for an accepted article
    record = _audit(tmp_path)
    assert record["rubric"] == RUBRIC.identity
    assert record["accepted"] is True
    assert record["revised"] is False
    assert record["final_disposition"] == "accept"
    assert record["initial_review"]["disposition"] == "accept"
    assert record["final_review"] is None
    # accepted path still produces the publishable package, with the audit in
    # exactly one place (no duplicate source of truth inside generated.json)
    assert "editorial_acceptance" not in _generated(tmp_path)


def test_weak_article_revised_once_then_accepted_continues(tmp_path):
    reviewer = FakeReviewTransport(
        _review_payload(
            disposition="revise",
            failed=["generic-filler", "insight"],
            guidance="Cut the filler; sharpen the one real insight.",
        ),
        _review_payload(),
    )
    revisor = FakeRevisionTransport("Sharpened revised article body.")
    code, patches = _run_entry(tmp_path, reviewer=reviewer, revisor=revisor)
    assert code == 0
    assert len(reviewer.calls) == 2
    assert len(revisor.calls) == 1  # exactly one revision
    # the revisor received the failed criteria and guidance
    revision_request = json.loads(revisor.calls[0]["request"])
    failed_ids = {c["criterion_id"] for c in revision_request["failed_criteria"]}
    assert failed_ids == {"generic-filler", "insight"}
    assert revision_request["revision_guidance"].startswith("Cut the filler")
    # the revised article continued into the generated package
    generated = _generated(tmp_path)
    assert "Sharpened revised article body." in generated["blog_article"]
    record = _audit(tmp_path)
    assert record["revised"] is True
    assert record["accepted"] is True
    assert record["final_disposition"] == "accept"
    assert record["initial_review"]["disposition"] == "revise"
    assert record["final_review"]["disposition"] == "accept"


# ===========================================================================
# 3–5. Stops: second REVISE, REJECT after revision, initial REJECT
# ===========================================================================


def test_revision_that_still_fails_review_stops(tmp_path):
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["voice"]),
        _review_payload(disposition="revise", failed=["voice", "generic-filler"]),
    )
    revisor = FakeRevisionTransport()
    code, patches = _run_entry(tmp_path, reviewer=reviewer, revisor=revisor, dry_run=False)
    assert code == 1
    assert len(revisor.calls) == 1  # never a second automatic revision
    _assert_no_publication_effects(tmp_path, patches)
    # both reviews survive persistence even though the run was blocked
    record = _audit(tmp_path)
    assert record["accepted"] is False
    assert record["revised"] is True
    assert record["final_disposition"] == "revise"
    assert record["initial_review"]["failed_criterion_ids"] == ["voice"]
    assert record["final_review"]["failed_criterion_ids"] == ["voice", "generic-filler"]


def test_rejection_after_revision_stops(tmp_path):
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["insight"]),
        _review_payload(disposition="reject", failed=["insight", "reader-value"]),
    )
    revisor = FakeRevisionTransport()
    code, patches = _run_entry(tmp_path, reviewer=reviewer, revisor=revisor, dry_run=False)
    assert code == 1
    assert len(revisor.calls) == 1  # exactly one revision before the rejection
    _assert_no_publication_effects(tmp_path, patches)
    # the full editorial history of the blocked run is preserved
    record = _audit(tmp_path)
    assert record["accepted"] is False
    assert record["revised"] is True
    assert record["final_disposition"] == "reject"
    assert record["initial_review"]["disposition"] == "revise"
    assert record["final_review"]["disposition"] == "reject"
    assert record["final_review"]["failed_criterion_ids"] == ["insight", "reader-value"]


def test_initial_reject_stops_with_zero_revision_calls(tmp_path):
    reviewer = FakeReviewTransport(
        _review_payload(disposition="reject", failed=["reader-value"])
    )
    revisor = FakeRevisionTransport()
    code, patches = _run_entry(tmp_path, reviewer=reviewer, revisor=revisor, dry_run=False)
    assert code == 1
    assert revisor.calls == []  # REJECT never triggers automatic revision
    _assert_no_publication_effects(tmp_path, patches)
    record = _audit(tmp_path)
    assert record["accepted"] is False
    assert record["revised"] is False
    assert record["final_disposition"] == "reject"
    assert record["final_review"] is None


# ===========================================================================
# 6–7. Rubric enforcement: unsupported claims and generic filler
# ===========================================================================


def test_unsupported_claim_cannot_produce_publishable_acceptance(tmp_path):
    # a reviewer that tries to ACCEPT while naming an unsupported-claims
    # failure violates the acceptance invariant — fail closed, no publication
    reviewer = FakeReviewTransport(
        {
            "disposition": "accept",
            "failed_criterion_ids": ["unsupported-claims"],
            "rationale": "Good enough despite the invented statistic.",
            "revision_guidance": "",
        }
    )
    code, patches = _run_entry(tmp_path, reviewer=reviewer, dry_run=False)
    assert code == 1
    _assert_no_publication_effects(tmp_path, patches)


def test_generic_filler_failure_requires_revision_or_rejection(tmp_path):
    reviewer = FakeReviewTransport(
        _review_payload(
            disposition="revise",
            failed=["generic-filler"],
            guidance="Remove the AI-sounding transitions.",
        ),
        _review_payload(),
    )
    revisor = FakeRevisionTransport()
    code, _ = _run_entry(tmp_path, reviewer=reviewer, revisor=revisor)
    assert code == 0
    assert len(revisor.calls) == 1
    request = json.loads(revisor.calls[0]["request"])
    assert request["failed_criteria"][0]["criterion_id"] == "generic-filler"


# ===========================================================================
# 8–10. Fail-closed reviewer/revision failures
# ===========================================================================


@pytest.mark.parametrize(
    "payload",
    [
        "this is not json {",
        '["a", "list"]',
        {"disposition": "accept", "failed_criterion_ids": [],
         "rationale": "ok", "revision_guidance": "", "raw_notes": {"x": 1}},
        {"disposition": "revise", "failed_criterion_ids": ["not-a-rubric-criterion"],
         "rationale": "bad id", "revision_guidance": ""},
        {"disposition": "revise", "failed_criterion_ids": [],
         "rationale": "revise with no criteria", "revision_guidance": ""},
    ],
    ids=["non-json", "non-object", "unknown-field", "unknown-criterion",
         "revise-without-criteria"],
)
def test_malformed_reviewer_output_stops(tmp_path, payload):
    reviewer = FakeReviewTransport(payload)
    code, patches = _run_entry(tmp_path, reviewer=reviewer, dry_run=False)
    assert code == 1
    _assert_no_publication_effects(tmp_path, patches)


def test_reviewer_transport_failure_stops(tmp_path):
    reviewer = FakeReviewTransport(RuntimeError("reviewer provider down"))
    code, patches = _run_entry(tmp_path, reviewer=reviewer, dry_run=False)
    assert code == 1
    _assert_no_publication_effects(tmp_path, patches)


@pytest.mark.parametrize(
    "revision_payload", [RuntimeError("revision provider down"), "", "   "],
    ids=["transport-error", "empty-article", "blank-article"],
)
def test_revision_failure_stops_without_silently_accepting_original(
    tmp_path, revision_payload
):
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["voice"]),
        _review_payload(),  # would accept — must never be reached
    )
    revisor = FakeRevisionTransport(revision_payload)
    code, patches = _run_entry(tmp_path, reviewer=reviewer, revisor=revisor, dry_run=False)
    assert code == 1
    assert len(reviewer.calls) == 1  # recheck never ran after failed revision
    _assert_no_publication_effects(tmp_path, patches)


# ===========================================================================
# 11–12. Single revision maximum; audit preserved (boundary-level)
# ===========================================================================


def _boundary_kwargs():
    from src.research.evidence import NormalizedResearchArtifact
    from tests.test_decision_lens_evaluator import _research_payload

    research = NormalizedResearchArtifact.model_validate(_research_payload())
    return dict(
        article_body="Original article body.",
        research=research,
        run_id="12345678-1234-4234-8234-123456789abc",
        rubric=RUBRIC,
    )


def test_exactly_one_revision_even_for_repeated_revise_verdicts():
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["insight"]),
        _review_payload(disposition="revise", failed=["insight"]),
    )
    revisor = FakeRevisionTransport()
    outcome = run_editorial_acceptance(
        reviewer=reviewer, revisor=revisor, **_boundary_kwargs()
    )
    assert outcome.accepted is False
    assert len(revisor.calls) == 1
    assert len(reviewer.calls) == 2


def test_initial_and_final_reviews_are_preserved():
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["voice"], guidance="Fix voice."),
        _review_payload(),
    )
    outcome = run_editorial_acceptance(
        reviewer=reviewer, revisor=FakeRevisionTransport(), **_boundary_kwargs()
    )
    assert outcome.accepted is True and outcome.revised is True
    assert outcome.initial_review.disposition is EditorialDisposition.REVISE
    assert outcome.initial_review.failed_criterion_ids == ("voice",)
    assert outcome.final_review is not None
    assert outcome.final_review.disposition is EditorialDisposition.ACCEPT
    assert outcome.audit["initial_review"]["disposition"] == "revise"
    assert outcome.audit["final_review"]["disposition"] == "accept"
    assert outcome.audit["rubric"] == RUBRIC.identity


# ===========================================================================
# 13–15. Publication side effects, channel discipline, metadata
# ===========================================================================


def test_blocked_article_produces_zero_wix_and_linkedin_effects(tmp_path):
    reviewer = FakeReviewTransport(
        _review_payload(disposition="reject", failed=["reader-value"])
    )
    code, patches = _run_entry(tmp_path, reviewer=reviewer, dry_run=False)
    assert code == 1
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not list(tmp_path.glob("*/runs/*/publication_results.json"))


def test_revision_regenerates_no_other_channels(tmp_path):
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["insight"]),
        _review_payload(),
    )
    revisor = FakeRevisionTransport("Channel-discipline revised body.")
    code, patches = _run_entry(tmp_path, reviewer=reviewer, revisor=revisor)
    assert code == 0
    # article generation (all channel composition) ran exactly once — the
    # revision boundary touched only the Wix article body
    assert patches["generate_article"].call_count == 1
    generated = _generated(tmp_path)
    assert "Channel-discipline revised body." in generated["blog_article"]
    # other channels keep their originally generated bodies
    assert generated["linkedin_post"].startswith("LinkedIn post text.")
    assert generated["facebook_post"].startswith("Facebook post text.")
    assert generated["instagram_caption"].startswith("Instagram caption text.")
    # the revision request contained only the one article
    request = json.loads(revisor.calls[0]["request"])
    assert "article" in request and "platforms" not in request


def test_accepted_article_preserves_run_id_and_wix_metadata(tmp_path):
    reviewer = FakeReviewTransport(_review_payload())
    code, _ = _run_entry(tmp_path, reviewer=reviewer)
    assert code == 0
    path = next(tmp_path.glob("*/runs/*/generated.json"))
    generated = json.loads(path.read_text())
    assert generated["run_id"] == path.parent.name  # exact current run_id
    for field in ("signal_id", "headline", "strategy_id", "strategy_version",
                  "configuration_identity", "blog_article"):
        assert generated.get(field), field


# ===========================================================================
# Rubric artifact and review contract
# ===========================================================================


def test_rubric_loads_with_stable_identity_and_required_criteria():
    assert RUBRIC.identity == "never-blank-editorial-acceptance/1.0"
    required = {
        "evidence-use", "defensible-angle", "audience-recognition", "insight",
        "narrative-coherence", "voice", "unsupported-claims", "generic-filler",
        "reader-value",
    }
    assert required <= set(RUBRIC.criterion_ids)


def test_review_contract_rejects_inconsistent_verdicts():
    with pytest.raises(Exception):
        EditorialReview(
            rubric_id=RUBRIC.rubric_id, rubric_version=RUBRIC.version,
            disposition=EditorialDisposition.ACCEPT,
            failed_criterion_ids=("voice",), rationale="inconsistent",
        )
    with pytest.raises(Exception):
        EditorialReview(
            rubric_id=RUBRIC.rubric_id, rubric_version=RUBRIC.version,
            disposition=EditorialDisposition.REVISE,
            failed_criterion_ids=(), rationale="inconsistent",
        )


def test_reviewer_receives_rubric_and_accepted_evidence():
    reviewer = FakeReviewTransport(_review_payload())
    run_editorial_acceptance(
        reviewer=reviewer, revisor=FakeRevisionTransport(), **_boundary_kwargs()
    )
    request = json.loads(reviewer.calls[0]["request"])
    assert request["rubric"]["rubric_id"] == RUBRIC.rubric_id
    assert {c["criterion_id"] for c in request["rubric"]["criteria"]} == set(
        RUBRIC.criterion_ids
    )
    assert request["accepted_evidence"][0]["evidence_id"] == "evidence-smb"
    assert "never invent support" in request["note"]
