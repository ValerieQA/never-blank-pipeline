"""S-08 · Candidate strategies: 2–4 whole plans for one destination.

The destination-scope stage that turns one unit's anchor into whole,
internally consistent ways of telling it. Step 2 §1 gives it the decisions and
forbids it the choice: "produce 2–4 whole, internally consistent strategies for
one destination. It decides editorial job, angle, thesis, focal subject, reader
path, opening, reveal, concession and ending intention. **It must not choose
among them, and must not produce labels**."

What one call sees, and what it cannot
--------------------------------------
"1 per destination per attempt. Calls for different destinations are
independent and may run in parallel" (§1, Calls), and §1's **Not an input** row
is the other half of that sentence: "sibling destinations' strategies or texts
(I-06, AD-01: independence); label records (AD-07)". Both are kept here the way
S-06 keeps the destination out of the anchor call — :func:`propose_strategies`
takes one destination's E-12 decision and has nowhere to put a sibling's
strategy, a sibling's text or a label. A request with no field for one carries
none however the caller is written.

The AD-01 link, as code
-----------------------
AD-01 makes the unit's leading-material set the thread between destinations and
leaves everything else free: "each destination strategy must foreground and use
at least one member of the unit's leading-material set as its **primary
evidentiary carrier**. It does not have to appear in the first line or the
opening move. Opening and reveal mechanics stay independent per destination."

So the schema check is exactly two rules and deliberately not a third:

1. ``leading_material_ref`` is a member of this unit's anchor set, and
2. at least one move of the reader path references it — the carrier is used and
   not merely named;
3. and **nothing** is asked of the opening's relation to it. A candidate whose
   opening carries something else entirely passes, because the alternative
   AD-01 rejected ("leading material must be the opening") is the hidden
   template the destination-strategy research was written to remove.

What a candidate is checked against
-----------------------------------
§1's Post column, and every rule in it is a reference check or arithmetic, so
none of it is asked of the model: the anchor's reading is in the thesis, the
second interpretation is admissible and in the unit's scope, every move has at
least one reference and every reference resolves to something this run holds,
the concession's limitation is in the boundary, a delayed reveal names a move
the path has, a ``person_in_story`` focal subject rests on a documented case
(V-P01's own wording), a client position comes from the contract, every field
has a justification, and ``knowledge_used`` names records this stage was
actually routed — which is I-11 as code, because a strategy that could cite a
record nobody routed is the routing table I-11 forbids.

A candidate that fails one of them is **dropped with its reason** rather than
repaired: §1's ARP column says "zero candidates pass schema validation → counts
as 'no admissible strategy' for this destination (see S-09)", so a set that
survives with nothing in it is not this stage's outcome to record. It is a
candidate set with no members, and S-09 takes the route.

The one outcome of its own
--------------------------
``strategy_generation_failed``: the call could not be made, could not be read,
or proposed a number of strategies §1 does not ask for. Terminal for the reason
S-01's, S-02's, S-04's and S-06's machinery states are terminal — no judgment
about the material was made, so there is nothing to degrade to — and kept apart
from ``no_admissible_strategy`` so that a provider outage is never counted as
the engine having found nothing to say.

``L_strategy`` is **not** spent here. §0.3 counts it against the routes that
re-enter S-08, and every one of them is spent by the stage that detected the
failure — S-09 when no candidate was admissible, S-10, S-11, S-12, S-13 and the
S-04 boundary re-entry. :func:`propose_strategies` therefore takes the arriving
OutcomeRecord on any attempt after the first and refuses one that is not that
route: a re-entry that cannot show what authorized it is not a re-entry.

**Production safety.** One model call, no external call, and nothing calls this
stage: the run harness still executes S-08 as the SL-1 pass-through, and wiring
the stages of SL-5 into it is a later slice. The shadow requirement is met by
there being nothing to switch off.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.2, §0.3
and §3 (S-08); ``docs/editorial/architecture/02_ARCHITECTURE_DECISIONS.md``
AD-01, AD-07; ``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §4
(E-13) and §6 (I-06, I-08, I-10, I-11);
``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §2.2, §2.3,
§2.5; ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §7.1, §7.2, §7.4.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
from src.editorial_core.destinations import (
    DESTINATIONS_DIRECTORY,
    Destination,
    DestinationDecision,
    Eligibility,
    destination_scope_key,
)
from src.editorial_core.editorial_units import (
    UNITS_DIRECTORY,
    EditorialUnit,
    UnitStatus,
)
from src.editorial_core.evidence_core import EvidenceCore
from src.editorial_core.interpretation_boundary import (
    BoundaryError,
    InterpretationBoundary,
    Justification,
)
from src.editorial_core.material_features import (
    Asset,
    AssetClass,
    MaterialFeature,
    MaterialFeatures,
)
from src.editorial_core.signal_selection import CallBudget
from src.knowledge.loader import RoutedKnowledge
from src.run.run_manifest import EntityIndexEntry
from src.run.run_workspace import RunWorkspace

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-08"

#: The entity it is the sole producer of (§1, Outputs).
STRATEGY_ENTITY_TYPE: Final[str] = "E-13"

#: Where a candidate set lives inside the destination's directory (§2.2).
STRATEGIES_DIRECTORY: Final[str] = "strategies"

#: The counter a **re-entry into** this stage spends (§0.3). Named here because
#: :func:`propose_strategies` checks the arriving route against it; it is never
#: spent here.
STRATEGY_COUNTER: Final[str] = "L_strategy"

#: §1: "produce 2–4 whole, internally consistent strategies". An answer outside
#: that range is not the answer the call asked for.
CANDIDATES_MIN: Final[int] = 2
CANDIDATES_MAX: Final[int] = 4

#: E-13's ``reader_path``: "ordered list of Move, yes, ≥2".
READER_PATH_MIN: Final[int] = 2

#: The fields E-13 requires a justification for: "every field above has one"
#: (Step 1 §4). The two optional refs are added when the candidate states them,
#: because a field that is absent was not decided.
STRATEGY_FIELDS: Final[tuple[str, ...]] = (
    "editorial_job",
    "angle",
    "editorial_thesis",
    "focal_subject",
    "leading_material_ref",
    "reader_path",
    "opening",
    "reveal",
    "concession",
    "ending_intention",
)

OPTIONAL_STRATEGY_FIELDS: Final[tuple[str, ...]] = (
    "second_interpretation_ref",
    "client_position_ref",
)

#: The weakest tier a prohibition may act from, as a place on the map §5 ladder.
#: §3's Decider column gives S-09 "deterministic exclusions (V-P02 promise
#: versus boundary, **tier 0–2 conflicts**, the code part of V-P01)", so tier 2
#: is the floor: a weaker record orders candidates at the §7.3 tie-breakers
#: instead of removing them. Taken from the ladder rather than written down, so
#: that a tier inserted above tier 2 moves this with it.
PROHIBITION_FLOOR_TIER: Final[KnowledgeTier] = KnowledgeTier.APPROVED_CLIENT_RULE
_PROHIBITION_FLOOR: Final[int] = tier_rank(PROHIBITION_FLOOR_TIER) or 0


class StrategyError(RuntimeError):
    """S-08 was asked to decide something its contract cannot decide."""


# ===========================================================================
# The vocabularies (Step 1 §4, E-13)
# ===========================================================================


class FocalSubjectKind(str, Enum):
    """E-13's ``focal_subject`` kinds, exactly as Step 1 §4 lists them."""

    COMPANY = "company"
    OWNER_READER = "owner_reader"
    CLIENT = "client"
    #: "requires a documented case in the core" (Step 1 §4), which is V-P01's
    #: own rule read at the stage that decides the field.
    PERSON_IN_STORY = "person_in_story"


