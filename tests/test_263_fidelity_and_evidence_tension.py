"""#263: social-fidelity calibration + diagnostics (ENGINE), and the conditional
Evidence Tension Lens (CLIENT: NEVER_BLANK).

A. The fidelity judge is not a wording checker: faithful paraphrase of the
   FINAL ACCEPTED article passes, and only materially new meaning — a new fact,
   number, cause, condition, broader generalization or conclusion — fails.
   Every check is recorded as diagnostic evidence that nothing reads back.
B. The Engine gains a generic conditional-lens mechanism. Whether a client's
   condition holds is decided from the RESEARCH EVIDENCE, before the article is
   written; the condition, the behaviour, the tone, the closing question and
   the Echo behaviour are the client's text, never Engine code. Never Blank's
   Evidence Tension Lens lives only on the client side, and another client
   runs through the same Engine without it.

No network, no model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial import platform_composer
from src.editorial.conditional_lenses import (
    ACTIVATION_INSTRUCTIONS,
    ACTIVE_GUIDANCE_KEY,
    LensActivationError,
    evidence_for_activation,
    guidance_block,
    parse_activation,
)
from src.editorial.derivation_fidelity import (
    FIDELITY_INSTRUCTIONS,
    UNSUPPORTED_KINDS,
    FidelityJudgeError,
    RecordedFidelityJudge,
)
from src.strategy.client_contracts import (
    DEFAULT_CLIENT_DIR,
    ClientContractError,
    contracts_for_role,
    load_lens,
)
from tests import test_generate_and_publish as legacy
from tests.test_client_contracts import _write
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_monday_stream import MONDAY_ROLE, _attributed_article
from tests.test_research_artifact_lifecycle import ReadyProvider

SIG = legacy._SIGNAL_ID
NB_LENS = DEFAULT_CLIENT_DIR / "lenses" / "evidence_tension_lens.md"
FINDING = "The source concludes leads fell, while its own figures show submissions rose 28%."


# ===========================================================================
# A. Fidelity calibration (ENGINE)
# ===========================================================================


def test_the_judge_is_told_paraphrase_is_faithful_and_what_counts_as_new():
    text = FIDELITY_INSTRUCTIONS
    assert "Different wording is NOT a problem" in text
    assert "you are\nnot checking wording" in text
    assert "reasonably entails" in text
    for kind in ("new_fact", "new_number", "new_cause", "new_condition",
                 "broader_generalization", "new_conclusion"):
        assert kind in text and kind in UNSUPPORTED_KINDS
    assert UNSUPPORTED_KINDS == {"new_fact", "new_number", "new_cause", "new_condition",
                                 "broader_generalization", "new_conclusion"}


def test_the_judge_knows_no_client():
    for text in (FIDELITY_INSTRUCTIONS, ACTIVATION_INSTRUCTIONS):
        lowered = text.casefold()
        for term in ("never blank", "small business", "small-business", "owner",
                     "echo", "ironic", "mismatch"):
            assert term not in lowered, term


class _ScriptedJudge:
    model_setting = "TEST_MODEL"

    def __init__(self, answer):
        self.answer = answer

    def unsupported(self, **kwargs):
        if isinstance(self.answer, Exception):
            raise self.answer
        return list(self.answer)


def _derive(body: str, judge, *, final: str, draft: str | None = None):
    """The real composer on one derivation, with the judge the run would use."""
    from src.editorial.pipeline import recompose_platform

    payload = json.dumps({"body": body, "echo_included": True, "title": None})
    with mock.patch.object(platform_composer, "chat", return_value=payload):
        return recompose_platform(
            {"echo_line": None}, "medium", canonical_body=final,
            draft_content=draft, fidelity_judge=judge)


FINAL_ARTICLE = ("Every like can hide how few people are ready to buy. The mechanism at "
                 "work here is friction as filter: a quiz inside the ad raised form "
                 "submissions 28%.")
PARAPHRASE = ("The added friction filtered out casual browsers and surfaced "
              "higher-intent prospects: a quiz inside the ad raised form submissions 28%.")
NEW_CONDITION = "The quiz worked without changing the ad or budget."


def test_a_faithful_paraphrase_passes_and_is_recorded_as_pass():
    records = []
    judge = RecordedFidelityJudge(_ScriptedJudge([]), sink=records.append,
                                  identity={"run_id": "r1", "signal_id": "s1"})

    result = _derive(PARAPHRASE, judge, final=FINAL_ARTICLE)

    assert result["body"] == PARAPHRASE
    assert records[0]["verdict"] == "PASS" and records[0]["unsupported"] == []


def test_materially_new_meaning_fails_closed_and_is_recorded_as_fail():
    from src.editorial.pipeline import ArticleGenerationError

    item = {"quote": "without changing the ad or budget", "kind": "new_condition",
            "reason": "the article states no such condition"}
    records = []
    judge = RecordedFidelityJudge(_ScriptedJudge([item]), sink=records.append,
                                  identity={"run_id": "r1", "signal_id": "s1"})

    with pytest.raises(ArticleGenerationError):
        _derive(NEW_CONDITION, judge, final=FINAL_ARTICLE)

    assert [r["verdict"] for r in records] == ["FAIL", "FAIL"]     # retried once
    assert records[0]["unsupported"] == [item]


def test_a_diagnostic_record_carries_everything_263_asks_for():
    records = []
    judge = RecordedFidelityJudge(_ScriptedJudge([]), sink=records.append,
                                  identity={"run_id": "r1", "signal_id": "s1"})
    judge.unsupported(final_content="Final.", derivative="Adapted.", surface="instagram",
                      removed_by_review=("a removed phrase",))

    record = records[0]
    for key in ("run_id", "signal_id", "surface", "final_content_digest", "derivative",
                "removed_by_review", "unsupported", "verdict", "judge", "model_setting"):
        assert key in record, key
    assert record["final_content_digest"].startswith("sha256:")
    assert record["removed_by_review"] == ["a removed phrase"]
    assert record["judge"] == "_ScriptedJudge" and record["model_setting"] == "TEST_MODEL"


def test_a_judge_that_cannot_answer_is_recorded_as_error_and_still_raises():
    records = []
    judge = RecordedFidelityJudge(_ScriptedJudge(FidelityJudgeError("bad JSON")),
                                  sink=records.append, identity={})
    with pytest.raises(FidelityJudgeError):
        judge.unsupported(final_content="F.", derivative="D.", surface="threads")
    assert records[0]["verdict"] == "ERROR" and "bad JSON" in records[0]["error"]


def test_the_numeric_guard_still_rejects_an_invented_figure():
    from src.editorial.pipeline import ArticleGenerationError

    with pytest.raises(ArticleGenerationError):
        _derive("Form submissions rose 41%.", _ScriptedJudge([]), final=FINAL_ARTICLE)


# --- diagnostics on the real run -------------------------------------------


def _preview(tmp_path, *, derive=None, judge=None, activation=None):
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    patches["generate_article"] = mock.MagicMock(return_value=_article())
    if derive is not None:
        patches["recompose_platform"] = mock.MagicMock(side_effect=derive)
    if activation is not None:
        patches["ModelLensActivationJudge"] = mock.MagicMock(return_value=activation)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=lambda *a, **k: []):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator,
                    **({"derivation_judge": judge} if judge is not None else {}))
    return code, patches


def _article():
    article = _attributed_article()
    article["platforms"]["reading"]["body"] = article["platforms"]["long"]["body"]
    return article


def test_every_real_fidelity_check_is_persisted_and_never_publication_input(tmp_path):
    judge_answers = iter([[], [{"quote": "q", "kind": "new_fact", "reason": "r"}]])

    class OneThenFail:
        model_setting = "TEST"

        def unsupported(self, **kwargs):
            return next(judge_answers)

    def derive(structured, format_key, *, fidelity_judge, canonical_body, **kwargs):
        # the real composer consults the judge; this stand-in does the same
        found = fidelity_judge.unsupported(final_content=canonical_body,
                                           derivative=f"{format_key} body",
                                           surface=format_key)
        if found:
            from src.editorial.pipeline import ArticleGenerationError
            raise ArticleGenerationError("platform_recomposer", ValueError("unsupported"))
        return {"body": f"{format_key} body", "word_count": 2, "echo_included": True,
                "title": None}

    code, _ = _preview(tmp_path, derive=derive, judge=OneThenFail())

    assert code == 1                                    # the second surface failed closed
    files = sorted(tmp_path.glob(f"{SIG}/runs/*/fidelity/*.json"))
    assert [f.name for f in files] == ["001-medium.json", "002-reading.json"]
    first, second = (json.loads(f.read_text()) for f in files)
    assert first["verdict"] == "PASS" and second["verdict"] == "FAIL"
    for record in (first, second):
        assert record["publishable"] is False
        assert record["artifact_kind"] == "fidelity_check"
        assert record["run_id"] == files[0].parent.parent.name
    # never a publication input: nothing that builds a package reads it
    source = Path("scripts/generate_and_publish.py").read_text()
    assert "load_fidelity" not in source and "fidelity/" not in source.split("def _run(")[0]


# ===========================================================================
# B. Conditional lenses — the Engine mechanism
# ===========================================================================


CONDITIONAL = """---
lens_id: demo-conditional
version: "1"
applies_to: [demo-weekly]
stages: [writing, revision]
activation: conditional
---

