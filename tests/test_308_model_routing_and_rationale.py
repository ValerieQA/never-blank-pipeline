"""#308 run 1 repair: one model identity, and a SKIP whose reason survives.

The first attempted acceptance run (37249738203) stopped at S-00 after one
model call, and the log showed that call going out on `gpt-4o` while
`NB_GOLDEN_ENGINE_MODEL` named another model. `golden_engine_transports()` does
read that variable — for the **ten** stage transports, and ten was the hole:
the three seams at the front of the chain are not Golden Engine transports and
resolved their own model through `model_enrich()`.

The second half is that the verdict which ended the run could not be reviewed.
`OutcomeRecord.reason` already carries the model's own words, and the ledger
deliberately does not (§3.3: a reason is a StateCode and a closed category) —
but nothing uploaded the run workspace, so the words died with the runner.

Both repairs are narrow on purpose. The transports keep their legacy default,
so Monday, Wednesday and every other caller route exactly as before; only the
canonical shadow composition root asks for something else. And the rationale is
preserved by keeping the workspace §3.2 already defines as a 90-day artifact,
rather than by putting prose into a ledger that refuses it.
"""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = pathlib.Path(".github/workflows/canonical_shadow.yml")
SCRIPT = pathlib.Path("scripts/run_canonical_shadow.py")


def executable_source(path: pathlib.Path) -> str:
    """The module's code with comments and docstrings removed.

    Asserting that a name is *absent* from a file is worthless against raw
    text: the comment explaining why it is absent contains it. I have now hit
    that three times in this slice chain — a workflow test that read `git add`
    out of a comment saying there is none, a visual-contract test that read
    "threshold" out of a comment saying there is no threshold, and this one.
    So the stripping happens once, here, and the absence tests use it.
    """

    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body.pop(0)
    return ast.unparse(tree)


# ===========================================================================
# One authoritative model identity for the canonical shadow run
# ===========================================================================


def test_every_front_of_chain_transport_accepts_an_explicit_model():
    from src.editorial.decision_lens_evaluator import LlmChatDecisionLensTransport
    from src.editorial.source_eligibility import LlmChatSourceEligibilityTransport
    from src.research.assessment import LlmChatEvidenceJudgmentTransport

    for cls in (
        LlmChatSourceEligibilityTransport,
        LlmChatEvidenceJudgmentTransport,
        LlmChatDecisionLensTransport,
    ):
        assert cls("m-1")._model == "m-1", cls.__name__


def test_the_legacy_default_is_untouched():
    """Monday, Wednesday and every other caller keep their routing.

    `None` means "resolve as you always did" — `model_enrich()`. The repair is
    an injection at one composition root, not a change to global routing.
    """

    from src.editorial.decision_lens_evaluator import (
        LlmChatDecisionLensTransport,
        production_evaluator,
    )
    from src.editorial.source_eligibility import LlmChatSourceEligibilityTransport
    from src.research.assessment import LlmChatEvidenceJudgmentTransport

    for cls in (
        LlmChatSourceEligibilityTransport,
        LlmChatEvidenceJudgmentTransport,
        LlmChatDecisionLensTransport,
    ):
        assert cls()._model is None, cls.__name__

    assert production_evaluator()._transport._model is None
    assert production_evaluator(model="m-2")._transport._model == "m-2"


def test_each_transport_falls_back_to_model_enrich_only_when_none_is_given():
    """The fallback is `or`, so an injected model always wins.

    Asserted on the parsed source rather than by making a call: a test that
    needed a provider to prove which model was asked for would need a provider.
    """

    import ast
    import inspect

    from src.editorial.decision_lens_evaluator import LlmChatDecisionLensTransport
    from src.editorial.source_eligibility import LlmChatSourceEligibilityTransport
    from src.research.assessment import LlmChatEvidenceJudgmentTransport

    for cls in (
        LlmChatSourceEligibilityTransport,
        LlmChatEvidenceJudgmentTransport,
        LlmChatDecisionLensTransport,
    ):
        source = inspect.getsource(cls.complete)
        tree = ast.parse(source.strip())
        kwargs = [
            keyword
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "model"
        ]
        assert len(kwargs) == 1, cls.__name__
        expression = ast.unparse(kwargs[0].value)
        assert expression == "self._model or model_enrich()", (
            f"{cls.__name__}: {expression}"
        )


