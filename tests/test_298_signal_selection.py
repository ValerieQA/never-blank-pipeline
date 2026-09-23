"""Issue #298: S-00 accepts or skips one signal on fit and eligibility.

SL-3's acceptance evidence for the first stage, as scenarios:

1. **an out-of-contract signal is skipped, and the rule ID says which rule
   refused it** — with no model call spent on a signal the contract had
   already turned away;
2. **an eligible, in-contract signal is selected**;
3. **the trace shows the SignalSelection** — the entity at the path §2.3 gives
   S-00, and the StageRecord that carries its outcome.

And the three properties the stage rests on: the eligibility judgment keeps its
fail-closed posture, portfolio pressure is recorded and never skips on its own,
and queue mode refuses to pretend it has a queue while the split cap is 1.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from src.editorial_core.arp import ArpOutcome, OutcomeScope, StateCode
from src.editorial_core.signal_selection import (
    SPLIT_CAP,
    STAGE,
    CandidateKind,
    ContractFitRules,
    FitRule,
    PortfolioFingerprint,
    PortfolioPressure,
    SelectionCandidate,
    SignalFit,
    SignalSelection,
    SignalSelectionError,
    SimilarityKind,
    select_from_queue,
    select_signal,
)
from src.run.call_budget import RunCallBudget
from src.run.call_budget_arp import ArpCallBudget
from src.run.run_context import create_run_id
from src.run.run_summary import ReasonCategory, reason_category
from src.run.run_workspace import (
    DeciderKind,
    EntityRef,
    RunWorkspace,
    StageAttribution,
    StageRecord,
    StageStatus,
)
from src.strategy.business_config import EditorialRole

#: The contract's fit rules, as one client might write them: a topic rule and a
#: risk rule, each with the ID a SKIP for it is recorded with.
TOPIC_RULE = FitRule(
    rule_id="FIT-TOPIC-01",
    fit=SignalFit.OUTSIDE_TOPICS,
    field="TOPIC",
    admits=("supply chain", "manufacturing"),
)
RISK_RULE = FitRule(
    rule_id="FIT-RISK-01",
    fit=SignalFit.OUTSIDE_RISK_LEVEL,
    field="RISK_LEVEL",
    admits=("low", "moderate"),
)
FIT_RULES = ContractFitRules((TOPIC_RULE, RISK_RULE))

SIGNAL_ID = "sig-298"
SOURCE = "https://example.test/recall"


def _role(**overrides: Any) -> EditorialRole:
    fields: dict[str, Any] = dict(
        role_id="role-under-test",
        intent="report the documented case",
        structure=("opening",),
        forbidden=("speculation",),
        eligibility_criteria=("The case must be documented by a named source.",),
    )
    fields.update(overrides)
    return EditorialRole(**fields)


def _candidate(**overrides: Any) -> SelectionCandidate:
    signal: dict[str, Any] = {
        "SIGNAL_ID": SIGNAL_ID,
        "HEADLINE": "A plant recalls one component batch",
        "CORE_FACT": "The manufacturer recalled 4,000 units.",
        "SOURCE_NAME": "Example Trade Press",
        "SOURCE_URL": SOURCE,
        "TOPIC": "Supply Chain",
        "RISK_LEVEL": "low",
    }
    signal.update(overrides)
    return SelectionCandidate(
        signal_id=str(signal["SIGNAL_ID"]),
        signal=signal,
        topic_key="supply chain",
        source_locators=(SOURCE,),
    )


class _Transport:
    """A source-eligibility judgment with a fixed answer, counting its calls."""

    def __init__(self, eligible: bool = True, reason: str = "documented") -> None:
        self.eligible = eligible
        self.reason = reason
        self.requests: list[str] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.requests.append(request)
        return json.dumps({"eligible": self.eligible, "reason": self.reason})


class _RefusingTransport:
    """A judgment that cannot be made. It never yields a verdict."""

    def complete(self, *, instructions: str, request: str) -> str:
        raise RuntimeError("the judgment model did not answer")


def _select(
    candidate: SelectionCandidate | None = None, **overrides: Any
) -> SignalSelection:
    arguments: dict[str, Any] = dict(
        fit_rules=FIT_RULES, role=_role(), transport=_Transport()
    )
    arguments.update(overrides)
    return select_signal(candidate or _candidate(), **arguments)


# ===========================================================================
# Contract fit
# ===========================================================================


def test_an_eligible_in_contract_signal_is_selected():
    transport = _Transport()

    selection = _select(transport=transport)

    assert selection.selected is True
    assert selection.fit is SignalFit.FITS
    assert selection.outcome is None
    assert all(result.passed for result in selection.fit_rules)
    assert selection.eligibility is not None
    assert selection.eligibility.eligible is True
    assert len(transport.requests) == 1, "S-00 makes exactly one model call"


def test_a_signal_outside_the_contract_topics_is_skipped_with_the_rule_id():
    transport = _Transport()

    selection = _select(_candidate(TOPIC="celebrity gossip"), transport=transport)

    assert selection.selected is False
    assert selection.fit is SignalFit.OUTSIDE_TOPICS
    outcome = selection.outcome
    assert outcome is not None
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.state_code is StateCode.SIGNAL_OUTSIDE_CONTRACT
    assert outcome.scope is OutcomeScope.SIGNAL
    assert outcome.scope_key == SIGNAL_ID
    assert TOPIC_RULE.rule_id in (outcome.reason or "")
    refused = [result for result in selection.fit_rules if not result.passed]
    assert [result.rule_id for result in refused] == [TOPIC_RULE.rule_id]


def test_a_signal_the_contract_turned_away_costs_no_model_call():
    """A SKIP on fit is terminal, so nothing after it is worth paying for."""

    transport = _Transport()

    selection = _select(_candidate(TOPIC="celebrity gossip"), transport=transport)

    assert transport.requests == []
    assert selection.eligibility is None


def test_a_risk_level_the_contract_does_not_take_is_its_own_reason():
    selection = _select(_candidate(RISK_LEVEL="extreme"))

    assert selection.fit is SignalFit.OUTSIDE_RISK_LEVEL
    assert selection.outcome is not None
    assert selection.outcome.state_code is StateCode.HIGH_STAKES_OUTSIDE_RISK_LEVEL


def test_every_fit_rule_is_recorded_not_only_the_one_that_refused():
    """§1's Trace column asks for the results, and a reader needs all of them."""

    selection = _select(_candidate(TOPIC="celebrity gossip", RISK_LEVEL="extreme"))

    assert [result.rule_id for result in selection.fit_rules] == [
        TOPIC_RULE.rule_id,
        RISK_RULE.rule_id,
    ]
    assert [result.passed for result in selection.fit_rules] == [False, False]
    # The first refusal in the contract's own order decides the recorded fit.
    assert selection.fit is SignalFit.OUTSIDE_TOPICS


