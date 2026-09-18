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
* **"Surgical, not regenerative" is prose a person edits.** It lives in the
  rubric's ``revision_instructions`` — the one human-edited text for revision —
  and reaches the reviser as its system message. The tests read that file rather
  than restating it.

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


# ── the surgical contract is the human-edited text, and it reaches the model ─


def _revision_instructions() -> str:
    return yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8"))["revision_instructions"]


def test_the_revision_contract_is_surgical_in_the_human_edited_rubric():
    text = " ".join(_revision_instructions().split())

    assert "Revision is surgical, not regenerative." in text
    assert "Leave every sentence, paragraph and section they do not implicate as it is." in text
    assert "Do not regenerate the article" in text
    assert "Do not flatten the voice, change the article's editorial position" in text


def test_the_rubric_version_moved_with_its_semantics():
    rubric = EditorialAcceptanceRubric.load(RUBRIC_PATH)

    assert rubric.identity == "never-blank-editorial-acceptance/1.1"


def test_the_contract_and_the_context_reach_the_reviser_model_call(monkeypatch):
    seen: list[dict] = []
    replies = iter([
        json.dumps({"disposition": "revise", "failed_criterion_ids": ["evidence-use"],
                    "rationale": "The source is not named.",
                    "revision_guidance": "Name the source in the second paragraph."}),
        "The revised article.",
        json.dumps({"disposition": "accept", "failed_criterion_ids": [],
                    "rationale": "Every criterion passes."}),
    ])

    def fake_chat(*, system, user, **kwargs):
        seen.append({"system": system, "user": user, "json": kwargs.get("json_mode")})
        return next(replies)

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    role = resolve_editorial_role(_configuration(), MONDAY_ROLE)[1]
    context = RevisionContext(
        role_rules=render_editorial_role_rules(role, surface="wix"),
        voice=_configuration().brand_editorial.voice,
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

    reviser_calls = [call for call in seen if call["json"] is not True]
    assert len(reviser_calls) == 1, "exactly one revision"
    call = reviser_calls[0]
    assert call["system"] == _revision_instructions()
    request = json.loads(call["user"])
    assert request["editorial_role"] == context.role_rules
    assert request["voice"] == list(context.voice)
    assert request["article"] == "The draft that passed everything except attribution."
    assert request["revision_guidance"] == "Name the source in the second paragraph."
