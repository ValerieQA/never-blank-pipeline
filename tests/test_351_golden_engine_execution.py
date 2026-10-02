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

**Three production-contract defects this execution found, and their repairs.**
All three were found by running the chain rather than by reading it, and all
three were resolved by owner decision:

1. one re-entry spent the single declared ``L_boundary`` route twice, so the F-4
   sibling truth re-check was unreachable. The layer that authorizes the REPLAN
   now spends it once and passes that authorization forward; ``re_enter_boundary``
   verifies it and spends nothing, exactly as ``propose_strategies`` already does
   for ``L_strategy``. F-4 is exercised here, not asserted;
2. the canonical six-destination topology costs more than ``R1_MAX_CEILING``
   admits, so no complete run could be sealed. The canonical path now has its own
   finite ceiling of 60 — a runaway guard and not a target spend — while the
   legacy default, ``R1_MAX_CEILING`` and Wednesday's 56 are untouched;
3. that ceiling bounded the wrong thing. §0.3 gives the run counter one consumer,
   "Every model call", but the canonical path never activated the budget, so
   ``llm_client.chat`` charged nothing and the only consumer was the stage-side
   wrap — which spends once per unit of work while S-04, S-11 and S-13 each make
   more than one call inside one. 50 calls were being counted as 38. The wrap now
   **asks** whether the next call is affordable and the calls do the charging, the
   canonical entrypoint activates its budget, and a refusal that arrives from
   inside a transport becomes §0.4's ARP outcomes instead of an exception out of a
   run that has already accepted work. Actual calls and recorded calls are now
   the same number.

**Absent inputs.** The two the issue names are regressions here: a run with no
Reference Library approves every plan with empty exemplars **and** one
``REFERENCE_LIBRARY_UNAVAILABLE`` degrade per destination, and the client's real
library — which is present — records none, so the degrade is a fact about the
input rather than noise. V-T05 against an empty prior set passes as a ``code``
check that ran, and the same check given a real prior refuses that destination's
publication, so the empty set is an answer and not a bypass.

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
    RUN_CALL_BUDGET_COUNTER,
    ArpOutcome,
    StateCode,
)
from src.editorial_core.arp import OutcomeScope
import re

