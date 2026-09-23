"""Issue #293: the RunSummary, and what the public ledger will not take.

Step 3 §3.3 says a RunSummary holds enough to compute every indicator without
the 90-day workspace, and §6 says the ledger it goes into is committed to a
public repository. The two together are the contract these tests hold:

- **the numbers are derived from the trace**, not supplied beside it — final
  state per scope, counter usage, calls and tokens;
- **free text, money and raw errors are refused**, in whatever field they
  arrive. That is the rule with teeth: the shape of the record already leaves
  a reason nowhere to go, so the validator is what still holds when a later
  slice adds a field.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from src.editorial_core.arp import (
    ArpOutcome,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.run.code_identity import CLEAN_POLICY, CodeIdentity
from src.run.ledger import LedgerCommitStatus
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_manifest import RunManifest
from src.run.run_summary import (
    PublicationResult,
    PublicSafetyError,
    ReasonCategory,
    RunScope,
    RunSummary,
    RunSummaryError,
    ScopeOutcome,
    WorkspaceRef,
    counter_usage,
    final_states,
    reason_category,
    stage_call_totals,
    verify_public_safe,
)
from src.run.run_workspace import (
    DeciderKind,
    StageAttribution,
    StageRecord,
    StageStatus,
)

TS_UTC = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)

_SIGNAL = "sig-293"
_UNIT = "unit-293"
_WIX = f"{_UNIT}/wix"
_LINKEDIN = f"{_UNIT}/linkedin"

_DIGEST = "sha256:" + "a" * 64


def _run_context(run_id: str | None = None) -> RunContext:
    return RunContext(
        run_id=run_id or create_run_id(),
        assignment_id=_SIGNAL,
        started_at=TS_UTC,
        strategy_ref="never-blank",
        strategy_version="1.0.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
    )


def _record(
    run_id: str,
    seq: int,
    stage: str,
    scope_key: str,
    outcomes: tuple[OutcomeRecord, ...] = (),
    calls: dict | None = None,
) -> StageRecord:
    started = TS_UTC + timedelta(seconds=seq)
    return StageRecord(
        run_id=run_id,
        seq=seq,
        stage=stage,
        scope_key=scope_key,
        started_at=started,
        ended_at=started + timedelta(seconds=1),
        created_by=StageAttribution(
            stage=stage, component="test", decider=DeciderKind.CODE
        ),
        outcomes=outcomes,
        calls=calls,
        status=StageStatus.COMPLETED,
    )


def _workspace_ref() -> WorkspaceRef:
    return WorkspaceRef(
        artifact_name="editorial-run-293",
        retention_days=90,
        expires_on=date(2026, 12, 21),
        manifest_digest=_DIGEST,
    )


def _summary(**overrides: Any) -> RunSummary:
    context = _run_context()
    fields: dict[str, Any] = dict(
        run_context=context,
        manifest=RunManifest.for_run(context),
        records=(),
        scopes=(RunScope(scope=OutcomeScope.SIGNAL, scope_key=_SIGNAL),),
        client="never_blank",
        signal_ids=(_SIGNAL,),
        workspace=_workspace_ref(),
        call_budget_limit=40,
        ledger_commit=LedgerCommitStatus.NOT_ATTEMPTED,
    )
    fields.update(overrides)
    return RunSummary.for_run(**fields)


# ── the closed reason vocabulary ───────────────────────────────────────────


def test_every_state_the_map_defines_is_counted_under_a_category():
    """A state with no category is a skip the indicators cannot group."""

    for state in StateCode:
        assert isinstance(reason_category(state), ReasonCategory)


def test_the_category_is_derived_from_the_state_and_not_chosen_beside_it():
    with pytest.raises(ValidationError):
        ScopeOutcome(
            scope=OutcomeScope.DESTINATION,
            scope_key=_WIX,
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.BUDGET_EXHAUSTED,
            category=ReasonCategory.TEXT,
        )


def test_a_skip_without_a_state_code_cannot_be_counted():
    with pytest.raises(ValidationError):
        ScopeOutcome(
            scope=OutcomeScope.DESTINATION,
            scope_key=_WIX,
            outcome=ArpOutcome.SKIP,
        )


def test_a_replan_is_not_a_final_state():
    with pytest.raises(ValidationError):
        ScopeOutcome(
            scope=OutcomeScope.DESTINATION,
            scope_key=_WIX,
            outcome=ArpOutcome.REPLAN,
            state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
            category=ReasonCategory.STRATEGY,
        )


# ── public-safe by construction (§3.3) ─────────────────────────────────────


def test_a_real_summary_is_public_safe():
    summary = _summary()

    verify_public_safe(summary.to_dict())


def test_the_validator_refuses_free_text():
    payload = {"scope_outcomes": [{"reason": "the client rules conflict"}]}

    with pytest.raises(PublicSafetyError, match="free text"):
        verify_public_safe(payload)


def test_the_validator_refuses_money_however_it_is_spelled():
    for payload in (
        {"run_cost": 12},
        {"totals": {"amount_usd": 3}},
        {"note": "$12.40"},
        {"note": "12.40USD"},
        {"spend": 0.42},
    ):
        with pytest.raises(PublicSafetyError):
            verify_public_safe(payload)


def test_the_validator_refuses_a_fractional_number_anywhere():
    with pytest.raises(PublicSafetyError, match="fractional"):
        verify_public_safe({"stage_calls": [{"tokens_in": 1.5}]})


def test_the_validator_refuses_a_raw_provider_error():
    for payload in (
        {"error": "Traceback"},
        {"error": "openai.RateLimitException"},
        {"publications": [{"external_id": "<ConnectionError"}]},
    ):
        with pytest.raises(PublicSafetyError):
            verify_public_safe(payload)


def test_a_summary_cannot_be_built_around_the_validator():
    """The shape leaves a sentence nowhere to go; an identifier is not a door."""

    with pytest.raises(ValidationError):
        _summary(client="never blank, the client")


def test_free_text_without_a_space_in_it_is_still_free_text():
    """A script that writes without spaces writes sentences all the same."""

    with pytest.raises(ValidationError):
        _summary(client="客户内部机密")

    with pytest.raises(PublicSafetyError, match="free text"):
        verify_public_safe({"client": "客户内部机密"})


def test_a_field_that_holds_an_identifier_holds_nothing_else():
    """What the blunt rule cannot know: which kind of token belonged here."""

    with pytest.raises(ValidationError):
        _summary(fingerprint_ids=("fp-1(the-second-attempt)",))

    with pytest.raises(ValidationError):
        _summary(client="never_blank/../elsewhere")


def test_a_publication_url_is_a_url_and_an_external_id_is_an_id():
    PublicationResult(
        destination="linkedin",
        published=True,
        external_id="urn:li:share:7123",
        url="https://www.linkedin.com/feed/update/urn:li:share:7123/",
    )

    with pytest.raises(ValidationError):
        PublicationResult(
            destination="linkedin", published=True, url="see-the-workspace-trace"
        )


def test_a_record_read_back_from_the_ledger_is_validated_again():
    unsafe = _summary().to_dict()
    unsafe["fingerprint_ids"] = ["fp-1 (the second attempt)"]

    with pytest.raises(RunSummaryError):
        RunSummary.from_dict(unsafe)


# ── derived from the trace (§4.1, §4.4) ────────────────────────────────────


def test_a_scope_that_left_no_outcome_resolved():
    scopes = (
        RunScope(scope=OutcomeScope.SIGNAL, scope_key=_SIGNAL),
        RunScope(scope=OutcomeScope.DESTINATION, scope_key=_WIX),
    )

    states = final_states(scopes, ())

    assert [state.outcome for state in states] == [ArpOutcome.RESOLVE] * 2
    assert all(state.state_code is None for state in states)


def test_the_final_state_of_a_scope_is_where_its_attempts_ended():
    run_id = create_run_id()
    replan = OutcomeRecord(
        outcome=ArpOutcome.REPLAN,
        state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
        scope=OutcomeScope.DESTINATION,
        scope_key=_WIX,
        counter="L_strategy",
        attempt=1,
        limit=2,
        route_target="S-08",
    )
    skip = OutcomeRecord(
        outcome=ArpOutcome.SKIP,
        state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
        scope=OutcomeScope.DESTINATION,
        scope_key=_WIX,
        counter="L_strategy",
        attempt=2,
        limit=2,
    )
    records = (
        _record(run_id, 0, "S-09", _WIX, (replan,)),
        _record(run_id, 1, "S-09", _WIX, (skip,)),
    )

    states = final_states(
        (RunScope(scope=OutcomeScope.DESTINATION, scope_key=_WIX),), records
    )

    assert len(states) == 1
    assert states[0].outcome is ArpOutcome.SKIP
    assert states[0].state_code is StateCode.NO_ADMISSIBLE_STRATEGY
    assert states[0].category is ReasonCategory.STRATEGY


def test_a_skip_recorded_for_an_undeclared_scope_is_kept():
    """Budget exhaustion skips destinations it never started (§0.4)."""

    run_id = create_run_id()
    skipped = OutcomeRecord(
        outcome=ArpOutcome.SKIP,
        state_code=StateCode.BUDGET_EXHAUSTED,
        scope=OutcomeScope.DESTINATION,
        scope_key=_LINKEDIN,
        counter="RunCallBudget",
        attempt=40,
        limit=40,
    )
    records = (_record(run_id, 0, "S-12", _WIX, (skipped,)),)

    states = final_states(
        (RunScope(scope=OutcomeScope.DESTINATION, scope_key=_WIX),), records
    )

    assert [state.scope_key for state in states] == [_WIX, _LINKEDIN]
    assert states[1].outcome is ArpOutcome.SKIP
    assert states[1].category is ReasonCategory.BUDGET


def test_every_counter_is_reported_and_its_cost_is_read_from_the_trace():
    run_id = create_run_id()

    def replan(scope_key: str, attempt: int) -> OutcomeRecord:
        return OutcomeRecord(
            outcome=ArpOutcome.REPLAN,
            state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
            scope=OutcomeScope.DESTINATION,
            scope_key=scope_key,
            counter="L_strategy",
            attempt=attempt,
            limit=2,
            route_target="S-08",
        )

    records = (
        _record(run_id, 0, "S-09", _WIX, (replan(_WIX, 1),)),
        _record(run_id, 1, "S-09", _WIX, (replan(_WIX, 2),)),
        _record(run_id, 2, "S-09", _LINKEDIN, (replan(_LINKEDIN, 1),)),
    )

    usage = {entry.counter: entry for entry in counter_usage(records)}

    assert set(usage) == {
        counter.counter_id for counter in CANONICAL_TOPOLOGY.counters
    }
    # Two attempts on one destination and one on another: three in all.
    assert usage["L_strategy"].used == 3
    assert usage["L_strategy"].limit == 2
    assert usage["L_enrich"].used == 0


def test_the_run_call_budget_is_not_reported_as_an_attempt_counter():
    run_id = create_run_id()
    records = (_record(run_id, 0, "S-12", _WIX, (
        OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.BUDGET_EXHAUSTED,
            scope=OutcomeScope.DESTINATION,
            scope_key=_WIX,
            counter="RunCallBudget",
            attempt=40,
            limit=40,
        ),
    )),)

    assert "RunCallBudget" not in {
        entry.counter for entry in counter_usage(records)
    }


def test_calls_and_tokens_are_summed_per_stage_across_executions():
    run_id = create_run_id()
    records = (
        _record(run_id, 0, "S-08", _WIX, calls={
            "count": 2, "tokens_in": 100, "tokens_out": 40,
        }),
        _record(run_id, 1, "S-08", _LINKEDIN, calls={
            "count": 3, "tokens_in": 150, "tokens_out": 60,
        }),
        _record(run_id, 2, "S-09", _WIX),
    )

    totals = {entry.stage: entry for entry in stage_call_totals(records)}

    assert totals["S-08"].calls == 5
    assert totals["S-08"].tokens_in == 250
    assert totals["S-08"].tokens_out == 100
    # A stage that recorded no block made no call: absence is zero, not unknown.
    assert totals["S-09"].calls == 0


def test_a_call_count_that_is_not_a_whole_number_is_refused():
    run_id = create_run_id()
    records = (_record(run_id, 0, "S-08", _WIX, calls={"count": 1.5}),)

    with pytest.raises(RunSummaryError):
        stage_call_totals(records)


def test_a_run_cannot_claim_more_calls_than_its_budget_allowed():
    run_id = create_run_id()
    records = (
        _record(run_id, 0, "S-08", _WIX, calls={"count": 5}),
    )

    with pytest.raises(ValidationError):
        _summary(records=records, call_budget_limit=4)


# ── where it goes (§3.2) ───────────────────────────────────────────────────


def test_the_summary_is_keyed_by_client_month_and_run():
    context = _run_context()
    summary = _summary(run_context=context, manifest=RunManifest.for_run(context))

    assert summary.relative_path() == (
        f"runs/never_blank/2026-09/{context.run_id}.json"
    )


def test_the_summary_states_the_topology_the_run_executed():
    context = _run_context()
    manifest = RunManifest.for_run(context)

    summary = _summary(run_context=context, manifest=manifest)

    assert summary.topology_digest == manifest.topology_digest


def test_the_summary_round_trips_through_its_own_serialization():
    summary = _summary(
        code_identity=CodeIdentity(
            commit_sha="b" * 40,
            tracked_worktree_clean=True,
            clean_policy=CLEAN_POLICY,
        ),
    )

    assert RunSummary.from_dict(summary.to_dict()) == summary
