"""Loading the register into a run: effective status, selection, size (§5, §9).

`validator.py` decides whether a register may be read at all. This decides what a
run *makes* of it: which records reach which stage, what a record still counts for
on the day the run happens, and what a stage may do when the knowledge it may
never cut does not fit the request it is about to make.

**Effective status (§5).** A record's file status is what the keeper wrote; its
effective status is what the loader made of it today. Past `review_by`, a
`descriptive` or `candidate` record becomes a `weak-candidate`; an `invariant` or
a tier-1 `approved-rule` stays in force and is flagged :data:`EXPIRED_REVIEW`,
because dropping a hard rule nobody re-checked is the unsafe direction. Both
statuses are carried into every KnowledgeRef, so a reader of the trace sees the
demotion rather than recomputing expiry from their own clock.

**What a weak candidate may do (§5.1).** It never acts alone:
:func:`may_exclude` is how a stage asks, and an exclusion, a `REPLAN` or a `SKIP`
resting on nothing but unreinforced weak candidates is not taken. It loses its own
tier to any non-expired record, which is the order :func:`in_precedence_order`
puts records in. It counts at its original weight only when a non-expired record
of the same or a higher tier points the same way — :func:`reinforced` records that,
and checks the half of the claim that is a fact about the register. Which way a
record points is the reading of the stage that met the conflict, and this module
does not guess at it.

**Selection (§9.3).** A record is *eligible* for a stage when its `## Influences`
names the stage, and *applicable* when its condition evaluates true against that
stage's inputs. Both are kept: §4 puts the true/false result of every eligible
record into the routing evidence, so a record that did not apply has to be
visible as one that was read and did not apply.

**Size discipline (§9.6).** Mandatory knowledge — tiers `0a`, `0b`, `0c`, `A`,
`1`, `2`, and every hard check the stage applies — is never truncated. Only
`descriptive`, `candidate` and `weak-candidate` records may be cut, in the reverse
of the precedence order. If the mandatory set alone is over capacity,
:func:`fit_to_capacity` raises :class:`MandatoryKnowledgeExceedsCapacity` instead
of returning material: the stage never gets a request surface to send, which is
what "the call is not made" means in code rather than in a comment. The exception
carries the sizes and the `SKIP` outcome the StageRecord records.

**Client rules.** Tier-2 approved client rules stay in the client folder (§1) and
reach a stage through the same classification as everything else: mandatory by
tier, not by which directory they came from. This module loads the universal
register; a slice that loads a client's rule files feeds the same types.

Sources: `docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md` §4, §5,
§5.1 and §9, with patch `PATCH_S4R1_STEP4.md`;
`docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md` §0.7.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Callable, Final, Mapping, Optional, Sequence

from src.editorial_core.arp import (
    ArpOutcome,
    KnowledgeRef,
    KnowledgeStatus,
    KnowledgeTier,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
    tier_rank,
)
from src.editorial_core.topology import CANONICAL_TOPOLOGY, StageScope
from src.knowledge import records as record_format
from src.knowledge.grammar import (
    AUDIENCE,
    BOUNDARY,
    DESTINATION,
    FEATURE,
    FORMAT,
    STRATEGY,
    Always,
    And,
    Atom,
    Condition,
    ConditionError,
    Not,
    Or,
    parse_condition,
)
from src.knowledge.markdown import DocumentError, load_document
from src.knowledge.records import CheckRecord, KnowledgeRecord, RecordError
from src.knowledge.validator import (
    CHECKS_DIR_NAME,
    LADDERS_DIR_NAME,
    RECORDS_DIR_NAME,
)
from src.knowledge.vocabulary import VocabularyError, load_vocabularies

#: What a record past `review_by` is flagged with when §5 keeps it in force. The
#: effective status of a demoted record already says it was demoted; a hard rule
#: keeps its status, so this flag is the only sign that nobody re-checked it.
EXPIRED_REVIEW: Final[str] = "expired_review"

#: The tiers §9.6 never truncates. Tier `2` is an approved client rule, which
#: lives in the client folder and is mandatory for the same reason a tier-1 rule
#: is: it is a rule, not a description of how things tend to work.
MANDATORY_TIERS: Final[tuple[KnowledgeTier, ...]] = (
    KnowledgeTier.EVIDENCE,
    KnowledgeTier.LAW,
    KnowledgeTier.ETHICS,
    KnowledgeTier.ARCHITECTURAL,
    KnowledgeTier.HARD_PLATFORM_POLICY,
    KnowledgeTier.APPROVED_CLIENT_RULE,
)

#: The effective statuses §9.6 allows a stage to reduce for context size.
REDUCIBLE_STATUSES: Final[tuple[KnowledgeStatus, ...]] = (
    KnowledgeStatus.DESCRIPTIVE,
    KnowledgeStatus.CANDIDATE,
    KnowledgeStatus.WEAK_CANDIDATE,
)

#: The §5.1 rules, worded for ``PrecedenceApplication.rule_applied`` so that the
#: PrecedenceLog says which limit decided a conflict rather than "precedence".
WEAK_CANDIDATE_ALONE: Final[str] = (
    "Step 4 §5.1 rule 1: a weak candidate alone excludes nothing and routes nowhere"
)
WEAK_CANDIDATE_LOSES_ITS_TIER: Final[str] = (
    "Step 4 §5.1 rule 2: a weak candidate loses to a non-expired record of its tier"
)
WEAK_CANDIDATE_REINFORCED: Final[str] = (
    "Step 4 §5.1 rule 3: reinforced by a non-expired record of the same or a "
    "higher tier"
)

_CONFIDENCE_RANK: Final[Mapping[str, int]] = {"high": 0, "medium": 1, "low": 2}

#: A stage's scope decides the scope of the `SKIP` it fails closed with (§9.6).
_OUTCOME_SCOPES: Final[Mapping[StageScope, OutcomeScope]] = {
    StageScope.SIGNAL: OutcomeScope.SIGNAL,
    StageScope.UNIT: OutcomeScope.UNIT,
    StageScope.DESTINATION: OutcomeScope.DESTINATION,
    StageScope.PUBLICATION: OutcomeScope.PUBLICATION,
}


class LoaderError(ValueError):
    """The register cannot be loaded into a run, or was asked for nonsense."""


# ----------------------------------------------------------------------
# What a stage evaluates a condition against (§4)
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StageInputs:
    """The entity versions one stage reads, as the grammar's terms see them.

    Code evaluates a condition against these; a model is never asked whether a
    condition holds (§4, "Time of evaluation"). An input the stage does not hold
    is not the value a term asks for, so the term is false — at S-04 no
    destination has been chosen, and `destination is linkedin` is false there
    rather than unknown.

    ``boundary`` counts: a fact the boundary simply has is ``1``, and a countable
    fact holds however many the boundary admits, which is what lets
    `boundary has at least 2 admissible_interpretations` be answered.
    """

    destination: Optional[str] = None
    format_name: Optional[str] = None
    features: Mapping[str, str] = field(default_factory=dict)
    boundary: Mapping[str, int] = field(default_factory=dict)
    strategy: Mapping[str, str] = field(default_factory=dict)
    audience: Mapping[str, str] = field(default_factory=dict)


def applies(condition: Condition, inputs: StageInputs) -> bool:
    """Does this condition hold for these inputs? Raises :class:`LoaderError`."""

    if isinstance(condition, Always):
        return True
    if isinstance(condition, Atom):
        return _atom(condition, inputs)
    if isinstance(condition, Not):
        return not applies(condition.operand, inputs)
    if isinstance(condition, And):
        return all(applies(operand, inputs) for operand in condition.operands)
    if isinstance(condition, Or):
        return any(applies(operand, inputs) for operand in condition.operands)
    raise LoaderError(
        f"{type(condition).__name__} is not a condition this loader evaluates; "
        "the grammar and the evaluator ship together (§4)"
    )


def _atom(atom: Atom, inputs: StageInputs) -> bool:
    if atom.family == DESTINATION:
        return inputs.destination == atom.name
    if atom.family == FORMAT:
        return inputs.format_name == atom.name
    if atom.family == BOUNDARY:
        return inputs.boundary.get(atom.name, 0) >= (atom.minimum or 1)
    declared: Optional[Mapping[str, str]] = {
        FEATURE: inputs.features,
        STRATEGY: inputs.strategy,
        AUDIENCE: inputs.audience,
    }.get(atom.family)
    if declared is None:
        raise LoaderError(
            f"the term `{atom.text}` is of the family {atom.family!r}, which no "
            "stage input answers; a new term family and the inputs that answer "
            "it ship together (§10)"
        )
    return declared.get(atom.name) == atom.value


# ----------------------------------------------------------------------
# The register as one run sees it (§5, §9.2)
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoadedRecord:
    """One knowledge record, as it counts on the day of this run."""

    record: KnowledgeRecord
    condition: Condition
    version: int
    tier: KnowledgeTier
    file_status: KnowledgeStatus
    effective_status: KnowledgeStatus
    #: True when `review_by` has passed, whatever §5 did about it.
    expired_review: bool

    @property
    def identity(self) -> str:
        return self.record.record_id

    @property
    def digest(self) -> str:
        return self.record.document.digest

    @property
    def confidence(self) -> str:
        return self.record.confidence or ""

    @property
    def stages(self) -> tuple[str, ...]:
        """The stages `## Influences` names: where this record is eligible."""

        return tuple(
            dict.fromkeys(influence.stage for influence in self.record.influences)
        )

    @property
    def routed_text(self) -> str:
        """What reaches a stage: the statement, whole (§2.2)."""

        return self.record.document.section("Statement") or ""

    @property
    def is_weak(self) -> bool:
        return self.effective_status is KnowledgeStatus.WEAK_CANDIDATE

    @property
    def flags(self) -> tuple[str, ...]:
        """What §5 flagged this record with. A rule kept in force says so here.

        A demotion is legible from the effective status alone. A rule §5 keeps
        enforced past its `review_by` keeps its status, so without the flag
        nothing in the trace would show that nobody re-checked it.
        """

        return (EXPIRED_REVIEW,) if self.expired_review else ()

    @property
    def mandatory(self) -> bool:
        return self.tier in MANDATORY_TIERS

    @property
    def reducible(self) -> bool:
        return self.effective_status in REDUCIBLE_STATUSES

    def ref(self, *, reinforced_by: Optional[str] = None) -> KnowledgeRef:
        """This record as it was at the time of use (§9.4)."""

        return KnowledgeRef(
            record_id=self.identity,
            record_version=self.version,
            tier=self.tier,
            file_status=self.file_status,
            effective_status=self.effective_status,
            reinforced_by=reinforced_by,
        )


@dataclass(frozen=True, slots=True)
class LoadedCheck:
    """One check record, and the stage its own `## Route` table applies it at."""

    check: CheckRecord
    version: int
    #: The stage the route rows leave. ``None`` when every row is terminal or a
    #: hint, which is a check the register does not place: a stage that applies
    #: one says so itself, out of its Step 2 contract.
    applied_at: Optional[str]

    @property
    def identity(self) -> str:
        return self.check.check_id

    @property
    def digest(self) -> str:
        return self.check.document.digest

    @property
    def is_hard(self) -> bool:
        return self.check.is_hard

    @property
    def routed_text(self) -> str:
        """What reaches a stage: the rule that must hold (§3)."""

        return self.check.document.section("Rule") or ""


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    """Every record a run loaded, with today's effective statuses."""

    records: tuple[LoadedRecord, ...]
    checks: tuple[LoadedCheck, ...]
    #: The label vocabulary. It is here because every S-00…S-13 stage declares
    #: it forbidden to its own requests (Step 2 §0.7, AD-07), and a caller that
    #: had to remember to fetch it is a caller that can forget.
    forbidden_terms: tuple[str, ...]
    #: The day the effective statuses were computed for.
    loaded_on: date

    def record(self, identity: str) -> LoadedRecord:
        """The loaded record, or :class:`LoaderError` if it is not loaded."""

        for loaded in self.records:
            if loaded.identity == identity:
                return loaded
        raise LoaderError(
            f"{identity} is not loaded into this run; a retired record never is, "
            "and a record that is not in the register never was"
        )

    def select(self, stage: str, inputs: StageInputs) -> "KnowledgeSelection":
        """Eligibility × applicability for one stage (§9.3)."""

        eligible = tuple(
            RoutedKnowledge.of_record(
                loaded, applicable=applies(loaded.condition, inputs)
            )
            for loaded in self.records
            if stage in loaded.stages
        )
        return KnowledgeSelection(
            stage=stage,
            eligible=in_precedence_order(eligible),
            checks=tuple(
                check for check in self.checks if check.applied_at == stage
            ),
        )


