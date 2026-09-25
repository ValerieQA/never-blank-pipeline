"""S-06 · Anchor: one reading, the strength it is stated at, and what carries it.

The unit-scope stage that turns an admissible set into a single story. Step 2 §1
gives it three decisions and forbids it two: "choose the unit's one anchor
interpretation, the strength it will be stated at, and the leading-material set
(1–2 items). It must not choose openings or destinations."

The three decisions are not equal in who makes them. §1's Decider column splits
them: "``model`` chooses. ``code`` validates and computes the ambiguity flag" —
so this module is a narrow model call wrapped in the rules of §1's Post column,
and every one of those rules is arithmetic or a reference check:

1. **the anchor is admissible and in scope.** Candidates are the boundary's
   admissible set intersected with the unit's ``interpretation_scope``, read
   from the **newest** boundary version rather than from the one the unit was
   created against: a re-entry that refused a reading does not leave the unit's
   scope able to permit it (patch R2, F-4);
2. **``strength_used`` ≤ ceiling.** A minimum over one ladder (AD-10), which is
   why code takes it and never the model: E-11 allows a ``DEGRADE`` to lower the
   strength and nothing to raise it;
3. **the leading-material set supports the anchor.** One item by default, a
   second only if it supports the anchor too (AD-01). An item that does not is
   dropped — and an answer that named no supporting item at all is a citation
   failure rather than a finding about the material, because every admissible
   interpretation rests on at least one evidence claim, so a supporting item
   always exists to be named.

``ambiguity_touches_anchor`` is computed here and nowhere else. The boundary
counts its ambiguities and says so itself: "whether it touches the anchor is
decided at S-06, not here" (``knowledge/vocab/boundary_facts.md``).

The one route out, and where it ends
------------------------------------
§1's ARP column gives S-06 one backward route and one terminal state, and the
topology registry declares the route: S-06 → S-03, cause
``ambiguity_touches_anchor``, spending ``L_enrich``, ending in
``degrade_or_skip_unit``. Which of those two ends it reaches is decided on the
evidence and not by the counter, so this module states it: the anchor is weakened
one level if the ladder has a level below the one it was chosen at, and the unit
is skipped if it does not. That is map §6.2 read forwards — "enrichment → weaken
the anchor (`DEGRADE`) → if there is no provable anchor, `SKIP` the unit".

``L_anchor`` is **not** spent here. §0.3 counts it against "re-entry into S-06",
and the two routes that re-enter — S-04's after a boundary commit invalidated the
anchor, and S-09's when no destination held an admissible candidate — are spent
by the stage that detected the failure (for S-04, by
``interpretation_boundary.re_enter_boundary``). So a run whose ``L_anchor`` is
exhausted never arrives: its route returned the unit's ``SKIP`` instead of a
``REPLAN``. :func:`re_enter_anchor` therefore takes the arriving OutcomeRecord
and refuses one that is not that route — a re-entry that cannot show what
authorized it is not a re-entry, and spending the counter twice or not at all are
the two ways the termination argument in §5.3 fails.

**Production safety.** One model call, no external call, and nothing calls this
stage: the run harness still executes S-06 as the SL-1 pass-through, and wiring
the stages of SL-5 into it is a later slice. The shadow requirement is met by
there being nothing to switch off.

What is deliberately absent
---------------------------
**Anything about a destination.** §1 forbids it, and the openings the same
sentence forbids are S-08's. The request carries no destination, no client
position, no lens and no portfolio.

**``K-PRC-03`` and ``K-RDR-*`` as routed records.** §1 names them and the seed
register holds neither family (``docs/KNOWLEDGE_SEED_SET.md``). ``K-PRC-03``
("choose among whole variants") is honoured by the *shape* of the call rather
than by its text: the model receives whole candidate anchors and returns one
choice with a reason for every candidate it did not take. The knowledge that
does reach this stage is the run's strength ladder, whose own record names
``S-06 · E-11.strength_used``, and it arrives as an argument.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.2, §0.3,
§1 (S-04 boundary commit), §2 (S-06) and §5.3;
``docs/editorial/architecture/02_ARCHITECTURE_DECISIONS.md`` AD-01, AD-10;
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §4 (E-11);
``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §2.2, §2.3,
§2.5; ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §6.2.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.artifacts import _validate_path_component
from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.editorial_units import (
    UNITS_DIRECTORY,
    EditorialUnit,
    UnitStatus,
)
from src.editorial_core.evidence_core import EvidenceCore, Strength, StrengthLadder
from src.editorial_core.interpretation_boundary import (
    Interpretation,
    InterpretationBoundary,
)
from src.editorial_core.material_features import Asset, AssetClass
from src.editorial_core.signal_selection import CallBudget
from src.run.run_manifest import EntityIndexEntry
from src.run.run_workspace import RunWorkspace, versioned_name

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-06"

#: The entity it is the sole producer of (§1, Outputs).
ANCHOR_ENTITY_TYPE: Final[str] = "E-11"

#: Where an anchor lives inside the unit's directory (§2.2). ``anchor/*``
#: belongs to S-06 in the §2.3 ownership table and to nothing else.
ANCHOR_DIRECTORY: Final[str] = "anchor"

#: The counter the one route out of this stage spends (§0.3): "``L_enrich`` |
#: signal | 2 rounds". The limit in force is the ledger's, not this module's.
ENRICHMENT_COUNTER: Final[str] = "L_enrich"

#: The counter a **re-entry into** this stage spends (§0.3). Named here because
#: :func:`re_enter_anchor` checks the arriving route against it; it is never
#: spent here.
ANCHOR_COUNTER: Final[str] = "L_anchor"

#: The route out, as the topology registry declares it.
AMBIGUITY_CAUSE: Final[str] = "ambiguity_touches_anchor"

#: AD-01: "Size of the set: one by default. A second item is allowed only if
#: both items support the anchor."
LEADING_MATERIAL_MAX: Final[int] = 2


class AnchorError(RuntimeError):
    """S-06 was asked to decide something its contract cannot decide."""


# ===========================================================================
# E-11 · Anchor interpretation
# ===========================================================================


class LeadingMaterialKind(str, Enum):
    """What a leading item is: AD-01 allows "evidence claims or assets"."""

    EVIDENCE_CLAIM = "evidence_claim"
    ASSET = "asset"


@dataclass(frozen=True, slots=True)
class LeadingItem:
    """One member of the leading-material set, and which kind it is.

    The kind is recorded rather than left to be inferred from the ID's prefix:
    S-08 must foreground this item as "the primary evidentiary carrier" (AD-01),
    and a consumer that had to guess whether it is looking at a claim or an
    asset would resolve the reference in the wrong list.
    """

    ref: str
    kind: LeadingMaterialKind

    def __post_init__(self) -> None:
        if not self.ref.strip():
            raise AnchorError(
                "a leading item is named by the claim or asset it is; AD-01 makes"
                " it the text's primary evidentiary carrier, and an unnamed one "
                "carries nothing"
            )

    def as_entity(self) -> dict[str, str]:
        return {"ref": self.ref, "kind": self.kind.value}


@dataclass(frozen=True, slots=True)
class AnchorCandidate:
    """One interpretation the stage considered, and why it did or did not win.

    E-11's ``candidates`` field: "list of (interpretation ID, reason chosen or
    not)". Every candidate in scope gets a row, which is what §1's Trace column
    means by "candidates with reasons" — a reader who sees only the winner
    cannot tell a choice from the absence of one.
    """

    interpretation_id: str
    chosen: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.interpretation_id.strip():
            raise AnchorError("a candidate is named by its interpretation ID")
        if not self.reason.strip():
            raise AnchorError(
                f"{self.interpretation_id} is recorded without a reason; E-11 "
                "keeps the reason a candidate was chosen or was not, and a row "
                "with none records that it was considered and nothing else"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "interpretation_ref": self.interpretation_id,
            "chosen": self.chosen,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class Anchor:
    """``E-11``: the unit's one anchor interpretation (Step 1 §4).

    ``interpretation_ref`` is an exact ``(interpretation_id, version)`` pair and
    ``boundary_ref`` the E-09 version it was decided against, both by boundary
    commit rule 6: "the anchor is invalidated when its interpretation's current
    version in the newest E-09 is inadmissible. Invalidation is detected by code
    comparing the pairs" — which needs the pair, not the ID.
    """

    anchor_id: str
    #: ``+1`` per S-06 re-entry; the old version is kept (§2.5).
    version: int
    unit_id: str
    interpretation_ref: tuple[str, int]
    boundary_ref: tuple[str, int]
    strength_used: Strength
    leading_material: tuple[LeadingItem, ...]
    candidates: tuple[AnchorCandidate, ...]
    ambiguity_touches_anchor: bool
    outcome: OutcomeRecord

    def __post_init__(self) -> None:
        if not self.anchor_id.strip() or not self.unit_id.strip():
            raise AnchorError(
                "an anchor is identified by its anchor ID and the unit it is the"
                " anchor of (I-07: one anchor per unit)"
            )
        if self.version < 1:
            raise AnchorError(
                f"anchor version {self.version} is below 1; S-06 produces v1 and "
                "a re-entry the versions after it (§2.5)"
            )
        if not self.leading_material:
            raise AnchorError(
                f"{self.anchor_id} states no leading material; AD-01 gives the "
                "unit one or two items, and a strategy has to foreground one of "
                "them as its primary evidentiary carrier"
            )
        if len(self.leading_material) > LEADING_MATERIAL_MAX:
            raise AnchorError(
                f"{self.anchor_id} states {len(self.leading_material)} leading "
                f"items; AD-01 allows at most {LEADING_MATERIAL_MAX}, and a set "
                "wider than that is a second anchor wearing another name"
            )
        refs = [item.ref for item in self.leading_material]
        if len(set(refs)) != len(refs):
            raise AnchorError(
                f"{self.anchor_id} names one leading item twice: a set of two is "
                "two items, and the same one counted again is one"
            )
        chosen = [row for row in self.candidates if row.chosen]
        if len(chosen) != 1:
            raise AnchorError(
                f"{self.anchor_id} records {len(chosen)} chosen candidate(s); "
                "I-07 gives the unit exactly one anchor, and the candidate list "
                "is where that choice is shown to have been made"
            )
        if chosen[0].interpretation_id != self.interpretation_ref[0]:
            raise AnchorError(
                f"{self.anchor_id} anchors on {self.interpretation_ref[0]} and "
                f"records {chosen[0].interpretation_id} as the chosen candidate; "
                "two answers to which reading won is no answer"
            )
        identities = [row.interpretation_id for row in self.candidates]
        duplicated = sorted({key for key in identities if identities.count(key) > 1})
        if duplicated:
            raise AnchorError(
                "one interpretation is recorded twice among the candidates of "
                f"{self.anchor_id}: {', '.join(duplicated)}"
            )

    @property
    def interpretation_id(self) -> str:
        """Which reading this unit's texts are about."""

        return self.interpretation_ref[0]

    def as_entity(self) -> dict[str, Any]:
        """The E-11 body, written to ``units/*/anchor/anchor.v<n>.json`` (§2.2)."""

        return {
            "entity_type": ANCHOR_ENTITY_TYPE,
            "entity_id": self.anchor_id,
            "anchor_id": self.anchor_id,
            "version": self.version,
            "unit_id": self.unit_id,
            "interpretation_ref": {
                "interpretation_id": self.interpretation_ref[0],
                "version": self.interpretation_ref[1],
            },
            "boundary_ref": {
                "boundary_id": self.boundary_ref[0],
                "version": self.boundary_ref[1],
            },
            "strength_used": self.strength_used.as_entity(),
            "leading_material": [item.as_entity() for item in self.leading_material],
            "candidates": [row.as_entity() for row in self.candidates],
            "ambiguity_touches_anchor": self.ambiguity_touches_anchor,
            "outcome": self.outcome.model_dump(mode="json"),
        }


