"""S-10 · Executable plan: the chosen strategy, adapted to one destination.

The destination-scope stage that turns S-09's chosen strategy into something a
Writer can execute. Step 2 §3 gives it the adaptation and forbids it the
decision: "adapt the chosen strategy to the destination without changing what
the reader should believe or do (decision-vs-adaptation criterion). It sets
format, length, segments, first-line mechanics, subheadings, hashtags,
citations, voice brief and the conditional cross-destination link. **It must not
change any E-13 field**."

The criterion, as code
----------------------
E-14 has no field that E-13 also has. The thesis, the focal subject, the reader
path, the opening, the reveal, the concession and the ending intention are
reached through ``strategy_ref`` and are not copied here, so "adaptation may not
change any E-13 field" is not a rule this stage remembers to follow: there is
nowhere to write a changed one. What the plan adds is the surface — how long,
in what shape, cut into which segments, with which first line — and
:func:`adapt_strategy` builds every one of those from the destination's own
rules rather than from anything the strategy said.

Code first, and one call for the two questions it cannot answer
---------------------------------------------------------------
§3's Decider column: "``code`` for length ranges, hashtag policy, citations, the
forbidden list and the link. ``model`` for segmenting and first-line mechanics."
So the one call is asked for the segmentation and the first line and is given no
field for anything else — the citations it might have invented are computed from
the core, the link it might have promised is computed from E-12's dependencies,
and the forbidden list is resolved from the contract and from hard policy before
the request is built.

A link that the text does not need (R-2)
----------------------------------------
"A cross-destination link is **always conditional**: the plan must deliver its
promise without the link" (§3 Post, refinement R-2). There is no field that
makes one required: :class:`CrossDestinationLink` records the target and the
interpretation the link promises, and S-14 binds it only if the target was
published. A target E-12 already dropped — "link targets this unit will never
publish" — produces no link at all, because a promise nobody can keep is not a
weaker promise.

The one route out, and the one outcome of its own
-------------------------------------------------
§3's ARP column: "an adaptation that cannot fit a hard constraint (e.g. the
reader path does not fit the format's length) is a structural failure →
``REPLAN`` → S-08 (consumes ``L_strategy``)". It is decided by code before the
call, because paying for a segmentation of a path the format cannot hold buys
nothing.

``plan_generation_failed`` is the other: the call could not be made, could not
be read, or produced a segmentation that is not one. Terminal for the reason
S-08's ``strategy_generation_failed`` is terminal — no judgment about the
material was made, so there is nothing to degrade to — and kept apart from the
structural failure so that a provider outage is never counted as a destination
the format could not hold.

**Production safety.** One model call, no external call, and nothing calls this
stage: the run harness still executes S-10 as the SL-1 pass-through, and wiring
the stages of SL-5 into it is a later slice.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.2, §0.3
and §3 (S-10), §5.3 and §6 (R-2);
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §4 (E-14);
``docs/editorial/architecture/02_ARCHITECTURE_DECISIONS.md`` AD-02 §5;
``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §2.2, §2.3,
§2.5.
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
    KnowledgeRef,
    KnowledgeTier,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.candidate_strategies import EditorialStrategy
from src.editorial_core.destinations import (
    DESTINATIONS_DIRECTORY,
    Destination,
    DestinationDecision,
    DestinationMode,
    Eligibility,
    destination_scope_key,
)
from src.editorial_core.editorial_units import UNITS_DIRECTORY
from src.editorial_core.evidence_core import EvidenceCore
from src.editorial_core.interpretation_boundary import InterpretationBoundary
from src.editorial_core.material_features import Asset
from src.editorial_core.signal_selection import CallBudget
from src.editorial_core.strategy_selection import StrategySelection
from src.run.run_manifest import EntityIndexEntry
from src.run.run_workspace import PLAN_APPROVED, PLAN_DRAFT, RunWorkspace

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-10"

#: The entity it is the sole producer of drafts of (§3, Outputs).
PLAN_ENTITY_TYPE: Final[str] = "E-14"

#: Where a plan lives inside the destination's directory (§2.2).
PLANS_DIRECTORY: Final[str] = "plans"

#: The counter the structural route spends (§0.3).
STRATEGY_COUNTER: Final[str] = "L_strategy"

#: The route this stage takes, as the topology registry declares it.
ADAPTATION_CAUSE: Final[str] = "adaptation_cannot_meet_hard_constraint"

#: §2.5: "one ID per strategy attempt. ``v1`` = draft (S-10); ``v2`` = approved
#: (S-11), ``supersedes`` v1". Two versions and no third: an approved plan is
#: not edited, and a further attempt is a further strategy attempt with a plan
#: ID of its own.
DRAFT_VERSION: Final[int] = 1
APPROVED_VERSION: Final[int] = 2

#: The stage that writes the approved version of a plan (§2.3). Named here
#: because :func:`write_plan` writes both versions and the workspace decides
#: ownership by ``stage_of_version``; S-11's own module owns everything else
#: about approval.
APPROVING_STAGE: Final[str] = "S-11"


class PlanError(RuntimeError):
    """S-10 was asked to decide something its contract cannot decide."""


# ===========================================================================
# The vocabularies (Step 1 §4, E-14)
# ===========================================================================


class PlanFormat(str, Enum):
    """E-14's ``format``, exactly as Step 1 §4 lists it."""

    ARTICLE = "article"
    POST = "post"
    CAROUSEL = "carousel"
    THREAD = "thread"
    CHANNEL_POST = "channel_post"
    OTHER = "other"


class LengthUnit(str, Enum):
    """E-14's ``length_target`` unit: "words / characters / slides"."""

    WORDS = "words"
    CHARACTERS = "characters"
    SLIDES = "slides"


class HashtagPolicy(str, Enum):
    """What the destination's rules do with hashtags.

    Three values because a plan has to record the difference between a surface
    that wants them, one that tolerates them and one that refuses them: "no
    hashtags" and "hashtags are not required" are the same list and different
    rules, and V-P04 checks the rule rather than the list.
    """

    REQUIRED = "required"
    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"


class ForbiddenKind(str, Enum):
    """What a forbidden entry is: a phrase, or a construction type.

    Step 1 §4: ``forbidden`` holds "phrases and construction types in force". A
    phrase is matched by code; a construction type is the one part of V-P04 a
    string match cannot answer, and the check record sends it to the model.
    """

    PHRASE = "phrase"
    CONSTRUCTION = "construction"


class PlanStage(str, Enum):
    """E-14's ``stage_of_version``: "draft (produced by S-10) / approved (S-11)".

    The values are the workspace's own, imported rather than written again:
    §2.3 splits ``plans/*`` between the two stages by this field, and a second
    spelling of it would be a plan no stage owns.
    """

    DRAFT = PLAN_DRAFT
    APPROVED = PLAN_APPROVED


