"""#263: social-fidelity calibration + diagnostics (ENGINE), and the conditional
Evidence Tension Lens (CLIENT: NEVER_BLANK).

A. The fidelity judge is not a wording checker: faithful paraphrase of the
   FINAL ACCEPTED article passes, and only materially new meaning — a new fact,
   number, cause, condition, broader generalization or conclusion — fails.
   Every check is recorded as diagnostic evidence that nothing reads back.
B. A client's conditional lens runs through the ONE authority the Engine has:
   the ``EditorialPlan`` (#267). Whether the client's condition holds is
   decided from the RESEARCH EVIDENCE before anything is written, the plan
   carries the activated lens into the stages that BUILD the argument — spine,
   hook, voice — and on into composition and revision. The condition, the
   behaviour, the tone, the closing question and the Echo behaviour are the
   client's text, never Engine code. Never Blank's Evidence Tension Lens lives
   only on the client side, and another client runs through the same Engine
   with its own.

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
from src.editorial.derivation_fidelity import (
    FIDELITY_INSTRUCTIONS,
    UNSUPPORTED_KINDS,
    FidelityJudgeError,
    RecordedFidelityJudge,
)
from src.editorial.editorial_plan import (
    PLAN_SIGNAL_KEY,
    Claim,
    EditorialPlanError,
    build_editorial_plan,
    evidence_package_from_artifact,
    plan_block,
)
from src.editorial.plan_decisions import (
    PLAN_DECISION_INSTRUCTIONS,
    plan_decision_request,
)
from src.strategy.client_contracts import (
    DEFAULT_CLIENT_DIR,
    contracts_for_role,
    load_lens,
)
from tests import test_generate_and_publish as legacy
from tests.test_client_contracts import _write
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_monday_stream import MONDAY_ROLE, _attributed_article
from tests.test_no_mandatory_thesis import _run_real_prompt_path
from tests.test_research_artifact_lifecycle import ReadyProvider

SIG = legacy._SIGNAL_ID
NB_LENS = DEFAULT_CLIENT_DIR / "lenses" / "evidence_tension_lens.md"
FINDING = (
    "The source concludes leads fell, while its own figures show submissions rose 28%."
)


# ===========================================================================
# A. Fidelity calibration (ENGINE)
# ===========================================================================


def test_the_judge_is_told_paraphrase_is_faithful_and_what_counts_as_new():
    text = FIDELITY_INSTRUCTIONS
    assert "Different wording is NOT a problem" in text
    assert "you are\nnot checking wording" in text
    assert "reasonably entails" in text
    for kind in (
        "new_fact",
        "new_number",
        "new_cause",
        "new_condition",
        "broader_generalization",
        "new_conclusion",
    ):
        assert kind in text and kind in UNSUPPORTED_KINDS
    # #269 extends the list with the ways a claim is not new but stronger, and
    # with the entities, timeframes and attributions a derivative may invent
    assert UNSUPPORTED_KINDS == {
        "new_fact",
        "new_number",
        "new_entity",
        "new_timeframe",
        "new_cause",
        "new_condition",
        "broader_generalization",
        "new_conclusion",
        "strengthened_claim",
        "invented_attribution",
    }
    for kind in ("new_entity", "new_timeframe", "strengthened_claim",
                 "invented_attribution"):
        assert kind in text, kind


def test_the_judge_knows_no_client():
    for text in (FIDELITY_INSTRUCTIONS, PLAN_DECISION_INSTRUCTIONS):
        lowered = text.casefold()
        for term in (
            "never blank",
            "small business",
            "small-business",
            "owner",
            "echo",
            "ironic",
            "mismatch",
        ):
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
            {"echo_line": None},
            "medium",
            canonical_body=final,
            draft_content=draft,
            fidelity_judge=judge,
        )


FINAL_ARTICLE = (
    "Every like can hide how few people are ready to buy. The mechanism at "
    "work here is friction as filter: a quiz inside the ad raised form "
    "submissions 28%."
)
PARAPHRASE = (
    "The added friction filtered out casual browsers and surfaced "
    "higher-intent prospects: a quiz inside the ad raised form submissions 28%."
)
NEW_CONDITION = "The quiz worked without changing the ad or budget."


def test_a_faithful_paraphrase_passes_and_is_recorded_as_pass():
    records = []
    judge = RecordedFidelityJudge(
        _ScriptedJudge([]),
        sink=records.append,
        identity={"run_id": "r1", "signal_id": "s1"},
    )

    result = _derive(PARAPHRASE, judge, final=FINAL_ARTICLE)

    assert result["body"] == PARAPHRASE
    assert records[0]["verdict"] == "PASS" and records[0]["unsupported"] == []


def test_materially_new_meaning_fails_closed_and_is_recorded_as_fail():
    from src.editorial.pipeline import ArticleGenerationError

    item = {
        "quote": "without changing the ad or budget",
        "kind": "new_condition",
        "reason": "the article states no such condition",
    }
    records = []
    judge = RecordedFidelityJudge(
        _ScriptedJudge([item]),
        sink=records.append,
        identity={"run_id": "r1", "signal_id": "s1"},
    )

    with pytest.raises(ArticleGenerationError):
        _derive(NEW_CONDITION, judge, final=FINAL_ARTICLE)

    assert [r["verdict"] for r in records] == ["FAIL", "FAIL"]  # retried once
    assert records[0]["unsupported"] == [item]


def test_a_diagnostic_record_carries_everything_263_asks_for():
    records = []
    judge = RecordedFidelityJudge(
        _ScriptedJudge([]),
        sink=records.append,
        identity={"run_id": "r1", "signal_id": "s1"},
    )
    judge.unsupported(
        final_content="Final.",
        derivative="Adapted.",
        surface="instagram",
        removed_by_review=("a removed phrase",),
    )

    record = records[0]
    for key in (
        "run_id",
        "signal_id",
        "surface",
        "final_content_digest",
        "derivative",
        "removed_by_review",
        "unsupported",
        "verdict",
        "judge",
        "model_setting",
    ):
        assert key in record, key
    assert record["final_content_digest"].startswith("sha256:")
    assert record["removed_by_review"] == ["a removed phrase"]
    assert (
        record["judge"] == "_ScriptedJudge" and record["model_setting"] == "TEST_MODEL"
    )


def test_a_judge_that_cannot_answer_is_recorded_as_error_and_still_raises():
    records = []
    judge = RecordedFidelityJudge(
        _ScriptedJudge(FidelityJudgeError("bad JSON")), sink=records.append, identity={}
    )
    with pytest.raises(FidelityJudgeError):
        judge.unsupported(final_content="F.", derivative="D.", surface="threads")
    assert records[0]["verdict"] == "ERROR" and "bad JSON" in records[0]["error"]


def test_the_numeric_guard_still_rejects_an_invented_figure():
    from src.editorial.pipeline import ArticleGenerationError

    with pytest.raises(ArticleGenerationError):
        _derive("Form submissions rose 41%.", _ScriptedJudge([]), final=FINAL_ARTICLE)


# --- diagnostics on the real run -------------------------------------------


def _preview(tmp_path, *, derive=None, judge=None, decider=None):
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    patches["generate_article"] = mock.MagicMock(return_value=_article())
    if derive is not None:
        patches["recompose_platform"] = mock.MagicMock(side_effect=derive)
    evaluator, _ = _evaluator(_model_output())
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch.multiple(gap, **patches),
        mock.patch(
            "scripts.research.prepare_content.prepare_content_packages",
            side_effect=lambda *a, **k: [],
        ),
    ):
        code = main(
            research_provider=ReadyProvider(),
            decision_evaluator=evaluator,
            **({"derivation_judge": judge} if judge is not None else {}),
            **({"plan_decider": decider} if decider is not None else {}),
        )
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
        found = fidelity_judge.unsupported(
            final_content=canonical_body,
            derivative=f"{format_key} body",
            surface=format_key,
        )
        if found:
            from src.editorial.pipeline import ArticleGenerationError

            raise ArticleGenerationError(
                "platform_recomposer", ValueError("unsupported")
            )
        return {
            "body": f"{format_key} body",
            "word_count": 2,
            "echo_included": True,
            "title": None,
        }

    code, _ = _preview(tmp_path, derive=derive, judge=OneThenFail())

    assert code == 1  # the second surface failed closed
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
    assert (
        "load_fidelity" not in source
        and "fidelity/" not in source.split("def _run(")[0]
    )


# ===========================================================================
# B. A conditional lens runs through the EditorialPlan, and nothing else
# ===========================================================================


CONDITIONAL = """---
lens_id: demo-conditional
version: "1"
applies_to: [demo-weekly]
stages: [writing, revision]
activates_on: [seasonal_price_spike]
---

