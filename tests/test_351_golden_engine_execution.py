"""Issue #351: the canonical topology, executed. S-00 → S-13, over one signal.

Everything else in #351 proves the chain is *wired*: that every stage has an
importer, that the entry function is really called, that no pass-through
component can reappear. None of it proves the chain *runs* — a wiring can
satisfy every per-stage contract and still have two stages whose shapes do not
meet. This module runs it: one intake record enters S-00 and six checked texts
leave S-13, through the production ``execute_canonical_topology`` with the
production configuration, the production ledger and the production call budget.

**What is replaced and what is not.** Only the external, nondeterministic
boundaries — the research provider and the eleven model transports, which
production hands in as ``GoldenEngineSeams`` precisely so a run can state where
each came from. No stage is mocked, no typed entity is hand-authored, and
nothing writes into the run workspace but the engine. The doubles live in
``tests/golden_engine_boundary.py`` and each answers the request the production
stage composed, in terms of the identifiers that request carries.

**Two production-contract defects this execution found, and their repairs.**
Both were found by running the chain rather than by reading it, and both were
resolved by owner decision on 2026-10-01:

1. one re-entry spent the single declared ``L_boundary`` route twice, so the F-4
   sibling truth re-check was unreachable. The layer that authorizes the REPLAN
   now spends it once and passes that authorization forward; ``re_enter_boundary``
   verifies it and spends nothing, exactly as ``propose_strategies`` already does
   for ``L_strategy``. F-4 is exercised here, not asserted;
2. the canonical six-destination topology costs 50 logical model calls where
   ``R1_MAX_CEILING`` is 40, so no complete run could be sealed. The canonical
   path now has its own finite ceiling of 60 — a runaway guard and not a target
   spend — while the legacy default, ``R1_MAX_CEILING`` and Wednesday's 56 are
   untouched.

Nothing here reaches a network, a provider, a credential or a publication, and
S-14 is not executed.
"""

from __future__ import annotations

import inspect
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from src.editorial_core.arp import (
    CANONICAL_TOPOLOGY,
    ArpOutcome,
    StateCode,
)
from src.run.run_workspace import DeciderKind
from src.editorial_core.text_check import (
    EXECUTION_INSTRUCTIONS,
    SIBLING_RECHECK_INSTRUCTIONS,
    TRUTH_INSTRUCTIONS,
)
from src.run.call_budget import (
    DEFAULT_CEILING,
    GOLDEN_ENGINE_MAX_CEILING,
    R1_MAX_CEILING,
    WEDNESDAY_MAX_CEILING,
    CallBudgetConfigurationError,
    RunCallBudget,
)
from src.run.walking_skeleton import (
    CANONICAL_DESTINATIONS,
    PASS_THROUGH_MARKER,
    run_golden_engine,
    run_walking_skeleton,
)
from tests.golden_engine_boundary import (
    Ledger,
    TextCheck,
    canonical_run,
    execute,
)

#: The stages this slice executes. S-14 and S-15 are #308's and SL-12's, so the
#: set is the topology's own minus those two rather than a list written here: a
#: stage added to the canonical topology below S-14 makes this fail, which is the
#: point of deriving it.
_EXECUTED_STAGES = tuple(
    stage.stage_id
    for stage in CANONICAL_TOPOLOGY.stages
    if stage.stage_id not in {"S-14", "S-15"}
)


@pytest.fixture(scope="module")
def executed(tmp_path_factory):
    """One clean canonical run, executed once and read by several tests.

    Module-scoped because it is the same run every one of these tests is about:
    re-running it per test would not test anything more and would make the
    assertions about call counts assertions about six separate runs.
    """

    run = canonical_run(tmp_path_factory.mktemp("clean"))
    execution, workspace, budget = execute(run)
    return run, execution, workspace, budget


# ===========================================================================
# The composition runs
# ===========================================================================


def test_the_run_executes_every_stage_from_s00_to_s13(executed):
    """Every executed stage of the topology appears in the trace.

    Not "the trace is long" and not "it reached S-13": each stage the topology
    declares below S-14 recorded at least one StageRecord, so a stage silently
    skipped over is a failure here rather than a gap nobody notices.
    """

    _, execution, _, _ = executed
    reached = {record.stage for record in execution.records}
    assert reached == set(_EXECUTED_STAGES)
    assert execution.stopped_at is None


