"""Issue #292: the Autonomous Resolution Protocol as mechanics, not prose.

The map says no run waits for a person and every loop is bounded. These
scenarios are what makes that refusable rather than aspirational:

- **Every counter exhausts into the outcome the contract specifies.** One case
  per counter — ``L_enrich``, ``L_boundary``, ``L_anchor``, ``L_strategy``,
  ``L_edit`` — forcing the exhaustion and reading the outcome, the scope and the
  attempt/limit out of the OutcomeRecord. The ledger takes the answer from the
  topology registry, so a stage cannot talk it into a gentler one.
- **Budget exhaustion keeps finished work.** The refused call is never paid for,
  an accepted text is preserved, and the destinations that had not started are
  skipped in reverse destination order (§0.4, refinement R-3).
- **Precedence is recorded and cannot lie.** Authority does not flow uphill, and
  a demoted weak candidate cannot win its own tier unless something non-expired
  reinforces it.
- **The logs live in the trace.** The outcome log and the PrecedenceLog are
  ordered views over the StageRecords, each entry naming the stage and scope key
  it came from (U-3), and a StageRecord refuses a REPLAN the route table does
  not declare.

The boundary-commit writer, the other half of this issue, is in
``tests/test_292_boundary_commit.py``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

from src.editorial_core.arp import (
    RUN_CALL_BUDGET_COUNTER,
    ArpError,
    ArpOutcome,
    AttemptCounterLedger,
    KnowledgeRef,
    KnowledgeStatus,
    KnowledgeTier,
    OutcomeRecord,
    OutcomeScope,
    PrecedenceApplication,
    StateCode,
    outcome_log,
    permitted_outcomes,
    precedence_log,
)
from src.run.call_budget import RunCallBudget
from src.run.call_budget_arp import (
    ArpCallBudget,
    ArpCallBudgetError,
    DestinationProgress,
    DestinationState,
)
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_workspace import (
    DeciderKind,
    RunWorkspace,
    StageAttribution,
    StageRecord,
    StageStatus,
    verify_run_workspace,
)
from src.strategy.execution_context import ConfigurationIdentity

TS_UTC = datetime(2026, 9, 22, 11, 0, tzinfo=timezone.utc)

#: The six canonical destinations in one order, as §0.2 hands them over.
DESTINATIONS = ("wix", "linkedin", "facebook", "instagram", "threads", "telegram")

#: A run identifies itself with the UUID v4 ``create_run_id`` mints and nothing
#: else (``src/run/run_context.py``), so the trace and the workspace here are
#: bound the way a real run binds them rather than by a readable stand-in.
RUN_ID = create_run_id()


def _run_context(run_id: str) -> RunContext:
    return RunContext(
        run_id=run_id,
        assignment_id="sig-292",
        started_at=TS_UTC,
        strategy_ref="never-blank",
        strategy_version="1.0.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
        configuration_identity=ConfigurationIdentity(
            schema_version="1.0",
            configuration_id="never-blank",
            configuration_version="1.0.0",
            configuration_hash="sha256:" + "b" * 64,
        ),
    )


def _stage_record(
    run_id: str,
    seq: int,
    stage: str,
    scope_key: str,
    *,
    outcomes: tuple[OutcomeRecord, ...] = (),
    precedence: tuple[PrecedenceApplication, ...] = (),
) -> StageRecord:
    started = TS_UTC + timedelta(minutes=seq)
    return StageRecord(
        run_id=run_id,
        seq=seq,
        stage=stage,
        scope_key=scope_key,
        started_at=started,
        ended_at=started + timedelta(seconds=5),
        created_by=StageAttribution(
            stage=stage, component=f"{stage}-pass-through", decider=DeciderKind.CODE
        ),
        outcomes=outcomes,
        precedence=precedence,
        status=StageStatus.COMPLETED,
    )


def _knowledge(
    record_id: str,
    tier: KnowledgeTier,
    *,
    file_status: KnowledgeStatus = KnowledgeStatus.DESCRIPTIVE,
    effective_status: Optional[KnowledgeStatus] = None,
    reinforced_by: Optional[str] = None,
) -> KnowledgeRef:
    return KnowledgeRef(
        record_id=record_id,
        record_version=1,
        tier=tier,
        file_status=file_status,
        effective_status=effective_status or file_status,
        reinforced_by=reinforced_by,
    )


def _progress(**states: DestinationState) -> tuple[DestinationProgress, ...]:
    """The six destinations in destination order, defaulting to not started."""

    return tuple(
        DestinationProgress(
            destination=destination,
            state=states.get(destination, DestinationState.NOT_STARTED),
        )
        for destination in DESTINATIONS
    )


# ===========================================================================
# OutcomeRecord
# ===========================================================================


def test_every_state_code_declares_which_outcomes_it_may_end_in():
    """A state with no declared outcome could be recorded as anything."""

    for state_code in StateCode:
        assert permitted_outcomes(state_code), state_code


def test_a_state_cannot_end_in_an_outcome_the_map_does_not_allow():
    with pytest.raises(ValueError, match="cannot end in RESOLVE"):
        OutcomeRecord(
            outcome=ArpOutcome.RESOLVE,
            state_code=StateCode.SIGNAL_OUTSIDE_CONTRACT,
            scope=OutcomeScope.SIGNAL,
        )


def test_only_a_replan_routes_anywhere():
    with pytest.raises(ValueError, match="route target belongs to a REPLAN"):
        OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
            scope=OutcomeScope.DESTINATION,
            counter="L_strategy",
            attempt=2,
            limit=2,
            route_target="S-08",
        )


def test_a_replan_spends_a_named_counter():
    """An unbounded backward route is how a run loops forever."""

    with pytest.raises(ValueError, match="spends a named counter"):
        OutcomeRecord(
            outcome=ArpOutcome.REPLAN,
            state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
            scope=OutcomeScope.DESTINATION,
            route_target="S-08",
        )


def test_a_count_is_recorded_against_its_counter():
    with pytest.raises(ValueError, match="recorded against no counter"):
        OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
            scope=OutcomeScope.DESTINATION,
            attempt=1,
            limit=2,
        )


def test_a_counter_is_never_spent_past_its_limit():
    with pytest.raises(ValueError, match="past limit"):
        OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
            scope=OutcomeScope.DESTINATION,
            counter="L_strategy",
            attempt=3,
            limit=2,
        )


# ===========================================================================
# Attempt counters (§0.3): forced exhaustion per counter
# ===========================================================================


#: One case per counter: the route that spends it, the state the stage met, and
#: the outcome Step 2 §0.3 and §5.3 say its exhaustion produces.
_COUNTER_CASES = (
    (
        "L_enrich",
        "S-01",
        "relevance_revise_or_hold",
        StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
        "sig-292",
        2,
        OutcomeScope.SIGNAL,
        StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
        "S-03",
    ),
    (
        "L_boundary",
        "S-13",
        "interpretation_inadmissible_or_unlisted",
        StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION,
        "unit-292/linkedin",
        1,
        OutcomeScope.DESTINATION,
        StateCode.BOUNDARY_REENTRY_EXHAUSTED,
        "S-04",
    ),
    (
        "L_anchor",
        "S-09",
        "no_admissible_candidate_on_any_destination",
        StateCode.NO_ADMISSIBLE_STRATEGY,
        "unit-292",
        1,
        OutcomeScope.UNIT,
        StateCode.NO_ADMISSIBLE_STRATEGY,
        "S-06",
    ),
    (
        "L_strategy",
        "S-09",
        "no_admissible_candidate",
        StateCode.NO_ADMISSIBLE_STRATEGY,
        "unit-292/telegram",
        2,
        OutcomeScope.DESTINATION,
        StateCode.NO_ADMISSIBLE_STRATEGY,
        "S-08",
    ),
    (
        "L_edit",
        "S-13",
        "phrasing_or_removable_fact",
        StateCode.FACT_OR_PHRASING_FAILURE,
        "unit-292/wix/txt-1",
        1,
        OutcomeScope.PUBLICATION,
        StateCode.FACT_OR_PHRASING_FAILURE,
        "S-12",
    ),
)


@pytest.mark.parametrize(
    "counter,source,cause,state_code,scope_key,limit,scope,exhausted_state,target",
    _COUNTER_CASES,
    ids=[case[0] for case in _COUNTER_CASES],
)
def test_each_counter_exhausts_into_the_specified_skip(
    counter,
    source,
    cause,
    state_code,
    scope_key,
    limit,
    scope,
    exhausted_state,
    target,
):
    """Forced exhaustion of one counter produces the outcome §0.3 specifies."""

    ledger = AttemptCounterLedger()
    assert ledger.limit(counter) == limit

    for attempt in range(1, limit + 1):
        replan = ledger.route(
            source=source, cause=cause, scope_key=scope_key, state_code=state_code
        )
        assert replan.outcome is ArpOutcome.REPLAN
        assert replan.route_target == target
        assert (replan.counter, replan.attempt, replan.limit) == (
            counter,
            attempt,
            limit,
        )
        assert replan.state_code is state_code
    assert ledger.exhausted(counter, scope_key)

    skip = ledger.route(
        source=source, cause=cause, scope_key=scope_key, state_code=state_code
    )
    assert skip.outcome is ArpOutcome.SKIP
    assert skip.scope is scope
    assert skip.scope_key == scope_key
    assert skip.route_target is None
    assert skip.state_code is exhausted_state
    assert (skip.counter, skip.attempt, skip.limit) == (counter, limit, limit)
    assert skip.exhausted


def test_the_anchor_ambiguity_route_ends_where_the_evidence_says():
    """One route ends in a DEGRADE or a SKIP, and the counter cannot choose.

    S-06 weakens the anchor when it still holds at a lower strength and skips
    the unit when there is no provable anchor. That is an evidence decision, so
    the ledger refuses to invent it and the caller has to state it.
    """

    ledger = AttemptCounterLedger()
    for _ in range(ledger.limit("L_enrich")):
        ledger.route(
            source="S-06",
            cause="ambiguity_touches_anchor",
            scope_key="sig-292",
            state_code=StateCode.EVIDENCE_CONFLICT_IN_ANCHOR,
        )

    with pytest.raises(ArpError, match="state which of them the evidence gave"):
        ledger.route(
            source="S-06",
            cause="ambiguity_touches_anchor",
            scope_key="sig-292",
            state_code=StateCode.EVIDENCE_CONFLICT_IN_ANCHOR,
        )

    degraded = ledger.route(
        source="S-06",
        cause="ambiguity_touches_anchor",
        scope_key="sig-292",
        state_code=StateCode.EVIDENCE_CONFLICT_IN_ANCHOR,
        on_exhaustion=ArpOutcome.DEGRADE,
    )
    assert degraded.outcome is ArpOutcome.DEGRADE
    assert degraded.scope is OutcomeScope.UNIT
    assert degraded.route_target is None

    skipped = ledger.route(
        source="S-06",
        cause="ambiguity_touches_anchor",
        scope_key="sig-292",
        state_code=StateCode.EVIDENCE_CONFLICT_IN_ANCHOR,
        on_exhaustion=ArpOutcome.SKIP,
    )
    assert skipped.outcome is ArpOutcome.SKIP


def test_a_route_whose_contract_fixes_its_end_refuses_a_chosen_one():
    ledger = AttemptCounterLedger()
    with pytest.raises(ArpError, match="may not choose the outcome"):
        ledger.route(
            source="S-09",
            cause="no_admissible_candidate",
            scope_key="unit-292/wix",
            state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
            on_exhaustion=ArpOutcome.DEGRADE,
        )


def test_two_scopes_spend_their_counters_independently():
    """``L_strategy`` is per destination: one exhausted destination is one."""

    ledger = AttemptCounterLedger()
    for _ in range(ledger.limit("L_strategy")):
        ledger.route(
            source="S-11",
            cause="plan_check_failed",
            scope_key="unit-292/wix",
            state_code=StateCode.PROMISE_WIDER_THAN_BOUNDARY,
        )

    assert ledger.exhausted("L_strategy", "unit-292/wix")
    assert not ledger.exhausted("L_strategy", "unit-292/telegram")
    other = ledger.route(
        source="S-11",
        cause="plan_check_failed",
        scope_key="unit-292/telegram",
        state_code=StateCode.PROMISE_WIDER_THAN_BOUNDARY,
    )
    assert other.outcome is ArpOutcome.REPLAN
    assert other.attempt == 1


def test_a_counter_is_never_reset_inside_a_run():
    """The §5.3 termination argument rests on this: exhaustion is permanent."""

    ledger = AttemptCounterLedger()
    scope_key = "unit-292/instagram"
    for _ in range(ledger.limit("L_strategy") + 3):
        ledger.route(
            source="S-12",
            cause="plan_does_not_hold",
            scope_key=scope_key,
            state_code=StateCode.PLAN_DOES_NOT_HOLD,
        )
    assert ledger.used("L_strategy", scope_key) == ledger.limit("L_strategy")
    assert ledger.remaining("L_strategy", scope_key) == 0


def test_an_undeclared_route_cannot_be_taken():
    ledger = AttemptCounterLedger()
    with pytest.raises(ArpError, match="no declared route leaves S-13"):
        ledger.route(
            source="S-13",
            cause="the_writer_should_try_harder",
            scope_key="unit-292/wix",
            state_code=StateCode.STRUCTURAL_TEXT_FAILURE,
        )


def test_a_limit_is_tunable_and_an_unknown_counter_is_not():
    """§0.3 calls the numbers tunable; the counters themselves are not."""

    ledger = AttemptCounterLedger(limits={"L_strategy": 1})
    assert ledger.limit("L_strategy") == 1
    first = ledger.route(
        source="S-09",
        cause="no_admissible_candidate",
        scope_key="unit-292/wix",
        state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
    )
    assert first.limit == 1
    assert ledger.exhausted("L_strategy", "unit-292/wix")

    with pytest.raises(ArpError, match="unknown counter"):
        AttemptCounterLedger(limits={"L_persistence": 2})
    with pytest.raises(ArpError, match="at least 1"):
        AttemptCounterLedger(limits={"L_edit": 0})


def test_a_counter_is_spent_per_scope_key_and_needs_one():
    ledger = AttemptCounterLedger()
    with pytest.raises(ArpError, match="the key must name the scope"):
        ledger.route(
            source="S-09",
            cause="no_admissible_candidate",
            scope_key="   ",
            state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
        )


# ===========================================================================
# RunCallBudget exhaustion as SKIP (§0.4, R-3)
# ===========================================================================


def test_the_refused_call_is_never_paid_for():
    budget = RunCallBudget(2)
    wrap = ArpCallBudget(budget)

    assert wrap.spend(scope=OutcomeScope.SIGNAL, scope_key="sig-292") is None
    assert wrap.spend(scope=OutcomeScope.SIGNAL, scope_key="sig-292") is None
    refused = wrap.spend(scope=OutcomeScope.DESTINATION, scope_key="unit-292/linkedin")

    assert budget.used == 2, "the refused call must not have been charged"
    assert refused is not None
    assert refused.outcome is ArpOutcome.SKIP
    assert refused.state_code is StateCode.BUDGET_EXHAUSTED
    assert refused.scope is OutcomeScope.DESTINATION
    assert refused.scope_key == "unit-292/linkedin"
    assert (refused.counter, refused.attempt, refused.limit) == (
        RUN_CALL_BUDGET_COUNTER,
        2,
        2,
    )


def test_budget_exhaustion_keeps_the_accepted_text_and_skips_the_unstarted():
    """§0.4: accepted work survives, and the unstarted go in reverse order.

    Reverse, because the destinations processed first are the ones others link
    to and the ones actually published: under a tight budget they are the last
    to be given up.
    """

    budget = RunCallBudget(1)
    wrap = ArpCallBudget(budget)
    assert wrap.spend(scope=OutcomeScope.DESTINATION, scope_key="unit-292/wix") is None

    progress = _progress(
        wix=DestinationState.TEXT_ACCEPTED,
        linkedin=DestinationState.IN_PROGRESS,
    )
    refused = wrap.spend(scope=OutcomeScope.DESTINATION, scope_key="unit-292/linkedin")
    assert refused is not None and refused.outcome is ArpOutcome.SKIP

    skips = wrap.exhaustion_outcomes(progress)
    assert [outcome.scope_key for outcome in skips] == [
        "telegram",
        "threads",
        "instagram",
        "facebook",
    ]
    assert {outcome.state_code for outcome in skips} == {StateCode.BUDGET_EXHAUSTED}
    assert {outcome.scope for outcome in skips} == {OutcomeScope.DESTINATION}

    preserved = ArpCallBudget.preserved_destinations(progress)
    assert preserved == ("wix",)
    assert "wix" not in {outcome.scope_key for outcome in skips}


def test_nothing_is_skipped_for_exhaustion_while_calls_remain():
    wrap = ArpCallBudget(RunCallBudget(3))
    with pytest.raises(ArpCallBudgetError, match="calls left"):
        wrap.exhaustion_outcomes(_progress())


def test_a_destination_has_one_state_in_the_progress_list():
    wrap = ArpCallBudget(RunCallBudget(1))
    assert wrap.spend(scope=OutcomeScope.SIGNAL, scope_key="sig-292") is None
    doubled = (
        DestinationProgress(destination="wix", state=DestinationState.NOT_STARTED),
        DestinationProgress(destination="wix", state=DestinationState.TEXT_ACCEPTED),
    )
    with pytest.raises(ArpCallBudgetError, match="more than once"):
        wrap.exhaustion_outcomes(doubled)


# ===========================================================================
# Precedence (map §5, Step 4 §5.1)
# ===========================================================================


def test_authority_does_not_flow_uphill():
    with pytest.raises(ValueError, match="the higher tier wins"):
        PrecedenceApplication(
            conflict="portfolio pressure against an approved client rule",
            winner=_knowledge("K-PRF-01", KnowledgeTier.PORTFOLIO),
            loser=_knowledge(
                "CLIENT-02",
                KnowledgeTier.APPROVED_CLIENT_RULE,
                file_status=KnowledgeStatus.APPROVED_RULE,
            ),
            rule_applied="map §5",
        )


def test_a_weak_candidate_cannot_win_its_own_tier():
    with pytest.raises(ValueError, match="loses to any non-expired record"):
        PrecedenceApplication(
            conflict="two editorial records on the same opening",
            winner=_knowledge(
                "K-OPN-09",
                KnowledgeTier.EDITORIAL,
                file_status=KnowledgeStatus.CANDIDATE,
                effective_status=KnowledgeStatus.WEAK_CANDIDATE,
            ),
            loser=_knowledge("K-OPN-02", KnowledgeTier.EDITORIAL),
            rule_applied="Step 4 §5.1 rule 2",
        )


def test_a_reinforced_weak_candidate_counts_at_its_original_weight():
    application = PrecedenceApplication(
        conflict="two editorial records on the same opening",
        winner=_knowledge(
            "K-OPN-09",
            KnowledgeTier.EDITORIAL,
            file_status=KnowledgeStatus.CANDIDATE,
            effective_status=KnowledgeStatus.WEAK_CANDIDATE,
            reinforced_by="K-PRC-04",
        ),
        loser=_knowledge("K-OPN-02", KnowledgeTier.EDITORIAL),
        rule_applied="Step 4 §5.1 rule 3 exception",
    )
    assert application.winner.reinforced_by == "K-PRC-04"


def test_a_lower_tier_may_lose_and_be_recorded():
    application = PrecedenceApplication(
        conflict="a stylistic preference against hard platform policy",
        winner=_knowledge(
            "K-DST-01",
            KnowledgeTier.HARD_PLATFORM_POLICY,
            file_status=KnowledgeStatus.APPROVED_RULE,
        ),
        loser=_knowledge("K-STY-03", KnowledgeTier.STYLE),
        rule_applied="map §5",
    )
    assert application.winner.tier is KnowledgeTier.HARD_PLATFORM_POLICY


def test_tier_a_is_recorded_without_an_invented_place_in_the_ladder():
    """The map's ladder does not list tier A, and this slice does not add one."""

    application = PrecedenceApplication(
        conflict="the strength ladder against a candidate wording",
        winner=_knowledge(
            "LADDER-DEFAULT",
            KnowledgeTier.ARCHITECTURAL,
            file_status=KnowledgeStatus.INVARIANT,
        ),
        loser=_knowledge("K-TEN-04", KnowledgeTier.EDITORIAL),
        rule_applied="Step 4 §2.3",
    )
    assert application.winner.tier is KnowledgeTier.ARCHITECTURAL


