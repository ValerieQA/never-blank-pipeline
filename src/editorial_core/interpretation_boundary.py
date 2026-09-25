"""S-04 · The Interpretation Boundary: generate, probe, code rules (Issue #301, SL-4).

The stage that decides what the material may mean. Step 2 §1 gives it one
authority — "decide what the material may mean for this audience: admissible
interpretations, probed inadmissible ones, limits" — and one prohibition: "it
must not consider client positions, lens or portfolio". The boundary answers
"what is true", not "what suits us", and the only context it is given is the
Audience Profile, for the reader connection (Step 1, E-09).

What it does, in the order it does it
-------------------------------------
1. **Generate, by model.** One call proposes interpretations with kind,
   supports, counter-evidence, dependencies, audience transfer and limits, and
   the reader connection the boundary needs (U-1 step 1).
2. **Probe, by model, in a separate call.** A second call receives the core,
   the Audience Profile and the generated list, works through the `K-TEMPT-*`
   families as an explicit checklist, names the most likely tempting reading
   per family, and tests that reading *and every generated one* against the
   evidence (U-1 step 2). Separate because "a model that has just produced a
   reading is weak at flagging its own overreach" — the whole of U-1's
   rejected alternative.
3. **The hard rules, by code.** Strength ≤ ceiling, the transfer rule,
   resolvable references and no dual listing (U-1 step 3). Code never widens
   what the model said: every rule here can only move an interpretation into
   the inadmissible list, never out of it.

**The probe is not optional.** A generate call that answers and a probe call
that does not is a boundary whose admissible set was never tested against the
families that catch the real errors, and recording it as admissible would be
exactly the fail-open U-1 exists to prevent. So a probe that cannot be made or
cannot be read is a ``SKIP``, not a boundary with an empty probe list.

**Bounded completeness (patch R1).** The boundary records what was generated,
what was tested and which families were applied. It does not claim to be
complete, and S-13's V-T02 is not limited to the list. That is why a probe
answer that skips a family is refused rather than recorded as "nothing found":
"this family found nothing" and "this family was never asked" are different
facts, and only one of them is evidence.

**Re-entry from S-13** (`L_boundary`, §0.3). One call tests the interpretation
a text was found to express, the detected reading is recorded as inadmissible
— a new E-08 record, or a new version of an existing one — and the whole
boundary is committed again as one coordinated E-08/E-09 change
(:mod:`src.run.boundary_commit`). Whether the anchor fell is decided by code
comparing the pairs (Step 2 §1, boundary commit rule 6), and the route out is
S-06 when it did and S-08 when it did not.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §1
(S-04), §4 U-1, §5.3 and §5.4 (F-4);
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §3 (E-08, E-09);
``docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md`` §6 (probe
families) and §7 (the ladder rules);
``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §13 walkthroughs A–C.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Final, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    KnowledgeRef,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.evidence_core import (
    EvidenceClaim,
    EvidenceCore,
    Strength,
    StrengthLadder,
)
from src.editorial_core.material_features import Asset, AssetClass, MaterialFeatures
from src.editorial_core.relevance_screen import (
    AudienceTransfer,
    BoundaryInput,
    DecisionRef,
)
from src.editorial_core.signal_selection import CallBudget
from src.knowledge.loader import KnowledgeBase

# The E-08/E-09 storage rule and its vocabulary, reused rather than restated.
# `Admissibility` is E-08's own field vocabulary, fixed by the module that
# writes the two files in the order §2.4 requires; a second copy of it here
# would eventually be a second answer to "which list is this in".
from src.run.boundary_commit import (
    Admissibility,
    BoundaryCommit,
    BoundaryMember,
    InterpretationVersion,
    commit_boundary,
    interpretation_relative_path,
)
from src.run.run_workspace import RunWorkspace
from src.strategy.audience_profile import AudienceProfile

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-04"

#: The counter a re-entry spends (§0.3): "L_boundary | unit | 1 | Re-entry
#: into S-04 from S-13". The limit in force is the ledger's, not this module's.
BOUNDARY_COUNTER: Final[str] = "L_boundary"

#: The route that brings a run back here, as the topology registry declares it.
REENTRY_SOURCE: Final[str] = "S-13"
REENTRY_CAUSE: Final[str] = "interpretation_inadmissible_or_unlisted"

#: The two routes out of a re-entry (§5.3). Which one is taken is decided by
#: code from the new boundary version, never by the model that tested the text.
ANCHOR_CAUSE: Final[str] = "anchor_invalidated_by_re_entry"
STRATEGY_CAUSE: Final[str] = "boundary_re_entry_without_anchor_loss"

#: Step 4 §7: "A `forecast` interpretation is capped at level 2, whatever its
#: supports" and "a `generalization` from a single case is capped at level 2".
#: Both are arithmetic on the one ladder, so both are code's.
CAPPED_LEVEL: Final[int] = 2

#: The level below which an admissible set is "only low-strength
#: interpretations" (§1, ARP → `DEGRADE`). The ladder's own weakest level:
#: anything a run may assert sits at 1 or above, so "nothing above the floor"
#: is the whole of the condition.
LOW_STRENGTH_LEVEL: Final[int] = 1


class BoundaryError(RuntimeError):
    """S-04 was asked to decide something its contract cannot decide."""


# ===========================================================================
# E-08 · Interpretation
# ===========================================================================


class InterpretationKind(str, Enum):
    """E-08's ``kind`` vocabulary (Step 1 §3)."""

    CAUSE = "cause"
    GENERALIZATION = "generalization"
    COMPARISON = "comparison"
    CONSEQUENCE_FOR_READER = "consequence_for_reader"
    FORECAST = "forecast"
    MECHANISM = "mechanism"
    OTHER = "other"


class InadmissibleReason(str, Enum):
    """E-08's ``inadmissible_reason`` vocabulary (Step 1 §3).

    Closed, like every other reason vocabulary in the engine: S-13's V-T02
    reconciles a finding against this list, and a free-text reason would make
    that reconciliation a string comparison over prose.
    """

    UNSUPPORTED = "unsupported"
    EXCEEDS_CEILING = "exceeds_ceiling"
    TRANSFER_NOT_SUPPORTED = "transfer_not_supported"
    INVENTED_SCENE = "invented_scene"
    CONTRADICTED = "contradicted"
    OTHER = "other"


#: The transfer values in order of how much they claim, weakest first. AD-08
#: gives S-04 the #58 claim mode as the *default* and lets "the code transfer
#: rule only make it stricter", which is a minimum over this order and not a
#: branch — so a model that asks for more than the screen established gets the
#: screen's answer, and a model that asks for less keeps its own.
_TRANSFER_ORDER: Final[tuple[AudienceTransfer, ...]] = (
    AudienceTransfer.BOUNDED_EXTERNAL_CASE,
    AudienceTransfer.DIRECT_AUDIENCE,
)


@dataclass(frozen=True, slots=True)
class Justification:
    """Free text plus the references that explain a value (Step 1 §0.3)."""

    text: str
    refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise BoundaryError(
                "a justification with no text explains nothing; every E-08 "
                "field that has one has it because the value needs a reason"
            )

    def as_entity(self) -> dict[str, Any]:
        return {"text": self.text, "refs": list(self.refs)}


@dataclass(frozen=True, slots=True)
class Limitation:
    """Text plus references (Step 1, E-08 ``limits`` and E-09 ``limits``).

    A concession candidate, and the shape walkthrough B's "there is not more
    money" arrives in: the boundary admits the reading the evidence supports
    and records beside it what that reading does not say.
    """

    text: str
    refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise BoundaryError("a limitation with no text limits nothing")

    def as_entity(self) -> dict[str, Any]:
        return {"text": self.text, "refs": list(self.refs)}


@dataclass(frozen=True, slots=True)
class Ambiguity:
    """Which interpretations a contradiction affects (Step 1, E-09).

    Whether it touches the anchor is S-06's decision, so nothing here says so:
    the boundary records the contradiction and the readings it reaches.
    """

    ambiguity_id: str
    text: str
    interpretation_refs: tuple[str, ...] = ()
    contradiction_ref: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.ambiguity_id.strip() or not self.text.strip():
            raise BoundaryError(
                "an ambiguity is named by its ID and says what is ambiguous"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "ambiguity_id": self.ambiguity_id,
            "text": self.text,
            "interpretation_refs": list(self.interpretation_refs),
            "contradiction_ref": self.contradiction_ref,
        }


