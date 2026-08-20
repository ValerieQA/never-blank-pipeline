"""Issue #131: the run's claim boundary must reach writing and rewriting.

The live-run failure shape these scenarios reproduce: a `PROCEED` in bounded
external-case mode, with restrictions recorded, produced an article asserting
audience-level facts no evidence supported — because neither the restrictions
nor the supported facts existed anywhere in the generation or revision path.

Everything here is deterministic: fake transports, fake stage chats, no live
providers. The tests prove what deterministic tests honestly can — that the
authoritative boundary is present at every point where prose is written or
rewritten, and that the acceptance gate still stops an article that ignores it.
They do not claim to prove a model obeys it.
"""

from __future__ import annotations

import json
import sys
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial.claim_boundary import (
    ClaimBoundary,
    build_claim_boundary,
    claim_boundary_text,
    render_claim_boundary,
)
from src.editorial.decision_contract import (
    DecisionLensDecisionArtifact,
    EditorialClaimMode,
)
from src.editorial.editorial_acceptance import (
    EditorialAcceptanceRubric,
    run_editorial_acceptance,
)
from src.editorial.discovery_builder import build_discovery
from src.editorial.narrative_spine import build_narrative_spine
from src.editorial.never_blank_voice import finalize_article
from src.editorial.story_assembly import assemble_story
from src.research.evidence import NormalizedResearchArtifact
from tests import test_decision_lens_evaluator as evaluator_fixtures
from tests import test_editorial_acceptance as acceptance_fixtures
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_research_artifact_lifecycle import ReadyProvider


RUBRIC = EditorialAcceptanceRubric.load()

# One recognizable restriction and one recognizable supported figure, so a
# prompt assertion cannot pass by accident on generic wording.
RESTRICTION = "This does not establish the same outcome for the configured audience."
EXACT_FIGURE = "Independent service firms report capacity as a material decision constraint."


def _bounded_decision() -> DecisionLensDecisionArtifact:
    """A real bounded PROCEED, built through the production evaluator path."""

    payload = evaluator_fixtures._bounded_model_output()  # noqa: SLF001
    payload["restrictions"] = [RESTRICTION]
    evaluator, _ = evaluator_fixtures._evaluator(payload)  # noqa: SLF001
    result = evaluator_fixtures._evaluate(evaluator)  # noqa: SLF001
    assert result.decision is not None
    return result.decision


def _direct_decision() -> DecisionLensDecisionArtifact:
    evaluator, _ = evaluator_fixtures._evaluator(  # noqa: SLF001
        evaluator_fixtures._model_output()  # noqa: SLF001
    )
    result = evaluator_fixtures._evaluate(evaluator)  # noqa: SLF001
    assert result.decision is not None
    return result.decision


def _research() -> NormalizedResearchArtifact:
    return evaluator_fixtures._research()  # noqa: SLF001


# ===========================================================================
# Derivation — the boundary is built from artifacts, never from vocabulary
# ===========================================================================


def test_bounded_boundary_carries_mode_restrictions_and_cited_facts():
    boundary = build_claim_boundary(_bounded_decision(), _research())

    assert boundary.claim_mode is EditorialClaimMode.BOUNDED_EXTERNAL_CASE
    assert boundary.restrictions == (RESTRICTION,)
    assert [fact.evidence_id for fact in boundary.supported_facts] == ["evidence-smb"]
    fact = boundary.supported_facts[0]
    assert fact.claim == EXACT_FIGURE
    assert fact.source_ids == ("source-sba",)
    assert fact.excerpts  # the support excerpt travels with the claim


def test_only_evidence_the_decision_cited_is_offered_as_supported_fact():
    decision = _bounded_decision()
    research = _research()
    extra = json.loads(research.model_dump_json())
    extra["evidence"].append({
        "evidence_id": "evidence-uncited",
        "claim": "An unrelated measured claim the decision never weighed.",
        "source_ids": ["source-sba"],
        "support": [{
            "source_id": "source-sba",
            "excerpt": "A separate figure appears elsewhere in the same report.",
            "location": "table 9",
        }],
        "disposition": "accepted",
    })

    boundary = build_claim_boundary(
        decision, NormalizedResearchArtifact.model_validate(extra)
    )

    # present in the run, never weighed by the decision — so not support
    assert [fact.evidence_id for fact in boundary.supported_facts] == ["evidence-smb"]