@dataclass(frozen=True, slots=True)
class AnchorDecision:
    """What one S-06 execution made of one unit.

    The anchor is absent whenever none was proved: the call could not be made or
    could not be read, the ambiguity route sent the run back to S-03, or the
    evidence left no reading this unit can be stated on. Unlike S-04 there is no
    case where a terminal outcome and a record of it coexist — an anchor nobody
    proved is not a weaker anchor, and E-11 has no field for one.
    """

    unit_id: str
    anchor: Optional[Anchor] = None
    outcomes: tuple[OutcomeRecord, ...] = ()
    #: Model calls this execution made, for the per-stage call record (§3.3).
    calls: int = 0


# ===========================================================================
# Identity and storage
# ===========================================================================


def anchor_id(unit: str) -> str:
    """The ``anc`` ID of the one anchor of one unit.

    Derived from the unit rather than counted, for the reason the unit ID is
    derived from the core: I-07 gives a unit exactly one anchor, and a re-entry
    produces a new **version** of it (§2.5) rather than a second record. An ID
    that counted re-entries would make the invalidation comparison in boundary
    commit rule 6 a search rather than a lookup.
    """

    return f"anc-{unit}"


def anchor_relative_path(unit: str, version: int) -> str:
    """``units/<unit_id>/anchor/anchor.v<n>.json`` (§2.2)."""

    _validate_path_component(unit, "unit_id")
    return (
        f"{UNITS_DIRECTORY}/{unit}/{ANCHOR_DIRECTORY}/"
        f"{versioned_name(ANCHOR_DIRECTORY, version)}"
    )


