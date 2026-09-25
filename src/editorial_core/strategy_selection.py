"""S-09 · Strategy selection: exclude by rule, then choose by tie-breaker.

The destination-scope stage that turns S-08's candidate set into one chosen
strategy. Step 2 §3 gives it the two halves and forbids it the third: "exclude
inadmissible candidates with a recorded reason, then choose one by the
tie-breaker order (map §7.3). **It must not edit candidates.**"

Code first, and only then a model
---------------------------------
§3's Decider column: "``code`` first: deterministic exclusions (V-P02 promise
versus boundary, tier 0–2 conflicts, the code part of V-P01). If one admissible
candidate remains, it is chosen. If several remain, ``model`` ranks them against
the tie-breakers as explicit criteria. Portfolio and cost tie-breakers are
computed by ``code``." The call count follows from it and is not a separate
decision: "0 if at most one candidate remains after code exclusion; 1
otherwise", so the transport is reached only where the contract says a ranking
is needed.

The model is therefore asked the two questions code cannot answer — how well a
candidate fits the evidence, and how well it fits the destination — and the
remaining five rungs of §7.3 are arithmetic over entities this run already
holds. The ladder is applied in order and the rung that reduced the leaders to
one is recorded as ``deciding_tiebreaker``, which is what map §6.2 means by
"``RESOLVE`` via 'what decided the choice'".

A candidate keeps no credentials
--------------------------------
Every code exclusion is re-evaluated here against the boundary, core and
features **in front of S-09**, never against the versions the candidate was
written under. E-13 is immutable and records its ``boundary_ref``, and a
candidate written against an older E-09 that a commit has since narrowed is not
a candidate that stays admissible because it once was: patch R2's versioned
references exist precisely so that the comparison is made rather than assumed.

Weak knowledge cannot exclude
-----------------------------
Step 4 §5.1: "a weak-candidate alone excludes nothing and routes nowhere", and
"if a weak-candidate is the only record behind an exclusion or route, that
exclusion or route is not taken. The conflict is recorded as a hint instead."
:func:`acts_alone` is that rule, :attr:`StrategySelection.hints` is where the
conflict goes, and :func:`preference_acts_at` is rule 3 — a demoted record may
order candidates only from the asset-strength rung down, never at the three
rungs that rest on evidence, destination and interpretation risk.

The two routes out, and the unit rule
-------------------------------------
§3's ARP column gives S-09 one destination route and one unit route, and the
topology registry declares both: S-09 → S-08, cause ``no_admissible_candidate``,
spending ``L_strategy``, ending in ``skip_destination``; and S-09 → S-06, cause
``no_admissible_candidate_on_any_destination``, spending ``L_anchor``, ending in
``skip_unit``.

:func:`select_strategy` takes the first, per destination. :func:`review_unit_round`
takes the second, once per round, and it is a separate function because it is a
unit-scope judgment that no destination-scope execution can make: fix F-5
reconciles the map's "no admissible strategy → REPLAN S-06" with AD-02 by
distinguishing one destination failing from all of them failing in the **same
round**. It fires only when every eligible destination *established* that it has
no admissible candidate. A destination the budget or a provider stopped short
established nothing, and spending ``L_anchor`` on that would charge the anchor
for an outage.

**Production safety.** At most one model call per destination, no external call,
and nothing calls this stage: the run harness still executes S-09 as the SL-1
pass-through, and wiring the stages of SL-5 into it is a later slice.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.3, §3
(S-09), §5.3 and §5.5 (F-5);
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §4 (StrategySelection,
fix F-1) and §6 (I-05, I-10, I-11);
``docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md`` §5.1;
``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §5, §6.2, §7.3, §11 (V-P01,
V-P02).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    KnowledgeRef,
    KnowledgeStatus,
    KnowledgeTier,
    OutcomeRecord,
    OutcomeScope,
    PrecedenceApplication,
    StateCode,
    tier_rank,
)
from src.editorial_core.candidate_strategies import (
    CandidateSet,
    ContractRule,
    EditorialStrategy,
    FocalSubjectKind,
    RevealKind,
    StrategyContract,
    strategies_relative_path,
)
from src.editorial_core.destinations import Destination, destination_scope_key
from src.editorial_core.evidence_core import EvidenceCore
from src.editorial_core.interpretation_boundary import InterpretationBoundary
from src.editorial_core.material_features import (
    Asset,
    MaterialFeature,
    MaterialFeatures,
)
from src.editorial_core.signal_selection import CallBudget
from src.knowledge.loader import WEAK_CANDIDATE_ALONE
from src.run.run_manifest import EntityIndexEntry
from src.run.run_workspace import RunWorkspace

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-09"

#: What it is the sole producer of (§3, Outputs). Not an E-number: Step 1 §4
#: gives StrategySelection its own name beside E-13 rather than a place in the
#: entity numbering.
SELECTION_ENTITY_TYPE: Final[str] = "StrategySelection"

#: Where it lives, beside the candidates it selected among (§2.2).
SELECTION_FILE_NAME: Final[str] = "selection.json"

#: The counter the destination route spends (§0.3): "``L_strategy`` |
#: destination | 2". The limit in force is the ledger's, not this module's.
STRATEGY_COUNTER: Final[str] = "L_strategy"

#: The counter the unit route spends (§0.3): "``L_anchor`` | unit | 1".
ANCHOR_COUNTER: Final[str] = "L_anchor"

#: The two routes, as the topology registry declares them.
NO_ADMISSIBLE_CAUSE: Final[str] = "no_admissible_candidate"
UNIT_CAUSE: Final[str] = "no_admissible_candidate_on_any_destination"

#: Where a tier the map §5 ladder does not place sorts: last. Tier ``A`` is the
#: only one today, and :func:`~src.editorial_core.arp.tier_rank` declines to
#: compare it rather than guess a position — so a caller that orders records has
#: to say what it does with one, and this is this module saying it.
_UNPLACED_TIER: Final[int] = len(KnowledgeTier)


class SelectionError(RuntimeError):
    """S-09 was asked to decide something its contract cannot decide."""


# ===========================================================================
# The vocabularies (map §7.3, Step 1 §4)
# ===========================================================================


class TieBreaker(str, Enum):
    """The map §7.3 criteria, by their Step 1 §4 names."""

    EVIDENCE_FIT = "evidence_fit"
    DESTINATION_FIT = "destination_fit"
    INTERPRETATION_RISK = "interpretation_risk"
    ASSET_STRENGTH = "asset_strength"
    CLIENT_PREFERENCE = "client_preference"
    PORTFOLIO = "portfolio"
    COST = "cost"


#: "Tie-breakers are applied in order" (§7.3). The order is the contract, so it
#: is written once and every rung reads it from here.
TIE_BREAKER_ORDER: Final[tuple[TieBreaker, ...]] = (
    TieBreaker.EVIDENCE_FIT,
    TieBreaker.DESTINATION_FIT,
    TieBreaker.INTERPRETATION_RISK,
    TieBreaker.ASSET_STRENGTH,
    TieBreaker.CLIENT_PREFERENCE,
    TieBreaker.PORTFOLIO,
    TieBreaker.COST,
)

#: Step 4 §5.1 rule 3: a demoted record "can act only after the §7.3
#: tie-breakers that rest on evidence, destination and interpretation risk.
#: That is, at the portfolio/cost end, as a soft preference."
WEAK_CANDIDATE_EARLIEST_TIEBREAKER: Final[TieBreaker] = TieBreaker.ASSET_STRENGTH

#: The range the ranking call scores on. A closed scale rather than an open
#: one, because the ladder compares the scores of one set against each other
#: and nothing else.
FIT_MIN: Final[int] = 1
FIT_MAX: Final[int] = 5


class ExclusionReason(str, Enum):
    """Why ``code`` removed a candidate before any ranking (§3, Decider).

    Four reasons and no fifth: each is one of the deterministic exclusions §3
    names, and a reason outside them would be S-09 judging a candidate rather
    than applying a rule.
    """

    #: I-05 and the second half of V-P02: the strategy references a reading the
    #: boundary in front of S-09 does not admit.
    INADMISSIBLE_INTERPRETATION = "inadmissible_interpretation"
    #: V-P02's first half: "the number of points is no greater than the number
    #: of admissible interpretations".
    PROMISE_WIDER_THAN_BOUNDARY = "promise_wider_than_boundary"
    #: The code part of V-P01: fields that do not hold together, or references
    #: this run cannot resolve.
    FIELD_INCONSISTENCY = "field_inconsistency"
    #: A tier 0–2 rule of the Client Contract forbids what this candidate
    #: decided.
    CONTRACT_PROHIBITION = "contract_prohibition"


#: The tier each reason acts from (map §5). The first three are the evidence
#: layer's: the core and the boundary are what makes them true, and nothing a
#: client or a platform writes overrules them. A contract prohibition carries
#: the tier of the rule that made it, which is why it is absent here.
_REASON_TIERS: Mapping[ExclusionReason, KnowledgeTier] = {
    ExclusionReason.INADMISSIBLE_INTERPRETATION: KnowledgeTier.EVIDENCE,
    ExclusionReason.PROMISE_WIDER_THAN_BOUNDARY: KnowledgeTier.EVIDENCE,
    ExclusionReason.FIELD_INCONSISTENCY: KnowledgeTier.EVIDENCE,
}


class DegradeReason(str, Enum):
    """Why a choice was a ``DEGRADE`` and not a ``RESOLVE`` (§3, ARP).

    Two facts a reader would otherwise have to guess apart, and the difference
    matters: one says the criteria were applied and left the leaders equal, the
    other says nobody applied them. Recorded as a field rather than in the free
    text, because ``reason`` stays in the 90-day workspace (Step 3 §3.3) and a
    distinction kept only there cannot be read back.
    """

    #: Every rung of §7.3 was applied and more than one leader survived all of
    #: them. "The model cannot separate the leaders" in the contract's words.
    LEADERS_INSEPARABLE = "leaders_inseparable"
    #: No ranking was produced at all: the transport failed, or the answer did
    #: not satisfy the contract. The ladder was never applied, and the safest
    #: admissible candidate is what is left rather than what was chosen.
    RANKING_UNAVAILABLE = "ranking_unavailable"


# ===========================================================================
# StrategySelection (Step 1 §4)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class Exclusion:
    """One candidate removed, with its reason, record and tier (Step 1 §4)."""

    strategy_id: str
    reason: ExclusionReason
    rule_ref: str
    tier: KnowledgeTier
    detail: str
    #: The record behind the rule, as it was at the time of use. Present for a
    #: contract prohibition that cites one; absent where the rule is the
    #: evidence layer itself, which no register record stands in for.
    knowledge: Optional[KnowledgeRef] = None

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.rule_ref.strip():
            raise SelectionError(
                "an exclusion names the candidate it removed and the rule that "
                "removed it; AD-02's direction holds here too — exclusion only "
                "by recorded reason"
            )
        if not self.detail.strip():
            raise SelectionError(
                f"{self.strategy_id} is excluded by {self.rule_ref} with no "
                "detail; the reason is the whole value of a recorded exclusion"
            )
        expected = _REASON_TIERS.get(self.reason)
        if expected is not None and self.tier is not expected:
            raise SelectionError(
                f"{self.strategy_id} is excluded for {self.reason.value} at tier "
                f"{self.tier.value}; that reason is the evidence layer's "
                f"({expected.value}), and a second opinion about its tier is a "
                "second precedence ladder"
            )
        if self.knowledge is not None and self.knowledge.tier is not self.tier:
            raise SelectionError(
                f"{self.strategy_id} is excluded at tier {self.tier.value} citing "
                f"{self.knowledge.record_id} at tier {self.knowledge.tier.value}; "
                "the tier belongs to whoever wrote the record"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "strategy_ref": self.strategy_id,
            "reason": self.reason.value,
            "rule_ref": self.rule_ref,
            "tier": self.tier.value,
            "detail": self.detail,
            "knowledge": (
                None
                if self.knowledge is None
                else self.knowledge.model_dump(mode="json")
            ),
        }


@dataclass(frozen=True, slots=True)
class Hint:
    """A conflict that was recorded instead of taken (Step 4 §5.1 rule 1).

    A weak candidate nothing reinforces cannot by itself exclude anything. The
    conflict is not lost: it is written here with the rule that limited it, so
    that a keeper reading the trace can see which demoted record would have
    acted had somebody re-checked it.
    """

    strategy_id: str
    rule_ref: str
    knowledge: KnowledgeRef
    rule_applied: str
    detail: str

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.rule_ref.strip():
            raise SelectionError(
                "a hint names the candidate it would have excluded and the rule "
                "that would have excluded it"
            )
        if not self.detail.strip() or not self.rule_applied.strip():
            raise SelectionError(
                f"the hint about {self.strategy_id} records no detail or no rule; "
                "§5.1 rule 4 keeps the trace showing that demoted knowledge could "
                "not win"
            )
        if self.knowledge.effective_status is not KnowledgeStatus.WEAK_CANDIDATE:
            raise SelectionError(
                f"the hint about {self.strategy_id} cites "
                f"{self.knowledge.record_id}, which is not a weak candidate; a "
                "record that may act is recorded as the exclusion it made and "
                "not as a conflict nobody took"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "strategy_ref": self.strategy_id,
            "rule_ref": self.rule_ref,
            "knowledge": self.knowledge.model_dump(mode="json"),
            "rule_applied": self.rule_applied,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class StrategySelection:
    """What S-09 made of one candidate set (Step 1 §4, S-09 Outputs).

    ``outcome`` is present for a set that reached one of §6.2's states and
    **absent** for the ordinary case where code exclusion left exactly one
    admissible candidate. That case left nothing unresolved: an OutcomeRecord
    is "one unresolved state, resolved", and a scope that simply completed "has
    no §6.2 state, and inventing one would make the indicators count it"
    (``run_summary.ScopeOutcome``). ``E-12`` and ``E-01.selection`` are written
    the same way, for the same reason.

    **There is no role field on E-13** (fix F-1). This record is where a
    candidate's role lives, and it lives here only: ``admissible``, ``excluded``
    and ``chosen`` are three views of one set, and E-13 stays immutable.
    """

    selection_id: str
    unit_id: str
    destination: Destination
    candidate_set_id: str
    admissible: tuple[str, ...] = ()
    excluded: tuple[Exclusion, ...] = ()
    chosen: Optional[str] = None
    deciding_tiebreaker: Optional[TieBreaker] = None
    precedence_applications: tuple[PrecedenceApplication, ...] = ()
    hints: tuple[Hint, ...] = ()
    degrade_reason: Optional[DegradeReason] = None
    outcome: Optional[OutcomeRecord] = None

    def __post_init__(self) -> None:
        if not self.selection_id.strip() or not self.unit_id.strip():
            raise SelectionError(
                "a selection is identified by its own ID and the unit it was made "
                "for"
            )
        if not self.candidate_set_id.strip():
            raise SelectionError(
                f"{self.selection_id} names no candidate set; a selection is one "
                "call's answer selected among, and Step 1 §4 keeps one per set"
            )
        removed = [item.strategy_id for item in self.excluded]
        repeated = sorted({item for item in removed if removed.count(item) > 1})
        if repeated:
            raise SelectionError(
                f"{self.selection_id} excludes "
                + ", ".join(repeated)
                + " twice; one candidate is removed by the rule with the most "
                "authority, and two reasons for it name neither"
            )
        overlap = sorted(set(self.admissible) & set(removed))
        if overlap:
            raise SelectionError(
                f"{self.selection_id} records "
                + ", ".join(overlap)
                + " as both admissible and excluded; a candidate is one or the "
                "other"
            )
        if len(set(self.admissible)) != len(self.admissible):
            raise SelectionError(
                f"{self.selection_id} lists one admissible candidate twice"
            )
        self._chosen_is_consistent()

    def _chosen_is_consistent(self) -> None:
        if self.chosen is None:
            if self.admissible:
                raise SelectionError(
                    f"{self.selection_id} chose nothing and records "
                    f"{len(self.admissible)} admissible candidate(s); §3's Post "
                    "column is 'exactly one chosen strategy, or an outcome', and "
                    "an admissible candidate nobody chose is neither"
                )
            if self.outcome is None or self.outcome.outcome is ArpOutcome.RESOLVE:
                raise SelectionError(
                    f"{self.selection_id} chose nothing and records "
                    f"{self.outcome!r}; no admissible candidate is a REPLAN to "
                    "S-08 while L_strategy allows and a SKIP of the destination "
                    "once it does not, and never a run that waits"
                )
            if self.deciding_tiebreaker is not None or self.degrade_reason is not None:
                raise SelectionError(
                    f"{self.selection_id} chose nothing and names a tie-breaker "
                    "or a degrade reason; nothing was decided between candidates "
                    "there were none of"
                )
            return
        if self.chosen not in self.admissible:
            raise SelectionError(
                f"{self.selection_id} chose {self.chosen}, which it does not "
                "record as admissible; the choice is made among the candidates "
                "that survived exclusion"
            )
        if len(self.admissible) == 1:
            if self.outcome is not None:
                raise SelectionError(
                    f"{self.selection_id} had one admissible candidate and "
                    f"records a {self.outcome.outcome.value}; §3's Decider column "
                    "chooses it without a ranking, which resolves no §6.2 state — "
                    "and a state invented here is one the indicators count"
                )
            if self.deciding_tiebreaker is not None or self.degrade_reason is not None:
                raise SelectionError(
                    f"{self.selection_id} had one admissible candidate and names "
                    f"{self.deciding_tiebreaker!r}/{self.degrade_reason!r}; no "
                    "tie-breaker was needed, so none decided"
                )
            return
        if self.outcome is None:
            raise SelectionError(
                f"{self.selection_id} chose among {len(self.admissible)} "
                "admissible candidates and records no outcome; map §6.2 makes "
                "'several equal strategies' a RESOLVE by what decided the choice "
                "or a DEGRADE to the safest, and both are states that were reached"
            )
        if self.outcome.state_code is not StateCode.SEVERAL_EQUAL_STRATEGIES:
            raise SelectionError(
                f"{self.selection_id} chose among several candidates and records "
                f"state {self.outcome.state_code.value}; §6.2 gives that choice "
                "its own state, and the skip rate is read per state"
            )
        if self.outcome.outcome is ArpOutcome.RESOLVE:
            if self.deciding_tiebreaker is None or self.degrade_reason is not None:
                raise SelectionError(
                    f"{self.selection_id} records a RESOLVE with tie-breaker "
                    f"{self.deciding_tiebreaker!r} and degrade reason "
                    f"{self.degrade_reason!r}; a RESOLVE is 'what decided the "
                    "choice' (§6.2), which is exactly one criterion of §7.3"
                )
            return
        if self.outcome.outcome is not ArpOutcome.DEGRADE:
            raise SelectionError(
                f"{self.selection_id} chose a strategy and records a "
                f"{self.outcome.outcome.value}; a choice that was made is a "
                "RESOLVE or a DEGRADE, and a terminal outcome is a choice that "
                "was not"
            )
        if self.deciding_tiebreaker is not None or self.degrade_reason is None:
            raise SelectionError(
                f"{self.selection_id} records a DEGRADE with tie-breaker "
                f"{self.deciding_tiebreaker!r} and degrade reason "
                f"{self.degrade_reason!r}; a DEGRADE is the choice no criterion "
                "made, and why no criterion made it is the fact a reader needs"
            )

    @property
    def scope_key(self) -> str:
        """The destination scope key this selection was made under (§4.2)."""

        return destination_scope_key(self.unit_id, self.destination)

    def as_entity(self) -> dict[str, Any]:
        """The body written to ``strategies/<set>/selection.json`` (§2.2)."""

        return {
            "entity_type": SELECTION_ENTITY_TYPE,
            "entity_id": self.selection_id,
            "selection_id": self.selection_id,
            "unit_id": self.unit_id,
            "destination": self.destination.value,
            "candidate_set_id": self.candidate_set_id,
            "admissible": list(self.admissible),
            "excluded": [item.as_entity() for item in self.excluded],
            "chosen": self.chosen,
            "deciding_tiebreaker": (
                None
                if self.deciding_tiebreaker is None
                else self.deciding_tiebreaker.value
            ),
            "precedence_applications": [
                item.model_dump(mode="json")
                for item in self.precedence_applications
            ],
            "hints": [item.as_entity() for item in self.hints],
            "degrade_reason": (
                None if self.degrade_reason is None else self.degrade_reason.value
            ),
            "outcome": (
                None if self.outcome is None else self.outcome.model_dump(mode="json")
            ),
        }


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    """What one S-09 execution made of one destination.

    The selection is absent only where nothing was selected among: the call
    budget refused before any ranking. Every other case writes one, including
    the case that routes back to S-08 — the exclusions and their reasons are
    the trace §3 asks this stage for, and losing them would leave the reason a
    destination went back recorded nowhere but in the counter.
    """

    unit_id: str
    destination: Destination
    selection: Optional[StrategySelection] = None
    outcomes: tuple[OutcomeRecord, ...] = ()
    #: Model calls this execution made, for the per-stage call record (§3.3).
    calls: int = 0

    @property
    def established_no_candidate(self) -> bool:
        """Did this execution *establish* that no candidate is admissible?

        The unit rule rests on this and not on "did it choose": a destination
        whose budget refused the ranking established nothing about the anchor,
        and reading its silence as a verdict is how ``L_anchor`` gets spent on
        an outage.
        """

        return self.selection is not None and self.selection.chosen is None


@dataclass(frozen=True, slots=True)
class StrategyFingerprint:
    """A prior E-16 as S-09's portfolio tie-breaker counts it (§3, Inputs).

    A narrow view of the fingerprint rather than the entity itself, for the
    reason :class:`~src.editorial_core.destinations.DestinationFingerprint` is
    one: the facts below are all the sixth tie-breaker compares, and which
    fingerprints count as recent is a question about the day the run happens on
    — a scheduling input the core is handed rather than one it reads (CE-1).
    """

    fingerprint_id: str
    destination: Destination
    focal_subject_kind: Optional[FocalSubjectKind] = None
    reveal: Optional[RevealKind] = None


# ===========================================================================
# Identity and storage
# ===========================================================================


def selection_id(set_id: str) -> str:
    """The ID of the one selection over one candidate set.

    Derived from the set rather than counted: Step 1 §4 gives one
    StrategySelection per ``candidate_set_id``, and §2.5 writes it once.
    """

    if not set_id.strip():
        raise SelectionError("a selection is named for the candidate set it is over")
    return f"sel-{set_id}"


def selection_relative_path(
    unit: str, destination: Destination, set_id: str
) -> str:
    """``strategies/<candidate_set_id>/selection.json`` (§2.2)."""

    return (
        f"{strategies_relative_path(unit, destination, set_id)}/"
        f"{SELECTION_FILE_NAME}"
    )


def write_strategy_selection(
    workspace: RunWorkspace, selection: StrategySelection
) -> EntityIndexEntry:
    """Write one selection into the run workspace, and index it.

    Through :class:`~src.run.run_workspace.RunWorkspace`, so create-once (P1)
    and §2.3 write ownership hold: ``strategies/*/selection.json`` belongs to
    S-09 and to nothing else, and the candidate files beside it belong to S-08.
    The name carries no version because StrategySelection is written once
    (§2.5) — a new attempt is a new set with a selection of its own.
    """

    return workspace.write_entity(
        stage=STAGE,
        relative_path=selection_relative_path(
            selection.unit_id, selection.destination, selection.candidate_set_id
        ),
        entity_type=SELECTION_ENTITY_TYPE,
        entity_id=selection.selection_id,
        payload=selection.as_entity(),
    )


# ===========================================================================
# The one call
# ===========================================================================


class RankingTransport(Protocol):
    """The model call S-09 makes when several candidates remain."""

    def complete(self, *, instructions: str, request: str) -> str: ...


RANKING_INSTRUCTIONS = """\
You rank whole editorial strategies for one destination against two explicit
criteria, and against nothing else. You do not choose, you do not edit, and you
do not name a type or a category for any of them.

The candidates have already passed every deterministic exclusion. What is left
for you is the two criteria code cannot compute:

1. `evidence_fit`: how well the strategy's reader path and thesis are carried by
   the evidence claims and readings it references, as the request states them.
2. `destination_fit`: how well the strategy suits this destination as a surface,
   given its mode and the reader it reaches.

Score each from 1 (worst) to 5 (best). Equal scores are a real answer: the
remaining criteria — interpretation risk, asset strength, client preference,
portfolio and cost — are applied afterwards by code, in that order.

Return one entry per candidate in the request, all of them, each with its
1-based `index`, both scores and one sentence of `reason`.

Return ONLY one valid JSON object, no text outside it:

{"rankings": [{"index": 1, "evidence_fit": 4, "destination_fit": 3,
 "reason": "..."}]}
"""


class _RankingModel(BaseModel):
    """An answer is parsed strictly, or it is not an answer."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=True
    )


class CandidateRanking(_RankingModel):
    index: int = Field(ge=1)
    evidence_fit: int = Field(ge=FIT_MIN, le=FIT_MAX)
    destination_fit: int = Field(ge=FIT_MIN, le=FIT_MAX)
    reason: str = Field(min_length=1)


class RankingAnswer(_RankingModel):
    rankings: tuple[CandidateRanking, ...] = ()


# ===========================================================================
# The stage
# ===========================================================================


def select_strategy(
    *,
    candidate_set: CandidateSet,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    features: MaterialFeatures,
    contract: StrategyContract,
    counters: AttemptCounterLedger,
    transport: Optional[RankingTransport] = None,
    assets: Sequence[Asset] = (),
    portfolio: Sequence[StrategyFingerprint] = (),
    budget: Optional[CallBudget] = None,
) -> SelectionDecision:
    """Exclude by rule, then choose by tie-breaker, for one destination.

    Returns a :class:`SelectionDecision` in every case the protocol has an
    outcome for, including the case where nothing is admissible: that is a
    recorded ``REPLAN`` to S-08 — or the destination's ``SKIP`` once
    ``L_strategy`` is gone — and not an exception, for the reason S-00 through
    S-08 give. The stage's preconditions still raise.

    ``transport`` is required only where §3 says a call is made: "0 [calls] if
    at most one candidate remains after code exclusion; 1 otherwise". A set
    that needs a ranking and has no ranker is a stage run without an input it
    was promised, so it raises rather than quietly degrading — a silent
    ``DEGRADE`` there would report a run as having chosen carefully when
    nothing was compared.
    """

    _precondition(
        candidate_set=candidate_set,
        boundary=boundary,
        core=core,
        features=features,
    )
    scope_key = candidate_set.scope_key
    admissible, excluded, hints, precedence = _exclusions(
        candidate_set=candidate_set,
        boundary=boundary,
        core=core,
        features=features,
        contract=contract,
        assets=assets,
    )
    if not admissible:
        return _no_admissible_candidate(
            candidate_set=candidate_set,
            excluded=excluded,
            hints=hints,
            precedence=precedence,
            counters=counters,
            scope_key=scope_key,
        )
    if len(admissible) == 1:
        return SelectionDecision(
            unit_id=candidate_set.unit_id,
            destination=candidate_set.destination,
            selection=_selection(
                candidate_set=candidate_set,
                admissible=admissible,
                excluded=excluded,
                hints=hints,
                precedence=precedence,
                chosen=admissible[0].strategy_id,
            ),
        )
    if transport is None:
        raise SelectionError(
            f"{candidate_set.candidate_set_id} left {len(admissible)} admissible "
            f"candidates and {STAGE} was given no ranking transport; §3 makes "
            "the call where several remain, and choosing without one would "
            "record a comparison nobody made"
        )

    refusal = _spend(budget, scope_key)
    if refusal is not None:
        return SelectionDecision(
            unit_id=candidate_set.unit_id,
            destination=candidate_set.destination,
            outcomes=(refusal,),
        )
    answer = _answer(
        transport,
        _request(
            candidate_set=candidate_set,
            admissible=admissible,
            boundary=boundary,
            contract=contract,
        ),
    )
    ranking = None if answer is None else _ranking(answer, admissible)
    if ranking is None:
        return _degraded(
            candidate_set=candidate_set,
            admissible=admissible,
            excluded=excluded,
            hints=hints,
            precedence=precedence,
            boundary=boundary,
            why=DegradeReason.RANKING_UNAVAILABLE,
            calls=1,
        )
    scores = _scores(
        admissible=admissible,
        ranking=ranking,
        boundary=boundary,
        core=core,
        contract=contract,
        assets=assets,
        portfolio=portfolio,
        destination=candidate_set.destination,
    )
    decided, leaders = _ladder(admissible, scores)
    if decided is None:
        return _degraded(
            candidate_set=candidate_set,
            admissible=admissible,
            excluded=excluded,
            hints=hints,
            precedence=precedence,
            boundary=boundary,
            why=DegradeReason.LEADERS_INSEPARABLE,
            calls=1,
        )
    chosen = leaders[0]
    resolved = OutcomeRecord(
        outcome=ArpOutcome.RESOLVE,
        state_code=StateCode.SEVERAL_EQUAL_STRATEGIES,
        scope=OutcomeScope.DESTINATION,
        scope_key=scope_key,
        reason=(
            f"{chosen.strategy_id} was chosen among {len(admissible)} admissible "
            f"candidates by {decided.value}"
        ),
    )
    return SelectionDecision(
        unit_id=candidate_set.unit_id,
        destination=candidate_set.destination,
        selection=_selection(
            candidate_set=candidate_set,
            admissible=admissible,
            excluded=excluded,
            hints=hints,
            precedence=precedence,
            chosen=chosen.strategy_id,
            deciding_tiebreaker=decided,
            outcome=resolved,
        ),
        outcomes=(resolved,),
        calls=1,
    )


def review_unit_round(
    *,
    unit_id: str,
    eligible: Sequence[Destination],
    decisions: Sequence[SelectionDecision],
    counters: AttemptCounterLedger,
) -> Optional[OutcomeRecord]:
    """The unit rule (fix F-5): all destinations failing points at the anchor.

    Returns the ``REPLAN`` into S-06 — or the unit's ``SKIP`` once ``L_anchor``
    is gone — when every eligible destination of this unit established, in this
    round, that it has no admissible candidate. Returns ``None`` otherwise, and
    the per-destination routes ``select_strategy`` already took stand.

    The round has to be complete, and that is a precondition rather than a
    judgment: a rule that concluded "no destination has one" from the
    destinations it happened to be shown would spend the unit's one anchor
    attempt on a round nobody finished. A destination that produced no
    selection at all — the budget refused, and nothing was compared —
    establishes nothing either, so it does not count towards the anchor being
    suspect.
    """

    if not unit_id.strip():
        raise SelectionError("a round is reviewed for one unit, named")
    if not eligible:
        raise SelectionError(
            f"{unit_id} was reviewed with no eligible destination; S-07 skips a "
            "unit with none (reason no_eligible_destination), so a round over "
            "none is a unit that should never have reached S-08"
        )
    named = [decision.destination for decision in decisions]
    duplicated = sorted({item.value for item in named if named.count(item) > 1})
    if duplicated:
        raise SelectionError(
            f"{unit_id} was reviewed with two decisions for "
            + ", ".join(duplicated)
            + "; one round holds one selection per destination"
        )
    missing = sorted(item.value for item in set(eligible) - set(named))
    if missing:
        raise SelectionError(
            f"{unit_id} was reviewed without a decision for "
            + ", ".join(missing)
            + "; the unit rule asks whether *every* eligible destination failed "
            "in the same round, and a round that is short of one cannot answer "
            "it"
        )
    unexpected = sorted(item.value for item in set(named) - set(eligible))
    if unexpected:
        raise SelectionError(
            f"{unit_id} was reviewed with a decision for "
            + ", ".join(unexpected)
            + ", which S-07 did not make eligible; a destination that was never "
            "attempted says nothing about the anchor"
        )
    for decision in decisions:
        if decision.unit_id != unit_id:
            raise SelectionError(
                f"a selection for {decision.unit_id!r} was offered in the round "
                f"of {unit_id!r}; the unit rule is about one unit's destinations"
            )
    if not all(decision.established_no_candidate for decision in decisions):
        return None
    return counters.route(
        source=STAGE,
        cause=UNIT_CAUSE,
        scope_key=unit_id,
        state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
        reason=(
            f"no destination of {unit_id} held an admissible candidate in this "
            "round, which points at the anchor rather than at any one surface"
        ),
    )


# ===========================================================================
# The code exclusions (§3, Decider)
# ===========================================================================


def acts_alone(rule: ContractRule) -> bool:
    """May this rule cause an exclusion by itself (Step 4 §5.1 rule 1)?

    ``False`` only for a demoted record nothing reinforces. A rule with no
    register record behind it is the contract itself, which §5.1 does not
    demote: expiry is a property of a knowledge record, and a client rule
    nobody wrote a record for is not an expired one.
    """

    record = rule.knowledge
    if record is None:
        return True
    return not (
        record.effective_status is KnowledgeStatus.WEAK_CANDIDATE
        and record.reinforced_by is None
    )


def preference_acts_at(rule: ContractRule, tie_breaker: TieBreaker) -> bool:
    """May this rule order candidates at this rung (Step 4 §5.1 rule 3)?

    A demoted record "is usable only as supporting soft input or as a late
    tie-breaker … it can act only after the §7.3 tie-breakers that rest on
    evidence, destination and interpretation risk". Everything else acts
    everywhere.
    """

    if acts_alone(rule):
        return True
    return TIE_BREAKER_ORDER.index(tie_breaker) >= TIE_BREAKER_ORDER.index(
        WEAK_CANDIDATE_EARLIEST_TIEBREAKER
    )


def promised_points(candidate: EditorialStrategy) -> int:
    """How many meanings the reader path promises (V-P02).

    The moves that carry a reading, counted. V-P02 is "the number of points is
    no greater than the number of admissible interpretations", and the map's
    own example is the Instagram "3 things" candidate against a boundary with
    two: three moves each promising a point where the evidence admits two
    readings. A move that only carries a fact promises no second meaning and is
    not counted.
    """

    readings = set(candidate.interpretation_refs)
    return sum(
        1
        for move in candidate.reader_path
        if readings.intersection(move.refs)
    )


def _exclusions(
    *,
    candidate_set: CandidateSet,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    features: MaterialFeatures,
    contract: StrategyContract,
    assets: Sequence[Asset],
) -> tuple[
    tuple[EditorialStrategy, ...],
    tuple[Exclusion, ...],
    tuple[Hint, ...],
    tuple[PrecedenceApplication, ...],
]:
    """Apply every deterministic exclusion, strongest rule first (map §5)."""

    resolvable = _resolvable_refs(boundary, core, assets)
    admissible: list[EditorialStrategy] = []
    excluded: list[Exclusion] = []
    hints: list[Hint] = []
    precedence: list[PrecedenceApplication] = []
    for candidate in candidate_set.candidates:
        evidence = _evidence_exclusion(
            candidate, boundary, features, resolvable
        )
        if evidence is not None:
            excluded.append(evidence)
            continue
        prohibition = _prohibition(candidate, contract, hints)
        if prohibition is None:
            admissible.append(candidate)
            continue
        excluded.append(prohibition)
        application = _precedence(candidate, contract, prohibition)
        if application is not None:
            precedence.append(application)
    return tuple(admissible), tuple(excluded), tuple(hints), tuple(precedence)


def _evidence_exclusion(
    candidate: EditorialStrategy,
    boundary: InterpretationBoundary,
    features: MaterialFeatures,
    resolvable: frozenset[str],
) -> Optional[Exclusion]:
    """The tier-0a exclusions: I-05, V-P02, and the code part of V-P01.

    Every one of them is re-evaluated against the entities in front of S-09.
    A candidate carries the ``boundary_ref`` it was written under, and a
    commit since then may have made a reading inadmissible: the candidate does
    not keep the standing that version gave it.
    """

    for identity in candidate.interpretation_refs:
        member = boundary.member(identity)
        if member is None or not member.admissible:
            return Exclusion(
                strategy_id=candidate.strategy_id,
                reason=ExclusionReason.INADMISSIBLE_INTERPRETATION,
                rule_ref="V-P02",
                tier=KnowledgeTier.EVIDENCE,
                detail=(
                    f"the strategy rests on {identity}, which boundary version "
                    f"{boundary.version} does not admit; it was written against "
                    f"version {candidate.boundary_ref[1]}, and a reading a "
                    "commit refused is refused for everything that referenced it"
                ),
            )
    promised = promised_points(candidate)
    admitted = len(boundary.admissible)
    if promised > admitted:
        return Exclusion(
            strategy_id=candidate.strategy_id,
            reason=ExclusionReason.PROMISE_WIDER_THAN_BOUNDARY,
            rule_ref="V-P02",
            tier=KnowledgeTier.EVIDENCE,
            detail=(
                f"the reader path promises {promised} point(s) where the "
                f"boundary admits {admitted} reading(s); a text cannot promise "
                "more meanings than the evidence was shown to carry"
            ),
        )
    inconsistency = _field_inconsistency(candidate, features, resolvable)
    if inconsistency is not None:
        return Exclusion(
            strategy_id=candidate.strategy_id,
            reason=ExclusionReason.FIELD_INCONSISTENCY,
            rule_ref="V-P01",
            tier=KnowledgeTier.EVIDENCE,
            detail=inconsistency,
        )
    return None


def _field_inconsistency(
    candidate: EditorialStrategy,
    features: MaterialFeatures,
    resolvable: frozenset[str],
) -> Optional[str]:
    """The code part of V-P01, as map §11 states it.

    "An opening built on a figure requires that figure in the core" and "if the
    reader path makes a case the subject of a move, ``documented_case`` is
    mandatory and confirmed in the core". Path labels are not used (I-10), and
    the parts that need reading rather than resolving — whether a delayed
    reveal suits the format's length — belong to S-11's model half, where the
    format exists.
    """

    cited = {
        reference
        for move in candidate.reader_path
        for reference in move.refs
    }
    cited.update(candidate.opening.refs)
    cited.update(candidate.focal_subject.refs)
    unresolved = sorted(cited - resolvable)
    if unresolved:
        return (
            "the strategy references "
            + ", ".join(unresolved)
            + ", which this run no longer holds; I-03 keeps facts inside the "
            "core and I-05 keeps readings inside the boundary"
        )
    if candidate.focal_subject.kind is FocalSubjectKind.PERSON_IN_STORY and not (
        features.value_of(MaterialFeature.DOCUMENTED_CASE).positive
    ):
        return (
            "the focal subject is a person in the story and the material holds "
            "no documented case; V-P01 makes documented_case mandatory and "
            "confirmed in the Evidence Core where a case is the subject of a "
            "move"
        )
    return None


def _prohibition(
    candidate: EditorialStrategy,
    contract: StrategyContract,
    hints: list[Hint],
) -> Optional[Exclusion]:
    """The tier 0–2 contract conflicts, with Step 4 §5.1 rule 1 applied.

    The rules are consulted strongest first, so a candidate two of them refuse
    is excluded by the one with the most authority (map §5): a client reading
    the selection learns which rule would have to change.
    """

    for rule in _by_authority(contract.prohibitions):
        if not rule.applies_to(candidate.focal_subject.kind, candidate.reveal.kind):
            continue
        record = rule.knowledge
        if record is not None and not acts_alone(rule):
            # §5.1 rule 1: "the conflict is recorded as a hint instead". The
            # candidate stays admissible and the demoted record is visible in
            # the trace, which is what makes the demotion auditable rather
            # than merely safe.
            hints.append(
                Hint(
                    strategy_id=candidate.strategy_id,
                    rule_ref=rule.rule_id,
                    knowledge=record,
                    rule_applied=WEAK_CANDIDATE_ALONE,
                    detail=(
                        f"{rule.rule_id} would have excluded "
                        f"{candidate.strategy_id}: {rule.text}"
                    ),
                )
            )
            continue
        return Exclusion(
            strategy_id=candidate.strategy_id,
            reason=ExclusionReason.CONTRACT_PROHIBITION,
            rule_ref=rule.rule_id,
            tier=rule.tier,
            detail=(
                f"{rule.rule_id} forbids what this candidate decided "
                f"({candidate.focal_subject.kind.value}, "
                f"{candidate.reveal.kind.value}): {rule.text}"
            ),
            knowledge=rule.knowledge,
        )
    return None


def _precedence(
    candidate: EditorialStrategy,
    contract: StrategyContract,
    exclusion: Exclusion,
) -> Optional[PrecedenceApplication]:
    """The conflict an exclusion resolved, where two records disagreed (U-3).

    Recorded only where both sides carry a KnowledgeRef: a
    PrecedenceApplication states which record won over which, and a contract
    rule nobody wrote a record for has nothing to put on either side of it.
    """

    if exclusion.knowledge is None:
        return None
    for rule in contract.preferences:
        if rule.knowledge is None:
            continue
        if not rule.applies_to(
            candidate.focal_subject.kind, candidate.reveal.kind
        ):
            continue
        winner = tier_rank(exclusion.knowledge.tier)
        loser = tier_rank(rule.knowledge.tier)
        if winner is None or loser is None or winner >= loser:
            continue
        return PrecedenceApplication(
            conflict=(
                f"{exclusion.rule_ref} forbids what {rule.rule_id} prefers for "
                f"{candidate.strategy_id}"
            ),
            winner=exclusion.knowledge,
            loser=rule.knowledge,
            rule_applied="map §5 rule 3: in a conflict the higher tier wins",
        )
    return None


def _by_authority(rules: Sequence[ContractRule]) -> tuple[ContractRule, ...]:
    """Strongest tier first, then by rule ID so the order is not the caller's.

    A weak candidate loses to a non-expired record of its own tier (§5.1 rule
    2), which is the same order :func:`~src.knowledge.loader.in_precedence_order`
    puts the register in — applied here to the contract's own rules, where the
    register's loader has nothing to sort.
    """

    def key(rule: ContractRule) -> tuple[int, int, str]:
        rank = tier_rank(rule.tier)
        return (
            _UNPLACED_TIER if rank is None else rank,
            0 if acts_alone(rule) else 1,
            rule.rule_id,
        )

    return tuple(sorted(rules, key=key))


def _resolvable_refs(
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    assets: Sequence[Asset],
) -> frozenset[str]:
    """Everything a strategy may still reference at S-09."""

    return frozenset(
        {claim.evidence_claim_id for claim in core.usable_claims}
        | {member.interpretation_id for member in boundary.admissible}
        | {asset.asset_id for asset in assets}
    )


# ===========================================================================
# The tie-breakers (map §7.3)
# ===========================================================================


def _scores(
    *,
    admissible: Sequence[EditorialStrategy],
    ranking: Mapping[str, CandidateRanking],
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    contract: StrategyContract,
    assets: Sequence[Asset],
    portfolio: Sequence[StrategyFingerprint],
    destination: Destination,
) -> Mapping[str, Mapping[TieBreaker, int]]:
    """Every candidate's score at every rung. Higher wins, at every rung."""

    scored: dict[str, dict[TieBreaker, int]] = {}
    for candidate in admissible:
        judged = ranking[candidate.strategy_id]
        scored[candidate.strategy_id] = {
            TieBreaker.EVIDENCE_FIT: judged.evidence_fit,
            TieBreaker.DESTINATION_FIT: judged.destination_fit,
            TieBreaker.INTERPRETATION_RISK: _headroom(candidate, boundary),
            TieBreaker.ASSET_STRENGTH: _carrier_strength(candidate, core, assets),
            TieBreaker.CLIENT_PREFERENCE: _preference_score(candidate, contract),
            TieBreaker.PORTFOLIO: -_portfolio_penalty(
                candidate, portfolio, destination
            ),
            TieBreaker.COST: -len(candidate.reader_path),
        }
    return scored


def _ladder(
    admissible: Sequence[EditorialStrategy],
    scores: Mapping[str, Mapping[TieBreaker, int]],
) -> tuple[Optional[TieBreaker], tuple[EditorialStrategy, ...]]:
    """Apply §7.3 in order; return the rung that left one leader, and them.

    ``None`` when every rung has been applied and more than one leader is
    still standing — the state §3 calls "the model cannot separate the
    leaders", whoever the criteria came from.
    """

    leaders = tuple(admissible)
    for tie_breaker in TIE_BREAKER_ORDER:
        best = max(scores[item.strategy_id][tie_breaker] for item in leaders)
        leaders = tuple(
            item for item in leaders if scores[item.strategy_id][tie_breaker] == best
        )
        if len(leaders) == 1:
            return tie_breaker, leaders
    return None, leaders


def _headroom(
    candidate: EditorialStrategy, boundary: InterpretationBoundary
) -> int:
    """Interpretation risk, as §7.3 defines it: strength against the ceiling.

    "Lower interpretation risk (lower strength relative to the ceiling)" — so
    what is scored is the distance a reading still has to its own ceiling, and
    the minimum over the readings the strategy rests on, because the riskiest
    of them is the one a text is exposed on. Higher is safer, which is the
    direction every rung of the ladder reads in.
    """

    distances: list[int] = []
    for identity in candidate.interpretation_refs:
        member = boundary.member(identity)
        if member is None:
            return 0
        distances.append(member.ceiling.level - member.strength.level)
    return min(distances) if distances else 0


def _carrier_strength(
    candidate: EditorialStrategy,
    core: EvidenceCore,
    assets: Sequence[Asset],
) -> int:
    """Asset strength: what the primary evidentiary carrier is worth.

    Measured on the one strength ladder rather than on two scales. A carrier
    that is an evidence claim scores its own level; a carrier that is an asset
    scores the strongest claim it rests on, because an asset's authority is
    the material under it (E-06 requires the references) and comparing a
    confidence word against a ladder level would order the candidates by which
    kind of carrier they happened to pick.
    """

    levels = {
        claim.evidence_claim_id: claim.strength.level
        for claim in core.usable_claims
    }
    direct = levels.get(candidate.leading_material_ref)
    if direct is not None:
        return direct
    for asset in assets:
        if asset.asset_id != candidate.leading_material_ref:
            continue
        rested = [levels[ref] for ref in asset.refs if ref in levels]
        return max(rested) if rested else 0
    return 0


def _preference_score(
    candidate: EditorialStrategy, contract: StrategyContract
) -> int:
    """Client preference: how many of the contract's preferences it meets.

    Weak-candidate records are admitted here because this rung sits after the
    three §5.1 rule 3 keeps them out of — :func:`preference_acts_at` is where
    that is decided, and it is asked rather than assumed so that moving this
    rung up the ladder would change the answer instead of silently keeping it.
    """

    return sum(
        1
        for rule in contract.preferences
        if preference_acts_at(rule, TieBreaker.CLIENT_PREFERENCE)
        and rule.applies_to(candidate.focal_subject.kind, candidate.reveal.kind)
    )


def _portfolio_penalty(
    candidate: EditorialStrategy,
    portfolio: Sequence[StrategyFingerprint],
    destination: Destination,
) -> int:
    """Portfolio: "soft penalty, not rotation" (§7.3).

    A penalty and never an exclusion, and never a rule that a shape which has
    just been used may not be used again: what it counts is how often this
    destination has recently told a story with the same focal subject and the
    same reveal, and it acts at the sixth rung, where three criteria that rest
    on the evidence have already had their say.
    """

    return sum(
        1
        for entry in portfolio
        if entry.destination is destination
        and entry.focal_subject_kind is candidate.focal_subject.kind
        and entry.reveal is candidate.reveal.kind
    )


def _safest(
    admissible: Sequence[EditorialStrategy], boundary: InterpretationBoundary
) -> EditorialStrategy:
    """The ``DEGRADE`` choice: "the safest admissible" (§3, ARP).

    "Lowest strength relative to the ceiling, no positional asset", in that
    order, and then the strategy ID — not for a reason of its own, but because
    a degrade that picked differently on two identical inputs would make the
    run unreproducible at exactly the point where nothing else decided.
    """

    return min(
        admissible,
        key=lambda candidate: (
            -_headroom(candidate, boundary),
            candidate.client_position_ref is not None,
            candidate.strategy_id,
        ),
    )


# ===========================================================================
# Outcomes, requests and answers
# ===========================================================================


def _precondition(
    *,
    candidate_set: CandidateSet,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    features: MaterialFeatures,
) -> None:
    """§3's Pre column, and the entities that have to describe one thing."""

    if boundary.core_ref != (core.core_id, core.version):
        raise SelectionError(
            f"{candidate_set.candidate_set_id} reached {STAGE} with a boundary "
            f"over {boundary.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); every exclusion is checked "
            "against both, and two that describe different material cannot both "
            "be right"
        )
    if features.core_ref != (core.core_id, core.version):
        raise SelectionError(
            f"{candidate_set.candidate_set_id} reached {STAGE} with features over "
            f"{features.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); E-05 is recomputed per core "
            "version, and V-P01's documented-case rule reads this vector"
        )
    for candidate in candidate_set.candidates:
        if candidate.boundary_ref[0] != boundary.boundary_id:
            raise SelectionError(
                f"{candidate.strategy_id} was written against boundary "
                f"{candidate.boundary_ref[0]!r} and reached {STAGE} with "
                f"{boundary.boundary_id!r}; a candidate is selected inside its "
                "own unit's boundary"
            )
        if candidate.boundary_ref[1] > boundary.version:
            raise SelectionError(
                f"{candidate.strategy_id} was written against boundary version "
                f"{candidate.boundary_ref[1]} and reached {STAGE} with version "
                f"{boundary.version}; a version only ever moves forward, and a "
                "selection made against an older snapshot than the candidate is "
                "the drift patch R2's versioned references exist to prevent"
            )


def _no_admissible_candidate(
    *,
    candidate_set: CandidateSet,
    excluded: tuple[Exclusion, ...],
    hints: tuple[Hint, ...],
    precedence: tuple[PrecedenceApplication, ...],
    counters: AttemptCounterLedger,
    scope_key: str,
) -> SelectionDecision:
    """§3's ARP: ``REPLAN`` → S-08, and the destination's ``SKIP`` after that.

    The same record for a set that held nothing and for a set every rule
    refused: §1 makes "zero candidates pass schema validation" count as no
    admissible strategy, so the two are one state and the exclusions — or
    their absence — say which of them happened.
    """

    route = counters.route(
        source=STAGE,
        cause=NO_ADMISSIBLE_CAUSE,
        scope_key=scope_key,
        state_code=StateCode.NO_ADMISSIBLE_STRATEGY,
        reason=(
            f"{candidate_set.candidate_set_id} left no admissible candidate: "
            f"{len(candidate_set.candidates)} proposed, {len(excluded)} excluded"
        ),
    )
    return SelectionDecision(
        unit_id=candidate_set.unit_id,
        destination=candidate_set.destination,
        selection=_selection(
            candidate_set=candidate_set,
            admissible=(),
            excluded=excluded,
            hints=hints,
            precedence=precedence,
            chosen=None,
            outcome=route,
        ),
        outcomes=(route,),
    )


def _degraded(
    *,
    candidate_set: CandidateSet,
    admissible: Sequence[EditorialStrategy],
    excluded: tuple[Exclusion, ...],
    hints: tuple[Hint, ...],
    precedence: tuple[PrecedenceApplication, ...],
    boundary: InterpretationBoundary,
    why: DegradeReason,
    calls: int,
) -> SelectionDecision:
    """§3's ARP: "``DEGRADE``: choose the safest admissible".

    Fail-closed and not fail-open: every candidate here has already survived
    every deterministic exclusion, so what is chosen without a ranking is one
    of the ones the rules allowed — the least exposed of them — and never a
    candidate the rules would have removed.
    """

    chosen = _safest(admissible, boundary)
    degraded = OutcomeRecord(
        outcome=ArpOutcome.DEGRADE,
        state_code=StateCode.SEVERAL_EQUAL_STRATEGIES,
        scope=OutcomeScope.DESTINATION,
        scope_key=candidate_set.scope_key,
        reason=(
            "no criterion of the tie-breaker order separated the "
            f"{len(admissible)} admissible candidates ({why.value}); "
            f"{chosen.strategy_id} is the safest of them"
        ),
    )
    return SelectionDecision(
        unit_id=candidate_set.unit_id,
        destination=candidate_set.destination,
        selection=_selection(
            candidate_set=candidate_set,
            admissible=admissible,
            excluded=excluded,
            hints=hints,
            precedence=precedence,
            chosen=chosen.strategy_id,
            degrade_reason=why,
            outcome=degraded,
        ),
        outcomes=(degraded,),
        calls=calls,
    )


def _selection(
    *,
    candidate_set: CandidateSet,
    admissible: Sequence[EditorialStrategy],
    excluded: tuple[Exclusion, ...],
    hints: tuple[Hint, ...],
    precedence: tuple[PrecedenceApplication, ...],
    chosen: Optional[str],
    deciding_tiebreaker: Optional[TieBreaker] = None,
    degrade_reason: Optional[DegradeReason] = None,
    outcome: Optional[OutcomeRecord] = None,
) -> StrategySelection:
    return StrategySelection(
        selection_id=selection_id(candidate_set.candidate_set_id),
        unit_id=candidate_set.unit_id,
        destination=candidate_set.destination,
        candidate_set_id=candidate_set.candidate_set_id,
        admissible=tuple(item.strategy_id for item in admissible),
        excluded=excluded,
        chosen=chosen,
        deciding_tiebreaker=deciding_tiebreaker,
        precedence_applications=precedence,
        hints=hints,
        degrade_reason=degrade_reason,
        outcome=outcome,
    )


def _request(
    *,
    candidate_set: CandidateSet,
    admissible: Sequence[EditorialStrategy],
    boundary: InterpretationBoundary,
    contract: StrategyContract,
) -> str:
    """What the ranking call sees: the survivors, and the two criteria.

    The excluded candidates are deliberately absent. They are not a shorter
    list for a model to reconsider — exclusion is ``code``'s and is already
    recorded with its rule — and a request that carried them would invite the
    one thing §3 forbids this stage, editing a candidate back in.
    """

    return json.dumps({
        "destination": candidate_set.destination.value,
        "candidate_set_id": candidate_set.candidate_set_id,
        "boundary": {
            "version": boundary.version,
            "admissible": [
                {
                    "interpretation_id": member.interpretation_id,
                    "statement": member.statement,
                    "strength_level": member.strength.level,
                    "ceiling_level": member.ceiling.level,
                }
                for member in boundary.admissible
            ],
        },
        "preferences": [
            {"rule_id": rule.rule_id, "text": rule.text}
            for rule in contract.preferences
        ],
        "candidates": [
            {
                "index": position,
                "strategy_id": candidate.strategy_id,
                "editorial_job": candidate.editorial_job,
                "angle": candidate.angle,
                "thesis": candidate.editorial_thesis.text,
                "thesis_interpretation_refs": list(
                    candidate.editorial_thesis.interpretation_refs
                ),
                "focal_subject": {
                    "kind": candidate.focal_subject.kind.value,
                    "text": candidate.focal_subject.text,
                },
                "leading_material_ref": candidate.leading_material_ref,
                "reader_path": [
                    move.as_entity() for move in candidate.reader_path
                ],
                "opening": candidate.opening.as_entity(),
                "reveal": candidate.reveal.as_entity(),
                "concession": candidate.concession.as_entity(),
                "ending_intention": candidate.ending_intention,
            }
            for position, candidate in enumerate(admissible, 1)
        ],
    })


def _answer(
    transport: RankingTransport, request: str
) -> Optional[RankingAnswer]:
    """One call, parsed, or ``None``. Never the provider's own text."""

    try:
        raw = transport.complete(
            instructions=RANKING_INSTRUCTIONS, request=request
        )
    except Exception:  # noqa: BLE001 — sanitized, never the provider's text
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return RankingAnswer.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return None


def _ranking(
    answer: RankingAnswer, admissible: Sequence[EditorialStrategy]
) -> Optional[Mapping[str, CandidateRanking]]:
    """The answer keyed by strategy, or ``None`` when it did not judge them all.

    Coverage is the whole check, for the reason S-06's anchor call is checked
    for it: a partial ranking is not a weaker ranking. A candidate nobody
    scored would be compared at the first rung against a score somebody would
    have to invent for it, and inventing one is how an unasked question passes
    as a verdict.
    """

    judged = [row.index for row in answer.rankings]
    expected = set(range(1, len(admissible) + 1))
    if sorted(judged) != sorted(expected) or len(judged) != len(set(judged)):
        return None
    return {
        admissible[row.index - 1].strategy_id: row for row in answer.rankings
    }


def _spend(budget: Optional[CallBudget], scope_key: str) -> Optional[OutcomeRecord]:
    if budget is None:
        return None
    return budget.spend(scope=OutcomeScope.DESTINATION, scope_key=scope_key)