def load_register(
    register_dir: Path, *, today: Optional[date] = None
) -> KnowledgeBase:
    """Read a register into a run. Raises :class:`LoaderError`.

    Retired records are not loaded (§9.2), and everything else arrives with the
    effective status §5 gives it today. A file this cannot read is an error and
    not a record left out: the register was supposed to have passed
    :func:`~src.knowledge.run_start.validate_at_run_start` before a run got here,
    so anything unreadable at this point is a register nobody validated.
    """

    when = today or date.today()
    try:
        vocabularies = load_vocabularies(register_dir)
    except VocabularyError as exc:
        raise LoaderError(str(exc)) from exc

    loaded: list[LoadedRecord] = []
    for path in (
        *sorted((register_dir / RECORDS_DIR_NAME).rglob("*.md")),
        *sorted((register_dir / LADDERS_DIR_NAME).glob("*.md")),
    ):
        try:
            record = record_format.parse_knowledge_record(load_document(path))
        except (DocumentError, RecordError) as exc:
            raise LoaderError(str(exc)) from exc
        if record.status == KnowledgeStatus.RETIRED.value:
            continue
        try:
            condition = parse_condition(record.applies_when, vocabularies)
        except ConditionError as exc:
            raise LoaderError(f"{record.path}: {exc}") from exc
        loaded.append(_loaded_record(record, condition, when))

    checks: list[LoadedCheck] = []
    for path in sorted((register_dir / CHECKS_DIR_NAME).glob("*.md")):
        try:
            check = record_format.parse_check_record(load_document(path))
        except (DocumentError, RecordError) as exc:
            raise LoaderError(str(exc)) from exc
        checks.append(
            LoadedCheck(
                check=check,
                version=_version(check.version_number, check.path),
                applied_at=_applied_at(check),
            )
        )

    return KnowledgeBase(
        records=tuple(loaded),
        checks=tuple(checks),
        forbidden_terms=vocabularies.get("labels").names,
        loaded_on=when,
    )