def write_anchor(workspace: RunWorkspace, anchor: Anchor) -> EntityIndexEntry:
    """Write one anchor version into the run workspace, and index it.

    Through :class:`~src.run.run_workspace.RunWorkspace`, so create-once (P1)
    and §2.3 write ownership hold: the path belongs to S-06 and to nothing else,
    and a second write of the same version is refused rather than replacing the
    first. The version is in the name (P2), because "the old version is kept"
    (§2.5) is only true if writing the new one cannot overwrite it.
    """

    return workspace.write_entity(
        stage=STAGE,
        relative_path=anchor_relative_path(anchor.unit_id, anchor.version),
        entity_type=ANCHOR_ENTITY_TYPE,
        entity_id=anchor.anchor_id,
        payload=anchor.as_entity(),
        version=anchor.version,
    )


# ===========================================================================
# The one call
# ===========================================================================


class AnchorTransport(Protocol):
    """The model call S-06 makes, as a narrow boundary."""

    def complete(self, *, instructions: str, request: str) -> str: ...


ANCHOR_INSTRUCTIONS = """\
You choose the anchor of one editorial unit. The anchor is the single reading
its texts are about: every destination of this unit will tell that one reading,
in its own way. You decide three things and nothing else — you do not choose how
a text opens, and you do not choose destinations.

You receive the Evidence Core (sources, observations, evidence claims with
verdicts, scopes, strengths and ceilings), the candidate readings the
Interpretation Boundary admits for this unit, the evidentiary assets, and a
strength ladder whose levels are numbered from 1 (weakest) upwards. Cite only
claim, asset and candidate identifiers the request contains.

Return exactly four things.

1. `chosen_index`: the 1-based position of the reading this unit is about. Choose
   a whole candidate, as it stands; you may not combine two or restate one.

2. `strength_level`: the ladder level the chosen reading may be *stated* at. It
   is what the evidence carries, never what would read best. A level above the
   candidate's own ceiling will be lowered to it.

3. `leading_material`: one or two identifiers — evidence claims or assets — that
   the texts of this unit will carry the chosen reading on. Each must support the
   chosen reading. One is the normal answer; return a second only if it supports
   the chosen reading too.

4. `candidates`: one entry per candidate in the request, all of them, each with
   its 1-based `index` and one sentence of `reason`: why you chose it, or why you
   did not.

Return ONLY one valid JSON object, no text outside it:

{"chosen_index": 1, "strength_level": 2, "leading_material": ["..."],
 "candidates": [{"index": 1, "reason": "..."}]}
"""