def test_blank_restrictions_are_dropped_rather_than_rendered_as_empty_rules():
    decision = _bounded_decision()
    hollow = decision.model_copy(
        update={
            "judgment": decision.judgment.model_copy(
                update={"restrictions": (RESTRICTION, "   ", "")}
            )
        }
    )

    boundary = build_claim_boundary(hollow, _research())

    assert boundary.restrictions == (RESTRICTION,)


def test_bounded_rules_forbid_transferring_the_outcome_direct_rules_do_not():
    bounded = build_claim_boundary(_bounded_decision(), _research()).rules
    direct = build_claim_boundary(_direct_decision(), _research()).rules

    assert any("observed elsewhere" in rule for rule in bounded)
    assert any("question, observation, hypothesis" in rule for rule in bounded)
    assert not any("observed elsewhere" in rule for rule in direct)
    # the evidence-boundary rules are universal — direct mode never licensed
    # inventing facts either
    for rule in (
        "Every factual assertion must trace to one of the supported facts below.",
    ):
        assert rule in bounded and rule in direct


@pytest.mark.parametrize(
    "mode", [EditorialClaimMode.BOUNDED_EXTERNAL_CASE, EditorialClaimMode.DIRECT_AUDIENCE_CLAIM]
)
def test_the_boundary_authors_no_product_or_sector_vocabulary(mode):
    # rendered with no facts and no restrictions, so what remains is exactly
    # the text this module authors — the run's own data is the only place
    # product-specific words may appear
    authored = render_claim_boundary(
        ClaimBoundary(claim_mode=mode, restrictions=(), supported_facts=())
    )

    for word in ("never blank", "agency", "agencies", "founder", "smb", "small business"):
        assert word not in authored.lower()


def test_rendering_is_deterministic_and_identical_for_generation_and_revision():
    decision, research = _bounded_decision(), _research()

    first = claim_boundary_text(decision, research)
    second = claim_boundary_text(decision, research)

    assert first == second == render_claim_boundary(
        build_claim_boundary(decision, research)
    )
    assert RESTRICTION in first and EXACT_FIGURE in first


@pytest.mark.parametrize(
    "decision, research",
    [(None, None), (None, "research"), ("decision", None)],
)
def test_a_caller_without_both_artifacts_adds_nothing(decision, research):
    resolved_decision = _bounded_decision() if decision else None
    resolved_research = _research() if research else None

    # None, not an empty or half-built block: a legacy caller's prompt is
    # byte-identical to what it was before this change
    assert claim_boundary_text(resolved_decision, resolved_research) is None


# ===========================================================================
# E. The boundary reaches every stage that writes prose
# ===========================================================================


def _capture(module: str, response: dict):
    return mock.patch(f"src.editorial.{module}.chat", return_value=json.dumps(response))


_SPINE_OUT = {
    "core_pattern": "d", "narrative_spine": "spine", "target_feeling": "recognition",
    "pattern_as_evidence_of": "x",
}
_DISCOVERY_OUT = {
    "first_wrong_explanation": "a", "puzzle": "b",
    "investigation_sequence": ["c1", "c2", "c3"], "aha_setup": "d",
}
_STORY_OUT = {
    "surviving_explanation": "e", "reframe": "A system-design problem.",
    "remaining_uncertainty": None, "business_translation": "f",
}
_VOICE_OUT = {
    "echo_line": "Customers rarely decide to forget a business.",
    "cta_line": None, "checklist_pass": True, "checklist_notes": "",
    "echo_candidates": [],
}


def test_every_prose_stage_receives_the_restrictions_and_supported_facts():
    boundary = claim_boundary_text(_bounded_decision(), _research())
    lens = {"owner_system_objective": "o", "delivery_vs_presence_conflict": "c",
            "customer_memory_consequence": "m", "structural_cause": "s",
            "never_blank_insight": "i"}
    signal = {"HEADLINE": "h", "SIGNAL_ID": "s-1"}
    hook = {"selected_hook": "hook"}
    spine = {"narrative_spine": "spine"}

    calls = {}
    with _capture("narrative_spine", _SPINE_OUT) as spine_chat:
        build_narrative_spine(lens, signal, claim_boundary=boundary)
        calls["narrative_spine"] = spine_chat.call_args.kwargs["user"]
    with _capture("discovery_builder", _DISCOVERY_OUT) as discovery_chat:
        build_discovery(hook, spine, lens, signal, claim_boundary=boundary)
        calls["discovery_builder"] = discovery_chat.call_args.kwargs["user"]
    with _capture("story_assembly", _STORY_OUT) as story_chat:
        assemble_story(_DISCOVERY_OUT, spine, lens, signal, claim_boundary=boundary)
        calls["story_assembly"] = story_chat.call_args.kwargs["user"]
    with _capture("never_blank_voice", _VOICE_OUT) as voice_chat:
        finalize_article(
            hook, None, _DISCOVERY_OUT, _STORY_OUT, spine, lens, signal, "none",
            claim_boundary=boundary,
        )
        calls["never_blank_voice"] = voice_chat.call_args.kwargs["user"]

    assert set(calls) == {
        "narrative_spine", "discovery_builder", "story_assembly", "never_blank_voice"
    }
    for stage, prompt in calls.items():
        assert RESTRICTION in prompt, stage
        assert EXACT_FIGURE in prompt, stage
        assert "bounded_external_case" in prompt, stage