def test_a_signal_that_states_nothing_for_a_rule_does_not_pass_it():
    """Silence is not admission: the contract listed what it takes."""

    signal = dict(_candidate().signal)
    del signal["TOPIC"]
    candidate = SelectionCandidate(signal_id=SIGNAL_ID, signal=signal)

    selection = _select(candidate)

    assert selection.selected is False
    assert selection.fit is SignalFit.OUTSIDE_TOPICS
    assert selection.fit_rules[0].stated == ()
    assert selection.outcome is not None
    assert "not stated" in (selection.outcome.reason or "")


def test_a_signal_fits_only_when_every_value_it_states_is_admitted():
    selection = _select(_candidate(TOPIC=["Supply Chain", "celebrity gossip"]))

    assert selection.selected is False
    assert selection.fit_rules[0].stated == ("supply chain", "celebrity gossip")


def test_a_field_with_a_member_the_stage_cannot_read_states_nothing_at_all():
    """Reading past it would pass the rule on a fit never established in full."""

    selection = _select(_candidate(RISK_LEVEL=["low", 123]))

    assert selection.selected is False
    assert selection.fit is SignalFit.OUTSIDE_RISK_LEVEL
    assert selection.fit_rules[1].stated == ()


def test_the_fit_rules_are_a_required_input_of_the_stage():
    with pytest.raises(SignalSelectionError, match="required input"):
        ContractFitRules(())