class _AnchorModel(BaseModel):
    """An answer is parsed strictly, or it is not an answer."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=True
    )


class CandidateAnswer(_AnchorModel):
    index: int = Field(ge=1)
    reason: str = Field(min_length=1)


class AnchorAnswer(_AnchorModel):
    chosen_index: int = Field(ge=1)
    strength_level: int = Field(ge=1)
    leading_material: tuple[str, ...] = ()
    candidates: tuple[CandidateAnswer, ...] = ()


# ===========================================================================
# The stage
# ===========================================================================


def choose_anchor(
    *,
    unit: EditorialUnit,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    transport: AnchorTransport,
    ladder: StrengthLadder,
    counters: AttemptCounterLedger,
    assets: Sequence[Asset] = (),
    budget: Optional[CallBudget] = None,
) -> AnchorDecision:
    """Choose the unit's anchor, its strength and what carries it.

    Returns an :class:`AnchorDecision` in every case the protocol has an outcome
    for. A call that could not be made or could not be read is a recorded
    outcome and not an exception, for the reason S-00 through S-04 give: a caller
    that had to catch an error would have nothing to write into the trace. The
    stage's preconditions still raise — §6.2 has no state for a stage run out of
    order.

    ``counters`` is required rather than optional. §1 gives S-06 exactly one
    route, the route is taken on a first execution and not only on a re-entry,
    and a stage that could reach the ambiguity condition without a ledger would
    have to either invent an unbounded loop or ignore the condition.
    """

    _precondition(unit=unit, boundary=boundary, core=core)
    candidates = _candidates(unit, boundary)
    if not candidates:
        return AnchorDecision(
            unit_id=unit.unit_id,
            outcomes=(
                _no_provable_anchor(
                    unit,
                    "the newest boundary version admits no reading this unit's "
                    "scope names, so there is nothing it could be about",
                ),
            ),
        )

    refusal = _spend(budget, unit.unit_id)
    if refusal is not None:
        return AnchorDecision(unit_id=unit.unit_id, outcomes=(refusal,))

    answer = _answer(transport, _request(core, candidates, assets, ladder))
    defect = None if answer is None else _defect(answer, candidates)
    if answer is None or defect is not None:
        return AnchorDecision(
            unit_id=unit.unit_id,
            outcomes=(
                _skip(
                    unit,
                    StateCode.ANCHOR_SELECTION_FAILED,
                    defect or "the anchor call produced no answer this stage may read",
                ),
            ),
            calls=1,
        )
    return _decided(
        unit=unit,
        boundary=boundary,
        core=core,
        assets=assets,
        ladder=ladder,
        counters=counters,
        answer=answer,
        candidates=candidates,
        version=1,
        calls=1,
    )


def re_enter_anchor(
    *,
    previous: Anchor,
    route: OutcomeRecord,
    unit: EditorialUnit,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    transport: AnchorTransport,
    ladder: StrengthLadder,
    counters: AttemptCounterLedger,
    assets: Sequence[Asset] = (),
    budget: Optional[CallBudget] = None,
) -> AnchorDecision:
    """Choose again without the anchor that failed, or weaken it (§1, ARP).

    ``route`` is the ``REPLAN`` that brought the run back here, and it is checked
    rather than trusted: ``L_anchor`` is spent by the stage that detected the
    failure — S-04 in
    :func:`~src.editorial_core.interpretation_boundary.re_enter_boundary`, S-09
    when no destination of the unit held an admissible candidate — so a re-entry
    without one either spent no counter, which is how a run loops forever, or
    spent it twice, which turns one allowed attempt into none.

    The previous anchor is excluded and the remaining candidates are chosen among
    (one call). When none remains, the failed anchor is weakened one level if the
    ladder has one below it and its reading is still admissible; when it does
    not, the unit is skipped. That is §1's "exclude the failed anchor and choose
    again, or weaken it", with the third case it leaves to map §6.2: "if there is
    no provable anchor, `SKIP` the unit".
    """

    _precondition(unit=unit, boundary=boundary, core=core)
    _authorized(route, unit)
    if previous.unit_id != unit.unit_id:
        raise AnchorError(
            f"anchor {previous.anchor_id} belongs to unit {previous.unit_id!r} "
            f"and is being re-entered for {unit.unit_id!r}; I-07 gives a unit one "
            "anchor, and an anchor of another unit is not a previous version of "
            "this one"
        )
    if boundary.version < previous.boundary_ref[1]:
        raise AnchorError(
            f"{previous.anchor_id} was chosen against boundary version "
            f"{previous.boundary_ref[1]} and is being re-entered against version "
            f"{boundary.version}; a re-entry follows a boundary commit, so the "
            "version it reads can only be the same or newer (patch R2, rule 6)"
        )

    version = previous.version + 1
    remaining = tuple(
        member
        for member in _candidates(unit, boundary)
        if member.interpretation_id != previous.interpretation_id
    )
    if not remaining:
        return _weakened(
            previous=previous,
            unit=unit,
            boundary=boundary,
            core=core,
            assets=assets,
            ladder=ladder,
            version=version,
        )

    refusal = _spend(budget, unit.unit_id)
    if refusal is not None:
        return AnchorDecision(unit_id=unit.unit_id, outcomes=(refusal,))

    answer = _answer(transport, _request(core, remaining, assets, ladder))
    defect = None if answer is None else _defect(answer, remaining)
    if answer is None or defect is not None:
        return AnchorDecision(
            unit_id=unit.unit_id,
            outcomes=(
                _skip(
                    unit,
                    StateCode.ANCHOR_SELECTION_FAILED,
                    defect
                    or "the re-entry anchor call produced no answer this stage "
                    "may read",
                ),
            ),
            calls=1,
        )
    return _decided(
        unit=unit,
        boundary=boundary,
        core=core,
        assets=assets,
        ladder=ladder,
        counters=counters,
        answer=answer,
        candidates=remaining,
        version=version,
        calls=1,
    )


# ===========================================================================
# The code rules (§1, Decider: validation and the ambiguity flag)
# ===========================================================================


def _precondition(
    *,
    unit: EditorialUnit,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
) -> None:
    """§1's Pre column, and the two refs that have to describe one thing.

    The boundary may be **newer** than the version the unit was created against
    — that is what a boundary commit produces — but never older: an anchor
    chosen against a superseded snapshot would be chosen against readings a
    later version has already refused, which is the one thing patch R2's
    versioned references exist to prevent.
    """

    if unit.status is not UnitStatus.ACTIVE:
        raise AnchorError(
            f"{unit.unit_id} is {unit.status.value} and reached {STAGE}; §1 Pre "
            "asks for an active unit, and a unit that is not active has either "
            "not started or already ended"
        )
    if not unit.interpretation_scope:
        raise AnchorError(
            f"{unit.unit_id} reached {STAGE} with an empty interpretation scope; "
            "§1 Pre asks for a scope that is not empty"
        )
    # Checked at the door rather than where the route needs it: a unit whose
    # enrichment allowance cannot be identified is a unit this stage cannot route
    # out of, and a guard that fired only when an ambiguity happened to touch the
    # anchor would let the same unit through on every other path.
    _enrichment_key(unit)
    if boundary.boundary_id != unit.boundary_ref[0]:
        raise AnchorError(
            f"{unit.unit_id} names boundary {unit.boundary_ref[0]!r} and reached "
            f"{STAGE} with {boundary.boundary_id!r}; an anchor is chosen inside "
            "its own unit's boundary"
        )
    if boundary.version < unit.boundary_ref[1]:
        raise AnchorError(
            f"{unit.unit_id} was created against boundary version "
            f"{unit.boundary_ref[1]} and reached {STAGE} with version "
            f"{boundary.version}; a re-entry only ever moves the version forward, "
            "and an older snapshot permits readings a newer one has refused "
            "(patch R2, F-4)"
        )
    if boundary.core_ref != (core.core_id, core.version):
        raise AnchorError(
            f"{unit.unit_id} reached {STAGE} with a boundary over "
            f"{boundary.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); the leading material is checked "
            "against the core, and two that describe different material cannot "
            "both be right"
        )


def _authorized(route: OutcomeRecord, unit: EditorialUnit) -> None:
    """Is this the route §0.3 counts as a re-entry into S-06?

    Four facts, each of which a wrong caller would get wrong differently: it is
    a ``REPLAN`` rather than a terminal outcome, it targets this stage, it spent
    ``L_anchor``, and it spent it against this unit. Nothing here spends
    anything; what it refuses is an unbounded loop dressed as a re-entry.
    """

    if route.outcome is not ArpOutcome.REPLAN:
        raise AnchorError(
            f"a re-entry into {STAGE} was authorized by a "
            f"{route.outcome.value}; only a REPLAN routes anywhere (§0.3), and a "
            "terminal outcome is where a unit ended rather than a way back in"
        )
    if route.route_target != STAGE:
        raise AnchorError(
            f"the route offered targets {route.route_target!r}, not {STAGE}; a "
            "re-entry is taken by the stage the route names"
        )
    if route.counter != ANCHOR_COUNTER:
        raise AnchorError(
            f"the route offered spent {route.counter!r}; §0.3 counts a re-entry "
            f"into {STAGE} against {ANCHOR_COUNTER}, and a route that spent "
            "another counter did not bound this one"
        )
    if route.scope_key not in (None, unit.unit_id):
        raise AnchorError(
            f"the route offered spent {ANCHOR_COUNTER} against "
            f"{route.scope_key!r} and is being taken for {unit.unit_id!r}; the "
            "counter is counted per unit, so another unit's attempt bounds "
            "nothing here"
        )


def _candidates(
    unit: EditorialUnit, boundary: InterpretationBoundary
) -> tuple[Interpretation, ...]:
    """The readings this unit may be about: admissible, and in its scope.

    Read from the boundary and filtered by the scope, in the scope's own order.
    The scope names readings and does not judge them (E-10): whether one is
    still admissible is the newest E-09 version's answer, so a reading the unit
    lists and this version refuses is not a candidate.
    """

    admissible = {
        member.interpretation_id: member for member in boundary.admissible
    }
    return tuple(
        admissible[identity]
        for identity in unit.interpretation_scope
        if identity in admissible
    )


def _defect(
    answer: AnchorAnswer, candidates: Sequence[Interpretation]
) -> Optional[str]:
    """Why this answer is not one, or ``None`` when it is one.

    Coverage is most of the check, for the reason S-04's probe is checked for it:
    E-11 keeps a reason for every candidate, and an answer that judged only its
    own choice leaves the others recorded as considered and nothing else — an
    unasked question passing as a verdict.
    """

    expected = set(range(1, len(candidates) + 1))
    judged = [row.index for row in answer.candidates]
    if sorted(judged) != sorted(expected) or len(judged) != len(set(judged)):
        return (
            f"the anchor call returned {len(judged)} reason(s) for "
            f"{len(candidates)} candidate(s); E-11 keeps a reason for each, and a "
            "candidate with none is one nobody said anything about"
        )
    if answer.chosen_index not in expected:
        return (
            f"the anchor call chose candidate {answer.chosen_index} of "
            f"{len(candidates)}; a choice outside the list it was given is not a "
            "reading this unit's boundary admits"
        )
    named = [ref for ref in dict.fromkeys(answer.leading_material) if ref.strip()]
    if not named:
        return (
            "the anchor call named no leading material; AD-01 makes it the "
            "text's primary evidentiary carrier, and the chosen reading rests on "
            "evidence claims the request listed"
        )
    return None


def _leading_material(
    chosen: Interpretation,
    named: Sequence[str],
    core: EvidenceCore,
    assets: Sequence[Asset],
) -> tuple[LeadingItem, ...]:
    """The named items that actually support the anchor, at most two (AD-01).

    "The leading-material set supports the anchor" (§1 Post) is a reference
    check, so it is code's: a claim supports the anchor when the chosen reading
    cites it, and an asset when at least one claim it rests on is cited. A
    positional asset is never a leading item however it is cited — it is a client
    position (E-06), and AD-01 makes the leading item the text's *evidentiary*
    carrier.

    Items that do not support it are dropped rather than refused one by one,
    which is AD-01's size rule read as code: the first supporting item is the
    set, and a second joins it only because it supports the anchor too.
    """

    supports = set(chosen.support_refs)
    usable = {claim.evidence_claim_id for claim in core.usable_claims}
    evidentiary = {
        asset.asset_id: asset
        for asset in assets
        if asset.asset_class is not AssetClass.POSITIONAL
    }
    found: list[LeadingItem] = []
    for ref in dict.fromkeys(named):
        if ref in supports and ref in usable:
            found.append(LeadingItem(ref=ref, kind=LeadingMaterialKind.EVIDENCE_CLAIM))
        elif ref in evidentiary and supports.intersection(evidentiary[ref].refs):
            found.append(LeadingItem(ref=ref, kind=LeadingMaterialKind.ASSET))
        if len(found) == LEADING_MATERIAL_MAX:
            break
    return tuple(found)


def _touches(boundary: InterpretationBoundary, chosen: Interpretation) -> bool:
    """Does an ambiguity of the boundary reach the chosen reading?

    Computed here because the boundary's own vocabulary says so: it counts its
    ambiguities and records which readings each affects, and "whether it touches
    the anchor is decided at S-06, not here".
    """

    return any(
        chosen.interpretation_id in ambiguity.interpretation_refs
        for ambiguity in boundary.ambiguities
    )


def _decided(
    *,
    unit: EditorialUnit,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    assets: Sequence[Asset],
    ladder: StrengthLadder,
    counters: AttemptCounterLedger,
    answer: AnchorAnswer,
    candidates: Sequence[Interpretation],
    version: int,
    calls: int,
) -> AnchorDecision:
    """Apply the code rules to a read answer, and take the route it earns."""

    chosen = candidates[answer.chosen_index - 1]
    leading = _leading_material(chosen, answer.leading_material, core, assets)
    if not leading:
        return AnchorDecision(
            unit_id=unit.unit_id,
            outcomes=(
                _skip(
                    unit,
                    StateCode.ANCHOR_SELECTION_FAILED,
                    "the anchor call named leading material that does not support "
                    f"the reading it chose ({chosen.interpretation_id}), so "
                    "nothing was left to carry it",
                ),
            ),
            calls=calls,
        )

    strength = _strength(answer.strength_level, chosen, ladder)
    rows = tuple(
        AnchorCandidate(
            interpretation_id=candidates[row.index - 1].interpretation_id,
            chosen=row.index == answer.chosen_index,
            reason=row.reason,
        )
        for row in sorted(answer.candidates, key=lambda row: row.index)
    )
    return _routed(
        unit=unit,
        boundary=boundary,
        ladder=ladder,
        counters=counters,
        chosen=chosen,
        strength=strength,
        leading=leading,
        candidates=rows,
        version=version,
        calls=calls,
    )


def _routed(
    *,
    unit: EditorialUnit,
    boundary: InterpretationBoundary,
    ladder: StrengthLadder,
    counters: AttemptCounterLedger,
    chosen: Interpretation,
    strength: Strength,
    leading: tuple[LeadingItem, ...],
    candidates: tuple[AnchorCandidate, ...],
    version: int,
    calls: int,
) -> AnchorDecision:
    """§1's ARP column: the ambiguity route first, the clean anchor otherwise."""

    touches = _touches(boundary, chosen)
    if not touches:
        resolved = _resolved(unit, chosen, strength, ladder)
        return AnchorDecision(
            unit_id=unit.unit_id,
            anchor=_anchor(
                unit=unit,
                boundary=boundary,
                chosen=chosen,
                strength=strength,
                leading=leading,
                candidates=candidates,
                touches=False,
                outcome=resolved,
                version=version,
            ),
            outcomes=(resolved,),
            calls=calls,
        )

    # "Enrichment → weaken the anchor (DEGRADE) → if there is no provable
    # anchor, SKIP the unit" (map §6.2). Which end the route has is decided on
    # the evidence, so it is stated before the ledger is asked: the counter can
    # say whether an attempt is left, and nothing else.
    weaker = _weaker(strength, ladder)
    route = counters.route(
        source=STAGE,
        cause=AMBIGUITY_CAUSE,
        # `L_enrich` is counted per **signal** (§0.3), because S-03 spends it per
        # signal and §5.3's termination argument rests on one counter, not on two
        # that happen to share a name. The record it produces concerns the unit,
        # which is what the route's terminal outcome is about, so the key it was
        # counted under is replaced on the way out — the same reconciliation
        # `re_enter_boundary` makes for `L_boundary`.
        scope_key=_enrichment_key(unit),
        state_code=StateCode.EVIDENCE_CONFLICT_IN_ANCHOR,
        reason=(
            f"an ambiguity of the boundary reaches {chosen.interpretation_id}, "
            "which is this unit's anchor"
        ),
        on_exhaustion=(
            ArpOutcome.DEGRADE if weaker is not None else ArpOutcome.SKIP
        ),
    ).model_copy(update={"scope_key": unit.unit_id})
    if route.outcome is ArpOutcome.REPLAN:
        # S-03 closes the ambiguity and the run comes back. No anchor is written
        # for an attempt that is being replaced: E-11 versions are kept (§2.5),
        # and keeping one nobody chose would leave the newest version of the
        # anchor recording a reading the run went back to reconsider.
        return AnchorDecision(unit_id=unit.unit_id, outcomes=(route,), calls=calls)
    if route.outcome is not ArpOutcome.DEGRADE or weaker is None:
        return AnchorDecision(unit_id=unit.unit_id, outcomes=(route,), calls=calls)
    return AnchorDecision(
        unit_id=unit.unit_id,
        anchor=_anchor(
            unit=unit,
            boundary=boundary,
            chosen=chosen,
            strength=weaker,
            leading=leading,
            candidates=candidates,
            touches=True,
            outcome=route,
            version=version,
        ),
        outcomes=(route,),
        calls=calls,
    )