class RevealKind(str, Enum):
    """E-13's ``reveal``: "immediate / gradual / delayed + ``until_move``"."""

    IMMEDIATE = "immediate"
    GRADUAL = "gradual"
    DELAYED = "delayed"


# ===========================================================================
# The Client Contract, as S-08 reads it and S-09 applies it
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ClientPosition:
    """One approved position of the contract (E-06) a strategy may cite.

    ``client_position_ref`` is "only from the contract" (Step 1 §4), so the
    approved list is an input rather than something a candidate may assert:
    an asset the contract never approved is a position the client never took.
    """

    position_id: str
    text: str
    rule_id: str

    def __post_init__(self) -> None:
        if not self.position_id.strip() or not self.rule_id.strip():
            raise StrategyError(
                "a client position is named by its asset ID and by the contract "
                "rule that approved it; E-06 admits no position without one"
            )
        if not self.text.strip():
            raise StrategyError(
                f"the contract position {self.position_id} says nothing; a "
                "position a strategy may take is one the contract stated"
            )


@dataclass(frozen=True, slots=True)
class ContractRule:
    """One rule of the Client Contract: a prohibition or a preference.

    The structured fields are what S-09 can apply by ``code`` — a rule that
    names no focal subject and no reveal forbids nothing mechanically and
    reaches S-08 as text, which is the honest shape for a rule nobody has
    reduced to a field yet. ``knowledge`` is the record behind the rule where
    one exists: an exclusion has to cite it (I-11), and Step 4 §5.1 reads its
    effective status to decide whether the rule may act alone at all.
    """

    rule_id: str
    text: str
    tier: KnowledgeTier = KnowledgeTier.APPROVED_CLIENT_RULE
    focal_subjects: tuple[FocalSubjectKind, ...] = ()
    reveals: tuple[RevealKind, ...] = ()
    knowledge: Optional[KnowledgeRef] = None

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise StrategyError(
                "a contract rule is named by its rule ID; an exclusion cites the "
                "rule that made it, and a rule with no name cites nothing"
            )
        if not self.text.strip():
            raise StrategyError(
                f"the contract rule {self.rule_id} says nothing; the text is what "
                "reaches S-08, and a rule nobody stated cannot be followed"
            )
        if self.knowledge is not None and self.knowledge.tier is not self.tier:
            raise StrategyError(
                f"{self.rule_id} is recorded at tier {self.tier.value} and cites "
                f"{self.knowledge.record_id} at tier {self.knowledge.tier.value}; "
                "the tier belongs to whoever wrote the record and is not a second "
                "opinion about it"
            )

    def applies_to(
        self, kind: FocalSubjectKind, reveal: RevealKind
    ) -> bool:
        """Does this rule name what the candidate decided?

        Structural only. A rule with neither list is text guidance for the
        call and matches nothing: reducing a sentence to a field is the
        keeper's work (E-18), not a stage's.
        """

        return kind in self.focal_subjects or reveal in self.reveals


@dataclass(frozen=True, slots=True)
class StrategyContract:
    """The contract material §1 makes a required input of S-08.

    "Client Contract: positions, prohibitions, preferences (required)". The
    three are kept apart because they act at different places: positions bound
    what ``client_position_ref`` may name, prohibitions are deterministic
    exclusions at S-09 (map §5, tiers 0–2), and preferences are the fifth
    tie-breaker of §7.3 and never exclude anything.
    """

    positions: tuple[ClientPosition, ...] = ()
    prohibitions: tuple[ContractRule, ...] = ()
    preferences: tuple[ContractRule, ...] = ()

    def __post_init__(self) -> None:
        identities = [
            rule.rule_id for rule in (*self.prohibitions, *self.preferences)
        ]
        repeated = sorted({
            item for item in identities if identities.count(item) > 1
        })
        if repeated:
            raise StrategyError(
                "contract rule ID(s) declared twice: "
                + ", ".join(repeated)
                + "; an exclusion names the rule that decided it, and a name two "
                "rules answer to names neither"
            )
        stated = [position.position_id for position in self.positions]
        duplicated = sorted({
            item for item in stated if stated.count(item) > 1
        })
        if duplicated:
            raise StrategyError(
                "the contract approves "
                + ", ".join(duplicated)
                + " twice; one approval is the whole of what a position has"
            )
        for rule in self.prohibitions:
            rank = tier_rank(rule.tier)
            if rank is None or rank > _PROHIBITION_FLOOR:
                raise StrategyError(
                    f"the prohibition {rule.rule_id} sits at tier "
                    f"{rule.tier.value}; §3's Decider column gives S-09 the "
                    "deterministic exclusions of tiers 0–2, and a weaker record "
                    "orders candidates at the tie-breakers rather than removing "
                    "them"
                )

    def position(self, position_id: str) -> Optional[ClientPosition]:
        """The approved position with this ID, or ``None``."""

        for position in self.positions:
            if position.position_id == position_id:
                return position
        return None


# ===========================================================================
# E-13 · Editorial Strategy
# ===========================================================================


@dataclass(frozen=True, slots=True)
class Move:
    """One move of the reader path: "text, purpose, refs"  (Step 1 §4).

    "Each move has at least one reference" is the chain I-04 is made of, and it
    is checked here rather than at S-10: a move nobody can resolve is a move
    the plan cannot execute, whatever a later stage does with it.
    """

    text: str
    purpose: str
    refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.text.strip() or not self.purpose.strip():
            raise StrategyError(
                "a move states what it does and what it is for; E-13 keeps both, "
                "because a purpose is what makes a reader path checkable"
            )
        if not self.refs:
            raise StrategyError(
                f"the move {self.text[:40]!r} references nothing; Step 1 §4 gives "
                "every move at least one reference, and a move resting on nothing "
                "is where the chain I-04 asks for breaks"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "purpose": self.purpose,
            "refs": list(self.refs),
        }


@dataclass(frozen=True, slots=True)
class Opening:
    """E-13's ``opening``: "what comes first + refs + ``held_back``".

    ``held_back`` is required because the field is a *mechanic* and not a
    summary: AD-01 keeps the opening independent of the leading material, and
    what makes that independence worth anything is that the opening states
    which variable it withholds.
    """

    text: str
    held_back: str
    refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise StrategyError("an opening states what comes first")
        if not self.held_back.strip():
            raise StrategyError(
                "the opening records no held-back variable; Step 1 §4 makes it "
                "part of the field, and an opening that withholds nothing has "
                "decided nothing about the reveal"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "held_back": self.held_back,
            "refs": list(self.refs),
        }


@dataclass(frozen=True, slots=True)
class Reveal:
    """E-13's ``reveal``: "``delayed`` requires ``until_move``" (Step 1 §4)."""

    kind: RevealKind
    until_move: Optional[int] = None

    def __post_init__(self) -> None:
        if (self.kind is RevealKind.DELAYED) != (self.until_move is not None):
            raise StrategyError(
                f"a {self.kind.value} reveal is recorded with until_move="
                f"{self.until_move!r}; Step 1 §4 requires the move index for a "
                "delayed reveal and admits one for nothing else"
            )
        if self.until_move is not None and self.until_move < 1:
            raise StrategyError(
                f"the reveal is delayed until move {self.until_move}; the reader "
                "path is numbered from 1"
            )

    def as_entity(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "until_move": self.until_move}