def test_one_rule_id_is_never_answered_by_two_rules():
    with pytest.raises(SignalSelectionError, match="declared twice"):
        ContractFitRules((TOPIC_RULE, TOPIC_RULE))


def test_a_rule_states_what_it_refuses_and_never_that_a_signal_fits():
    with pytest.raises(SignalSelectionError, match="says what it refuses"):
        FitRule(
            rule_id="FIT-BAD-01",
            fit=SignalFit.FITS,
            field="TOPIC",
            admits=("supply chain",),
        )


# ===========================================================================
# Source eligibility
# ===========================================================================


def test_a_source_the_role_may_not_start_from_skips_the_signal():
    selection = _select(transport=_Transport(eligible=False, reason="no named source"))

    assert selection.selected is False
    # The contract agreed; the source class did not.
    assert selection.fit is SignalFit.FITS
    assert selection.outcome is not None
    assert selection.outcome.state_code is StateCode.SOURCE_NOT_ELIGIBLE
    assert selection.eligibility is not None
    assert selection.eligibility.failed_closed is False


def test_a_judgment_that_failed_is_a_skip_and_never_a_verdict():
    """The boundary's fail-closed posture, kept by the stage that wraps it."""

    selection = _select(transport=_RefusingTransport())

    assert selection.selected is False
    assert selection.outcome is not None
    assert selection.outcome.state_code is StateCode.SOURCE_NOT_ELIGIBLE
    assert selection.eligibility is not None
    assert selection.eligibility.eligible is False
    assert selection.eligibility.failed_closed is True


def test_a_role_that_restricts_no_source_does_not_refuse_every_source():
    """An empty criteria list is a declared state, not a missing one."""

    transport = _Transport()

    selection = _select(role=_role(eligibility_criteria=()), transport=transport)

    assert selection.selected is True
    assert selection.eligibility is None
    assert transport.requests == []


def test_the_judgment_asks_about_exactly_one_signal():
    transport = _Transport()

    _select(transport=transport)

    request = json.loads(transport.requests[0])
    assert request["source_case"]["SIGNAL_ID"] == SIGNAL_ID
    assert request["eligibility_criteria"] == list(_role().eligibility_criteria)


def test_an_unjudgeable_candidate_is_skipped_rather_than_raised():
    """``judge_source_eligibility`` raises; S-00 records, because I-01."""

    signal = dict(_candidate().signal)
    signal["SIGNAL_ID"] = "  "
    candidate = SelectionCandidate(signal_id=SIGNAL_ID, signal=signal)

    selection = _select(candidate)

    assert selection.selected is False
    assert selection.eligibility is not None
    assert selection.eligibility.failed_closed is True


# ===========================================================================
# The run's call budget (refinement R-3)
# ===========================================================================


def test_a_refused_call_is_never_made_and_the_signal_is_skipped():
    budget = RunCallBudget(1)
    budget.spend()
    transport = _Transport()

    selection = _select(transport=transport, budget=ArpCallBudget(budget))

    assert transport.requests == []
    assert selection.selected is False
    assert selection.outcome is not None
    assert selection.outcome.state_code is StateCode.BUDGET_EXHAUSTED
    assert selection.eligibility is None


def test_a_budget_with_room_pays_for_the_one_call():
    budget = RunCallBudget(4)

    selection = _select(budget=ArpCallBudget(budget))

    assert selection.selected is True
    assert budget.used == 1


# ===========================================================================
# Portfolio pressure (tier 5, soft)
# ===========================================================================


def test_portfolio_pressure_is_recorded_and_never_skips_on_its_own():
    """I-12: the soft signal is recorded; in assigned mode it decides nothing."""

    portfolio = (
        PortfolioFingerprint("fp-earlier", topic_key="Supply chain"),
        PortfolioFingerprint("fp-other", topic_key="hiring"),
    )

    selection = _select(portfolio=portfolio)

    assert selection.selected is True
    assert selection.portfolio_pressure == (
        PortfolioPressure("fp-earlier", SimilarityKind.SAME_TOPIC),
    )