def test_the_canonical_composition_root_names_one_model_for_every_seam():
    """The fix for the defect, read off the composition root itself."""

    code = executable_source(SCRIPT)

    assert "model = configured_golden_engine_model()" in code
    assert "LlmChatSourceEligibilityTransport(model)" in code
    assert "LlmChatEvidenceJudgmentTransport(model)" in code
    assert "production_evaluator(model=model)" in code
    # And nothing in this root resolves a model any other way. Checked against
    # the executable code, so the comment that explains the defect does not
    # read as the defect.
    for other in ("model_enrich", "NB_ENRICH_MODEL", "NB_OPENAI_CHAT_MODEL"):
        assert other not in code, other


def test_an_unconfigured_model_still_stops_the_run_before_any_call():
    """`configured_golden_engine_model()` has no fallback, and that is the point.

    The canonical run refuses to start rather than measuring whatever the
    legacy pipeline happens to be set to — now for the front of the chain too,
    because the same function answers for all of it.
    """

    import os
    from unittest import mock

    from src.run.transports import (
        GoldenEngineModelConfigurationError,
        configured_golden_engine_model,
    )

    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(GoldenEngineModelConfigurationError):
            configured_golden_engine_model()


# ===========================================================================
# An early SKIP leaves a reviewable reason
# ===========================================================================


def test_the_outcome_record_carries_the_models_own_words():
    """The rationale was never missing from the trace — only from the upload."""

    import json

    from src.editorial_core.arp import (
        ArpOutcome,
        OutcomeRecord,
        OutcomeScope,
        StateCode,
    )
    from src.run.run_workspace import StageRecord

    outcome = OutcomeRecord(
        outcome=ArpOutcome.SKIP,
        state_code=StateCode.SOURCE_NOT_ELIGIBLE,
        scope=OutcomeScope.SIGNAL,
        scope_key="sig-1",
        reason="the role found no usable angle in this source",
    )
    record = StageRecord.model_construct(
        stage="S-00", scope_key="sig-1", outcomes=(outcome,)
    )

    written = json.loads(json.dumps(record.model_dump(mode="json")))
    assert written["outcomes"][0]["reason"] == (
        "the role found no usable angle in this source"
    )


def test_the_ledger_still_refuses_the_prose_and_keeps_the_category():
    """§3.3 is unchanged, deliberately: the summary carries no reason field.

    The repair preserves the words where the architecture puts them — the
    90-day workspace — instead of widening the public ledger to hold them.
    """

    from src.run.run_summary import ScopeOutcome

    assert "reason" not in ScopeOutcome.model_fields
    assert set(ScopeOutcome.model_fields) == {
        "scope", "scope_key", "outcome", "state_code", "category",
    }


def test_the_run_reports_the_model_and_the_workspace_it_used():
    """So the next run's report does not need the log to say which model ran."""

    code = executable_source(SCRIPT)
    assert "model             {model}" in code
    assert "workspace" in code


# ===========================================================================
# The audit: the seam list is proven exhaustive, not assumed
# ===========================================================================


