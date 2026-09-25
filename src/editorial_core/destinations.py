"""S-07 · Destinations: six decisions, every one of them a rule (AD-02).

The stage that says which destinations a unit is attempted on, with which mode
and which publication dependencies. AD-02 settles what it is: "S-07 is a
**deterministic** step, not a model judgment", and §1 puts the same thing twice —
``Calls: 0``, ``Decider: rule / code only`` — so a model call is not a design
option here that this module declines to take. There is no transport in it.

What each decision is made of
-----------------------------
**Eligibility**, in AD-02's own order: the destinations the Client Contract
enables, minus those it excludes for this unit's topic or risk level (tier 2),
minus those a hard platform policy record forbids the material on (tier 1), minus
those cadence defers (AD-02 §2). Every exclusion carries one
:class:`ExclusionRule` and the tier that gives that rule authority — which is the
whole point of a deterministic S-07: "every exclusion explainable by one rule and
one tier".

Where several rules refuse the same destination, the decision cites the one with
**the most authority** (map §5): a client reading it learns which rule would have
to change, and a tier-1 platform record that forbids the material is not made
optional by a contract row that also happened to refuse.

**Mode**, from the three inputs AD-02 §3 says "must never be confused":

1. the contract enables publishing for that destination (tier 2, and its own
   choice — "``generate_only`` is a temporary migration state, **or** a contract
   choice");
2. the destination is **capable**: "it has a publisher, package, preflight, an
   idempotency authority (Step 3 §3.6) and a metrics collector". The idempotency
   authority is checked and reported on its own, because Step 3 §3.6 rule 7 names
   it on its own: a destination without one "can only be ``generate_only``", and
   it is the one missing part whose absence risks a second publication rather
   than a missing feature;
3. the **rollout scope** includes it — a deployment setting, temporary, whose
   AS-IS value is ``release_scope.R1_PUBLISH_CHANNELS``.

All three, or ``generate_only``. Nothing here is a judgment about the material:
"a destination for which no admissible strategy exists fails at S-08/S-11"
(AD-02 §4), and fit is never predicted up front.

**Publication dependencies**, recorded separately from content (AD-02 §5). A
dependency is publication **order** and never content derivation (I-06): the
LinkedIn post may link to the Wix article, and that fact makes Wix publish first
(§0.2) and makes nothing of the article a source for the post. A link whose
target this unit excluded is not recorded as a dependency — an order cannot wait
on a destination that will never run — and it is not silently forgotten either:
:attr:`DestinationDecision.dropped_dependencies` names it, so the reason the link
is missing is in the decision rather than only in another destination's skip.

What the stage refuses
----------------------
A **cycle** in the dependencies, at construction. §0.2 makes dependency order the
first ordering criterion for budget exhaustion and for publication, and a set
with a cycle has no such order — so the refusal belongs where the set is built
rather than where S-14 would discover it with a post already published.

A **tier other than 1** on a platform policy. §1 gives this stage "hard platform
policy records (``K-DST-*`` at tier 1 only)", and the register holds K-DST
records at tiers 3 and 4 as well: those act at S-08 and S-10, where AD-02 moved
them, and a descriptive record that excluded a destination outright would be a
ranking note with the authority of a platform rule.

**Silence as admission.** A contract row that refuses a set of topics, applied to
a unit that states no topic key, refuses: "the contract listed what it takes, and
a signal that does not say which of them it is has not been shown to be one"
(``signal_selection``, the same direction for the same reason). For a destination
the direction is the same one: nothing is published that the contract has not
been shown to allow.

**Production safety.** No model call, no external call, and nothing calls this
stage: the run harness still executes S-07 as the SL-1 pass-through, and wiring
the stages of SL-5 into it is a later slice. The AS-IS capability table and the
AS-IS rollout scope reproduce today's behaviour exactly — Wix and LinkedIn
publish, the other four are generated — so nothing about production changes even
once a caller exists.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.2 and §2
(S-07); ``docs/editorial/architecture/02_ARCHITECTURE_DECISIONS.md`` AD-02;
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §4 (E-12);
``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §2.2, §2.3,
§2.5, §3.6; ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §5, §6.2, §8.6.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Optional

from src.artifacts import _validate_path_component
from src.editorial_core.anchor import Anchor
from src.editorial_core.arp import (
    ArpOutcome,
    KnowledgeRef,
    KnowledgeTier,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
    tier_rank,
)
from src.editorial_core.editorial_units import (
    UNITS_DIRECTORY,
    EditorialUnit,
    UnitStatus,
)
from src.knowledge.loader import KnowledgeBase, StageInputs

# The one authorization boundary the rollout scope is: `release_scope.py` is what
# AD-02's Seam row turns into the rollout-scope setting, and #227 is why the list
# is imported rather than restated — a duplicated list is a list that drifts.
from src.publishing.release_scope import (
    NON_R1_PUBLISH_CHANNELS,
    R1_PUBLISH_CHANNELS,
)
from src.run.run_manifest import EntityIndexEntry
from src.run.run_workspace import RunWorkspace

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-07"

#: The entity it is the sole producer of (§1, Outputs).
DECISION_ENTITY_TYPE: Final[str] = "E-12"

#: Where a decision lives inside the unit's directory (§2.2).
DESTINATIONS_DIRECTORY: Final[str] = "destinations"
DECISION_FILE_NAME: Final[str] = "decision.json"


class DestinationError(RuntimeError):
    """S-07 was asked to decide something its contract cannot decide."""


# ===========================================================================
# The vocabularies (Step 1 §4, E-12)
# ===========================================================================


class Destination(str, Enum):
    """The six surfaces of the target architecture (AD-02 §3, Step 1 §4).

    All six, because the target supports all six: "the finished canonical run
    publishes to all six". Which of them today's deployment *publishes* to is the
    rollout scope's answer and not this enum's, and the difference between the two
    is the one AD-02 says must never be confused.
    """

    WIX = "wix"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    THREADS = "threads"
    TELEGRAM = "telegram"


def _mirror_release_scope() -> None:
    """Refuse a drift between this vocabulary and its one authority (#227).

    ``release_scope.py`` is the authorization boundary, and the knowledge
    register's ``destinations`` vocabulary is already mirrored against it by the
    register validator. This makes the third copy the same kind of copy: a
    destination added to the release lists and not here, or here and not there,
    fails at import rather than at the first run that meets it.
    """

    drifted = {member.value for member in Destination} ^ {
        *R1_PUBLISH_CHANNELS,
        *NON_R1_PUBLISH_CHANNELS,
    }
    if drifted:
        raise DestinationError(
            "the E-12 destination vocabulary and src/publishing/release_scope.py "
            f"disagree about {', '.join(sorted(drifted))}; there is one list of "
            "surfaces and #227 is what a second one costs"
        )


_mirror_release_scope()


#: The rollout scope, AS-IS (AD-02 §3): "a deployment setting listing which
#: capable destinations are switched on for publishing … The current
#: ``R1_PUBLISH_CHANNELS`` (Wix + LinkedIn) is an **AS-IS fact** about today's
#: release, not a target constraint." Temporary by contract: "when all six
#: destinations are capable and enabled, the rollout scope equals the contract's
#: destinations and can be removed".
ROLLOUT_SCOPE: Final[frozenset[Destination]] = frozenset(
    Destination(name) for name in R1_PUBLISH_CHANNELS
)


class Eligibility(str, Enum):
    """E-12's ``eligibility``. Every declared destination gets one (§1 Post)."""

    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"


class ExclusionRule(str, Enum):
    """E-12's ``exclusion_rule``: "always a rule with a tier, never 'model
    judged'"."""

    CONTRACT_DISABLED = "contract_disabled"
    CONTRACT_TOPIC = "contract_topic"
    CONTRACT_RISK = "contract_risk"
    HARD_PLATFORM_POLICY = "hard_platform_policy"
    CADENCE = "cadence"


#: Which tier gives each rule its authority (map §5). A table rather than a
#: field on the rule, because the tier is a property of *who wrote the rule* and
#: not of the row that applies it: a caller that could state the tier could give
#: a cadence preference the authority of a platform rule.
_RULE_TIERS: Mapping[ExclusionRule, KnowledgeTier] = {
    ExclusionRule.CONTRACT_DISABLED: KnowledgeTier.APPROVED_CLIENT_RULE,
    ExclusionRule.CONTRACT_TOPIC: KnowledgeTier.APPROVED_CLIENT_RULE,
    ExclusionRule.CONTRACT_RISK: KnowledgeTier.APPROVED_CLIENT_RULE,
    ExclusionRule.HARD_PLATFORM_POLICY: KnowledgeTier.HARD_PLATFORM_POLICY,
    # AD-02 §2 states cadence and portfolio pressure together, and the map puts
    # portfolio at tier 5: the rule is the client's, what it measures is the
    # portfolio, and it is the softest thing that can nonetheless defer a
    # destination outright.
    ExclusionRule.CADENCE: KnowledgeTier.PORTFOLIO,
}

#: Which state code each rule is recorded as. Three codes for five rules,
#: because the skip rate is read by reason (map §6.3) and two of the contract's
#: three rules are the same reason: the contract does not take this destination
#: for this material. The risk level keeps the map's own row.
_RULE_STATE_CODES: Mapping[ExclusionRule, StateCode] = {
    ExclusionRule.CONTRACT_DISABLED: StateCode.DESTINATION_OUTSIDE_CONTRACT,
    ExclusionRule.CONTRACT_TOPIC: StateCode.DESTINATION_OUTSIDE_CONTRACT,
    ExclusionRule.CONTRACT_RISK: StateCode.HIGH_STAKES_OUTSIDE_RISK_LEVEL,
    ExclusionRule.HARD_PLATFORM_POLICY: StateCode.HARD_PLATFORM_POLICY_FORBIDS,
    ExclusionRule.CADENCE: StateCode.DESTINATION_DEFERRED_BY_CADENCE,
}


class DestinationMode(str, Enum):
    """E-12's ``mode``. Set only for an eligible destination."""

    PUBLISH = "publish"
    GENERATE_ONLY = "generate_only"


class ModeRule(str, Enum):
    """Why an eligible destination publishes, or only generates (AD-02 §3).

    Recorded as a rule of its own rather than folded into the eligibility rule,
    because the two answer different questions and §1's Trace column asks for
    both: "per destination: decision, rule, tier, **mode**, dependencies".
    """

    #: All three inputs hold: the contract enables it, it is capable, and the
    #: rollout scope includes it.
    PUBLISHES = "contract_capability_and_rollout_scope"
    #: The contract's own choice to generate and not publish — not a migration
    #: state, and the only one of these that the target keeps.
    CONTRACT_GENERATE_ONLY = "contract_generate_only"
    #: Step 3 §3.6 rule 7: "a destination may have ``mode = publish`` only if at
    #: least one idempotency authority exists for it … Otherwise S-07 must give
    #: it ``generate_only``." Reported before the rest of capability because a
    #: missing authority is the one gap that risks publishing twice.
    NO_IDEMPOTENCY_AUTHORITY = "no_idempotency_authority"
    #: Some other part of capability is missing: a publisher, a package, a
    #: preflight or a metrics collector (AD-02 §3).
    NOT_CAPABLE = "destination_not_capable"
    #: Capable and enabled, and today's deployment does not publish it.
    OUTSIDE_ROLLOUT_SCOPE = "outside_rollout_scope"


class DependencyKind(str, Enum):
    """E-12's ``publication_dependencies`` kind. One member, and Step 1 says so:
    "list of (target destination, kind = ``link``)"."""

    LINK = "link"


# ===========================================================================
# What the stage is handed
# ===========================================================================


@dataclass(frozen=True, slots=True)
class UnitFacts:
    """The unit's topic and risk facts, as the contract's rules read them.

    §1's Inputs column says these "come from the core and boundary". They are
    lifted out and handed over rather than discovered here, exactly as
    :class:`~src.editorial_core.signal_selection.SelectionCandidate` lifts the
    signal's ``topic_key``: neither fact has one fixed spelling in E-04, and S-07
    compares values rather than deciding what they are.

    ``None`` means the unit states nothing, which is not the same as stating
    something the contract allows — see :meth:`ContractDestination.refuses`.
    """

    topic_key: Optional[str] = None
    risk_level: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ContractDestination:
    """One destination as the Client Contract declares it (tier 2).

    The row is the destination's identity in the contract, so ``rule_id`` is
    cited by the decision whether it ends eligible or excluded — §1 Post asks for
    "exactly one decision, eligible or excluded, each with a rule and a tier".

    ``refused_topics`` and ``refused_risk_levels`` are exclusion lists, as AD-02
    states them: "minus those the contract excludes for this unit's topic or risk
    level". An empty list excludes nothing; a list the unit cannot be compared
    against excludes everything it was given.
    """

    destination: Destination
    rule_id: str
    enabled: bool = True
    refused_topics: tuple[str, ...] = ()
    refused_risk_levels: tuple[str, ...] = ()
    #: The contract's own answer to "may this destination be published to". False
    #: is a contract choice and not a migration state (Step 1, E-12).
    publishes: bool = True
    #: The destinations a text here may link to. Publication order only (I-06).
    links_to: tuple[Destination, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise DestinationError(
                f"the contract row for {self.destination.value} has no rule ID; "
                "every decision cites a rule, and a decision that cites nothing "
                "is the model judgment AD-02 removed"
            )
        if self.destination in self.links_to:
            raise DestinationError(
                f"{self.destination.value} is recorded as linking to itself; a "
                "publication dependency is an order between two destinations"
            )
        duplicated = sorted({
            target.value
            for target in self.links_to
            if self.links_to.count(target) > 1
        })
        if duplicated:
            raise DestinationError(
                f"the contract row for {self.destination.value} names "
                f"{', '.join(duplicated)} twice as a link target; one dependency "
                "on a destination is the whole of the order it imposes"
            )

    def refuses(self, facts: UnitFacts) -> Optional[ExclusionRule]:
        """Which of this row's three rules refuses the unit, if one does.

        In the order AD-02 lists them, and each fails closed on a fact the unit
        does not state: a row that names refused topics cannot show that an
        unnamed topic is not one of them, and the direction that publishes
        nothing the contract has not been shown to allow is the safe one.
        """

        if not self.enabled:
            return ExclusionRule.CONTRACT_DISABLED
        if self.refused_topics and _refused(facts.topic_key, self.refused_topics):
            return ExclusionRule.CONTRACT_TOPIC
        if self.refused_risk_levels and _refused(
            facts.risk_level, self.refused_risk_levels
        ):
            return ExclusionRule.CONTRACT_RISK
        return None


@dataclass(frozen=True, slots=True)
class ContractDestinations:
    """The contract's destination settings, as data rather than as branches.

    Required input (§1). The destinations it does **not** declare are not
    excluded: they are unknown to the contract, and
    :attr:`DestinationDecisionSet.undeclared` records them as that, so a reader
    can tell a destination the client turned off from one it never mentioned.
    """

    rows: tuple[ContractDestination, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise DestinationError(
                "the Client Contract's destination settings are a required input "
                f"of {STAGE}; a unit with no declared destination has nowhere to "
                "go, and that is a contract to fix rather than a run to make"
            )
        declared = [row.destination for row in self.rows]
        duplicated = sorted({
            item.value for item in declared if declared.count(item) > 1
        })
        if duplicated:
            raise DestinationError(
                "the Client Contract declares "
                + ", ".join(duplicated)
                + " twice; §1 Post gives every declared destination exactly one "
                "decision, and a destination two rows answer for has two"
            )
        identities = [row.rule_id for row in self.rows]
        repeated = sorted({
            item for item in identities if identities.count(item) > 1
        })
        if repeated:
            raise DestinationError(
                "contract rule ID(s) declared twice: "
                + ", ".join(repeated)
                + "; an exclusion names the rule that decided it, and a name two "
                "rows answer to names neither"
            )

    @property
    def destinations(self) -> tuple[Destination, ...]:
        """The declared destinations, in the contract's own order (§0.2 rule 2)."""

        return tuple(row.destination for row in self.rows)

    def row(self, destination: Destination) -> Optional[ContractDestination]:
        """The contract's row for this destination, or ``None`` if it has none."""

        for row in self.rows:
            if row.destination is destination:
                return row
        return None


@dataclass(frozen=True, slots=True)
class DestinationCapability:
    """What makes a destination capable (AD-02 §3).

    Five parts and all of them required: "a destination is **capable** when it has
    a publisher, package, preflight, an idempotency authority (Step 3 §3.6) and a
    metrics collector". A fact about the engine rather than about a client, which
    is why it is not in the contract.
    """

    destination: Destination
    publisher: bool
    package: bool
    preflight: bool
    idempotency_authority: bool
    metrics_collector: bool

    @property
    def capable(self) -> bool:
        """All five. A conjunction, because AD-02 states it as one."""

        return not self.missing

    @property
    def missing(self) -> tuple[str, ...]:
        """Which parts this destination does not have, for the trace.

        Named rather than counted: "not capable" is what decides the mode, and
        which part is absent is what a reader needs in order to know whether a
        release or a piece of work would change it.
        """

        return tuple(
            name
            for name, present in (
                ("publisher", self.publisher),
                ("package", self.package),
                ("preflight", self.preflight),
                ("idempotency_authority", self.idempotency_authority),
                ("metrics_collector", self.metrics_collector),
            )
            if not present
        )


def _capability(
    destination: Destination,
    *,
    package: bool,
    preflight: bool,
    metrics_collector: bool,
) -> DestinationCapability:
    """One AS-IS row. The two parts every destination has are not arguments.

    A publisher exists for all six (``src/publishing/{wix,linkedin,facebook,
    instagram,threads,telegram}.py``) and so does an idempotency authority:
    ``src/publishing/publication_markers.py`` keys all six, composed from the
    release lists rather than a list of its own. What differs between
    destinations today is the other three.
    """

    return DestinationCapability(
        destination=destination,
        publisher=True,
        package=package,
        preflight=preflight,
        idempotency_authority=True,
        metrics_collector=metrics_collector,
    )


#: Destination capability as this repository stands, per AD-02 §3. The evidence,
#: destination by destination:
#:
#: - **packages**: ``build_wix_publication_package`` and
#:   ``build_linkedin_publication_package`` in ``src/publishing/package.py``, and
#:   no others. Step 2's S-14 Seam row says the same thing — "packages and
#:   preflight exist today only for Wix and LinkedIn; they are extended to
#:   Facebook, Instagram, Threads, Telegram";
#: - **preflight**: ``src/publishing/preflight.py`` knows the credentials of two
#:   channels, Wix and LinkedIn;
#: - **metrics collectors**: ``src/analytics/`` holds ``blog.py`` (Wix) and
#:   ``linkedin.py``; its collector protocol lists the other four as planned.
#:
#: A table and not a computation: it is an AS-IS fact that a release changes, and
#: reading it out of the modules would make the editorial core depend on the
#: publishers to find out what it may decide. It is an argument with a default,
#: so a caller can state a different one and a test can check this one.
AS_IS_CAPABILITY: Mapping[Destination, DestinationCapability] = {
    Destination.WIX: _capability(
        Destination.WIX, package=True, preflight=True, metrics_collector=True
    ),
    Destination.LINKEDIN: _capability(
        Destination.LINKEDIN, package=True, preflight=True, metrics_collector=True
    ),
    Destination.FACEBOOK: _capability(
        Destination.FACEBOOK, package=False, preflight=False, metrics_collector=False
    ),
    Destination.INSTAGRAM: _capability(
        Destination.INSTAGRAM, package=False, preflight=False, metrics_collector=False
    ),
    Destination.THREADS: _capability(
        Destination.THREADS, package=False, preflight=False, metrics_collector=False
    ),
    Destination.TELEGRAM: _capability(
        Destination.TELEGRAM, package=False, preflight=False, metrics_collector=False
    ),
}


@dataclass(frozen=True, slots=True)
class PlatformPolicy:
    """One tier-1 hard platform policy record, as S-07 applies it.

    Resolved by the caller from the loaded register — :func:`platform_policies` is
    that resolution — for the reason S-04's probe families are: applicability is
    the record's own ``## Applies when``, evaluated by the loader's condition
    machinery against the stage's inputs, and expiry is computed against a day the
    core is given rather than one it reads (CE-1).

    What arrives here is therefore a record that **applies** to this destination
    for this material. S-07 does not re-judge it: AD-02 §4 forbids the stage a
    material judgment, and the record's `KnowledgeRef` is what the exclusion
    cites.
    """

    destination: Destination
    knowledge: KnowledgeRef

    def __post_init__(self) -> None:
        if self.knowledge.tier is not KnowledgeTier.HARD_PLATFORM_POLICY:
            raise DestinationError(
                f"{self.knowledge.record_id} is tier "
                f"{self.knowledge.tier.value} and is offered as a hard platform "
                f"policy; §1 gives {STAGE} K-DST records at tier 1 only, and the "
                "descriptive ones act at S-08 and S-10 where AD-02 moved them"
            )


def platform_policies(
    knowledge: KnowledgeBase, inputs: StageInputs
) -> tuple[PlatformPolicy, ...]:
    """The tier-1 records that forbid this destination's material (Step 4 §9.3).

    One destination per call, named by ``inputs.destination``, because a record's
    condition is evaluated per destination and a record that applies to one says
    nothing about another. The selection is the loader's own —
    ``KnowledgeBase.select`` is eligibility × applicability, in precedence order —
    so what this adds is the tier filter §1 states and nothing else: a second
    condition evaluator beside the register's would eventually be a second answer.

    Reads the loaded register rather than the directory: a retired record is never
    loaded, and a demoted one arrives with the demotion visible in its
    :class:`~src.editorial_core.arp.KnowledgeRef`. A record past its ``review_by``
    is **not** dropped — §5 demotes only descriptive and candidate records and
    keeps a hard rule in force, flagged for review, "because dropping a hard rule
    because nobody re-checked it is the unsafe direction", and a platform rule
    that stopped applying when nobody looked at it is exactly that drop.
    """

    named = inputs.destination
    if named is None:
        raise DestinationError(
            "a hard platform policy is resolved for one destination, and these "
            "stage inputs name none; `destination is …` is false without one, so "
            "every record would silently fail to apply and the tier-1 surface "
            "would be empty for a reason nobody recorded"
        )
    resolved = Destination(named)
    return tuple(
        PlatformPolicy(destination=resolved, knowledge=item.ref())
        for item in knowledge.select(STAGE, inputs).routed
        if item.record is not None
        and item.record.tier is KnowledgeTier.HARD_PLATFORM_POLICY
    )


@dataclass(frozen=True, slots=True)
class DestinationFingerprint:
    """A prior E-16 as S-07 counts it (§1, Inputs: "cadence state from prior
    E-16").

    A narrow view of the fingerprint rather than the entity itself, for the reason
    :class:`~src.editorial_core.signal_selection.PortfolioFingerprint` is one: the
    two facts below are all a cadence rule counts, and which fingerprints are
    *recent* is a question about the day the run happens on — a scheduling input
    the core is handed rather than one it reads (CE-1).
    """

    fingerprint_id: str
    destination: Destination
    #: Whether the text was published. A ``generate_only`` text took no slot in
    #: the calendar (§3.4 keeps its fingerprint too), so cadence does not count
    #: it: deferring a destination because it generated something is the mirror
    #: of the mistake AD-02 §3 warns about.
    published: bool


@dataclass(frozen=True, slots=True)
class CadenceRule:
    """One per-destination cadence rule (AD-02 §2), counted over the portfolio.

    ``allowed`` is how many publications this destination may already hold among
    the fingerprints the caller selected. At least one: a rule that allows none
    defers every unit forever, which is ``contract_disabled`` wearing another
    name and would be recorded as the wrong reason.
    """

    rule_id: str
    destination: Destination
    allowed: int

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise DestinationError(
                f"the cadence rule for {self.destination.value} has no rule ID; a "
                "deferral cites the rule that made it"
            )
        if self.allowed < 1:
            raise DestinationError(
                f"the cadence rule {self.rule_id} allows {self.allowed} "
                "publication(s); a rule that allows none defers every unit for "
                "ever, which is the contract disabling the destination and is "
                "recorded as that"
            )

    def defers(self, portfolio: Sequence[DestinationFingerprint]) -> bool:
        """Has this destination already had its allowance?"""

        published = sum(
            1
            for entry in portfolio
            if entry.destination is self.destination and entry.published
        )
        return published >= self.allowed


# ===========================================================================
# E-12 · Destination decision
# ===========================================================================


@dataclass(frozen=True, slots=True)
class PublicationDependency:
    """One recorded dependency: publication order, never content (I-06)."""

    target: Destination
    kind: DependencyKind = DependencyKind.LINK

    def as_entity(self) -> dict[str, str]:
        return {"target": self.target.value, "kind": self.kind.value}


@dataclass(frozen=True, slots=True)
class DestinationDecision:
    """``E-12``: one destination of one unit, decided (Step 1 §4).

    ``outcome`` is present for an excluded destination and **absent** for an
    eligible one, and the two are enforced against each other below. Step 1 marks
    the field required; what it is required to hold is an OutcomeRecord, and an
    OutcomeRecord is "one unresolved state, resolved" — an eligible destination
    left nothing unresolved. The cost of recording one anyway is named where the
    ledger reads these: a scope that simply completed "has no §6.2 state, and
    inventing one would make the indicators count it"
    (``run_summary.ScopeOutcome``), and the skip rate is the map's main indicator
    of autonomous operation. ``E-01.selection`` is written the same way, for the
    same reason.

    An eligible destination is not left undescribed by that absence: ``mode``,
    ``mode_rule`` and the dependencies say what was decided about it, and the
    eligibility itself is the verdict.
    """

    destination_decision_id: str
    unit_id: str
    destination: Destination
    eligibility: Eligibility
    #: The rule this decision cites, and the tier that gives it authority (§1
    #: Post, Trace). For an eligible destination it is the contract row that
    #: declares it; for an excluded one, the rule that refused.
    rule_ref: str
    tier: KnowledgeTier
    exclusion_rule: Optional[ExclusionRule] = None
    #: The record a tier-1 exclusion cites, as it was at the time of use.
    knowledge: Optional[KnowledgeRef] = None
    mode: Optional[DestinationMode] = None
    mode_rule: Optional[ModeRule] = None
    #: Which of AD-02 §3's five capability parts this destination does not have.
    #: Present only when capability is what withheld publication: "not capable"
    #: is what decides the mode, and which part is absent is what says whether a
    #: release or a piece of work would change it.
    capability_gaps: tuple[str, ...] = ()
    publication_dependencies: tuple[PublicationDependency, ...] = ()
    #: Link targets this unit will never publish, so no order can wait on them.
    #: Recorded rather than dropped silently: S-10 has to know that the plan it
    #: writes cannot carry the link the contract expected (R-2, AD-02 §5).
    dropped_dependencies: tuple[Destination, ...] = ()
    outcome: Optional[OutcomeRecord] = None

    def __post_init__(self) -> None:
        if not self.destination_decision_id.strip() or not self.unit_id.strip():
            raise DestinationError(
                "a destination decision is identified by its own ID and the unit "
                "it was made for"
            )
        if not self.rule_ref.strip():
            raise DestinationError(
                f"{self.destination_decision_id} cites no rule; §1 Post gives "
                "every decision a rule and a tier, which is what makes a "
                "deterministic S-07 explainable"
            )
        if self.eligibility is Eligibility.EXCLUDED:
            self._excluded()
            return
        self._eligible()

    def _excluded(self) -> None:
        if self.exclusion_rule is None:
            raise DestinationError(
                f"{self.destination_decision_id} is excluded and names no rule; "
                "AD-02 allows an exclusion only 'by recorded reason'"
            )
        if self.tier is not _RULE_TIERS[self.exclusion_rule]:
            raise DestinationError(
                f"{self.destination_decision_id} records tier "
                f"{self.tier.value} for rule {self.exclusion_rule.value}; the "
                "tier belongs to whoever wrote the rule "
                f"({_RULE_TIERS[self.exclusion_rule].value}) and is not a second "
                "opinion about it"
            )
        if (self.exclusion_rule is ExclusionRule.HARD_PLATFORM_POLICY) != (
            self.knowledge is not None
        ):
            raise DestinationError(
                f"{self.destination_decision_id} records rule "
                f"{self.exclusion_rule.value} with knowledge "
                f"{self.knowledge!r}; a tier-1 exclusion cites the record that "
                "forbids the material, and a contract or cadence rule cites its "
                "own rule ID and no record"
            )
        if self.mode is not None or self.mode_rule is not None:
            raise DestinationError(
                f"{self.destination_decision_id} is excluded and carries mode "
                f"{self.mode!r}; Step 1 sets the mode 'if eligible', and a mode "
                "on a destination that is not attempted says it will be"
            )
        if self.capability_gaps:
            raise DestinationError(
                f"{self.destination_decision_id} is excluded and records "
                "capability gaps; capability decides a mode, and an excluded "
                "destination has none — reading the two together would make a "
                "rule the client wrote look like work the engine owes"
            )
        if self.publication_dependencies:
            raise DestinationError(
                f"{self.destination_decision_id} is excluded and records "
                "publication dependencies; a dependency is an order among the "
                "destinations this unit publishes, and this one publishes nothing"
            )
        if self.outcome is None or self.outcome.outcome is not ArpOutcome.SKIP:
            raise DestinationError(
                f"{self.destination_decision_id} is excluded and records "
                f"{self.outcome!r}; §1's ARP column makes an exclusion a SKIP of "
                "the destination with its rule, and a destination left without "
                "one is a run that waits"
            )
        if self.outcome.scope is not OutcomeScope.DESTINATION:
            raise DestinationError(
                f"{self.destination_decision_id} records its SKIP at "
                f"{self.outcome.scope.value} scope; an exclusion skips the "
                "destination, and the unit keeps whatever destinations remain"
            )
        if self.outcome.state_code is not _RULE_STATE_CODES[self.exclusion_rule]:
            raise DestinationError(
                f"{self.destination_decision_id} refuses by "
                f"{self.exclusion_rule.value} and records state "
                f"{self.outcome.state_code.value}; the state a skip is counted "
                "under is derived from the rule that made it"
            )

    def _eligible(self) -> None:
        if self.exclusion_rule is not None or self.knowledge is not None:
            raise DestinationError(
                f"{self.destination_decision_id} is eligible and carries "
                f"exclusion rule {self.exclusion_rule!r}; Step 1 sets those 'if "
                "excluded', and a destination is one or the other"
            )
        if self.mode is None or self.mode_rule is None:
            raise DestinationError(
                f"{self.destination_decision_id} is eligible and states mode "
                f"{self.mode!r} by rule {self.mode_rule!r}; AD-02 §3 decides the "
                "mode from three inputs, and an eligible destination whose mode "
                "nobody stated would be read as publishing"
            )
        publishes = self.mode is DestinationMode.PUBLISH
        if publishes != (self.mode_rule is ModeRule.PUBLISHES):
            raise DestinationError(
                f"{self.destination_decision_id} records mode "
                f"{self.mode.value} by rule {self.mode_rule.value}; a destination "
                "publishes exactly when the contract enables it, it is capable "
                "and the rollout scope includes it (AD-02 §3), and every other "
                "rule is a reason it does not"
            )
        capability_withheld = self.mode_rule in (
            ModeRule.NO_IDEMPOTENCY_AUTHORITY,
            ModeRule.NOT_CAPABLE,
        )
        if capability_withheld != bool(self.capability_gaps):
            raise DestinationError(
                f"{self.destination_decision_id} records mode rule "
                f"{self.mode_rule.value if self.mode_rule else None} with "
                f"capability gaps {list(self.capability_gaps)}; a destination held "
                "back by capability names the parts it lacks, and one held back by "
                "the contract or the rollout scope lacks none"
            )
        if self.outcome is not None:
            raise DestinationError(
                f"{self.destination_decision_id} is eligible and records a "
                f"{self.outcome.outcome.value}; an OutcomeRecord is a state the "
                "stage could not resolve, and deciding the destination resolved "
                "it — a state code invented here is one the indicators count"
            )
        targets = [item.target for item in self.publication_dependencies]
        if self.destination in targets:
            raise DestinationError(
                f"{self.destination_decision_id} depends on itself; a publication "
                "dependency orders two destinations"
            )
        duplicated = sorted({
            target.value for target in targets if targets.count(target) > 1
        })
        if duplicated:
            raise DestinationError(
                f"{self.destination_decision_id} records a dependency on "
                f"{', '.join(duplicated)} twice"
            )
        overlap = sorted(
            {target.value for target in targets}
            & {target.value for target in self.dropped_dependencies}
        )
        if overlap:
            raise DestinationError(
                f"{self.destination_decision_id} records "
                f"{', '.join(overlap)} as both a dependency and a dropped one; a "
                "link target is one or the other, and S-10 reads the difference"
            )

    @property
    def publishes(self) -> bool:
        """Will this destination reach an external platform?"""

        return self.mode is DestinationMode.PUBLISH

    def as_entity(self) -> dict[str, Any]:
        """The E-12 body, written to ``destinations/<destination>/decision.json``."""

        return {
            "entity_type": DECISION_ENTITY_TYPE,
            "entity_id": self.destination_decision_id,
            "destination_decision_id": self.destination_decision_id,
            "unit_id": self.unit_id,
            "destination": self.destination.value,
            "eligibility": self.eligibility.value,
            "rule_ref": self.rule_ref,
            "tier": self.tier.value,
            "exclusion_rule": (
                None if self.exclusion_rule is None else self.exclusion_rule.value
            ),
            "knowledge": (
                None
                if self.knowledge is None
                else self.knowledge.model_dump(mode="json")
            ),
            "mode": None if self.mode is None else self.mode.value,
            "mode_rule": None if self.mode_rule is None else self.mode_rule.value,
            "capability_gaps": list(self.capability_gaps),
            "publication_dependencies": [
                item.as_entity() for item in self.publication_dependencies
            ],
            "dropped_dependencies": [
                target.value for target in self.dropped_dependencies
            ],
            "outcome": (
                None if self.outcome is None else self.outcome.model_dump(mode="json")
            ),
        }


@dataclass(frozen=True, slots=True)
class DestinationDecisionSet:
    """Every decision S-07 made for one unit, and the unit's own outcome.

    ``undeclared`` is the other half of §1's Post column. "Every destination
    known to the contract has exactly one decision" says nothing about the rest,
    and a reader that saw only five decisions could not tell the sixth from one
    that was excluded and lost. A destination the contract never mentioned is
    neither eligible nor excluded, and this is where it says so.
    """

    unit_id: str
    decisions: tuple[DestinationDecision, ...]
    undeclared: tuple[Destination, ...] = ()
    #: The unit's ``SKIP`` when no declared destination is eligible (§1, ARP).
    outcome: Optional[OutcomeRecord] = None

    def __post_init__(self) -> None:
        if not self.decisions:
            raise DestinationError(
                f"{self.unit_id} reached the end of {STAGE} with no decision at "
                "all; the contract declares at least one destination and every "
                "declared one is decided"
            )
        decided = [decision.destination for decision in self.decisions]
        duplicated = sorted({
            item.value for item in decided if decided.count(item) > 1
        })
        if duplicated:
            raise DestinationError(
                f"{self.unit_id} holds two decisions for "
                + ", ".join(duplicated)
                + "; §1 Post gives each destination exactly one"
            )
        overlap = sorted({item.value for item in decided} & {
            item.value for item in self.undeclared
        })
        if overlap:
            raise DestinationError(
                f"{self.unit_id} records "
                + ", ".join(overlap)
                + " as both decided and undeclared; a destination the contract "
                "declares is decided, and one it does not is not"
            )
        if set(decided) | set(self.undeclared) != set(Destination):
            missing = sorted(
                item.value
                for item in set(Destination) - set(decided) - set(self.undeclared)
            )
            raise DestinationError(
                f"{self.unit_id} accounts for neither a decision nor a "
                "non-declaration of "
                + ", ".join(missing)
                + "; the target has six destinations and a unit's record of them "
                "is complete or it is not a record"
            )
        if self.eligible and self.outcome is not None:
            raise DestinationError(
                f"{self.unit_id} has {len(self.eligible)} eligible destination(s) "
                f"and records a {self.outcome.outcome.value}; the unit's outcome "
                "here is the one §1 gives it for having none"
            )
        if not self.eligible:
            if self.outcome is None or self.outcome.outcome is not ArpOutcome.SKIP:
                raise DestinationError(
                    f"{self.unit_id} has no eligible destination and records "
                    f"{self.outcome!r}; §1's ARP column makes that a SKIP of the "
                    "unit with reason no_eligible_destination"
                )
            if self.outcome.scope is not OutcomeScope.UNIT:
                raise DestinationError(
                    f"{self.unit_id} records its SKIP at "
                    f"{self.outcome.scope.value} scope; a unit with nowhere to go "
                    "is skipped as a unit"
                )
        # A set with a cycle has no publication order, and §0.2 needs one
        # wherever order matters. Refused here rather than discovered by S-14
        # with a post already published.
        publication_order(self.decisions)

    @property
    def eligible(self) -> tuple[DestinationDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.eligibility is Eligibility.ELIGIBLE
        )

    @property
    def excluded(self) -> tuple[DestinationDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.eligibility is Eligibility.EXCLUDED
        )

    @property
    def publishing(self) -> tuple[DestinationDecision, ...]:
        """The destinations this unit will publish to, if their texts are
        accepted."""

        return tuple(decision for decision in self.eligible if decision.publishes)

    def decision(self, destination: Destination) -> Optional[DestinationDecision]:
        """The decision for this destination, or ``None`` when undeclared."""

        for decision in self.decisions:
            if decision.destination is destination:
                return decision
        return None


def publication_order(
    decisions: Sequence[DestinationDecision],
) -> tuple[Destination, ...]:
    """The order §0.2 processes a unit's destinations in.

    Three criteria, in §0.2's own numbering:

    1. **the order of ``publication_dependencies``**: a destination that others
       link to goes first, "because the social posts may link to the article";
    2. **otherwise the Client Contract's listed order**, which is the order the
       decisions were made in;
    3. **during migration only: ``publish`` destinations before ``generate_only``
       ones**, so that a tight budget protects what is actually published.

    Criterion 3 only ever separates destinations criterion 2 left level, and the
    contract's order is total over the destinations it declares — so while that
    holds it changes nothing, and it is applied where §0.2 puts it rather than
    promoted above the contract's own order.

    Raises on a cycle: a dependency that waits on a destination which waits on it
    has no order, and answering with some order anyway would publish one of them
    before its link target existed.
    """

    pending = [
        decision
        for decision in decisions
        if decision.eligibility is Eligibility.ELIGIBLE
    ]
    listed = {decision.destination: index for index, decision in enumerate(pending)}
    waiting_for = {
        decision.destination: {
            item.target
            for item in decision.publication_dependencies
            if item.target in listed
        }
        for decision in pending
    }
    ordered: list[Destination] = []
    placed: set[Destination] = set()
    while waiting_for:
        ready = [
            destination
            for destination, blockers in waiting_for.items()
            if not blockers - placed
        ]
        if not ready:
            raise DestinationError(
                "the publication dependencies of "
                + ", ".join(sorted(item.value for item in waiting_for))
                + " wait on each other; §0.2 orders a unit's destinations by "
                "their dependencies, and a cycle has no such order"
            )
        # Criterion 2 then criterion 3: the contract's order, and — where two
        # destinations are level in it, which a total order never leaves them —
        # the published one first.
        chosen = min(
            ready,
            key=lambda item: (listed[item], not _publishes(pending, item)),
        )
        ordered.append(chosen)
        placed.add(chosen)
        del waiting_for[chosen]
    return tuple(ordered)


def _publishes(
    decisions: Sequence[DestinationDecision], destination: Destination
) -> bool:
    return any(
        decision.publishes
        for decision in decisions
        if decision.destination is destination
    )


# ===========================================================================
# Identity and storage
# ===========================================================================


def decision_id(unit: str, destination: Destination) -> str:
    """The ``dst`` ID of one unit's decision about one destination.

    Derived from both rather than counted: E-12 is written once (§2.5), so a
    second execution over the same unit must name the same decision — the
    workspace writes each path once (P1), and an ID that counted executions would
    turn a repeat into a second decision about the same destination.
    """

    return f"dst-{unit}-{destination.value}"


def destination_scope_key(unit: str, destination: Destination) -> str:
    """The scope key a destination's outcome is recorded against (§4.2).

    ``<unit_id>/<destination>``, which is the shape §4.2 gives as its example
    (``unit_…/linkedin/attempt_2``) and not the destination alone: AD-04 lets one
    run hold several units, the durable summary keys a scope's final state by
    ``(scope, scope_key)``, and two units' LinkedIn decisions under one key would
    leave one of them counted as the other's.
    """

    return f"{unit}/{destination.value}"


def decision_relative_path(unit: str, destination: Destination) -> str:
    """``units/<unit_id>/destinations/<destination>/decision.json`` (§2.2)."""

    _validate_path_component(unit, "unit_id")
    return (
        f"{UNITS_DIRECTORY}/{unit}/{DESTINATIONS_DIRECTORY}/"
        f"{destination.value}/{DECISION_FILE_NAME}"
    )


def write_destination_decision(
    workspace: RunWorkspace, decision: DestinationDecision
) -> EntityIndexEntry:
    """Write one decision into the run workspace, and index it.

    Through :class:`~src.run.run_workspace.RunWorkspace`, so create-once (P1) and
    §2.3 write ownership hold: ``destinations/*/decision.json`` belongs to S-07
    and to nothing else. The name carries no version because E-12 is written once
    (§2.5).
    """

    return workspace.write_entity(
        stage=STAGE,
        relative_path=decision_relative_path(decision.unit_id, decision.destination),
        entity_type=DECISION_ENTITY_TYPE,
        entity_id=decision.destination_decision_id,
        payload=decision.as_entity(),
    )


def write_destination_decisions(
    workspace: RunWorkspace, decided: DestinationDecisionSet
) -> tuple[EntityIndexEntry, ...]:
    """Write every decision of one unit, eligible and excluded alike.

    Both, because §1's Post column is a record of the whole set: an excluded
    destination whose decision was not written would be indistinguishable from a
    destination nobody decided about, and the exclusion's rule and tier are the
    evidence AD-02 exists to produce.
    """

    return tuple(
        write_destination_decision(workspace, decision)
        for decision in decided.decisions
    )


# ===========================================================================
# The stage
# ===========================================================================


def decide_destinations(
    *,
    unit: EditorialUnit,
    anchor: Anchor,
    contract: ContractDestinations,
    facts: UnitFacts,
    capability: Mapping[Destination, DestinationCapability] = AS_IS_CAPABILITY,
    rollout_scope: frozenset[Destination] = ROLLOUT_SCOPE,
    policies: Sequence[PlatformPolicy] = (),
    cadence: Sequence[CadenceRule] = (),
    portfolio: Sequence[DestinationFingerprint] = (),
) -> DestinationDecisionSet:
    """Decide every destination the contract declares, by rule.

    Returns a :class:`DestinationDecisionSet` in every case, including the one
    where nothing is eligible: that is a recorded ``SKIP`` of the unit and not an
    exception, for the reason S-00 through S-06 give — a caller that had to catch
    an error would have nothing to write into the trace. The stage's
    preconditions still raise.

    ``capability`` and ``rollout_scope`` default to this repository's AS-IS facts
    (:data:`AS_IS_CAPABILITY`, :data:`ROLLOUT_SCOPE`), so a caller that states
    neither gets today's behaviour rather than an optimistic one: Wix and LinkedIn
    publish, and the four destinations without a package, a preflight or a metrics
    collector are ``generate_only``.
    """

    if anchor.unit_id != unit.unit_id:
        raise DestinationError(
            f"anchor {anchor.anchor_id} is the anchor of {anchor.unit_id!r} and "
            f"reached {STAGE} for {unit.unit_id!r}; §1 Pre is this unit's anchor, "
            "and I-07 gives a unit exactly one"
        )
    if unit.status is not UnitStatus.ACTIVE:
        raise DestinationError(
            f"{unit.unit_id} is {unit.status.value} and reached {STAGE}; a unit "
            "that is not active has either not started or already ended"
        )
    _one_rule_per_destination(cadence)

    decided = tuple(
        _decide(
            unit=unit,
            row=row,
            facts=facts,
            capability=_capability_of(capability, row.destination),
            rollout_scope=rollout_scope,
            policies=policies,
            cadence=cadence,
            portfolio=portfolio,
        )
        for row in contract.rows
    )
    return DestinationDecisionSet(
        unit_id=unit.unit_id,
        decisions=_with_dependencies(decided, contract),
        undeclared=tuple(
            destination
            for destination in Destination
            if destination not in contract.destinations
        ),
        outcome=_unit_outcome(unit, decided),
    )


# ===========================================================================
# The rules, by tier (AD-02, map §5)
# ===========================================================================


def _decide(
    *,
    unit: EditorialUnit,
    row: ContractDestination,
    facts: UnitFacts,
    capability: DestinationCapability,
    rollout_scope: frozenset[Destination],
    policies: Sequence[PlatformPolicy],
    cadence: Sequence[CadenceRule],
    portfolio: Sequence[DestinationFingerprint],
) -> DestinationDecision:
    """One destination: excluded by the rule with the most authority, or
    eligible."""

    refusals = _refusals(
        row=row,
        facts=facts,
        policies=policies,
        cadence=cadence,
        portfolio=portfolio,
    )
    identity = decision_id(unit.unit_id, row.destination)
    if refusals:
        rule, reference, knowledge = refusals[0]
        return DestinationDecision(
            destination_decision_id=identity,
            unit_id=unit.unit_id,
            destination=row.destination,
            eligibility=Eligibility.EXCLUDED,
            rule_ref=reference,
            tier=_RULE_TIERS[rule],
            exclusion_rule=rule,
            knowledge=knowledge,
            outcome=OutcomeRecord(
                outcome=ArpOutcome.SKIP,
                state_code=_RULE_STATE_CODES[rule],
                scope=OutcomeScope.DESTINATION,
                scope_key=destination_scope_key(unit.unit_id, row.destination),
                reason=(
                    f"{rule.value} ({reference}, tier "
                    f"{_RULE_TIERS[rule].value}) excludes "
                    f"{row.destination.value} for this unit"
                ),
                knowledge=() if knowledge is None else (knowledge,),
            ),
        )

    mode, mode_rule = _mode(row, capability, rollout_scope)
    return DestinationDecision(
        destination_decision_id=identity,
        unit_id=unit.unit_id,
        destination=row.destination,
        eligibility=Eligibility.ELIGIBLE,
        rule_ref=row.rule_id,
        tier=KnowledgeTier.APPROVED_CLIENT_RULE,
        mode=mode,
        mode_rule=mode_rule,
        capability_gaps=(
            capability.missing
            if mode_rule
            in (ModeRule.NO_IDEMPOTENCY_AUTHORITY, ModeRule.NOT_CAPABLE)
            else ()
        ),
    )


def _refusals(
    *,
    row: ContractDestination,
    facts: UnitFacts,
    policies: Sequence[PlatformPolicy],
    cadence: Sequence[CadenceRule],
    portfolio: Sequence[DestinationFingerprint],
) -> tuple[tuple[ExclusionRule, str, Optional[KnowledgeRef]], ...]:
    """Every rule that refuses this destination, the strongest first (map §5).

    All of them are evaluated and then ordered by tier, rather than the first one
    found deciding: "in a conflict the higher tier wins", and a client reading an
    exclusion needs to know which rule would have to change — a contract row it
    could edit, or a platform rule it cannot.
    """

    found: list[tuple[ExclusionRule, str, Optional[KnowledgeRef]]] = []
    for policy in policies:
        if policy.destination is row.destination:
            found.append((
                ExclusionRule.HARD_PLATFORM_POLICY,
                policy.knowledge.record_id,
                policy.knowledge,
            ))
    refused = row.refuses(facts)
    if refused is not None:
        found.append((refused, row.rule_id, None))
    for rule in cadence:
        if rule.destination is row.destination and rule.defers(portfolio):
            found.append((ExclusionRule.CADENCE, rule.rule_id, None))
    return tuple(sorted(found, key=lambda item: _authority(item[0])))


def _authority(rule: ExclusionRule) -> int:
    """Where a rule's tier sits on the map §5 ladder: 0 is strongest.

    Every tier these rules use is on the ladder, so :func:`tier_rank` answers for
    all of them; a tier it could not place is refused rather than sorted to the
    end, because "somewhere at the bottom" is a position nobody chose.
    """

    rank = tier_rank(_RULE_TIERS[rule])
    if rank is None:
        raise DestinationError(
            f"tier {_RULE_TIERS[rule].value} ({rule.value}) is not on the map §5 "
            "ladder, so it cannot be compared with the other rules that refuse a "
            "destination"
        )
    return rank


def _mode(
    row: ContractDestination,
    capability: DestinationCapability,
    rollout_scope: frozenset[Destination],
) -> tuple[DestinationMode, ModeRule]:
    """AD-02 §3, in the order it states the three inputs.

    "A destination is ``publish`` when the client contract enables it, it is
    capable, and the rollout scope includes it. Otherwise it is
    ``generate_only``." Where more than one input withholds publication, the
    recorded rule is the first of the three, because that is the order in which
    they would have to be fixed: a contract that does not want to publish there
    makes the rest moot, and a destination without an idempotency authority may
    not publish however wide the rollout scope is (Step 3 §3.6 rule 7).
    """

    if not row.publishes:
        return DestinationMode.GENERATE_ONLY, ModeRule.CONTRACT_GENERATE_ONLY
    if not capability.idempotency_authority:
        return DestinationMode.GENERATE_ONLY, ModeRule.NO_IDEMPOTENCY_AUTHORITY
    if not capability.capable:
        return DestinationMode.GENERATE_ONLY, ModeRule.NOT_CAPABLE
    if row.destination not in rollout_scope:
        return DestinationMode.GENERATE_ONLY, ModeRule.OUTSIDE_ROLLOUT_SCOPE
    return DestinationMode.PUBLISH, ModeRule.PUBLISHES


def _with_dependencies(
    decided: Sequence[DestinationDecision], contract: ContractDestinations
) -> tuple[DestinationDecision, ...]:
    """Record each eligible destination's links, and drop the unreachable ones.

    A dependency on a destination this unit excluded is not recorded: §0.2 orders
    the destinations of the unit by their dependencies, and one on a destination
    that will never run is an order waiting for nothing. A dependency on an
    eligible ``generate_only`` destination **is** recorded — the order still
    holds, and whether the link is bound is S-14's question, which R-2 already
    answers with "the link is bound only if its target was published".
    """

    eligible = {
        decision.destination
        for decision in decided
        if decision.eligibility is Eligibility.ELIGIBLE
    }
    recorded: list[DestinationDecision] = []
    for decision in decided:
        row = contract.row(decision.destination)
        if decision.eligibility is not Eligibility.ELIGIBLE or row is None:
            recorded.append(decision)
            continue
        recorded.append(
            DestinationDecision(
                destination_decision_id=decision.destination_decision_id,
                unit_id=decision.unit_id,
                destination=decision.destination,
                eligibility=decision.eligibility,
                rule_ref=decision.rule_ref,
                tier=decision.tier,
                mode=decision.mode,
                mode_rule=decision.mode_rule,
                capability_gaps=decision.capability_gaps,
                publication_dependencies=tuple(
                    PublicationDependency(target=target)
                    for target in row.links_to
                    if target in eligible
                ),
                dropped_dependencies=tuple(
                    target for target in row.links_to if target not in eligible
                ),
            )
        )
    return tuple(recorded)


def _unit_outcome(
    unit: EditorialUnit, decided: Sequence[DestinationDecision]
) -> Optional[OutcomeRecord]:
    """§1's ARP column: "Zero eligible destinations → ``SKIP`` unit"."""

    if any(
        decision.eligibility is Eligibility.ELIGIBLE for decision in decided
    ):
        return None
    refused = ", ".join(
        f"{decision.destination.value} by {rule.value}"
        for decision in decided
        for rule in (decision.exclusion_rule,)
        if rule is not None
    )
    return OutcomeRecord(
        outcome=ArpOutcome.SKIP,
        state_code=StateCode.NO_ELIGIBLE_DESTINATION,
        scope=OutcomeScope.UNIT,
        scope_key=unit.unit_id,
        reason=f"every destination the contract declares is excluded: {refused}",
    )


def _capability_of(
    capability: Mapping[Destination, DestinationCapability],
    destination: Destination,
) -> DestinationCapability:
    """The capability row for one destination, or a refusal.

    An unstated destination is not an incapable one: AD-02 §3 makes capability
    five facts about the engine, and a missing row is nobody having stated them.
    Defaulting it either way would decide the mode on an assumption — and "assume
    capable" is the assumption that publishes.
    """

    try:
        stated = capability[destination]
    except KeyError:
        raise DestinationError(
            f"capability states nothing about {destination.value}, and the "
            "contract declares it; AD-02 §3 decides the mode from five facts "
            "about the engine, and a destination nobody stated them for has no "
            "mode a rule could give it"
        ) from None
    if stated.destination is not destination:
        raise DestinationError(
            f"the capability filed under {destination.value} describes "
            f"{stated.destination.value}; a row that answers for another "
            "destination answers for nothing"
        )
    return stated


def _one_rule_per_destination(cadence: Sequence[CadenceRule]) -> None:
    """One cadence rule per destination, or the deferral names no single rule."""

    declared = [rule.destination for rule in cadence]
    duplicated = sorted({
        item.value for item in declared if declared.count(item) > 1
    })
    if duplicated:
        raise DestinationError(
            "two cadence rules are declared for "
            + ", ".join(duplicated)
            + "; a deferral cites the rule that made it, and two rules over one "
            "destination make that citation a choice"
        )


def _refused(stated: Optional[str], listed: Sequence[str]) -> bool:
    """Does a refusal list cover what the unit states?

    Silence is not admission: a unit that states nothing for the fact the rule
    reads has not been shown to be outside the refused set, so the rule refuses.
    That is the same direction S-00 takes on the same question, and it is the one
    that publishes nothing the contract has not been shown to allow.
    """

    if stated is None or not stated.strip():
        return True
    normalized = _normalized(stated)
    return any(normalized == _normalized(value) for value in listed)


def _normalized(value: str) -> str:
    """One comparable spelling: whitespace collapsed, case folded."""

    return " ".join(value.split()).casefold()