def effective_status(
    file_status: KnowledgeStatus, review_by: date, *, today: date
) -> tuple[KnowledgeStatus, bool]:
    """What a record counts as today, and whether its review has lapsed (§5).

    `descriptive` and `candidate` are demoted to `weak-candidate`; every other
    status stays exactly as written and is flagged instead. That asymmetry is the
    whole of §5: old descriptions stop carrying weight, and old rules go on being
    rules, because the safest admissible reading of a hard rule nobody re-checked
    is the stricter one.
    """

    expired = review_by < today
    if expired and file_status in (
        KnowledgeStatus.DESCRIPTIVE,
        KnowledgeStatus.CANDIDATE,
    ):
        return KnowledgeStatus.WEAK_CANDIDATE, True
    return file_status, expired


# ----------------------------------------------------------------------
# What one stage was routed (§9.3, §9.6)
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoutedKnowledge:
    """One register item selected for one stage, and what it may do there."""

    identity: str
    version: int
    digest: str
    text: str
    mandatory: bool
    reducible: bool
    #: The record this came from. Absent for a check, which has no tier and no
    #: KnowledgeRef: a check is a rule a stage applies, not knowledge in a
    #: conflict.
    record: Optional[LoadedRecord] = None
    #: Whether its condition held for this stage's inputs (§4). An eligible
    #: record that did not apply is kept, because the routing evidence records
    #: the result per record rather than only the records that survived.
    applicable: bool = True
    reinforced_by: Optional[str] = None

    @classmethod
    def of_record(
        cls, loaded: LoadedRecord, *, applicable: bool
    ) -> "RoutedKnowledge":
        return cls(
            identity=loaded.identity,
            version=loaded.version,
            digest=loaded.digest,
            text=loaded.routed_text,
            mandatory=loaded.mandatory,
            reducible=loaded.reducible,
            record=loaded,
            applicable=applicable,
        )

    @classmethod
    def of_check(cls, check: LoadedCheck) -> "RoutedKnowledge":
        return cls(
            identity=check.identity,
            version=check.version,
            digest=check.digest,
            text=check.routed_text,
            mandatory=check.is_hard,
            reducible=False,
        )

    @property
    def is_weak(self) -> bool:
        return self.record is not None and self.record.is_weak

    @property
    def acts_alone(self) -> bool:
        """A weak candidate nothing reinforces, which §5.1 rule 1 limits."""

        return self.is_weak and self.reinforced_by is None

    @property
    def expired_review(self) -> bool:
        return self.record is not None and self.record.expired_review

    def ref(self) -> KnowledgeRef:
        """The KnowledgeRef for the trace. Checks have none."""

        if self.record is None:
            raise LoaderError(
                f"{self.identity} is a check record, and a KnowledgeRef records a "
                "knowledge record's tier and status (§9.4)"
            )
        return self.record.ref(reinforced_by=self.reinforced_by)


