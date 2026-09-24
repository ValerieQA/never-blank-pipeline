"""S-01 · Evidence Core v1, built from real research (Issue #299, slice SL-3).

The stage that turns retrieval into something later stages may reason from.
Step 2 §1 gives it one authority: build the core — source observations,
evidence claims with verdicts, uncertainties, contradictions — and then let the
#58 screen say whether the material is relevant at all. "It must not interpret,
and it must not pick an angle", so nothing here reads meaning into the material
and nothing here produces anything an angle could be taken from.

This module is the first half: research and the core. The relevance screen is
:mod:`src.editorial_core.relevance_screen`, and the two are ordered by their
types rather than by a comment — the screen takes an :class:`EvidenceCore`, so
there is no way to screen relevance before the core exists.

What it does, in the order it does it
-------------------------------------
1. **Retrieval, by code.** The existing lifecycle, reused whole:
   ``execute_and_persist_research`` runs the adapters, writes the create-once
   ``research.json`` and strict-reloads it. What S-01 asks of it that production
   does not is ``require_ready=False``: the Release 1 gate stops a run that is
   not READY, and Step 2 §1 gives that decision to the ARP instead, where
   ``needs_review`` continues and only a core with no usable claim is a ``SKIP``.
   Every other check the lifecycle makes — identity, lineage, timestamps,
   canonical form — is unconditional and untouched.
2. **The extended assessment, by model.** One call (§1, Calls (a)), which is
   the existing ``assess_artifact`` call carrying two more classifications:
   per observation ``kind``, ``figure`` and ``is_third_party_assertion``, and
   per claim ``scope`` and ``strength``. It is one call and not two because
   :class:`ExtendedEvidenceAssessor` is a wrap of the #125 judgment transport:
   ``assess_artifact`` still decides which records need judging, still rejects
   the ones that cannot be assessed structurally, still derives readiness and
   still attributes only the work it did. The extension rides on the same
   response.
3. **The core, by code.** Observations are **built** from the artifact's own
   support references, one per reference, and the model only classifies them —
   so an observation that no source recorded cannot be invented into the core
   (I-03 at source). Attribution is code-generated from the source and the
   excerpt, never model-written (E-02). The ceiling is the lower of the client
   ceiling and the strength the evidence reached, which is arithmetic and
   therefore code's.

**Strength is a position on one ladder per run** (AD-10). The ladder is an
input, not something this stage chooses: it is the client contract's
``claim_strength_ceiling`` where one is declared and the universal default
(``knowledge/ladders/default.md``, parsed by :mod:`src.knowledge.ladder`)
otherwise. A stage that picked its own ladder would make two runs' strengths
incomparable.

**AD-05 is preserved.** E-02, E-03 and E-04 *wrap* the existing research
contract rather than replacing it: ``ExtractedEvidence.claim`` becomes
``evidence_claim.statement``, the serialized artifact is unchanged, and
``research.json`` stays the artifact of record that the core references by ID
and digest.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §1 (S-01)
and §7 (R-1); ``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §0.3
and §2 (E-02, E-03, E-04); ``docs/editorial/architecture/02_ARCHITECTURE_DECISIONS.md``
AD-05 and AD-10; ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md``
§2.2 and §2.3.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.editorial.decision_contract import research_artifact_digest
from src.editorial_core.arp import (
    ArpOutcome,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)

# The budget protocol is stated once, in the stage that first needed it: the
# core says what it needs of a budget and the run harness supplies it. A second
# declaration of the same protocol would eventually be a second contract.
from src.editorial_core.signal_selection import CallBudget
from src.research.assessment import (
    JUDGMENT_INSTRUCTIONS,
    USABLE_DISPOSITIONS,
    EvidenceAssessmentError,
    EvidenceJudgmentTransport,
)
from src.research.evidence import (
    Contradiction,
    EvidenceDisposition,
    EvidenceReadiness,
    NormalizedResearchArtifact,
    NormalizedSource,
    UncertaintyAssessment,
)
from src.research.lifecycle import ResearchGateError, execute_and_persist_research
from src.research.provider import ResearchProvider, ResearchProviderRequest
from src.strategy.execution_context import ConfigurationIdentity

#: The stage this module is, as the topology registry and §2.3 spell it. The
#: relevance screen is the other half of the same stage and imports it.
STAGE: Final[str] = "S-01"

#: The version of the core S-01 produces. It is the sole producer of v1; S-03
#: produces every later version (§2.3).
CORE_VERSION: Final[int] = 1

#: What code writes where a claim nobody assessed still has to say something.
#: No usable claim may carry either: a claim the assessment never reached is
#: ``rejected`` or ``not_assessed``, and E-03's usability rule keeps it out of
#: every stage after S-04. Stating the absence beats inventing a scope.
UNASSESSED_SCOPE: Final[str] = (
    "not established: this claim was never assessed against its own support"
)
UNASSESSED_RATIONALE: Final[str] = "not assessed: no verdict was recorded"


class EvidenceCoreError(RuntimeError):
    """S-01 was asked for a core its contract cannot honestly build."""


# ===========================================================================
# The vocabularies (Step 1 §2, E-02 and E-03)
# ===========================================================================


class ObservationKind(str, Enum):
    """What an excerpt *is* — never what it proves (E-02).

    ``OTHER`` is also what an unclassified observation gets: a claim the
    assessment never reached has excerpts all the same, and they enter the core
    as observations because nothing may enter it any other way (I-03).
    """

    QUOTE = "quote"
    FIGURE = "figure"
    EVENT = "event"
    STATED_POSITION = "stated_position"
    DOCUMENT_FACT = "document_fact"
    OTHER = "other"


class FigureProvenance(str, Enum):
    """Whether the source produced the figure or is repeating one (E-02)."""

    OWN = "own"
    THIRD_PARTY = "third_party"


# ===========================================================================
# Strength and the ladder (Step 1 §0.3, AD-10)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class Strength:
    """A position on the run's one ladder: its ID and an ordinal index.

    Carries the ladder ID rather than only the index, because an index without
    the ladder it indexes cannot be read — and two runs on different ladders
    must not compare by accident.
    """

    ladder_id: str
    level: int

    def __post_init__(self) -> None:
        if not self.ladder_id.strip():
            raise EvidenceCoreError(
                "a strength is a position on a named ladder; an index with no "
                "ladder cannot be read back"
            )
        if self.level < 1:
            raise EvidenceCoreError(
                f"strength level {self.level} is below the ladder's first level; "
                "a ladder is numbered from 1 upwards, weakest first"
            )

    def as_entity(self) -> dict[str, Any]:
        return {"ladder_id": self.ladder_id, "level": self.level}


@dataclass(frozen=True, slots=True)
class StrengthLadder:
    """The run's ordered wording levels, weakest first (Step 1 §0.3).

    One per run, and an input of the stage rather than a choice it makes: the
    client contract's ``claim_strength_ceiling`` where one is declared, the
    universal default otherwise.
    """

    ladder_id: str
    levels: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.ladder_id.strip():
            raise EvidenceCoreError("a ladder is named by its record ID")
        if len(self.levels) < 2:
            raise EvidenceCoreError(
                f"{self.ladder_id} declares {len(self.levels)} level(s); one "
                "level is not a ladder, and nothing can be weaker than it"
            )
        if any(not level.strip() for level in self.levels):
            raise EvidenceCoreError(
                f"{self.ladder_id} declares a level with no wording; a level is "
                "what a writer may say, so an unworded one says nothing"
            )
        if len(set(self.levels)) != len(self.levels):
            raise EvidenceCoreError(
                f"{self.ladder_id} declares one wording at two levels; two "
                "levels that read alike are not two strengths"
            )

    @property
    def bottom(self) -> Strength:
        """The weakest level. What a claim its own evidence does not support
        reaches, and the floor code applies rather than the model."""

        return Strength(self.ladder_id, 1)

    @property
    def top(self) -> Strength:
        return Strength(self.ladder_id, len(self.levels))

    def at(self, level: int) -> Strength:
        """The named level, or an error. A level the ladder does not have is
        not a strength it can place."""

        if not 1 <= level <= len(self.levels):
            raise EvidenceCoreError(
                f"level {level} is outside {self.ladder_id}, which has "
                f"{len(self.levels)} level(s)"
            )
        return Strength(self.ladder_id, level)

    def wording(self, strength: Strength) -> str:
        """What a claim at this strength may be worded as."""

        self._same_ladder(strength)
        return self.levels[strength.level - 1]

    def lower_of(self, first: Strength, second: Strength) -> Strength:
        """The lower of two positions — the ceiling rule of E-03 and E-08.

        A minimum and not a judgment, which is why it is code's: AD-10 exists
        so that "the ceiling is the lower of the client's and the evidence's"
        is arithmetic on one ordered ladder.
        """

        self._same_ladder(first)
        self._same_ladder(second)
        return first if first.level <= second.level else second

    def as_entity(self) -> dict[str, Any]:
        return {"ladder_id": self.ladder_id, "levels": list(self.levels)}

    def _same_ladder(self, strength: Strength) -> None:
        if strength.ladder_id != self.ladder_id:
            raise EvidenceCoreError(
                f"strength on ladder {strength.ladder_id!r} compared against "
                f"{self.ladder_id!r}; AD-10 gives a run one ladder, and "
                "positions on two of them are not comparable"
            )


# ===========================================================================
# E-02 · Source observation
# ===========================================================================


@dataclass(frozen=True, slots=True)
class Figure:
    """A figure an observation records (E-02).

    ``value`` is kept as the excerpt states it. Turning "$530 million" into a
    number is a calculation, calculations are S-02's and their inputs must all
    be in the core — so the core carries what the source said.
    """

    value: str
    provenance: FigureProvenance
    unit: Optional[str] = None
    as_of: Optional[date] = None

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise EvidenceCoreError("a figure with no value is not a figure")

    def as_entity(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "as_of": None if self.as_of is None else self.as_of.isoformat(),
            "figure_provenance": self.provenance.value,
        }


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """``E-02``: what one source recorded, attributed to that source.

    Never a statement about the world. The claim is E-03's, and the link
    between them is what I-04's lower half checks.
    """

    observation_id: str
    signal_id: str
    source_ref: str
    kind: ObservationKind
    excerpt: str
    #: The "source X reports Y" form, generated by :func:`build_attribution`
    #: from the source and the excerpt. Never model-written: an attribution a
    #: model composed could attribute an excerpt to a source that never
    #: carried it, which is the one thing this field exists to rule out.
    attribution: str
    is_third_party_assertion: bool
    location: Optional[str] = None
    figure: Optional[Figure] = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("observation_id", self.observation_id),
            ("signal_id", self.signal_id),
            ("source_ref", self.source_ref),
            ("excerpt", self.excerpt),
            ("attribution", self.attribution),
        ):
            if not value.strip():
                raise EvidenceCoreError(
                    f"observation {self.observation_id!r} states nothing for "
                    f"{field_name}; an observation with no source, no excerpt or "
                    "no attribution is a fact with no provenance (I-03)"
                )
        if (self.kind is ObservationKind.FIGURE) != (self.figure is not None):
            raise EvidenceCoreError(
                f"observation {self.observation_id!r} is kind "
                f"{self.kind.value!r} and "
                + ("carries" if self.figure is not None else "carries no")
                + " figure; E-02 requires one for a figure and admits one for "
                "nothing else"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "signal_id": self.signal_id,
            "source_ref": self.source_ref,
            "kind": self.kind.value,
            "excerpt": self.excerpt,
            "location": self.location,
            "attribution": self.attribution,
            "figure": None if self.figure is None else self.figure.as_entity(),
            "is_third_party_assertion": self.is_third_party_assertion,
        }


def build_attribution(source: NormalizedSource, excerpt: str) -> str:
    """The E-02 attribution, from the source and the excerpt alone.

    Deterministic, and derived from two fields a model never touched. The
    publisher names the institution where there is one and the title names the
    document otherwise; the excerpt's whitespace is collapsed because this is
    the one-line form, and the verbatim excerpt is carried beside it.
    """

    label = (source.publisher or source.title).strip()
    return f"{label} reports: {' '.join(excerpt.split())}"


def observation_id(evidence_claim_id: str, index: int) -> str:
    """The ID of the ``index``-th support reference of one claim.

    Positional over the claim's own support list, whose order the research
    contract preserves and documents. Used by both the assessor that asks the
    model to classify an observation and the builder that turns it into one, so
    the two cannot drift into naming different things.
    """

    return f"obs-{evidence_claim_id}-{index}"


# ===========================================================================
# E-03 · Evidence claim
# ===========================================================================


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    """``E-03``: a statement about the world, grounded and judged.

    ``statement`` is ``ExtractedEvidence.claim`` (AD-05: mapped, never renamed
    in place), and ``verdict`` is the existing ``EvidenceDisposition``.
    """

    evidence_claim_id: str
    statement: str
    observation_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    verdict: EvidenceDisposition
    verdict_rationale: str
    scope: str
    strength: Strength
    ceiling: Strength
    caveats: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.observation_refs:
            raise EvidenceCoreError(
                f"claim {self.evidence_claim_id!r} cites no observation; a "
                "statement about the world with nothing observed behind it is "
                "fabrication (I-04)"
            )
        if not self.source_refs:
            raise EvidenceCoreError(
                f"claim {self.evidence_claim_id!r} cites no source"
            )
        for field_name, value in (
            ("statement", self.statement),
            ("verdict_rationale", self.verdict_rationale),
            ("scope", self.scope),
        ):
            if not value.strip():
                raise EvidenceCoreError(
                    f"claim {self.evidence_claim_id!r} states nothing for "
                    f"{field_name}, which E-03 requires of every claim"
                )
        if self.verdict is EvidenceDisposition.QUALIFIED and not self.caveats:
            raise EvidenceCoreError(
                f"claim {self.evidence_claim_id!r} is qualified and names no "
                "caveat; a qualification whose limitation is not written down "
                "is an acceptance (E-03)"
            )
        if self.ceiling.ladder_id != self.strength.ladder_id:
            raise EvidenceCoreError(
                f"claim {self.evidence_claim_id!r} has its strength on ladder "
                f"{self.strength.ladder_id!r} and its ceiling on "
                f"{self.ceiling.ladder_id!r}; AD-10 gives a run one ladder"
            )
        if self.ceiling.level > self.strength.level:
            raise EvidenceCoreError(
                f"claim {self.evidence_claim_id!r} has ceiling level "
                f"{self.ceiling.level} above strength level "
                f"{self.strength.level}; the ceiling is the lower of the client "
                "ceiling and the strength the evidence reached, so it can never "
                "be above it"
            )
        if self.usable and (
            self.scope == UNASSESSED_SCOPE
            or self.verdict_rationale == UNASSESSED_RATIONALE
        ):
            raise EvidenceCoreError(
                f"claim {self.evidence_claim_id!r} is {self.verdict.value} and "
                "carries the text code writes for a claim nobody assessed; a "
                "usable claim carries the assessor's own scope and rationale"
            )

    @property
    def usable(self) -> bool:
        """E-03's usability rule: only ``accepted`` and ``qualified`` may be
        referenced downstream of S-04. The same set as ``_USABLE_DISPOSITIONS``
        was, read from the module that owns it."""

        return self.verdict in USABLE_DISPOSITIONS

    def as_entity(self) -> dict[str, Any]:
        return {
            "evidence_claim_id": self.evidence_claim_id,
            "statement": self.statement,
            "observation_refs": list(self.observation_refs),
            "source_refs": list(self.source_refs),
            "verdict": self.verdict.value,
            "verdict_rationale": self.verdict_rationale,
            "caveats": list(self.caveats),
            "scope": self.scope,
            "strength": self.strength.as_entity(),
            "ceiling": self.ceiling.as_entity(),
            "usable": self.usable,
        }


# ===========================================================================
# E-04 · Evidence Core
# ===========================================================================


@dataclass(frozen=True, slots=True)
class EvidenceCore:
    """``E-04``: everything known about the signal, with provenance.

    The only source of facts for every later stage (I-03), which is why its
    referential integrity is checked here rather than trusted: a reference that
    does not resolve is how a fact with no source reaches a text.
    """

    core_id: str
    version: int
    signal_ids: tuple[str, ...]
    #: ``(artifact_id, digest)`` per wrapped ``NormalizedResearchArtifact``.
    #: The digest is the existing ``research_artifact_digest``, so the core and
    #: the #58 decision reference the artifact the same way.
    research_artifact_refs: tuple[tuple[str, str], ...]
    sources: tuple[NormalizedSource, ...]
    observations: tuple[SourceObservation, ...]
    evidence_claims: tuple[EvidenceClaim, ...]
    readiness: EvidenceReadiness
    uncertainties: tuple[UncertaintyAssessment, ...] = ()
    contradictions: tuple[Contradiction, ...] = ()
    closed_gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.core_id.strip():
            raise EvidenceCoreError("a core is identified by its core ID")
        if self.version < 1:
            raise EvidenceCoreError(
                f"core version {self.version} is below 1; S-01 produces v1 and "
                "S-03 every version after it"
            )
        if not self.signal_ids:
            raise EvidenceCoreError(
                "a core is about at least one signal (AD-04: exactly one in "
                "current behaviour)"
            )
        if not self.research_artifact_refs:
            raise EvidenceCoreError(
                "a core states which research artifact(s) it wraps, by ID and "
                "digest; a core that names none cannot be checked against one"
            )
        if not self.sources:
            raise EvidenceCoreError("a core with no source has no provenance")
        self._references_resolve()

    @property
    def usable_claims(self) -> tuple[EvidenceClaim, ...]:
        """The claims later stages may reference (E-03's usability rule).

        Empty is the state Step 2 §1 skips the signal for: it is the one thing
        S-01 says about the *material* rather than about the machinery.
        """

        return tuple(claim for claim in self.evidence_claims if claim.usable)

    def as_entity(self) -> dict[str, Any]:
        """The entity body written to ``signal/core/core.v1.json`` (§2.2)."""

        return {
            "entity_type": "E-04",
            "entity_id": self.core_id,
            "core_id": self.core_id,
            "version": self.version,
            "signal_ids": list(self.signal_ids),
            "research_artifact_refs": [
                {"artifact_id": artifact_id, "digest": digest}
                for artifact_id, digest in self.research_artifact_refs
            ],
            "sources": [source.model_dump(mode="json") for source in self.sources],
            "observations": [
                observation.as_entity() for observation in self.observations
            ],
            "evidence_claims": [claim.as_entity() for claim in self.evidence_claims],
            "uncertainties": [
                item.model_dump(mode="json") for item in self.uncertainties
            ],
            "contradictions": [
                item.model_dump(mode="json") for item in self.contradictions
            ],
            "readiness": self.readiness.value,
            "closed_gaps": list(self.closed_gaps),
        }

    # ------------------------------------------------------------------
    # Referential integrity
    # ------------------------------------------------------------------

    def _references_resolve(self) -> None:
        source_ids = _unique("source", (item.source_id for item in self.sources))
        observation_ids = _unique(
            "observation", (item.observation_id for item in self.observations)
        )
        claim_ids = _unique(
            "evidence claim", (item.evidence_claim_id for item in self.evidence_claims)
        )
        _unique(
            "core entity",
            (*source_ids, *observation_ids, *claim_ids),
        )

        signals = set(self.signal_ids)
        for observation in self.observations:
            _resolves(
                f"observation {observation.observation_id!r} source",
                (observation.source_ref,),
                set(source_ids),
            )
            if observation.signal_id not in signals:
                raise EvidenceCoreError(
                    f"observation {observation.observation_id!r} is about signal "
                    f"{observation.signal_id!r}, which this core is not about "
                    "(AD-04 keeps the signal per observation)"
                )

        by_id = {item.observation_id: item for item in self.observations}
        for claim in self.evidence_claims:
            _resolves(
                f"claim {claim.evidence_claim_id!r} observations",
                claim.observation_refs,
                set(observation_ids),
            )
            _resolves(
                f"claim {claim.evidence_claim_id!r} sources",
                claim.source_refs,
                set(source_ids),
            )
            observed = {by_id[ref].source_ref for ref in claim.observation_refs}
            if observed != set(claim.source_refs):
                raise EvidenceCoreError(
                    f"claim {claim.evidence_claim_id!r} cites sources "
                    f"{sorted(set(claim.source_refs))!r} and observations from "
                    f"{sorted(observed)!r}; E-03 keeps the two consistent, "
                    "because a source cited without an observation behind it is "
                    "a citation with nothing under it"
                )

        for item in self.uncertainties:
            _resolves(
                f"uncertainty {item.uncertainty_id!r} claims",
                item.evidence_ids,
                set(claim_ids),
            )
            _resolves(
                f"uncertainty {item.uncertainty_id!r} sources",
                item.source_ids,
                set(source_ids),
            )
        for item in self.contradictions:
            _resolves(
                f"contradiction {item.contradiction_id!r} claims",
                item.evidence_ids,
                set(claim_ids),
            )
            _resolves(
                f"contradiction {item.contradiction_id!r} sources",
                item.source_ids,
                set(source_ids),
            )


def _unique(kind: str, values: Any) -> tuple[str, ...]:
    collected = tuple(values)
    duplicated = sorted({item for item in collected if collected.count(item) > 1})
    if duplicated:
        raise EvidenceCoreError(
            f"{kind} ID(s) used twice in one core: {', '.join(duplicated)}; a "
            "reference to one of them would name neither"
        )
    return collected


def _resolves(label: str, references: Sequence[str], known: set[str]) -> None:
    missing = sorted(set(references) - known)
    if missing:
        raise EvidenceCoreError(
            f"{label} reference(s) that are not in the core: "
            f"{', '.join(missing)}. The core is the only source of facts "
            "(I-03), so a reference out of it points at nothing"
        )


# ===========================================================================
# The extended assessment (§1, Calls (a))
# ===========================================================================


class _AssessmentModel(BaseModel):
    """The extension is parsed strictly, or it is not an assessment."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FigureAssessment(_AssessmentModel):
    """The figure an observation records, as the model read it off the excerpt."""

    value: str = Field(min_length=1, max_length=200)
    provenance: FigureProvenance
    unit: Optional[str] = Field(default=None, max_length=80)
    #: ``None`` when the excerpt states no date. Required to be a real date
    #: when it states one, because a figure's as-of is checkable or absent.
    as_of: Optional[date] = None


class ObservationAssessment(_AssessmentModel):
    """One observation classified: what the excerpt is, and whose claim it is."""

    observation_id: str = Field(min_length=1)
    kind: ObservationKind
    is_third_party_assertion: bool
    figure: Optional[FigureAssessment] = None

    @model_validator(mode="after")
    def _figure_belongs_to_a_figure(self) -> "ObservationAssessment":
        if (self.kind is ObservationKind.FIGURE) != (self.figure is not None):
            raise ValueError(
                f"{self.observation_id} is kind {self.kind.value!r} and "
                + ("carries" if self.figure is not None else "carries no")
                + " figure; E-02 requires one for a figure and admits one for "
                "nothing else"
            )
        return self


class ClaimAssessment(_AssessmentModel):
    """One claim's scope and the ladder level its own support reaches."""

    evidence_claim_id: str = Field(min_length=1)
    scope: str = Field(min_length=1, max_length=600)
    strength_level: int = Field(ge=1)


class ExtendedAssessment(_AssessmentModel):
    """The E-02 and E-03 classifications one extended assessment returned."""

    claims: tuple[ClaimAssessment, ...] = ()
    observations: tuple[ObservationAssessment, ...] = ()

    @model_validator(mode="after")
    def _answers_each_thing_once(self) -> "ExtendedAssessment":
        for label, identities in (
            ("claim", [item.evidence_claim_id for item in self.claims]),
            ("observation", [item.observation_id for item in self.observations]),
        ):
            if len(set(identities)) != len(identities):
                raise ValueError(
                    f"the assessment classifies one {label} twice; two answers "
                    "about one thing are not an assessment of it"
                )
        return self

    def claim(self, evidence_claim_id: str) -> Optional[ClaimAssessment]:
        for item in self.claims:
            if item.evidence_claim_id == evidence_claim_id:
                return item
        return None

    def observation(self, identity: str) -> Optional[ObservationAssessment]:
        for item in self.observations:
            if item.observation_id == identity:
                return item
        return None


#: What the extension asks for, beside the verdict the #125 instructions
#: already define. Appended to those rather than restating them: the verdict
#: rules have one home, and a second copy of them would be a second policy.
EXTENSION_INSTRUCTIONS = """\

Two more classifications are asked for in the same answer. They do not change
the verdict rules above, and they never decide a verdict.

For each observation — one bounded excerpt cited as support — return:

  kind: quote | figure | event | stated_position | document_fact | other.
        What the excerpt *is*, not what it proves.
  is_third_party_assertion: true when the source is reporting somebody else's
        claim about the world rather than recording something itself.
  figure: required when kind is "figure", and null for every other kind. The
        value exactly as the excerpt states it, the unit if the excerpt states
        one, the as-of date as YYYY-MM-DD if the excerpt states one and null if
        it does not, and provenance "own" when the source produced or measured
        the figure itself, "third_party" when it is repeating someone else's.

For each claim, return:

  scope: who, where and when the claim holds, in one sentence, taken from the
        cited support and never widened past it. A later stage checks whether a
        claim carries to a configured audience, and that check reads this field.
  strength_level: the level of `strength_ladder` in this request that the cited
        support actually reaches, judged by that level's own wording. Never the
        level the claim would need: a claim that would need level 3 and whose
        support reaches level 1 is level 1.

Return ONLY one valid JSON object, no text outside it, with exactly these three
keys:

{"verdicts": [{"evidence_id": "...", "disposition": "accepted | qualified | rejected", "rationale": "one bounded sentence, checkable against the excerpt"}],
 "claims": [{"evidence_claim_id": "...", "scope": "...", "strength_level": 1}],
 "observations": [{"observation_id": "...", "kind": "quote", "is_third_party_assertion": false, "figure": null}]}
"""


def extended_instructions() -> str:
    """The #125 judgment instructions, extended. One call, one instruction."""

    return JUDGMENT_INSTRUCTIONS + EXTENSION_INSTRUCTIONS


class ExtendedEvidenceAssessor:
    """The extended assessment, as a wrap of the #125 judgment transport.

    Handed to ``execute_and_persist_research`` as its ``judgment_transport``,
    so ``assess_artifact`` runs exactly as it does in production — it decides
    which records need a judgment, rejects the ones no model can assess,
    derives readiness from the result and attributes only the work it did —
    while the one request it causes also returns the E-02 and E-03
    classifications the core needs. That is what makes this **one** call and
    not two (§1, Calls).

    The base request names each claim and its support excerpts in the
    artifact's own order, which is the order the research contract preserves;
    the observation IDs are :func:`observation_id` over that order, so the
    model classifies exactly the observations the builder will create and can
    invent no others.

    Two things it deliberately does not do: it does not decide a verdict (the
    response's verdicts go to ``assess_artifact``, whose structural rejections
    still overrule them), and it does not retry. An assessment asked twice
    fails closed twice.
    """

    def __init__(
        self, transport: EvidenceJudgmentTransport, *, ladder: StrengthLadder
    ) -> None:
        self._transport = transport
        self._ladder = ladder
        self._assessment: Optional[ExtendedAssessment] = None
        self._failure: Optional[str] = None
        self._calls = 0

    @property
    def assessment(self) -> Optional[ExtendedAssessment]:
        """What the one call classified, or ``None`` if it was never made."""

        return self._assessment

    @property
    def failure(self) -> Optional[str]:
        """Why the extension was not usable, in this module's own words.

        ``assess_artifact`` normalizes everything a transport raises into one
        ``EvidenceAssessmentError`` naming the exception type, which is the
        right boundary for it and loses what was wrong. Recorded here so the
        stage's ``SKIP`` can say it.
        """

        return self._failure

    @property
    def calls(self) -> int:
        return self._calls

    def complete(self, *, instructions: str, request: str) -> str:
        """Make the one call, keep the extension, return the verdicts.

        ``instructions`` is the #125 text this extends and is replaced by
        :func:`extended_instructions`; the base ``request`` is read for the
        claims and support it names, because that is the whole material the
        judgment is allowed to see.
        """

        self._calls += 1
        try:
            items = _base_request_items(request)
        except (KeyError, TypeError, ValueError) as exc:
            raise self._refuse(
                "the evidence judgment request could not be read"
            ) from exc

        raw = self._transport.complete(
            instructions=extended_instructions(),
            request=self._extended_request(items),
        )
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(payload, dict):
                raise TypeError("the extended assessment is not a JSON object")
            assessment = ExtendedAssessment.model_validate({
                "claims": payload.get("claims", ()),
                "observations": payload.get("observations", ()),
            })
            verdicts = payload["verdicts"]
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise self._refuse(
                "the extended assessment output does not satisfy the "
                "assessment contract"
            ) from exc

        self._check_covers(items, assessment)
        self._assessment = assessment
        # Only the verdicts go back: `assess_artifact` owns the disposition, and
        # a record it rejected structurally keeps that rejection whatever the
        # model said about it.
        return json.dumps({"verdicts": verdicts}, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extended_request(self, items: Sequence[Mapping[str, Any]]) -> str:
        return json.dumps(
            {
                "strength_ladder": {
                    "ladder_id": self._ladder.ladder_id,
                    "levels": [
                        {"level": index, "wording": wording}
                        for index, wording in enumerate(self._ladder.levels, 1)
                    ],
                },
                "claims": [
                    {
                        "evidence_claim_id": item["evidence_id"],
                        "statement": item["claim"],
                        "observations": [
                            {
                                "observation_id": observation_id(
                                    item["evidence_id"], index
                                ),
                                "excerpt": excerpt,
                            }
                            for index, excerpt in enumerate(item["support"], 1)
                        ],
                    }
                    for item in items
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _check_covers(
        self, items: Sequence[Mapping[str, Any]], assessment: ExtendedAssessment
    ) -> None:
        """Everything asked about is answered, and nothing else is."""

        asked_claims = {str(item["evidence_id"]) for item in items}
        asked_observations = {
            observation_id(str(item["evidence_id"]), index)
            for item in items
            for index, _ in enumerate(item["support"], 1)
        }
        answered_claims = {item.evidence_claim_id for item in assessment.claims}
        answered_observations = {
            item.observation_id for item in assessment.observations
        }
        for label, asked, answered in (
            ("claim", asked_claims, answered_claims),
            ("observation", asked_observations, answered_observations),
        ):
            unanswered = sorted(asked - answered)
            if unanswered:
                raise self._refuse(
                    f"the extended assessment classified no {label} "
                    + ", ".join(unanswered)
                )
            invented = sorted(answered - asked)
            if invented:
                raise self._refuse(
                    f"the extended assessment classified {label}(s) the request "
                    "does not contain: " + ", ".join(invented)
                )
        for item in assessment.claims:
            if item.strength_level > len(self._ladder.levels):
                raise self._refuse(
                    f"claim {item.evidence_claim_id} is placed at strength level "
                    f"{item.strength_level}, and {self._ladder.ladder_id} has "
                    f"{len(self._ladder.levels)} level(s)"
                )

    def _refuse(self, detail: str) -> EvidenceCoreError:
        self._failure = detail
        self._assessment = None
        return EvidenceCoreError(detail)


def _base_request_items(request: str) -> tuple[Mapping[str, Any], ...]:
    """The claims and support of the #125 request, checked into shape."""

    payload = json.loads(request)
    items = tuple(payload["evidence"])
    for item in items:
        if not isinstance(item, dict):
            raise TypeError("an evidence entry of the request is not an object")
        if not str(item["evidence_id"]).strip() or not str(item["claim"]).strip():
            raise ValueError("an evidence entry names no claim")
        support = item["support"]
        if not isinstance(support, list) or not support:
            raise ValueError("an evidence entry cites no support")
    return items


# ===========================================================================
# Building the core (§1, Post)
# ===========================================================================


def build_evidence_core(
    *,
    artifact: NormalizedResearchArtifact,
    assessment: Optional[ExtendedAssessment],
    core_id: str,
    ladder: StrengthLadder,
    client_ceiling: Optional[Strength] = None,
    version: int = CORE_VERSION,
) -> EvidenceCore:
    """Wrap one assessed research artifact as ``E-04`` v1.

    Every observation is built from a support reference of the artifact and
    every claim from one of its evidence records, so the core holds exactly
    what research retrieved and nothing beside it (I-03 at source). The
    assessment classifies; it never adds a claim or an observation, and
    :meth:`ExtendedEvidenceAssessor._check_covers` has already refused one that
    tried.

    A claim the assessment did not reach — a record ``assess_artifact``
    rejected structurally — keeps its verdict, is floored to the ladder's
    weakest level, and says in ``scope`` that nobody assessed it. A *usable*
    claim in that position is refused outright: the core would be carrying an
    accepted statement whose strength this stage never obtained.

    A support reference whose excerpt is blank becomes no observation, because
    E-02 requires one; a record whose every excerpt is blank therefore enters
    the core not at all. It is ``rejected`` either way, E-03's usability rule
    keeps it out of every stage after S-04, and ``research.json`` — which this
    core references by ID and digest — still records that retrieval returned it.
    """

    sources = {source.source_id: source for source in artifact.sources}
    observations: list[SourceObservation] = []
    claims: list[EvidenceClaim] = []

    for item in artifact.evidence:
        classified = None if assessment is None else assessment.claim(item.evidence_id)
        usable = item.disposition in USABLE_DISPOSITIONS
        if usable and classified is None:
            raise EvidenceCoreError(
                f"claim {item.evidence_id!r} is {item.disposition.value} and the "
                "extended assessment never placed it on the ladder; S-01 does "
                "not carry a usable claim whose strength it did not obtain"
            )

        refs: list[str] = []
        observed_sources: list[str] = []
        for index, support in enumerate(item.support, 1):
            source = sources.get(support.source_id)
            if source is None:
                raise EvidenceCoreError(
                    f"claim {item.evidence_id!r} cites source "
                    f"{support.source_id!r}, which the artifact does not declare"
                )
            if not support.excerpt.strip():
                # E-02 requires an excerpt, so there is no observation to make
                # of a blank one. `assess_artifact` has already rejected the
                # record it belongs to for exactly this reason, and the artifact
                # the core references by digest still holds it.
                continue
            identity = observation_id(item.evidence_id, index)
            observed = None if assessment is None else assessment.observation(identity)
            observations.append(
                SourceObservation(
                    observation_id=identity,
                    signal_id=artifact.signal_id,
                    source_ref=support.source_id,
                    # An unclassified excerpt is `other` and asserts nothing
                    # about whose claim it is: saying it reports somebody else's
                    # would be the invention, and saying nothing is not.
                    kind=(
                        ObservationKind.OTHER if observed is None else observed.kind
                    ),
                    excerpt=support.excerpt,
                    attribution=build_attribution(source, support.excerpt),
                    is_third_party_assertion=(
                        False if observed is None else observed.is_third_party_assertion
                    ),
                    location=support.location,
                    figure=_figure(observed),
                )
            )
            refs.append(identity)
            observed_sources.append(support.source_id)

        if not refs:
            # Nothing of this record is readable, so there is nothing to ground
            # a claim in and I-04 forbids one that is grounded in nothing. A
            # usable claim in that position is a contradiction the stage refuses
            # rather than resolves.
            if usable:
                raise EvidenceCoreError(
                    f"claim {item.evidence_id!r} is {item.disposition.value} and "
                    "every excerpt it cites is blank; a usable claim with no "
                    "readable support is not a claim this core can hold (I-04)"
                )
            continue

        rationale = (item.assessment_rationale or "").strip()
        strength = (
            ladder.at(classified.strength_level)
            if usable and classified is not None
            # A verdict that says the support does not establish the claim is
            # not a claim the ladder can place higher, whatever level the model
            # read off the excerpt. The floor is code's because it follows from
            # the verdict rather than being a second judgment.
            else ladder.bottom
        )
        claims.append(
            EvidenceClaim(
                evidence_claim_id=item.evidence_id,
                statement=item.claim,
                observation_refs=tuple(refs),
                # Read off the observations this core actually holds, rather
                # than copied from the record's declared `source_ids`, which the
                # research contract permits to be wider than what the support
                # cites. A source the claim names with no observation behind it
                # is a citation with nothing under it, and the artifact keeps
                # the wider list either way — the core references it by digest.
                source_refs=tuple(dict.fromkeys(observed_sources)),
                verdict=item.disposition,
                verdict_rationale=rationale or UNASSESSED_RATIONALE,
                # The #125 contract already requires a qualified record's
                # rationale to name the real limitation it is qualified by, so
                # the caveat is that limitation carried across rather than asked
                # for a second time. Asking twice would let the two disagree.
                caveats=(
                    (rationale,)
                    if item.disposition is EvidenceDisposition.QUALIFIED and rationale
                    else ()
                ),
                scope=(
                    classified.scope if classified is not None else UNASSESSED_SCOPE
                ),
                strength=strength,
                ceiling=(
                    strength
                    if client_ceiling is None
                    else ladder.lower_of(strength, client_ceiling)
                ),
            )
        )

    return EvidenceCore(
        core_id=core_id,
        version=version,
        signal_ids=(artifact.signal_id,),
        research_artifact_refs=(
            (artifact.artifact_id, research_artifact_digest(artifact)),
        ),
        sources=artifact.sources,
        observations=tuple(observations),
        evidence_claims=tuple(claims),
        readiness=artifact.readiness,
        uncertainties=artifact.uncertainties,
        contradictions=artifact.contradictions,
    )


def _figure(observed: Optional[ObservationAssessment]) -> Optional[Figure]:
    if observed is None or observed.figure is None:
        return None
    return Figure(
        value=observed.figure.value,
        provenance=observed.figure.provenance,
        unit=observed.figure.unit,
        as_of=observed.figure.as_of,
    )


# ===========================================================================
# The stage's first half
# ===========================================================================


@dataclass(frozen=True, slots=True)
class CoreBuild:
    """What research and assessment made of one selected signal.

    A core and a terminal outcome are not exclusive: a run that retrieved real
    material and found no usable claim in it has both, and the core is still
    written — it is the evidence of what the run found.
    """

    signal_id: str
    core: Optional[EvidenceCore] = None
    #: The artifact the core wraps, kept for the relevance screen, which judges
    #: the same artifact by digest.
    research: Optional[NormalizedResearchArtifact] = None
    outcome: Optional[OutcomeRecord] = None

    def __post_init__(self) -> None:
        if self.core is None and self.outcome is None:
            raise EvidenceCoreError(
                f"{self.signal_id} produced neither a core nor an outcome; "
                "every state the engine does not resolve is recorded with its "
                "reason, and a signal left without one is a run that waits"
            )
        if self.core is not None and self.research is None:
            raise EvidenceCoreError(
                f"{self.signal_id} has a core and no research artifact beside "
                "it; the relevance screen judges the artifact the core wraps"
            )
        if self.outcome is not None and self.outcome.outcome is not ArpOutcome.SKIP:
            raise EvidenceCoreError(
                f"{self.signal_id} records a {self.outcome.outcome.value} from "
                "research and assessment; the only S-01 route that is not "
                "terminal is the relevance screen's REPLAN (Step 2 §1)"
            )

    @property
    def continues(self) -> bool:
        """Is there a core to screen for relevance?"""

        return self.core is not None and self.outcome is None


def retrieve_evidence_core(
    *,
    provider: ResearchProvider,
    request: ResearchProviderRequest,
    run_dir: Path,
    identity: ConfigurationIdentity,
    run_started_at: datetime,
    now: datetime,
    transport: EvidenceJudgmentTransport,
    ladder: StrengthLadder,
    core_id: str,
    client_ceiling: Optional[Strength] = None,
    budget: Optional[CallBudget] = None,
) -> CoreBuild:
    """Retrieve, assess and build the core — or record why there is none.

    ``now`` is handed in rather than read: the editorial core is given its
    inputs, and timestamps are the run harness's (CE-1 placement rule). It is
    the clock ``execute_and_persist_research`` compares the provider's own
    timestamps against.

    Returns a :class:`CoreBuild` in every case that the protocol has an outcome
    for. A failure is a value and not an exception, because I-01 makes each of
    these states a recorded ``SKIP`` and a caller that had to catch an error
    would have nothing to write into the trace. A core that cannot be built at
    all — an artifact whose own references do not resolve — still raises: that
    is a contract violation, and §6.2 has no state for one.
    """

    signal_id = request.signal_id
    if budget is not None:
        refusal = budget.spend(scope=OutcomeScope.SIGNAL, scope_key=signal_id)
        if refusal is not None:
            return CoreBuild(signal_id=signal_id, outcome=refusal)

    assessor = ExtendedEvidenceAssessor(transport, ladder=ladder)
    try:
        artifact = execute_and_persist_research(
            provider,
            request,
            run_dir,
            identity=identity,
            run_started_at=run_started_at,
            clock=lambda: now,
            judgment_transport=assessor,
            # Step 2 §1 gives readiness to the ARP. Every other check the
            # lifecycle makes still applies, unchanged.
            require_ready=False,
        )
    except EvidenceAssessmentError as exc:
        # The artifact is persisted exactly as retrieved and nothing was
        # promoted; what is missing is the judgment, which is a condition of the
        # machinery and not a verdict about the material.
        return _skipped(
            signal_id,
            StateCode.EVIDENCE_ASSESSMENT_FAILED,
            assessor.failure or str(exc),
        )
    except ResearchGateError as exc:
        return _skipped(signal_id, StateCode.RESEARCH_FAILED, str(exc))

    unobtained = _usable_claims_without_assessment(artifact, assessor.assessment)
    if unobtained:
        # `assess_artifact` leaves a record that already carries a disposition
        # alone, so an artifact assessed elsewhere arrives usable and
        # unclassified. Refusing it is the same posture as that module's own:
        # rather than attribute work it did not do, it fails closed.
        return _skipped(
            signal_id,
            StateCode.EVIDENCE_ASSESSMENT_FAILED,
            "claim(s) "
            + ", ".join(unobtained)
            + " arrived usable and already assessed, so the extended assessment "
            "this stage needs was never made for them",
        )

    core = build_evidence_core(
        artifact=artifact,
        assessment=assessor.assessment,
        core_id=core_id,
        ladder=ladder,
        client_ceiling=client_ceiling,
    )
    if not core.usable_claims:
        return CoreBuild(
            signal_id=signal_id,
            core=core,
            research=artifact,
            outcome=OutcomeRecord(
                outcome=ArpOutcome.SKIP,
                state_code=StateCode.NO_USABLE_EVIDENCE_CLAIM,
                scope=OutcomeScope.SIGNAL,
                scope_key=signal_id,
                reason=(
                    f"the core holds {len(core.evidence_claims)} claim(s) and "
                    "none of them is accepted or qualified, so no later stage "
                    f"could reference one (readiness: {core.readiness.value})"
                ),
            ),
        )
    return CoreBuild(signal_id=signal_id, core=core, research=artifact)


def _usable_claims_without_assessment(
    artifact: NormalizedResearchArtifact, assessment: Optional[ExtendedAssessment]
) -> tuple[str, ...]:
    return tuple(
        item.evidence_id
        for item in artifact.evidence
        if item.disposition in USABLE_DISPOSITIONS
        and (assessment is None or assessment.claim(item.evidence_id) is None)
    )


def _skipped(signal_id: str, state_code: StateCode, reason: str) -> CoreBuild:
    return CoreBuild(
        signal_id=signal_id,
        outcome=OutcomeRecord(
            outcome=ArpOutcome.SKIP,
            state_code=state_code,
            scope=OutcomeScope.SIGNAL,
            scope_key=signal_id,
            reason=reason,
        ),
    )