@dataclass(frozen=True, slots=True)
class ReaderConnection:
    """How the material connects to the Audience Profile (Step 1, E-09).

    Required, "empty is allowed only together with a ``SKIP``" — which is why
    this is a type with a non-empty text rather than an optional string: a
    boundary that has one has a real one, and a boundary that has none carries
    ``None`` and the ``SKIP`` that goes with it.
    """

    text: str
    refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise BoundaryError(
                "a reader connection with no text is not a connection; a "
                "boundary that has none records none, and skips (E-09)"
            )

    def as_entity(self) -> dict[str, Any]:
        return {"text": self.text, "refs": list(self.refs)}


@dataclass(frozen=True, slots=True)
class Interpretation:
    """``E-08``: what the evidence means, and whether it may be said.

    The layer where most AI-shaped errors live (map walkthroughs A–C), so the
    rules Step 1 states about it are enforced here rather than trusted:
    ``strength`` above ``ceiling`` is exactly the state whose reason is
    ``exceeds_ceiling``, an inadmissible record carries both its reason and the
    note saying why a writer would reach for it, and an *admissible* one cites
    at least one usable claim — the middle link of I-04.
    """

    interpretation_id: str
    version: int
    statement: str
    kind: InterpretationKind
    support_refs: tuple[str, ...]
    audience_transfer: AudienceTransfer
    strength: Strength
    ceiling: Strength
    admissibility: Admissibility
    rationale: Justification
    counter_refs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    limits: tuple[Limitation, ...] = ()
    inadmissible_reason: Optional[InadmissibleReason] = None
    temptation_note: Optional[str] = None
    #: What this version replaces. ``None`` at version 1, and the previous
    #: version's key afterwards — the chain §2.4 rule 3 follows.
    supersedes: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.interpretation_id.strip() or not self.statement.strip():
            raise BoundaryError(
                f"interpretation {self.interpretation_id!r} is missing its "
                "identity or its statement"
            )
        if self.version < 1:
            raise BoundaryError(
                f"{self.interpretation_id} is at version {self.version}; an "
                "E-08 record starts at 1 and gains a version per commit"
            )
        if (self.version > 1) != (self.supersedes is not None):
            raise BoundaryError(
                f"{self.interpretation_id} version {self.version} "
                + ("names" if self.supersedes is not None else "names no")
                + " superseded version; a first version replaces nothing and "
                "a later one says what it replaces (Step 1 §0.1)"
            )
        if self.strength.ladder_id != self.ceiling.ladder_id:
            raise BoundaryError(
                f"{self.interpretation_id} has its strength on ladder "
                f"{self.strength.ladder_id!r} and its ceiling on "
                f"{self.ceiling.ladder_id!r}; AD-10 gives a run one ladder"
            )
        if self.admissible:
            self._admissible_record()
        else:
            self._inadmissible_record()

    @property
    def admissible(self) -> bool:
        return self.admissibility is Admissibility.ADMISSIBLE

    @property
    def key(self) -> tuple[str, int]:
        """The exact pair an E-09 version lists it by (§2.4 rule 1)."""

        return (self.interpretation_id, self.version)

    def as_entity(self) -> dict[str, Any]:
        """The E-08 body, written to
        ``signal/boundary/interpretations/<int_id>.v<n>.json`` (§2.2)."""

        return {
            "entity_type": "E-08",
            "entity_id": self.interpretation_id,
            "interpretation_id": self.interpretation_id,
            "version": self.version,
            "supersedes": self.supersedes,
            "statement": self.statement,
            "kind": self.kind.value,
            "support_refs": list(self.support_refs),
            "counter_refs": list(self.counter_refs),
            "depends_on": list(self.depends_on),
            "audience_transfer": self.audience_transfer.value,
            "strength": self.strength.as_entity(),
            "ceiling": self.ceiling.as_entity(),
            "limits": [item.as_entity() for item in self.limits],
            "admissibility": self.admissibility.value,
            "inadmissible_reason": (
                None
                if self.inadmissible_reason is None
                else self.inadmissible_reason.value
            ),
            "temptation_note": self.temptation_note,
            "rationale": self.rationale.as_entity(),
        }

    # ------------------------------------------------------------------
    # The two halves of E-08's validation
    # ------------------------------------------------------------------

    def _admissible_record(self) -> None:
        if self.inadmissible_reason is not None:
            raise BoundaryError(
                f"{self.interpretation_id} is admissible and carries reason "
                f"{self.inadmissible_reason.value!r}; a reason belongs to the "
                "list it explains"
            )
        if not self.support_refs:
            raise BoundaryError(
                f"{self.interpretation_id} is admissible and cites no evidence "
                "claim; the middle link of I-04 is "
                "`interpretation → evidence_claim`, and a reading a text may "
                "express with nothing under it is fabrication"
            )
        if self.strength.level > self.ceiling.level:
            raise BoundaryError(
                f"{self.interpretation_id} is admissible at strength level "
                f"{self.strength.level} with ceiling level "
                f"{self.ceiling.level}; Step 1 makes that state inadmissible "
                "with reason exceeds_ceiling, not an admissible reading"
            )

    def _inadmissible_record(self) -> None:
        # An inadmissible record may cite nothing: "unsupported" is the state
        # where there is nothing to cite, and refusing to store the reading
        # would delete the detection material V-T02 reconciles against (I-05).
        if self.inadmissible_reason is None:
            raise BoundaryError(
                f"{self.interpretation_id} is inadmissible and says why not; "
                "§1 Post: every inadmissible one has a reason"
            )
        if self.temptation_note is None or not self.temptation_note.strip():
            raise BoundaryError(
                f"{self.interpretation_id} is inadmissible and carries no "
                "temptation note; the note is why a writer would reach for it, "
                "and it is V-T02's detection material (Step 1, E-08)"
            )
        # Step 1's rule reads one way and is enforced one way: strength above
        # the ceiling *is* reason `exceeds_ceiling`. The converse is not a
        # rule — a reading refused for inventing a scene keeps whatever
        # strength it was asserted at, and saying so is not a ceiling breach.
        if (
            self.strength.level > self.ceiling.level
            and self.inadmissible_reason is not InadmissibleReason.EXCEEDS_CEILING
        ):
            raise BoundaryError(
                f"{self.interpretation_id} is recorded as "
                f"{self.inadmissible_reason.value!r} at strength level "
                f"{self.strength.level} over ceiling level "
                f"{self.ceiling.level}; Step 1 gives that state one reason, "
                "and it is exceeds_ceiling"
            )


# ===========================================================================
# The probe families (Step 4 §6, U-1)
# ===========================================================================


class ProbeFinding(str, Enum):
    """What one applied family found.

    Two members and no third: a family that was not applied is not recorded
    here at all, because a probe answer that skips a family is refused. "This
    family found nothing" is evidence; "nobody asked" is not, and a vocabulary
    that could express both as one value would let the second pass as the
    first.
    """

    FOUND = "found"
    NONE_FOUND = "none_found"


@dataclass(frozen=True, slots=True)
class ProbeFamily:
    """One ``K-TEMPT-*`` record, as the probe call uses it.

    Handed to the stage rather than read by it, exactly as the run's ladder is:
    :func:`probe_families` takes a register somebody else loaded, because
    expiry is computed against a day, and the day a run happens on is a
    scheduling input the core is given (CE-1).
    """

    record_id: str
    name: str
    #: The question the probe call asks for this family (§6, ``## Probe``).
    probe: str
    knowledge: KnowledgeRef

    def __post_init__(self) -> None:
        if not self.record_id.strip() or not self.probe.strip():
            raise BoundaryError(
                f"probe family {self.record_id!r} carries no question; §6 "
                "makes `## Probe` a required section for exactly this reason"
            )


def probe_families(knowledge: KnowledgeBase) -> tuple[ProbeFamily, ...]:
    """Every probe family a run loaded, in register order (Step 4 §6).

    Reads the loaded register rather than the directory: a retired family is
    never loaded, and a family past its ``review_by`` arrives demoted, with the
    demotion visible in its :class:`~src.editorial_core.arp.KnowledgeRef`. The
    probe applies it either way — a family only asks a question, and asking it
    can only narrow the boundary — and the trace shows what it was worth.
    """

    return tuple(
        ProbeFamily(
            record_id=loaded.identity,
            name=loaded.record.document.title,
            probe=(loaded.record.document.section("Probe") or "").strip(),
            knowledge=loaded.ref(),
        )
        for loaded in knowledge.records
        if loaded.record.is_probe_family
    )


