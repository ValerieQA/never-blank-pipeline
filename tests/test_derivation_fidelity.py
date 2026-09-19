"""#260 (review of fdcefc4): non-numeric derivation fidelity is enforced.

The figure guard proves only that a number cannot be invented. Controlled live
run 35417616416 failed differently: Instagram added "without changing the ad
or budget" and a renewed small-business generalization — claims with no
number in them. These tests prove the enforced, fail-closed checks for that
class, end to end through the real entrypoint, the REAL acceptance boundary
and the REAL composer:

- a clause Editorial Revision removed, restored by Instagram → the run stops:
  the reused draft wording is handed to the fidelity judge as evidence and
  the judge's confirmation is enforced;
- reused draft wording alone never rejects — a claim revision only reworded
  (and the final article still supports) passes (#262 review);
- a new generalization the accepted article never made → the run stops
  (the fidelity judge's verdict is enforced);
- a faithful derivative passes, and every derivation is judged against the
  final accepted article;
- a judge that cannot answer stops the run rather than waving it through.

No network, no model.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial import platform_composer
from src.editorial.derivation_fidelity import (
    FIDELITY_INSTRUCTIONS,
    FidelityJudgeError,
    ModelFidelityJudge,
    parse_judgment,
    removed_phrases,
    resurrected_phrases,
)
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_editorial_acceptance import (
    FakeReviewTransport,
    FakeRevisionTransport,
    _review_payload,
)
from tests.test_monday_stream import FIXTURE_SOURCE_TITLE, FIXTURE_SOURCE_URL, MONDAY_ROLE
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_social_derivation_invariant import (
    ECHO,
    TITLE,
    FaithfulComposer,
    RecordingJudge,
    _draft,
)
from tests.test_visual_contract import _pimgs

SIG = legacy._SIGNAL_ID

#: The live run's non-numeric addition, verbatim.
LIVE_CLAUSE = "without changing the ad or budget"
#: The live run's renewed generalization, as a new claim.
GENERALIZATION = "The same lesson holds for every small business"

_CITATION = f"Source: {FIXTURE_SOURCE_TITLE} ({FIXTURE_SOURCE_URL})."

DRAFT = (
    "Every like and comment on your ad can disguise how few people are ready to buy.\n\n"
    "In one documented case, adding a quiz to the ad improved the quality of the "
    f"leads it produced {LIVE_CLAUSE}. {_CITATION}\n\n"
    "Requiring a small action inside the ad filters casual browsers from buyers.\n\n"
    f"**Never Blank:** {ECHO}"
)
FINAL = (
    "Every like and comment on your ad can disguise how few people are ready to buy.\n\n"
    "In one documented case, adding a quiz to the ad improved the quality of the "
    f"leads it produced. {_CITATION}\n\n"
    "Requiring a small action inside the ad filters casual browsers from buyers.\n\n"
    f"**Never Blank:** {ECHO}"
)


class ReviewAwareJudge(RecordingJudge):
    """A test judge that weighs the removed-by-review evidence the way the
    production instructions ask: a reused draft phrase is unsupported unless
    the final content supports the same claim (here: listed in ``supported``)."""

    def __init__(self, flag=(), supported=()):
        super().__init__(flag=flag)
        self.supported = tuple(supported)

    def unsupported(self, *, final_content, derivative, surface, removed_by_review=()):
        found = super().unsupported(final_content=final_content, derivative=derivative,
                                    surface=surface, removed_by_review=removed_by_review)
        return found + [phrase for phrase in removed_by_review
                        if not any(claim in phrase or phrase in claim
                                   for claim in self.supported)]


class AddingComposer(FaithfulComposer):
    """Faithful on every surface except ONE, where it appends a sentence —
    the shape of the live Instagram attempts."""

    def __init__(self, target: str, addition: str) -> None:
        super().__init__()
        self.target, self.addition = target, addition

    def __call__(self, *, system, user, **kwargs):
        raw = json.loads(super().__call__(system=system, user=user, **kwargs))
        fmt = re.search(r"^FORMAT: (\w+)$", user, re.MULTILINE).group(1)
        if fmt == self.target:
            body = raw["body"]
            closing = body.rsplit("\n\n", 1)
            raw["body"] = (f"{closing[0]} {self.addition}\n\n{closing[1]}"
                           if len(closing) == 2 else f"{self.addition}\n\n{body}")
        return json.dumps(raw)


def _run(tmp_path, *, composer, judge, draft_body=DRAFT, final_body=None):
    final_body = FINAL if final_body is None else final_body
    draft = copy.deepcopy(_draft())
    draft["platforms"]["long"] = {"body": draft_body, "title": TITLE}
    argv, patches = _entry_patches(tmp_path)          # dry run
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    del patches["run_editorial_acceptance"]           # the REAL acceptance boundary
    del patches["recompose_platform"]                 # the REAL derivation seam
    patches.pop("formatting", None)
    patches.pop("generate_hashtags", None)
    patches["generate_article"] = mock.MagicMock(return_value=draft)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["unsupported-claims"],
                        guidance="The source does not say the ad or budget were unchanged."),
        _review_payload(),
    )
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.object(platform_composer, "chat", side_effect=composer), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: [
                           {"images": {"platform_images": _pimgs(tmp_path)}}]):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator,
                    editorial_reviewer=reviewer,
                    article_revisor=FakeRevisionTransport(final_body),
                    derivation_judge=judge)
    return code, patches


def _artifact(tmp_path, name):
    found = next(tmp_path.glob(f"{SIG}/runs/*/{name}"), None)
    return json.loads(found.read_text()) if found else None


def _assert_stopped_without_effects(tmp_path, patches):
    assert _artifact(tmp_path, "generated.json") is None
    assert not patches["WixPublisher"].called
    assert not patches["LinkedInPublisher"].called
    assert not patches["append_published_entry"].called
    # the accepted article outlives the failed derivation (#260 item 2)
    accepted = _artifact(tmp_path, "accepted_composition.json")
    assert accepted["content"]["article_body"] == FINAL
    assert accepted["content"]["title"] == TITLE
    assert accepted["content"]["echo"] == ECHO


# ===========================================================================
# The live failure class: a removed non-numeric clause comes back
# ===========================================================================


def test_instagram_restoring_a_clause_revision_removed_fails_closed(tmp_path):
    """The live failure: the judge, handed the removed wording as evidence,
    confirms the claim is unsupported — and the run stops."""
    composer = AddingComposer("instagram", f"It worked {LIVE_CLAUSE}.")
    judge = ReviewAwareJudge()
    code, patches = _run(tmp_path, composer=composer, judge=judge)

    assert code == 1
    _assert_stopped_without_effects(tmp_path, patches)
    rejected = _artifact(tmp_path, "rejected_composition.json")
    attempts = [a for a in rejected["attempts"] if a["format"] == "instagram"]
    assert len(attempts) == 2                        # retried once, then stopped
    for attempt in attempts:
        assert "does not support" in attempt["validation_error"]
        assert "wording Editorial Review removed" in attempt["validation_error"]
        assert "changing the ad or budget" in attempt["validation_error"]
    # the evidence reached the judge for the Instagram derivation
    evidence = [c["removed_by_review"] for c in judge.calls if c["surface"] == "instagram"]
    assert evidence and all(any("budget" in p for p in e) for e in evidence)


def test_reused_removed_wording_alone_never_rejects(tmp_path):
    """Wording is evidence, not a verdict: if the judge finds the claim
    supported, reused draft wording does not stop the run (#262 review)."""
    composer = AddingComposer("instagram", f"It worked {LIVE_CLAUSE}.")
    judge = RecordingJudge()                         # finds everything supported
    code, _ = _run(tmp_path, composer=composer, judge=judge)

    assert code == 0
    evidence = [c["removed_by_review"] for c in judge.calls if c["surface"] == "instagram"]
    assert evidence and any("budget" in p for p in evidence[0])


REWORDED_DRAFT = (
    "Every like and comment on your ad can disguise how few people are ready to buy.\n\n"
    "In one documented case, form submissions rose by twenty eight percent once a quiz "
    f"sat inside the ad {LIVE_CLAUSE}. {_CITATION}\n\n"
    "Requiring a small action inside the ad filters casual browsers from buyers.\n\n"
    f"**Never Blank:** {ECHO}"
)
REWORDED_FINAL = (
    "Every like and comment on your ad can disguise how few people are ready to buy.\n\n"
    "In one documented case, form submissions increased 28% once a quiz sat inside "
    f"the ad. {_CITATION}\n\n"
    "Requiring a small action inside the ad filters casual browsers from buyers.\n\n"
    f"**Never Blank:** {ECHO}"
)
#: what the final article still supports, in the draft's words
REWORDED_CLAIM = "form submissions rose by twenty eight percent"


def test_a_claim_revision_only_reworded_is_allowed(tmp_path):
    """Revision reworded a claim it kept: a derivative using the draft's
    wording is faithful, and passes."""
    composer = AddingComposer("instagram", "Form submissions rose by twenty eight percent.")
    judge = ReviewAwareJudge(supported=(REWORDED_CLAIM,))
    code, _ = _run(tmp_path, composer=composer, judge=judge,
                   draft_body=REWORDED_DRAFT, final_body=REWORDED_FINAL)

    assert code == 0
    generated = _artifact(tmp_path, "generated.json")
    assert "rose by twenty eight percent" in generated["instagram_caption"]
    # it WAS reused removed wording — the judge weighed it and found it supported
    evidence = [c["removed_by_review"] for c in judge.calls if c["surface"] == "instagram"]
    assert evidence and any("twenty eight" in p for p in evidence[0])


def test_in_the_same_revision_the_removed_clause_is_still_rejected(tmp_path):
    composer = AddingComposer("instagram", f"It worked {LIVE_CLAUSE}.")
    judge = ReviewAwareJudge(supported=(REWORDED_CLAIM,))
    code, patches = _run(tmp_path, composer=composer, judge=judge,
                         draft_body=REWORDED_DRAFT, final_body=REWORDED_FINAL)

    assert code == 1
    assert _artifact(tmp_path, "generated.json") is None
    assert not patches["LinkedInPublisher"].called


def test_a_new_generalization_the_article_never_made_fails_closed(tmp_path):
    """Not in the draft either — only the enforced judge verdict can stop it."""
    composer = AddingComposer("instagram", f"{GENERALIZATION}.")
    judge = RecordingJudge(flag=(GENERALIZATION,))
    code, patches = _run(tmp_path, composer=composer, judge=judge)

    assert code == 1
    _assert_stopped_without_effects(tmp_path, patches)
    rejected = _artifact(tmp_path, "rejected_composition.json")
    errors = [a["validation_error"] for a in rejected["attempts"] if a["format"] == "instagram"]
    assert errors and all("does not support" in e and "small business" in e for e in errors)
    # the judge weighed Instagram against the FINAL accepted article
    instagram = [c for c in judge.calls if c["surface"] == "instagram"]
    assert instagram and all(c["final_content"] == FINAL for c in instagram)


@pytest.mark.parametrize("surface", ["medium", "reading", "telegram", "threads"])
def test_every_derivation_is_held_to_the_same_rule(tmp_path, surface):
    composer = AddingComposer(surface, f"It worked {LIVE_CLAUSE}.")
    code, patches = _run(tmp_path, composer=composer, judge=ReviewAwareJudge())

    assert code == 1
    assert _artifact(tmp_path, "generated.json") is None


def test_a_faithful_derivation_passes_and_every_surface_is_judged(tmp_path):
    judge = RecordingJudge(flag=(GENERALIZATION, LIVE_CLAUSE))
    code, patches = _run(tmp_path, composer=FaithfulComposer(), judge=judge)

    assert code == 0
    generated = _artifact(tmp_path, "generated.json")
    for field in ("linkedin_post", "facebook_post", "instagram_caption", "telegram_text"):
        assert LIVE_CLAUSE not in generated[field], field
    assert all(LIVE_CLAUSE not in post for post in generated["threads_sequence"])
    judged = {call["surface"] for call in judge.calls}
    assert judged == {"medium", "reading", "instagram", "telegram", "threads"}
    assert all(call["final_content"] == FINAL for call in judge.calls)


def test_a_judge_that_cannot_answer_stops_the_run(tmp_path):
    class BrokenJudge:
        def unsupported(self, **kwargs):
            raise FidelityJudgeError("fidelity judge returned invalid JSON")

    code, patches = _run(tmp_path, composer=FaithfulComposer(), judge=BrokenJudge())

    assert code == 1
    assert _artifact(tmp_path, "generated.json") is None
    assert not patches["LinkedInPublisher"].called


# ===========================================================================
# The Engine pieces
# ===========================================================================


def test_removed_phrases_are_what_revision_took_out():
    removed = removed_phrases(DRAFT, FINAL)

    assert resurrected_phrases(f"Results improved {LIVE_CLAUSE}.", removed)
    assert resurrected_phrases("Results improved without changing the Ad, or budget!", removed)
    # a faithful restatement of the accepted text is not a resurrection
    assert resurrected_phrases(FINAL, removed) == []
    assert resurrected_phrases(
        "Adding a quiz improved the quality of the leads the ad produced.", removed) == []


def test_connective_words_alone_never_count_as_removed_content():
    removed = removed_phrases("It was one of the best of all of them.", "Nothing.")
    assert all(sum(w not in {"it", "was", "of", "the", "all", "them"} for w in gram) >= 2
               for gram in removed)


@pytest.mark.parametrize("raw,expected", [
    ('{"unsupported": []}', []),
    ('{"unsupported": [{"quote": "the same lesson holds", "kind": "broader_generalization", '
     '"reason": "extends the case"}]}',
     [{"quote": "the same lesson holds", "kind": "broader_generalization",
       "reason": "extends the case"}]),
])
def test_a_judgment_is_read_strictly(raw, expected):
    assert parse_judgment(raw) == expected


@pytest.mark.parametrize("raw", [
    "not json", '{"unsupported": "x"}', '{"other": []}', '{"unsupported": [1]}', "[]",
    # #263: a bare string, an unknown kind, or an empty quote is not an answer
    '{"unsupported": ["a phrase"]}',
    '{"unsupported": [{"quote": "x", "kind": "different_wording", "reason": ""}]}',
    '{"unsupported": [{"quote": " ", "kind": "new_fact", "reason": ""}]}',
])
def test_an_unreadable_judgment_is_an_error_never_a_pass(raw):
    with pytest.raises(FidelityJudgeError):
        parse_judgment(raw)


def test_the_production_judge_knows_no_client():
    """Replace-the-client: the judge sees two texts and a platform, nothing else."""
    text = FIDELITY_INSTRUCTIONS.casefold()
    for term in ("never blank", "small business", "small-business", "owner", "echo"):
        assert term not in text, term

    captured: dict = {}

    def fake_chat(*, system, user, json_mode, model):
        captured.update(system=system, user=json.loads(user))
        return '{"unsupported": []}'

    with mock.patch("src.utils.llm_client.chat", side_effect=fake_chat):
        assert ModelFidelityJudge().unsupported(
            final_content="Final.", derivative="Adapted.", surface="instagram") == []
    assert captured["system"] == FIDELITY_INSTRUCTIONS
    assert captured["user"] == {"platform": "instagram", "FINAL CONTENT": "Final.",
                                "ADAPTATION": "Adapted."}
    # the removed-by-review evidence travels to the judge when there is some
    with mock.patch("src.utils.llm_client.chat", side_effect=fake_chat):
        ModelFidelityJudge().unsupported(
            final_content="Final.", derivative="Adapted.", surface="instagram",
            removed_by_review=("without changing the ad",))
    assert captured["user"]["REMOVED BY REVIEW"] == ["without changing the ad"]
    assert "report it only if its meaning is not stated or reasonably entailed" in (
        FIDELITY_INSTRUCTIONS)


def test_production_runs_always_have_a_judge():
    source = __import__("pathlib").Path("scripts/generate_and_publish.py").read_text()
    assert "derivation_judge or ModelFidelityJudge()," in source
    assert "_fidelity_judge = RecordedFidelityJudge(" in source      # #263: every check recorded
    assert source.count("fidelity_judge=_fidelity_judge") == 2      # LinkedIn + preview