def test_a_retired_record_never_reaches_a_run():
    with pytest.raises(ValueError, match="retired"):
        _knowledge(
            "K-OPN-11",
            KnowledgeTier.EDITORIAL,
            file_status=KnowledgeStatus.RETIRED,
        )


def test_weak_candidate_is_never_a_file_status():
    with pytest.raises(ValueError, match="set only by the loader"):
        _knowledge(
            "K-OPN-11",
            KnowledgeTier.EDITORIAL,
            file_status=KnowledgeStatus.WEAK_CANDIDATE,
        )


def test_a_hard_rule_is_not_demoted_by_expiry():
    """§5: dropping a hard rule because nobody re-checked it is the unsafe way."""

    with pytest.raises(ValueError, match="demotes only"):
        _knowledge(
            "K-DST-01",
            KnowledgeTier.HARD_PLATFORM_POLICY,
            file_status=KnowledgeStatus.APPROVED_RULE,
            effective_status=KnowledgeStatus.WEAK_CANDIDATE,
        )


# ===========================================================================
# The logs in the trace (U-3, Step 3 §4.1)
# ===========================================================================


def _application(conflict: str) -> PrecedenceApplication:
    return PrecedenceApplication(
        conflict=conflict,
        winner=_knowledge(
            "K-DST-01",
            KnowledgeTier.HARD_PLATFORM_POLICY,
            file_status=KnowledgeStatus.APPROVED_RULE,
        ),
        loser=_knowledge("K-STY-03", KnowledgeTier.STYLE),
        rule_applied="map §5",
    )