def test_a_stage_without_a_boundary_keeps_its_previous_prompt_exactly():
    lens = {"owner_system_objective": "o", "delivery_vs_presence_conflict": "c",
            "customer_memory_consequence": "m", "structural_cause": "s",
            "never_blank_insight": "i"}
    signal = {"HEADLINE": "h"}

    with _capture("narrative_spine", _SPINE_OUT) as chat:
        build_narrative_spine(lens, signal)
        without = chat.call_args.kwargs["user"]
    with _capture("narrative_spine", _SPINE_OUT) as chat:
        build_narrative_spine(lens, signal, claim_boundary=None)
        explicit_none = chat.call_args.kwargs["user"]

    assert without == explicit_none
    assert "CLAIM BOUNDARY" not in without


def test_the_entrypoint_hands_the_decision_artifact_to_generation(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())
    generated = patches["generate_article"]

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0

    passed = generated.call_args.kwargs["decision_artifact"]
    assert isinstance(passed, DecisionLensDecisionArtifact)
    # the persisted artifact, not a reconstruction
    persisted = json.loads(next(tmp_path.glob("*/runs/*/decision.json")).read_text())
    assert passed.decision_artifact_id == persisted["decision_artifact_id"]


# ===========================================================================
# A–D. Generation, acceptance and the single controlled revision
# ===========================================================================


def _boundary_for_acceptance() -> str:
    return claim_boundary_text(_bounded_decision(), _research())


BOUNDED_ARTICLE = (
    f"{EXACT_FIGURE} That was measured in the reported context and nowhere else. "
    "It raises a question for a reader in a different situation: what would you "
    "have to see to know the same constraint applies to you?"
)
INVENTED_ARTICLE = (
    "Owners in this market receive vague enquiries every week and their referrals "
    "arrive without context, which is why their sales calls turn into education."
)


def test_a_bounded_article_that_stays_inside_the_boundary_is_accepted():
    reviewer = acceptance_fixtures.FakeReviewTransport(
        acceptance_fixtures._review_payload()  # noqa: SLF001
    )
    revisor = acceptance_fixtures.FakeRevisionTransport()

    outcome = run_editorial_acceptance(
        article_body=BOUNDED_ARTICLE, research=_research(), run_id="run-1",
        rubric=RUBRIC, reviewer=reviewer, revisor=revisor,
        claim_boundary=_boundary_for_acceptance(),
    )

    assert outcome.accepted and not outcome.revised
    assert not revisor.calls  # an accepted article is never revised


def test_an_invented_audience_claim_is_stopped_and_never_reaches_packaging(tmp_path):
    reviewer = acceptance_fixtures.FakeReviewTransport(
        acceptance_fixtures._review_payload(  # noqa: SLF001
            disposition="revise",
            failed=["unsupported-claims", "evidence-use"],
            guidance="Remove claims about the audience that no evidence supports.",
        ),
        acceptance_fixtures._review_payload(  # noqa: SLF001
            disposition="revise",
            failed=["unsupported-claims"],
            guidance="Still asserts audience behaviour as fact.",
        ),
    )
    # the reviser trades one flagged claim for a different invented one
    revisor = acceptance_fixtures.FakeRevisionTransport(INVENTED_ARTICLE)

    outcome = run_editorial_acceptance(
        article_body=INVENTED_ARTICLE, research=_research(), run_id="run-1",
        rubric=RUBRIC, reviewer=reviewer, revisor=revisor,
        claim_boundary=_boundary_for_acceptance(),
    )

    # D: a revision that invents again does not become publishable — the
    # recheck is what stops it, and it is not weakened here
    assert not outcome.accepted
    assert outcome.revised
    assert outcome.final_review is not None
    assert len(revisor.calls) == 1  # exactly one controlled revision, no retry loop