@dataclass(frozen=True, slots=True)
class Concession:
    """E-13's ``concession``: "present: bool; limitation ref; move index"."""

    present: bool
    limitation_ref: Optional[str] = None
    move_index: Optional[int] = None

    def __post_init__(self) -> None:
        stated = self.limitation_ref is not None and self.move_index is not None
        if self.present != stated:
            raise StrategyError(
                f"a concession recorded as present={self.present} states "
                f"limitation {self.limitation_ref!r} at move {self.move_index!r}; "
                "Step 1 §4 asks a present concession for both and an absent one "
                "for neither"
            )
        if self.move_index is not None and self.move_index < 1:
            raise StrategyError(
                f"the concession sits at move {self.move_index}; the reader path "
                "is numbered from 1"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "limitation_ref": self.limitation_ref,
            "move_index": self.move_index,
        }


@dataclass(frozen=True, slots=True)
class Thesis:
    """E-13's ``editorial_thesis``: "text + interpretation refs" (Step 1 §4).

    "Its ceiling is the minimum over the referenced interpretations", which is
    why the references are part of the field and not a note beside it.
    """

    text: str
    interpretation_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise StrategyError("a thesis states one sentence (map §7.1)")
        if not self.interpretation_refs:
            raise StrategyError(
                "the thesis references no interpretation; I-04 makes the chain "
                "thesis → interpretations → evidence claims → observations, and "
                "a thesis resting on no reading is where it starts to break"
            )


@dataclass(frozen=True, slots=True)
class FocalSubject:
    """E-13's ``focal_subject``: "kind + text + refs" (Step 1 §4)."""

    kind: FocalSubjectKind
    text: str
    refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise StrategyError("a focal subject names who the entry is about")


@dataclass(frozen=True, slots=True)
class FieldJustification:
    """One entry of E-13's ``justifications`` map: a field, and why.

    A tuple of these rather than a mapping, for the reason every record in this
    package is a tuple of records: E-13 is immutable, and a frozen entity whose
    fields include a live mapping is immutable only by convention.
    """

    field_name: str
    justification: Justification

    def __post_init__(self) -> None:
        if not self.field_name.strip():
            raise StrategyError("a justification names the field it justifies")

    def as_entity(self) -> dict[str, Any]:
        return {
            "field": self.field_name,
            **self.justification.as_entity(),
        }