def test_the_logs_are_ordered_and_name_where_each_entry_came_from():
    ledger = AttemptCounterLedger()
    replan = ledger.route(
        source="S-09",
        cause="no_admissible_candidate",
        scope_key="unit-292/wix",
        state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
    )
    degrade = OutcomeRecord(
        outcome=ArpOutcome.DEGRADE,
        state_code=StateCode.SEVERAL_EQUAL_STRATEGIES,
        scope=OutcomeScope.DESTINATION,
    )
    records = (
        _stage_record(
            RUN_ID,
            7,
            "S-09",
            "unit-292/wix/attempt_2",
            outcomes=(degrade,),
            precedence=(_application("second"),),
        ),
        _stage_record(
            RUN_ID,
            3,
            "S-09",
            "unit-292/wix/attempt_1",
            outcomes=(replan,),
            precedence=(_application("first"),),
        ),
    )

    outcomes = outcome_log(records)
    assert [entry.seq for entry in outcomes] == [3, 7]
    assert [entry.outcome.outcome for entry in outcomes] == [
        ArpOutcome.REPLAN,
        ArpOutcome.DEGRADE,
    ]
    assert outcomes[0].stage == "S-09"
    assert outcomes[0].scope_key == "unit-292/wix/attempt_1"

    log = precedence_log(records)
    assert [entry.application.conflict for entry in log] == ["first", "second"]
    assert [entry.scope_key for entry in log] == [
        "unit-292/wix/attempt_1",
        "unit-292/wix/attempt_2",
    ]


