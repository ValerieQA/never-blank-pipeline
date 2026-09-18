"""#254 D10: the reviser's temporary contract, proven end to end.

Owner decision (#253, temporary until Sveta and the owner finalize it): the
reviser receives the applicable editorial role, the configured voice, the draft,
and the reviewer's specific findings — and revision is surgical, not
regenerative.

Two layers, each proven where it lives:

* **The role and voice are data the entrypoint builds.** They are carried into
  the revision request by the canonical entrypoint for any non-Wednesday role.
  Wednesday is paused and keeps its own acceptance; a run with no role is
  unchanged.
* **"Surgical, not regenerative" is client policy a person edits.** It is
  CLIENT: NEVER_BLANK's revision lens, ``clients/never_blank/lenses/revision.md``
  (#240 D12), routed by the Engine to the revision stage and delivered verbatim
  in the reviser's request. The tests read that file rather than restating it.
  The acceptance rubric is unchanged.

No network, no model: every transport is a fake or has ``chat`` patched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import yaml

import scripts.generate_and_publish as gap
import src.utils.llm_client as llm_client
from scripts.generate_and_publish import main
from src.editorial.editorial_acceptance import (
    EditorialAcceptanceRubric,
    LlmChatArticleRevisionTransport,
    RevisionContext,
    run_editorial_acceptance,
)
from src.editorial.editorial_role import render_editorial_role_rules, resolve_editorial_role
from src.strategy.business_config import load_business_strategy_configuration
from tests import test_editorial_acceptance as acceptance_fixtures
from tests.test_decision_lifecycle import _evaluator, _model_output
from tests.test_monday_stream import (
    MONDAY_ROLE,
    _attributed_article,
    _entry_patches,
    _research_artifact,
)
from tests.test_research_artifact_lifecycle import ReadyProvider

RUBRIC_PATH = Path("config/prompts/editorial_acceptance/never_blank.yaml")
REVISED = (
    "A documented owner-led case. According to Verified report, the constraint "
    "is real. Sources: Verified report (https://source.example/report)."
)


def _configuration():
    return load_business_strategy_configuration(
        Path("strategy/current/business_strategy.json")
    )


def _revise_then_accept():
    return acceptance_fixtures.FakeReviewTransport(
        acceptance_fixtures._review_payload(  # noqa: SLF001
            disposition="revise", failed=["evidence-use"], guidance="Attribute it.",
        ),
        acceptance_fixtures._review_payload(),  # noqa: SLF001
    )


def _run_entrypoint(tmp_path, *, role: str | None):
    article = _attributed_article()
    article["platforms"]["long"]["body"] = "An unattributed first draft."
    article["platforms"]["medium"]["body"] = "Per Verified report, the constraint is real."
    argv, patches = _entry_patches(tmp_path)
    patches["generate_article"] = mock.MagicMock(return_value=article)
    if role is not None:
        argv = argv + ["--editorial-role", role]
    del patches["run_editorial_acceptance"]  # the real acceptance lifecycle
    evaluator, _ = _evaluator(_model_output())
    revisor = acceptance_fixtures.FakeRevisionTransport(REVISED)

    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        main(
            research_provider=ReadyProvider(), decision_evaluator=evaluator,
            editorial_reviewer=_revise_then_accept(), article_revisor=revisor,
        )
    assert revisor.calls, "the run never reached the reviser"
    return json.loads(revisor.calls[0]["request"]), revisor.calls[0]["instructions"]


# ── the entrypoint hands the reviser the role and the voice ─────────────────


def test_a_monday_revision_request_carries_the_role_for_the_article_surface(tmp_path):
    request, _ = _run_entrypoint(tmp_path, role=MONDAY_ROLE)

    role = resolve_editorial_role(_configuration(), MONDAY_ROLE)[1]
    assert request["editorial_role"] == render_editorial_role_rules(role, surface="wix")
    # the article surface's own rules, never the LinkedIn post's
    assert role.linkedin_rules[0] not in request["editorial_role"]


def test_a_monday_revision_request_carries_the_configured_voice(tmp_path):
    request, _ = _run_entrypoint(tmp_path, role=MONDAY_ROLE)

    assert request["voice"] == list(_configuration().brand_editorial.voice)


def test_the_request_still_carries_the_draft_and_the_reviewers_findings(tmp_path):
    request, _ = _run_entrypoint(tmp_path, role=MONDAY_ROLE)

    assert request["article"] == "An unattributed first draft."
    assert request["failed_criteria"][0]["criterion_id"] == "evidence-use"
    assert request["revision_guidance"] == "Attribute it."


def test_a_run_without_a_role_is_unchanged(tmp_path):
    request, _ = _run_entrypoint(tmp_path, role=None)

    assert "editorial_role" not in request
    assert "voice" not in request


# ── the surgical contract is the client's lens, and it reaches the model ─────


REVISION_LENS = Path("clients/never_blank/lenses/revision.md")


def _revision_lens_text() -> str:
    from src.strategy.client_contracts import load_lens

    return load_lens(REVISION_LENS).text


def test_the_revision_contract_is_surgical_in_the_client_lens():
    text = " ".join(_revision_lens_text().split())

    assert "Revision is surgical, not regenerative." in text
    assert "Leave every sentence, paragraph and section they do not implicate as it is." in text
    assert "Do not regenerate the article" in text
    assert "Do not flatten the voice, change the article's editorial position" in text


def test_the_rubric_is_unchanged_because_the_policy_is_the_clients():
    assert EditorialAcceptanceRubric.load(RUBRIC_PATH).identity == (
        "never-blank-editorial-acceptance/1.0"
    )


def test_a_monday_revision_request_carries_the_clients_revision_lens(tmp_path):
    request, _ = _run_entrypoint(tmp_path, role=MONDAY_ROLE)

    assert request["client_lenses"] == [_revision_lens_text()]
    assert "Follow every client lens in this request" in request["note"]


def test_the_contract_and_the_context_reach_the_reviser_model_call(monkeypatch):
    seen: list[dict] = []
    replies = iter(["The revised article."])

    def fake_chat(*, system, user, **kwargs):
        seen.append({"system": system, "user": user})
        return next(replies)

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    role = resolve_editorial_role(_configuration(), MONDAY_ROLE)[1]
    context = RevisionContext(
        role_rules=render_editorial_role_rules(role, surface="wix"),
        voice=_configuration().brand_editorial.voice,
        lenses=(_revision_lens_text(),),
    )

    run_editorial_acceptance(
        article_body="The draft that passed everything except attribution.",
        research=_research_artifact(), run_id="run-1",
        rubric=EditorialAcceptanceRubric.load(RUBRIC_PATH),
        reviewer=acceptance_fixtures.FakeReviewTransport(
            acceptance_fixtures._review_payload(  # noqa: SLF001
                disposition="revise", failed=["evidence-use"],
                guidance="Name the source in the second paragraph.",
            ),
            acceptance_fixtures._review_payload(),  # noqa: SLF001
        ),
        revisor=LlmChatArticleRevisionTransport(),
        revision_context=context,
    )

    assert len(seen) == 1, "exactly one revision reached the model"
    request = json.loads(seen[0]["user"])
    assert seen[0]["system"] == EditorialAcceptanceRubric.load(RUBRIC_PATH).revision_instructions
    assert request["editorial_role"] == context.role_rules
    assert request["voice"] == list(context.voice)
    assert request["client_lenses"] == [_revision_lens_text()]
    assert request["article"] == "The draft that passed everything except attribution."
    assert request["revision_guidance"] == "Name the source in the second paragraph."


def test_without_revision_lenses_the_request_has_none():
    """Zero client lenses is valid: nothing is invented in their place."""
    from src.editorial.editorial_acceptance import _revise_article

    revisor = acceptance_fixtures.FakeRevisionTransport("Revised.")
    review = acceptance_fixtures.FakeReviewTransport(
        acceptance_fixtures._review_payload(  # noqa: SLF001
            disposition="revise", failed=["evidence-use"], guidance="g",
        ),
    )
    from src.editorial.editorial_acceptance import _review_article

    verdict = _review_article(
        review, EditorialAcceptanceRubric.load(RUBRIC_PATH),
        article_body="a", research=_research_artifact(), run_id="run-1",
    )
    _revise_article(
        revisor, EditorialAcceptanceRubric.load(RUBRIC_PATH),
        article_body="a", review=verdict, run_id="run-1",
        revision_context=RevisionContext(role_rules="r", voice=("v",)),
    )

    request = json.loads(revisor.calls[0]["request"])
    assert "client_lenses" not in request
    assert request["voice"] == ["v"]