@dataclass(frozen=True, slots=True)
class ProbeApplication:
    """One family applied, and what it found (§1, Trace; patch R1)."""

    record_id: str
    finding: ProbeFinding
    #: What the probe said, in one line. Free text, and therefore
    #: workspace-only (Step 3 §3.3).
    note: str
    #: The interpretation this family produced, when it found one.
    interpretation_id: Optional[str] = None
    knowledge: Optional[KnowledgeRef] = None

    def __post_init__(self) -> None:
        if (self.finding is ProbeFinding.FOUND) != (
            self.interpretation_id is not None
        ):
            raise BoundaryError(
                f"probe family {self.record_id} records {self.finding.value} "
                f"with interpretation {self.interpretation_id!r}; a family that "
                "found a tempting reading names it, and one that found none "
                "names nothing"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "finding": self.finding.value,
            "note": self.note,
            "interpretation_id": self.interpretation_id,
            "knowledge": (
                None
                if self.knowledge is None
                else self.knowledge.model_dump(mode="json")
            ),
        }


# ===========================================================================
# E-09 · Interpretation Boundary
# ===========================================================================


@dataclass(frozen=True, slots=True)
class InterpretationBoundary:
    """``E-09``: what the texts of this signal may and may not mean.

    Every version is a complete snapshot (patch R2): it carries the exact E-08
    versions it lists, and the two lists are derived from the records rather
    than stored beside them — which is how "no interpretation sits in both
    lists" becomes unrepresentable instead of merely checked.
    """

    boundary_id: str
    version: int
    #: ``(core_id, version)``: the final core version after enrichment.
    core_ref: tuple[str, int]
    #: Fix F-6: the relevance evidence the reader connection and the
    #: ``audience_transfer`` defaults came from.
    relevance_ref: DecisionRef
    members: tuple[Interpretation, ...]
    probes: tuple[ProbeApplication, ...]
    outcome: OutcomeRecord
    reader_connection: Optional[ReaderConnection] = None
    limits: tuple[Limitation, ...] = ()
    ambiguities: tuple[Ambiguity, ...] = ()

    def __post_init__(self) -> None:
        if not self.boundary_id.strip():
            raise BoundaryError("a boundary is identified by its boundary ID")
        if self.version < 1:
            raise BoundaryError(
                f"boundary version {self.version} is below 1; S-04 produces v1 "
                "and every boundary commit the versions after it"
            )
        if not self.members:
            raise BoundaryError(
                f"{self.boundary_id} lists no interpretation at all; a boundary "
                "version is a complete snapshot, and a snapshot of nothing "
                "records neither what was generated nor what was tested"
            )
        identities = [member.interpretation_id for member in self.members]
        duplicated = sorted({key for key in identities if identities.count(key) > 1})
        if duplicated:
            raise BoundaryError(
                "one interpretation is listed twice in "
                f"{self.boundary_id}: {', '.join(duplicated)}; a snapshot holds "
                "one exact version of each, in one of the two lists and never "
                "in both (Step 1, E-09 validation)"
            )
        if (
            self.reader_connection is None
            and self.outcome.outcome is not ArpOutcome.SKIP
        ):
            raise BoundaryError(
                f"{self.boundary_id} states no reader connection and records "
                f"outcome {self.outcome.outcome.value}; §1 Post allows an "
                "absent connection only together with a SKIP"
            )
        # "Empty `admissible` → SKIP with state 'no admissible interpretation'"
        # (Step 1, E-09) is enforced where S-04 decides it — `_stage_outcome`,
        # the §1 ARP column — and not here. A *re-entry* version may legitimately
        # admit nothing and still record a REPLAN: when the reclassified
        # interpretation was the anchor's, §1 routes to S-06, and it is S-06
        # that turns "no provable anchor" into the unit's SKIP.

    @property
    def admissible(self) -> tuple[Interpretation, ...]:
        return tuple(member for member in self.members if member.admissible)

    @property
    def inadmissible(self) -> tuple[Interpretation, ...]:
        return tuple(member for member in self.members if not member.admissible)

    def member(self, interpretation_id: str) -> Optional[Interpretation]:
        """The member with this ID, or ``None`` when the boundary has none."""

        for member in self.members:
            if member.interpretation_id == interpretation_id:
                return member
        return None

    def as_entity(self) -> dict[str, Any]:
        """The E-09 body the commit marker carries (§2.2, §2.4).

        The membership itself is *not* here: ``commit_boundary`` states it,
        because each member entry carries the digest of a file that does not
        exist until the commit writes it.
        """

        return {
            "entity_type": "E-09",
            "entity_id": self.boundary_id,
            "core_ref": {"core_id": self.core_ref[0], "version": self.core_ref[1]},
            "relevance_ref": self.relevance_ref.as_entity(),
            "limits": [item.as_entity() for item in self.limits],
            "ambiguities": [item.as_entity() for item in self.ambiguities],
            "reader_connection": (
                None
                if self.reader_connection is None
                else self.reader_connection.as_entity()
            ),
            "probe_families_applied": [probe.as_entity() for probe in self.probes],
            "outcome": self.outcome.model_dump(mode="json"),
        }


@dataclass(frozen=True, slots=True)
class BoundaryDecision:
    """What one S-04 execution made of one core.

    A boundary and a terminal outcome are not exclusive: walkthrough C ends in
    a ``SKIP`` *with* a boundary, because "no admissible interpretation" is a
    finding about the material and the inadmissible reading that tempted the
    engine is exactly what is worth keeping. A boundary is absent only when a
    call could not be made or could not be read, and then there is nothing to
    record about the material at all.
    """

    signal_id: str
    boundary: Optional[InterpretationBoundary] = None
    outcomes: tuple[OutcomeRecord, ...] = ()
    #: Model calls this execution made, for the per-stage call record (§3.3).
    calls: int = 0


# ===========================================================================
# Identity
# ===========================================================================


def boundary_id(core_id: str) -> str:
    """The ``bnd`` ID of the boundary over one core."""

    return f"bnd-{core_id}"


def interpretation_id(core_id: str, index: int) -> str:
    """The ID of the ``index``-th interpretation recorded against one core.

    ``index`` counts members of the boundary and never resets: a re-entry
    appends, and a reclassification keeps the ID it already had, so the count
    of members is strictly increasing and the ID it produces is new.
    """

    return f"int-{core_id}-{index}"


def ambiguity_id(core_id: str, index: int) -> str:
    return f"amb-{core_id}-{index}"


# ===========================================================================
# The two calls (U-1)
# ===========================================================================


class BoundaryTransport(Protocol):
    """The model calls S-04 makes, as a narrow boundary.

    One protocol for both calls, and its own name: what separates generate
    from probe is the instructions each carries, and U-1 is explicit that they
    are two calls to the same kind of boundary rather than two providers.
    """

    def complete(self, *, instructions: str, request: str) -> str: ...


GENERATE_INSTRUCTIONS = """\
You propose interpretations of evidence for an editorial engine. You decide
what the material may mean for the configured audience — what is *true*, not
what suits anybody. You are given no client position, no lens and no portfolio,
and you must not ask for one or reason about one.

You receive an Evidence Core (sources, observations, evidence claims with
verdicts, scopes, strengths and ceilings), the material's feature vector, the
Audience Profile and a strength ladder whose levels are numbered from 1
(weakest) upwards. Everything you say must point back at usable evidence claims
by their IDs. Cite only claim IDs the request contains.

Return exactly three things.

1. `interpretations`: every reading the evidence supports, as a list. Each entry
   carries:

     statement        one sentence: what the evidence means
     kind             "cause", "generalization", "comparison",
                      "consequence_for_reader", "forecast", "mechanism" or
                      "other"
     support_refs     the claim IDs that support it, at least one
     counter_refs     the claim IDs that argue against it, possibly empty
     depends_on       1-based positions in this same list whose readings this
                      one rests on as premises, possibly empty
     audience_transfer  "direct_audience" when the reading is about the
                      configured reader's own conditions, otherwise
                      "bounded_external_case"
     strength_level   the ladder level this reading may be asserted at
     limits           what the reading does *not* say: text plus claim refs
     rationale        one sentence, with `rationale_refs` of claim IDs

2. `limits`: boundary-level limitations, e.g. "a single case", "no second
   source". Text plus claim refs. Possibly empty.

3. `ambiguities`: where the evidence contradicts itself, which readings it
   reaches (1-based positions), and the contradiction ID when the core names
   one. Possibly empty.

4. `reader_connection`: how this material connects to the Audience Profile, in
   one sentence, with the claim IDs that carry the connection. Return `null` —
   not an empty sentence — when the evidence establishes no connection to this
   reader. "There is no connection" is a legitimate and useful answer.

Return ONLY one valid JSON object, no text outside it:

{"interpretations": [{"statement": "...", "kind": "cause", "support_refs": ["..."],
  "counter_refs": [], "depends_on": [], "audience_transfer": "bounded_external_case",
  "strength_level": 2, "limits": [{"text": "...", "refs": ["..."]}],
  "rationale": "...", "rationale_refs": ["..."]}],
 "limits": [{"text": "...", "refs": ["..."]}],
 "ambiguities": [{"text": "...", "interpretation_refs": [1], "contradiction_ref": null}],
 "reader_connection": {"text": "...", "refs": ["..."]}}
"""