@dataclass(frozen=True, slots=True)
class KnowledgeSelection:
    """What one stage was routed, and what it read and did not apply."""

    stage: str
    #: Every eligible record, applicable or not, in precedence order.
    eligible: tuple[RoutedKnowledge, ...]
    checks: tuple[LoadedCheck, ...]

    @property
    def routed(self) -> tuple[RoutedKnowledge, ...]:
        """The applicable records: what actually reaches the stage (§9.3)."""

        return tuple(item for item in self.eligible if item.applicable)

    @property
    def mandatory(self) -> tuple[RoutedKnowledge, ...]:
        """Applicable mandatory records, and every hard check of this stage."""

        return (
            *(item for item in self.routed if item.mandatory),
            *(
                RoutedKnowledge.of_check(check)
                for check in self.checks
                if check.is_hard
            ),
        )

    @property
    def reducible(self) -> tuple[RoutedKnowledge, ...]:
        return tuple(item for item in self.routed if item.reducible)


def in_precedence_order(
    items: Sequence[RoutedKnowledge],
) -> tuple[RoutedKnowledge, ...]:
    """Strongest first: tier, then §5.1 rule 2 inside a tier, then confidence.

    §5.1 rule 2 is the whole of it: a weak candidate **keeps its tier** and
    loses to any non-expired record *of that tier*, whatever the confidences.
    "Within tier 3, the order is therefore: non-expired by confidence, then
    weak-candidates by confidence."

    This is the conflict ladder, and it is not the cut order — see
    :func:`in_reduction_order`. One key used to serve both, which is how an
    expired tier-3 candidate survived a capacity cut ahead of fresh tier-4
    knowledge (#331 review).
    """

    return tuple(sorted(items, key=_precedence_key))