def test_every_canonical_destination_leaves_s13_with_an_accepted_text(executed):
    """Six destination lanes, six accepted texts, one unit, one signal."""

    _, execution, _, _ = executed
    accepted = [item.value for item in execution.accepted]
    # Compared as a set against the declared list, because the order a run
    # accepts in is the order it planned in and is not the order the list
    # declares; what is being claimed is that none of the six was left out.
    assert set(accepted) == set(CANONICAL_DESTINATIONS)
    assert len(accepted) == 6
    assert execution.unit_ids == ("unit-core-sig-351-exec",)
    assert execution.signal_ids == ("sig-351-exec",)


def test_the_run_asks_each_boundary_as_often_as_its_stage_declares(executed):
    """The call counts are the topology's arithmetic, not an incidental total.

    Seven signal- and unit-scoped calls, four planning calls per destination, one
    barrier, and three per destination to write and check. A double that was
    asked twice where the stage declares one call would change this, and so would
    a lane that quietly re-planned.
    """

    run, _, _, _ = executed
    assert dict(Counter(run.ledger.names)) == {
        # signal and unit scope
        "eligibility": 1,
        "research": 1,
        "evidence_judgment": 1,
        "lens": 1,
        "material": 1,
        "boundary": 2,  # S-04 generates, then probes
        "anchor": 1,
        # once per destination
        "strategy": 6,
        "ranking": 6,
        "segmentation": 6,
        "plan_check": 6,
        # once per unit
        "barrier": 1,
        # once per destination, and S-13 asks two questions per text version
        "writer": 6,
        "text_check": 12,
    }


def test_the_eleven_model_boundaries_are_each_asked_at_least_once(executed):
    """No seam is decorative.

    The run is only evidence that the chain composes if every boundary the
    thirteen stages declare was actually reached: a transport nothing asks is a
    stage whose model call this run did not exercise.
    """

    run, _, _, _ = executed
    for name in (
        "eligibility",
        "evidence_judgment",
        "lens",
        "material",
        "boundary",
        "anchor",
        "strategy",
        "ranking",
        "segmentation",
        "plan_check",
        "barrier",
        "writer",
        "text_check",
    ):
        assert run.ledger.count(name) >= 1, name


# ===========================================================================
# What the run recorded, and that the records are not fiction
# ===========================================================================


def test_every_consumed_entity_was_produced_by_an_earlier_stage(executed):
    """Producer → ID and version → consumer, for every input the run recorded.

    Walked in trace order, so an input that resolves only to an entity written
    *later* fails: the chain is a chain because each stage consumed something an
    earlier one produced, and this is the form of that claim that a reader can
    check without trusting any stage's own account of itself.
    """

    _, execution, _, _ = executed
    produced: set[tuple[str, str, Any]] = set()
    unresolved = []
    for record in execution.records:
        for ref in record.inputs:
            key = (ref.entity_type, ref.entity_id, ref.version)
            if key not in produced:
                unresolved.append((record.stage, record.scope_key, key))
        for ref in record.outputs:
            produced.add((ref.entity_type, ref.entity_id, ref.version))
    assert unresolved == []
    # The claim is only worth making if there were references to resolve.
    assert sum(len(record.inputs) for record in execution.records) >= 50


def test_the_typed_entities_the_records_name_are_on_disk(executed):
    """Each recorded output names a file the run actually wrote.

    A trace is cheap to produce and expensive to trust. This reads the workspace
    the engine sealed and requires an entity file for every output reference, so
    a record describing an artifact nobody wrote is a failure.
    """

    _, execution, workspace, _ = executed
    written = {
        path.name: path
        for path in workspace.run_dir.rglob("*.json")
    }
    assert len(written) >= 20
    produced = {
        ref.entity_type
        for record in execution.records
        for ref in record.outputs
    }
    # The eleven typed entities this slice's stages produce, by their map IDs.
    assert {"E-04", "E-05", "E-06", "E-09", "E-10", "E-11", "E-12", "E-13",
            "E-14", "E-15"} <= produced


def test_the_executed_run_contains_no_pass_through_anywhere(executed):
    """``PASS_THROUGH_MARKER`` appears in nothing this run produced.

    The marker is the anti-false-green lever: the pass-through harness writes it
    and the canonical one must not, so its absence from every record and every
    sealed file is the runtime half of the wiring tests' static claim.
    """

    _, execution, workspace, _ = executed
    serialized = json.dumps(
        [record.model_dump(mode="json") for record in execution.records]
    )
    assert PASS_THROUGH_MARKER not in serialized
    for path in workspace.run_dir.rglob("*"):
        if path.is_file():
            assert PASS_THROUGH_MARKER not in path.read_text(encoding="utf-8")