from src.editorial_core.destinations import Destination
from src.editorial_core.text_check import (
    CheckClass,
    CheckMethod,
    CheckOutcome,
    PriorPublication,
    TextFingerprint,
    TextResult,
    normalized_sentence,
    shingles,
)
from src.run.run_inputs import NO_REFERENCE_LIBRARY, InputKind, run_inputs
from src.run.run_workspace import DeciderKind
from src.editorial_core.text_check import (
    EXECUTION_INSTRUCTIONS,
    SIBLING_RECHECK_INSTRUCTIONS,
    TRUTH_INSTRUCTIONS,
)
from src.run.call_budget import (
    DEFAULT_CEILING,
    active_call_budget,
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
#: The stages this engine executes. S-15 is SL-12's, so the set is the
#: topology's own minus that one rather than a list written here: a stage added
#: to the canonical topology makes this fail, which is the point of deriving it.
#: S-14 joined in #308, in shadow.
_EXECUTED_STAGES = tuple(
    stage.stage_id
    for stage in CANONICAL_TOPOLOGY.stages
    if stage.stage_id != "S-15"
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


def test_the_run_executes_every_stage_from_s00_to_s14(executed):
    """Every executed stage of the topology appears in the trace.

    Not "the trace is long" and not "it reached the end": each stage the
    topology declares below S-15 recorded at least one StageRecord, so a stage
    silently skipped over is a failure here rather than a gap nobody notices.
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


def test_the_ceiling_bounds_actual_model_calls_one_for_one(executed):
    """The hard ceiling counts calls, and the trace counts the same calls.

    §0.3 names the run counter's consumer — "Every model call" — and that charge
    is made inside ``llm_client.chat`` before the provider is reached. So the
    number the ceiling bounds and the number the trace records are the same
    number, and this asserts they are equal rather than merely close. Before the
    repair they were 50 and 38: the stages were charging once per unit of work
    while S-04, S-11 and S-13 each make more than one call inside one, so the
    ceiling bounded units of work and not calls (#351 review).
    """

    run, execution, _, budget = executed
    recorded = sum(record.calls["count"] for record in execution.records)
    assert recorded == 50
    assert budget.used == recorded, (
        "every recorded call was charged, and nothing was charged twice"
    )
    assert budget.limit == GOLDEN_ENGINE_MAX_CEILING
    # One boundary invocation more than the charge: the research retrieval, which
    # §6 excludes — "Model calls only. Retrieval providers, publishers and the
    # label job are not counted."
    assert len(run.ledger.calls) == recorded + 1
    assert run.ledger.count("research") == 1


def test_the_canonical_entrypoint_activates_the_budget_it_built(tmp_path):
    """Without activation the ceiling would bound nothing on this path.

    ``charge_active_call_budget`` charges the budget in the ``ContextVar`` and
    no other, so a run that never activates its own is a run whose calls are
    charged to nobody. Asserted from inside the run, through a transport that
    reads the active budget at the moment it is called — which is where
    ``chat`` reads it.
    """

    seen: list[object] = []
    run = canonical_run(tmp_path)

    class _Watching:
        """Stands where `chat` stands: reads the active budget at call time."""

        def complete(self, *, instructions: str, request: str) -> str:
            seen.append(active_call_budget())
            # A transport failure is a recorded state and not a crash (S-00
            # normalizes it), so this neither stops the run nor hides the answer.
            raise RuntimeError("the question here is the budget, not the verdict")

    object.__setattr__(run.seams, "eligibility", _Watching())
    run_golden_engine(
        seams=run.seams,
        configuration=run.configuration,
        signal=run.signal,
        binding=run.binding,
        runs_root=run.runs_root,
        # Isolated, like `runs_root` beside it. Without it `write_run_summary`
        # falls back to the repository's own `data/editorial/runs/` tree — which
        # `.gitignore` deliberately re-includes — so the run summary lands in the
        # working tree and the next commit picks it up. Two PRs did (#231, #370).
        ledger_dir=run.runs_root.parent / "ledger",
        started_at=run.now,
        now=run.now,
    )

    assert seen, "the run reached a transport"
    assert seen[0] is not None, "the run's own budget was active at the call"
    assert seen[0].limit == GOLDEN_ENGINE_MAX_CEILING


def test_the_call_past_the_ceiling_is_refused_before_the_boundary_is_reached(
    tmp_path,
):
    """§0.4.1: the call that would exceed the budget is not made.

    The ceiling is set to the cost of the run's first few calls, so a later one
    is refused. The refusal is raised by ``charge_active_call_budget`` before the
    double produces an answer — mirroring ``chat``, which charges before
    ``client.chat.completions.create`` — so the boundary that was about to be
    asked records no request for the refused call. #171's own
    ``test_refusal_happens_before_any_transport_is_invoked`` proves the same
    property of the production transport; this proves the canonical path is
    inside it.
    """

    run = canonical_run(tmp_path)
    execution, _, budget = execute(run, limit=5)

    assert budget.used == 5, "the ceiling was reached and never passed"
    assert len(run.ledger.calls) == 6, (
        "five charged calls, plus the uncharged research retrieval, and nothing "
        "for the refused one"
    )
    # Fail-closed: a run that cannot pay stops with recorded outcomes rather
    # than with an exception, and names no accepted text.
    assert execution.accepted == ()
    states = {
        outcome.state_code
        for record in execution.records
        for outcome in record.outcomes
    }
    assert StateCode.BUDGET_EXHAUSTED in states


def test_exhaustion_preserves_accepted_work_and_skips_the_rest(tmp_path):
    """§0.4.2–0.4.4, over a real run rather than over the wrap alone.

    A ceiling that admits some destinations and not the rest: the ones that
    reached an accepted text keep it, the destination whose next call was refused
    is skipped, and the destinations that never started are skipped in reverse
    order — the ones others link to and the ones actually published are the last
    to be given up. Nothing raises out of the run.
    """

    run = canonical_run(tmp_path)
    execution, _, budget = execute(run, limit=45)

    assert budget.exhausted
    assert execution.accepted, "work already paid for and accepted is kept"
    assert len(set(execution.accepted)) < 6, "not every destination could be served"
    exhausted = [
        outcome
        for record in execution.records
        for outcome in record.outcomes
        if outcome.state_code is StateCode.BUDGET_EXHAUSTED
    ]
    assert exhausted, "the stop is recorded as ARP outcomes"
    assert {outcome.outcome for outcome in exhausted} == {ArpOutcome.SKIP}
    assert {outcome.counter for outcome in exhausted} == {RUN_CALL_BUDGET_COUNTER}
    # No destination is both accepted and skipped for budget.
    skipped = {outcome.scope_key for outcome in exhausted}
    assert not ({item.value for item in execution.accepted} & skipped)


# ===========================================================================
# The routes out of S-13
# ===========================================================================


def test_an_edit_class_finding_opens_exactly_one_edit_and_then_stops():
    """``L_edit`` routes S-13 → S-12 once per approved plan, and once only.

    V-T06 is the edit class, so a failing one sends the text back to be edited
    rather than re-planned. It is failed for the **first** text only: a scenario
    that failed all six would cost more than the run's own ceiling, and the guard
    rather than the route would then be what the test measured.

    One extra write and two extra checks is the whole of the loop — seven writer
    calls for six destinations, fourteen text checks for seven text versions —
    and the edited text is accepted, which is what makes it an edit and not a
    re-plan.
    """

    ledger = Ledger()
    run = canonical_run(
        _tmp(), text_check=TextCheck(ledger, fails="V-T06", from_call=1)
    )
    execution, _, budget = execute(run)

    assert run.ledger.count("writer") == 7
    assert run.ledger.count("text_check") == 14
    edits = [
        outcome
        for record in execution.records
        for outcome in record.outcomes
        if outcome.state_code is StateCode.TEXT_REQUIRES_EDIT
    ]
    assert len(edits) == 1
    assert (edits[0].counter, edits[0].attempt, edits[0].limit) == ("L_edit", 1, 1)
    assert edits[0].route_target == "S-12"
    assert edits[0].outcome is ArpOutcome.REPLAN
    # The edit answered the finding, so every destination still ends accepted.
    assert len(set(execution.accepted)) == 6
    assert budget.used == sum(
        record.calls["count"] for record in execution.records
    )


def test_a_replan_class_finding_sends_the_destination_back_to_s08():
    """``L_strategy`` routes S-13 → S-08, and the destination is re-planned.

    V-T03 is the chain check and its failure is the plan's fault, not the
    prose's, so the route goes back to where the decision was made. Failed for
    the first text only, for the reason the edit test gives. The proof that the
    route was *taken* rather than recorded is that S-08 ran again: seven strategy
    rounds where a clean run makes six, and the re-planned destination ends
    accepted on its new plan.
    """

    ledger = Ledger()
    run = canonical_run(
        _tmp(), text_check=TextCheck(ledger, fails="V-T03", from_call=1)
    )
    execution, _, budget = execute(run)

    assert run.ledger.count("strategy") == 7
    replans = [
        outcome
        for record in execution.records
        for outcome in record.outcomes
        if outcome.state_code is StateCode.STRUCTURAL_TEXT_FAILURE
    ]
    assert len(replans) == 1
    assert replans[0].counter == "L_strategy"
    assert replans[0].route_target == "S-08"
    # The record the next attempt must be able to name: #304's `_authorized`
    # refuses a re-entry that cannot say which counter paid for it, at which
    # scope, so the attempt and the scope travel with the route.
    assert replans[0].attempt == 1
    assert replans[0].scope_key.startswith("unit-core-sig-351-exec/")
    assert len(set(execution.accepted)) == 6
    assert budget.used == sum(
        record.calls["count"] for record in execution.records
    )


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
    when the boundary moves, which is the situation F-4 exists for. The causing
    destination is then re-planned against version 2 — and this scenario runs the
    canonical ceiling out, so the five accepted siblings are preserved (§0.4.4)
    and the re-planned destination is the one the budget gives up. That is two
    behaviours in one run, and both are asserted.
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
    # Three calls to the boundary: generate, probe, and the re-entry's test.
    assert run.ledger.count("boundary") == 3
    # The five siblings accepted before the commit are kept.
    assert len(set(execution.accepted)) == 5


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
    changed, which is why the count is five and not ten — and why the re-check is
    one call per sibling beside the six full checks, not a seventh full check.
    """

    ledger = Ledger()
    checker = TextCheck(ledger, fails="V-T02", from_call=6)
    run = canonical_run(_tmp(), text_check=checker)
    execution, _, _ = execute(run)

    assert checker.answered[SIBLING_RECHECK_INSTRUCTIONS] == 5
    assert checker.answered[TRUTH_INSTRUCTIONS] == 6
    assert checker.answered[EXECUTION_INSTRUCTIONS] == 6
    assert len(set(execution.accepted)) == 5


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
    # run re-planned the causing destination and kept the five accepted ones,
    # which it could not have done if a stale approval had reached the barrier —
    # that raises rather than passing.
    assert len(set(execution.accepted)) == 5


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
        # Isolated, like `runs_root` beside it. Without it `write_run_summary`
        # falls back to the repository's own `data/editorial/runs/` tree — which
        # `.gitignore` deliberately re-includes — so the run summary lands in the
        # working tree and the next commit picks it up. Two PRs did (#231, #370).
        ledger_dir=run.runs_root.parent / "ledger",
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
# Absent inputs, stated as absent rather than passed over
# ===========================================================================


def test_no_reference_library_degrades_with_the_record_that_says_so(tmp_path):
    """The soft input §3 lets degrade, degrading — and saying it did.

    §3 lists the Reference Library among S-11's inputs and lets it be absent,
    which is exactly why its absence has to be *recorded*: a plan approved with
    no exemplar and no outcome is indistinguishable from a plan whose library
    answered with nothing, and the whole soft-input rule rests on that
    distinction. So a run with no library at all approves every plan with empty
    exemplars **and** one ``DEGRADE`` per destination carrying
    ``REFERENCE_LIBRARY_UNAVAILABLE``, and the run still reaches six accepted
    texts, because a soft input is not a gate.
    """

    run = canonical_run(tmp_path, library=None)
    assert run.configuration.library is None
    execution, workspace, _ = execute(run)

    degraded = [
        outcome
        for record in execution.records
        for outcome in record.outcomes
        if outcome.state_code is StateCode.REFERENCE_LIBRARY_UNAVAILABLE
    ]
    assert len(degraded) == 6, "one per destination, not one per run"
    assert {outcome.outcome for outcome in degraded} == {ArpOutcome.DEGRADE}
    assert {outcome.scope for outcome in degraded} == {OutcomeScope.DESTINATION}
    assert all("no Reference Library" in (outcome.reason or "") for outcome in degraded)
    assert len(set(execution.accepted)) == 6

    approved = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(workspace.run_dir.rglob("plan-*.json"))
    ]
    assert approved, "the run approved plans"
    assert all(item["exemplars"] == [] for item in approved)


def test_a_library_that_answered_with_nothing_is_not_an_absent_library(tmp_path):
    """The distinction the record exists for, asserted from both sides.

    The client's real library is present and holds items, so the canonical run
    records no ``REFERENCE_LIBRARY_UNAVAILABLE`` at all. Without this the test
    above would pass just as well against a run that always degrades, and the
    DEGRADE would be noise rather than a fact about the input.
    """

    run = canonical_run(tmp_path)
    library = run.configuration.library
    assert library is not None and library.available
    execution, _, _ = execute(run)

    assert not [
        outcome
        for record in execution.records
        for outcome in record.outcomes
        if outcome.state_code is StateCode.REFERENCE_LIBRARY_UNAVAILABLE
    ]


def test_an_absent_reference_library_is_declared_in_the_run_inputs():
    """§4.1: a run that read no library states that, rather than omitting it."""

    entry = run_inputs().reference_library
    assert entry.kind is InputKind.REFERENCE_LIBRARY
    assert entry.identities == ()
    assert entry.digest is None
    assert entry.absent_reason == NO_REFERENCE_LIBRARY


def test_no_prior_publication_makes_vt05_pass_rather_than_unanswered(executed):
    """V-T05 against an empty prior set is an answer, not an absence.

    "An empty prior set is the honest first-run answer: the check ran and found
    nothing to compare against, which is a pass and not an absence of a check."
    So every text version records V-T05 as a ``code`` check that passed — never
    ``NOT_ANSWERED``, which is what a check nobody ran would be.
    """

    _, _, workspace, _ = executed
    verdicts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(workspace.run_dir.rglob("text_*.json"))
    ]
    assert len(verdicts) == 6
    for verdict in verdicts:
        results = {item["check_id"]: item for item in verdict["checks"]}
        assert results["V-T05"]["result"] == "pass"
        assert not results["V-T05"].get("findings")
        # V-T04 beside it: the other code check over the core, so a verdict
        # whose code half did not run at all would fail here too.
        assert results["V-T04"]["result"] == "pass"


def test_vt05_still_refuses_a_republication_when_a_prior_exists():
    """The empty prior set is an answer, not a bypass.

    Two passes over the real path. The first produces the texts and the trace
    records each one's content digest, which is what V-T05 compares. The second
    is given one of them back as a prior E-16 — which is what a prior *is*, the
    fingerprint of something this client already published — and V-T05 refuses
    that destination's publication while the other five are unaffected.

    Nothing is hand-authored: the digest comes from the first run's own trace, so
    the check is asked about a text the engine really wrote.
    """

    first = canonical_run(_tmp())
    first_execution, _, _ = execute(first)
    published = {
        record.scope_key.rsplit("/", 1)[-1]: ref.digest
        for record in first_execution.records
        if record.stage == "S-13"
        for ref in record.inputs
        if ref.entity_type == "E-15"
    }
    assert len(published) == 6

    prior = PriorPublication(
        fingerprint_id="fp-351-prior",
        destination=Destination.WIX,
        content_digest=published["wix"],
    )
    second = canonical_run(_tmp())
    second_execution, _, _ = execute(second, priors=(prior,))

    accepted = {item.value for item in second_execution.accepted}
    assert "wix" not in accepted, "the republication is refused"
    assert len(accepted) == 5, "only the destination with a prior is affected"
    refused = [
        outcome
        for record in second_execution.records
        for outcome in record.outcomes
        if outcome.state_code is StateCode.NEAR_EXACT_REPUBLICATION
    ]
    assert len(refused) == 1
    assert refused[0].outcome is ArpOutcome.SKIP
    assert refused[0].scope is OutcomeScope.PUBLICATION
    assert refused[0].counter is None, "V-T05 is terminal and spends no counter"


# ===========================================================================
# V-S05 on the canonical path: the producer is wired, both ways
# ===========================================================================


def _v_s05(verdict):
    """The one V-S05 hint on a verdict this run produced."""

    hints = [item for item in verdict.hints if item.check_id == "V-S05"]
    assert len(hints) == 1, [item.check_id for item in verdict.hints]
    return hints[0]


def _projected(entity: dict) -> TextFingerprint:
    """A prior E-16 projected from a text a previous canonical run published.

    Exactly what a harness would do with a real fingerprint, and done with the
    production helpers so both sides of the comparison are built the same way.
    The body and the part names come out of the run's own sealed E-15; nothing is
    authored, and no production fingerprint source is introduced.
    """

    body = entity["body"]
    sentences = [
        part for part in re.split(r"(?<=[.!?])\s+", body.strip()) if part.strip()
    ]
    return TextFingerprint(
        fingerprint_id="fp-351-portfolio",
        destination=Destination(entity["destination"]),
        reader_path=tuple(
            normalized_sentence(item["name"]) for item in entity["segments"]
        ),
        opening=normalized_sentence(sentences[0]),
        ending=normalized_sentence(sentences[-1]),
        shingles=shingles(body),
    )


def test_v_s05_is_present_and_evaluated_on_every_canonical_verdict(executed):
    """The producer is wired, and an empty portfolio is answered not skipped.

    Before this, `check_text`'s `soft_hints` parameter had no caller anywhere in
    ``src/`` and every canonical TextVerdict carried ``hints: []`` — the check was
    in the register, named in S-13's contract, and never applied. Now every
    accepted text carries it, recorded as the soft code check that it is, with the
    one finding that says the comparison ran and found nothing.
    """

    _, execution, workspace, _ = executed

    assert len(execution.verdicts) == 6
    for verdict in execution.verdicts:
        hint = _v_s05(verdict)
        assert hint.check_class is CheckClass.SOFT
        assert hint.method is CheckMethod.CODE
        assert hint.result is CheckOutcome.PASS, "evaluated, not unanswered"
        assert hint.route is None
        assert len(hint.findings) == 1
        assert "found nothing" in hint.findings[0].detail
        assert "over 0 prior publication(s)" in hint.findings[0].detail
        # I-12, enforced by TextVerdict itself: never among the deciding checks.
        assert "V-S05" not in {item.check_id for item in verdict.checks}

    assert len(set(execution.accepted)) == 6, "a soft check is not a gate"
    # And it is on the sealed entity too, which records hints by check ID.
    for path in sorted(workspace.run_dir.rglob("text_*.json")):
        entity = json.loads(path.read_text(encoding="utf-8"))
        assert entity["hints"] == ["V-S05"]


def test_v_s05_reports_separate_hints_against_a_prior_canonical_publication():
    """Two passes: the first publishes, the second finds itself in the portfolio.

    The prior is projected from the first run's own sealed E-15 and supplied
    through the canonical input seam, exactly as the V-T05 prior test supplies
    `PriorPublication`. The dimensions stay separate — the record requires it —
    and nothing about the verdict changes: V-S05 blocks nothing, routes nowhere,
    spends no counter and costs no call.
    """

    first = canonical_run(_tmp())
    first_execution, first_workspace, _ = execute(first)
    published = {
        json.loads(path.read_text(encoding="utf-8"))["destination"]: json.loads(
            path.read_text(encoding="utf-8")
        )
        for path in sorted(first_workspace.run_dir.rglob("txt-*.json"))
    }
    assert "wix" in published, sorted(published)
    prior = _projected(published["wix"])

    second = canonical_run(_tmp())
    execution, _, _ = execute(second, text_portfolio=(prior,))

    wix = next(item for item in execution.verdicts if item.destination is Destination.WIX)
    hint = _v_s05(wix)
    details = [finding.detail for finding in hint.findings]
    assert details, "a matching prior produces at least one similarity hint"
    for dimension in ("the reader path", "the opening", "the ending", "n-gram overlap"):
        assert sum(dimension in detail for detail in details) <= 1, dimension
    assert sum(
        any(dimension in detail for detail in details)
        for dimension in ("the reader path", "the opening", "the ending", "n-gram overlap")
    ) == len(details), "every finding names exactly one dimension"
    assert all("fp-351-portfolio" in detail for detail in details)
    assert all("never a reason to block, edit or replan" in detail for detail in details)

    # Nothing about the decision moved.
    assert wix.result is TextResult.ACCEPTED
    assert wix.route is None and wix.counter is None and wix.outcome is None
    assert Destination.WIX in execution.accepted
    assert len(set(execution.accepted)) == 6
    # The five destinations the prior is not about are unaffected.
    for verdict in execution.verdicts:
        if verdict.destination is Destination.WIX:
            continue
        assert "over 0 prior publication(s)" in _v_s05(verdict).findings[0].detail


def test_v_s05_adds_no_model_call_to_the_canonical_run():
    """`method: code`, proved over the whole run rather than over one verdict.

    The same six-destination run with and without a portfolio records the same 50
    calls and charges the same 50 units, so the soft check costs nothing against
    the ceiling it now runs under.
    """

    without = canonical_run(_tmp())
    empty_execution, _, empty_budget = execute(without)
    recorded_empty = sum(record.calls["count"] for record in empty_execution.records)

    first = canonical_run(_tmp())
    _, first_workspace, _ = execute(first)
    entity = json.loads(
        sorted(first_workspace.run_dir.rglob("txt-*.json"))[0].read_text(
            encoding="utf-8"
        )
    )

    with_prior = canonical_run(_tmp())
    loaded_execution, _, loaded_budget = execute(
        with_prior, text_portfolio=(_projected(entity),)
    )
    recorded_loaded = sum(
        record.calls["count"] for record in loaded_execution.records
    )

    assert recorded_empty == recorded_loaded == 50
    assert empty_budget.used == loaded_budget.used == 50


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