def in_reduction_order(
    items: Sequence[RoutedKnowledge],
) -> tuple[RoutedKnowledge, ...]:
    """Most expendable first — what §9.6 cuts when the request is too large.

    §9.6: reducible records "are cut in tier order, then by confidence,
    **weak-candidates first**". That last clause is a different order from the
    precedence ladder, not a restatement of it: a weak candidate nothing
    reinforces goes before every record that still acts on its own, whatever
    the tiers.

    Which is the point of the demotion. On the ladder a demoted record keeps
    its tier, because §5.1 rule 2 says so and a conflict is decided inside a
    tier. Deciding what to *drop* is not a conflict: a record nobody has
    re-checked is the most expendable thing in the request, and letting its
    old tier defend it would hand it the authority the demotion took away.

    Reading the precedence order backwards gave exactly that, and no test saw
    it because within one tier the two orders agree.
    """

    return tuple(sorted(items, key=_reduction_key))


def _precedence_key(item: RoutedKnowledge) -> tuple[int, int, int, str]:
    loaded = item.record
    if loaded is None:
        # A check is never cut and never loses a conflict; it sorts above the
        # ladder rather than being given a tier it does not have.
        return (-1, 0, 0, item.identity)
    rank = tier_rank(loaded.tier)
    return (
        -1 if rank is None else rank,
        1 if item.acts_alone else 0,
        _CONFIDENCE_RANK.get(loaded.confidence, len(_CONFIDENCE_RANK)),
        item.identity,
    )