def test_a_revision_that_narrows_the_claim_is_accepted_on_recheck():
    reviewer = acceptance_fixtures.FakeReviewTransport(
        acceptance_fixtures._review_payload(  # noqa: SLF001
            disposition="revise", failed=["unsupported-claims"],
            guidance="Narrow the audience statements to questions.",
        ),
        acceptance_fixtures._review_payload(),  # noqa: SLF001
    )
    revisor = acceptance_fixtures.FakeRevisionTransport(BOUNDED_ARTICLE)

    outcome = run_editorial_acceptance(
        article_body=INVENTED_ARTICLE, research=_research(), run_id="run-1",
        rubric=RUBRIC, reviewer=reviewer, revisor=revisor,
        claim_boundary=_boundary_for_acceptance(),
    )

    assert outcome.accepted and outcome.revised
    assert outcome.final_article_body == BOUNDED_ARTICLE
    assert EXACT_FIGURE in outcome.final_article_body  # core argument preserved


def test_the_controlled_revision_receives_the_boundary_not_only_reviewer_prose():
    reviewer = acceptance_fixtures.FakeReviewTransport(
        acceptance_fixtures._review_payload(  # noqa: SLF001
            disposition="revise", failed=["unsupported-claims"], guidance="Narrow it.",
        ),
        acceptance_fixtures._review_payload(),  # noqa: SLF001
    )
    revisor = acceptance_fixtures.FakeRevisionTransport(BOUNDED_ARTICLE)

    run_editorial_acceptance(
        article_body=INVENTED_ARTICLE, research=_research(), run_id="run-1",
        rubric=RUBRIC, reviewer=reviewer, revisor=revisor,
        claim_boundary=_boundary_for_acceptance(),
    )

    request = json.loads(revisor.calls[0]["request"])
    assert RESTRICTION in request["claim_boundary"]      # F: the restrictions
    assert EXACT_FIGURE in request["claim_boundary"]     # G: the exact wording
    assert "source-sba" in request["claim_boundary"]     # F: source attribution
    assert "bounded_external_case" in request["claim_boundary"]
    assert "authoritative" in request["note"]


def test_the_revision_prompt_is_unchanged_when_no_boundary_is_supplied():
    reviewer = acceptance_fixtures.FakeReviewTransport(
        acceptance_fixtures._review_payload(  # noqa: SLF001
            disposition="revise", failed=["unsupported-claims"], guidance="Narrow it.",
        ),
        acceptance_fixtures._review_payload(),  # noqa: SLF001
    )
    revisor = acceptance_fixtures.FakeRevisionTransport(BOUNDED_ARTICLE)

    run_editorial_acceptance(
        article_body=INVENTED_ARTICLE, research=_research(), run_id="run-1",
        rubric=RUBRIC, reviewer=reviewer, revisor=revisor,
    )

    request = json.loads(revisor.calls[0]["request"])
    assert "claim_boundary" not in request
    assert "authoritative" not in request["note"]


# ===========================================================================
# I. Editorial acceptance semantics are untouched
# ===========================================================================


def test_the_reviewer_request_is_not_changed_by_this_correction():
    reviewer = acceptance_fixtures.FakeReviewTransport(
        acceptance_fixtures._review_payload()  # noqa: SLF001
    )

    run_editorial_acceptance(
        article_body=BOUNDED_ARTICLE, research=_research(), run_id="run-1",
        rubric=RUBRIC, reviewer=reviewer,
        revisor=acceptance_fixtures.FakeRevisionTransport(),
        claim_boundary=_boundary_for_acceptance(),
    )

    request = json.loads(reviewer.calls[0]["request"])
    # the reviewer judges the article against the rubric and the accepted
    # evidence exactly as before — it is not told what the writer was told
    assert set(request) == {"run_id", "article", "rubric", "accepted_evidence", "note"}
    assert RUBRIC.identity == "never-blank-editorial-acceptance/1.0"


def test_boundary_models_are_immutable_and_reject_unknown_fields():
    boundary = build_claim_boundary(_bounded_decision(), _research())

    with pytest.raises(Exception):
        boundary.restrictions = ()
    with pytest.raises(Exception):
        ClaimBoundary(
            claim_mode=EditorialClaimMode.DIRECT_AUDIENCE_CLAIM,
            restrictions=(), supported_facts=(), smuggled="x",
        )