@dataclass(frozen=True, slots=True)
class EditorialStrategy:
    """``E-13``: one whole strategy for one destination of one unit (Step 1 §4).

    **There is no role field and no label field** (fix F-1, AD-07). Whether a
    candidate was chosen or excluded is recorded only in StrategySelection, and
    a label is written after the run by a separate job. Neither is absent by
    convention here: there is nowhere to put one, which is what makes "E-13 is
    immutable and carries no role" checkable rather than promised.
    """

    strategy_id: str
    unit_id: str
    destination: Destination
    candidate_set_id: str
    anchor_ref: str
    #: The E-09 version this strategy was built against (patch R2). An exact
    #: ``(boundary_id, version)`` pair, because invalidation after a commit is
    #: a code comparison of the pair and not of the ID.
    boundary_ref: tuple[str, int]
    editorial_job: str
    angle: str
    editorial_thesis: Thesis
    focal_subject: FocalSubject
    leading_material_ref: str
    reader_path: tuple[Move, ...]
    opening: Opening
    reveal: Reveal
    concession: Concession
    ending_intention: str
    justifications: tuple[FieldJustification, ...]
    knowledge_used: tuple[KnowledgeRef, ...] = ()
    second_interpretation_ref: Optional[str] = None
    client_position_ref: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.unit_id.strip():
            raise StrategyError(
                "a strategy is identified by its own ID and the unit it is a "
                "strategy for"
            )
        if not self.candidate_set_id.strip() or not self.anchor_ref.strip():
            raise StrategyError(
                f"{self.strategy_id} names no candidate set or no anchor; the set "
                "groups the candidates of one call and the anchor is what I-07 "
                "requires the strategy to match"
            )
        if not self.editorial_job.strip() or not self.angle.strip():
            raise StrategyError(
                f"{self.strategy_id} states no editorial job or no angle; both "
                "are open descriptions (I-10) and neither is optional"
            )
        if not self.ending_intention.strip():
            raise StrategyError(
                f"{self.strategy_id} states no ending intention; map §7.1 records "
                "it after the opening, and a strategy that decided no ending has "
                "left the last move to the Writer (I-08)"
            )
        if len(self.reader_path) < READER_PATH_MIN:
            raise StrategyError(
                f"{self.strategy_id} has a reader path of "
                f"{len(self.reader_path)} move(s); Step 1 §4 asks for at least "
                f"{READER_PATH_MIN}, because one move is a statement and not a "
                "path"
            )
        self._indices_are_in_the_path()
        self._every_field_is_justified()

    def _indices_are_in_the_path(self) -> None:
        length = len(self.reader_path)
        if self.reveal.until_move is not None and self.reveal.until_move > length:
            raise StrategyError(
                f"{self.strategy_id} delays its reveal until move "
                f"{self.reveal.until_move} of a path with {length}; a reveal that "
                "never arrives is not a delayed reveal"
            )
        if self.concession.move_index is not None and (
            self.concession.move_index > length
        ):
            raise StrategyError(
                f"{self.strategy_id} places its concession at move "
                f"{self.concession.move_index} of a path with {length}; a "
                "concession outside the path is not placed"
            )

    def _every_field_is_justified(self) -> None:
        optional: Mapping[str, Optional[str]] = {
            "second_interpretation_ref": self.second_interpretation_ref,
            "client_position_ref": self.client_position_ref,
        }
        expected = set(STRATEGY_FIELDS) | {
            name for name in OPTIONAL_STRATEGY_FIELDS if optional[name] is not None
        }
        justified = [entry.field_name for entry in self.justifications]
        repeated = sorted({
            name for name in justified if justified.count(name) > 1
        })
        if repeated:
            raise StrategyError(
                f"{self.strategy_id} justifies "
                + ", ".join(repeated)
                + " twice; two answers to why a field was decided are no answer"
            )
        missing = sorted(expected - set(justified))
        if missing:
            raise StrategyError(
                f"{self.strategy_id} justifies nothing for "
                + ", ".join(missing)
                + "; Step 1 §4 gives every field of E-13 a justification, and a "
                "field with none was not decided but merely written down"
            )
        unexpected = sorted(set(justified) - expected)
        if unexpected:
            raise StrategyError(
                f"{self.strategy_id} justifies "
                + ", ".join(unexpected)
                + ", which E-13 has no such field for, or which this candidate "
                "did not state"
            )

    @property
    def interpretation_refs(self) -> tuple[str, ...]:
        """Every reading this strategy rests on: the thesis's, and the second."""

        named = list(self.editorial_thesis.interpretation_refs)
        if self.second_interpretation_ref is not None:
            named.append(self.second_interpretation_ref)
        return tuple(dict.fromkeys(named))

    @property
    def carries_leading_material(self) -> bool:
        """Does a move of the reader path reference the primary carrier (AD-01)?

        The moves and nothing else. The opening is deliberately not consulted:
        AD-01 rejected "leading material must be the opening" as a hidden
        template, and a property that also accepted an opening reference would
        let a candidate satisfy the carrier rule without the path ever using it.
        """

        return any(
            self.leading_material_ref in move.refs for move in self.reader_path
        )

    def justification(self, field_name: str) -> Optional[Justification]:
        """Why one field was decided as it was, or ``None`` if it has no such
        field."""

        for entry in self.justifications:
            if entry.field_name == field_name:
                return entry.justification
        return None

    def as_entity(self) -> dict[str, Any]:
        """The E-13 body, written to ``strategies/<set>/<str_id>.json`` (§2.2)."""

        boundary_id, boundary_version = self.boundary_ref
        return {
            "entity_type": STRATEGY_ENTITY_TYPE,
            "entity_id": self.strategy_id,
            "strategy_id": self.strategy_id,
            "unit_id": self.unit_id,
            "destination": self.destination.value,
            "candidate_set_id": self.candidate_set_id,
            "anchor_ref": self.anchor_ref,
            "boundary_ref": {
                "boundary_id": boundary_id,
                "version": boundary_version,
            },
            "second_interpretation_ref": self.second_interpretation_ref,
            "editorial_job": self.editorial_job,
            "angle": self.angle,
            "editorial_thesis": {
                "text": self.editorial_thesis.text,
                "interpretation_refs": list(
                    self.editorial_thesis.interpretation_refs
                ),
            },
            "focal_subject": {
                "kind": self.focal_subject.kind.value,
                "text": self.focal_subject.text,
                "refs": list(self.focal_subject.refs),
            },
            "leading_material_ref": self.leading_material_ref,
            "reader_path": [move.as_entity() for move in self.reader_path],
            "opening": self.opening.as_entity(),
            "reveal": self.reveal.as_entity(),
            "concession": self.concession.as_entity(),
            "ending_intention": self.ending_intention,
            "client_position_ref": self.client_position_ref,
            "justifications": [
                entry.as_entity() for entry in self.justifications
            ],
            "knowledge_used": [
                ref.model_dump(mode="json") for ref in self.knowledge_used
            ],
        }


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    """One proposal that did not meet the E-13 schema, and why (§3, Trace)."""

    index: int
    reason: str

    def __post_init__(self) -> None:
        if self.index < 1:
            raise StrategyError("a proposal is numbered from 1 in the answer")
        if not self.reason.strip():
            raise StrategyError(
                "a rejected proposal records why it was rejected; §3's Trace "
                "column asks for the schema validation failures, and a rejection "
                "with no reason is a candidate that merely disappeared"
            )

    def as_entity(self) -> dict[str, Any]:
        return {"index": self.index, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class CandidateSet:
    """Every candidate of one S-08 call, grouped by ``candidate_set_id``.

    A set may hold **no** candidate. §1's ARP column makes that the ordinary
    shape of a failed attempt rather than an error — "zero candidates pass
    schema validation → counts as 'no admissible strategy' for this destination
    (see S-09)" — and the proposals that were refused stay in ``rejected`` so
    that the reason is in the trace rather than only in S-09's route.
    """

    unit_id: str
    destination: Destination
    candidate_set_id: str
    attempt: int
    candidates: tuple[EditorialStrategy, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()
    #: The route that sent this destination back, when one did (§3, Trace).
    re_entry_cause: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.unit_id.strip() or not self.candidate_set_id.strip():
            raise StrategyError(
                "a candidate set is identified by its own ID and the unit it "
                "belongs to"
            )
        if self.attempt < 1:
            raise StrategyError(
                f"the candidate set records attempt {self.attempt}; the first "
                "execution of S-08 is attempt 1"
            )
        if len(self.candidates) > CANDIDATES_MAX:
            raise StrategyError(
                f"{self.candidate_set_id} holds {len(self.candidates)} "
                f"candidates; §1 asks for {CANDIDATES_MIN}–{CANDIDATES_MAX}, and "
                "a wider set is a stage choosing how much to plan"
            )
        identities = [item.strategy_id for item in self.candidates]
        repeated = sorted({
            item for item in identities if identities.count(item) > 1
        })
        if repeated:
            raise StrategyError(
                f"{self.candidate_set_id} holds "
                + ", ".join(repeated)
                + " twice; one candidate counted again is one candidate"
            )
        for item in self.candidates:
            if (
                item.candidate_set_id != self.candidate_set_id
                or item.unit_id != self.unit_id
                or item.destination is not self.destination
            ):
                raise StrategyError(
                    f"{item.strategy_id} belongs to "
                    f"{item.unit_id}/{item.destination.value} in set "
                    f"{item.candidate_set_id} and is being grouped into "
                    f"{self.unit_id}/{self.destination.value} in "
                    f"{self.candidate_set_id}; a candidate set is one call's "
                    "answer for one destination"
                )

    @property
    def scope_key(self) -> str:
        """The destination scope key this set was produced under (§4.2)."""

        return destination_scope_key(self.unit_id, self.destination)

    def candidate(self, strategy_id: str) -> Optional[EditorialStrategy]:
        """The candidate with this ID, or ``None``."""

        for item in self.candidates:
            if item.strategy_id == strategy_id:
                return item
        return None


@dataclass(frozen=True, slots=True)
class StrategyProposal:
    """What one S-08 execution made of one destination.

    The candidate set is absent only when the call produced nothing this stage
    may read: a set with no members is a real answer and S-09's to route, while
    no set at all is the machinery state this stage records itself.
    """

    unit_id: str
    destination: Destination
    candidate_set: Optional[CandidateSet] = None
    outcomes: tuple[OutcomeRecord, ...] = ()
    #: Model calls this execution made, for the per-stage call record (§3.3).
    calls: int = 0


# ===========================================================================
# Identity and storage
# ===========================================================================


def candidate_set_id(unit: str, destination: Destination, attempt: int) -> str:
    """The ID that groups the candidates of one S-08 call (§2.5).

    Derived from the destination and the attempt rather than counted: "a new
    S-08 attempt is a new ``candidate_set_id``, not a new version", and a set
    whose name did not carry the attempt would collide with the set the attempt
    is replacing — which the workspace refuses (P1) rather than overwrites.
    """

    if attempt < 1:
        raise StrategyError(
            f"a candidate set is named for attempt {attempt}; the first execution "
            "of S-08 is attempt 1"
        )
    return f"cs-{unit}-{destination.value}-a{attempt}"


def strategy_id(set_id: str, index: int) -> str:
    """The ``str`` ID of one candidate of one set."""

    if index < 1:
        raise StrategyError(
            f"a candidate is numbered from 1 in its set; got {index}"
        )
    return f"str-{set_id}-{index}"


def strategies_relative_path(
    unit: str, destination: Destination, set_id: str
) -> str:
    """``units/<unit>/destinations/<dst>/strategies/<candidate_set_id>`` (§2.2)."""

    _validate_path_component(unit, "unit_id")
    _validate_path_component(set_id, "candidate_set_id")
    return (
        f"{UNITS_DIRECTORY}/{unit}/{DESTINATIONS_DIRECTORY}/{destination.value}/"
        f"{STRATEGIES_DIRECTORY}/{set_id}"
    )


def strategy_relative_path(
    unit: str, destination: Destination, set_id: str, identity: str
) -> str:
    """``strategies/<candidate_set_id>/<str_id>.json`` (§2.2)."""

    _validate_path_component(identity, "strategy_id")
    return (
        f"{strategies_relative_path(unit, destination, set_id)}/{identity}.json"
    )


def write_strategy(
    workspace: RunWorkspace, strategy: EditorialStrategy
) -> EntityIndexEntry:
    """Write one candidate into the run workspace, and index it.

    Through :class:`~src.run.run_workspace.RunWorkspace`, so create-once (P1)
    and §2.3 write ownership hold: ``strategies/*/<str_id>.json`` belongs to
    S-08 and to nothing else. The name carries no version because E-13 is
    written once (§2.5) — a new attempt is a new set, not a new version.
    """

    return workspace.write_entity(
        stage=STAGE,
        relative_path=strategy_relative_path(
            strategy.unit_id,
            strategy.destination,
            strategy.candidate_set_id,
            strategy.strategy_id,
        ),
        entity_type=STRATEGY_ENTITY_TYPE,
        entity_id=strategy.strategy_id,
        payload=strategy.as_entity(),
    )


def write_candidate_set(
    workspace: RunWorkspace, candidate_set: CandidateSet
) -> tuple[EntityIndexEntry, ...]:
    """Write every candidate of one set. A set with none writes nothing."""

    return tuple(
        write_strategy(workspace, candidate)
        for candidate in candidate_set.candidates
    )


# ===========================================================================
# The one call
# ===========================================================================


class StrategyTransport(Protocol):
    """The model call S-08 makes, as a narrow boundary."""

    def complete(self, *, instructions: str, request: str) -> str: ...


STRATEGY_INSTRUCTIONS = """\
You plan whole editorial strategies for ONE destination of one editorial unit.
Produce between 2 and 4 of them. Each must be whole and internally consistent:
you decide every field together, never one field at a time, and you do not
choose between the strategies you produce.

You receive the unit's anchor — the single reading every destination of this
unit tells — its leading-material set, the readings the Interpretation Boundary
admits, the Evidence Core, the material features, the evidentiary assets, this
destination's decision, and the client's positions, prohibitions and
preferences. Cite only identifiers the request contains.

Two rules bind every strategy:

- the `leading_material_ref` must be one of the unit's leading-material
  identifiers, and at least one move of the reader path must reference it: it
  is the strategy's primary evidentiary carrier;
- the opening is decided independently. It does NOT have to use the leading
  material and does NOT have to come first in the evidence order. Strategies
  for different destinations are expected to open differently.

Return for each strategy: `editorial_job` (open description), `angle` (the
reader's question), `thesis` with `thesis_interpretation_refs` (the readings it
rests on; the anchor's reading must be among them), `focal_subject_kind`
(company, owner_reader, client or person_in_story), `focal_subject` with
`focal_subject_refs`, `leading_material_ref`, `reader_path` (at least two
moves, each with `text`, `purpose` and at least one reference),
`opening` (`text`, `held_back`, `refs`), `reveal` (immediate, gradual or
delayed) with `until_move` for a delayed reveal, `concession`
(`present`, and when present `limitation_ref` and `move_index`),
`ending_intention` decided after the opening, optionally
`second_interpretation_ref` and `client_position_ref`, one `justifications`
entry per field you decided, and `knowledge_used` naming the records that
shaped it.

Do not produce a label, a category or a name for the type of the entry.

Return ONLY one valid JSON object, no text outside it:

{"candidates": [{"editorial_job": "...", "angle": "...", "thesis": "...",
 "thesis_interpretation_refs": ["..."], "focal_subject_kind": "company",
 "focal_subject": "...", "focal_subject_refs": ["..."],
 "leading_material_ref": "...", "reader_path": [{"text": "...",
 "purpose": "...", "refs": ["..."]}], "opening": {"text": "...",
 "held_back": "...", "refs": ["..."]}, "reveal": "immediate",
 "until_move": null, "concession": {"present": false},
 "ending_intention": "...", "second_interpretation_ref": null,
 "client_position_ref": null, "justifications": [{"field_name": "angle",
 "text": "...", "refs": ["..."]}], "knowledge_used": ["..."]}]}
"""


class _StrategyModel(BaseModel):
    """An answer is parsed strictly, or it is not an answer."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=True
    )


class MoveAnswer(_StrategyModel):
    text: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    refs: tuple[str, ...] = ()


class OpeningAnswer(_StrategyModel):
    text: str = Field(min_length=1)
    held_back: str = Field(min_length=1)
    refs: tuple[str, ...] = ()


class ConcessionAnswer(_StrategyModel):
    present: bool
    limitation_ref: Optional[str] = None
    move_index: Optional[int] = None


class JustificationAnswer(_StrategyModel):
    field_name: str = Field(min_length=1)
    text: str = Field(min_length=1)
    refs: tuple[str, ...] = ()


class StrategyAnswer(_StrategyModel):
    editorial_job: str = Field(min_length=1)
    angle: str = Field(min_length=1)
    thesis: str = Field(min_length=1)
    thesis_interpretation_refs: tuple[str, ...] = ()
    focal_subject_kind: FocalSubjectKind
    focal_subject: str = Field(min_length=1)
    focal_subject_refs: tuple[str, ...] = ()
    leading_material_ref: str = Field(min_length=1)
    reader_path: tuple[MoveAnswer, ...] = ()
    opening: OpeningAnswer
    reveal: RevealKind
    until_move: Optional[int] = None
    concession: ConcessionAnswer
    ending_intention: str = Field(min_length=1)
    second_interpretation_ref: Optional[str] = None
    client_position_ref: Optional[str] = None
    justifications: tuple[JustificationAnswer, ...] = ()
    knowledge_used: tuple[str, ...] = ()


class CandidatesAnswer(_StrategyModel):
    candidates: tuple[StrategyAnswer, ...] = ()


# ===========================================================================
# The stage
# ===========================================================================


def propose_strategies(
    *,
    unit: EditorialUnit,
    anchor: Anchor,
    decision: DestinationDecision,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    features: MaterialFeatures,
    contract: StrategyContract,
    transport: StrategyTransport,
    assets: Sequence[Asset] = (),
    knowledge: Sequence[RoutedKnowledge] = (),
    attempt: int = 1,
    re_entry: Optional[OutcomeRecord] = None,
    budget: Optional[CallBudget] = None,
) -> StrategyProposal:
    """Produce this destination's candidate strategies: one call, one set.

    Returns a :class:`StrategyProposal` in every case the protocol has an
    outcome for. A call that could not be made or could not be read is a
    recorded outcome and not an exception, for the reason S-00 through S-07
    give: a caller that had to catch an error would have nothing to write into
    the trace. The stage's preconditions still raise — §6.2 has no state for a
    stage run out of order.

    ``re_entry`` is the ``REPLAN`` that brought the run back, and it is checked
    rather than trusted on every attempt after the first: ``L_strategy`` is
    spent by the stage that detected the failure, so an attempt that cannot
    show what authorized it either spent no counter — which is how a run loops
    for ever — or spent someone else's.
    """

    _precondition(
        unit=unit,
        anchor=anchor,
        decision=decision,
        boundary=boundary,
        core=core,
        features=features,
    )
    _authorized(re_entry, attempt, unit, decision)

    scope_key = destination_scope_key(unit.unit_id, decision.destination)
    refusal = _spend(budget, scope_key)
    if refusal is not None:
        return StrategyProposal(
            unit_id=unit.unit_id,
            destination=decision.destination,
            outcomes=(refusal,),
        )

    request = _request(
        unit=unit,
        anchor=anchor,
        decision=decision,
        boundary=boundary,
        core=core,
        features=features,
        contract=contract,
        assets=assets,
        knowledge=knowledge,
    )
    answer = _answer(transport, request)
    defect = None if answer is None else _defect(answer)
    if answer is None or defect is not None:
        return StrategyProposal(
            unit_id=unit.unit_id,
            destination=decision.destination,
            outcomes=(
                _skip(
                    unit,
                    decision,
                    StateCode.STRATEGY_GENERATION_FAILED,
                    defect
                    or "the strategy call produced no answer this stage may read",
                ),
            ),
            calls=1,
        )
    return StrategyProposal(
        unit_id=unit.unit_id,
        destination=decision.destination,
        candidate_set=_candidate_set(
            unit=unit,
            anchor=anchor,
            decision=decision,
            boundary=boundary,
            core=core,
            features=features,
            contract=contract,
            assets=assets,
            knowledge=knowledge,
            answer=answer,
            attempt=attempt,
            re_entry=re_entry,
        ),
        calls=1,
    )


# ===========================================================================
# The code rules (§1 Pre and Post)
# ===========================================================================


def _precondition(
    *,
    unit: EditorialUnit,
    anchor: Anchor,
    decision: DestinationDecision,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    features: MaterialFeatures,
) -> None:
    """§1's Pre column: eligible destination, valid anchor, one unit throughout.

    "Anchor valid" is the boundary commit's rule 6 read forwards: the anchor is
    invalidated when its interpretation's current version in the newest E-09 is
    inadmissible. An invalid anchor is not S-08's to route around — S-04's
    re-entry owns it and spends ``L_anchor`` — so meeting one here is a stage
    run out of order.
    """

    if unit.status is not UnitStatus.ACTIVE:
        raise StrategyError(
            f"{unit.unit_id} is {unit.status.value} and reached {STAGE}; a unit "
            "that is not active has either not started or already ended"
        )
    if anchor.unit_id != unit.unit_id:
        raise StrategyError(
            f"anchor {anchor.anchor_id} is the anchor of {anchor.unit_id!r} and "
            f"reached {STAGE} for {unit.unit_id!r}; I-07 gives a unit exactly one"
        )
    if decision.unit_id != unit.unit_id:
        raise StrategyError(
            f"the destination decision {decision.destination_decision_id} was "
            f"made for {decision.unit_id!r} and reached {STAGE} for "
            f"{unit.unit_id!r}; a strategy is planned inside its own unit"
        )
    if decision.eligibility is not Eligibility.ELIGIBLE:
        raise StrategyError(
            f"{decision.destination_decision_id} is "
            f"{decision.eligibility.value} and reached {STAGE}; §1 Pre asks for "
            "an eligible destination, and S-07 already skipped this one with its "
            "rule"
        )
    if boundary.boundary_id != anchor.boundary_ref[0]:
        raise StrategyError(
            f"{anchor.anchor_id} was chosen against boundary "
            f"{anchor.boundary_ref[0]!r} and reached {STAGE} with "
            f"{boundary.boundary_id!r}; a strategy is planned inside its own "
            "unit's boundary"
        )
    if boundary.version < anchor.boundary_ref[1]:
        raise StrategyError(
            f"{anchor.anchor_id} was chosen against boundary version "
            f"{anchor.boundary_ref[1]} and reached {STAGE} with version "
            f"{boundary.version}; an older snapshot permits readings a newer one "
            "has refused (patch R2, F-4)"
        )
    member = boundary.member(anchor.interpretation_id)
    if member is None or not member.admissible:
        raise StrategyError(
            f"{anchor.anchor_id} anchors on {anchor.interpretation_id}, which "
            f"boundary version {boundary.version} does not admit; §1 Pre asks "
            "for a valid anchor, and an invalidated one is S-04's re-entry to "
            "route and S-06's to decide again (commit rule 6)"
        )
    if boundary.core_ref != (core.core_id, core.version):
        raise StrategyError(
            f"{unit.unit_id} reached {STAGE} with a boundary over "
            f"{boundary.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); the references of every move "
            "are checked against the core, and two that describe different "
            "material cannot both be right"
        )
    if features.core_ref != (core.core_id, core.version):
        raise StrategyError(
            f"{unit.unit_id} reached {STAGE} with features over "
            f"{features.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); E-05 is recomputed per core "
            "version, and a vector describing an earlier one answers about "
            "material this run no longer holds"
        )


def _authorized(
    route: Optional[OutcomeRecord],
    attempt: int,
    unit: EditorialUnit,
    decision: DestinationDecision,
) -> None:
    """Is this attempt the one a declared route paid for (§0.3)?

    A first execution is authorized by the run reaching S-08 at all, and every
    later one by the ``REPLAN`` that spent ``L_strategy`` for this destination.
    Four facts, each of which a wrong caller would get wrong differently: the
    record is a ``REPLAN``, it targets this stage, it spent this counter, and
    it spent it against this destination. Nothing here spends anything; what it
    refuses is an unbounded loop dressed as a re-entry.
    """

    if attempt < 1:
        raise StrategyError(
            f"{STAGE} was entered as attempt {attempt}; the first execution is "
            "attempt 1"
        )
    scope_key = destination_scope_key(unit.unit_id, decision.destination)
    if attempt == 1:
        if route is not None:
            raise StrategyError(
                f"{STAGE} was entered as attempt 1 with a route that spent "
                f"{route.counter!r}; the first execution of a destination is "
                "reached forwards and pays for nothing"
            )
        return
    if route is None:
        raise StrategyError(
            f"{STAGE} was entered as attempt {attempt} for {scope_key} with no "
            f"route; every attempt after the first spends {STRATEGY_COUNTER} "
            "(§0.3), and one that cannot show which record paid for it bounded "
            "nothing"
        )
    if route.outcome is not ArpOutcome.REPLAN:
        raise StrategyError(
            f"a re-entry into {STAGE} was authorized by a "
            f"{route.outcome.value}; only a REPLAN routes anywhere (§0.3), and a "
            "terminal outcome is where a destination ended rather than a way "
            "back in"
        )
    if route.route_target != STAGE:
        raise StrategyError(
            f"the route offered targets {route.route_target!r}, not {STAGE}; a "
            "re-entry is taken by the stage the route names"
        )
    if route.counter != STRATEGY_COUNTER:
        raise StrategyError(
            f"the route offered spent {route.counter!r}; §0.3 counts a re-entry "
            f"into {STAGE} against {STRATEGY_COUNTER}, and a route that spent "
            "another counter did not bound this one"
        )
    if route.scope_key not in (None, scope_key):
        raise StrategyError(
            f"the route offered spent {STRATEGY_COUNTER} against "
            f"{route.scope_key!r} and is being taken for {scope_key!r}; the "
            "counter is counted per destination, so another destination's "
            "attempt bounds nothing here"
        )
    if route.attempt is not None and attempt != route.attempt + 1:
        raise StrategyError(
            f"{STAGE} was entered as attempt {attempt} on a route that spent "
            f"attempt {route.attempt} of {STRATEGY_COUNTER}; the attempt a set "
            "is named for is the one the counter paid for, and a set named for "
            "another would collide with the one it replaces"
        )


def _candidate_set(
    *,
    unit: EditorialUnit,
    anchor: Anchor,
    decision: DestinationDecision,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    features: MaterialFeatures,
    contract: StrategyContract,
    assets: Sequence[Asset],
    knowledge: Sequence[RoutedKnowledge],
    answer: CandidatesAnswer,
    attempt: int,
    re_entry: Optional[OutcomeRecord],
) -> CandidateSet:
    """Build the set: every proposal that meets the schema, and the reasons."""

    identity = candidate_set_id(unit.unit_id, decision.destination, attempt)
    resolvable = _resolvable_refs(boundary, core, assets)
    routed = {
        item.identity: item
        for item in knowledge
        if item.record is not None and item.applicable
    }
    kept: list[EditorialStrategy] = []
    refused: list[RejectedCandidate] = []
    for position, proposal in enumerate(answer.candidates, 1):
        try:
            candidate = _candidate(
                proposal=proposal,
                strategy=strategy_id(identity, position),
                unit=unit,
                anchor=anchor,
                decision=decision,
                boundary=boundary,
                features=features,
                contract=contract,
                assets=assets,
                routed=routed,
                resolvable=resolvable,
                set_id=identity,
            )
        # BoundaryError is caught beside StrategyError because a candidate
        # carries records the boundary owns — a Justification is E-08's shape
        # reused rather than copied — and a proposal is refused with its reason
        # whichever entity said no. Letting one of them out would turn "one
        # candidate did not validate" into an S-08 that produced nothing, which
        # is a different state counted under a different category.
        except (StrategyError, BoundaryError) as refusal:
            refused.append(RejectedCandidate(index=position, reason=str(refusal)))
            continue
        kept.append(candidate)
    return CandidateSet(
        unit_id=unit.unit_id,
        destination=decision.destination,
        candidate_set_id=identity,
        attempt=attempt,
        candidates=tuple(kept),
        rejected=tuple(refused),
        re_entry_cause=None if re_entry is None else re_entry.state_code.value,
    )


def _candidate(
    *,
    proposal: StrategyAnswer,
    strategy: str,
    unit: EditorialUnit,
    anchor: Anchor,
    decision: DestinationDecision,
    boundary: InterpretationBoundary,
    features: MaterialFeatures,
    contract: StrategyContract,
    assets: Sequence[Asset],
    routed: Mapping[str, RoutedKnowledge],
    resolvable: frozenset[str],
    set_id: str,
) -> EditorialStrategy:
    """One proposal as an E-13, or :class:`StrategyError` saying why it is not.

    Every rule of §1's Post column, in the order a reader of that column meets
    them. The exception is the one AD-01 forbids: nothing is asked of the
    opening's relation to the leading material.
    """

    leading = {item.ref for item in anchor.leading_material}
    if proposal.leading_material_ref not in leading:
        raise StrategyError(
            f"the leading material {proposal.leading_material_ref!r} is not in "
            "this unit's leading-material set ("
            + ", ".join(sorted(leading))
            + "); AD-01 makes the set the one thing the destinations share"
        )
    if anchor.interpretation_id not in proposal.thesis_interpretation_refs:
        raise StrategyError(
            "the thesis rests on "
            + ", ".join(proposal.thesis_interpretation_refs)
            + f" and not on the unit's anchor {anchor.interpretation_id}; map "
            "§7.4 keeps the thesis within the anchor, and a thesis outside it is "
            "a second story for one unit (I-07)"
        )
    _admissible(proposal.thesis_interpretation_refs, boundary, "thesis")
    if proposal.second_interpretation_ref is not None:
        second = proposal.second_interpretation_ref
        if second == anchor.interpretation_id:
            raise StrategyError(
                f"the second interpretation {second} is the anchor itself; a "
                "second reading is a second reading"
            )
        if second not in unit.interpretation_scope:
            raise StrategyError(
                f"the second interpretation {second} is not in this unit's "
                "interpretation scope; Step 1 §4 admits one only from the unit's "
                "own scope"
            )
        _admissible((second,), boundary, "second interpretation")
    _resolves(proposal.thesis_interpretation_refs, resolvable, "the thesis")
    _resolves(proposal.focal_subject_refs, resolvable, "the focal subject")
    _resolves(proposal.opening.refs, resolvable, "the opening")
    for position, move in enumerate(proposal.reader_path, 1):
        _resolves(move.refs, resolvable, f"move {position}")
    if proposal.focal_subject_kind is FocalSubjectKind.PERSON_IN_STORY and not (
        features.value_of(MaterialFeature.DOCUMENTED_CASE).positive
    ):
        raise StrategyError(
            "the focal subject is a person in the story and the material holds "
            "no documented case; Step 1 §4 requires one in the core, which is "
            "V-P01's rule read at the stage that decides the field"
        )
    if proposal.client_position_ref is not None:
        position_ref = proposal.client_position_ref
        if contract.position(position_ref) is None:
            raise StrategyError(
                f"the client position {position_ref} is not one the contract "
                "approved; Step 1 §4 takes positional assets only from E-06"
            )
        if not _is_positional(position_ref, assets):
            raise StrategyError(
                f"the client position {position_ref} is not a positional asset "
                "of this run; a position the material carries as evidence is "
                "evidence, and AD-01 keeps the two apart"
            )
    if proposal.concession.present:
        limitation = proposal.concession.limitation_ref
        if limitation not in _limitations(boundary):
            raise StrategyError(
                f"the concession cites the limitation {limitation!r}, which the "
                "boundary does not state; Step 1 §4 requires a present "
                "concession's limitation to be in the boundary"
            )
    used = _knowledge_used(proposal.knowledge_used, routed)
    candidate = EditorialStrategy(
        strategy_id=strategy,
        unit_id=unit.unit_id,
        destination=decision.destination,
        candidate_set_id=set_id,
        anchor_ref=anchor.anchor_id,
        boundary_ref=(boundary.boundary_id, boundary.version),
        editorial_job=proposal.editorial_job,
        angle=proposal.angle,
        editorial_thesis=Thesis(
            text=proposal.thesis,
            interpretation_refs=tuple(
                dict.fromkeys(proposal.thesis_interpretation_refs)
            ),
        ),
        focal_subject=FocalSubject(
            kind=proposal.focal_subject_kind,
            text=proposal.focal_subject,
            refs=tuple(proposal.focal_subject_refs),
        ),
        leading_material_ref=proposal.leading_material_ref,
        reader_path=tuple(
            Move(text=move.text, purpose=move.purpose, refs=tuple(move.refs))
            for move in proposal.reader_path
        ),
        opening=Opening(
            text=proposal.opening.text,
            held_back=proposal.opening.held_back,
            refs=tuple(proposal.opening.refs),
        ),
        reveal=Reveal(kind=proposal.reveal, until_move=proposal.until_move),
        concession=Concession(
            present=proposal.concession.present,
            limitation_ref=proposal.concession.limitation_ref,
            move_index=proposal.concession.move_index,
        ),
        ending_intention=proposal.ending_intention,
        justifications=tuple(
            FieldJustification(
                field_name=entry.field_name,
                justification=Justification(
                    text=entry.text, refs=tuple(entry.refs)
                ),
            )
            for entry in proposal.justifications
        ),
        knowledge_used=used,
        second_interpretation_ref=proposal.second_interpretation_ref,
        client_position_ref=proposal.client_position_ref,
    )
    if not candidate.carries_leading_material:
        raise StrategyError(
            "no move of the reader path references "
            f"{candidate.leading_material_ref}; AD-01 makes it the strategy's "
            "primary evidentiary carrier, and a carrier the path never uses "
            "carries nothing. The opening is not consulted for this: AD-01 "
            "keeps the opening independent"
        )
    return candidate


def _admissible(
    refs: Sequence[str], boundary: InterpretationBoundary, what: str
) -> None:
    """I-05: a strategy may reference only admissible readings."""

    for identity in refs:
        member = boundary.member(identity)
        if member is None or not member.admissible:
            raise StrategyError(
                f"{what} references {identity}, which boundary version "
                f"{boundary.version} does not admit; I-05 lets a strategy "
                "reference only the admissible set, and the inadmissible list "
                "exists to be detected against rather than planned from"
            )


def _resolves(
    refs: Sequence[str], resolvable: frozenset[str], what: str
) -> None:
    """I-03: every reference names something this run holds."""

    unknown = sorted(set(refs) - resolvable)
    if unknown:
        raise StrategyError(
            f"{what} references "
            + ", ".join(unknown)
            + ", which this run does not hold; I-03 keeps facts inside the core "
            "and I-05 keeps readings inside the boundary, so a reference to "
            "neither is an invention"
        )


def _resolvable_refs(
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    assets: Sequence[Asset],
) -> frozenset[str]:
    """Everything a move may reference: claims, admissible readings, assets.

    Usable claims only (E-03's usability rule), because a claim the core holds
    and refuses is not a fact a text may rest on, and a move that referenced
    one would pass every later check by citing something nobody accepted.
    """

    return frozenset(
        {claim.evidence_claim_id for claim in core.usable_claims}
        | {member.interpretation_id for member in boundary.admissible}
        | {asset.asset_id for asset in assets}
    )


def _limitations(boundary: InterpretationBoundary) -> frozenset[str]:
    """The limitations a concession may cite: the boundary's and its members'.

    Identified by their text, because that is the identity a Limitation has:
    Step 1 gives E-08's and E-09's ``limits`` a text and references and no ID
    of their own. What the check enforces is the rule that matters — "if
    present, the limitation must be in the boundary" — and a caller that wants
    to cite one has to carry it across unchanged, which is the direction that
    fails closed.
    """

    return frozenset(
        {limit.text for limit in boundary.limits}
        | {
            limit.text
            for member in boundary.members
            for limit in member.limits
        }
    )


def _is_positional(asset_id: str, assets: Sequence[Asset]) -> bool:
    return any(
        asset.asset_id == asset_id and asset.asset_class is AssetClass.POSITIONAL
        for asset in assets
    )


def _knowledge_used(
    named: Sequence[str], routed: Mapping[str, RoutedKnowledge]
) -> tuple[KnowledgeRef, ...]:
    """The records that shaped a candidate, as they were at the time of use.

    Resolved against what this stage was routed rather than taken from the
    answer: I-11 says knowledge is not a routing table, and the way that fails
    is a strategy naming a record — with a tier, a status and an authority —
    that nobody put in front of it. The tier is the register's to state, never
    a model's.
    """

    refs: list[KnowledgeRef] = []
    for identity in dict.fromkeys(named):
        item = routed.get(identity)
        if item is None:
            raise StrategyError(
                f"the candidate records {identity} as knowledge it used, and "
                "this stage was not routed it; I-11 keeps knowledge_used a "
                "record of what reached the stage and not a table a strategy "
                "may add to"
            )
        refs.append(item.ref())
    return tuple(refs)


# ===========================================================================
# Requests, answers and outcomes
# ===========================================================================


def _request(
    *,
    unit: EditorialUnit,
    anchor: Anchor,
    decision: DestinationDecision,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    features: MaterialFeatures,
    contract: StrategyContract,
    assets: Sequence[Asset],
    knowledge: Sequence[RoutedKnowledge],
) -> str:
    """What the one call sees.

    One destination, and no field for a sibling's strategy, a sibling's text or
    a label. §1's **Not an input** row is kept the way S-06 keeps the
    destination out of the anchor call: a request with nowhere to put one
    carries none however the caller is written, and a later caller that wanted
    to pass a sibling's plan would have to change this function to do it.
    """

    body = core.as_entity()
    return json.dumps({
        "unit": {
            "unit_id": unit.unit_id,
            "interpretation_scope": list(unit.interpretation_scope),
        },
        "anchor": {
            "anchor_id": anchor.anchor_id,
            "interpretation_id": anchor.interpretation_id,
            "strength_used": anchor.strength_used.as_entity(),
            "leading_material": [
                item.as_entity() for item in anchor.leading_material
            ],
        },
        "destination": {
            "destination": decision.destination.value,
            "mode": None if decision.mode is None else decision.mode.value,
            "rule_ref": decision.rule_ref,
        },
        "boundary": {
            "boundary_id": boundary.boundary_id,
            "version": boundary.version,
            "admissible": [
                {
                    "interpretation_id": member.interpretation_id,
                    "statement": member.statement,
                    "kind": member.kind.value,
                    "support_refs": list(member.support_refs),
                    "strength_level": member.strength.level,
                    "ceiling_level": member.ceiling.level,
                    "limits": [limit.as_entity() for limit in member.limits],
                }
                for member in boundary.admissible
            ],
            "limits": [limit.as_entity() for limit in boundary.limits],
        },
        "core": {
            "core_id": core.core_id,
            "version": core.version,
            "sources": body["sources"],
            "observations": body["observations"],
            "claims": body["evidence_claims"],
        },
        "features": features.as_entity()["values"],
        "assets": [asset.as_entity() for asset in assets],
        "contract": {
            "positions": [
                {
                    "position_id": position.position_id,
                    "text": position.text,
                    "rule_id": position.rule_id,
                }
                for position in contract.positions
            ],
            "prohibitions": [
                {"rule_id": rule.rule_id, "text": rule.text, "tier": rule.tier.value}
                for rule in contract.prohibitions
            ],
            "preferences": [
                {"rule_id": rule.rule_id, "text": rule.text, "tier": rule.tier.value}
                for rule in contract.preferences
            ],
        },
        "knowledge": _routed_knowledge(knowledge),
    })


def _routed_knowledge(
    knowledge: Sequence[RoutedKnowledge],
) -> list[dict[str, Any]]:
    """What the register put in front of this stage, as the request carries it.

    The record's own tier and effective status travel with its text, because
    I-11 makes the trace show demoted knowledge losing rather than leaving a
    reader to work out what a record counted for. Checks are not knowledge here
    and carry no tier, so they are not among what this stage was routed.
    """

    entries: list[dict[str, Any]] = []
    for item in knowledge:
        record = item.record
        if record is None or not item.applicable:
            continue
        entries.append({
            "record_id": item.identity,
            "text": item.text,
            "tier": record.tier.value,
            "effective_status": record.effective_status.value,
        })
    return entries


def _answer(
    transport: StrategyTransport, request: str
) -> Optional[CandidatesAnswer]:
    """One call, parsed, or ``None``. Never the provider's own text."""

    try:
        raw = transport.complete(
            instructions=STRATEGY_INSTRUCTIONS, request=request
        )
    except Exception:  # noqa: BLE001 — sanitized, never the provider's text
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return CandidatesAnswer.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return None


def _defect(answer: CandidatesAnswer) -> Optional[str]:
    """Why this answer is not one, or ``None`` when it is one.

    The count and nothing else: §1 asks for 2–4 whole strategies, and an answer
    with one is a stage that chose before S-09 could, while an answer with five
    is a stage deciding how much planning this destination gets. What is wrong
    with an individual proposal is a schema rejection with its reason, which is
    a different fact and is recorded as one.
    """

    proposed = len(answer.candidates)
    if CANDIDATES_MIN <= proposed <= CANDIDATES_MAX:
        return None
    return (
        f"the strategy call returned {proposed} strategies; §1 asks for "
        f"{CANDIDATES_MIN}–{CANDIDATES_MAX} whole ones, and a set outside that "
        "range is the stage choosing among them or choosing how much to plan"
    )


def _skip(
    unit: EditorialUnit,
    decision: DestinationDecision,
    state_code: StateCode,
    reason: str,
) -> OutcomeRecord:
    return OutcomeRecord(
        outcome=ArpOutcome.SKIP,
        state_code=state_code,
        scope=OutcomeScope.DESTINATION,
        scope_key=destination_scope_key(unit.unit_id, decision.destination),
        reason=reason,
    )


def _spend(budget: Optional[CallBudget], scope_key: str) -> Optional[OutcomeRecord]:
    if budget is None:
        return None
    return budget.spend(scope=OutcomeScope.DESTINATION, scope_key=scope_key)