def test_only_four_modules_on_the_canonical_path_reach_the_model_client():
    """The proof that the repaired seam list is complete.

    The instruction was explicit that the known list must not be assumed
    exhaustive. It is checked here instead: of everything the canonical run
    can reach, exactly four modules import the shared model client, and all
    four are given the canonical model. A fifth appearing later fails this.

    `src/editorial_core/` imports it **nowhere** — the thirteen stages take
    transports and never resolve a model themselves, which is why widening
    `NB_GOLDEN_ENGINE_MODEL` to the front of the chain is four injections and
    not an audit of thirteen stages.
    """

    import pathlib

    reachable = [
        pathlib.Path("src/run/golden_engine.py"),
        pathlib.Path("src/run/transports.py"),
        pathlib.Path("src/run/walking_skeleton.py"),
        pathlib.Path("src/editorial/source_eligibility.py"),
        pathlib.Path("src/research/assessment.py"),
        pathlib.Path("src/editorial/decision_lens_evaluator.py"),
        *pathlib.Path("src/editorial_core").rglob("*.py"),
    ]
    # Executable code only. `walking_skeleton.py` mentions `llm_client.chat`
    # in a comment about where #171 charges the budget, and a comment is not
    # an import — the fourth time in this chain that an absence assertion read
    # prose as code.
    users = {
        str(path)
        for path in reachable
        if "llm_client" in executable_source(path)
    }

    assert users == {
        "src/run/transports.py",
        "src/editorial/source_eligibility.py",
        "src/research/assessment.py",
        "src/editorial/decision_lens_evaluator.py",
    }, users

    core = [
        path for path in pathlib.Path("src/editorial_core").rglob("*.py")
        if "llm_client" in executable_source(path)
    ]
    assert core == [], core


def test_every_seam_the_engine_takes_is_either_model_backed_and_injected_or_not():
    """Each field of `GoldenEngineSeams`, accounted for.

    Five fields: the ten transports (already on `NB_GOLDEN_ENGINE_MODEL`), the
    three model-backed seams this repair injects, and research — which is
    Exa, not a model.
    """

    import dataclasses

    from src.run.golden_engine import GoldenEngineSeams
    from src.run.transports import GoldenEngineTransports

    assert {field.name for field in dataclasses.fields(GoldenEngineSeams)} == {
        "transports", "research", "eligibility", "evidence_judgment", "relevance",
    }
    assert len(dataclasses.fields(GoldenEngineTransports)) == 10

    code = executable_source(SCRIPT)
    # research is the one seam with no model, and it is not given one.
    assert "research=research" in code
    assert "ExaResearchAdapter" in code


# ===========================================================================
# The early-stop record
# ===========================================================================


def test_an_early_stop_persists_stage_outcome_code_model_and_rationale():
    from src.run.early_stop import early_stop_from_outcome

    stop = early_stop_from_outcome(
        run_id="bbe4867a",
        signal_id="6a72b2abcc466aab",
        stage="S-00",
        outcome={
            "outcome": "SKIP",
            "state_code": "source_not_eligible",
            "category": "contract_fit",
            "reason": "the source carries no documented mechanism",
        },
        model="gpt-6.1-sol",
    )

    entity = stop.as_entity()
    assert entity["stage"] == "S-00"
    assert entity["outcome"] == "SKIP"
    assert entity["state_code"] == "source_not_eligible"
    assert entity["category"] == "contract_fit"
    assert entity["model"] == "gpt-6.1-sol"
    assert entity["rationale"] == "the source carries no documented mechanism"
    assert entity["rationale_absent_reason"] is None
    assert stop.stop_id == "stop-bbe4867a-S-00"


def test_the_record_names_the_model_the_run_actually_used():
    """Handed over, never re-read from the environment.

    A record that consulted `NB_GOLDEN_ENGINE_MODEL` again could name a model
    the run did not use — which is exactly the class of defect this repair
    exists to remove.
    """

    import inspect

    from src.run import early_stop
    from src.run.walking_skeleton import _write_early_stop

    assert "model" in inspect.signature(_write_early_stop).parameters
    code = executable_source(pathlib.Path("src/run/early_stop.py"))
    for forbidden in ("environ", "getenv", "NB_GOLDEN_ENGINE_MODEL"):
        assert forbidden not in code, forbidden
    assert early_stop.NO_MODEL_INVOLVED


def test_no_rationale_is_invented_when_the_seam_produced_none():
    from src.run.early_stop import NO_RATIONALE_PRODUCED, early_stop_from_outcome

    for empty in (None, "", "   "):
        stop = early_stop_from_outcome(
            run_id="r1",
            signal_id="sig",
            stage="S-04",
            outcome={"outcome": "SKIP", "reason": empty},
            model="gpt-6.1-sol",
        )
        assert stop.rationale is None
        assert stop.rationale_absent_reason == NO_RATIONALE_PRODUCED


