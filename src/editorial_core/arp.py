"""The Autonomous Resolution Protocol: outcomes, counters, precedence (Issue #292).

The map's §6 says that nothing in a run waits for a person: every state the
engine cannot resolve ends in one of four outcomes, with its reason recorded.
This module is that protocol as code, and nothing else — it holds no stage
logic, and no stage decision is taken here. What it provides is the vocabulary
and the accounting every stage of slice SL-1 needs before it has any logic of
its own:

**OutcomeRecord** (Step 1 §0.3). One unresolved state, resolved: the outcome,
the machine ``state_code`` from the closed vocabulary below, the scope it
concerns, the counter it spent with its attempt and limit, and — for a
``REPLAN`` — the stage it routes to. The free-text ``reason`` stays in the
90-day workspace: the durable RunSummary carries the state code and a category
and never free text (Step 3 §3.3), which is what keeps it public-safe.

**PrecedenceApplication** (Step 1 §0.3, map §5). Which record won a conflict,
over what, and by which rule. Authority never flows uphill here, and a record
the loader demoted to ``weak-candidate`` cannot win its own tier unless a
non-expired record reinforces it (Step 4 §5.1).

**KnowledgeRef** (Step 1 §0.3, patch S4-R1). A record as it was *at the time of
use*: its tier, the status in its file and the effective status the loader
computed, so that the trace shows demoted knowledge losing rather than leaving
a reader to recompute expiry from today's clock.

**Attempt counters** (Step 2 §0.3). ``L_enrich``, ``L_boundary``, ``L_anchor``,
``L_strategy`` and ``L_edit``, spent per scope key by
:class:`AttemptCounterLedger`. Every backward route consumes one, no counter is
ever reset inside a run, and the route table in the topology registry — not
this module — says where each route goes and what its exhaustion does. That is
why forced exhaustion produces one specified outcome rather than whatever the
calling stage believes: the contract is in the registry, the accounting is
here.

The **PrecedenceLog** and the outcome log (U-3, Step 3 §4.1) are not separate
files. They live inside the StageRecords, and :func:`precedence_log` and
:func:`outcome_log` are the ordered views over a run's trace, each entry
carrying the stage and scope key the application or the outcome came from.

``RunCallBudget`` is deliberately absent: it is the run-scoped spend limit
owned by ``src/run/call_budget.py``, it bounds every route rather than
belonging to one, and turning its refusal into a ``SKIP`` is
``src/run/call_budget_arp.py``. Its name is fixed here (§0.3 lists it in the
counter table) so that the trace spells it one way.

Sources: ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §5 (precedence) and
§6 (the protocol); ``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md``
§0.3; ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.3, §0.6,
§5.3 and §5.5; ``docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md``
§2.3 and §5.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.editorial_core.topology import (
    CANONICAL_TOPOLOGY,
    ReplanRoute,
    StageTopology,
    TerminalOutcome,
)

_STAGE_ID_PATTERN = r"^S-(?:0\d|1[0-5])$"

#: How the run-scoped spend limit is named where a counter is named (§0.3). It
#: is not an attempt counter and no route spends it, so it is a string here
#: rather than a member of the topology's counter registry.
RUN_CALL_BUDGET_COUNTER = "RunCallBudget"


class ArpError(RuntimeError):
    """The protocol was asked for something its contract refuses."""


class ArpOutcome(str, Enum):
    """The four outcomes (map §6.1). There is no fifth, and none of them waits.

    ``RESOLVE`` the state is resolved on evidence. ``DEGRADE`` proceed with the
    safest admissible option, low confidence recorded. ``REPLAN`` return to the
    layer that made the wrong decision (I-09), with a limited number of
    attempts. ``SKIP`` the signal, unit, destination or publication is not
    released, and the reason is recorded.
    """

    RESOLVE = "RESOLVE"
    DEGRADE = "DEGRADE"
    REPLAN = "REPLAN"
    SKIP = "SKIP"


class OutcomeScope(str, Enum):
    """What an outcome concerns (Step 1 §0.3).

    Deliberately not :class:`~src.editorial_core.topology.CounterScope`, which
    also counts per text: a text is where an edit is counted, while what a
    failed edit costs is the publication.
    """

    SIGNAL = "signal"
    UNIT = "unit"
    DESTINATION = "destination"
    PUBLICATION = "publication"


class StateCode(str, Enum):
    """The closed vocabulary of unresolved states (map §6.2).

    Closed on purpose: the durable RunSummary counts skips and degrades by
    state code, so a free-text state would make the main indicator of
    autonomous operation (map §6.3) uncountable. Several codes come from Step 2
    rather than from §6.2, because Step 2 names them as reasons of their own:
    ``budget_exhausted`` (§0.4), ``boundary_reentry_exhausted`` (§0.3),
    ``source_not_eligible`` (§1, S-00's ARP column) and the S-01 states at the
    end of this vocabulary (§1, S-01's ARP column).

    Later slices add the states their stages need. A stage may not invent one
    in passing: a new state is a new member here, reviewed with the contract
    that produces it.
    """

    SIGNAL_OUTSIDE_CONTRACT = "signal_outside_contract"
    SOURCE_NOT_ELIGIBLE = "source_not_eligible"
    NO_ASSET_OR_ADMISSIBLE_INTERPRETATION = "no_asset_or_admissible_interpretation"
    CLIENT_POSITION_MISSING = "client_position_missing"
    EVIDENCE_CONFLICT_OUTSIDE_ANCHOR = "evidence_conflict_outside_anchor"
    EVIDENCE_CONFLICT_IN_ANCHOR = "evidence_conflict_in_anchor"
    HIGH_STAKES_OUTSIDE_RISK_LEVEL = "high_stakes_outside_risk_level"
    CLIENT_RULES_CONFLICT = "client_rules_conflict"
    SEVERAL_EQUAL_STRATEGIES = "several_equal_strategies"
    NO_ADMISSIBLE_STRATEGY = "no_admissible_strategy"
    PROMISE_WIDER_THAN_BOUNDARY = "promise_wider_than_boundary"
    DESTINATIONS_CONTRADICT = "destinations_contradict"
    PLAN_DOES_NOT_HOLD = "plan_does_not_hold"
    STRUCTURAL_TEXT_FAILURE = "structural_text_failure"
    INVENTED_OR_INADMISSIBLE_INTERPRETATION = "invented_or_inadmissible_interpretation"
    FACT_OR_PHRASING_FAILURE = "fact_or_phrasing_failure"
    PLATFORM_KNOWLEDGE_EXPIRED = "platform_knowledge_expired"
    MANDATORY_KNOWLEDGE_EXCEEDS_CAPACITY = "mandatory_knowledge_exceeds_capacity"
    BUDGET_EXHAUSTED = "budget_exhausted"
    BOUNDARY_REENTRY_EXHAUSTED = "boundary_reentry_exhausted"
    #: The model provider refused or could not be reached: a rate limit, an
    #: authentication failure, a connection failure, a provider outage. It is
    #: not a statement about the material. `source_eligibility.py` already
    #: draws this line — its `SourceEligibilityError.scope` separates a
    #: candidate-local judgment failure from a provider-wide one — and a stage
    #: that flattened the two would record "this source was not eligible"
    #: about a source nobody managed to read.
    #:
    #: The name is the one this repository already uses for the condition:
    #: `ErrorCategory.PROVIDER_UNAVAILABLE` on the publication side, and the
    #: `provider_unavailable` disposition the live sweep writes.
    PROVIDER_UNAVAILABLE = "provider_unavailable"

    # -- S-01 · Evidence Core and relevance screen (Step 2 §1, ARP) --------
    #: Retrieval produced no artifact this run may reason from: a
    #: `FailedResearchResult`, or an envelope whose lineage is not this run's.
    #: Step 2 §1 names this reason `research_failed`.
    RESEARCH_FAILED = "research_failed"
    #: The extended evidence assessment produced no admissible judgment, so no
    #: record was assessed and no strength was placed on the ladder. It says
    #: nothing about the material: `assess_artifact` fails closed rather than
    #: promoting anything, and persists the artifact exactly as retrieved.
    EVIDENCE_ASSESSMENT_FAILED = "evidence_assessment_failed"
    #: The core was built and holds no `accepted` or `qualified` claim (E-03's
    #: usability rule). This is the state that says the material was thin, and
    #: it is the only one of S-01's that says it.
    NO_USABLE_EVIDENCE_CLAIM = "no_usable_evidence_claim"
    #: The #58 relevance screen produced no admissible judgment at all: the
    #: provider failed, or the answer did not satisfy the decision contract, so
    #: no decision artifact exists. Not a verdict about the audience.
    RELEVANCE_SCREEN_FAILED = "relevance_screen_failed"
    #: Disposition `revise` or `hold`: relevance is not established and the
    #: screen's own reasons name what is missing. The one S-01 state that is not
    #: terminal — §1 routes it into S-03 while `L_enrich` allows, and I-01 makes
    #: that a REPLAN rather than the wait the current engine takes.
    RELEVANCE_NOT_ESTABLISHED = "relevance_not_established"
    #: Disposition `reject`, or relevance `irrelevant`: the screen refused the
    #: signal for the configured audience. Both are one row of §1's ARP column,
    #: and both are the audience question answered — not the evidence one.
    SIGNAL_NOT_RELEVANT = "signal_not_relevant"
    #: Disposition `insufficient_evidence`: the claims may be usable and still
    #: not carry an audience judgment. Kept apart from
    #: `no_usable_evidence_claim`, which is about the core holding nothing
    #: usable at all; a client reading the skip rate is owed the difference.
    RELEVANCE_EVIDENCE_INSUFFICIENT = "relevance_evidence_insufficient"


#: Which outcomes each state may end in. The union of two columns: the outcome
#: map §6.2 gives the state, and the terminal outcome Step 2 §5.3 gives its
#: route when the counter runs out — a state that ``REPLAN``s at all can
#: therefore also ``SKIP``. Validating against it is what stops a stage from
#: recording, say, a ``RESOLVE`` for a signal that does not fit the contract.
_PERMITTED_OUTCOMES: Mapping[StateCode, frozenset[ArpOutcome]] = {
    StateCode.SIGNAL_OUTSIDE_CONTRACT: frozenset({ArpOutcome.SKIP}),
    # Step 2 §1, S-00: "Source not eligible → SKIP signal (terminal)". The
    # judgment fails closed, so there is nothing to degrade to and nowhere to
    # replan: a source the role may not start from stays one however often it
    # is asked about.
    StateCode.SOURCE_NOT_ELIGIBLE: frozenset({ArpOutcome.SKIP}),
    StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION: frozenset({
        ArpOutcome.RESOLVE,
        ArpOutcome.REPLAN,
        ArpOutcome.SKIP,
    }),
    StateCode.CLIENT_POSITION_MISSING: frozenset({
        ArpOutcome.DEGRADE,
        ArpOutcome.SKIP,
    }),
    StateCode.EVIDENCE_CONFLICT_OUTSIDE_ANCHOR: frozenset({ArpOutcome.DEGRADE}),
    StateCode.EVIDENCE_CONFLICT_IN_ANCHOR: frozenset({
        ArpOutcome.RESOLVE,
        ArpOutcome.DEGRADE,
        ArpOutcome.REPLAN,
        ArpOutcome.SKIP,
    }),
    StateCode.HIGH_STAKES_OUTSIDE_RISK_LEVEL: frozenset({ArpOutcome.SKIP}),
    StateCode.CLIENT_RULES_CONFLICT: frozenset({ArpOutcome.DEGRADE}),
    StateCode.SEVERAL_EQUAL_STRATEGIES: frozenset({
        ArpOutcome.RESOLVE,
        ArpOutcome.DEGRADE,
    }),
    StateCode.NO_ADMISSIBLE_STRATEGY: frozenset({
        ArpOutcome.REPLAN,
        ArpOutcome.SKIP,
    }),
    StateCode.PROMISE_WIDER_THAN_BOUNDARY: frozenset({
        ArpOutcome.REPLAN,
        ArpOutcome.SKIP,
    }),
    StateCode.DESTINATIONS_CONTRADICT: frozenset({
        ArpOutcome.REPLAN,
        ArpOutcome.SKIP,
    }),
    StateCode.PLAN_DOES_NOT_HOLD: frozenset({ArpOutcome.REPLAN, ArpOutcome.SKIP}),
    StateCode.STRUCTURAL_TEXT_FAILURE: frozenset({
        ArpOutcome.REPLAN,
        ArpOutcome.SKIP,
    }),
    StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION: frozenset({
        ArpOutcome.REPLAN,
        ArpOutcome.SKIP,
    }),
    StateCode.FACT_OR_PHRASING_FAILURE: frozenset({
        ArpOutcome.REPLAN,
        ArpOutcome.SKIP,
    }),
    # Expiry is applied when knowledge is loaded, so §5.5 needs no stage
    # outcome for it. A stage that does record the demotion records a DEGRADE:
    # it proceeded on a weaker input.
    StateCode.PLATFORM_KNOWLEDGE_EXPIRED: frozenset({ArpOutcome.DEGRADE}),
    # Step 4 §9.6: the knowledge that may never be truncated did not fit the
    # request. There is nothing to degrade to — a hard-policy surface with a
    # hole in it is not a weaker input, it is a different rule set — so the
    # stage fails closed before the call and the scope is skipped.
    StateCode.MANDATORY_KNOWLEDGE_EXCEEDS_CAPACITY: frozenset({ArpOutcome.SKIP}),
    StateCode.BUDGET_EXHAUSTED: frozenset({ArpOutcome.SKIP}),
    StateCode.BOUNDARY_REENTRY_EXHAUSTED: frozenset({ArpOutcome.SKIP}),
    # Nothing to degrade to and nothing to replan: no verdict was produced, so
    # there is no weaker reading to fall back on. The scope is skipped, and the
    # state says why, so that a later caller walking a queue can tell this from
    # a source its own role turned away.
    StateCode.PROVIDER_UNAVAILABLE: frozenset({ArpOutcome.SKIP}),
    # Step 2 §1, S-01. Four of its five states are terminal for the same
    # reason: there is no weaker reading of material nobody retrieved, of a
    # judgment nobody made, or of an audience the screen refused, and S-01 has
    # no counter of its own ("None of its own", §1 Limits).
    StateCode.RESEARCH_FAILED: frozenset({ArpOutcome.SKIP}),
    StateCode.EVIDENCE_ASSESSMENT_FAILED: frozenset({ArpOutcome.SKIP}),
    StateCode.NO_USABLE_EVIDENCE_CLAIM: frozenset({ArpOutcome.SKIP}),
    StateCode.RELEVANCE_SCREEN_FAILED: frozenset({ArpOutcome.SKIP}),
    # The exception, and the whole point of R-1: `revise`/`hold` is "not a
    # wait" but a REPLAN into S-03 with a gap, and a SKIP once `L_enrich` is
    # exhausted. Both outcomes keep this state code, because what was never
    # established is still relevance when the last attempt is spent.
    StateCode.RELEVANCE_NOT_ESTABLISHED: frozenset({
        ArpOutcome.REPLAN,
        ArpOutcome.SKIP,
    }),
    StateCode.SIGNAL_NOT_RELEVANT: frozenset({ArpOutcome.SKIP}),
    StateCode.RELEVANCE_EVIDENCE_INSUFFICIENT: frozenset({ArpOutcome.SKIP}),
}


def permitted_outcomes(state_code: StateCode) -> frozenset[ArpOutcome]:
    """The outcomes the map and Step 2 allow for one state."""

    return _PERMITTED_OUTCOMES[state_code]


# ===========================================================================
# Knowledge and precedence (map §5, Step 4 §2.3 and §5)
# ===========================================================================


class KnowledgeTier(str, Enum):
    """Authority, not confidence (map §5). The higher tier wins a conflict.

    ``ARCHITECTURAL`` is Step 4's tier ``A``, which the map's ladder does not
    list. It is recorded like any other tier and left out of the authority
    comparison below: placing it in the ladder would be an architecture
    decision, and this slice has no business taking one.
    """

    EVIDENCE = "0a"
    LAW = "0b"
    ETHICS = "0c"
    HARD_PLATFORM_POLICY = "1"
    APPROVED_CLIENT_RULE = "2"
    EDITORIAL = "3"
    PLATFORM_RANKING = "4"
    PORTFOLIO = "5"
    STYLE = "6"
    ARCHITECTURAL = "A"


#: The map §5 ladder, strongest first. Tier A is absent by the reasoning in
#: :class:`KnowledgeTier`.
_TIER_LADDER: tuple[KnowledgeTier, ...] = (
    KnowledgeTier.EVIDENCE,
    KnowledgeTier.LAW,
    KnowledgeTier.ETHICS,
    KnowledgeTier.HARD_PLATFORM_POLICY,
    KnowledgeTier.APPROVED_CLIENT_RULE,
    KnowledgeTier.EDITORIAL,
    KnowledgeTier.PLATFORM_RANKING,
    KnowledgeTier.PORTFOLIO,
    KnowledgeTier.STYLE,
)

_TIER_RANK: Mapping[KnowledgeTier, int] = {
    tier: rank for rank, tier in enumerate(_TIER_LADDER)
}


def tier_rank(tier: KnowledgeTier) -> Optional[int]:
    """Where a tier sits on the map §5 ladder: 0 is strongest.

    ``None`` for a tier the ladder does not place, which today is only
    :attr:`KnowledgeTier.ARCHITECTURAL`. A caller that orders records has to
    say what it does with one rather than assume a position for it, which is
    the same reason the precedence check above declines to compare it.
    """

    return _TIER_RANK.get(tier)


class KnowledgeStatus(str, Enum):
    """The closed status vocabulary (Step 4 §2.3).

    ``WEAK_CANDIDATE`` is set only by the loader, for a ``descriptive`` or
    ``candidate`` record past its ``review_by`` (§5). It is never written in a
    file, which is why a KnowledgeRef carries both statuses.
    """

    INVARIANT = "invariant"
    APPROVED_RULE = "approved-rule"
    DESCRIPTIVE = "descriptive"
    CANDIDATE = "candidate"
    WEAK_CANDIDATE = "weak-candidate"
    RETIRED = "retired"


#: The two file statuses expiry demotes (§5). The others stay in force, flagged
#: for review: dropping a hard rule because nobody re-checked it is the unsafe
#: direction.
_DEMOTABLE_STATUSES = frozenset({
    KnowledgeStatus.DESCRIPTIVE,
    KnowledgeStatus.CANDIDATE,
})


class _ArpRecord(BaseModel):
    """Every protocol record is immutable and rejects fields it does not know."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class KnowledgeRef(_ArpRecord):
    """One knowledge record as it was at the time of use (patch S4-R1)."""

    record_id: str = Field(min_length=1)
    record_version: int = Field(ge=1)
    tier: KnowledgeTier
    #: The status written in the record's file.
    file_status: KnowledgeStatus
    #: What the loader made of it for this run.
    effective_status: KnowledgeStatus
    #: The non-expired record that lets a weak candidate count at its original
    #: weight (§5.1 rule 3). Absent when there is none.
    reinforced_by: Optional[str] = None

    @model_validator(mode="after")
    def _as_it_was_loaded(self) -> "KnowledgeRef":
        if KnowledgeStatus.RETIRED in (self.file_status, self.effective_status):
            raise ValueError(
                f"{self.record_id} is retired, and a retired record is never "
                "loaded into a run (Step 4 §2.3): a reference to one could "
                "only have come from outside the loader"
            )
        if self.file_status is KnowledgeStatus.WEAK_CANDIDATE:
            raise ValueError(
                f"{self.record_id} claims weak-candidate as its file status; "
                "that status is set only by the loader and is never written in "
                "a file (Step 4 §2.3)"
            )
        if self.effective_status != self.file_status:
            if self.effective_status is not KnowledgeStatus.WEAK_CANDIDATE:
                raise ValueError(
                    f"{self.record_id} was loaded as "
                    f"{self.effective_status.value!r} from file status "
                    f"{self.file_status.value!r}; the only demotion §5 makes "
                    "is to weak-candidate"
                )
            if self.file_status not in _DEMOTABLE_STATUSES:
                raise ValueError(
                    f"{self.record_id} was demoted to weak-candidate from file "
                    f"status {self.file_status.value!r}; §5 demotes only "
                    "descriptive and candidate records, and keeps the rest in "
                    "force"
                )
        if self.reinforced_by is not None:
            if not self.reinforced_by.strip():
                raise ValueError("reinforced_by must name a record, or be absent")
            if self.effective_status is not KnowledgeStatus.WEAK_CANDIDATE:
                raise ValueError(
                    f"{self.record_id} is not a weak candidate, so it is not "
                    "reinforced by anything: reinforcement is what lets a "
                    "demoted record count at its original weight (§5.1 rule 3)"
                )
        return self


class PrecedenceApplication(_ArpRecord):
    """One conflict resolved by precedence, recorded (map §5 rule 3, U-3)."""

    #: What the conflict was, in the words of the stage that met it.
    conflict: str = Field(min_length=1)
    winner: KnowledgeRef
    loser: KnowledgeRef
    #: The rule that decided it: a map §5 rule, or a weak-candidate rule from
    #: Step 4 §5.1.
    rule_applied: str = Field(min_length=1)

    @model_validator(mode="after")
    def _authority_does_not_flow_uphill(self) -> "PrecedenceApplication":
        if self.winner.record_id == self.loser.record_id:
            raise ValueError(
                f"{self.winner.record_id} cannot win a conflict with itself"
            )
        winner_rank = _TIER_RANK.get(self.winner.tier)
        loser_rank = _TIER_RANK.get(self.loser.tier)
        if winner_rank is None or loser_rank is None:
            return self
        if winner_rank > loser_rank:
            raise ValueError(
                f"tier {self.winner.tier.value} ({self.winner.record_id}) is "
                f"recorded as winning over tier {self.loser.tier.value} "
                f"({self.loser.record_id}); in a conflict the higher tier wins "
                "(map §5)"
            )
        if (
            winner_rank == loser_rank
            and self.winner.effective_status is KnowledgeStatus.WEAK_CANDIDATE
            and self.loser.effective_status is not KnowledgeStatus.WEAK_CANDIDATE
            and self.winner.reinforced_by is None
        ):
            raise ValueError(
                f"{self.winner.record_id} is a weak candidate and is recorded "
                f"as winning over {self.loser.record_id}, which is not; a weak "
                "candidate loses to any non-expired record of its own tier "
                "unless a non-expired record reinforces it (Step 4 §5.1)"
            )
        return self


# ===========================================================================
# OutcomeRecord (Step 1 §0.3)
# ===========================================================================


class OutcomeRecord(_ArpRecord):
    """One unresolved state and what the protocol did about it.

    Stored in the trace, inside the StageRecord of the execution that produced
    it, and referenced from the entity it concerns.
    """

    outcome: ArpOutcome
    state_code: StateCode
    scope: OutcomeScope
    #: Which signal, unit, destination or publication. Absent means the scope
    #: key of the StageRecord that carries it; present when a stage records an
    #: outcome for a sibling scope, as budget exhaustion does for the
    #: destinations it skips without starting them (§0.4).
    scope_key: Optional[str] = None
    #: Free text, and therefore workspace-only: the durable RunSummary carries
    #: the state code and a closed category instead (Step 3 §3.3).
    reason: Optional[str] = None
    knowledge: tuple[KnowledgeRef, ...] = ()
    precedence: Optional[PrecedenceApplication] = None
    #: The counter this outcome spent: an attempt counter from the topology
    #: registry, or :data:`RUN_CALL_BUDGET_COUNTER`.
    counter: Optional[str] = None
    attempt: Optional[int] = Field(default=None, ge=1)
    limit: Optional[int] = Field(default=None, ge=1)
    #: Where a ``REPLAN`` goes. Only a ``REPLAN`` goes anywhere.
    route_target: Optional[str] = Field(default=None, pattern=_STAGE_ID_PATTERN)

    @model_validator(mode="after")
    def _internally_consistent(self) -> "OutcomeRecord":
        if self.outcome not in _PERMITTED_OUTCOMES[self.state_code]:
            allowed = ", ".join(
                sorted(item.value for item in _PERMITTED_OUTCOMES[self.state_code])
            )
            raise ValueError(
                f"state {self.state_code.value!r} cannot end in "
                f"{self.outcome.value}; the map and Step 2 §5.3 allow {allowed}"
            )
        if self.scope_key is not None and not self.scope_key.strip():
            raise ValueError(
                "scope_key must name the scope, or be absent and mean the "
                "stage record's own"
            )
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must say something, or be absent")
        if (self.outcome is ArpOutcome.REPLAN) != (self.route_target is not None):
            raise ValueError(
                "a route target belongs to a REPLAN and to nothing else: "
                f"{self.outcome.value} with route_target={self.route_target!r}"
            )
        if self.outcome is ArpOutcome.REPLAN and self.counter is None:
            raise ValueError(
                "a REPLAN spends a named counter (§0.3); an unbounded backward "
                "route is how a run loops forever"
            )
        if self.counter is not None and not self.counter.strip():
            raise ValueError("counter must be named, or be absent")
        if (self.counter is None) and (
            self.attempt is not None or self.limit is not None
        ):
            raise ValueError(
                f"attempt {self.attempt!r} of limit {self.limit!r} is recorded "
                "against no counter; a count without its counter cannot be read"
            )
        if self.counter is not None and (self.attempt is None or self.limit is None):
            raise ValueError(
                f"counter {self.counter!r} is recorded without its attempt and "
                "limit; §0.3 keeps both in the OutcomeRecord"
            )
        if (
            self.attempt is not None
            and self.limit is not None
            and self.attempt > self.limit
        ):
            raise ValueError(
                f"attempt {self.attempt} is past limit {self.limit}; a counter "
                "is never spent beyond its limit and is never reset in a run"
            )
        return self

    @property
    def exhausted(self) -> bool:
        """Did this outcome exhaust its counter?"""

        return self.attempt is not None and self.attempt == self.limit


# ===========================================================================
# The logs (U-3, Step 3 §4.1)
# ===========================================================================


class TracedStageExecution(Protocol):
    """What the logs need from a StageRecord.

    A protocol rather than an import: the StageRecord lives with the workspace
    that writes it (``src/run/run_workspace.py``), and it is that module which
    depends on the protocol's records, not the other way round.
    """

    @property
    def seq(self) -> int: ...

    @property
    def stage(self) -> str: ...

    @property
    def scope_key(self) -> str: ...

    @property
    def outcomes(self) -> tuple[OutcomeRecord, ...]: ...

    @property
    def precedence(self) -> tuple[PrecedenceApplication, ...]: ...


class _LogEntry(_ArpRecord):
    """Where in the run one logged item came from."""

    seq: int = Field(ge=0)
    stage: str = Field(pattern=_STAGE_ID_PATTERN)
    scope_key: str = Field(min_length=1)


class LoggedOutcome(_LogEntry):
    """One entry of the outcome log."""

    outcome: OutcomeRecord


class LoggedPrecedence(_LogEntry):
    """One entry of the PrecedenceLog (U-3): stage, scope key, application."""

    application: PrecedenceApplication


def outcome_log(
    executions: Iterable[TracedStageExecution],
) -> tuple[LoggedOutcome, ...]:
    """Every OutcomeRecord of a run, in execution order.

    Ordered by ``seq`` rather than by the order the records were handed over:
    the trace's own order is the run's order, and a caller that read the
    workspace directory has no other claim to it.
    """

    return tuple(
        LoggedOutcome(
            seq=execution.seq,
            stage=execution.stage,
            scope_key=execution.scope_key,
            outcome=outcome,
        )
        for execution in _in_execution_order(executions)
        for outcome in execution.outcomes
    )


def precedence_log(
    executions: Iterable[TracedStageExecution],
) -> tuple[LoggedPrecedence, ...]:
    """The PrecedenceLog of a run: every application, in execution order.

    U-3 keeps this out of ``DecisionPolicyRecord``, which proves five things
    and nothing else, and out of ``stage_routing``, which proves what material
    reached a stage rather than what the stage decided.
    """

    return tuple(
        LoggedPrecedence(
            seq=execution.seq,
            stage=execution.stage,
            scope_key=execution.scope_key,
            application=application,
        )
        for execution in _in_execution_order(executions)
        for application in execution.precedence
    )


def _in_execution_order(
    executions: Iterable[TracedStageExecution],
) -> list[TracedStageExecution]:
    return sorted(executions, key=lambda execution: execution.seq)


# ===========================================================================
# Attempt counters (Step 2 §0.3, §5.3)
# ===========================================================================


#: Step 2 §0.3 names one exhaustion reason of its own: when ``L_boundary`` runs
#: out, the destination whose text caused the re-entry is skipped with reason
#: ``boundary_reentry_exhausted``. Every other counter's exhaustion keeps the
#: state code of the state that was never resolved — "no admissible strategy"
#: is still what happened when ``L_strategy`` ran out.
_EXHAUSTION_STATE_CODE: Mapping[str, StateCode] = {
    "L_boundary": StateCode.BOUNDARY_REENTRY_EXHAUSTED,
}

#: What each terminal outcome of the route table means as an ARP outcome and a
#: scope. ``DEGRADE_OR_SKIP_UNIT`` is the one route whose end is decided on the
#: evidence rather than by the counter, so it names two outcomes and the caller
#: has to state which of them it took.
_TERMINAL_OUTCOMES: Mapping[
    TerminalOutcome, tuple[frozenset[ArpOutcome], OutcomeScope]
] = {
    TerminalOutcome.SKIP_SIGNAL: (
        frozenset({ArpOutcome.SKIP}),
        OutcomeScope.SIGNAL,
    ),
    TerminalOutcome.SKIP_UNIT: (
        frozenset({ArpOutcome.SKIP}),
        OutcomeScope.UNIT,
    ),
    TerminalOutcome.SKIP_DESTINATION: (
        frozenset({ArpOutcome.SKIP}),
        OutcomeScope.DESTINATION,
    ),
    TerminalOutcome.SKIP_PUBLICATION: (
        frozenset({ArpOutcome.SKIP}),
        OutcomeScope.PUBLICATION,
    ),
    TerminalOutcome.DEGRADE_OR_SKIP_UNIT: (
        frozenset({ArpOutcome.DEGRADE, ArpOutcome.SKIP}),
        OutcomeScope.UNIT,
    ),
}


class AttemptCounterLedger:
    """The run's attempt counters, and the only thing that spends them.

    One instance per run: "reset" is construction, exactly as it is for
    ``RunCallBudget``, because §5.3's termination argument rests on no counter
    ever being reset inside a run.

    A counter is counted per **scope key**, so two destinations spend
    ``L_strategy`` independently while two attempts on one destination spend
    the same one. The key must therefore identify the scope and not the attempt.

    The ledger does not decide anything editorial. It looks the route up in the
    topology registry, spends the counter that route declares, and — when the
    counter is gone — returns the outcome the registry says that route ends in.
    A stage cannot talk it into a different one, which is what makes forced
    exhaustion produce the specified outcome rather than a plausible one.
    """

    def __init__(
        self,
        *,
        limits: Optional[Mapping[str, int]] = None,
        topology: StageTopology = CANONICAL_TOPOLOGY,
    ) -> None:
        self._topology = topology
        self._limits: dict[str, int] = {
            counter.counter_id: counter.default_limit for counter in topology.counters
        }
        for counter_id, limit in (limits or {}).items():
            if counter_id not in self._limits:
                raise ArpError(
                    f"unknown counter {counter_id!r}; the topology declares "
                    f"{', '.join(sorted(self._limits))}"
                )
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                raise ArpError(
                    f"limit for {counter_id} must be an integer of at least 1; "
                    f"got {limit!r}"
                )
            self._limits[counter_id] = limit
        self._spent: dict[tuple[str, str], int] = {}

    def limit(self, counter_id: str) -> int:
        """The limit in force for one counter (§0.3 default, or the override)."""

        try:
            return self._limits[counter_id]
        except KeyError:
            raise ArpError(
                f"unknown counter {counter_id!r}; the topology declares "
                f"{', '.join(sorted(self._limits))}"
            ) from None

    def used(self, counter_id: str, scope_key: str) -> int:
        """How much of one counter this scope has spent."""

        return self._spent.get((counter_id, self._validated(scope_key)), 0)

    def remaining(self, counter_id: str, scope_key: str) -> int:
        """How much of one counter this scope has left."""

        return self.limit(counter_id) - self.used(counter_id, scope_key)

    def exhausted(self, counter_id: str, scope_key: str) -> bool:
        """Has this scope spent the whole counter?"""

        return self.remaining(counter_id, scope_key) <= 0

    def route(
        self,
        *,
        source: str,
        cause: str,
        scope_key: str,
        state_code: StateCode,
        reason: Optional[str] = None,
        knowledge: Iterable[KnowledgeRef] = (),
        precedence: Optional[PrecedenceApplication] = None,
        on_exhaustion: Optional[ArpOutcome] = None,
    ) -> OutcomeRecord:
        """Take one declared route, or record the outcome it ends in.

        Returns a ``REPLAN`` while the route's counter has an attempt left, and
        the route's terminal outcome once it has not. ``on_exhaustion`` is for
        the single route the contract ends in either a ``DEGRADE`` or a
        ``SKIP``: the choice is made on the evidence, so the caller states it,
        and every other route refuses the argument outright.
        """

        route = self._route(source, cause)
        key = (route.counter, self._validated(scope_key))
        limit = self._limits[route.counter]
        permitted, scope = _TERMINAL_OUTCOMES[route.on_exhaustion]
        if on_exhaustion is not None and len(permitted) == 1:
            raise ArpError(
                f"route {source}→{route.target} ({cause}) ends in "
                f"{route.on_exhaustion.value} by contract; a caller may not "
                "choose the outcome of its exhaustion"
            )

        used = self._spent.get(key, 0)
        if used >= limit:
            return OutcomeRecord(
                outcome=self._terminal(route, permitted, on_exhaustion),
                state_code=_EXHAUSTION_STATE_CODE.get(route.counter, state_code),
                scope=scope,
                scope_key=scope_key,
                reason=reason,
                knowledge=tuple(knowledge),
                precedence=precedence,
                counter=route.counter,
                attempt=limit,
                limit=limit,
            )

        self._spent[key] = used + 1
        return OutcomeRecord(
            outcome=ArpOutcome.REPLAN,
            state_code=state_code,
            scope=scope,
            scope_key=scope_key,
            reason=reason,
            knowledge=tuple(knowledge),
            precedence=precedence,
            counter=route.counter,
            attempt=used + 1,
            limit=limit,
            route_target=route.target,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _route(self, source: str, cause: str) -> ReplanRoute:
        for route in self._topology.replan_routes:
            if route.source == source and route.cause == cause:
                return route
        raise ArpError(
            f"no declared route leaves {source} for cause {cause!r}; the route "
            "table in the topology registry is the whole set of routes a run "
            "may take, and an undeclared one is a second engine"
        )

    @staticmethod
    def _terminal(
        route: ReplanRoute,
        permitted: frozenset[ArpOutcome],
        on_exhaustion: Optional[ArpOutcome],
    ) -> ArpOutcome:
        if len(permitted) == 1:
            return next(iter(permitted))
        if on_exhaustion is None:
            raise ArpError(
                f"route {route.source}→{route.target} ({route.cause}) ends in "
                f"{route.on_exhaustion.value}: state which of them the "
                "evidence gave, because the counter cannot decide it"
            )
        if on_exhaustion not in permitted:
            allowed = ", ".join(sorted(item.value for item in permitted))
            raise ArpError(
                f"route {route.source}→{route.target} ({route.cause}) may end "
                f"in {allowed}; got {on_exhaustion.value}"
            )
        return on_exhaustion

    @staticmethod
    def _validated(scope_key: str) -> str:
        if not isinstance(scope_key, str) or not scope_key.strip():
            raise ArpError(
                "a counter is spent per scope key, so the key must name the "
                f"scope; got {scope_key!r}"
            )
        return scope_key
