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

**Two production-contract defects this execution found.** Both are recorded here
as the behaviour they currently are, not as behaviour anyone wants, and each
test says what has to change for it to be inverted:

1. one re-entry spends the single declared ``L_boundary`` route twice, so the F-4
   sibling truth re-check — one of the four orchestration behaviours this
   module's subject exists for — is unreachable;
2. the canonical six-destination topology costs 50 logical model calls at its
   cheapest, and ``R1_MAX_CEILING`` is 40, so a complete canonical run cannot be
   sealed through ``run_golden_engine``.

Nothing here reaches a network, a provider, a credential or a publication, and
S-14 is not executed.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from src.editorial_core.arp import (
    CANONICAL_TOPOLOGY,
    ArpOutcome,
    AttemptCounterLedger,
    StateCode,
)
from src.editorial_core.destinations import Destination
from src.run.call_budget import R1_MAX_CEILING, WEDNESDAY_MAX_CEILING
from src.run.walking_skeleton import CANONICAL_DESTINATIONS, PASS_THROUGH_MARKER
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
# The two defects this execution found, recorded as what they are
# ===========================================================================


def test_one_reentry_spends_l_boundary_twice_so_f4_cannot_run():
    """RECORDED DEFECT. The F-4 sibling re-check is unreachable.

    One V-T02 failure is one logical re-entry, and the **same declared route** is
    spent for it twice. ``topology.py`` declares exactly one ``L_boundary`` route
    — ``S-13 → S-04`` on cause ``interpretation_inadmissible_or_unlisted``, scoped
    per unit, ``default_limit=1``. Both of these spend it:

    * ``text_check.py``'s ``_ROUTE_BY_CHECK["V-T02"]`` routes the failing check on
      ``L_boundary`` at ``scope_key=text.unit_id``;
    * ``interpretation_boundary.py``'s ``re_enter_boundary`` then calls
      ``counters.route`` again with ``source=REENTRY_SOURCE`` — which **is**
      ``"S-13"`` — the same cause, the same counter and the same
      ``scope_key=unit_id``.

    So the first spend consumes the only attempt and the re-entry it routes to is
    refused as ``boundary_reentry_exhausted``. The boundary is never re-committed,
    no sibling is ever put in question, and
    ``recheck_siblings_after_boundary_commit`` is never called — although this
    slice's own subject names the F-4 sibling re-check as one of the four
    behaviours it exists to orchestrate.

    Raising the limit is not a workaround; the test below shows why. Invert this
    test when one layer is made the owner of the route — either S-13 routes
    without spending, or the re-entry consumes the route S-13 already paid for.
    Both are stage semantics and neither is this slice's to choose.
    """

    ledger = Ledger()
    run = canonical_run(
        _tmp(), text_check=TextCheck(ledger, fails="V-T02", from_call=6)
    )
    execution, _, _ = execute(run)

    # Five siblings were accepted before the sixth text failed, which is exactly
    # the situation F-4 exists for.
    assert [item.value for item in execution.accepted] == [
        "facebook",
        "instagram",
        "linkedin",
        "telegram",
        "threads",
    ]
    route = _only(execution, StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION)
    assert (route.counter, route.attempt, route.route_target) == ("L_boundary", 1, "S-04")
    exhausted = _only(execution, StateCode.BOUNDARY_REENTRY_EXHAUSTED)
    assert exhausted.outcome is ArpOutcome.SKIP
    assert exhausted.counter == "L_boundary"
    # And the sibling re-check never happened: twelve text-check calls is six
    # texts × two questions, with no V-T02-only call beside them.
    assert run.ledger.count("text_check") == 12


def test_raising_the_boundary_limit_produces_an_undeclared_s04_to_s04_route():
    """RECORDED DEFECT, the other half. Configuration cannot rescue it.

    With ``L_boundary=2`` the second spend succeeds and returns the route table's
    ``S-13 → S-04`` record. The harness files that record on the StageRecord of
    the stage it is re-entering — ``trace.record(stage="S-04", …)`` — so the
    workspace sees an S-04 record whose ``route_target`` is ``"S-04"``, and the
    route table declares no such route. The run raises rather than writing it.
    """

    from src.run.golden_engine import execute_canonical_topology
    from src.run.call_budget import RunCallBudget
    from src.run.call_budget_arp import ArpCallBudget
    from src.run.run_workspace import RunWorkspace

    ledger = Ledger()
    run = canonical_run(
        _tmp(), text_check=TextCheck(ledger, fails="V-T02", from_call=6)
    )
    workspace = RunWorkspace.create(run.runs_root, run.run_context.run_id)
    with pytest.raises(Exception, match="S-04 → S-04 is not a declared REPLAN route"):
        execute_canonical_topology(
            workspace=workspace,
            run_context=run.run_context,
            seams=run.seams,
            configuration=run.configuration,
            signal=run.signal,
            binding=run.binding,
            budget=ArpCallBudget(
                RunCallBudget(WEDNESDAY_MAX_CEILING, hard_max=WEDNESDAY_MAX_CEILING)
            ),
            counters=AttemptCounterLedger(limits={"L_boundary": 2}),
            now=run.now,
        )


def test_a_complete_canonical_run_costs_more_calls_than_r1_admits(executed):
    """RECORDED DEFECT. ``run_golden_engine`` cannot seal a complete run.

    The arithmetic, and it is a floor rather than a typical cost — the clean run
    above re-plans nothing and still records:

    * 7 at signal and unit scope (S-00, S-01 ×2, S-02, S-04 ×2, S-06);
    * 4 per destination through planning (S-08, S-09, S-10, S-11) — 24;
    * 1 for barrier B1;
    * 3 per destination to write and check (S-12, S-13 ×2) — 18.

    That is 50. ``R1_MAX_CEILING`` is 40 and ``run_golden_engine`` builds
    ``RunCallBudget(call_budget_limit)`` with that as its hard maximum, so no
    admissible ``call_budget_limit`` covers the run; and ``RunSummary`` refuses a
    summary whose ``calls_total`` exceeds the limit, on the stated ground that
    the budget would have refused the call. The Wednesday role's declared 56
    covers it, but ``run_golden_engine`` takes no role and never reaches for it.

    Invert this test when the canonical run is given a ceiling that admits its
    own cost. Choosing that number is a spend decision and not this slice's.
    """

    _, execution, _, _ = executed
    recorded = sum(record.calls["count"] for record in execution.records)
    assert recorded == 50
    assert recorded > R1_MAX_CEILING
    assert recorded <= WEDNESDAY_MAX_CEILING


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