PROBE_INSTRUCTIONS = """\
You test proposed interpretations against the evidence, for an editorial
engine. You did not write them. Your job is to find the reading a writer would
reach for and the evidence does not carry, and to say of every proposed reading
whether the evidence admits it.

You receive the Evidence Core, the Audience Profile, the list of proposed
interpretations (numbered from 1) and a checklist of probe families. Each family
carries a question. You must answer every family in the checklist — leaving one
out is not an answer, and "I found nothing for this family" is said by returning
the family with `tempting` set to `null`.

Return exactly two things.

1. `families`: one entry per family in the checklist, in any order.

     record_id    the family's ID, exactly as the checklist gives it
     finding      one sentence: what you looked for and what you saw
     tempting     `null`, or the most likely tempting inadmissible reading for
                  this family: `statement`, `kind`, `support_refs` (possibly
                  empty — an unsupported reading cites nothing), `reason`
                  ("unsupported", "exceeds_ceiling", "transfer_not_supported",
                  "invented_scene", "contradicted" or "other") and
                  `temptation_note`, one sentence on why a writer would reach
                  for it.

2. `verdicts`: one entry per proposed interpretation, all of them.

     index            its 1-based position in the proposed list
     admissibility    "admissible" or "inadmissible"
     finding          one sentence: the evidence you tested it against
     reason           the reason code, when inadmissible; `null` otherwise
     temptation_note  one sentence on why a writer would reach for it, when
                      inadmissible; `null` otherwise

Cite only claim IDs the request contains. Return ONLY one valid JSON object, no
text outside it:

{"families": [{"record_id": "K-TEMPT-01", "finding": "...",
   "tempting": {"statement": "...", "kind": "consequence_for_reader",
     "support_refs": [], "reason": "transfer_not_supported",
     "temptation_note": "..."}}],
 "verdicts": [{"index": 1, "admissibility": "admissible", "finding": "...",
   "reason": null, "temptation_note": null}]}
"""

TEST_INSTRUCTIONS = """\
You test one interpretation a written text was found to express, against the
evidence and against a boundary that already exists. This is a re-entry: the
text expressed a reading the boundary does not admit, and the boundary must now
record that reading.

You receive the Evidence Core, the Audience Profile, the current boundary's
members (each with its ID, statement and list) and the detected reading.

Decide one thing: is the detected reading one the boundary already records, or
a new one?

     matches           the interpretation ID it is the same reading as, or
                       `null` when it is new
     reason            why the evidence does not admit it: "unsupported",
                       "exceeds_ceiling", "transfer_not_supported",
                       "invented_scene", "contradicted" or "other"
     temptation_note   one sentence on why a writer would reach for it
     finding           one sentence: the evidence you tested it against
     statement, kind, support_refs, rationale, rationale_refs
                       the new record's fields, required when `matches` is
                       `null` and ignored otherwise

Cite only claim IDs the request contains. Return ONLY one valid JSON object, no
text outside it:

{"matches": null, "reason": "transfer_not_supported", "temptation_note": "...",
 "finding": "...", "statement": "...", "kind": "consequence_for_reader",
 "support_refs": [], "rationale": "...", "rationale_refs": []}
"""


# ===========================================================================
# The answers, parsed strictly
# ===========================================================================


class _BoundaryModel(BaseModel):
    """An answer is parsed strictly, or it is not an answer.

    ``str_strip_whitespace`` is what makes every ``min_length=1`` below mean
    "says something": a field of spaces is not a shorter answer, it is an
    absent one dressed as a present one, and the records these answers become
    refuse an empty statement, reason or note.
    """

    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=True
    )


class TextWithRefs(_BoundaryModel):
    text: str = Field(min_length=1)
    refs: tuple[str, ...] = ()


class AmbiguityAnswer(_BoundaryModel):
    text: str = Field(min_length=1)
    interpretation_refs: tuple[int, ...] = ()
    contradiction_ref: Optional[str] = None


class InterpretationAnswer(_BoundaryModel):
    statement: str = Field(min_length=1)
    kind: InterpretationKind
    support_refs: tuple[str, ...] = ()
    counter_refs: tuple[str, ...] = ()
    depends_on: tuple[int, ...] = ()
    audience_transfer: AudienceTransfer
    strength_level: int = Field(ge=1)
    limits: tuple[TextWithRefs, ...] = ()
    rationale: str = Field(min_length=1)
    rationale_refs: tuple[str, ...] = ()


class GenerateAnswer(_BoundaryModel):
    interpretations: tuple[InterpretationAnswer, ...] = ()
    limits: tuple[TextWithRefs, ...] = ()
    ambiguities: tuple[AmbiguityAnswer, ...] = ()
    reader_connection: Optional[TextWithRefs] = None


class TemptingAnswer(_BoundaryModel):
    statement: str = Field(min_length=1)
    kind: InterpretationKind
    support_refs: tuple[str, ...] = ()
    reason: InadmissibleReason
    temptation_note: str = Field(min_length=1)


class FamilyAnswer(_BoundaryModel):
    record_id: str = Field(min_length=1)
    finding: str = Field(min_length=1)
    tempting: Optional[TemptingAnswer] = None


class VerdictAnswer(_BoundaryModel):
    index: int = Field(ge=1)
    admissibility: Admissibility
    finding: str = Field(min_length=1)
    reason: Optional[InadmissibleReason] = None
    temptation_note: Optional[str] = None


class ProbeAnswer(_BoundaryModel):
    families: tuple[FamilyAnswer, ...] = ()
    verdicts: tuple[VerdictAnswer, ...] = ()


class TestAnswer(_BoundaryModel):
    reason: InadmissibleReason
    temptation_note: str = Field(min_length=1)
    finding: str = Field(min_length=1)
    matches: Optional[str] = None
    statement: Optional[str] = None
    kind: Optional[InterpretationKind] = None
    support_refs: tuple[str, ...] = ()
    rationale: Optional[str] = None
    rationale_refs: tuple[str, ...] = ()


# ===========================================================================
# What S-13 hands back at a re-entry
# ===========================================================================


@dataclass(frozen=True, slots=True)
class DetectedInterpretation:
    """The V-T02 finding that sent the run back here (§1, Inputs).

    Carried as a type rather than a string so that the trace can say "which
    S-13 finding triggered a re-entry" without a reader reconstructing it from
    the outcome's free text.
    """

    statement: str
    #: The destination whose text expressed it — the scope §0.3 skips when
    #: ``L_boundary`` is exhausted.
    destination: str
    #: The text it was found in, when the caller has one.
    text_ref: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.statement.strip() or not self.destination.strip():
            raise BoundaryError(
                "a detected interpretation names what was expressed and the "
                "destination whose text expressed it"
            )


@dataclass(frozen=True, slots=True)
class Reentry:
    """What one re-entry made of the boundary it was sent back to."""

    #: The new boundary version, or ``None`` when none was committed: the
    #: counter was exhausted, the budget refused, or the test call did not
    #: answer. In all three the destination is skipped rather than released.
    boundary: Optional[InterpretationBoundary] = None
    outcomes: tuple[OutcomeRecord, ...] = ()
    calls: int = 0
    #: Whether the anchor's interpretation is inadmissible in the new version
    #: (boundary commit rule 6). Decided by code comparing the pairs.
    anchor_invalidated: bool = False
    #: The record the detected reading was written into: a new one, or the new
    #: version of the one it matched.
    detected_interpretation_id: Optional[str] = None


# ===========================================================================
# The stage
# ===========================================================================