def test_the_same_source_is_its_own_kind_of_resemblance():
    portfolio = (PortfolioFingerprint("fp-earlier", source_locators=(SOURCE,)),)

    selection = _select(portfolio=portfolio)

    assert [pressure.kind for pressure in selection.portfolio_pressure] == [
        SimilarityKind.SAME_SOURCE
    ]


def test_two_locators_that_differ_only_in_path_case_are_two_sources():
    """Only the scheme and the host fold; the path is the server's to spell."""

    portfolio = (
        PortfolioFingerprint(
            "fp-other", source_locators=("https://example.test/Recall",)
        ),
        PortfolioFingerprint(
            "fp-earlier", source_locators=("HTTPS://Example.test/recall",)
        ),
    )

    selection = _select(portfolio=portfolio)

    assert [item.fingerprint_id for item in selection.portfolio_pressure] == [
        "fp-earlier"
    ]


def test_pressure_is_recorded_for_a_skipped_signal_too():
    portfolio = (PortfolioFingerprint("fp-earlier", topic_key="supply chain"),)

    selection = _select(_candidate(TOPIC="celebrity gossip"), portfolio=portfolio)

    assert selection.selected is False
    assert [item.fingerprint_id for item in selection.portfolio_pressure] == [
        "fp-earlier"
    ]


def test_a_portfolio_that_holds_nothing_alike_produces_no_pressure():
    portfolio = (PortfolioFingerprint("fp-other", topic_key="hiring"),)

    assert _select(portfolio=portfolio).portfolio_pressure == ()


# ===========================================================================
# Modes (AD-03, U-2)
# ===========================================================================


def test_a_deferred_unit_is_not_a_candidate_in_assigned_mode():
    candidate = SelectionCandidate(
        signal_id="unit-1", signal={}, kind=CandidateKind.DEFERRED_UNIT
    )

    with pytest.raises(SignalSelectionError, match="assigned mode"):
        _select(candidate)


def test_queue_mode_is_dormant_while_the_split_cap_is_one():
    assert SPLIT_CAP == 1

    with pytest.raises(SignalSelectionError, match="dormant"):
        select_from_queue((_candidate(),))


def test_queue_mode_does_not_execute_deferred_units_above_the_cap():
    """The interface is fixed; the ranking arrives with the cap that needs it."""

    with pytest.raises(SignalSelectionError, match="out of scope"):
        select_from_queue((_candidate(),), split_cap=2)


# ===========================================================================
# The entity and the trace
# ===========================================================================


def test_a_signal_that_is_not_selected_records_why():
    selected = _select()

    with pytest.raises(SignalSelectionError, match="records no outcome"):
        SignalSelection(
            signal_id=SIGNAL_ID,
            candidate_kind=CandidateKind.SIGNAL,
            fit=SignalFit.OUTSIDE_TOPICS,
            fit_rules=selected.fit_rules,
            portfolio_pressure=(),
            selected=False,
        )


def test_a_selected_signal_cannot_record_a_fit_it_does_not_have():
    with pytest.raises(SignalSelectionError, match="is a SKIP"):
        SignalSelection(
            signal_id=SIGNAL_ID,
            candidate_kind=CandidateKind.SIGNAL,
            fit=SignalFit.OUTSIDE_CONTRACT,
            fit_rules=(),
            portfolio_pressure=(),
            selected=True,
        )


def test_every_skip_this_stage_records_is_countable_in_the_public_ledger():
    for state in (
        StateCode.SIGNAL_OUTSIDE_CONTRACT,
        StateCode.HIGH_STAKES_OUTSIDE_RISK_LEVEL,
        StateCode.SOURCE_NOT_ELIGIBLE,
    ):
        assert isinstance(reason_category(state), ReasonCategory)
    assert reason_category(StateCode.SOURCE_NOT_ELIGIBLE) is ReasonCategory.CONTRACT_FIT