Lead with the price spike.
"""

#: What this run decided, in the one shape the Engine accepts (#267).
SPIKE = "seasonal_price_spike"
TENSION = "evidence_tension"


class ScriptedDecider:
    """Answers the plan decision from a script, recording what it was asked."""

    identity = "test:scripted"

    def __init__(self, answer: object) -> None:
        self.answer, self.requests = answer, []

    def decide(self, request):
        self.requests.append(json.loads(json.dumps(request)))
        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)


def _decision(condition: str, *, met: bool, finding: str = "", refs=("evidence-1",)):
    return {
        "activations": [
            {
                "condition": condition,
                "met": met,
                "finding": finding if met else "",
                "evidence_refs": list(refs) if met else [],
                "reason": "decided from the research evidence",
            }
        ],
        "selections": [],
    }


def _nb_contracts():
    return contracts_for_role(MONDAY_ROLE, DEFAULT_CLIENT_DIR)


def _nb_plan(*, active: bool, finding: str = FINDING):
    """The plan a Never Blank run builds, with the lens active or not."""
    contracts = _nb_contracts()
    return build_editorial_plan(
        contracts,
        central_claim=Claim(text="The source's figures do not support its conclusion."),
        activation_evidence={TENSION: finding} if active else {},
    )


def test_a_client_declares_its_condition_in_front_matter_not_in_engine_code(tmp_path):
    _write(tmp_path, "lenses/c.md", CONDITIONAL)
    lens = load_lens(tmp_path / "lenses/c.md")

    assert not lens.is_standing and lens.activates_on == (SPIKE,)
    assert lens.text == "Lead with the price spike."


def test_a_conditional_lens_reaches_its_stages_only_through_a_plan():
    contracts = _nb_contracts()
    lens = next(
        l for l in contracts.lenses if l.lens_id == "never-blank-evidence-tension"
    )

    # no route that predates the plan carries it
    assert lens.text not in contracts.for_stage("writing")
    assert lens.text not in contracts.for_stage("revision")
    assert lens.text not in contracts.selection_requirements
    # and the plan carries it to both stages once this run activated it
    active = _nb_plan(active=True)
    for stage in ("writing", "revision"):
        assert any(lens.text in text for text in active.activated_lens_texts(stage))
    inactive = _nb_plan(active=False)
    for stage in ("writing", "revision"):
        assert inactive.activated_lens_texts(stage) == ()
    assert any(
        entry["activates_on"] == [TENSION] for entry in contracts.provenance["lenses"]
    )


def test_the_decision_sees_research_evidence_and_never_generated_text():
    from tests.test_decision_lens_evaluator import _research

    request = plan_decision_request(
        _nb_contracts(),
        central_claim=Claim(text="The figures point the other way."),
        evidence=evidence_package_from_artifact(_research()),
    )

    assert [c["condition"] for c in request["conditions"]] == [TENSION]
    assert set(request) == {"central_claim", "conditions", "slots", "evidence"}
    # the client's own lens text is what defines the condition, verbatim
    assert "material tension" in request["conditions"][0]["lenses"][0]["text"]
    # nothing composed exists yet: only evidence items and the run's claim
    assert _attributed_article()["platforms"]["long"]["body"] not in json.dumps(request)


def test_an_activated_lens_carries_the_evidence_that_activated_it():
    texts = _nb_plan(active=True).activated_lens_texts("writing")

    assert len(texts) == 1
    assert FINDING in texts[0]
    assert "Are we the only ones seeing the mismatch?" in texts[0]


def test_a_lens_may_not_be_activated_without_evidence():
    with pytest.raises(EditorialPlanError, match="applied on evidence or not at all"):
        _nb_plan(active=True, finding="   ")


def test_the_plan_reaches_the_stages_that_build_the_argument():
    """The generic upstream route: one key, read by every writing stage."""
    from src.editorial import hook_engine, narrative_spine, never_blank_voice

    signal = {"HEADLINE": "H", PLAN_SIGNAL_KEY: "PLAN-CANARY: close on the tension."}
    seen = []

    def fake_chat(*, system, user, **kwargs):
        seen.append(user)
        raise RuntimeError("stop after capturing the prompt")

    for module, call in (
        (narrative_spine, lambda: narrative_spine.build_narrative_spine({}, signal)),
        (hook_engine, lambda: hook_engine.generate_hook({}, {}, signal)),
        (
            never_blank_voice,
            lambda: never_blank_voice.finalize_article(
                {}, None, {}, {}, {}, {}, signal
            ),
        ),
    ):
        with (
            mock.patch.object(module, "chat", side_effect=fake_chat),
            pytest.raises(RuntimeError),
        ):
            call()

    assert len(seen) == 3
    for prompt in seen:
        assert "PLAN-CANARY: close on the tension." in prompt
    assert plan_block({}) == ""  # no plan changes nothing


# ===========================================================================
# B. CLIENT: NEVER_BLANK — the Evidence Tension Lens lives on the client side
# ===========================================================================


def test_the_evidence_tension_lens_is_a_conditional_never_blank_client_lens():
    lens = load_lens(NB_LENS)

    assert lens.lens_id == "never-blank-evidence-tension"
    assert not lens.is_standing and set(lens.stages) == {"writing", "revision"}
    assert lens.activates_on == (TENSION,)
    for rule in (
        "material tension or",
        "contradiction",
        "Do not activate to make an article more interesting",
        "inside the research evidence",
        "central hook",
        "what the source claims",
        "fact and inference",
        "Keep every useful, supported finding",
        "lightly ironic",
        "Never accuse",
        "does not add up",
        "Are we the only ones seeing the mismatch?",
        "Never Blank Echo takes the same evidence-tension perspective",
        "not licence to add claims of our own",
    ):
        assert rule in lens.text, rule


def test_the_existing_evidence_policy_is_untouched():
    evidence = load_lens(DEFAULT_CLIENT_DIR / "lenses" / "evidence.md")
    assert evidence.is_standing
    assert set(evidence.stages) == {"selection", "writing"}


def test_no_engine_code_carries_the_never_blank_lens_policy():
    engine = [*Path("src").rglob("*.py"), *Path("scripts").rglob("*.py")]
    for path in engine:
        text = path.read_text(encoding="utf-8")
        for phrase in (
            "Are we the only ones",
            "lightly ironic",
            "Evidence Tension",
            "evidence-tension",
            "evidence_tension",
        ):
            assert phrase not in text, f"{path}: {phrase}"


# ===========================================================================
# C. The whole chain, on the real run
# ===========================================================================


def _run_plan(tmp_path, decider):
    """Run the entrypoint and return the plan generation actually received."""
    code, patches = _preview(tmp_path, decider=decider)
    call = patches["generate_article"].call_args
    return (
        code,
        (call.kwargs.get("editorial_plan") if call is not None else None),
        patches,
    )


def test_an_inactive_lens_changes_nothing(tmp_path):
    decider = ScriptedDecider(_decision(TENSION, met=False))

    code, plan, patches = _run_plan(tmp_path, decider)

    assert code == 0
    assert plan is not None and plan.activated_lens_texts("writing") == ()
    tension = load_lens(NB_LENS).text
    for surface in ("long", "medium"):
        assert (
            tension
            not in patches["generate_article"].call_args.kwargs["editorial_role_rules"][
                surface
            ]
        )
    record = json.loads(
        next(tmp_path.glob(f"{SIG}/runs/*/editorial_plan.json")).read_text()
    )
    assert record["run_decisions"]["activations"][0] == {
        "condition": TENSION,
        "met": False,
        "finding": "",
        "evidence_refs": [],
        "reason": "decided from the research evidence",
        "declared_by": ["never-blank-evidence-tension/1"],
        "stages": ["writing", "revision"],
    }
    assert [entry for entry in record["active_by_stage"]["writing"]
            if entry["activation"]] == []


def test_the_client_document_reaches_the_stages_that_build_the_argument(
    tmp_path, monkeypatch
):
    """The lineage #263 asks for, end to end:

    client lens document → activation decision on this run's evidence →
    EditorialPlan → the spine, hook and voice that build the argument → the
    composed article. The plan handed to the real prompt path below is the
    exact object the production run built.
    """
    decider = ScriptedDecider(_decision(TENSION, met=True, finding=FINDING))

    code, plan, _ = _run_plan(tmp_path, decider)

    assert code == 0
    # the decision was made from this run's evidence, and recorded
    assert decider.requests[0]["conditions"][0]["condition"] == TENSION
    record = json.loads(
        next(tmp_path.glob(f"{SIG}/runs/*/editorial_plan.json")).read_text()
    )
    assert record["run_decisions"]["activations"][0]["met"] is True
    assert record["run_decisions"]["activations"][0]["evidence_refs"] == ["evidence-1"]
    for stage in ("writing", "revision"):
        assert [entry for entry in record["active_by_stage"][stage]
                if entry["activation"]] == [
            {"identity": "never-blank-evidence-tension/1", "activation": TENSION}
        ]

    # …and that same plan reaches every stage that shapes the argument
    calls, _ = _run_real_prompt_path(
        monkeypatch,
        MONDAY_ROLE,
        "price",
        "A published figure moved first.",
        editorial_plan=plan,
    )
    canary = "Are we the only ones seeing the mismatch?"
    for stage in (
        "narrative_spine",
        "hook_engine",
        "never_blank_voice",
        "platform_composer",
    ):
        assert canary in "\n".join(calls[stage]), stage
        assert FINDING in "\n".join(calls[stage]), stage


def test_an_inactive_lens_reaches_none_of_those_stages(tmp_path, monkeypatch):
    """The mutation twin: same client, same run, condition not met."""
    code, plan, _ = _run_plan(tmp_path, ScriptedDecider(_decision(TENSION, met=False)))

    assert code == 0
    calls, _ = _run_real_prompt_path(
        monkeypatch,
        MONDAY_ROLE,
        "price",
        "A published figure moved first.",
        editorial_plan=plan,
    )
    for stage in (
        "narrative_spine",
        "hook_engine",
        "never_blank_voice",
        "platform_composer",
    ):
        assert "Are we the only ones seeing the mismatch?" not in "\n".join(
            calls[stage]
        )


def test_an_active_lens_reaches_the_reviser(tmp_path):
    from tests.test_editorial_acceptance import (
        FakeReviewTransport,
        FakeRevisionTransport,
        _review_payload,
    )

    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    del patches["run_editorial_acceptance"]  # the REAL acceptance boundary
    patches["generate_article"] = mock.MagicMock(return_value=_article())
    reviewer = FakeReviewTransport(
        _review_payload(
            disposition="revise",
            failed=["unsupported-claims"],
            guidance="State only what the evidence supports.",
        ),
        _review_payload(),
    )
    revisor = FakeRevisionTransport(_article()["platforms"]["long"]["body"])
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(
            research_provider=ReadyProvider(),
            decision_evaluator=evaluator,
            editorial_reviewer=reviewer,
            article_revisor=revisor,
            plan_decider=ScriptedDecider(_decision(TENSION, met=True, finding=FINDING)),
        )

    assert code == 0
    lenses = "\n".join(json.loads(revisor.calls[0]["request"])["client_lenses"])
    assert "Are we the only ones seeing the mismatch?" in lenses
    assert FINDING in lenses


def test_an_undecidable_decision_stops_the_run(tmp_path):
    code, patches = _preview(tmp_path, decider=ScriptedDecider("not json at all"))

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


def test_another_client_without_a_conditional_lens_decides_nothing(
    tmp_path, monkeypatch
):
    client = tmp_path / "client"
    _write(client, "streams/weekly.md", BAKERY_STREAM)
    monkeypatch.setenv("NB_CLIENT_DIR", str(client))
    decider = ScriptedDecider(_decision(TENSION, met=True, finding=FINDING))

    code, patches = _preview(tmp_path / "packages", decider=decider)

    assert code == 0
    assert decider.requests == []  # nothing left open to decide
    assert patches["generate_article"].call_args.kwargs["editorial_plan"] is None
    assert not list((tmp_path / "packages").glob("*/runs/*/editorial_plan.json"))
    # none of the Evidence Tension Lens reaches the writers. (The role's own
    # configured rules in business_strategy.json still name Never Blank —
    # moving those to the client is #255, not this lens.)
    tension = load_lens(NB_LENS)
    for surface in ("long", "medium"):
        rules = patches["generate_article"].call_args.kwargs["editorial_role_rules"][
            surface
        ]
        assert tension.text not in rules
        assert "Are we the only ones" not in rules


def test_another_clients_own_conditional_lens_uses_its_own_text(tmp_path, monkeypatch):
    client = tmp_path / "client"
    _write(client, "streams/weekly.md", BAKERY_STREAM)
    _write(
        client, "lenses/spike.md", CONDITIONAL.replace("demo-weekly", "bakery-weekly")
    )
    monkeypatch.setenv("NB_CLIENT_DIR", str(client))
    decider = ScriptedDecider(
        _decision(SPIKE, met=True, finding="Flour rose 30% in March.")
    )

    code, patches = _preview(tmp_path / "packages", decider=decider)

    assert code == 0
    assert decider.requests[0]["conditions"][0]["condition"] == SPIKE
    plan = patches["generate_article"].call_args.kwargs["editorial_plan"]
    carried = "\n".join(plan.activated_lens_texts("writing"))
    assert (
        "Lead with the price spike." in carried
        and "Flour rose 30% in March." in carried
    )
    assert "Are we the only ones" not in carried and "Never Blank" not in carried