def _reduction_key(item: RoutedKnowledge) -> tuple[int, int, int, str]:
    """Most expendable first, which is the order §9.6 cuts in.

    The reverse of the ladder in every component, with one difference that is
    the whole point: the unreinforced-weak flag comes first, so a demoted
    record is cut before anything that still acts on its own, whatever the
    tiers. After that, the weakest tier goes first and then the lowest
    confidence — `tier_rank` counts 0 as strongest and `_CONFIDENCE_RANK`
    counts `high` as 0, so both are negated to put the weak end in front.
    """

    loaded = item.record
    if loaded is None:
        # A check is never cut (§9.6 reduces only descriptive, candidate and
        # weak-candidate records), so it sorts last: the least expendable
        # thing in the request.
        return (2, 0, 0, item.identity)
    rank = tier_rank(loaded.tier)
    return (
        0 if item.acts_alone else 1,
        # A tier the ladder does not place is the strongest there is, so it is
        # the last thing to drop rather than the first.
        1 if rank is None else -rank,
        -_CONFIDENCE_RANK.get(loaded.confidence, len(_CONFIDENCE_RANK)),
        item.identity,
    )


def may_exclude(items: Sequence[RoutedKnowledge]) -> bool:
    """May an exclusion, a `REPLAN` or a `SKIP` rest on these records? (§5.1 r1)

    No, when every one of them is a weak candidate nothing reinforces: at S-09 a
    candidate strategy is never excluded solely because it conflicts with one,
    and at S-11 and S-13 no route is triggered solely by one. The stage records
    the conflict as a hint instead.
    """

    return any(not item.acts_alone for item in items)