def decide_boundary(
    *,
    core: EvidenceCore,
    features: MaterialFeatures,
    relevance: BoundaryInput,
    relevance_ref: DecisionRef,
    audience: AudienceProfile,
    families: Sequence[ProbeFamily],
    transport: BoundaryTransport,
    ladder: StrengthLadder,
    assets: Sequence[Asset] = (),
    budget: Optional[CallBudget] = None,
) -> BoundaryDecision:
    """Generate, probe and apply the code rules: one boundary, version 1.

    Returns a :class:`BoundaryDecision` in every case the protocol has an
    outcome for. A call that could not be made or could not be read is a
    recorded ``SKIP`` and not an exception, for the reason S-00 through S-03
    give: a caller that had to catch an error would have nothing to write into
    the trace. The stage's precondition — a final core with at least one usable
    claim — still raises: §6.2 has no state for a stage run out of order.
    """

    signal_id = core.signal_ids[0]
    if not core.usable_claims:
        raise BoundaryError(
            f"{signal_id} reached {STAGE} with a core holding no accepted or "
            "qualified claim; §1 Pre asks for at least one usable evidence "
            "claim, and a boundary over nothing citable is not a boundary"
        )
    if features.core_ref != (core.core_id, core.version):
        raise BoundaryError(
            f"{signal_id} reached {STAGE} with a feature vector describing "
            f"{features.core_ref!r} and a core at "
            f"({core.core_id!r}, {core.version}); §1 Pre is the *final* core, "
            "and a vector describing another version does not describe it"
        )
    if not families:
        raise BoundaryError(
            f"{signal_id} reached {STAGE} with no probe family; U-1 makes the "
            "probe an explicit checklist, and a checklist with no rows is not "
            "a weaker probe — it is no probe at all"
        )

    calls = 0
    refusal = _spend(budget, signal_id)
    if refusal is not None:
        return BoundaryDecision(signal_id=signal_id, outcomes=(refusal,))

    request = _generate_request(core, features, assets, audience, relevance, ladder)
    generated = _answer(transport, GENERATE_INSTRUCTIONS, request, GenerateAnswer)
    calls += 1
    if generated is None or not generated.interpretations:
        return BoundaryDecision(
            signal_id=signal_id,
            outcomes=(
                _skip(
                    signal_id,
                    StateCode.BOUNDARY_GENERATION_FAILED,
                    "the generate call produced no interpretation this stage "
                    "may read",
                ),
            ),
            calls=calls,
        )

    refusal = _spend(budget, signal_id)
    if refusal is not None:
        return BoundaryDecision(
            signal_id=signal_id, outcomes=(refusal,), calls=calls
        )

    probed = _answer(
        transport,
        PROBE_INSTRUCTIONS,
        _probe_request(core, audience, generated, families),
        ProbeAnswer,
    )
    calls += 1
    defect = None if probed is None else _probe_defect(probed, generated, families)
    if probed is None or defect is not None:
        return BoundaryDecision(
            signal_id=signal_id,
            outcomes=(
                _skip(
                    signal_id,
                    StateCode.BOUNDARY_PROBE_FAILED,
                    defect
                    or "the probe call produced no answer this stage may read",
                ),
            ),
            calls=calls,
        )

    members, probes = _members(
        core=core,
        ladder=ladder,
        relevance=relevance,
        generated=generated,
        probed=probed,
        families=families,
    )
    connection = _reader_connection(core, generated.reader_connection)
    outcome = _stage_outcome(signal_id, members, connection)
    boundary = InterpretationBoundary(
        boundary_id=boundary_id(core.core_id),
        version=1,
        core_ref=(core.core_id, core.version),
        relevance_ref=relevance_ref,
        members=members,
        probes=probes,
        outcome=outcome,
        reader_connection=connection,
        limits=tuple(
            Limitation(text=item.text, refs=_held(item.refs, core))
            for item in generated.limits
        ),
        ambiguities=_ambiguities(core, generated, members),
    )
    return BoundaryDecision(
        signal_id=signal_id,
        boundary=boundary,
        outcomes=(outcome,),
        calls=calls,
    )


def re_enter_boundary(
    *,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    audience: AudienceProfile,
    detected: DetectedInterpretation,
    unit_id: str,
    transport: BoundaryTransport,
    ladder: StrengthLadder,
    counters: AttemptCounterLedger,
    anchor_interpretation_id: Optional[str] = None,
    budget: Optional[CallBudget] = None,
) -> Reentry:
    """Record what a text expressed, and route out of the new version.

    One call, and every refusal before it fails closed on the destination whose
    text caused the re-entry: an exhausted ``L_boundary``, a refused budget and
    a test call that did not answer all end in that destination's ``SKIP``,
    because the alternative is releasing a text S-13 found to express a reading
    the boundary does not admit (I-05).
    """

    if not unit_id.strip():
        raise BoundaryError(
            "a re-entry spends L_boundary, which is counted per unit (§0.3); "
            "an unnamed unit is a counter nobody can bound"
        )

    route = counters.route(
        source=REENTRY_SOURCE,
        cause=REENTRY_CAUSE,
        # §0.3 counts `L_boundary` per **unit**, so the unit is what the ledger
        # keys on: two destinations of one unit share the attempt, which is
        # what makes a single re-entry per unit mean what it says.
        scope_key=unit_id,
        state_code=StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION,
        reason=(
            f"{detected.destination} expressed an interpretation the boundary "
            f"does not admit: {detected.statement}"
        ),
    )
    if route.outcome is not ArpOutcome.REPLAN:
        # Exhaustion skips "the destination whose text caused it" (§0.3). The
        # ledger takes one scope key and counted under the unit, so the record
        # it produced is re-keyed to the scope it actually concerns.
        return Reentry(outcomes=(route.model_copy(update={
            "scope_key": detected.destination
        }),))

    refusal = _spend(budget, detected.destination, scope=OutcomeScope.DESTINATION)
    if refusal is not None:
        return Reentry(outcomes=(route, refusal))

    answer = _answer(
        transport,
        TEST_INSTRUCTIONS,
        _test_request(core, audience, boundary, detected),
        TestAnswer,
    )
    matched = None if answer is None else boundary.member(answer.matches or "")
    if answer is None or (answer.matches is not None and matched is None):
        return Reentry(
            outcomes=(
                route,
                _skip(
                    detected.destination,
                    StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION,
                    "the re-entry test call produced no answer this stage may "
                    "read, so the detected interpretation could not be recorded",
                    scope=OutcomeScope.DESTINATION,
                ),
            ),
            calls=1,
        )

    recorded, members = _recorded(
        boundary=boundary,
        core=core,
        ladder=ladder,
        answer=answer,
        matched=matched,
    )
    if recorded is None:
        return Reentry(
            outcomes=(
                route,
                _skip(
                    detected.destination,
                    StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION,
                    "the re-entry test call did not describe the new record it "
                    "asked for, so nothing could be written",
                    scope=OutcomeScope.DESTINATION,
                ),
            ),
            calls=1,
        )

    # Boundary commit rule 6: "the anchor is invalidated when its
    # interpretation's current version in the newest E-09 is inadmissible.
    # Invalidation is detected by code comparing the pairs."
    anchor = None
    if anchor_interpretation_id is not None:
        anchor = next(
            (
                member
                for member in members
                if member.interpretation_id == anchor_interpretation_id
            ),
            None,
        )
    invalidated = anchor is not None and not anchor.admissible

    onward = counters.route(
        source=STAGE,
        cause=ANCHOR_CAUSE if invalidated else STRATEGY_CAUSE,
        scope_key=unit_id if invalidated else detected.destination,
        state_code=StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION,
        reason=(
            f"{recorded.interpretation_id} is inadmissible in boundary version "
            f"{boundary.version + 1} "
            + (
                "and the anchor rests on it"
                if invalidated
                else "and the anchor still stands"
            )
        ),
    )
    committed = InterpretationBoundary(
        boundary_id=boundary.boundary_id,
        version=boundary.version + 1,
        core_ref=boundary.core_ref,
        relevance_ref=boundary.relevance_ref,
        members=members,
        probes=boundary.probes,
        outcome=onward,
        reader_connection=boundary.reader_connection,
        limits=boundary.limits,
        ambiguities=boundary.ambiguities,
    )
    return Reentry(
        boundary=committed,
        outcomes=(route, onward),
        calls=1,
        anchor_invalidated=invalidated,
        detected_interpretation_id=recorded.interpretation_id,
    )


def commit_boundary_version(
    workspace: RunWorkspace, boundary: InterpretationBoundary
) -> BoundaryCommit:
    """Write one boundary version as the coordinated commit §2.4 requires.

    The E-08 versions this commit introduces go first and the E-09 marker
    last, through :func:`~src.run.boundary_commit.commit_boundary` rather than
    beside it: a member whose file the workspace already holds is an unchanged
    interpretation and is referenced where it is (rule 4), and one whose file
    is not there yet is written now.
    """

    written = tuple(
        InterpretationVersion(
            interpretation_id=member.interpretation_id,
            version=member.version,
            admissibility=member.admissibility,
            payload=member.as_entity(),
        )
        for member in boundary.members
        if not (
            workspace.run_dir
            / interpretation_relative_path(member.interpretation_id, member.version)
        ).is_file()
    )
    return commit_boundary(
        workspace,
        boundary_id=boundary.boundary_id,
        version=boundary.version,
        interpretations=written,
        members=tuple(
            BoundaryMember(
                interpretation_id=member.interpretation_id,
                version=member.version,
                admissibility=member.admissibility,
            )
            for member in boundary.members
        ),
        payload=boundary.as_entity(),
    )