## Activation

Only when the research shows a seasonal price spike.

## When active

Lead with the price spike.
"""


def test_a_conditional_lens_separates_its_condition_from_its_behaviour(tmp_path):
    _write(tmp_path, "lenses/c.md", CONDITIONAL)
    lens = load_lens(tmp_path / "lenses/c.md")

    assert lens.conditional
    assert lens.activation_criteria == "Only when the research shows a seasonal price spike."
    assert lens.text == "Lead with the price spike."


@pytest.mark.parametrize("mutation,message", [
    (lambda t: t.replace("## When active", "## Behaviour"), "exactly"),
    (lambda t: t.replace("## Activation\n\nOnly when the research shows a seasonal price spike.\n\n", ""), "exactly"),
    (lambda t: t.replace("Lead with the price spike.", ""), "empty"),
    (lambda t: t.replace("stages: [writing, revision]", "stages: [selection, writing]"), "selection"),
    (lambda t: t.replace("activation: conditional", "activation: sometimes"), "activation"),
])
def test_a_malformed_conditional_lens_fails_the_run(tmp_path, mutation, message):
    _write(tmp_path, "lenses/c.md", mutation(CONDITIONAL))
    with pytest.raises(ClientContractError, match=message):
        load_lens(tmp_path / "lenses/c.md")


def test_a_conditional_lens_reaches_its_stages_only_when_active():
    contracts = contracts_for_role(MONDAY_ROLE, DEFAULT_CLIENT_DIR)
    lens = next(l for l in contracts.lenses if l.lens_id == "never-blank-evidence-tension")

    assert lens.text not in contracts.for_stage("writing")
    assert lens.text not in contracts.for_stage("revision")
    assert lens.text in contracts.for_stage("writing", {lens.lens_id})
    assert lens.text in contracts.for_stage("revision", {lens.lens_id})
    assert lens.text not in contracts.selection_requirements
    assert any(entry["activation"] == "conditional"
               for entry in contracts.provenance["lenses"])


def test_activation_answers_are_read_strictly():
    assert parse_activation('{"active": false, "finding": "", "reason": "none"}') == (
        False, "", "none")
    assert parse_activation(f'{{"active": true, "finding": "{FINDING}", "reason": "r"}}')[0]
    for raw in ("nope", '{"active": "yes"}', '{"active": true, "finding": "", "reason": "r"}'):
        with pytest.raises(LensActivationError):
            parse_activation(raw)


def test_the_activation_judge_sees_research_evidence_never_generated_text():
    from tests.test_decision_lens_evaluator import _research

    evidence = evidence_for_activation(_research(), legacy._RAW_SIGNAL)

    assert set(evidence) == {"source_claims", "sources", "evidence", "contradictions"}
    assert evidence["source_claims"]["HEADLINE"] == legacy._RAW_SIGNAL["HEADLINE"]
    # nothing composed exists yet when activation is decided (asserted in the run below)


def test_guidance_reaches_the_stages_that_shape_the_argument_and_the_echo():
    from src.editorial import hook_engine, narrative_spine, never_blank_voice

    signal = {"HEADLINE": "H", ACTIVE_GUIDANCE_KEY: "Lead with the price spike."}
    seen = []

    def fake_chat(*, system, user, **kwargs):
        seen.append(user)
        raise RuntimeError("stop after capturing the prompt")

    for module, call in (
        (narrative_spine, lambda: narrative_spine.build_narrative_spine({}, signal)),
        (hook_engine, lambda: hook_engine.generate_hook({}, {}, signal)),
        (never_blank_voice, lambda: never_blank_voice.finalize_article(
            {}, None, {}, {}, {}, {}, signal)),
    ):
        with mock.patch.object(module, "chat", side_effect=fake_chat):
            with pytest.raises(RuntimeError):
                call()
    assert len(seen) == 3
    for prompt in seen:
        assert "ACTIVE CLIENT LENS" in prompt and "Lead with the price spike." in prompt
    assert guidance_block({}) == ""                     # inactive changes nothing


# ===========================================================================
# B. CLIENT: NEVER_BLANK — the Evidence Tension Lens lives on the client side
# ===========================================================================


def test_the_evidence_tension_lens_is_a_conditional_never_blank_client_lens():
    lens = load_lens(NB_LENS)

    assert lens.lens_id == "never-blank-evidence-tension"
    assert lens.conditional and set(lens.stages) == {"writing", "revision"}
    criteria, behaviour = lens.activation_criteria, lens.text
    assert "material tension or" in criteria and "contradiction" in criteria
    assert "Do not activate to make an article more interesting" in criteria
    assert "inside the research evidence" in criteria
    for rule in ("central hook", "what the source claims", "fact and inference",
                 "Keep every useful, supported finding", "lightly ironic",
                 "Never accuse", "does not add up", "Are we the only ones seeing the mismatch?",
                 "Never Blank Echo takes the same evidence-tension perspective",
                 "not licence to add claims of our own"):
        assert rule in behaviour, rule


def test_the_existing_evidence_policy_is_untouched():
    evidence = load_lens(DEFAULT_CLIENT_DIR / "lenses" / "evidence.md")
    assert not evidence.conditional
    assert set(evidence.stages) == {"selection", "writing"}


def test_no_engine_code_carries_the_never_blank_lens_policy():
    engine = [*Path("src").rglob("*.py"), *Path("scripts").rglob("*.py")]
    for path in engine:
        text = path.read_text(encoding="utf-8")
        for phrase in ("Are we the only ones", "lightly ironic", "Evidence Tension",
                       "evidence-tension", "evidence_tension"):
            assert phrase not in text, f"{path}: {phrase}"


# --- on the real run ----------------------------------------------------------


class _Activation:
    model_setting = "TEST"

    def __init__(self, active: bool, finding: str = ""):
        self.active, self.finding, self.calls = active, finding, []

    def decide(self, *, criteria, evidence):
        self.calls.append({"criteria": criteria, "evidence": evidence})
        return self.active, self.finding, "decided from the evidence"


def test_inactive_lens_changes_nothing(tmp_path):
    activation = _Activation(False)
    code, patches = _preview(tmp_path, activation=activation)

    assert code == 0
    kwargs = patches["generate_article"].call_args.kwargs
    assert kwargs["active_guidance"] == ""
    tension = load_lens(NB_LENS).text
    for surface in ("long", "medium"):
        assert tension not in kwargs["editorial_role_rules"][surface]
    record = json.loads(next(tmp_path.glob(f"{SIG}/runs/*/conditional_lenses.json")).read_text())
    assert record["decisions"][0]["active"] is False and record["publishable"] is False


def test_active_lens_shapes_generation_writing_and_revision_before_composition(tmp_path):
    activation = _Activation(True, FINDING)
    order = []
    activation_decide = activation.decide

    def decide(**kwargs):
        order.append("activation")
        return activation_decide(**kwargs)

    activation.decide = decide
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    patches["generate_article"] = mock.MagicMock(
        side_effect=lambda *a, **k: (order.append("generation"), _attributed_article())[1])
    patches["ModelLensActivationJudge"] = mock.MagicMock(return_value=activation)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main(research_provider=ReadyProvider(), decision_evaluator=evaluator) == 0

    tension = load_lens(NB_LENS)
    assert order == ["activation", "generation"]        # resolved before composition
    # the judge got the client's condition and research evidence — no article
    call = activation.calls[0]
    assert call["criteria"] == tension.activation_criteria
    assert _attributed_article()["platforms"]["long"]["body"] not in json.dumps(call["evidence"])
    kwargs = patches["generate_article"].call_args.kwargs
    assert tension.text in kwargs["active_guidance"] and FINDING in kwargs["active_guidance"]
    for surface in ("long", "medium"):
        assert tension.text in kwargs["editorial_role_rules"][surface]
    record = json.loads(next(tmp_path.glob(f"{SIG}/runs/*/conditional_lenses.json")).read_text())
    assert record["decisions"] == [{"lens": "never-blank-evidence-tension/1", "active": True,
                                    "finding": FINDING, "reason": "decided from the evidence"}]


def test_an_undecidable_activation_stops_the_run(tmp_path):
    class Broken:
        def decide(self, **kwargs):
            raise LensActivationError("unreadable")

    code, patches = _preview(tmp_path, activation=Broken())

    assert code == 1
    assert not patches["generate_article"].called


# ===========================================================================
# Replace the client
# ===========================================================================


BAKERY_STREAM = """---
stream_id: bakery-weekly
version: "1"
role_id: never-blank-monday-documented-case
selection: first_valid
---