def test_a_stage_record_refuses_a_replan_the_route_table_does_not_declare():
    with pytest.raises(ValueError, match="is not a declared"):
        _stage_record(
            RUN_ID,
            1,
            "S-13",
            "unit-292/wix",
            outcomes=(
                OutcomeRecord(
                    outcome=ArpOutcome.REPLAN,
                    state_code=StateCode.STRUCTURAL_TEXT_FAILURE,
                    scope=OutcomeScope.DESTINATION,
                    counter="L_strategy",
                    attempt=1,
                    limit=2,
                    route_target="S-11",
                ),
            ),
        )


def test_a_stage_record_refuses_a_route_that_spends_the_wrong_counter():
    with pytest.raises(ValueError, match="that route spends"):
        _stage_record(
            RUN_ID,
            1,
            "S-13",
            "unit-292/wix/txt-1",
            outcomes=(
                OutcomeRecord(
                    outcome=ArpOutcome.REPLAN,
                    state_code=StateCode.FACT_OR_PHRASING_FAILURE,
                    scope=OutcomeScope.PUBLICATION,
                    counter="L_strategy",
                    attempt=1,
                    limit=2,
                    route_target="S-12",
                ),
            ),
        )


def test_the_trace_carries_the_outcomes_through_the_workspace(tmp_path: Path):
    """The log is the trace: written with the execution, read back as records."""

    runs_root = tmp_path / "editorial_runs"
    workspace = RunWorkspace.create(runs_root, RUN_ID)
    ledger = AttemptCounterLedger()
    replan = ledger.route(
        source="S-13",
        cause="phrasing_or_removable_fact",
        scope_key="unit-292/wix/txt-1",
        state_code=StateCode.FACT_OR_PHRASING_FAILURE,
        reason="a figure quoted from the core with the wrong unit",
    )
    entry = workspace.write_stage_record(
        _stage_record(
            RUN_ID,
            1,
            "S-13",
            "unit-292/wix/txt-1",
            outcomes=(replan,),
            precedence=(_application("voice preference against platform policy"),),
        )
    )
    workspace.write_manifest(_run_context(RUN_ID))

    report = verify_run_workspace(runs_root, RUN_ID)
    assert report.verified_stage_records == 1

    written = json.loads((workspace.run_dir / entry.path).read_text(encoding="utf-8"))
    assert written["outcomes"][0]["route_target"] == "S-12"
    assert written["outcomes"][0]["counter"] == "L_edit"
    assert written["precedence"][0]["winner"]["tier"] == "1"

    reloaded = StageRecord.from_dict(written)
    assert reloaded.outcomes[0] == replan
    assert reloaded.precedence[0].rule_applied == "map §5"