# ===========================================================================
# The code rules (§1, Decider: ceilings, transfer, references, dual listing)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One reading on its way to being an E-08 record."""

    identity: str
    statement: str
    kind: InterpretationKind
    support_refs: tuple[str, ...]
    counter_refs: tuple[str, ...]
    depends_on: tuple[str, ...]
    audience_transfer: AudienceTransfer
    strength_level: int
    rationale: Justification
    limits: tuple[Limitation, ...]
    admissibility: Admissibility
    reason: Optional[InadmissibleReason]
    temptation_note: Optional[str]


def _members(
    *,
    core: EvidenceCore,
    ladder: StrengthLadder,
    relevance: BoundaryInput,
    generated: GenerateAnswer,
    probed: ProbeAnswer,
    families: Sequence[ProbeFamily],
) -> tuple[tuple[Interpretation, ...], tuple[ProbeApplication, ...]]:
    """Every generated and probed reading, as checked E-08 records."""

    verdicts = {verdict.index: verdict for verdict in probed.verdicts}
    candidates: list[_Candidate] = []
    for position, item in enumerate(generated.interpretations, 1):
        verdict = verdicts[position]
        candidates.append(
            _Candidate(
                identity=interpretation_id(core.core_id, position),
                statement=item.statement,
                kind=item.kind,
                support_refs=tuple(dict.fromkeys(item.support_refs)),
                counter_refs=tuple(dict.fromkeys(item.counter_refs)),
                depends_on=tuple(
                    interpretation_id(core.core_id, index)
                    for index in dict.fromkeys(item.depends_on)
                ),
                audience_transfer=item.audience_transfer,
                strength_level=item.strength_level,
                rationale=Justification(
                    text=item.rationale, refs=tuple(item.rationale_refs)
                ),
                limits=tuple(
                    Limitation(text=limit.text, refs=tuple(limit.refs))
                    for limit in item.limits
                ),
                admissibility=verdict.admissibility,
                reason=verdict.reason,
                temptation_note=verdict.temptation_note,
            )
        )

    # The families, in the order the checklist gave them, so that the trace
    # reads as the checklist rather than as the order the model answered in.
    answered = {family.record_id: family for family in probed.families}
    probes: list[ProbeApplication] = []
    for family in families:
        found = answered[family.record_id]
        if found.tempting is None:
            probes.append(
                ProbeApplication(
                    record_id=family.record_id,
                    finding=ProbeFinding.NONE_FOUND,
                    note=found.finding,
                    knowledge=family.knowledge,
                )
            )
            continue
        identity = interpretation_id(core.core_id, len(candidates) + 1)
        candidates.append(
            _Candidate(
                identity=identity,
                statement=found.tempting.statement,
                kind=found.tempting.kind,
                support_refs=tuple(dict.fromkeys(found.tempting.support_refs)),
                counter_refs=(),
                depends_on=(),
                # A tempting reading the probe named is never admitted, so its
                # transfer claims nothing: the screen's own value is the
                # default and code may only make it stricter (AD-08).
                audience_transfer=relevance.audience_transfer,
                strength_level=LOW_STRENGTH_LEVEL,
                rationale=Justification(
                    text=found.finding, refs=tuple(found.tempting.support_refs)
                ),
                limits=(),
                admissibility=Admissibility.INADMISSIBLE,
                reason=found.tempting.reason,
                temptation_note=found.tempting.temptation_note,
            )
        )
        probes.append(
            ProbeApplication(
                record_id=family.record_id,
                finding=ProbeFinding.FOUND,
                note=found.finding,
                interpretation_id=identity,
                knowledge=family.knowledge,
            )
        )

    return _checked(core, ladder, relevance, tuple(candidates)), tuple(probes)


def _checked(
    core: EvidenceCore,
    ladder: StrengthLadder,
    relevance: BoundaryInput,
    candidates: Sequence[_Candidate],
) -> tuple[Interpretation, ...]:
    """Apply the hard rules. They only ever move a reading out of the list.

    Four rules, in one pass and then a second over dependencies:

    1. **Resolvable references.** Supports must be *usable* claims of this
       core (E-03's usability rule); counters and rationale refs must be claims
       it holds; dependencies must be readings this boundary lists. A reading
       citing something the core does not hold is not one a text may express,
       so it is inadmissible and ``unsupported``, with its strength floored.
    2. **Ceiling.** The ceiling is the lowest ceiling among the supporting
       claims (E-08), further capped at level 2 for a ``forecast`` and for a
       ``generalization`` resting on a single source (Step 4 §7).
    3. **Transfer.** The effective transfer is the stricter of the model's and
       the #58 claim mode (AD-08), and a ``consequence_for_reader`` claiming
       ``direct_audience`` needs at least one supporting claim the relevance
       screen recorded as carrying the audience connection.
    4. **No dual listing.** By construction: one ``admissibility`` per record,
       and :class:`InterpretationBoundary` refuses a repeated ID.
    """

    claims = {item.evidence_claim_id: item for item in core.evidence_claims}
    usable = {item.evidence_claim_id for item in core.usable_claims}
    audience_claims = {
        ref for basis in relevance.relevance_bases for ref in basis.evidence_claim_refs
    }
    known = {candidate.identity for candidate in candidates}

    built: list[Interpretation] = []
    for candidate in candidates:
        built.append(
            _rule_checked(
                candidate,
                ladder=ladder,
                claims=claims,
                usable=usable,
                audience_claims=audience_claims,
                known=known,
                default_transfer=relevance.audience_transfer,
            )
        )

    # Nothing is written yet, so a demotion here is not a reclassification:
    # every record is still at version 1.
    return _premise_checked(built, reclassified=False)


def _premise_checked(
    members: Sequence[Interpretation], *, reclassified: bool
) -> tuple[Interpretation, ...]:
    """Refuse every reading resting on a premise the boundary does not admit.

    I-05 forbids a text from expressing the premise, and a conclusion a text
    may state only by stating an inadmissible premise is the same prohibition
    one link along. Demoting one can demote its own dependents, so this runs to
    a fixed point; ``depends_on`` is finite and every pass strictly shrinks the
    admissible set, so it terminates.

    ``reclassified`` is what makes it safe to run at a re-entry as well as at
    the first execution: a record already on disk cannot be edited in place, so
    a demotion there is a new version of the same E-08 that says what it
    supersedes (§2.4 rule 3). Running it at a re-entry is not optional — a
    reclassified premise whose conclusion kept its old admissibility is exactly
    the stale form of a decision going on carrying the authority it lost.
    """

    built = list(members)
    while True:
        refused = {
            item.interpretation_id for item in built if not item.admissible
        }
        demoted = [
            _on_refused_premise(item, refused, reclassified=reclassified)
            if item.admissible and any(ref in refused for ref in item.depends_on)
            else item
            for item in built
        ]
        if demoted == built:
            return tuple(built)
        built = demoted


def _rule_checked(
    candidate: _Candidate,
    *,
    ladder: StrengthLadder,
    claims: Mapping[str, EvidenceClaim],
    usable: set[str],
    audience_claims: set[str],
    known: set[str],
    default_transfer: AudienceTransfer,
) -> Interpretation:
    transfer = _stricter(candidate.audience_transfer, default_transfer)
    # A level above the ladder's top is read as its top: the strongest thing
    # the ladder can express, which the ceiling comparison below then judges.
    # Both ends are bounded — pydantic refuses a level below 1.
    level = min(candidate.strength_level, len(ladder.levels))

    unresolved = _unresolved(candidate, claims=claims, usable=usable, known=known)
    # Nothing citable left means nothing to compute a ceiling from, so the
    # ceiling is the ladder's floor: the same posture S-01 takes for a claim
    # its own evidence does not establish.
    ceiling = (
        ladder.bottom
        if unresolved is not None
        else _ceiling(candidate, ladder=ladder, claims=claims)
    )

    if candidate.admissibility is Admissibility.INADMISSIBLE:
        # The probe already refused this reading and said why. Code narrows the
        # boundary; it does not relabel a judgment that was already made, so
        # the reason and the note stay the probe's and only the arithmetic is
        # made consistent: an inadmissible record stands above its ceiling only
        # where that is exactly what it is refused for.
        reason = candidate.reason or InadmissibleReason.OTHER
        return _record(
            candidate,
            transfer=transfer,
            strength=(
                ladder.at(level)
                if reason is InadmissibleReason.EXCEEDS_CEILING
                or level <= ceiling.level
                else ceiling
            ),
            ceiling=ceiling,
            admissibility=Admissibility.INADMISSIBLE,
            reason=reason,
            note=(
                candidate.temptation_note
                or "the probe tested this reading and the evidence refused it"
            ),
        )

    if unresolved is not None:
        return _record(
            candidate,
            transfer=transfer,
            strength=ladder.bottom,
            ceiling=ceiling,
            admissibility=Admissibility.INADMISSIBLE,
            reason=InadmissibleReason.UNSUPPORTED,
            note=unresolved,
        )

    if level > ceiling.level:
        return _record(
            candidate,
            transfer=transfer,
            strength=ladder.at(level),
            ceiling=ceiling,
            admissibility=Admissibility.INADMISSIBLE,
            reason=InadmissibleReason.EXCEEDS_CEILING,
            note=(
                f"asserted at level {level} on evidence that reaches level "
                f"{ceiling.level}; the stronger wording is the one a writer "
                "would reach for"
            ),
        )

    if (
        candidate.kind is InterpretationKind.CONSEQUENCE_FOR_READER
        and transfer is AudienceTransfer.DIRECT_AUDIENCE
        and not any(ref in audience_claims for ref in candidate.support_refs)
    ):
        return _record(
            candidate,
            transfer=transfer,
            strength=ladder.at(level),
            ceiling=ceiling,
            admissibility=Admissibility.INADMISSIBLE,
            reason=InadmissibleReason.TRANSFER_NOT_SUPPORTED,
            note=(
                "stated as a consequence for the configured reader on evidence "
                "the relevance screen did not scope to that reader"
            ),
        )

    return _record(
        candidate,
        transfer=transfer,
        strength=ladder.at(level),
        ceiling=ceiling,
        admissibility=Admissibility.ADMISSIBLE,
        reason=None,
        note=None,
    )