def reinforced(
    item: RoutedKnowledge, by: LoadedRecord
) -> RoutedKnowledge:
    """Record that a non-expired record lets a weak candidate count (§5.1 r3).

    Two halves, and only one of them is code's. Whether ``by`` points the same
    way is the reading of the stage that met the conflict, and asserting it is
    what calling this means. Whether ``by`` is allowed to carry that weight —
    that it is not the record itself, that its own review has not lapsed, and
    that its tier is the same or higher — is a fact about the register, and is
    checked here.
    """

    if item.record is None:
        raise LoaderError(
            f"{item.identity} is a check record; reinforcement is what lets a "
            "demoted knowledge record count at its original weight (§5.1)"
        )
    if not item.is_weak:
        raise LoaderError(
            f"{item.identity} is not a weak candidate, so nothing reinforces it: "
            "a record that was not demoted already counts at its own weight"
        )
    if by.identity == item.identity:
        raise LoaderError(f"{item.identity} cannot reinforce itself")
    if by.is_weak:
        raise LoaderError(
            f"{by.identity} is itself a weak candidate; §5.1 rule 3 is a "
            "non-expired record pointing the same way, and two demoted records "
            "do not add up to one"
        )
    if by.expired_review:
        raise LoaderError(
            f"{by.identity} is past its own `review_by`; §5 keeps a rule of that "
            "kind enforced, which is its status and not its currency, and §5.1 "
            "rule 3 asks for a record somebody has re-checked"
        )
    item_rank = tier_rank(item.record.tier)
    by_rank = tier_rank(by.tier)
    if item_rank is not None and by_rank is not None and by_rank > item_rank:
        raise LoaderError(
            f"{by.identity} is tier {by.tier.value} and {item.identity} is tier "
            f"{item.record.tier.value}; a weak candidate is reinforced by the "
            "same tier or a higher one, never by a weaker record"
        )
    return replace(item, reinforced_by=by.identity)


# ----------------------------------------------------------------------
# Size discipline (§9.6)
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KnowledgePacking:
    """What fits in one request, and what was cut to make it fit."""

    stage: str
    mandatory: tuple[RoutedKnowledge, ...]
    included: tuple[RoutedKnowledge, ...]
    #: The remainder, which the StageRecord records (§9.6).
    excluded: tuple[RoutedKnowledge, ...]
    mandatory_size: int
    size: int
    capacity: int

    @property
    def routed(self) -> tuple[RoutedKnowledge, ...]:
        """Everything the request carries, mandatory first."""

        return (*self.mandatory, *self.included)

    @property
    def refs(self) -> tuple[KnowledgeRef, ...]:
        """A KnowledgeRef per routed knowledge record; checks have none."""

        return tuple(item.ref() for item in self.routed if item.record is not None)


class MandatoryKnowledgeExceedsCapacity(LoaderError):
    """The knowledge that may never be cut did not fit, so nothing is returned.

    Raised instead of handing back a request surface, because §9.6's "the call
    is not made" has to be something the caller cannot get around by accident: a
    stage that never receives the material cannot send an incomplete hard-policy
    surface with it.
    """

    def __init__(self, packing: KnowledgePacking) -> None:
        self.packing = packing
        named = ", ".join(item.identity for item in packing.mandatory)
        super().__init__(
            f"{packing.stage}: the mandatory knowledge is {packing.mandatory_size} "
            f"of a capacity of {packing.capacity}, and §9.6 never truncates it. "
            f"The call is not made: {named}"
        )

    def outcome(self, *, scope_key: Optional[str] = None) -> OutcomeRecord:
        """The `SKIP` the StageRecord records, at the stage's own scope."""

        packing = self.packing
        return OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=StateCode.MANDATORY_KNOWLEDGE_EXCEEDS_CAPACITY,
            scope=outcome_scope(packing.stage),
            scope_key=scope_key,
            reason=(
                f"mandatory knowledge of {packing.mandatory_size} did not fit a "
                f"capacity of {packing.capacity}; no call was made"
            ),
            knowledge=packing.refs,
        )