def test_the_run_charges_the_production_budget_for_the_calls_it_made(executed):
    """The budget was spent by the stages, not by the harness around them.

    38 spends against 50 model calls is not an inconsistency: a stage spends once
    per unit of work it is about to do, and S-04, S-11 and S-13 each make more
    than one call inside one. It is pinned here because the difference is what
    the recorded ceiling defect below is about.
    """

    run, execution, _, budget = executed
    recorded = sum(record.calls["count"] for record in execution.records)
    assert recorded == 50
    assert budget.used == 38
    assert len(run.ledger.calls) == recorded + 1  # the research retrieval beside them


# ===========================================================================
# The routes out of S-13
# ===========================================================================


def test_an_edit_class_finding_opens_exactly_one_edit_and_then_stops():
    """``L_edit`` routes S-13 → S-12 once per approved plan, and once only.

    V-T06 is the edit class, so a failing one sends the text back to be edited
    rather than re-planned. The second failure on the same approved plan has no
    attempt to spend — ``L_edit`` is counted at ``<plan_id>/v<version>`` — so the
    destination is skipped. Twelve writer calls for six destinations is the
    bound: one write and one edit each, never a third.
    """

    ledger = Ledger()
    run = canonical_run(_tmp(), text_check=TextCheck(ledger, fails="V-T06"))
    execution, _, _ = execute(run)

    assert execution.accepted == ()
    assert run.ledger.count("writer") == 12
    routes = [
        (record.scope_key, outcome.counter, outcome.route_target, outcome.outcome)
        for record in execution.records
        for outcome in record.outcomes
        if outcome.state_code is StateCode.TEXT_REQUIRES_EDIT
    ]
    assert [item[1] for item in routes] == ["L_edit"] * 12
    # Per destination: one REPLAN into S-12, then one SKIP with nothing left.
    assert [item[3] for item in routes].count(ArpOutcome.REPLAN) == 6
    assert [item[3] for item in routes].count(ArpOutcome.SKIP) == 6
    assert {item[2] for item in routes} == {"S-12", None}


def test_a_replan_class_finding_sends_the_destination_back_to_s08():
    """``L_strategy`` routes S-13 → S-08, and the destination is re-planned.

    V-T03 is the chain check and its failure is the plan's fault, not the
    prose's, so the route goes back to where the decision was made. The proof
    that the route was *taken* rather than recorded is that S-08 ran again:
    eleven strategy calls where a clean run makes six.
    """

    ledger = Ledger()
    run = canonical_run(_tmp(), text_check=TextCheck(ledger, fails="V-T03"))
    execution, _, _ = execute(run)

    assert execution.accepted == ()
    assert run.ledger.count("strategy") > 6
    replans = [
        outcome
        for record in execution.records
        for outcome in record.outcomes
        if outcome.state_code is StateCode.STRUCTURAL_TEXT_FAILURE
    ]
    assert len(replans) == 6
    assert {outcome.counter for outcome in replans} == {"L_strategy"}
    assert {outcome.route_target for outcome in replans} == {"S-08"}
    # The record the next attempt must be able to name: #304's `_authorized`
    # refuses a re-entry that cannot say which counter paid for it, at which
    # scope, so the attempt and the scope travel with the route.
    for outcome in replans:
        assert outcome.attempt == 1
        assert outcome.scope_key.startswith("unit-core-sig-351-exec/")


# ===========================================================================
# The boundary re-entry, and the F-4 sibling truth re-check behind it
# ===========================================================================