def normalized(value: str) -> str:
    """One spelling of a string, for the mechanical parts of the checks.

    Case and run-length of whitespace are not what a forbidden phrase is about,
    and ``EditorialPlan.forbidden_in`` already matches this way in the current
    engine (``src/editorial/editorial_plan.py``). Lifted here rather than
    imported because the editorial core does not depend on the engine it
    replaces.
    """

    return " ".join(value.lower().split())


# ===========================================================================
# E-14 · Executable Destination Plan
# ===========================================================================


@dataclass(frozen=True, slots=True)
class LengthTarget:
    """E-14's ``length_target``: "range, unit (words / characters / slides)".

    A range and not a ceiling, and both ends are part of it: a surface that
    refuses a post under its minimum refuses it exactly as firmly as one that
    refuses a post over its maximum, and a plan checked at one end only would
    be approved against half a rule.
    """

    minimum: int
    maximum: int
    unit: LengthUnit

    def __post_init__(self) -> None:
        if self.minimum < 1:
            raise PlanError(
                f"the length target starts at {self.minimum}; a plan that may "
                "be empty states no target"
            )
        if self.maximum < self.minimum:
            raise PlanError(
                f"the length target runs from {self.minimum} to {self.maximum} "
                f"{self.unit.value}; a range whose end is before its start "
                "admits nothing"
            )

    def contains(self, value: int) -> bool:
        """Is this count inside the range? Both ends, not one of them."""

        return self.minimum <= value <= self.maximum

    def within(self, other: "LengthTarget") -> bool:
        """Is this range inside another's, at both ends and in its unit?

        What V-P04 asks of a plan against the destination's own rule. A target
        that starts below the surface's minimum is as far outside it as one
        that ends above its maximum, and units that differ are not compared at
        all: 900 characters is not 900 words.
        """

        return (
            self.unit is other.unit
            and self.minimum >= other.minimum
            and self.maximum <= other.maximum
        )

    def as_entity(self) -> dict[str, Any]:
        return {
            "minimum": self.minimum,
            "maximum": self.maximum,
            "unit": self.unit.value,
        }


@dataclass(frozen=True, slots=True)
class Segment:
    """One entry of E-14's ``segments``: "(segment, the moves it carries)".

    ``move_indices`` are 1-based positions in the strategy's reader path, which
    is where the moves live: E-14 does not copy them (a copy would be an E-13
    field this stage could change), so a segment names them.
    """

    name: str
    purpose: str
    move_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.purpose.strip():
            raise PlanError(
                "a segment states what it is and what it is for; the purpose is "
                "what makes a segmentation checkable against the reader path"
            )
        if not self.move_indices:
            raise PlanError(
                f"the segment {self.name!r} carries no move; §3's Post column is "
                "'every move is carried by at least one segment', and a segment "
                "that carries none is surface the plan added to the strategy"
            )
        if any(index < 1 for index in self.move_indices):
            raise PlanError(
                f"the segment {self.name!r} carries move "
                f"{min(self.move_indices)}; the reader path is numbered from 1"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "moves": list(self.move_indices),
        }


@dataclass(frozen=True, slots=True)
class CrossDestinationLink:
    """E-14's ``cross_destination_link``, which is always conditional (R-2).

    There is no field that makes one required, and that absence is the
    refinement: "the linking text must deliver its promise without it. The link
    is bound at S-14 only if the target was published, otherwise omitted
    (``DEGRADE``)". A plan that could declare a link mandatory would be a plan
    whose promise fails when a sibling destination is skipped after the text
    was written, which is the case R-2 replaced "drop the link in adaptation"
    to cover.
    """

    target: Destination
    #: The interpretation the link promises — a reading, not a fact and not the
    #: sibling's text (I-06).
    interpretation_ref: str

    def __post_init__(self) -> None:
        if not self.interpretation_ref.strip():
            raise PlanError(
                f"the link to {self.target.value} promises no interpretation; a "
                "link is a promise about a reading, and one that promises "
                "nothing is a URL the plan decided to carry"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "target": self.target.value,
            "interpretation_ref": self.interpretation_ref,
            # Recorded on the entity rather than left to a reader: S-14 binds
            # the link only if the target was published, and a consumer that
            # had to infer the condition could bind one that was not.
            "conditional": True,
        }


@dataclass(frozen=True, slots=True)
class ForbiddenItem:
    """One entry of E-14's ``forbidden``, with the rule that put it there.

    "Resolved from the contract (tier 2) and hard policy (tier 1)" (Step 1 §4),
    so the tier travels with the entry: V-P04's route is decided by the tier of
    the rule the plan broke, and an entry that did not carry one would be
    routed by whoever read it.
    """

    kind: ForbiddenKind
    value: str
    rule_ref: str
    tier: KnowledgeTier
    knowledge: Optional[KnowledgeRef] = None

    def __post_init__(self) -> None:
        if not self.value.strip() or not self.rule_ref.strip():
            raise PlanError(
                "a forbidden entry names what is forbidden and the rule that "
                "forbids it; a list with neither cannot be checked or explained"
            )
        if self.knowledge is not None and self.knowledge.tier is not self.tier:
            raise PlanError(
                f"{self.rule_ref} is recorded at tier {self.tier.value} and "
                f"cites {self.knowledge.record_id} at tier "
                f"{self.knowledge.tier.value}; the tier belongs to whoever wrote "
                "the record"
            )

    def matches(self, text: str) -> bool:
        """Does this text carry the forbidden phrase?

        Only a phrase is matched here. A construction type is not a string —
        V-P04's own criterion sends it to the model, "does any segment execute a
        construction type the contract forbids, however it is worded?" — and
        matching one mechanically would pass a plan that used other words.
        """

        return (
            self.kind is ForbiddenKind.PHRASE
            and normalized(self.value) in normalized(text)
        )

    def as_entity(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "value": self.value,
            "rule_ref": self.rule_ref,
            "tier": self.tier.value,
            "knowledge": (
                None
                if self.knowledge is None
                else self.knowledge.model_dump(mode="json")
            ),
        }


@dataclass(frozen=True, slots=True)
class FixedSlot:
    """A contract slot S-10 treats as a constraint (§3, Inputs).

    "Fixed slots such as ``ending_mode`` treated as constraints": the value is
    the client's and the plan carries it unchanged, so that V-P04 can compare
    what the plan holds with what the contract fixed rather than ask whether the
    plan would like to.
    """

    name: str
    value: str
    rule_ref: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.rule_ref.strip():
            raise PlanError(
                "a fixed slot is named, and cites the contract rule that fixed "
                "it; a slot with neither is a value nobody agreed to"
            )
        if not self.value.strip():
            raise PlanError(
                f"the fixed slot {self.name} holds no value; a slot the contract "
                "left open is not fixed, and is absent rather than empty"
            )

    def as_entity(self) -> dict[str, str]:
        return {"name": self.name, "value": self.value, "rule_ref": self.rule_ref}