def fit_to_capacity(
    selection: KnowledgeSelection,
    *,
    capacity: int,
    size_of: Optional[Callable[[RoutedKnowledge], int]] = None,
) -> KnowledgePacking:
    """Fit one stage's knowledge into one request (§9.6).

    Raises :class:`MandatoryKnowledgeExceedsCapacity` when the mandatory set
    alone is over capacity. Otherwise the reducible records are added in
    precedence order and cut from the weak end: once one does not fit, the rest
    of the order goes with it, which is what cutting in tier order means.

    ``size_of`` measures one item however the caller measures a request —
    characters by default, tokens where a stage counts tokens.
    """

    if capacity < 0:
        raise LoaderError(f"a request capacity is not negative; got {capacity}")
    measure = size_of or (lambda item: len(item.text))

    mandatory = selection.mandatory
    mandatory_size = sum(measure(item) for item in mandatory)
    packing = KnowledgePacking(
        stage=selection.stage,
        mandatory=mandatory,
        included=(),
        excluded=selection.reducible,
        mandatory_size=mandatory_size,
        size=mandatory_size,
        capacity=capacity,
    )
    if mandatory_size > capacity:
        raise MandatoryKnowledgeExceedsCapacity(packing)

    included: list[RoutedKnowledge] = []
    size = mandatory_size
    remaining = list(selection.reducible)
    while remaining:
        item = remaining[0]
        item_size = measure(item)
        if size + item_size > capacity:
            break
        included.append(remaining.pop(0))
        size += item_size

    return replace(
        packing,
        included=tuple(included),
        excluded=tuple(remaining),
        size=size,
    )


def outcome_scope(stage: str) -> OutcomeScope:
    """What a `SKIP` at this stage concerns (§9.6, Step 2 §0.2)."""

    try:
        scope = CANONICAL_TOPOLOGY.stage(stage).scope
    except KeyError as exc:
        raise LoaderError(str(exc)) from exc
    outcome = _OUTCOME_SCOPES.get(scope)
    if outcome is None:
        raise LoaderError(
            f"{stage} runs at {scope.value} scope, which no outcome concerns; "
            "the observation stage is outside the run's scopes"
        )
    return outcome


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _loaded_record(
    record: KnowledgeRecord, condition: Condition, when: date
) -> LoadedRecord:
    file_status = _status(record.status, record.path)
    if file_status is KnowledgeStatus.WEAK_CANDIDATE:
        # Rule 1 of §8 refuses this, and a run reaches here only on a register
        # that passed. Refusing it again costs a line and closes the one way a
        # file could hand the loader a status the loader is supposed to compute.
        raise LoaderError(
            f"{record.path}: `status` is `{KnowledgeStatus.WEAK_CANDIDATE.value}`, "
            "which the loader computes from `review_by` and is never written in "
            "a file (§2.3)"
        )
    tier = _tier(record.tier, record.path)
    if not record_format.is_date(record.review_by):
        raise LoaderError(
            f"{record.path}: `review_by` is {record.review_by!r}, and expiry is "
            "computed from it (§5)"
        )
    status, expired = effective_status(
        file_status, date.fromisoformat(record.review_by or ""), today=when
    )
    return LoadedRecord(
        record=record,
        condition=condition,
        version=_version(record.version_number, record.path),
        tier=tier,
        file_status=file_status,
        effective_status=status,
        expired_review=expired,
    )


def _applied_at(check: CheckRecord) -> Optional[str]:
    sources: set[str] = set()
    for row in check.routes:
        edge = row.edge
        if edge is not None:
            sources.add(edge[0])
    if len(sources) == 1:
        return sources.pop()
    return None


def _version(version: Optional[int], path: str) -> int:
    if version is None:
        raise LoaderError(
            f"{path}: `version` is not a whole number from 1 upwards, and every "
            "reference to this record carries it (§9.4)"
        )
    return version


def _status(value: Optional[str], path: str) -> KnowledgeStatus:
    try:
        return KnowledgeStatus(value)
    except ValueError as exc:
        raise LoaderError(
            f"{path}: `status` is {value!r}, which is not one of "
            f"{', '.join(member.value for member in KnowledgeStatus)}"
        ) from exc


def _tier(value: Optional[str], path: str) -> KnowledgeTier:
    try:
        return KnowledgeTier(value)
    except ValueError as exc:
        raise LoaderError(
            f"{path}: `tier` is {value!r}, which is not one of "
            f"{', '.join(member.value for member in KnowledgeTier)}"
        ) from exc