def _weakened(
    *,
    previous: Anchor,
    unit: EditorialUnit,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    assets: Sequence[Asset],
    ladder: StrengthLadder,
    version: int,
) -> AnchorDecision:
    """A re-entry with nothing else to choose: weaken the failed anchor, or skip.

    No call is made. There is nothing to ask a model — the candidate list has one
    entry and the run has already been told it does not hold — so what is left is
    the arithmetic of §6.2: the same reading one level lower, if the ladder has a
    level below it, the reading is still admissible in the newest boundary
    version, and something in the core still carries it.
    """

    member = boundary.member(previous.interpretation_id)
    weaker = _weaker(previous.strength_used, ladder)
    if member is None or not member.admissible or weaker is None:
        return AnchorDecision(
            unit_id=unit.unit_id,
            outcomes=(
                _no_provable_anchor(
                    unit,
                    f"{previous.interpretation_id} is the unit's only remaining "
                    "reading and cannot carry it: it is no longer admissible, or "
                    "it is already stated at the ladder's weakest level",
                ),
            ),
        )
    leading = _leading_material(
        member, [item.ref for item in previous.leading_material], core, assets
    )
    if not leading:
        return AnchorDecision(
            unit_id=unit.unit_id,
            outcomes=(
                _no_provable_anchor(
                    unit,
                    f"{previous.interpretation_id} is the unit's only remaining "
                    "reading and nothing in the core still carries it",
                ),
            ),
        )
    # The state, and why it is this one: map §6.2 puts "weaken the anchor
    # (`DEGRADE`) → if there is no provable anchor, `SKIP` the unit" on the
    # anchor's own row, and that is the row a weakening belongs to whatever sent
    # the run back — what weakening answers is always "this anchor could not be
    # stated as it was". The route's own cause is in the OutcomeRecord the caller
    # spent to get here; this is the record of what S-06 then did.
    outcome = OutcomeRecord(
        outcome=ArpOutcome.DEGRADE,
        state_code=StateCode.EVIDENCE_CONFLICT_IN_ANCHOR,
        scope=OutcomeScope.UNIT,
        scope_key=unit.unit_id,
        reason=(
            f"the unit keeps {previous.interpretation_id} as its anchor at one "
            "level lower; no other admissible reading of its scope was left to "
            "choose"
        ),
    )
    return AnchorDecision(
        unit_id=unit.unit_id,
        anchor=_anchor(
            unit=unit,
            boundary=boundary,
            chosen=member,
            strength=weaker,
            leading=leading,
            candidates=(
                AnchorCandidate(
                    interpretation_id=previous.interpretation_id,
                    chosen=True,
                    reason=(
                        "kept and weakened: the re-entry left no other admissible "
                        "reading of this unit's scope"
                    ),
                ),
            ),
            # Recomputed against the boundary in front of it, never carried over
            # from the previous version: a commit can add or resolve an ambiguity,
            # and a flag copied forward would describe the snapshot that is gone.
            touches=_touches(boundary, member),
            outcome=outcome,
            version=version,
        ),
        outcomes=(outcome,),
    )