@dataclass(frozen=True, slots=True)
class Hashtags:
    """E-14's ``hashtags``: "policy + list".

    The policy is checked against the list here rather than at S-11, because
    the two are one field: a plan that records ``forbidden`` and three tags has
    not broken a rule, it has failed to state one thing.
    """

    policy: HashtagPolicy
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(not tag.strip() for tag in self.tags):
            raise PlanError("a hashtag is a tag; an empty one is not one")
        if self.policy is HashtagPolicy.FORBIDDEN and self.tags:
            raise PlanError(
                f"the hashtag policy is {self.policy.value} and the plan lists "
                f"{len(self.tags)} tag(s); the policy is what the destination's "
                "rule says, and a list against it is not a plan but a conflict"
            )
        if self.policy is HashtagPolicy.REQUIRED and not self.tags:
            raise PlanError(
                f"the hashtag policy is {self.policy.value} and the plan lists "
                "none; both ends of a policy are checked, or half of it is"
            )

    def as_entity(self) -> dict[str, Any]:
        return {"policy": self.policy.value, "tags": list(self.tags)}


@dataclass(frozen=True, slots=True)
class Exemplar:
    """One entry of E-14's ``exemplars``: "(item ID, take, do not copy)".

    Empty in the draft and filled in the approved version (Step 1 §4), which is
    why the record lives here — with the entity — and is produced at S-11.
    """

    item_id: str
    take: str
    do_not_copy: str

    def __post_init__(self) -> None:
        if not self.item_id.strip():
            raise PlanError("an exemplar names the reference library item it is")
        if not self.take.strip() or not self.do_not_copy.strip():
            raise PlanError(
                f"the exemplar {self.item_id} carries no take note or no "
                "do-not-copy note; Step 1 §4 keeps both, because an example "
                "handed over without the second is a template"
            )

    def as_entity(self) -> dict[str, str]:
        return {
            "item_id": self.item_id,
            "take": self.take,
            "do_not_copy": self.do_not_copy,
        }