def test_a_boundary_reentry_spends_l_boundary_once_and_recommits():
    """One V-T02 failure, one `L_boundary`, one new boundary version.

    `§5.3` lists the `S-13 → S-04` edge once and gives it one unit-scoped
    attempt, so the route S-13 decided is the route S-04 is handed: S-13 records
    the REPLAN at attempt 1 of 1, and the re-entry verifies it rather than
    charging it again. The onward edge out of the new version is the second,
    separate route the same row declares — `L_strategy` back into S-08, because
    the anchor survived the commit.

    The sixth text is the one that fails, so five siblings are already accepted
    when the boundary moves. All six are accepted in the end: the causing
    destination is re-planned against version 2 and its new text passes.
    """

    ledger = Ledger()
    run = canonical_run(
        _tmp(), text_check=TextCheck(ledger, fails="V-T02", from_call=6)
    )
    execution, _, _ = execute(run)

    # Both edges of the row record the same state code, so they are told apart
    # by the stage that wrote each and the counter each spent — which is the
    # distinction the fix is about.
    spent = [
        outcome
        for record in execution.records
        if record.stage == "S-13"
        for outcome in record.outcomes
        if outcome.counter == "L_boundary"
    ]
    assert len(spent) == 1, "one V-T02 failure spends L_boundary exactly once"
    route = spent[0]
    assert route.state_code is StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION
    assert (route.attempt, route.limit) == (1, 1)
    assert route.route_target == "S-04"
    # The onward edge, on its own record and against its own counter.
    onward = [
        outcome
        for record in execution.records
        if record.stage == "S-04"
        for outcome in record.outcomes
        if outcome.outcome is ArpOutcome.REPLAN
    ]
    assert len(onward) == 1
    assert onward[0].counter == "L_strategy"
    assert onward[0].route_target == "S-08"
    # Two S-04 records: the first boundary, and the version the re-entry made.
    assert sum(1 for record in execution.records if record.stage == "S-04") == 2
    assert len(set(execution.accepted)) == 6
    # Three calls to the boundary: generate, probe, and the re-entry's test.
    assert run.ledger.count("boundary") == 3


def test_the_f4_sibling_recheck_runs_one_vt02_only_call_per_accepted_sibling():
    """§5.4, defect F-4: the half no stage can do.

    A text accepted ten minutes earlier is still accepted against the boundary
    version the commit replaced, and nothing else would catch it — S-11's code
    checks re-run on the plans and the S-12 precondition compares versions, but a
    text that already passed S-13 has no reason to be looked at again unless this
    does it. So after the commit, every already-accepted sibling is re-checked:
    **one call each, V-T02 only**, routed by the production
    `SIBLING_RECHECK_INSTRUCTIONS` rather than by call order.

    Five siblings were accepted before the sixth text failed, so five re-checks.
    Re-running the execution call would pay for an answer that cannot have
    changed, which is why the count is five and not ten.
    """

    ledger = Ledger()
    checker = TextCheck(ledger, fails="V-T02", from_call=6)
    run = canonical_run(_tmp(), text_check=checker)
    execution, _, _ = execute(run)

    assert checker.answered[SIBLING_RECHECK_INSTRUCTIONS] == 5
    # The six first texts, plus the re-planned destination's second text.
    assert checker.answered[TRUTH_INSTRUCTIONS] == 7
    assert checker.answered[EXECUTION_INSTRUCTIONS] == 7
    assert len(set(execution.accepted)) == 6


def test_a_commit_re_establishes_every_plan_of_the_unit_before_the_barrier():
    """§5.4: the code half of F-4 covers the whole unit, not one lane.

    "On a new boundary version, S-11's code checks (V-P02, chain) re-run on
    **every approved plan of the unit** (0 model calls)." The barrier compares
    siblings, so a round that admitted a plan approved against the version the
    commit replaced would carry a stale approval past the barrier — which is the
    defect itself. The re-checks are code and cost nothing, so they are visible
    as S-11 records that made no call.
    """

    ledger = Ledger()
    run = canonical_run(
        _tmp(), text_check=TextCheck(ledger, fails="V-T02", from_call=6)
    )
    execution, _, _ = execute(run)

    free = [
        record
        for record in execution.records
        if record.stage == "S-11" and record.calls["count"] == 0
    ]
    assert free, "a boundary commit re-establishes approvals without paying"
    assert all(
        record.created_by.decider is DeciderKind.CODE for record in free
    )
    # Every barrier round that ran, ran against plans whose approval held: the
    # run reached accepted texts for all six, which it could not have done if a
    # stale approval had reached the barrier.
    assert len(set(execution.accepted)) == 6


# ===========================================================================
# The run seals inside the Golden Engine's own ceiling
# ===========================================================================