def _anchor(
    *,
    unit: EditorialUnit,
    boundary: InterpretationBoundary,
    chosen: Interpretation,
    strength: Strength,
    leading: tuple[LeadingItem, ...],
    candidates: tuple[AnchorCandidate, ...],
    touches: bool,
    outcome: OutcomeRecord,
    version: int,
) -> Anchor:
    return Anchor(
        anchor_id=anchor_id(unit.unit_id),
        version=version,
        unit_id=unit.unit_id,
        interpretation_ref=(chosen.interpretation_id, chosen.version),
        boundary_ref=(boundary.boundary_id, boundary.version),
        strength_used=strength,
        leading_material=leading,
        candidates=candidates,
        ambiguity_touches_anchor=touches,
        outcome=outcome,
    )


def _strength(
    asked: int, chosen: Interpretation, ladder: StrengthLadder
) -> Strength:
    """``strength_used`` ≤ ceiling, as a minimum over one ladder (AD-10).

    The ceiling is applied rather than the answer refused, because E-11 states
    the rule as an inequality and not as a verdict: "``strength_used`` ≤
    interpretation ceiling. ``DEGRADE`` may lower it, never raise it". A level
    the ladder does not have is capped at its top for the same reason, before the
    ceiling is applied — the ladder has no position above its own top, so there
    is none for a model to ask for.
    """

    within = min(max(asked, 1), len(ladder.levels))
    return ladder.lower_of(ladder.at(within), chosen.ceiling)