def _record(
    candidate: _Candidate,
    *,
    transfer: AudienceTransfer,
    strength: Strength,
    ceiling: Strength,
    admissibility: Admissibility,
    reason: Optional[InadmissibleReason],
    note: Optional[str],
) -> Interpretation:
    """One checked record, always at version 1.

    A first execution writes only version 1; every later version is a
    reclassification, and those are built in :func:`_recorded` from the record
    already on the boundary rather than from a fresh candidate.
    """

    return Interpretation(
        interpretation_id=candidate.identity,
        version=1,
        statement=candidate.statement,
        kind=candidate.kind,
        support_refs=candidate.support_refs,
        counter_refs=candidate.counter_refs,
        depends_on=candidate.depends_on,
        audience_transfer=transfer,
        strength=strength,
        ceiling=ceiling,
        admissibility=admissibility,
        rationale=candidate.rationale,
        limits=candidate.limits,
        inadmissible_reason=reason,
        temptation_note=note,
    )


def _unresolved(
    candidate: _Candidate,
    *,
    claims: Mapping[str, EvidenceClaim],
    usable: set[str],
    known: set[str],
) -> Optional[str]:
    """The first reference that does not resolve, as a sentence."""

    if not candidate.support_refs:
        return "cites no evidence claim at all"
    for ref in candidate.support_refs:
        if ref not in claims:
            return f"cites {ref}, which this core does not hold"
        if ref not in usable:
            return (
                f"cites {ref}, whose verdict is "
                f"{claims[ref].verdict.value}; only accepted and qualified "
                "claims may be referenced downstream of S-04 (E-03)"
            )
    for ref in (*candidate.counter_refs, *candidate.rationale.refs):
        if ref not in claims:
            return f"cites {ref}, which this core does not hold"
    for ref in candidate.depends_on:
        if ref not in known:
            return f"rests on {ref}, which this boundary does not list"
    return None


def _ceiling(
    candidate: _Candidate,
    *,
    ladder: StrengthLadder,
    claims: Mapping[str, EvidenceClaim],
) -> Strength:
    """The highest level this reading may be asserted at.

    The lowest ceiling among the supporting claims (E-08), and then Step 4 §7's
    two kind caps. A claim's own ceiling is never above its strength (E-03), so
    the minimum over the ceilings already carries "≤ the lowest strength among
    the supports".
    """

    supports = [claims[ref] for ref in candidate.support_refs]
    ceiling = supports[0].ceiling
    for claim in supports[1:]:
        ceiling = ladder.lower_of(ceiling, claim.ceiling)
    if candidate.kind is InterpretationKind.FORECAST or (
        candidate.kind is InterpretationKind.GENERALIZATION
        and len({ref for claim in supports for ref in claim.source_refs}) == 1
    ):
        ceiling = ladder.lower_of(ceiling, ladder.at(CAPPED_LEVEL))
    return ceiling


def _stricter(stated: AudienceTransfer, default: AudienceTransfer) -> AudienceTransfer:
    """AD-08: the #58 claim mode is the default, and code only narrows it."""

    return min(stated, default, key=_TRANSFER_ORDER.index)


def _on_refused_premise(
    item: Interpretation, refused: set[str], *, reclassified: bool
) -> Interpretation:
    fallen = sorted(ref for ref in item.depends_on if ref in refused)
    return replace(
        item,
        version=item.version + 1 if reclassified else item.version,
        supersedes=(
            f"{item.interpretation_id}.v{item.version}"
            if reclassified
            else item.supersedes
        ),
        admissibility=Admissibility.INADMISSIBLE,
        inadmissible_reason=InadmissibleReason.UNSUPPORTED,
        temptation_note=(
            "rests on "
            + ", ".join(fallen)
            + ", which the boundary does not admit; the conclusion reads as "
            "supported because its premise reads as stated"
        ),
    )


# ===========================================================================
# The re-entry's new member list
# ===========================================================================


def _recorded(
    *,
    boundary: InterpretationBoundary,
    core: EvidenceCore,
    ladder: StrengthLadder,
    answer: TestAnswer,
    matched: Optional[Interpretation],
) -> tuple[Optional[Interpretation], tuple[Interpretation, ...]]:
    """The new snapshot: the detected reading recorded as inadmissible.

    Rule 2 of the boundary commit for a reading the boundary never held — a new
    record at version 1 — and rule 3 for one it held: a new version of the same
    record, superseding the old one. Unchanged members are carried across at
    the exact versions they already have (rule 4).
    """

    claims = {item.evidence_claim_id: item for item in core.evidence_claims}
    usable = {item.evidence_claim_id for item in core.usable_claims}
    supports = tuple(
        ref for ref in dict.fromkeys(answer.support_refs) if ref in usable
    )
    if matched is not None:
        # A reclassification keeps the reading's own statement and supports:
        # what changed is which list it is in, not what it says.
        reclassified = replace(
            matched,
            version=matched.version + 1,
            supersedes=f"{matched.interpretation_id}.v{matched.version}",
            admissibility=Admissibility.INADMISSIBLE,
            inadmissible_reason=answer.reason,
            temptation_note=answer.temptation_note,
            # An admissible record is already at or under its ceiling, so this
            # changes nothing on the ordinary path. It matters for a record
            # already refused *for* over-reach whose reason now changes: the
            # one state `exceeds_ceiling` names is strength above the ceiling,
            # so a record that stops claiming it stops standing above it.
            strength=(
                matched.strength
                if answer.reason is InadmissibleReason.EXCEEDS_CEILING
                else ladder.lower_of(matched.strength, matched.ceiling)
            ),
        )
        return reclassified, _premise_checked(
            tuple(
                reclassified
                if member.interpretation_id == matched.interpretation_id
                else member
                for member in boundary.members
            ),
            # A member that rested on the reclassified reading loses its own
            # admissibility with it, and — because its record is already on
            # disk — it loses it as a new version rather than in place.
            reclassified=True,
        )

    if not answer.statement or answer.kind is None or not answer.rationale:
        # A new record is a record: without a statement, a kind and a
        # rationale there is nothing to write, and writing a placeholder would
        # put a reading into the boundary that nobody stated.
        return None, boundary.members

    identity = interpretation_id(core.core_id, len(boundary.members) + 1)
    discovered = Interpretation(
        interpretation_id=identity,
        version=1,
        statement=answer.statement,
        kind=answer.kind,
        support_refs=supports,
        audience_transfer=AudienceTransfer.BOUNDED_EXTERNAL_CASE,
        strength=ladder.bottom,
        ceiling=ladder.bottom,
        admissibility=Admissibility.INADMISSIBLE,
        rationale=Justification(
            text=answer.rationale,
            refs=tuple(ref for ref in answer.rationale_refs if ref in claims),
        ),
        inadmissible_reason=answer.reason,
        temptation_note=answer.temptation_note,
    )
    # No premise check here: the identity is new, and a member's `depends_on`
    # can only name a reading the boundary already listed, so nothing can rest
    # on this one yet.
    return discovered, (*boundary.members, discovered)


# ===========================================================================
# Requests, answers and outcomes
# ===========================================================================


