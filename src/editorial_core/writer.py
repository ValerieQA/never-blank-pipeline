"""S-12 · Writer: prose that executes the approved plan and decides nothing.

The destination-scope stage that turns one approved E-14 into one E-15. Step 2
§3 gives it the execution and forbids it the decision: "execute the approved
plan in prose. **Decides nothing editorial.** If the plan cannot be executed
honestly, it says so instead of improvising".

The plan is the only planning input
-----------------------------------
§3's Inputs column: "approved ``E-14`` (required, and **the only planning
input**); the core items the plan references (resolved by code); exemplars;
voice brief; ``forbidden``". And its Not-an-input row, which is the more
load-bearing half: "the boundary's full lists beyond what the plan references;
sibling texts; labels; the raw research".

Both halves are enforced by construction rather than by a rule this stage
remembers. :func:`_request` builds what the call sees from a closed set of
records — the plan, the strategy it references, :func:`referenced_core`'s
resolution of the items it cites, its exemplars, its forbidden list and the
voice document it approved — and there is no parameter anywhere in this module
that a sibling text, a label or a research artifact could arrive through.
:class:`WriterInputs` records what was sent, down to the digest of the exact
request string, so the property is auditable after the fact and not only
assertable before it: ``withheld`` names the four classes §3 keeps out, and the
digest is what a reader checks that claim against.

``E-13`` is reached through the plan, not beside it. E-14 copies no E-13 field
(§4, S-10), so the thesis, the reader path and the ending intention arrive by
resolving ``strategy_ref`` — the same mechanism as the core items, applied to
the record the plan names. Nothing else from the planning layer is resolved.

Knowledge reaches the Writer only through the plan (I-11), which is why this
module loads no check record, reads no register and takes no knowledge
argument: the tiers were applied at S-10 and S-11, and the ``forbidden`` list
the plan carries is their result.

Refusal is a route, not a worse text
------------------------------------
§3's ARP column: "``plan_holds = false`` → ``REPLAN`` → S-08 (consumes
``L_strategy``). The Writer does not retry itself." So a refusal produces no
E-15 at all — §3's Post column is "on ``plan_holds = false``, no text is
accepted" — and :class:`Text` cannot express one: a text is the executed plan,
and a body written against a plan the Writer has just said does not hold is the
improvisation the signal exists to prevent.

The three ways a destination leaves this stage are kept apart, because a reader
of the skip rate is owed the difference: a refusal carries a
:class:`WriterSignal` with ``plan_holds = false`` and its reason and routes to
S-08; a call nobody could read carries **no signal at all** and ends the
destination under ``text_generation_failed``; a budget that refused before the
call carries neither and ends it under ``budget_exhausted``. "The Writer said
the plan does not hold" and "the Writer said nothing" are never the same
record.

An approval that no longer holds opens nothing (F-4)
----------------------------------------------------
§5.4's fix F-4 makes the boundary version part of the precondition: "PlanVerdict
records the boundary version. The S-12 precondition requires it to equal the
current version." :func:`approval_holds` is that comparison, and it is S-11's
own — imported rather than written again, because two spellings of "does this
approval still stand" would eventually disagree, and the stale one would be the
one still saying yes. The boundary entity reaches the precondition and never the
call: ``_request`` has no parameter for it, so the lists §3 withholds cannot
travel with the version this stage checks.

The same holds for the barrier. §0.2 blocks S-12 on B1, so a :class:`BarrierRound`
that did not pass — including the round nobody could answer — is refused here
rather than treated as a barrier that was not reached.

**Production safety.** One model call per write, no external call, and nothing
calls this stage: the run harness still executes S-12 as the SL-1 pass-through,
and wiring the stages of SL-6 into it is a later slice. The edit (§5.3, S-13 →
S-12 on the same approved plan, consuming ``L_edit``) arrives with S-13's
findings, which do not exist yet; it belongs to the slice that produces them.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.2
(barrier B1), §0.3, §3 (S-12), §5.3 and §5.4 (F-4);
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §5 (E-15) and §6
(I-03, I-06, I-08, I-11);
``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §2.2, §2.3,
§2.5.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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
from src.editorial_core.candidate_strategies import EditorialStrategy
from src.editorial_core.destinations import DESTINATIONS_DIRECTORY, Destination
from src.editorial_core.editorial_units import UNITS_DIRECTORY
from src.editorial_core.evidence_core import (
    EvidenceClaim,
    EvidenceCore,
    SourceObservation,
)
from src.editorial_core.executable_plan import (
    ExecutablePlan,
    PlanFormat,
    PlanStage,
)
from src.editorial_core.interpretation_boundary import InterpretationBoundary
from src.editorial_core.plan_check import BarrierRound, PlanVerdict, approval_holds
from src.editorial_core.signal_selection import CallBudget
from src.research.evidence import NormalizedSource, SourceLocatorKind
from src.run.run_manifest import EntityIndexEntry
from src.run.run_workspace import RunWorkspace

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-12"

#: The entity it is the sole producer of (§3, Outputs).
TEXT_ENTITY_TYPE: Final[str] = "E-15"

#: Where a text lives inside the destination's directory (§2.2).
TEXTS_DIRECTORY: Final[str] = "texts"

#: The counter the one route out spends (§0.3).
STRATEGY_COUNTER: Final[str] = "L_strategy"

#: The route this stage takes, as the topology registry declares it.
PLAN_DOES_NOT_HOLD_CAUSE: Final[str] = "plan_does_not_hold"

#: §2.5: "one ID per approved plan. ``+1`` per edit (S-12)". The first write is
#: v1; the edit that produces v2 arrives with the S-13 findings that ask for it.
FIRST_VERSION: Final[int] = 1

#: The serialization ``content_digest`` is taken over. Bump it only when the
#: meaning of the payload changes: V-T05 compares digests across runs, and a
#: digest whose recipe changed silently would read every prior text as new.
CONTENT_SERIALIZATION: Final[str] = "editorial-text-json-v1"

#: What §3's Not-an-input row keeps out of the call, named so that the trace
#: states the property rather than leaving a reader to infer it from an absence.
#: Recorded on every :class:`WriterInputs` beside the digest of what *was* sent,
#: because "no sibling text was shown" is only checkable against the request it
#: is claimed about.
WITHHELD_INPUTS: Final[tuple[str, ...]] = (
    "sibling_texts",
    "labels",
    "raw_research",
    "boundary_beyond_the_plan",
)


class WriterError(RuntimeError):
    """S-12 was asked to write something its contract cannot write."""


# ===========================================================================
# E-15 · Text
# ===========================================================================


@dataclass(frozen=True, slots=True)
class WriterSignal:
    """E-15's ``writer_signal``: "``plan_holds`` bool + reason".

    The reason belongs to the refusal and to nothing else. A plan that holds
    needs no explanation — the text is the explanation — and a field that could
    carry one would be the Writer commenting on a decision it did not make.
    A refusal without a reason is refused here rather than accepted silently,
    which is why :func:`_signal` writes one when the answer carried none: the
    route this signal takes spends ``L_strategy``, and a destination sent back
    to S-08 with no reason recorded is an attempt nobody can learn from.
    """

    plan_holds: bool
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.plan_holds and not (self.reason or "").strip():
            raise WriterError(
                "the writer signal says the plan does not hold and states no "
                "reason; the refusal is what routes the destination back to "
                "S-08, and one that says nothing routes it on no finding"
            )
        if self.plan_holds and self.reason is not None:
            raise WriterError(
                f"the writer signal says the plan holds and carries the reason "
                f"{self.reason!r}; a plan that holds is executed, and a note "
                "about it is the Writer deciding something editorial"
            )

    def as_entity(self) -> dict[str, Any]:
        return {"plan_holds": self.plan_holds, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class TextSegment:
    """One entry of E-15's ``segments``: "ordered text parts".

    ``name`` is the plan segment this part realizes, spelled exactly as the plan
    spells it. Step 1 §5 makes the alignment the rule — "aligned to the plan's
    segments" — and naming rather than numbering is what makes it checkable: a
    part that carries a name no plan segment has is not a shorter text, it is a
    part of some other plan.
    """

    name: str
    text: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.text.strip():
            raise WriterError(
                "a text part names the plan segment it executes and carries the "
                "prose that executes it; one with neither executes nothing"
            )

    def as_entity(self) -> dict[str, str]:
        return {"name": self.name, "text": self.text}


@dataclass(frozen=True, slots=True)
class WriterInputs:
    """Exactly what the one call was given (§3, Inputs and Not an input).

    The acceptance evidence of this slice is a trace that proves the Writer
    received no sibling text, no label and no raw research, and a record that
    only listed what *was* sent would prove it by omission — which is the same
    proof a request that quietly grew a fifth input would still pass. So both
    halves are recorded: the refs that went in, and ``withheld``, the classes §3
    keeps out, against ``request_digest``, the digest of the exact string the
    transport was handed. A reader with the request can verify all three; a
    reader without it can still see which claim was made.
    """

    plan_ref: tuple[str, int]
    strategy_ref: str
    core_item_refs: tuple[str, ...]
    exemplar_refs: tuple[str, ...]
    voice_brief_ref: str
    forbidden_refs: tuple[str, ...]
    request_digest: str

    def __post_init__(self) -> None:
        if not self.strategy_ref.strip() or not self.voice_brief_ref.strip():
            raise WriterError(
                "the writer's inputs name no strategy or no voice document "
                "version; both reach the call through the plan, and a record of "
                "what was sent that omits them records nothing checkable"
            )
        if not self.core_item_refs:
            raise WriterError(
                "the writer's inputs resolve no core item; I-03 gives the facts "
                "to the core, and a call handed none could only invent them"
            )
        if not self.request_digest.startswith("sha256:"):
            raise WriterError(
                f"the writer's inputs record {self.request_digest!r} as the "
                "request digest; the claim about what was withheld is checked "
                "against the request, and a digest in no known form checks nothing"
            )

    @property
    def withheld(self) -> tuple[str, ...]:
        """The classes §3 keeps out of the call, as the trace states them."""

        return WITHHELD_INPUTS

    def as_entity(self) -> dict[str, Any]:
        plan_identity, plan_version = self.plan_ref
        return {
            "plan_ref": {"plan_id": plan_identity, "version": plan_version},
            "strategy_ref": self.strategy_ref,
            "core_item_refs": list(self.core_item_refs),
            "exemplar_refs": list(self.exemplar_refs),
            "voice_brief_ref": self.voice_brief_ref,
            "forbidden_refs": list(self.forbidden_refs),
            "withheld": list(self.withheld),
            "request_digest": self.request_digest,
        }


@dataclass(frozen=True, slots=True)
class Text:
    """``E-15``: one approved plan, executed in prose (Step 1 §5).

    ``body`` and ``content_digest`` are **derived** and not stored: the body is
    the parts in order, and the digest is taken over the parts, the title, the
    dek and the links. Step 1 §5 lists all four as fields, and a record that
    held the derived two as well would be a record whose body could disagree
    with its own segments after an edit — which is the state V-T05 and
    idempotency would then be reading.

    ``writer_signal`` is present and always holds: a text is what exists when
    the plan holds, and the refusal is a :class:`WriterDecision` with no text at
    all (§3, Post).

    ``supersedes`` is §3's "edit lineage". §2.5 gives a text "+1 per edit", and
    the version above the first supersedes the one before it: a v2 that named no
    predecessor would be an edit of nothing, and the version — which every
    TextVerdict is written against — would say an edit happened that no record
    can be read back to.
    """

    text_id: str
    version: int
    unit_id: str
    destination: Destination
    plan_ref: tuple[str, int]
    segments: tuple[TextSegment, ...]
    writer_signal: WriterSignal
    inputs: WriterInputs
    links: tuple[str, ...] = ()
    title: Optional[str] = None
    dek: Optional[str] = None
    #: The version this one edits (§2.5). ``None`` on the first version.
    supersedes: Optional[tuple[str, int]] = None

    def __post_init__(self) -> None:
        if not self.text_id.strip() or not self.unit_id.strip():
            raise WriterError(
                "a text is identified by its own ID and the unit whose plan it "
                "executes"
            )
        if self.version < 1:
            raise WriterError(
                f"{self.text_id} is at version {self.version}; §2.5 makes the "
                f"first text v{FIRST_VERSION} and every edit the version after it"
            )
        if not self.segments:
            raise WriterError(
                f"{self.text_id} has no part; a text executes the plan's segments, "
                "and one that executes none is not a shorter text"
            )
        if not self.writer_signal.plan_holds:
            raise WriterError(
                f"{self.text_id} carries a writer signal that the plan does not "
                "hold; §3's Post column is that no text is accepted then, and a "
                "body written against a refused plan is the improvisation the "
                "signal exists to prevent"
            )
        named = [segment.name for segment in self.segments]
        repeated = sorted({item for item in named if named.count(item) > 1})
        if repeated:
            raise WriterError(
                f"{self.text_id} executes "
                + ", ".join(repeated)
                + " twice; one plan segment is executed by one part, and two "
                "parts under one name align to neither"
            )
        self._version_states_its_lineage()

    def _version_states_its_lineage(self) -> None:
        if self.version == FIRST_VERSION:
            if self.supersedes is not None:
                raise WriterError(
                    f"{self.text_id} is v{self.version} and supersedes "
                    f"{self.supersedes!r}; the first version is where a text "
                    "starts, and one that edits something was not the first"
                )
            return
        if self.supersedes != (self.text_id, self.version - 1):
            raise WriterError(
                f"{self.text_id} is v{self.version} and supersedes "
                f"{self.supersedes!r}; §2.5 makes an edit the version after the "
                "one it edits, and a version that names another text's — or "
                "none — is an edit nobody can read back to"
            )

    @property
    def body(self) -> str:
        """E-15's ``body``: the parts in the plan's order, and nothing else."""

        return "\n\n".join(segment.text for segment in self.segments)

    @property
    def content_digest(self) -> str:
        """E-15's ``content_digest``: "sha256", "used by idempotency and V-T05".

        Taken over what the text says — the title, the dek, the ordered parts
        and the links — and not over the record around it. A digest that moved
        with the plan reference or the version would make every edit of an
        unchanged paragraph a different text, which is the comparison V-T05 is.
        """

        payload = json.dumps(
            {
                "serialization": CONTENT_SERIALIZATION,
                "title": self.title,
                "dek": self.dek,
                "segments": [segment.as_entity() for segment in self.segments],
                "links": list(self.links),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def text_ref(self) -> tuple[str, int]:
        """This exact version, as a TextVerdict will hold it."""

        return (self.text_id, self.version)

    def as_entity(self) -> dict[str, Any]:
        """The E-15 body, written to ``texts/<txt_id>.v<n>.json`` (§2.2)."""

        plan_identity, plan_version = self.plan_ref
        return {
            "entity_type": TEXT_ENTITY_TYPE,
            "entity_id": self.text_id,
            "text_id": self.text_id,
            "version": self.version,
            "unit_id": self.unit_id,
            "destination": self.destination.value,
            "plan_ref": {"plan_id": plan_identity, "version": plan_version},
            "title": self.title,
            "dek": self.dek,
            "body": self.body,
            "segments": [segment.as_entity() for segment in self.segments],
            "links": list(self.links),
            "writer_signal": self.writer_signal.as_entity(),
            "content_digest": self.content_digest,
            "supersedes": (
                None
                if self.supersedes is None
                else {"text_id": self.supersedes[0], "version": self.supersedes[1]}
            ),
            "inputs": self.inputs.as_entity(),
        }


@dataclass(frozen=True, slots=True)
class WriterDecision:
    """What one S-12 execution made of one approved plan.

    Three absences, and they are not the same absence. ``text`` and ``signal``
    are both present when the plan was executed; ``signal`` alone is present
    when the Writer refused the plan, which is the finding that routes to S-08;
    neither is present when the call could not be made or could not be read, or
    when the budget refused before it. A caller reading ``text is None`` learns
    that nothing was written and must read ``signal`` to learn whether anybody
    said why.
    """

    unit_id: str
    destination: Destination
    text: Optional[Text] = None
    signal: Optional[WriterSignal] = None
    inputs: Optional[WriterInputs] = None
    outcomes: tuple[OutcomeRecord, ...] = ()
    #: Model calls this execution made, for the per-stage call record (§3.3).
    calls: int = 0

    @property
    def refused(self) -> bool:
        """Did the Writer read the plan and say it does not hold?

        False for a call nobody could read: that execution produced no judgment
        about the plan, and reading it as one would charge the machinery's
        failure to the plan (I-09).
        """

        return self.signal is not None and not self.signal.plan_holds


# ===========================================================================
# What the stage is handed
# ===========================================================================


@dataclass(frozen=True, slots=True)
class VoiceBrief:
    """The client voice document, at the version the plan references (§3, Inputs).

    ``brief_ref`` is checked against ``E-14.voice_brief_ref`` before the call:
    the plan was approved against one version of the voice, and writing against
    another is a voice nobody approved reaching prose through a stage that
    decides nothing.
    """

    brief_ref: str
    text: str

    def __post_init__(self) -> None:
        if not self.brief_ref.strip():
            raise WriterError(
                "the voice brief carries no version reference; E-14 references "
                "one, and a brief that cannot be compared with it cannot be "
                "shown to be the one the plan approved"
            )
        if not self.text.strip():
            raise WriterError(
                f"the voice brief {self.brief_ref} holds no text; a voice nobody "
                "wrote down is not a constraint on prose, and a call handed an "
                "empty one would write in whatever voice it has"
            )


@dataclass(frozen=True, slots=True)
class ReferencedCore:
    """The core items the plan references, resolved by code (§3, Inputs).

    Not the core: the sources the plan cites, the usable claims behind them and
    the observations those claims rest on. What is absent is the point —
    ``research_artifact_refs``, the uncertainties, the contradictions and every
    claim the plan does not reach stay in E-04, because "the raw research" is
    §3's first Not-an-input and a stage that handed over the whole core would
    have passed it through under another name.
    """

    sources: tuple[NormalizedSource, ...]
    claims: tuple[EvidenceClaim, ...]
    observations: tuple[SourceObservation, ...]

    def __post_init__(self) -> None:
        if not self.sources or not self.claims:
            raise WriterError(
                "the plan's citations resolve to no usable claim; I-03 gives the "
                "facts to the core, and a Writer handed a citation with nothing "
                "under it can only invent what it says"
            )

    @property
    def refs(self) -> tuple[str, ...]:
        """Every item ID this resolution carries, for the trace."""

        return (
            *(source.source_id for source in self.sources),
            *(claim.evidence_claim_id for claim in self.claims),
            *(item.observation_id for item in self.observations),
        )


# ===========================================================================
# Identity and storage
# ===========================================================================


def text_id(plan_identity: str) -> str:
    """The ID of the one text of one approved plan (§2.5).

    "One ID per approved plan", derived from the plan rather than counted: an
    edit is a version of this text, and a further attempt is a further plan with
    a text ID of its own — which the workspace refuses to overwrite (P1).
    """

    if not plan_identity.strip():
        raise WriterError("a text is named for the approved plan it executes")
    return f"txt-{plan_identity}"


def texts_relative_path(unit: str, destination: Destination) -> str:
    """``units/<unit>/destinations/<dst>/texts`` (§2.2)."""

    _validate_path_component(unit, "unit_id")
    return (
        f"{UNITS_DIRECTORY}/{unit}/{DESTINATIONS_DIRECTORY}/{destination.value}/"
        f"{TEXTS_DIRECTORY}"
    )


def text_relative_path(
    unit: str, destination: Destination, identity: str, version: int
) -> str:
    """``texts/<txt_id>.v<n>.json`` (§2.2)."""

    _validate_path_component(identity, "text_id")
    if version < 1:
        raise WriterError(f"a text version is numbered from 1; got {version}")
    return f"{texts_relative_path(unit, destination)}/{identity}.v{version}.json"


def write_text(workspace: RunWorkspace, text: Text) -> EntityIndexEntry:
    """Write one text version into the run workspace, and index it.

    Through :class:`~src.run.run_workspace.RunWorkspace`, so create-once (P1)
    and §2.3 write ownership hold: ``texts/*`` belongs to S-12 and to nothing
    else, and an edit is a new version at a path of its own rather than an
    overwrite of the version a TextVerdict was written about.
    """

    return workspace.write_entity(
        stage=STAGE,
        relative_path=text_relative_path(
            text.unit_id, text.destination, text.text_id, text.version
        ),
        entity_type=TEXT_ENTITY_TYPE,
        entity_id=text.text_id,
        payload=text.as_entity(),
        version=text.version,
    )


# ===========================================================================
# The one call
# ===========================================================================


class WriterTransport(Protocol):
    """The model call S-12 makes: the plan, executed in prose."""

    def complete(self, *, instructions: str, request: str) -> str: ...


WRITER_INSTRUCTIONS = """\
You write ONE text that executes ONE already-approved plan for ONE destination.
You decide nothing.

The thesis, the focal subject, the reader path, the opening, the reveal, the
concession, the ending intention, the format, the length target, the
segmentation and the first line's mechanics are decided and are given to you as
they are. You do not change them, improve them, reorder them, add to them or
leave any of them out. You do not choose what the text links to: the run records
the links from the plan's citations.

Every fact you state comes from the core items in the request, as they are
written there. You do not add a figure, a name, a date, a source or a URL that
is not in them, and you do not state as established anything they attribute to
one source.

Return one part per plan segment, in the plan's order, each named EXACTLY as the
plan names it, carrying that segment's moves in prose.

`title` and `dek` are written only when the request asks for them, and are null
otherwise.

If the plan cannot be executed honestly — the segments cannot carry the moves at
the length the plan sets, or the core items do not support what a move asks the
reader to believe — do NOT improvise, do not repair the plan and do not write a
partial text. Return `plan_holds: false` with a `reason` naming what does not
hold, and no segments. Saying so is correct behaviour; the run re-plans.

Return ONLY one valid JSON object, no text outside it:

{"plan_holds": true, "reason": null, "title": null, "dek": null,
 "segments": [{"name": "...", "text": "..."}]}

or, when the plan cannot be executed:

{"plan_holds": false, "reason": "...", "title": null, "dek": null,
 "segments": []}
"""


class _WriterModel(BaseModel):
    """An answer is parsed strictly, or it is not an answer."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SegmentDraft(_WriterModel):
    name: str = Field(min_length=1)
    text: str = Field(min_length=1)


class WriterAnswer(_WriterModel):
    """What comes back. There is no field for a changed plan, and none for a
    link: a shape that cannot express the breach is the whole enforcement."""

    plan_holds: bool
    reason: Optional[str] = Field(default=None, min_length=1)
    title: Optional[str] = Field(default=None, min_length=1)
    dek: Optional[str] = Field(default=None, min_length=1)
    segments: tuple[SegmentDraft, ...] = ()


# ===========================================================================
# The stage
# ===========================================================================


def write_prose(
    *,
    plan: ExecutablePlan,
    verdict: PlanVerdict,
    barrier: BarrierRound,
    strategy: EditorialStrategy,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    brief: VoiceBrief,
    counters: AttemptCounterLedger,
    transport: WriterTransport,
    budget: Optional[CallBudget] = None,
) -> WriterDecision:
    """Execute one approved plan in prose: one call, one text or one route.

    Returns a :class:`WriterDecision` in every case the protocol has an outcome
    for, including the refusal that sends the destination back to S-08: that is
    a recorded ``REPLAN`` — or the destination's ``SKIP`` once ``L_strategy`` is
    gone — and not an exception, for the reason S-00 through S-11 give. The
    stage's preconditions still raise.

    The preconditions run **before** the budget is spent. A plan that is not
    approved, an approval the current boundary version has taken away (F-4) and
    a barrier that has not passed are all states in which no text may exist at
    all, and paying for a call to discover it would spend the run's allowance on
    prose nobody may keep.
    """

    _precondition(
        plan=plan,
        verdict=verdict,
        barrier=barrier,
        strategy=strategy,
        boundary=boundary,
        core=core,
        brief=brief,
    )
    scope_key = plan.scope_key
    referenced = referenced_core(plan, strategy, core)

    refusal = _spend(budget, scope_key)
    if refusal is not None:
        return WriterDecision(
            unit_id=plan.unit_id,
            destination=plan.destination,
            outcomes=(refusal,),
        )

    request = _request(
        plan=plan, strategy=strategy, referenced=referenced, brief=brief
    )
    inputs = _inputs(plan=plan, referenced=referenced, request=request)
    answer = _answer(transport, request)
    if answer is None:
        return _unreadable(
            plan=plan,
            inputs=inputs,
            reason="the write call produced no text this stage may read",
        )
    if not answer.plan_holds:
        signal = _signal(answer)
        return WriterDecision(
            unit_id=plan.unit_id,
            destination=plan.destination,
            signal=signal,
            inputs=inputs,
            outcomes=(
                counters.route(
                    source=STAGE,
                    cause=PLAN_DOES_NOT_HOLD_CAUSE,
                    scope_key=scope_key,
                    state_code=StateCode.PLAN_DOES_NOT_HOLD,
                    reason=signal.reason,
                ),
            ),
            calls=1,
        )
    defect = _defect(answer, plan)
    if defect is not None:
        return _unreadable(plan=plan, inputs=inputs, reason=defect)
    return WriterDecision(
        unit_id=plan.unit_id,
        destination=plan.destination,
        text=_text(plan=plan, referenced=referenced, answer=answer, inputs=inputs),
        signal=WriterSignal(plan_holds=True),
        inputs=inputs,
        calls=1,
    )


# ===========================================================================
# The code rules (§3 Pre and Inputs)
# ===========================================================================


def referenced_core(
    plan: ExecutablePlan, strategy: EditorialStrategy, core: EvidenceCore
) -> ReferencedCore:
    """The core items the plan references (§3, Inputs: "resolved by code").

    Two paths reach an item, and both are the plan's own. A claim the strategy
    names — in the focal subject, the opening, a move or the leading material —
    is referenced through ``strategy_ref``. A claim under a source the plan
    cites is referenced through ``citations``, which is how the readings the
    thesis rests on reach the Writer without the boundary travelling with them:
    S-10 computed the citations from those readings' support, so the claims are
    recoverable from the citation list alone.

    Only usable claims (E-03's usability rule), and only the observations those
    claims cite. A rejected or unassessed claim is not material a text may rest
    on, and an observation no cited claim names is core the plan did not reach.
    """

    known = {source.source_id: source for source in core.sources}
    missing = sorted(set(plan.citations) - set(known))
    if missing:
        raise WriterError(
            f"{plan.plan_id} cites "
            + ", ".join(missing)
            + f", which the core {core.core_id!r} v{core.version} does not hold; "
            "a citation that resolves to nothing is a fact with no provenance "
            "(I-03), and resolving it is this stage's precondition rather than "
            "the Writer's problem"
        )
    named = {
        strategy.leading_material_ref,
        *strategy.focal_subject.refs,
        *strategy.opening.refs,
        *(ref for move in strategy.reader_path for ref in move.refs),
    }
    cited = set(plan.citations)
    claims = tuple(
        claim
        for claim in core.usable_claims
        if claim.evidence_claim_id in named or cited.intersection(claim.source_refs)
    )
    observed = {ref for claim in claims for ref in claim.observation_refs}
    return ReferencedCore(
        sources=tuple(known[identity] for identity in plan.citations),
        claims=claims,
        observations=tuple(
            item for item in core.observations if item.observation_id in observed
        ),
    )


def resolved_links(referenced: ReferencedCore) -> tuple[str, ...]:
    """E-15's ``links``, computed rather than asked for (Step 1 §5).

    "Each is a source in the core or a canonical URL of a sibling destination":
    the first half is these, the URL locator of every source the plan cites, in
    the plan's citation order. The second half is not written here — a sibling's
    canonical URL exists only once that sibling was published, and §3 (R-2) binds
    the cross-destination link at S-14 or omits it.

    Computed by code for the same reason S-10 computes the citations: a link the
    Writer could type is a link the Writer could invent, and V-T04 can then only
    fail on something this stage did not produce. A source located by an
    identifier rather than a URL contributes none, because there is nothing to
    link to.
    """

    links: list[str] = []
    for source in referenced.sources:
        if (
            source.locator.kind is SourceLocatorKind.URL
            and source.locator.value not in links
        ):
            links.append(source.locator.value)
    return tuple(links)


def _precondition(
    *,
    plan: ExecutablePlan,
    verdict: PlanVerdict,
    barrier: BarrierRound,
    strategy: EditorialStrategy,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    brief: VoiceBrief,
) -> None:
    """§3's Pre column: an approved plan, a passed barrier, a current approval.

    Everything here fails closed. Each of these states is one in which the text
    that would be written is a text no later stage could act on — S-13 checks it
    against the plan that was approved, S-14 publishes what S-13 accepted — so
    the stage refuses rather than producing prose and a state code beside it.
    """

    if plan.stage_of_version is not PlanStage.APPROVED:
        raise WriterError(
            f"{plan.plan_id} v{plan.version} is {plan.stage_of_version.value} and "
            f"reached {STAGE}; I-08 makes the approved version the gate prose "
            "opens on, and a draft is a plan whose checks have not been made"
        )
    if verdict.approved_plan_ref != plan.plan_ref:
        raise WriterError(
            f"{verdict.verdict_id} approved {verdict.approved_plan_ref!r} and "
            f"{plan.plan_ref!r} reached {STAGE}; the plan a verdict opens is the "
            "one it approved"
        )
    if verdict.unit_id != plan.unit_id or verdict.destination is not plan.destination:
        raise WriterError(
            f"{verdict.verdict_id} was made for "
            f"{verdict.unit_id}/{verdict.destination.value} and {plan.plan_id} "
            f"belongs to {plan.unit_id}/{plan.destination.value}; a verdict and "
            "the plan it approved are one destination's"
        )
    if not approval_holds(verdict, boundary):
        raise WriterError(
            f"{verdict.verdict_id} is {verdict.result.value} against boundary "
            f"{verdict.boundary_ref!r} and the current boundary is "
            f"({boundary.boundary_id!r}, {boundary.version}); F-4 makes the "
            "equality this stage's precondition, and an approval a commit has "
            "overtaken is re-established at S-11 before any prose is written"
        )
    if barrier.unit_id != plan.unit_id:
        raise WriterError(
            f"barrier round {barrier.round_index} was evaluated for "
            f"{barrier.unit_id!r} and {plan.plan_id} belongs to "
            f"{plan.unit_id!r}; B1 is one unit's barrier"
        )
    if plan.destination not in barrier.destinations:
        raise WriterError(
            f"barrier round {barrier.round_index} of {barrier.unit_id} compared "
            f"{', '.join(sorted(item.value for item in barrier.destinations))} "
            f"and {plan.destination.value} was not among them; V-P03 compares the "
            "unit's plans, and a destination it did not compare is one B1 has not "
            "passed for"
        )
    if not barrier.passed:
        raise WriterError(
            f"barrier round {barrier.round_index} of {barrier.unit_id} has not "
            f"passed and {plan.plan_id} reached {STAGE}; §0.2 is that no text is "
            "written before B1 passes, and a round nobody could answer is not a "
            "barrier that was reached"
        )
    if plan.strategy_ref != strategy.strategy_id:
        raise WriterError(
            f"{plan.plan_id} adapts {plan.strategy_ref} and "
            f"{strategy.strategy_id} reached {STAGE}; the decided fields are the "
            "ones the plan references, and another strategy's are a second "
            "editorial decision arriving as prose"
        )
    if (
        strategy.unit_id != plan.unit_id
        or strategy.destination is not plan.destination
    ):
        raise WriterError(
            f"{strategy.strategy_id} belongs to "
            f"{strategy.unit_id}/{strategy.destination.value} and {plan.plan_id} "
            f"to {plan.unit_id}/{plan.destination.value}; a plan and the strategy "
            "it adapts are one destination's"
        )
    if boundary.core_ref != (core.core_id, core.version):
        raise WriterError(
            f"{plan.plan_id} reached {STAGE} with a boundary over "
            f"{boundary.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); the approval is checked against "
            "one and the citations resolve through the other, and two that "
            "describe different material cannot both be right"
        )
    if brief.brief_ref != plan.voice_brief_ref:
        raise WriterError(
            f"{plan.plan_id} references voice document "
            f"{plan.voice_brief_ref!r} and {brief.brief_ref!r} reached {STAGE}; "
            "the plan was approved against one version of the voice, and writing "
            "against another is a voice nobody approved reaching prose"
        )


def _defect(answer: WriterAnswer, plan: ExecutablePlan) -> Optional[str]:
    """Why this answer is not the plan executed, or ``None`` when it is.

    The plan's own shape, checked against what came back, and nothing further:
    the text's facts, its phrasing, its length and its forbidden constructions
    are S-13's, and §3 puts the checks outside this stage. What is left is the
    question S-13 could not ask — whether what came back is this plan's text at
    all — and an answer that executes some other segmentation is not a weaker
    text but a state of the machinery.
    """

    if not answer.segments:
        return (
            "the write call returned no part and said the plan holds; a text "
            "executes the plan's segments, and one that executes none has "
            "neither written the plan nor refused it"
        )
    written = tuple(segment.name for segment in answer.segments)
    planned = tuple(segment.name for segment in plan.segments)
    if written != planned:
        return (
            "the text executes the parts "
            + ", ".join(written)
            + " and "
            + plan.plan_id
            + " plans "
            + ", ".join(planned)
            + "; Step 1 §5 aligns the parts to the plan's segments, in the "
            "plan's order, and a part under another name executes another plan"
        )
    takes_title = plan.format is PlanFormat.ARTICLE
    if takes_title and (answer.title is None or answer.dek is None):
        return (
            f"the text for an {plan.format.value} states no title or no dek; "
            "Step 1 §5 requires both of the article formats, and a headline the "
            "Writer left out is one a later stage would have to invent"
        )
    if not takes_title and (answer.title is not None or answer.dek is not None):
        return (
            f"the text for a {plan.format.value} states a title or a dek, which "
            "the format does not carry; a headline nobody asked for is surface "
            "the plan did not decide"
        )
    return None


def _signal(answer: WriterAnswer) -> WriterSignal:
    """The refusal, with a reason it is routed on.

    A Writer that refused the plan and named nothing is still a Writer that
    refused the plan: upgrading the answer into a text would be improvisation,
    and demoting it to "no answer" would charge the machinery for a judgment
    that was made. So the refusal stands and the missing reason is recorded as
    what it is.
    """

    return WriterSignal(
        plan_holds=False,
        reason=answer.reason
        or "the Writer refused the plan and named no reason for the refusal",
    )


def _text(
    *,
    plan: ExecutablePlan,
    referenced: ReferencedCore,
    answer: WriterAnswer,
    inputs: WriterInputs,
) -> Text:
    """The text: the call's prose, and everything else from the records."""

    return Text(
        text_id=text_id(plan.plan_id),
        version=FIRST_VERSION,
        unit_id=plan.unit_id,
        destination=plan.destination,
        plan_ref=plan.plan_ref,
        segments=tuple(
            TextSegment(name=segment.name, text=segment.text)
            for segment in answer.segments
        ),
        writer_signal=WriterSignal(plan_holds=True),
        inputs=inputs,
        links=resolved_links(referenced),
        title=answer.title,
        dek=answer.dek,
    )


def _unreadable(
    *, plan: ExecutablePlan, inputs: WriterInputs, reason: str
) -> WriterDecision:
    """One call made, and nothing this stage may read (``text_generation_failed``).

    No signal: the Writer produced no judgment about the plan, and a decision
    that recorded one would route a destination back to S-08 on a finding nobody
    made. The inputs are kept, because what the call was given is exactly what a
    reader of a failed call needs.
    """

    return WriterDecision(
        unit_id=plan.unit_id,
        destination=plan.destination,
        inputs=inputs,
        outcomes=(
            OutcomeRecord(
                outcome=ArpOutcome.SKIP,
                state_code=StateCode.TEXT_GENERATION_FAILED,
                scope=OutcomeScope.DESTINATION,
                scope_key=plan.scope_key,
                reason=reason,
            ),
        ),
        calls=1,
    )


# ===========================================================================
# Requests and answers
# ===========================================================================


def _request(
    *,
    plan: ExecutablePlan,
    strategy: EditorialStrategy,
    referenced: ReferencedCore,
    brief: VoiceBrief,
) -> str:
    """What the one call sees: the approved plan, and what it references.

    Seven blocks and no eighth. The plan and the strategy it adapts arrive as
    they are, with no field for a revision of them; the core items are
    :func:`referenced_core`'s resolution; the exemplars, the forbidden list, the
    fixed slots and the voice brief are the plan's own.

    Four things are absent, and their absence is §3's Not-an-input row made
    structural. There is no sibling plan or text here, because this function
    takes neither. There is no label, because no entity upstream of S-13 has one
    (AD-07). There is no research artifact, because :class:`ReferencedCore`
    carries claims and observations and not the core. And there is no boundary,
    because the version this stage checks is compared in the precondition and
    never travels.

    The cross-destination link is withheld deliberately, although the plan holds
    one: R-2 makes it always conditional and binds it at S-14 only if the target
    was published, so a Writer shown a link it must deliver without could only
    promise one the run may then omit.
    """

    return json.dumps({
        "plan": {
            "plan_id": plan.plan_id,
            "version": plan.version,
            "destination": plan.destination.value,
            "mode": plan.mode.value,
            "format": plan.format.value,
            "length_target": plan.length_target.as_entity(),
            "first_line_mechanics": plan.first_line_mechanics,
            "segments": [segment.as_entity() for segment in plan.segments],
            "subheadings": plan.subheadings,
            "hashtags": (
                None if plan.hashtags is None else plan.hashtags.as_entity()
            ),
            "takes_title_and_dek": plan.format is PlanFormat.ARTICLE,
        },
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
        "core_items": {
            "sources": [
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "publisher": source.publisher,
                }
                for source in referenced.sources
            ],
            "claims": [
                {
                    "evidence_claim_id": claim.evidence_claim_id,
                    "statement": claim.statement,
                    "scope": claim.scope,
                    "caveats": list(claim.caveats),
                    "source_refs": list(claim.source_refs),
                    "observation_refs": list(claim.observation_refs),
                }
                for claim in referenced.claims
            ],
            "observations": [
                {
                    "observation_id": item.observation_id,
                    "source_ref": item.source_ref,
                    "excerpt": item.excerpt,
                    "attribution": item.attribution,
                    "figure": None if item.figure is None else item.figure.as_entity(),
                    "is_third_party_assertion": item.is_third_party_assertion,
                }
                for item in referenced.observations
            ],
        },
        "exemplars": [item.as_entity() for item in plan.exemplars],
        "voice_brief": {"ref": brief.brief_ref, "text": brief.text},
        "forbidden": [
            {"kind": item.kind.value, "value": item.value, "rule_ref": item.rule_ref}
            for item in plan.forbidden
        ],
        "fixed_slots": [slot.as_entity() for slot in plan.fixed_slots],
    })


def _inputs(
    *, plan: ExecutablePlan, referenced: ReferencedCore, request: str
) -> WriterInputs:
    """The trace of what the call was given, over the request it was given in."""

    return WriterInputs(
        plan_ref=plan.plan_ref,
        strategy_ref=plan.strategy_ref,
        core_item_refs=referenced.refs,
        exemplar_refs=tuple(item.item_id for item in plan.exemplars),
        voice_brief_ref=plan.voice_brief_ref,
        forbidden_refs=tuple(
            dict.fromkeys(item.rule_ref for item in plan.forbidden)
        ),
        request_digest="sha256:"
        + hashlib.sha256(request.encode("utf-8")).hexdigest(),
    )


def _answer(transport: WriterTransport, request: str) -> Optional[WriterAnswer]:
    """One call, parsed, or ``None``. Never the provider's own text."""

    try:
        raw = transport.complete(
            instructions=WRITER_INSTRUCTIONS, request=request
        )
    except Exception:  # noqa: BLE001 — sanitized, never the provider's text
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return WriterAnswer.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return None


def _spend(budget: Optional[CallBudget], scope_key: str) -> Optional[OutcomeRecord]:
    if budget is None:
        return None
    return budget.spend(scope=OutcomeScope.DESTINATION, scope_key=scope_key)