def _weaker(strength: Strength, ladder: StrengthLadder) -> Optional[Strength]:
    """One level down, or ``None`` at the ladder's weakest level.

    ``None`` and not the bottom again: "weaken the anchor" at the floor is not a
    weaker statement, it is the same statement, and treating it as a ``DEGRADE``
    would report a run as having proceeded more carefully when nothing changed.
    """

    if strength.level <= ladder.bottom.level:
        return None
    return ladder.at(strength.level - 1)


def _enrichment_key(unit: EditorialUnit) -> str:
    """The scope key ``L_enrich`` is counted under: the unit's signal (§0.3).

    A unit naming more than one signal is refused rather than keyed on the first.
    AD-04 makes the reference a list so that merging needs no migration, and says
    of the behaviour: "No component builds a core from several signals". A unit
    that names two would spend one signal's enrichment allowance for two of them,
    which is exactly the accounting §5.3's termination argument rests on.
    """

    if len(unit.signal_ids) != 1:
        raise AnchorError(
            f"{unit.unit_id} names {len(unit.signal_ids)} signals, and "
            f"{ENRICHMENT_COUNTER} is counted per signal (§0.3); AD-04 keeps the "
            "reference a list for a future capability that no component builds "
            "today, so a unit over several signals has no one enrichment "
            "allowance to spend"
        )
    return unit.signal_ids[0]