def test_the_trace_shows_the_signal_selection(tmp_path: Path):
    """The entity at the path §2.3 gives S-00, and the record that made it."""

    selection = _select(_candidate(TOPIC="celebrity gossip"))
    workspace, record = _write(tmp_path, selection)

    body = json.loads((workspace.run_dir / "signal/selection.json").read_text())
    assert body["entity_type"] == "E-01.selection"
    assert body["selected"] is False
    assert body["fit"] == SignalFit.OUTSIDE_TOPICS.value
    assert [rule["rule_id"] for rule in body["fit_rules"]] == [
        TOPIC_RULE.rule_id,
        RISK_RULE.rule_id,
    ]
    assert body["outcome"]["state_code"] == StateCode.SIGNAL_OUTSIDE_CONTRACT.value

    reloaded = StageRecord.from_dict(
        json.loads((workspace.run_dir / record).read_text())
    )
    assert reloaded.stage == STAGE
    assert reloaded.scope_key == SIGNAL_ID
    assert [outcome.state_code for outcome in reloaded.outcomes] == [
        StateCode.SIGNAL_OUTSIDE_CONTRACT
    ]
    assert [ref.entity_type for ref in reloaded.outputs] == ["E-01.selection"]


def test_the_trace_of_a_selected_signal_records_no_outcome(tmp_path: Path):
    workspace, record = _write(tmp_path, _select())

    reloaded = StageRecord.from_dict(
        json.loads((workspace.run_dir / record).read_text())
    )
    assert reloaded.outcomes == ()
    assert reloaded.status is StageStatus.COMPLETED


def _write(tmp_path: Path, selection: SignalSelection) -> tuple[RunWorkspace, str]:
    """One S-00 execution written into a fresh run workspace."""

    run_id = create_run_id()
    workspace = RunWorkspace.create(tmp_path / "editorial_runs", run_id)
    entry = workspace.write_entity(
        stage=STAGE,
        relative_path="signal/selection.json",
        entity_type="E-01.selection",
        entity_id=selection.signal_id,
        payload=selection.as_entity(),
    )
    started = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
    trace = workspace.write_stage_record(StageRecord(
        run_id=run_id,
        seq=0,
        stage=STAGE,
        scope_key=selection.signal_id,
        started_at=started,
        ended_at=started + timedelta(seconds=1),
        created_by=StageAttribution(
            stage=STAGE, component="signal-selection", decider=DeciderKind.RULE
        ),
        outputs=(EntityRef(
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            version=entry.version,
            digest=entry.digest,
        ),),
        outcomes=() if selection.outcome is None else (selection.outcome,),
        status=StageStatus.COMPLETED,
    ))
    return workspace, trace.path


# ===========================================================================
# Provider scope: an outage is not a verdict about the source
# ===========================================================================
#
# `source_eligibility.py` separates a judgment that failed on this candidate
# from one that failed because the provider refused, and says why the
# difference matters: "every subsequent call is expected to fail identically,
# and each attempt makes a rate limit worse; a caller walking a queue must
# stop". S-00 has no queue to stop at cap 1 — these tests do not assert that it
# stops, because it must not start doing so here. What they assert is that the
# distinction survives into the record, so the caller U-2 eventually puts in
# front of this stage can act on it.
#
# Live run 32440540565 is the shape being guarded: eight consecutive judgment
# calls, each refused with `RateLimitError`, one outage amplified into a burst
# against the provider that was refusing it. Recorded as `SOURCE_NOT_ELIGIBLE`
# that would read as eight sources the role turned away.


def _sdk_error(cls: type, message: str) -> BaseException:
    # Constructed the way `test_selector_circuit_breaker.py` constructs them:
    # the classifier is isinstance-anchored, and building these the SDK's own
    # way needs an httpx response whose package differs across openai versions.
    exc = cls.__new__(cls)
    Exception.__init__(exc, message)
    return exc