def test_a_complete_canonical_run_seals_inside_the_golden_engine_ceiling(tmp_path):
    """`run_golden_engine` writes a manifest, verifies and summarizes the run.

    The ceiling is the canonical path's own: Step 2 §0.3 records 40 as "AS-IS:
    the current engine's ceiling", and §6 puts the six-destination minimum at 44
    and the normal case at 61, so `R1_MAX_CEILING` was never this run's number.
    A clean run records 50 — §6's minimum of 44 plus one S-09 ranking per
    destination, which the minimum assumes away — and `RunSummary` accepts it
    because the limit it is compared against is now 60 (owner decision,
    2026-10-01): a runaway guard, not a target spend.
    """

    run = canonical_run(tmp_path)
    sealed = run_golden_engine(
        seams=run.seams,
        configuration=run.configuration,
        signal=run.signal,
        binding=run.binding,
        runs_root=run.runs_root,
        started_at=run.now,
        now=run.now,
    )

    summary = sealed.summary
    assert summary.calls_total == 50
    assert summary.call_budget_limit == GOLDEN_ENGINE_MAX_CEILING == 60
    assert summary.calls_total > R1_MAX_CEILING, (
        "the canonical run does not fit the legacy ceiling, which is why it has "
        "one of its own"
    )
    assert sum(entry.calls for entry in summary.stage_calls) == summary.calls_total
    assert sealed.verification.verified_stage_records == len(sealed.records)
    assert sealed.summary_path.exists()
    assert len(set(sealed.execution.accepted)) == 6


def test_the_legacy_and_wednesday_ceilings_are_untouched():
    """Three ceilings, three paths, and no path inherits another's.

    The Golden Engine's 60 is reached only by naming it. `DEFAULT_CEILING` and
    `R1_MAX_CEILING` stay 40 for every legacy caller, Wednesday's exception stays
    56, and a limit above a path's own hard maximum is refused rather than
    clamped — the posture `NB_OPENAI_MAX_RETRIES` established.
    """

    assert (DEFAULT_CEILING, R1_MAX_CEILING) == (40, 40)
    assert WEDNESDAY_MAX_CEILING == 56
    assert GOLDEN_ENGINE_MAX_CEILING == 60
    for limit, hard_max in (
        (41, R1_MAX_CEILING),
        (57, WEDNESDAY_MAX_CEILING),
        (61, GOLDEN_ENGINE_MAX_CEILING),
    ):
        with pytest.raises(CallBudgetConfigurationError, match="must be between"):
            RunCallBudget(limit, hard_max=hard_max)
    # The pass-through harness keeps the legacy default; only the canonical
    # entrypoint reaches for 60.
    assert (
        inspect.signature(run_golden_engine).parameters["call_budget_limit"].default
        == GOLDEN_ENGINE_MAX_CEILING
    )
    assert (
        inspect.signature(run_walking_skeleton).parameters["call_budget_limit"].default
        == DEFAULT_CEILING
    )


# ===========================================================================
# The scenario cannot pass by answering nothing
# ===========================================================================


def test_the_scenario_answers_every_transport_the_bundle_declares():
    """A new transport must be answered here, not silently left unanswered.

    Without this, a transport added to ``GoldenEngineTransports`` would reach the
    stages as ``None`` and the stage would fail for want of a double rather than
    for want of a contract — a red test that says nothing about the composition.
    """

    from src.run.transports import GoldenEngineTransports

    run = canonical_run(_tmp())
    bound = {
        name: getattr(run.seams.transports, name)
        for name in GoldenEngineTransports.__dataclass_fields__
    }
    assert all(value is not None for value in bound.values())
    assert len(bound) == 10


def test_each_boundary_answers_the_request_it_was_given(executed):
    """The doubles are request-answering, which is what keeps them honest.

    The anchor's answer names a candidate index the request offered; the strategy
    answers cite the anchor's own leading material. Asserted over the recorded
    requests so that a double drifting to a constant payload fails here rather
    than producing a run that agrees with nothing.
    """

    run, _, _, _ = executed
    anchor_request = json.loads(run.ledger.requests("anchor")[0])
    offered = {item["index"] for item in anchor_request["candidates"]}
    assert offered == {1, 2}
    for raw in run.ledger.requests("strategy"):
        asked = json.loads(raw)
        leading = {item["ref"] for item in asked["anchor"]["leading_material"]}
        assert leading == {"evidence-ups-investment", "evidence-ups-demand"}


# ===========================================================================
# Helpers
# ===========================================================================

_counter = Counter()


def _tmp() -> Path:
    """A fresh temporary root per scenario, named so failures are locatable."""

    import tempfile

    _counter["runs"] += 1
    return Path(tempfile.mkdtemp(prefix=f"nb351-{_counter['runs']}-"))


def _only(execution, state_code: StateCode):
    """The one outcome of ``state_code`` this run recorded."""

    found = [
        outcome
        for record in execution.records
        for outcome in record.outcomes
        if outcome.state_code is state_code
    ]
    assert len(found) == 1, (state_code, len(found))
    return found[0]