def _generate_request(
    core: EvidenceCore,
    features: MaterialFeatures,
    assets: Sequence[Asset],
    audience: AudienceProfile,
    relevance: BoundaryInput,
    ladder: StrengthLadder,
) -> str:
    return json.dumps({
        "core": _core_request(core),
        "features": features.as_entity()["values"],
        "assets": [asset.as_entity() for asset in _evidentiary(assets)],
        "audience_profile": audience.for_stage(STAGE),
        "ladder": ladder.as_entity(),
        "relevance": relevance.as_entity(),
    })


def _probe_request(
    core: EvidenceCore,
    audience: AudienceProfile,
    generated: GenerateAnswer,
    families: Sequence[ProbeFamily],
) -> str:
    return json.dumps({
        "core": _core_request(core),
        "audience_profile": audience.for_stage(STAGE),
        "interpretations": [
            {"index": position, **item.model_dump(mode="json")}
            for position, item in enumerate(generated.interpretations, 1)
        ],
        "probe_families": [
            {"record_id": family.record_id, "name": family.name, "probe": family.probe}
            for family in families
        ],
    })


def _test_request(
    core: EvidenceCore,
    audience: AudienceProfile,
    boundary: InterpretationBoundary,
    detected: DetectedInterpretation,
) -> str:
    return json.dumps({
        "core": _core_request(core),
        "audience_profile": audience.for_stage(STAGE),
        "boundary": {
            "boundary_id": boundary.boundary_id,
            "version": boundary.version,
            "members": [
                {
                    "interpretation_id": member.interpretation_id,
                    "version": member.version,
                    "statement": member.statement,
                    "admissibility": member.admissibility.value,
                }
                for member in boundary.members
            ],
        },
        "detected": {
            "statement": detected.statement,
            "text_ref": detected.text_ref,
        },
    })


def _core_request(core: EvidenceCore) -> dict[str, Any]:
    """The core as the two calls see it: claims, observations and sources.

    No client position, no lens and no portfolio, here or anywhere else in
    these requests: "client rights to speak, lens and portfolio do **not**
    enter the boundary" (Step 1, E-09), and a request with nowhere to put one
    is how that is kept rather than remembered.
    """

    body = core.as_entity()
    return {
        "core_id": core.core_id,
        "version": core.version,
        "sources": body["sources"],
        "observations": body["observations"],
        "claims": body["evidence_claims"],
        "contradictions": body["contradictions"],
        "readiness": body["readiness"],
    }


def _evidentiary(assets: Sequence[Asset]) -> tuple[Asset, ...]:
    """E-06 without its positional assets.

    §1 lists E-06 among S-04's inputs, and Step 1 forbids client positions from
    entering the boundary. A positional asset *is* a client position, so the
    two are reconciled the only way that keeps both: the evidentiary assets go
    in and the positional ones do not.
    """

    return tuple(
        asset for asset in assets if asset.asset_class is not AssetClass.POSITIONAL
    )


def _answer(
    transport: BoundaryTransport,
    instructions: str,
    request: str,
    model: type[BaseModel],
) -> Any:
    """One call, parsed, or ``None``. Never the provider's own text."""

    try:
        raw = transport.complete(instructions=instructions, request=request)
    except Exception:  # noqa: BLE001 — sanitized, never the provider's text
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return model.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return None


def _probe_defect(
    probed: ProbeAnswer,
    generated: GenerateAnswer,
    families: Sequence[ProbeFamily],
) -> Optional[str]:
    """Why this probe answer is not one, or ``None`` when it is one.

    Coverage is the whole check. A probe that skipped a family or a proposed
    reading did not do the stage's second call, and recording its silence as
    "nothing found" would turn an unasked question into evidence of absence —
    which is the one thing patch R1's bounded completeness may not do.
    """

    declared = {family.record_id for family in families}
    answered = [family.record_id for family in probed.families]
    missing = sorted(declared - set(answered))
    if missing:
        return (
            "the probe answered no finding for " + ", ".join(missing) + "; a "
            "family that was not applied is not a family that found nothing"
        )
    unknown = sorted(set(answered) - declared)
    if unknown:
        return (
            "the probe answered for " + ", ".join(unknown) + ", which is not in "
            "this run's checklist"
        )
    if len(answered) != len(set(answered)):
        return "the probe answered for one family twice"

    expected = set(range(1, len(generated.interpretations) + 1))
    judged = [verdict.index for verdict in probed.verdicts]
    if sorted(judged) != sorted(expected) or len(judged) != len(set(judged)):
        return (
            "the probe returned "
            f"{len(judged)} verdict(s) for "
            f"{len(generated.interpretations)} proposed interpretation(s); U-1 "
            "tests every generated one, and an untested reading is not an "
            "admissible one"
        )
    for verdict in probed.verdicts:
        inadmissible = verdict.admissibility is Admissibility.INADMISSIBLE
        if inadmissible and (
            verdict.reason is None
            or verdict.temptation_note is None
            or not verdict.temptation_note.strip()
        ):
            return (
                f"the probe refused interpretation {verdict.index} without a "
                "reason and a temptation note; §1 Post gives every inadmissible "
                "one both"
            )
    return None


def _reader_connection(
    core: EvidenceCore, answer: Optional[TextWithRefs]
) -> Optional[ReaderConnection]:
    """The connection, with only the claims this core holds behind it."""

    if answer is None or not answer.text.strip():
        return None
    refs = _held(answer.refs, core)
    if not refs:
        # A connection to the reader is a claim about the material, so it is
        # held to the same rule as every other: cited, or not made.
        return None
    return ReaderConnection(text=answer.text, refs=refs)


def _held(refs: Sequence[str], core: EvidenceCore) -> tuple[str, ...]:
    usable = {item.evidence_claim_id for item in core.usable_claims}
    return tuple(ref for ref in dict.fromkeys(refs) if ref in usable)


def _ambiguities(
    core: EvidenceCore,
    generated: GenerateAnswer,
    members: Sequence[Interpretation],
) -> tuple[Ambiguity, ...]:
    contradictions = {item.contradiction_id for item in core.contradictions}
    return tuple(
        Ambiguity(
            ambiguity_id=ambiguity_id(core.core_id, position),
            text=item.text,
            interpretation_refs=tuple(
                members[index - 1].interpretation_id
                for index in dict.fromkeys(item.interpretation_refs)
                if 1 <= index <= len(members)
            ),
            contradiction_ref=(
                item.contradiction_ref
                if item.contradiction_ref in contradictions
                else None
            ),
        )
        for position, item in enumerate(generated.ambiguities, 1)
    )


def _stage_outcome(
    signal_id: str,
    members: Sequence[Interpretation],
    connection: Optional[ReaderConnection],
) -> OutcomeRecord:
    """§1's ARP column, in the order it reads.

    "No admissible interpretation → ``SKIP`` signal (terminal; walkthrough C)"
    — and a boundary with no reader connection is the same finding said the
    other way round, because §1 Post allows an absent connection only with a
    ``SKIP``. "Only low-strength interpretations → ``DEGRADE``" comes after,
    and a boundary that cleared both resolves.
    """

    admissible = [member for member in members if member.admissible]
    if not admissible:
        return _skip(
            signal_id,
            StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
            "no admissible interpretation for the reader: "
            f"{len(members)} reading(s) were generated or tested and the "
            "evidence admitted none",
        )
    if connection is None:
        return _skip(
            signal_id,
            StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
            "no admissible interpretation for the reader: the material "
            "establishes no connection to the configured audience",
        )
    if all(member.strength.level <= LOW_STRENGTH_LEVEL for member in admissible):
        return OutcomeRecord(
            outcome=ArpOutcome.DEGRADE,
            state_code=StateCode.ONLY_LOW_STRENGTH_INTERPRETATION,
            scope=OutcomeScope.SIGNAL,
            scope_key=signal_id,
            reason=(
                "every admissible interpretation sits at the ladder's weakest "
                "level; the boundary proceeds with low confidence recorded"
            ),
        )
    return OutcomeRecord(
        outcome=ArpOutcome.RESOLVE,
        state_code=StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
        scope=OutcomeScope.SIGNAL,
        scope_key=signal_id,
        reason=(
            f"{len(admissible)} admissible interpretation(s), "
            f"{len(members) - len(admissible)} recorded as inadmissible"
        ),
    )


def _spend(
    budget: Optional[CallBudget],
    scope_key: str,
    *,
    scope: OutcomeScope = OutcomeScope.SIGNAL,
) -> Optional[OutcomeRecord]:
    if budget is None:
        return None
    return budget.spend(scope=scope, scope_key=scope_key)


def _skip(
    scope_key: str,
    state_code: StateCode,
    reason: str,
    *,
    scope: OutcomeScope = OutcomeScope.SIGNAL,
) -> OutcomeRecord:
    return OutcomeRecord(
        outcome=ArpOutcome.SKIP,
        state_code=state_code,
        scope=scope,
        scope_key=scope_key,
        reason=reason,
    )