# ===========================================================================
# Requests, answers and outcomes
# ===========================================================================


def _request(
    core: EvidenceCore,
    candidates: Sequence[Interpretation],
    assets: Sequence[Asset],
    ladder: StrengthLadder,
) -> str:
    """What the one call sees.

    No destination, no client position, no lens and no portfolio: §1 forbids this
    stage the first and Step 1 forbids the boundary the rest, and the anchor is
    the boundary's reading chosen for the unit rather than for a surface. A
    request with nowhere to put one is how that is kept rather than remembered.
    """

    body = core.as_entity()
    return json.dumps({
        "core": {
            "core_id": core.core_id,
            "version": core.version,
            "sources": body["sources"],
            "observations": body["observations"],
            "claims": body["evidence_claims"],
            "contradictions": body["contradictions"],
        },
        "candidates": [
            {
                "index": position,
                "interpretation_id": member.interpretation_id,
                "statement": member.statement,
                "kind": member.kind.value,
                "support_refs": list(member.support_refs),
                "counter_refs": list(member.counter_refs),
                "audience_transfer": member.audience_transfer.value,
                "strength_level": member.strength.level,
                "ceiling_level": member.ceiling.level,
                "limits": [limit.as_entity() for limit in member.limits],
            }
            for position, member in enumerate(candidates, 1)
        ],
        "assets": [
            asset.as_entity()
            for asset in assets
            if asset.asset_class is not AssetClass.POSITIONAL
        ],
        "ladder": ladder.as_entity(),
    })


def _answer(transport: AnchorTransport, request: str) -> Optional[AnchorAnswer]:
    """One call, parsed, or ``None``. Never the provider's own text."""

    try:
        raw = transport.complete(
            instructions=ANCHOR_INSTRUCTIONS, request=request
        )
    except Exception:  # noqa: BLE001 — sanitized, never the provider's text
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return AnchorAnswer.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return None


def _resolved(
    unit: EditorialUnit,
    chosen: Interpretation,
    strength: Strength,
    ladder: StrengthLadder,
) -> OutcomeRecord:
    """The anchor was proved: the state S-06 exists to reach a verdict on.

    Recorded on the state map §6.2 gives the stage rather than on one of its own,
    which is how S-04 records a boundary that admitted something: the question
    "is there a reading this unit can rest on, and an asset to carry it" is the
    map's "no asset or admissible interpretation", answered.
    """

    return OutcomeRecord(
        outcome=ArpOutcome.RESOLVE,
        state_code=StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
        scope=OutcomeScope.UNIT,
        scope_key=unit.unit_id,
        reason=(
            f"{chosen.interpretation_id} is the unit's anchor, stated at "
            f"{ladder.wording(strength)!r}"
        ),
    )


def _no_provable_anchor(unit: EditorialUnit, detail: str) -> OutcomeRecord:
    """§1's "no provable anchor → ``SKIP`` unit"."""

    return _skip(unit, StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION, detail)


def _skip(
    unit: EditorialUnit, state_code: StateCode, reason: str
) -> OutcomeRecord:
    return OutcomeRecord(
        outcome=ArpOutcome.SKIP,
        state_code=state_code,
        scope=OutcomeScope.UNIT,
        scope_key=unit.unit_id,
        reason=reason,
    )


def _spend(budget: Optional[CallBudget], unit: str) -> Optional[OutcomeRecord]:
    if budget is None:
        return None
    return budget.spend(scope=OutcomeScope.UNIT, scope_key=unit)