@dataclass(frozen=True, slots=True)
class AppliedConstraint:
    """One constraint the adaptation applied, and the tier it came from.

    §3's Trace column: "the plan; which constraints were applied from which
    tier". A list rather than a sentence, because the tier is what decides
    V-P04's route later, and a reader of the plan is owed the same table the
    check will be read against.
    """

    rule_ref: str
    tier: KnowledgeTier
    detail: str
    knowledge: Optional[KnowledgeRef] = None

    def __post_init__(self) -> None:
        if not self.rule_ref.strip() or not self.detail.strip():
            raise PlanError(
                "an applied constraint names the rule and what it fixed; a row "
                "with neither records that something was applied and nothing else"
            )
        if self.knowledge is not None and self.knowledge.tier is not self.tier:
            raise PlanError(
                f"{self.rule_ref} is applied at tier {self.tier.value} citing "
                f"{self.knowledge.record_id} at tier {self.knowledge.tier.value}; "
                "the tier belongs to whoever wrote the record"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
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
class ExecutablePlan:
    """``E-14``: one strategy, adapted to one destination (Step 1 §4).

    **No E-13 field appears here.** The thesis, focal subject, reader path,
    opening, reveal, concession and ending intention are reached through
    ``strategy_ref``, so the decision-vs-adaptation criterion is not a rule this
    entity obeys — it is a shape that cannot express the breach.

    A version is a ``draft`` or an ``approved``, and the difference is not
    cosmetic: §2.3 gives ``plans/*`` to S-10 or to S-11 by this field, and only
    an approved version goes to S-12 (I-08).
    """

    plan_id: str
    version: int
    unit_id: str
    destination: Destination
    mode: DestinationMode
    strategy_ref: str
    format: PlanFormat
    length_target: LengthTarget
    first_line_mechanics: str
    segments: tuple[Segment, ...]
    citations: tuple[str, ...]
    voice_brief_ref: str
    forbidden: tuple[ForbiddenItem, ...]
    fixed_slots: tuple[FixedSlot, ...]
    stage_of_version: PlanStage
    attempt: int
    subheadings: Optional[str] = None
    hashtags: Optional[Hashtags] = None
    cross_destination_link: Optional[CrossDestinationLink] = None
    exemplars: tuple[Exemplar, ...] = ()
    constraints: tuple[AppliedConstraint, ...] = ()
    #: The draft this approved version replaces (§2.5). ``None`` on the draft.
    supersedes: Optional[tuple[str, int]] = None

    def __post_init__(self) -> None:
        if not self.plan_id.strip() or not self.unit_id.strip():
            raise PlanError(
                "a plan is identified by its own ID and the unit it is a plan for"
            )
        if not self.strategy_ref.strip():
            raise PlanError(
                f"{self.plan_id} names no strategy; a plan is one chosen E-13 "
                "adapted, and one that names none adapted nothing"
            )
        if self.attempt < 1:
            raise PlanError(
                f"{self.plan_id} records attempt {self.attempt}; the first "
                "adaptation of a destination is attempt 1"
            )
        if not self.first_line_mechanics.strip():
            raise PlanError(
                f"{self.plan_id} states no first-line mechanics; §3 makes it one "
                "of the two things the call decides, and a plan without it "
                "leaves the preview cut-off to the Writer (I-08)"
            )
        if not self.voice_brief_ref.strip():
            raise PlanError(
                f"{self.plan_id} references no voice document version; Step 1 §4 "
                "requires one, and a voice nobody versioned cannot be checked "
                "against what the client approved"
            )
        if not self.segments:
            raise PlanError(
                f"{self.plan_id} has no segments; every move of the reader path "
                "is carried by at least one of them, and none carries none"
            )
        if not self.citations:
            raise PlanError(
                f"{self.plan_id} cites no source; Step 1 §4 requires the field, "
                "and a plan that cites nothing leaves the Writer to choose what "
                "the text rests on — which I-03 gives to the core"
            )
        self._format_states_its_subheadings()
        self._version_matches_its_stage()

    def _format_states_its_subheadings(self) -> None:
        takes_subheadings = self.format is PlanFormat.ARTICLE
        if takes_subheadings and self.subheadings is None:
            raise PlanError(
                f"{self.plan_id} is an {self.format.value} and states no "
                "subheadings plan; Step 1 §4 requires the field for article "
                "formats, and 'no subheadings' is a plan stated as one"
            )
        if not takes_subheadings and self.subheadings is not None:
            raise PlanError(
                f"{self.plan_id} is a {self.format.value} and states a "
                "subheadings plan; the field belongs to the formats that carry "
                "subheadings, and a plan for one that does not is surface "
                "nobody will execute"
            )

    def _version_matches_its_stage(self) -> None:
        if self.stage_of_version is PlanStage.DRAFT:
            if self.version != DRAFT_VERSION:
                raise PlanError(
                    f"{self.plan_id} is a draft at version {self.version}; §2.5 "
                    f"makes the draft v{DRAFT_VERSION}, and a second draft is a "
                    "second strategy attempt with a plan ID of its own"
                )
            if self.exemplars:
                raise PlanError(
                    f"{self.plan_id} is a draft and carries "
                    f"{len(self.exemplars)} exemplar(s); Step 1 §4 keeps them "
                    "empty in the draft, because choosing them is S-11's and a "
                    "draft that chose its own examples was checked against them"
                )
            if self.supersedes is not None:
                raise PlanError(
                    f"{self.plan_id} is a draft and supersedes "
                    f"{self.supersedes!r}; the draft is where a plan starts"
                )
            return
        if self.version != APPROVED_VERSION:
            raise PlanError(
                f"{self.plan_id} is approved at version {self.version}; §2.5 "
                f"makes the approved version v{APPROVED_VERSION}, superseding "
                "the draft it was checked as"
            )
        if self.supersedes != (self.plan_id, DRAFT_VERSION):
            raise PlanError(
                f"{self.plan_id} is approved and supersedes {self.supersedes!r}; "
                "an approved version supersedes its own draft, and one that "
                "supersedes another plan was never checked"
            )

    @property
    def scope_key(self) -> str:
        """The destination scope key this plan was made under (§4.2)."""

        return destination_scope_key(self.unit_id, self.destination)

    @property
    def carried_moves(self) -> frozenset[int]:
        """Every move index some segment carries."""

        return frozenset(
            index for segment in self.segments for index in segment.move_indices
        )

    @property
    def plan_ref(self) -> tuple[str, int]:
        """This exact version, as a reference another record may hold."""

        return (self.plan_id, self.version)

    def texts(self) -> tuple[str, ...]:
        """Every string of this plan a forbidden phrase could appear in.

        The plan's own surface and nothing the strategy decided: what E-13
        holds is checked where E-13 was written, and re-checking it here would
        make one finding into two with different owners (I-09).
        """

        stated = [self.first_line_mechanics, *(
            f"{segment.name} {segment.purpose}" for segment in self.segments
        )]
        if self.subheadings is not None:
            stated.append(self.subheadings)
        if self.hashtags is not None:
            stated.extend(self.hashtags.tags)
        return tuple(stated)

    def approved_with(self, exemplars: Sequence[Exemplar]) -> "ExecutablePlan":
        """The approved version of this draft, with its exemplars (S-11).

        Everything else is carried across unchanged, and that is the whole
        method: §3 says S-11 "must not repair plans", so approval is a copy with
        the two fields approval consists of — the stage of the version and the
        exemplars — and there is no argument for anything else.
        """

        if self.stage_of_version is not PlanStage.DRAFT:
            raise PlanError(
                f"{self.plan_id} is already {self.stage_of_version.value} and is "
                "being approved again; a version is approved once, and an "
                "approval that could be repeated is a plan that could be reopened"
            )
        return ExecutablePlan(
            plan_id=self.plan_id,
            version=APPROVED_VERSION,
            unit_id=self.unit_id,
            destination=self.destination,
            mode=self.mode,
            strategy_ref=self.strategy_ref,
            format=self.format,
            length_target=self.length_target,
            first_line_mechanics=self.first_line_mechanics,
            segments=self.segments,
            citations=self.citations,
            voice_brief_ref=self.voice_brief_ref,
            forbidden=self.forbidden,
            fixed_slots=self.fixed_slots,
            stage_of_version=PlanStage.APPROVED,
            attempt=self.attempt,
            subheadings=self.subheadings,
            hashtags=self.hashtags,
            cross_destination_link=self.cross_destination_link,
            exemplars=tuple(exemplars),
            constraints=self.constraints,
            supersedes=(self.plan_id, DRAFT_VERSION),
        )

    def as_entity(self) -> dict[str, Any]:
        """The E-14 body, written to ``plans/<plan_id>.v<n>.json`` (§2.2)."""

        return {
            "entity_type": PLAN_ENTITY_TYPE,
            "entity_id": self.plan_id,
            "plan_id": self.plan_id,
            "version": self.version,
            "unit_id": self.unit_id,
            "destination": self.destination.value,
            "mode": self.mode.value,
            "strategy_ref": self.strategy_ref,
            "format": self.format.value,
            "length_target": self.length_target.as_entity(),
            "first_line_mechanics": self.first_line_mechanics,
            "segments": [segment.as_entity() for segment in self.segments],
            "subheadings": self.subheadings,
            "hashtags": (
                None if self.hashtags is None else self.hashtags.as_entity()
            ),
            "cross_destination_link": (
                None
                if self.cross_destination_link is None
                else self.cross_destination_link.as_entity()
            ),
            "citations": list(self.citations),
            "voice_brief_ref": self.voice_brief_ref,
            "exemplars": [item.as_entity() for item in self.exemplars],
            "forbidden": [item.as_entity() for item in self.forbidden],
            "fixed_slots": [slot.as_entity() for slot in self.fixed_slots],
            "constraints": [item.as_entity() for item in self.constraints],
            "stage_of_version": self.stage_of_version.value,
            "attempt": self.attempt,
            "supersedes": (
                None
                if self.supersedes is None
                else {"plan_id": self.supersedes[0], "version": self.supersedes[1]}
            ),
        }


@dataclass(frozen=True, slots=True)
class AdaptationDecision:
    """What one S-10 execution made of one destination.

    The plan is absent whenever none was produced: the budget refused, the call
    produced nothing this stage may read, or the reader path does not fit the
    format and the destination went back to S-08. A draft that exists is a draft
    S-11 may check, and there is no third state between the two.
    """

    unit_id: str
    destination: Destination
    plan: Optional[ExecutablePlan] = None
    outcomes: tuple[OutcomeRecord, ...] = ()
    #: Model calls this execution made, for the per-stage call record (§3.3).
    calls: int = 0


# ===========================================================================
# What the stage is handed
# ===========================================================================


@dataclass(frozen=True, slots=True)
class PlatformRule:
    """One ``K-DST-*`` record as S-10 applies it (§3, Inputs: tiers 1 and 4).

    Resolved by the caller from the loaded register, for the reason S-07's
    :class:`~src.editorial_core.destinations.PlatformPolicy` is: applicability
    is the record's own ``## Applies when``, evaluated by the loader's condition
    machinery, and a stage that re-judged it would be a second answer.

    ``compliant_variant`` is the record's own property and never this stage's
    opinion: V-P04's route table ends a destination on "a tier-1 hard platform
    rule is violated **with no compliant variant**", and whether a compliant
    variant exists is a fact about the rule — a length ceiling admits a shorter
    plan, a surface that refuses the material at all admits nothing.
    """

    rule_id: str
    text: str
    tier: KnowledgeTier
    compliant_variant: bool = True
    knowledge: Optional[KnowledgeRef] = None

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.text.strip():
            raise PlanError(
                "a platform rule is named by its record ID and states what it "
                "requires; a rule with neither cannot be applied or cited"
            )
        if self.tier not in (
            KnowledgeTier.HARD_PLATFORM_POLICY,
            KnowledgeTier.PLATFORM_RANKING,
        ):
            raise PlanError(
                f"{self.rule_id} is offered at tier {self.tier.value}; §3 gives "
                f"{STAGE} K-DST records at tiers 1 and 4, and a rule from "
                "anywhere else reaches adaptation as the contract's, with the "
                "contract's authority"
            )
        if (
            self.tier is KnowledgeTier.PLATFORM_RANKING
            and not self.compliant_variant
        ):
            raise PlanError(
                f"{self.rule_id} is a tier-{self.tier.value} ranking record "
                "recorded as admitting no compliant variant; only a tier-1 hard "
                "rule ends a destination (V-P04), and a ranking record that "
                "could would be a hard rule nobody approved"
            )
        if self.knowledge is not None and self.knowledge.tier is not self.tier:
            raise PlanError(
                f"{self.rule_id} is recorded at tier {self.tier.value} and cites "
                f"{self.knowledge.record_id} at tier {self.knowledge.tier.value}; "
                "the tier belongs to whoever wrote the record"
            )

    @property
    def is_hard(self) -> bool:
        """Is this a tier-1 hard platform rule?"""

        return self.tier is KnowledgeTier.HARD_PLATFORM_POLICY


@dataclass(frozen=True, slots=True)
class DestinationRules:
    """What the destination's own rules fix about its surface (§3, Inputs).

    The format, the length range and the hashtag policy are the destination's,
    not the plan's: adaptation applies them, and V-P04 later compares the plan
    with them again — against the rules in front of S-11, which a keeper may
    have changed since. Each of the three names the rule that fixed it, because
    V-P04's route is decided by the tier of the rule a plan broke: a finding
    that could not say which record fixed the value it broke would be routed by
    whoever read it.

    ``segment_capacity`` is how many segments the surface counts, where it
    counts them: a carousel's slides and a thread's posts are countable, an
    article's paragraphs are not. It is the one number that can make a reader
    path structurally impossible, and it comes from the destination's knowledge
    rather than from arithmetic this stage invented.
    """

    destination: Destination
    format: PlanFormat
    format_rule: PlatformRule
    length: LengthTarget
    length_rule: PlatformRule
    hashtags: HashtagPolicy
    hashtag_rule: PlatformRule
    segments_max: Optional[int] = None
    #: Everything else the register routed to this destination's adaptation.
    #: They shape the plan and are recorded in its constraints; the three above
    #: are the ones a plan can be compared against by code.
    other_rules: tuple[PlatformRule, ...] = ()

    def __post_init__(self) -> None:
        if self.segments_max is not None and self.segments_max < 1:
            raise PlanError(
                f"{self.destination.value} is recorded as carrying "
                f"{self.segments_max} segment(s); a surface that carries none "
                "publishes nothing, and that is S-07's exclusion rather than a "
                "length rule"
            )
        stated: dict[str, PlatformRule] = {}
        for rule in (
            self.format_rule,
            self.length_rule,
            self.hashtag_rule,
            *self.other_rules,
        ):
            held = stated.setdefault(rule.rule_id, rule)
            if held != rule:
                raise PlanError(
                    f"{rule.rule_id} is offered twice with different content; a "
                    "finding cites the rule that made it, and a name two rules "
                    "answer to names neither"
                )

    @property
    def rules(self) -> tuple[PlatformRule, ...]:
        """Every rule that reached this adaptation, each of them once."""

        stated: dict[str, PlatformRule] = {}
        for rule in (
            self.format_rule,
            self.length_rule,
            self.hashtag_rule,
            *self.other_rules,
        ):
            stated.setdefault(rule.rule_id, rule)
        return tuple(stated.values())

    @property
    def segment_capacity(self) -> Optional[int]:
        """The most segments this surface holds, or ``None`` where it counts none.

        The declared maximum, and otherwise the length's own when the length is
        counted in segments: a carousel whose target ends at eight slides holds
        eight, and saying so twice would let the two disagree.
        """

        if self.segments_max is not None:
            return self.segments_max
        if self.length.unit is LengthUnit.SLIDES:
            return self.length.maximum
        return None

    @property
    def hard_rules(self) -> tuple[PlatformRule, ...]:
        """The tier-1 rules: the ones a plan cannot be replanned around."""

        return tuple(rule for rule in self.rules if rule.is_hard)


@dataclass(frozen=True, slots=True)
class AdaptationContract:
    """The contract material §3 makes an input of S-10.

    "Client Contract: voice document, forbidden phrases and constructions, fixed
    slots such as ``ending_mode`` treated as constraints". The voice brief is
    referenced by version, the forbidden list is resolved into the plan, and the
    fixed slots are carried unchanged so V-P04 can compare rather than ask.

    ``hashtags`` is the client's tag list. The **policy** is the destination's —
    a surface decides whether tags are wanted, tolerated or refused — and what
    the tags say is the client's voice, so neither this stage nor its one call
    invents one.
    """

    voice_brief_ref: str
    forbidden: tuple[ForbiddenItem, ...] = ()
    fixed_slots: tuple[FixedSlot, ...] = ()
    hashtags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.voice_brief_ref.strip():
            raise PlanError(
                "the contract offers no voice document version; E-14 references "
                "one, and a voice nobody versioned cannot be checked against"
            )
        named = [slot.name for slot in self.fixed_slots]
        repeated = sorted({item for item in named if named.count(item) > 1})
        if repeated:
            raise PlanError(
                "the contract fixes "
                + ", ".join(repeated)
                + " twice; two values for one slot fix neither"
            )


# ===========================================================================
# Identity and storage
# ===========================================================================


def plan_id(set_id: str) -> str:
    """The ID of the one plan over one candidate set (§2.5).

    "One ID per strategy attempt", derived from the set the attempt produced
    rather than counted: a second attempt is a second candidate set, so the
    plan it leads to is named apart from the one it replaces — which the
    workspace refuses to overwrite (P1) rather than silently accepts.
    """

    if not set_id.strip():
        raise PlanError("a plan is named for the candidate set it was chosen from")
    return f"plan-{set_id}"


def plans_relative_path(unit: str, destination: Destination) -> str:
    """``units/<unit>/destinations/<dst>/plans`` (§2.2)."""

    _validate_path_component(unit, "unit_id")
    return (
        f"{UNITS_DIRECTORY}/{unit}/{DESTINATIONS_DIRECTORY}/{destination.value}/"
        f"{PLANS_DIRECTORY}"
    )


def plan_relative_path(
    unit: str, destination: Destination, identity: str, version: int
) -> str:
    """``plans/<plan_id>.v<n>.json`` (§2.2)."""

    _validate_path_component(identity, "plan_id")
    if version < 1:
        raise PlanError(f"a plan version is numbered from 1; got {version}")
    return f"{plans_relative_path(unit, destination)}/{identity}.v{version}.json"


def write_plan(workspace: RunWorkspace, plan: ExecutablePlan) -> EntityIndexEntry:
    """Write one plan version into the run workspace, and index it.

    The writing stage is the version's own: §2.3 splits ``plans/*`` between
    S-10 (``draft``) and S-11 (``approved``), and the entity already declares
    which of them made it. Deriving the stage from the field rather than from
    the caller is what stops an approved plan from being written as a draft —
    the workspace would accept it, because the path is the same.
    """

    stage = STAGE if plan.stage_of_version is PlanStage.DRAFT else APPROVING_STAGE
    return workspace.write_entity(
        stage=stage,
        relative_path=plan_relative_path(
            plan.unit_id, plan.destination, plan.plan_id, plan.version
        ),
        entity_type=PLAN_ENTITY_TYPE,
        entity_id=plan.plan_id,
        payload=plan.as_entity(),
        version=plan.version,
    )


# ===========================================================================
# The one call
# ===========================================================================


class SegmentationTransport(Protocol):
    """The model call S-10 makes: segmenting, and the first line."""

    def complete(self, *, instructions: str, request: str) -> str: ...


SEGMENTATION_INSTRUCTIONS = """\
You cut ONE already-decided editorial strategy into the segments of ONE
destination's format, and you decide how its first line works on that surface.

You decide nothing else. The thesis, the focal subject, the reader path, the
opening, the reveal, the concession and the ending intention are already
decided and are given to you as they are: you do not restate them, improve them,
add to them or drop any of them. You do not choose citations, hashtags or links —
those are computed from the run's own records.

Two rules bind the segmentation:

- every move of the reader path must be carried by at least one segment. A move
  may be carried by more than one segment, and a segment may carry more than one
  move, but no move may be left out;
- the number of segments must fit the format, within the segment capacity the
  request states when it states one.

`first_line_mechanics` says how the first line works on this surface — the
preview cut-off, the first slide, what is visible before a reader expands the
text — and not what the first line says.

`subheadings` is a plan for them when the request asks for one, and null
otherwise. When the format takes subheadings, "no subheadings, the segments run
on" is a plan; say it rather than leaving the field empty.

Return ONLY one valid JSON object, no text outside it:

{"segments": [{"name": "...", "purpose": "...", "moves": [1, 2]}],
 "first_line_mechanics": "...", "subheadings": null}
"""


class _PlanModel(BaseModel):
    """An answer is parsed strictly, or it is not an answer."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SegmentAnswer(_PlanModel):
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    moves: tuple[int, ...] = ()


class SegmentationAnswer(_PlanModel):
    segments: tuple[SegmentAnswer, ...] = ()
    first_line_mechanics: str = Field(min_length=1)
    subheadings: Optional[str] = Field(default=None, min_length=1)


# ===========================================================================
# The stage
# ===========================================================================


def adapt_strategy(
    *,
    strategy: EditorialStrategy,
    selection: StrategySelection,
    decision: DestinationDecision,
    rules: DestinationRules,
    contract: AdaptationContract,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    counters: AttemptCounterLedger,
    transport: SegmentationTransport,
    assets: Sequence[Asset] = (),
    attempt: int = 1,
    budget: Optional[CallBudget] = None,
) -> AdaptationDecision:
    """Adapt one chosen strategy to one destination: one call, one draft.

    Returns an :class:`AdaptationDecision` in every case the protocol has an
    outcome for, including the structural failure that sends the destination
    back to S-08: that is a recorded ``REPLAN`` — or the destination's ``SKIP``
    once ``L_strategy`` is gone — and not an exception, for the reason S-00
    through S-09 give. The stage's preconditions still raise.

    The structural check runs **before** the call. §3's ARP column makes "the
    reader path does not fit the format's length" a structural failure, and a
    failure that is already decided is not one a segmentation could talk its way
    out of — paying for the call first would spend the run's allowance to learn
    what the format already said.
    """

    _precondition(
        strategy=strategy,
        selection=selection,
        decision=decision,
        rules=rules,
        contract=contract,
        boundary=boundary,
        core=core,
    )
    scope_key = destination_scope_key(strategy.unit_id, decision.destination)
    structural = _structural_conflict(strategy, rules)
    if structural is not None:
        route = counters.route(
            source=STAGE,
            cause=ADAPTATION_CAUSE,
            scope_key=scope_key,
            state_code=StateCode.ADAPTATION_CANNOT_MEET_CONSTRAINT,
            reason=structural,
        )
        return AdaptationDecision(
            unit_id=strategy.unit_id,
            destination=decision.destination,
            outcomes=(route,),
        )

    refusal = _spend(budget, scope_key)
    if refusal is not None:
        return AdaptationDecision(
            unit_id=strategy.unit_id,
            destination=decision.destination,
            outcomes=(refusal,),
        )

    answer = _answer(
        transport,
        _request(strategy=strategy, decision=decision, rules=rules, contract=contract),
    )
    defect = None if answer is None else _defect(answer, strategy, rules)
    if answer is None or defect is not None:
        return AdaptationDecision(
            unit_id=strategy.unit_id,
            destination=decision.destination,
            outcomes=(
                OutcomeRecord(
                    outcome=ArpOutcome.SKIP,
                    state_code=StateCode.PLAN_GENERATION_FAILED,
                    scope=OutcomeScope.DESTINATION,
                    scope_key=scope_key,
                    reason=defect
                    or "the adaptation call produced no answer this stage may read",
                ),
            ),
            calls=1,
        )
    return AdaptationDecision(
        unit_id=strategy.unit_id,
        destination=decision.destination,
        plan=_plan(
            strategy=strategy,
            selection=selection,
            decision=decision,
            rules=rules,
            contract=contract,
            boundary=boundary,
            core=core,
            assets=assets,
            answer=answer,
            attempt=attempt,
        ),
        calls=1,
    )


# ===========================================================================
# The code rules (§3 Pre and Post)
# ===========================================================================


def uncarried_moves(
    plan: ExecutablePlan, strategy: EditorialStrategy
) -> tuple[int, ...]:
    """The moves of the reader path no segment carries (§3, Post).

    Public because S-11 asks the same question of the approved plan: the
    post-condition S-10 builds to is the invariant V-P01 checks, and two
    spellings of it would eventually disagree.
    """

    carried = plan.carried_moves
    return tuple(
        index
        for index in range(1, len(strategy.reader_path) + 1)
        if index not in carried
    )


def citations_from_core(
    strategy: EditorialStrategy,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    assets: Sequence[Asset] = (),
) -> tuple[str, ...]:
    """The sources a plan may cite: the ones under what the strategy rests on.

    "Citations come only from the core" (§3, Post), computed rather than asked
    for: the strategy's own references resolve to usable evidence claims —
    directly, through the readings it rests on, or through an asset that rests
    on them — and a claim's ``source_refs`` are the sources behind it. Nothing a
    model proposed can enter, which is what makes the post-condition a property
    of the construction rather than a rule applied afterwards.

    The result is never empty for entities that describe one run: an admissible
    interpretation cites at least one usable claim (E-08) and every claim cites
    at least one source (E-03), so a strategy whose thesis rests on an
    admissible reading always reaches one.
    """

    claims = {claim.evidence_claim_id: claim for claim in core.usable_claims}
    named: set[str] = set(strategy.focal_subject.refs)
    named.update(strategy.opening.refs)
    for move in strategy.reader_path:
        named.update(move.refs)
    named.add(strategy.leading_material_ref)
    for identity in strategy.interpretation_refs:
        member = boundary.member(identity)
        if member is not None and member.admissible:
            named.update(member.support_refs)
    for asset in assets:
        if asset.asset_id in named:
            named.update(asset.refs)
    sources: set[str] = set()
    for identity in named:
        claim = claims.get(identity)
        if claim is not None:
            sources.update(claim.source_refs)
    return tuple(sorted(sources))


def _precondition(
    *,
    strategy: EditorialStrategy,
    selection: StrategySelection,
    decision: DestinationDecision,
    rules: DestinationRules,
    contract: AdaptationContract,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
) -> None:
    """§3's Pre column, and the entities that have to describe one thing.

    "StrategySelection has a chosen strategy" is the whole precondition Step 2
    states, and the rest is the same identity check every destination-scope
    stage makes: a selection, a decision and a set of destination rules that
    disagree about which surface they are for cannot all be right, and adapting
    against the wrong one is not a state §6.2 has an outcome for.
    """

    if selection.chosen is None:
        raise PlanError(
            f"{selection.selection_id} chose no strategy and reached {STAGE}; §3 "
            "Pre asks for a chosen one, and S-09 already routed a selection that "
            "has none"
        )
    if selection.chosen != strategy.strategy_id:
        raise PlanError(
            f"{selection.selection_id} chose {selection.chosen} and "
            f"{strategy.strategy_id} reached {STAGE}; a plan adapts the strategy "
            "the selection chose, and adapting another is the choice S-09 made "
            "being taken again here"
        )
    if selection.unit_id != strategy.unit_id or (
        selection.destination is not strategy.destination
    ):
        raise PlanError(
            f"{selection.selection_id} was made for "
            f"{selection.unit_id}/{selection.destination.value} and "
            f"{strategy.strategy_id} belongs to "
            f"{strategy.unit_id}/{strategy.destination.value}; a selection and "
            "the strategy it chose are one destination's"
        )
    if decision.unit_id != strategy.unit_id:
        raise PlanError(
            f"the destination decision {decision.destination_decision_id} was "
            f"made for {decision.unit_id!r} and reached {STAGE} for "
            f"{strategy.unit_id!r}; a plan is adapted inside its own unit"
        )
    if decision.destination is not strategy.destination:
        raise PlanError(
            f"{decision.destination_decision_id} decides "
            f"{decision.destination.value} and {strategy.strategy_id} was written "
            f"for {strategy.destination.value}; the mode and the dependencies a "
            "plan carries are its own destination's"
        )
    if decision.eligibility is not Eligibility.ELIGIBLE or decision.mode is None:
        raise PlanError(
            f"{decision.destination_decision_id} is "
            f"{decision.eligibility.value} with mode {decision.mode!r} and "
            f"reached {STAGE}; a plan carries E-12's mode, and a destination "
            "S-07 excluded has none"
        )
    if rules.destination is not strategy.destination:
        raise PlanError(
            f"the rules offered are {rules.destination.value}'s and "
            f"{strategy.strategy_id} is {strategy.destination.value}'s; K-DST "
            "records apply per destination, and another surface's rules adapt "
            "nothing here"
        )
    if rules.hashtags is HashtagPolicy.REQUIRED and not contract.hashtags:
        raise PlanError(
            f"{rules.destination.value} requires hashtags and the contract "
            "offers none; the policy is the destination's and the tags are the "
            "client's, so a plan here could only be made by inventing the "
            "client's words — which is a setup conflict and not a state §6.2 "
            "has an outcome for"
        )
    if boundary.core_ref != (core.core_id, core.version):
        raise PlanError(
            f"{strategy.strategy_id} reached {STAGE} with a boundary over "
            f"{boundary.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); the citations are computed "
            "through both, and two that describe different material cannot both "
            "be right"
        )
    if strategy.boundary_ref[0] != boundary.boundary_id:
        raise PlanError(
            f"{strategy.strategy_id} was written against boundary "
            f"{strategy.boundary_ref[0]!r} and reached {STAGE} with "
            f"{boundary.boundary_id!r}; a plan is adapted inside its own unit's "
            "boundary"
        )
    if strategy.boundary_ref[1] > boundary.version:
        raise PlanError(
            f"{strategy.strategy_id} was written against boundary version "
            f"{strategy.boundary_ref[1]} and reached {STAGE} with version "
            f"{boundary.version}; a version only ever moves forward, and an "
            "adaptation made against an older snapshot than the strategy is the "
            "drift patch R2's versioned references exist to prevent"
        )


def _structural_conflict(
    strategy: EditorialStrategy, rules: DestinationRules
) -> Optional[str]:
    """§3's ARP: does the reader path fit the format at all?

    One question, and it is arithmetic: a surface that counts its segments
    cannot carry more moves than it has segments, because every move needs one
    and a segment carries at least one move. Where the surface counts no
    segments — an article's paragraphs are not a countable format — nothing
    here can fail, and the length is V-P04's to compare.
    """

    capacity = rules.segment_capacity
    moves = len(strategy.reader_path)
    if capacity is None or moves <= capacity:
        return None
    return (
        f"the reader path has {moves} moves and {rules.destination.value} carries "
        f"{capacity} segment(s) in this format; every move is carried by at least "
        "one segment, so a path longer than the format is an adaptation that "
        "cannot be made rather than one that was made badly"
    )


def _defect(
    answer: SegmentationAnswer,
    strategy: EditorialStrategy,
    rules: DestinationRules,
) -> Optional[str]:
    """Why this answer is not a segmentation, or ``None`` when it is one.

    Every rule the call was given, checked against what came back. An answer
    that left a move uncarried or overran the format has not produced a weaker
    plan: §3's Post column is what a plan *is*, so what came back is not one,
    and the state is the machinery's rather than the material's.
    """

    if not answer.segments:
        return "the adaptation call returned no segment; a plan is its segments"
    empty = [segment.name for segment in answer.segments if not segment.moves]
    if empty:
        return (
            "the segment(s) "
            + ", ".join(sorted(empty))
            + " carry no move; a segment is what carries the reader path, and "
            "one that carries nothing is surface added to the strategy"
        )
    moves = len(strategy.reader_path)
    carried = {
        index for segment in answer.segments for index in segment.moves
    }
    outside = sorted(index for index in carried if index < 1 or index > moves)
    if outside:
        return (
            "the segmentation carries move(s) "
            + ", ".join(str(index) for index in outside)
            + f", and the reader path has {moves}; a segment cannot carry a move "
            "the strategy did not decide"
        )
    missing = sorted(set(range(1, moves + 1)) - carried)
    if missing:
        return (
            "the segmentation leaves move(s) "
            + ", ".join(str(index) for index in missing)
            + " uncarried; §3's Post column is that every move of the reader path "
            "is carried by at least one segment"
        )
    capacity = rules.segment_capacity
    if capacity is not None and len(answer.segments) > capacity:
        return (
            f"the segmentation has {len(answer.segments)} segments and "
            f"{rules.destination.value} carries {capacity} in this format"
        )
    if rules.length.unit is LengthUnit.SLIDES and not rules.length.contains(
        len(answer.segments)
    ):
        return (
            f"the segmentation has {len(answer.segments)} segments and the length "
            f"target runs from {rules.length.minimum} to {rules.length.maximum} "
            f"{rules.length.unit.value}; both ends of the range are the format"
        )
    takes_subheadings = rules.format is PlanFormat.ARTICLE
    if takes_subheadings and answer.subheadings is None:
        return (
            f"the segmentation states no subheadings plan for an "
            f"{rules.format.value}; Step 1 §4 requires the field for article "
            "formats, and 'no subheadings' is a plan stated as one"
        )
    if not takes_subheadings and answer.subheadings is not None:
        return (
            f"the segmentation states a subheadings plan for a "
            f"{rules.format.value}, which does not carry subheadings"
        )
    return None


def _plan(
    *,
    strategy: EditorialStrategy,
    selection: StrategySelection,
    decision: DestinationDecision,
    rules: DestinationRules,
    contract: AdaptationContract,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    assets: Sequence[Asset],
    answer: SegmentationAnswer,
    attempt: int,
) -> ExecutablePlan:
    """The draft: the model's two fields, and everything else from the records."""

    assert decision.mode is not None  # the precondition refused an absent mode
    return ExecutablePlan(
        plan_id=plan_id(selection.candidate_set_id),
        version=DRAFT_VERSION,
        unit_id=strategy.unit_id,
        destination=strategy.destination,
        mode=decision.mode,
        strategy_ref=strategy.strategy_id,
        format=rules.format,
        length_target=rules.length,
        first_line_mechanics=answer.first_line_mechanics,
        segments=tuple(
            Segment(
                name=segment.name,
                purpose=segment.purpose,
                move_indices=tuple(dict.fromkeys(segment.moves)),
            )
            for segment in answer.segments
        ),
        citations=citations_from_core(strategy, boundary, core, assets),
        voice_brief_ref=contract.voice_brief_ref,
        forbidden=contract.forbidden,
        fixed_slots=contract.fixed_slots,
        stage_of_version=PlanStage.DRAFT,
        attempt=attempt,
        subheadings=answer.subheadings,
        hashtags=Hashtags(
            policy=rules.hashtags,
            tags=(
                ()
                if rules.hashtags is HashtagPolicy.FORBIDDEN
                else tuple(contract.hashtags)
            ),
        ),
        cross_destination_link=_link(strategy, decision),
        constraints=_constraints(rules, contract),
    )


def _link(
    strategy: EditorialStrategy, decision: DestinationDecision
) -> Optional[CrossDestinationLink]:
    """The conditional cross-destination link, by code (§3, Decider; R-2).

    The link follows the publication dependency E-12 recorded, and only that:
    a target the unit will never publish is already **out** of them — S-07 puts
    it in ``dropped_dependencies`` instead, and E-12 refuses a target that is in
    both — so a plan here can never promise a text that will not exist.

    What the link promises is the reading the thesis rests on, because that is
    what a sibling destination's text can be said to carry. The plan still
    delivers its promise without it (R-2): the link is an addition to a text
    that is whole, and there is no field here that could make it otherwise.
    """

    if not decision.publication_dependencies:
        return None
    return CrossDestinationLink(
        target=decision.publication_dependencies[0].target,
        interpretation_ref=strategy.editorial_thesis.interpretation_refs[0],
    )


def _constraints(
    rules: DestinationRules, contract: AdaptationContract
) -> tuple[AppliedConstraint, ...]:
    """§3's Trace: which constraints were applied, from which tier."""

    applied = [
        AppliedConstraint(
            rule_ref=rule.rule_id,
            tier=rule.tier,
            detail=rule.text,
            knowledge=rule.knowledge,
        )
        for rule in rules.rules
    ]
    applied.extend(
        AppliedConstraint(
            rule_ref=slot.rule_ref,
            tier=KnowledgeTier.APPROVED_CLIENT_RULE,
            detail=f"{slot.name} is fixed at {slot.value!r} by the contract",
        )
        for slot in contract.fixed_slots
    )
    return tuple(applied)


# ===========================================================================
# Requests and answers
# ===========================================================================


def _request(
    *,
    strategy: EditorialStrategy,
    decision: DestinationDecision,
    rules: DestinationRules,
    contract: AdaptationContract,
) -> str:
    """What the one call sees: the decided strategy, and the surface.

    The strategy arrives as it is, with no field for a revision of it, and the
    answer has none either — :class:`SegmentationAnswer` holds segments, a
    first line and a subheadings plan, and nothing that could carry a changed
    thesis back. The citations, the hashtags and the link are absent because
    code decides them; showing them would invite an answer about them.
    """

    return json.dumps({
        "destination": rules.destination.value,
        "mode": None if decision.mode is None else decision.mode.value,
        "format": rules.format.value,
        "length_target": rules.length.as_entity(),
        "segment_capacity": rules.segment_capacity,
        "takes_subheadings": rules.format is PlanFormat.ARTICLE,
        "strategy": {
            "strategy_id": strategy.strategy_id,
            "editorial_job": strategy.editorial_job,
            "angle": strategy.angle,
            "thesis": strategy.editorial_thesis.text,
            "focal_subject": strategy.focal_subject.text,
            "leading_material_ref": strategy.leading_material_ref,
            "reader_path": [
                {"index": index, **move.as_entity()}
                for index, move in enumerate(strategy.reader_path, 1)
            ],
            "opening": strategy.opening.as_entity(),
            "reveal": strategy.reveal.as_entity(),
            "concession": strategy.concession.as_entity(),
            "ending_intention": strategy.ending_intention,
        },
        "platform_rules": [
            {"rule_id": rule.rule_id, "text": rule.text, "tier": rule.tier.value}
            for rule in rules.rules
        ],
        "forbidden": [
            {"kind": item.kind.value, "value": item.value, "rule_ref": item.rule_ref}
            for item in contract.forbidden
        ],
        "fixed_slots": [slot.as_entity() for slot in contract.fixed_slots],
    })


def _answer(
    transport: SegmentationTransport, request: str
) -> Optional[SegmentationAnswer]:
    """One call, parsed, or ``None``. Never the provider's own text."""

    try:
        raw = transport.complete(
            instructions=SEGMENTATION_INSTRUCTIONS, request=request
        )
    except Exception:  # noqa: BLE001 — sanitized, never the provider's text
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return SegmentationAnswer.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return None


def _spend(budget: Optional[CallBudget], scope_key: str) -> Optional[OutcomeRecord]:
    if budget is None:
        return None
    return budget.spend(scope=OutcomeScope.DESTINATION, scope_key=scope_key)