## Purpose

Help independent bakers price flour and butter against seasonal swings.

## Selection

### Relevant

- The signal concerns ingredient prices.
"""


def test_another_client_without_the_lens_runs_with_no_conditional_behaviour(tmp_path, monkeypatch):
    client = tmp_path / "client"
    _write(client, "streams/weekly.md", BAKERY_STREAM)
    monkeypatch.setenv("NB_CLIENT_DIR", str(client))
    activation = _Activation(True, FINDING)
    code, patches = _preview(tmp_path / "packages", activation=activation)

    assert code == 0
    assert activation.calls == []                        # nothing conditional to decide
    kwargs = patches["generate_article"].call_args.kwargs
    assert kwargs["active_guidance"] == ""
    assert not list((tmp_path / "packages").glob("*/runs/*/conditional_lenses.json"))
    # none of the Evidence Tension Lens reaches the writers. (The role's own
    # configured rules in business_strategy.json still name Never Blank —
    # moving those to the client is #255, not this lens.)
    tension = load_lens(NB_LENS)
    for surface in ("long", "medium"):
        rules = kwargs["editorial_role_rules"][surface]
        assert tension.text not in rules
        assert "Are we the only ones" not in rules
        assert "evidence-tension perspective" not in rules


def test_another_clients_own_conditional_lens_uses_its_own_text(tmp_path, monkeypatch):
    client = tmp_path / "client"
    _write(client, "streams/weekly.md", BAKERY_STREAM)
    _write(client, "lenses/spike.md", CONDITIONAL.replace("demo-weekly", "bakery-weekly"))
    monkeypatch.setenv("NB_CLIENT_DIR", str(client))
    activation = _Activation(True, "Flour rose 30% in March.")
    code, patches = _preview(tmp_path / "packages", activation=activation)

    assert code == 0
    assert activation.calls[0]["criteria"] == (
        "Only when the research shows a seasonal price spike.")
    guidance = patches["generate_article"].call_args.kwargs["active_guidance"]
    assert "Lead with the price spike." in guidance and "Flour rose 30% in March." in guidance
    assert "Are we the only ones" not in guidance and "Never Blank" not in guidance