def test_a_code_decided_stop_names_no_model_rather_than_an_unknown_one():
    from src.run.early_stop import NO_MODEL_INVOLVED, early_stop_from_outcome

    stop = early_stop_from_outcome(
        run_id="r1", signal_id="sig", stage="S-07",
        outcome={"outcome": "SKIP", "reason": "no eligible destination"},
        model=None,
    )
    assert stop.model is None
    assert stop.model_absent_reason == NO_MODEL_INVOLVED


def test_a_record_that_both_states_and_omits_a_fact_is_refused():
    from src.run.early_stop import EarlyStop, EarlyStopError

    with pytest.raises(EarlyStopError, match="not true"):
        EarlyStop(
            run_id="r", signal_id="s", stage="S-00", outcome="SKIP",
            model="m", model_absent_reason="none", rationale="x",
        )
    with pytest.raises(EarlyStopError, match="neither recorded nor stated absent"):
        EarlyStop(run_id="r", signal_id="s", stage="S-00", outcome="SKIP")


def test_a_run_that_reaches_s14_writes_no_early_stop(tmp_path):
    """Nothing to explain, so nothing is written."""

    from src.run.walking_skeleton import run_golden_engine
    from tests.golden_engine_boundary import canonical_run

    run = canonical_run(tmp_path)
    ledger = tmp_path / "ledger"
    sealed = run_golden_engine(
        seams=run.seams,
        configuration=run.configuration,
        signal=run.signal,
        binding=run.binding,
        runs_root=run.runs_root,
        ledger_dir=ledger,
        started_at=run.now,
        now=run.now,
        model="gpt-6.1-sol",
    )

    assert sealed.execution.stopped_at is None
    assert sealed.early_stop_path is None
    assert not (ledger / "early_stops").exists()


def test_the_summary_still_carries_no_prose_and_the_stop_record_does():
    """§3.3 is intact: the widening happened beside the ledger's summary.

    The public summary keeps codes. The rationale lives in a record of its
    own, in the same ledger, exactly as the E-16 fingerprints do.
    """

    from src.run.early_stop import early_stop_ledger_path, early_stop_from_outcome
    from src.run.run_summary import ScopeOutcome

    assert "reason" not in ScopeOutcome.model_fields

    stop = early_stop_from_outcome(
        run_id="r1", signal_id="sig", stage="S-00",
        outcome={"outcome": "SKIP", "reason": "words"}, model="m",
    )
    path = early_stop_ledger_path(stop, client="never_blank", month="2026-10")
    assert path == "early_stops/never_blank/2026-10/stop-r1-S-00.json"


# ===========================================================================
# Shadow stays shadow
# ===========================================================================


def test_publication_image_and_s15_remain_unreachable_from_canonical_shadow():
    import pathlib as _pathlib

    source = _pathlib.Path("src/editorial_core/publication.py").read_text()
    for forbidden in (
        "publish(", "WixPublisher", "LinkedInPublisher", "PublicationGuard",
        "record_intent", "record_marker", "generate_image", "image_pipeline",
    ):
        assert forbidden not in source, forbidden

    from src.run.golden_engine import UNWIRED_STAGES, WIRED_STAGES

    assert WIRED_STAGES[-1] == "S-14"
    assert UNWIRED_STAGES == ("S-15",)

    code = executable_source(SCRIPT)
    for forbidden in ("Publisher", "image_pipeline", "generate_image", "S-15"):
        assert forbidden not in code, forbidden


def test_the_shadow_workflow_does_not_upload_the_whole_workspace():
    """The instruction preferred structured evidence over a blanket upload.

    An earlier draft of this repair uploaded `reports/editorial_runs/` as an
    artifact. It is removed: the rationale now reaches the durable ledger as a
    record, so preserving the whole runner workspace is no longer what makes an
    early stop reviewable.
    """

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    uploads = [
        step for step in workflow["jobs"]["shadow"]["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert uploads == []