class _ProviderRefusingTransport:
    """A transport that fails the way a provider fails."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def complete(self, *, instructions: str, request: str) -> str:
        raise self.error


def _provider_selection(error: BaseException) -> SignalSelection:
    return _select(transport=_ProviderRefusingTransport(error))


@pytest.mark.parametrize(
    ("factory", "normalized_reason"),
    [
        ("RateLimitError", "rate_limit"),
        ("AuthenticationError", "authentication"),
        ("APIConnectionError", "connection"),
        ("InternalServerError", "provider_internal"),
    ],
)
def test_a_provider_failure_is_never_recorded_as_an_ineligible_source(
    factory: str, normalized_reason: str
):
    """The #170 provider set, each one proven not to become a verdict."""

    import openai

    selection = _provider_selection(_sdk_error(getattr(openai, factory), factory))

    assert selection.selected is False
    assert selection.outcome is not None
    # The point of the whole repair.
    assert selection.outcome.state_code is StateCode.PROVIDER_UNAVAILABLE
    assert selection.outcome.state_code is not StateCode.SOURCE_NOT_ELIGIBLE
    assert selection.outcome.outcome is ArpOutcome.SKIP

    # Not an editorial reason: an outage counted as contract fit or as source
    # eligibility would make the indicators read a dead provider as a selective
    # role.
    assert reason_category(selection.outcome.state_code) is ReasonCategory.PROVIDER

    assert selection.eligibility is not None
    assert selection.eligibility.failed_closed is True
    # Structural, not parsed back out of `reason`.
    assert selection.eligibility.failure_scope == "provider"

    diagnostic = selection.eligibility.provider_failure
    assert diagnostic is not None
    assert diagnostic["normalized_reason"] == normalized_reason
    assert diagnostic["provider"]


def test_the_provider_diagnostic_carries_no_provider_prose():
    """#188's contract: structured fields only, never the provider's sentence."""

    import openai

    secret_shaped = "Invalid API key sk-proj-ABC123DEF456 supplied"
    selection = _provider_selection(
        _sdk_error(openai.AuthenticationError, secret_shaped)
    )

    diagnostic = selection.eligibility.provider_failure  # type: ignore[union-attr]
    assert diagnostic is not None
    assert set(diagnostic) == {
        "provider",
        "normalized_reason",
        "http_status",
        "provider_error_type",
        "provider_error_code",
        "request_id",
        "sanitized_message",
    }
    # The message an authentication error quotes can echo key-shaped material,
    # so it is not extracted at all.
    assert "sk-proj-ABC123DEF456" not in json.dumps(diagnostic)
    assert diagnostic["sanitized_message"] is None
    # And the normalized reason comes from the fixed vocabulary, not the prose.
    assert diagnostic["normalized_reason"] == "authentication"


def test_a_candidate_scope_failure_still_fails_closed_as_before():
    """The other half: an unjudgeable candidate is unchanged by this repair."""

    selection = _select(transport=_RefusingTransport())

    assert selection.selected is False
    assert selection.outcome is not None
    assert selection.outcome.state_code is StateCode.SOURCE_NOT_ELIGIBLE
    assert selection.outcome.outcome is ArpOutcome.SKIP
    assert reason_category(selection.outcome.state_code) is not ReasonCategory.PROVIDER

    assert selection.eligibility is not None
    assert selection.eligibility.eligible is False
    assert selection.eligibility.failed_closed is True
    assert selection.eligibility.failure_scope == "candidate"
    # No provider failed, so there is nothing to say about one.
    assert selection.eligibility.provider_failure is None


def test_a_verdict_carries_no_failure_scope_at_all():
    """`failure_scope` is about a failure; a judged source did not have one."""

    selection = _select(transport=_Transport(eligible=True))

    assert selection.selected is True
    assert selection.eligibility is not None
    assert selection.eligibility.failed_closed is False
    assert selection.eligibility.failure_scope is None
    assert selection.eligibility.provider_failure is None


def test_the_distinction_survives_into_the_written_trace(tmp_path: Path):
    """Structural in the artifact too, not only in memory (§3.3)."""

    import openai

    selection = _provider_selection(_sdk_error(openai.RateLimitError, "429"))
    workspace, record = _write(tmp_path, selection)

    written = (workspace.run_dir / record).read_text(encoding="utf-8")
    assert "provider_unavailable" in written
    assert "source_not_eligible" not in written

    # And the entity the stage wrote carries the scope as a field.
    entity = json.loads(
        (workspace.run_dir / "signal" / "selection.json").read_text(encoding="utf-8")
    )
    assert entity["eligibility"]["failure_scope"] == "provider"
    assert entity["eligibility"]["provider_failure"]["normalized_reason"] == (
        "rate_limit"
    )
