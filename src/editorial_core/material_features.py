"""S-02 · Material features, initial assets and notes (Issue #300, slice SL-3).

The stage that describes the material and nothing else. Step 2 §1 gives it one
authority: "describe the material: the 12 features, initial assets, and what is
missing", and forbids it the rest — "it must not choose a reader path, a label
or a story". So nothing here names a path, nothing here derives
``material_label`` (I-10), and the notes it writes about missing material are
notes rather than gaps: S-03 is the sole producer of E-07 (fix F-3), and it
opens one only where a note blocks a decision.

What it does, in the order it does it
-------------------------------------
1. **One call, by model.** The features, the asset candidates and the
   missing-material notes come back from a single request (§1, Calls: 1). The
   request carries the core's claims and observations and nothing else a model
   could take an angle from, and the answer is parsed strictly: a description
   that does not satisfy the contract describes nothing.
2. **The reference check, by code.** Every positive feature, every asset and
   every note is checked against the core it claims to come from: each
   reference must resolve to a claim the core holds, and at least one of them
   must be usable (E-03's usability rule). One rule for all three, because a
   feature, an asset and a note grounded only in material the assessment
   rejected are the same mistake. An item that fails is **dropped and
   recorded** — a ``DEGRADE`` with low confidence, never a retry (§1, ARP).
3. **The calculations, by code.** A calculation asset is a derived evidence
   claim (E-06), so its inputs must all be in the core and its arithmetic is
   never left to the model: code resolves each input claim to the one figure
   its observations record, reads the amount off the figure, and computes the
   result. A figure code cannot read is a calculation that is dropped, not one
   that is guessed at.

**A positional asset is not something a model may create** (E-06). The model
may only point at a position the Client Contract already approved; code refuses
an ID the contract does not declare, and the ARP state "client position needed"
is what that refusal is recorded as.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §1 (S-02);
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §0.3 and §2 (E-05,
E-06, E-07); ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §8.3 (the twelve
features) and §6.2; ``knowledge/vocab/features.md`` (the closed value lists).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation
from enum import Enum
from typing import Any, Final, Optional, Protocol, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.editorial_core.arp import (
    ArpOutcome,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.evidence_core import (
    EvidenceClaim,
    EvidenceCore,
    Figure,
)

# The budget protocol is declared once, in the stage that first needed it
# (S-00), and asked for here rather than restated: a second declaration of the
# same protocol would eventually be a second contract.
from src.editorial_core.signal_selection import CallBudget

#: The stage this module is, as the topology registry and §2.3 spell it.
STAGE: Final[str] = "S-02"

#: A stage of the canonical topology, as every trace record spells one. What a
#: note may say it blocks.
_STAGE_ID: Final[re.Pattern[str]] = re.compile(r"^S-(?:0\d|1[0-5])$")


class MaterialFeaturesError(RuntimeError):
    """S-02 was asked to describe material its contract cannot describe."""


# ===========================================================================
# The vocabularies (map §8.3, knowledge/vocab/features.md)
# ===========================================================================


class MaterialFeature(str, Enum):
    """The twelve features, exactly as map §8.3 lists them.

    A closed list, and E-05 requires one entry per member: a feature nobody
    answered is a feature a later condition would read as absent, and the
    difference between "no" and "not looked at" is the one this stage exists to
    keep.
    """

    DOCUMENTED_CASE = "documented_case"
    NAMED_COMPANY = "named_company"
    FIGURE_PROVENANCE = "figure_provenance"
    METHOD_KNOWN = "method_known"
    FRESHNESS = "freshness"
    MECHANISM_PRESENT = "mechanism_present"
    REAL_SCENE = "real_scene"
    FIRST_PERSON = "first_person"
    FAILURE_COST = "failure_cost"
    CONTESTED_ASSERTION = "contested_assertion"
    PARALLEL_STRUCTURE = "parallel_structure"
    OPEN_QUESTION = "open_question"


class FeatureFigureProvenance(str, Enum):
    """E-05's ``figure_provenance`` value: who produced the figures.

    Three values where E-02's :class:`~src.editorial_core.evidence_core.FigureProvenance`
    has two: an observation carries a figure or it is not a figure observation,
    while the material as a whole may hold no figure at all.
    """

    OWN = "own"
    THIRD_PARTY = "third_party"
    NONE = "none"


class Freshness(str, Enum):
    """E-05's ``freshness`` value: how recent the material is against its own
    subject's pace of change. Judged from the material's own dates — S-02 reads
    no clock (CE-1).

    ``LOW`` is the floor of the domain and asserts nothing a reference could
    carry: it is what is left when nothing in the core dates the material, and
    it is what the reference check withdraws a freshness claim to.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConfidenceLevel(str, Enum):
    """Step 1 §0.3: three levels and no numbers. Thresholds are OPEN-05."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AssetClass(str, Enum):
    """E-06: what kind of authority an asset draws on."""

    EVIDENTIARY = "evidentiary"
    POSITIONAL = "positional"


class AssetKind(str, Enum):
    """E-06's kinds. ``CLIENT_POSITION`` is the only positional one."""

    FIGURE = "figure"
    CALCULATION = "calculation"
    DOCUMENT = "document"
    SECOND_SOURCE = "second_source"
    FIRST_TO_REPORT = "first_to_report"
    OTHER = "other"
    CLIENT_POSITION = "client_position"


#: Which class each kind belongs to. A table rather than a branch, so that a
#: kind without a class is a missing row and not a silent default.
_CLASS_OF_KIND: Mapping[AssetKind, AssetClass] = {
    AssetKind.FIGURE: AssetClass.EVIDENTIARY,
    AssetKind.CALCULATION: AssetClass.EVIDENTIARY,
    AssetKind.DOCUMENT: AssetClass.EVIDENTIARY,
    AssetKind.SECOND_SOURCE: AssetClass.EVIDENTIARY,
    AssetKind.FIRST_TO_REPORT: AssetClass.EVIDENTIARY,
    AssetKind.OTHER: AssetClass.EVIDENTIARY,
    AssetKind.CLIENT_POSITION: AssetClass.POSITIONAL,
}


class CalculationMethod(str, Enum):
    """The arithmetic code will do, and the whole of it.

    Deliberately four named operations rather than an expression language: E-06
    calls a calculation "a derived evidence claim with its own ceiling", and a
    derivation a reader cannot reproduce from the method and the inputs is not
    one. The inputs are ordered, because three of the four are not commutative.
    """

    SUM = "sum"
    DIFFERENCE = "difference"
    RATIO = "ratio"
    PERCENT_CHANGE = "percent_change"


class GapKind(str, Enum):
    """E-07's kinds, declared where the first producer of the value is.

    S-02 writes the kind on a MaterialNote and S-03 carries it onto the E-07 it
    opens from that note, so the vocabulary arrives with the stage that fills
    it — the same placement :class:`~src.editorial_core.relevance_screen.AudienceTransfer`
    has. ``RequestedGapKind`` in the relevance screen is two of these six, and
    stays restricted to them on purpose.
    """

    EVIDENCE = "evidence"
    READER_CONNECTION = "reader_connection"
    COUNTER_EVIDENCE = "counter_evidence"
    ASSET = "asset"
    FIGURE_PROVENANCE = "figure_provenance"
    OTHER = "other"


#: What a dropped feature falls back to (§1, ARP: dropped and recorded, low
#: confidence). The weakest value of each domain, because a feature whose
#: references did not hold has not been shown, and "not shown" is not "no
#: figure at all" being asserted either — it is the claim being withdrawn.
_WITHDRAWN: Mapping[MaterialFeature, Union[bool, FeatureFigureProvenance, Freshness]] = {
    MaterialFeature.FIGURE_PROVENANCE: FeatureFigureProvenance.NONE,
    MaterialFeature.FRESHNESS: Freshness.LOW,
}


# ===========================================================================
# Confidence, quantities and derivations (Step 1 §0.3, E-06)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class Confidence:
    """A level and a short rationale (Step 1 §0.3). No numbers."""

    level: ConfidenceLevel
    rationale: str

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise MaterialFeaturesError(
                f"a {self.level.value} confidence with no rationale states a "
                "degree of belief and not a reason for it"
            )

    def as_entity(self) -> dict[str, str]:
        return {"level": self.level.value, "rationale": self.rationale}


@dataclass(frozen=True, slots=True)
class Quantity:
    """An amount code computed, with the unit it is in.

    ``Decimal`` rather than ``float``: a derived evidence claim is checkable
    only if the number a reader recomputes is the number the core holds.
    """

    amount: Decimal
    unit: Optional[str] = None

    def as_entity(self) -> dict[str, Any]:
        # Serialized as a string so that the exact amount survives JSON, which
        # has one numeric type and it is binary floating point.
        return {"amount": str(self.amount), "unit": self.unit}


@dataclass(frozen=True, slots=True)
class Derivation:
    """``E-06.derivation``: the inputs, the method, and what code computed.

    Every input is an evidence claim ID, and every one of them must be in the
    core — which is checked here rather than trusted, because a calculation
    over a claim the core does not hold is a figure with no provenance.
    """

    inputs: tuple[str, ...]
    method: CalculationMethod
    result: Quantity

    def __post_init__(self) -> None:
        if not self.inputs:
            raise MaterialFeaturesError(
                "a calculation with no input is not a derivation"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "inputs": list(self.inputs),
            "method": self.method.value,
            "result": self.result.as_entity(),
        }


# ===========================================================================
# E-05 · Material features
# ===========================================================================


@dataclass(frozen=True, slots=True)
class FeatureValue:
    """One feature, its value, its confidence and what shows it.

    ``evidence_refs`` is required when the value is positive, and a positive
    feature with no reference is invalid (E-05). Positive means the value
    asserts something the core has to carry, so each domain has exactly one
    value that asserts nothing and needs no citation: ``false``, ``none`` and
    ``low``.
    """

    feature: MaterialFeature
    value: Union[bool, FeatureFigureProvenance, Freshness]
    confidence: Confidence
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _value_fits(self.feature, self.value):
            raise MaterialFeaturesError(
                f"feature {self.feature.value!r} was given the value "
                f"{self.value!r}, which is not one its own vocabulary declares "
                "(knowledge/vocab/features.md)"
            )
        if self.positive and not self.evidence_refs:
            raise MaterialFeaturesError(
                f"feature {self.feature.value!r} is positive and cites no "
                "evidence; a positive feature with no reference is invalid "
                "(E-05), and it is what the S-02 reference check exists for"
            )

    @property
    def positive(self) -> bool:
        """Does this value assert something the core has to carry?"""

        if isinstance(self.value, bool):
            return self.value
        if isinstance(self.value, FeatureFigureProvenance):
            return self.value is not FeatureFigureProvenance.NONE
        return self.value is not Freshness.LOW

    def as_entity(self) -> dict[str, Any]:
        return {
            "feature": self.feature.value,
            "value": self.value if isinstance(self.value, bool) else self.value.value,
            "confidence": self.confidence.as_entity(),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class MaterialFeatures:
    """``E-05``: the feature vector later knowledge conditions refer to.

    **No label lives here** (AD-07, I-10). There is no field for one, which is
    what makes "S-02 produces no label" checkable rather than promised.
    """

    features_id: str
    #: ``(core_id, version)``. Features are recomputed per core version, so the
    #: version is part of what they are about and not metadata beside it.
    core_ref: tuple[str, int]
    values: tuple[FeatureValue, ...]

    def __post_init__(self) -> None:
        if not self.features_id.strip():
            raise MaterialFeaturesError("a feature vector is named by its ID")
        answered = [item.feature for item in self.values]
        missing = [item for item in MaterialFeature if item not in answered]
        if missing:
            raise MaterialFeaturesError(
                "the feature vector answers nothing for "
                + ", ".join(item.value for item in missing)
                + "; E-05 holds exactly one entry per feature of map §8.3, "
                "because a feature nobody answered reads as a feature that is "
                "absent"
            )
        if len(set(answered)) != len(answered):
            raise MaterialFeaturesError(
                "the feature vector answers one feature twice; two values for "
                "one feature are not a value of it"
            )

    @property
    def positive(self) -> tuple[FeatureValue, ...]:
        """The values that assert something, and therefore carry references."""

        return tuple(item for item in self.values if item.positive)

    def value_of(self, feature: MaterialFeature) -> FeatureValue:
        """One feature's entry. Always present: E-05 holds all twelve."""

        for item in self.values:
            if item.feature is feature:
                return item
        raise MaterialFeaturesError(  # pragma: no cover - __post_init__ covers it
            f"feature {feature.value!r} is not in this vector"
        )

    def as_entity(self) -> dict[str, Any]:
        """The entity body written to ``signal/features/features.v<n>.json``."""

        core_id, version = self.core_ref
        return {
            "entity_type": "E-05",
            "entity_id": self.features_id,
            "features_id": self.features_id,
            "core_ref": {"core_id": core_id, "version": version},
            "values": [item.as_entity() for item in self.values],
        }


# ===========================================================================
# E-06 · Asset
# ===========================================================================


@dataclass(frozen=True, slots=True)
class Asset:
    """``E-06``: what gives a text something the reader could not get elsewhere."""

    asset_id: str
    asset_class: AssetClass
    kind: AssetKind
    refs: tuple[str, ...]
    strength: Confidence
    derivation: Optional[Derivation] = None

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise MaterialFeaturesError("an asset is named by its asset ID")
        if not self.refs:
            raise MaterialFeaturesError(
                f"asset {self.asset_id!r} cites nothing; an asset without a "
                "reference is invalid (E-06)"
            )
        if _CLASS_OF_KIND[self.kind] is not self.asset_class:
            raise MaterialFeaturesError(
                f"asset {self.asset_id!r} is {self.asset_class.value} of kind "
                f"{self.kind.value!r}, which E-06 lists under "
                f"{_CLASS_OF_KIND[self.kind].value}"
            )
        if (self.kind is AssetKind.CALCULATION) != (self.derivation is not None):
            raise MaterialFeaturesError(
                f"asset {self.asset_id!r} is kind {self.kind.value!r} and "
                + ("carries" if self.derivation is not None else "carries no")
                + " derivation; E-06 requires one for a calculation and admits "
                "one for nothing else"
            )
        if self.asset_class is AssetClass.POSITIONAL and len(self.refs) != 1:
            raise MaterialFeaturesError(
                f"asset {self.asset_id!r} is positional and cites "
                f"{len(self.refs)} references; a positional asset comes from "
                "one approved position of the Client Contract (E-06)"
            )

    def as_entity(self) -> dict[str, Any]:
        """One entry of ``signal/assets/assets.v<n>.json``."""

        return {
            "entity_type": "E-06",
            "entity_id": self.asset_id,
            "asset_id": self.asset_id,
            "asset_class": self.asset_class.value,
            "kind": self.kind.value,
            "refs": list(self.refs),
            "derivation": (
                None if self.derivation is None else self.derivation.as_entity()
            ),
            "strength": self.strength.as_entity(),
        }


# ===========================================================================
# MaterialNotes (§1, Outputs — "These are not gaps")
# ===========================================================================


@dataclass(frozen=True, slots=True)
class NoteBlock:
    """What a note says is blocked: a stage ID and the decision (E-07)."""

    stage: str
    decision: str

    def __post_init__(self) -> None:
        if not _STAGE_ID.match(self.stage):
            raise MaterialFeaturesError(
                f"a note blocks a stage of the canonical topology; got "
                f"{self.stage!r}"
            )
        if not self.decision.strip():
            raise MaterialFeaturesError(
                f"a note blocking {self.stage} does not say which decision; "
                "S-03 opens a gap only where a note blocks one, so a block "
                "with no decision behind it opens nothing"
            )

    def as_entity(self) -> dict[str, str]:
        return {"stage": self.stage, "decision": self.decision}


@dataclass(frozen=True, slots=True)
class MaterialNote:
    """One missing-material note: free text, with references.

    Not a gap. S-03 is the sole producer of E-07 (fix F-3) and turns a note
    into one **only** when the note blocks a decision — which is why ``blocks``
    is optional here and required there.
    """

    note_id: str
    kind: GapKind
    description: str
    refs: tuple[str, ...] = ()
    blocks: Optional[NoteBlock] = None

    def __post_init__(self) -> None:
        if not self.note_id.strip():
            raise MaterialFeaturesError("a note is named by its note ID")
        if not self.description.strip():
            raise MaterialFeaturesError(
                f"note {self.note_id!r} says nothing is missing"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "kind": self.kind.value,
            "description": self.description,
            "refs": list(self.refs),
            "blocks": None if self.blocks is None else self.blocks.as_entity(),
        }


# ===========================================================================
# What the stage made of the core
# ===========================================================================


@dataclass(frozen=True, slots=True)
class DroppedItem:
    """One thing the reference check refused, as the trace records it (§1)."""

    #: ``feature``, ``asset`` or ``note``.
    kind: str
    identity: str
    reason: str

    def as_entity(self) -> dict[str, str]:
        return {"kind": self.kind, "identity": self.identity, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class MaterialDescription:
    """What S-02 made of one core: E-05 v1, E-06 v1 and the notes.

    A description and a terminal outcome are exclusive here, unlike S-01's
    core: a stage whose single call did not answer has nothing to describe the
    material with, and an empty feature vector is not a description of it.
    """

    signal_id: str
    features: Optional[MaterialFeatures] = None
    assets: tuple[Asset, ...] = ()
    notes: tuple[MaterialNote, ...] = ()
    dropped: tuple[DroppedItem, ...] = ()
    outcomes: tuple[OutcomeRecord, ...] = ()
    #: Model calls this execution made, for the per-stage call record (§3.3).
    calls: int = 0

    def __post_init__(self) -> None:
        skips = tuple(
            item for item in self.outcomes if item.outcome is ArpOutcome.SKIP
        )
        if (self.features is None) != bool(skips):
            raise MaterialFeaturesError(
                f"{self.signal_id} recorded "
                + ("no" if self.features is None else "a")
                + " feature vector and "
                + (f"{len(skips)} SKIP(s)" if skips else "no SKIP")
                + "; every state the engine does not resolve is recorded with "
                "its reason, and a description that is neither made nor "
                "refused is a run that waits"
            )

    @property
    def continues(self) -> bool:
        """Is there a described core for S-03 to enrich?"""

        return self.features is not None

    def as_entity(self) -> dict[str, Any]:
        """The MaterialNotes body written to ``signal/notes/``."""

        return {
            "entity_type": "MaterialNotes",
            "entity_id": f"notes-{self.signal_id}",
            "signal_id": self.signal_id,
            "notes": [note.as_entity() for note in self.notes],
            "dropped": [item.as_entity() for item in self.dropped],
        }


class MaterialTransport(Protocol):
    """The one model call S-02 makes, as a narrow boundary.

    The same shape as the evidence judgment transport and deliberately its own
    name: S-02 judges no evidence, and a stage that borrowed the judgment
    boundary would eventually be handed judgment instructions.
    """

    def complete(self, *, instructions: str, request: str) -> str: ...


# ===========================================================================
# The one call
# ===========================================================================


MATERIAL_INSTRUCTIONS = """\
You describe retrieved material for an editorial engine. You describe it and
nothing else: you do not interpret it, you do not say what it means for anyone,
and you never choose or name a reader path, a story, an angle or a label. A
later stage owns all of those, and naming one here is out of scope.

You receive an Evidence Core: sources, source observations (one bounded excerpt
each, attributed to its source) and evidence claims with verdicts. Everything
you say must point back at those claims by their IDs. Cite only claim IDs the
request contains, and never cite one to support something the excerpt does not
show.

Return exactly three things.

1. `features`. All twelve below, once each, in any order. Each entry carries a
   `value`, a `confidence` of "high", "medium" or "low", a one-sentence
   `rationale`, and `evidence_refs`: the claim IDs that show the value. A value
   that asserts something about the material MUST cite at least one claim. Each
   domain has one value that asserts nothing and may cite nothing: false, "none"
   and "low".

     documented_case      true / false — a real case a reader could look up
     named_company        true / false — a company is named, not "a manufacturer"
     figure_provenance    "own" / "third_party" / "none" — who produced the figures
     method_known         true / false — how a figure was measured is stated
     freshness            "high" / "medium" / "low" — how recent the material is
                          against its own subject's pace of change, judged from
                          the dates the material itself carries
     mechanism_present    true / false — it shows how something works
     real_scene           true / false — a scene that happened, with a source
     first_person         true / false — somebody in it speaks from inside it
     failure_cost         true / false — what a failure cost is stated
     contested_assertion  true / false — a third-party assertion the evidence
                          contests
     parallel_structure   true / false — comparable items treated the same way
     open_question        true / false — a question left genuinely open

2. `assets`: what would give a text something a reader could not get elsewhere.
   Each entry carries a `kind`, an `asset_class`, `refs`, a `strength` of
   "high", "medium" or "low", and a one-sentence `rationale`.

     kind "figure", "calculation", "document", "second_source",
     "first_to_report" or "other" with asset_class "evidentiary": `refs` are
     claim IDs.

     kind "calculation" also carries `derivation`: `inputs`, the ordered claim
     IDs whose figures the calculation is over, and `method`, one of "sum",
     "difference", "ratio" or "percent_change". You do not compute anything:
     the arithmetic is done afterwards, by code, from the figures those claims
     record. "difference" is input 1 minus input 2, "ratio" is input 1 divided
     by input 2, "percent_change" is the change from input 1 to input 2.

     kind "client_position" with asset_class "positional": `refs` is exactly
     one position ID from `approved_positions` in the request. You may not
     invent a position, and an ID that is not in that list is refused.

   Return an empty list when the material carries no asset. A weak asset
   asserted is worse than an asset absent.

3. `notes`: what is missing. Each entry carries a `kind` of "evidence",
   "reader_connection", "counter_evidence", "asset", "figure_provenance" or
   "other", a `description` of what is missing in one sentence, `refs` (claim
   IDs the absence concerns, possibly empty), and — only when the absence stops
   a later decision from being taken — `blocks_stage` (the stage ID, "S-04"
   through "S-13") and `blocks` (the decision it stops, in a few words). Leave
   both out for anything merely interesting: only a note that blocks a decision
   is searched for later, and that is what keeps enrichment finite.

Return ONLY one valid JSON object, no text outside it, with exactly these three
keys:

{"features": [{"feature": "documented_case", "value": true, "confidence": "high", "rationale": "...", "evidence_refs": ["..."]}],
 "assets": [{"asset_class": "evidentiary", "kind": "figure", "refs": ["..."], "strength": "medium", "rationale": "...", "derivation": null}],
 "notes": [{"kind": "evidence", "description": "...", "refs": [], "blocks_stage": null, "blocks": null}]}
"""


class _MaterialModel(BaseModel):
    """The answer is parsed strictly, or it is not a description."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FeatureAnswer(_MaterialModel):
    """One feature as the model answered it."""

    feature: MaterialFeature
    value: Union[bool, FeatureFigureProvenance, Freshness]
    confidence: ConfidenceLevel
    rationale: str = Field(min_length=1, max_length=400)
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _value_is_of_this_feature(self) -> "FeatureAnswer":
        if not _value_fits(self.feature, self.value):
            raise ValueError(
                f"{self.feature.value} was given {self.value!r}, which is not "
                "one of its own values"
            )
        return self


class DerivationAnswer(_MaterialModel):
    """The inputs and the method of a calculation. Never its result."""

    inputs: tuple[str, ...] = Field(min_length=1, max_length=8)
    method: CalculationMethod


class AssetAnswer(_MaterialModel):
    """One asset candidate as the model answered it."""

    asset_class: AssetClass
    kind: AssetKind
    refs: tuple[str, ...] = Field(min_length=1, max_length=20)
    strength: ConfidenceLevel
    rationale: str = Field(min_length=1, max_length=400)
    derivation: Optional[DerivationAnswer] = None

    @model_validator(mode="after")
    def _kind_and_class_agree(self) -> "AssetAnswer":
        if _CLASS_OF_KIND[self.kind] is not self.asset_class:
            raise ValueError(
                f"kind {self.kind.value!r} is {_CLASS_OF_KIND[self.kind].value}, "
                f"not {self.asset_class.value}"
            )
        if (self.kind is AssetKind.CALCULATION) != (self.derivation is not None):
            raise ValueError(
                "a derivation belongs to a calculation and to nothing else"
            )
        return self


class NoteAnswer(_MaterialModel):
    """One missing-material note as the model answered it."""

    kind: GapKind
    description: str = Field(min_length=1, max_length=400)
    refs: tuple[str, ...] = ()
    blocks_stage: Optional[str] = Field(default=None, pattern=r"^S-(?:0\d|1[0-5])$")
    blocks: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _a_block_names_both(self) -> "NoteAnswer":
        if (self.blocks_stage is None) != (not (self.blocks or "").strip()):
            raise ValueError(
                "a note blocks a named decision of a named stage, or it blocks "
                "nothing: got stage "
                f"{self.blocks_stage!r} and decision {self.blocks!r}"
            )
        return self


class MaterialAnswer(_MaterialModel):
    """The three lists one S-02 call returned."""

    features: tuple[FeatureAnswer, ...]
    assets: tuple[AssetAnswer, ...] = ()
    notes: tuple[NoteAnswer, ...] = ()

    @model_validator(mode="after")
    def _answers_every_feature_once(self) -> "MaterialAnswer":
        answered = [item.feature for item in self.features]
        if len(set(answered)) != len(answered):
            raise ValueError("the description answers one feature twice")
        missing = [item.value for item in MaterialFeature if item not in answered]
        if missing:
            raise ValueError(
                "the description answers nothing for " + ", ".join(missing)
            )
        return self


# ===========================================================================
# The stage
# ===========================================================================


def features_id(core_id: str, version: int) -> str:
    """The ID of the feature vector describing one core version.

    Derived rather than passed in, for the reason
    :func:`~src.editorial_core.evidence_core.observation_id` is: S-02 makes the
    first vector and S-03 makes every later one, and two stages naming the same
    thing differently is how a reader loses the lineage.
    """

    return f"feat-{core_id}-v{version}"


def asset_id(core_id: str, version: int, index: int) -> str:
    """The ID of the ``index``-th asset found against one core version."""

    return f"ast-{core_id}-v{version}-{index}"


def note_id(core_id: str, version: int, index: int) -> str:
    """The ID of the ``index``-th note written against one core version."""

    return f"note-{core_id}-v{version}-{index}"


def describe_material(
    *,
    core: EvidenceCore,
    transport: MaterialTransport,
    approved_positions: Sequence[str] = (),
    budget: Optional[CallBudget] = None,
) -> MaterialDescription:
    """Describe one core: features, assets and notes (§1, S-02).

    Returns a :class:`MaterialDescription` in every case the protocol has an
    outcome for. A call that could not be made or could not be read is a
    recorded ``SKIP`` and not an exception, for the reason S-00 and S-01 give:
    a caller that had to catch an error would have nothing to write into the
    trace. A core that violates the stage's precondition — no usable claim,
    which S-01 already skips the signal for — still raises: §6.2 has no state
    for a stage being run out of order.
    """

    signal_id = core.signal_ids[0]
    if not core.usable_claims:
        raise MaterialFeaturesError(
            f"{signal_id} reached {STAGE} with a core holding no accepted or "
            "qualified claim; S-01 skips that signal, and describing material "
            "no later stage may reference would describe nothing"
        )

    if budget is not None:
        refusal = budget.spend(scope=OutcomeScope.SIGNAL, scope_key=signal_id)
        if refusal is not None:
            return MaterialDescription(signal_id=signal_id, outcomes=(refusal,))

    try:
        raw = transport.complete(
            instructions=MATERIAL_INSTRUCTIONS,
            request=_request(core, approved_positions),
        )
    except Exception as exc:  # noqa: BLE001 — sanitized, never the provider's text
        return _refused(
            signal_id,
            f"the material description transport failed ({type(exc).__name__})",
        )

    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        answer = MaterialAnswer.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return _refused(
            signal_id,
            "the material description does not satisfy the S-02 contract",
        )

    return _checked(core, answer, approved_positions)


# ===========================================================================
# The reference check, by code (§1, Decider)
# ===========================================================================


def _checked(
    core: EvidenceCore,
    answer: MaterialAnswer,
    approved_positions: Sequence[str],
) -> MaterialDescription:
    """Drop what the core does not carry, and record every drop."""

    claims = {item.evidence_claim_id: item for item in core.evidence_claims}
    positions = {value.strip() for value in approved_positions if value.strip()}
    dropped: list[DroppedItem] = []
    outcomes: list[OutcomeRecord] = []
    signal_id = core.signal_ids[0]

    values: list[FeatureValue] = []
    for item in answer.features:
        # A value that asserts nothing carries no reference. false, "none" and
        # "low" are what is left when the material shows nothing, so a citation
        # on one supports a claim E-05 is not making, and keeping it would put
        # a reference beside a value no later stage reads as shown. The
        # reference check is therefore over the positive values, and a negative
        # one keeps none of what the model offered.
        positive = _positive(item.feature, item.value)
        refs = tuple(dict.fromkeys(item.evidence_refs)) if positive else ()
        failure = _unheld(refs, claims) if positive else None
        if failure is None:
            values.append(
                FeatureValue(
                    feature=item.feature,
                    value=item.value,
                    confidence=Confidence(item.confidence, item.rationale),
                    evidence_refs=refs,
                )
            )
            continue
        dropped.append(DroppedItem("feature", item.feature.value, failure))
        outcomes.append(
            _degraded(
                signal_id,
                StateCode.MATERIAL_WITHOUT_REFERENCE,
                f"feature {item.feature.value} was dropped: {failure}",
            )
        )
        values.append(_withdrawn(item.feature, failure))

    assets: list[Asset] = []
    for index, item in enumerate(answer.assets, 1):
        identity = asset_id(core.core_id, core.version, index)
        built, failure = _asset(core, claims, positions, item, identity)
        if built is not None:
            assets.append(built)
            continue
        dropped.append(DroppedItem("asset", identity, failure or ""))
        outcomes.append(
            _degraded(
                signal_id,
                (
                    StateCode.CLIENT_POSITION_MISSING
                    if item.asset_class is AssetClass.POSITIONAL
                    else StateCode.MATERIAL_WITHOUT_REFERENCE
                ),
                f"asset {identity} ({item.kind.value}) was dropped: {failure}",
            )
        )

    notes: list[MaterialNote] = []
    for index, item in enumerate(answer.notes, 1):
        identity = note_id(core.core_id, core.version, index)
        # A note is about what is *missing*, so citing nothing is a legitimate
        # answer and the one-usable-reference rule applies only once it cites
        # something. What it may not do is cite a claim the core does not hold.
        failure = _unheld(item.refs, claims) if item.refs else None
        if failure is not None:
            dropped.append(DroppedItem("note", identity, failure))
            outcomes.append(
                _degraded(
                    signal_id,
                    StateCode.MATERIAL_WITHOUT_REFERENCE,
                    f"note {identity} was dropped: {failure}",
                )
            )
            continue
        notes.append(
            MaterialNote(
                note_id=identity,
                kind=item.kind,
                description=item.description,
                refs=tuple(dict.fromkeys(item.refs)),
                blocks=(
                    None
                    if item.blocks_stage is None or item.blocks is None
                    else NoteBlock(item.blocks_stage, item.blocks)
                ),
            )
        )

    return MaterialDescription(
        signal_id=signal_id,
        features=MaterialFeatures(
            features_id=features_id(core.core_id, core.version),
            core_ref=(core.core_id, core.version),
            values=tuple(values),
        ),
        assets=tuple(assets),
        notes=tuple(notes),
        dropped=tuple(dropped),
        outcomes=tuple(outcomes),
        calls=1,
    )


def _unheld(
    refs: Sequence[str], claims: Mapping[str, EvidenceClaim]
) -> Optional[str]:
    """Why these references do not hold, or ``None`` when they do.

    One rule for features, assets and notes: every reference resolves to a
    claim the core holds, and at least one of them is usable. The second half
    is E-03's usability rule reaching backwards — a feature is read by S-08 and
    checked by V-P01, both after S-04, so a description grounded only in
    material the assessment rejected would carry that material past the rule
    that keeps it out. A claim with a rejected verdict may still appear beside
    a usable one, which is how ``contested_assertion`` names the assertion the
    evidence contests.
    """

    if not refs:
        return "it cites no evidence claim"
    missing = sorted({ref for ref in refs if ref not in claims})
    if missing:
        return (
            "it cites claim(s) the core does not hold: " + ", ".join(missing)
        )
    if not any(claims[ref].usable for ref in refs):
        return (
            "every claim it cites is rejected or unassessed, and only accepted "
            "or qualified claims may be referenced downstream (E-03)"
        )
    return None


def _asset(
    core: EvidenceCore,
    claims: Mapping[str, EvidenceClaim],
    positions: set[str],
    answer: AssetAnswer,
    identity: str,
) -> tuple[Optional[Asset], Optional[str]]:
    """Build one asset, or say why the core does not carry it."""

    if answer.asset_class is AssetClass.POSITIONAL:
        if len(answer.refs) != 1 or answer.refs[0] not in positions:
            return None, (
                "a positional asset comes only from an approved position of "
                "the Client Contract, and "
                + ", ".join(answer.refs)
                + " is not one of "
                + (", ".join(sorted(positions)) if positions else "none declared")
            )
        return (
            Asset(
                asset_id=identity,
                asset_class=AssetClass.POSITIONAL,
                kind=answer.kind,
                refs=(answer.refs[0],),
                strength=Confidence(answer.strength, answer.rationale),
            ),
            None,
        )

    failure = _unheld(answer.refs, claims)
    if failure is not None:
        return None, failure

    derivation: Optional[Derivation] = None
    if answer.derivation is not None:
        derivation, failure = _derive(core, claims, answer.derivation)
        if derivation is None:
            return None, failure

    return (
        Asset(
            asset_id=identity,
            asset_class=AssetClass.EVIDENTIARY,
            kind=answer.kind,
            refs=tuple(dict.fromkeys(answer.refs)),
            strength=Confidence(answer.strength, answer.rationale),
            derivation=derivation,
        ),
        None,
    )


def _degraded(signal_id: str, state_code: StateCode, reason: str) -> OutcomeRecord:
    return OutcomeRecord(
        outcome=ArpOutcome.DEGRADE,
        state_code=state_code,
        scope=OutcomeScope.SIGNAL,
        scope_key=signal_id,
        reason=reason,
    )


def _refused(signal_id: str, reason: str) -> MaterialDescription:
    return MaterialDescription(
        signal_id=signal_id,
        outcomes=(
            OutcomeRecord(
                outcome=ArpOutcome.SKIP,
                state_code=StateCode.MATERIAL_DESCRIPTION_FAILED,
                scope=OutcomeScope.SIGNAL,
                scope_key=signal_id,
                reason=reason,
            ),
        ),
        calls=1,
    )


def _withdrawn(feature: MaterialFeature, reason: str) -> FeatureValue:
    """The entry a dropped feature leaves: the weakest value, low confidence."""

    return FeatureValue(
        feature=feature,
        value=_WITHDRAWN.get(feature, False),
        confidence=Confidence(
            ConfidenceLevel.LOW,
            f"withdrawn by the S-02 reference check: {reason}",
        ),
    )


# ===========================================================================
# Calculations, by code (§1: arithmetic is never left to the model)
# ===========================================================================


#: What a figure's amount may look like: an optional sign, an optional currency
#: marker, digits with or without thousand separators, an optional fraction and
#: an optional scale word. Deliberately no trailing prose — a figure code
#: cannot read exactly is a calculation that is dropped rather than guessed at,
#: and E-02 keeps the value as the excerpt stated it precisely so that this
#: reading is checkable against the source.
_AMOUNT: Final[re.Pattern[str]] = re.compile(
    r"(?i)^(?P<sign>[-+])?\s*"
    r"(?P<currency>[$€£¥₽]|usd|eur|gbp|rub|aud)?\s*"
    r"(?P<digits>\d{1,3}(?:,\d{3})+|\d+)"
    r"(?P<fraction>\.\d+)?\s*"
    r"(?P<scale>hundred|thousand|million|billion|trillion)?\s*"
    r"(?P<percent>%)?$"
)

_SCALES: Final[Mapping[str, Decimal]] = {
    "hundred": Decimal(100),
    "thousand": Decimal(1_000),
    "million": Decimal(1_000_000),
    "billion": Decimal(1_000_000_000),
    "trillion": Decimal(1_000_000_000_000),
}

#: How many inputs each method takes. ``None`` means two or more.
_INPUT_COUNT: Mapping[CalculationMethod, Optional[int]] = {
    CalculationMethod.SUM: None,
    CalculationMethod.DIFFERENCE: 2,
    CalculationMethod.RATIO: 2,
    CalculationMethod.PERCENT_CHANGE: 2,
}


def read_amount(figure: Figure) -> Optional[Quantity]:
    """The amount and unit of one figure, or ``None`` if code cannot read it.

    The unit is the figure's own where E-02 recorded one, and otherwise the
    marker the value carries: a currency, or a per-cent sign. Two amounts are
    only added, subtracted or compared when their units agree, which is what
    stops "$530 million" and "530 employees" from becoming one number.
    """

    match = _AMOUNT.match(figure.value.strip())
    if match is None:
        return None
    try:
        amount = Decimal(match["digits"].replace(",", "") + (match["fraction"] or ""))
    except InvalidOperation:  # pragma: no cover - the pattern admits no other digits
        return None
    if match["sign"] == "-":
        amount = -amount
    scale = match["scale"]
    if scale is not None:
        amount *= _SCALES[scale.casefold()]
    unit = (figure.unit or "").strip() or _marker(match)
    return Quantity(amount=amount, unit=unit)


def _marker(match: re.Match[str]) -> Optional[str]:
    if match["percent"] is not None:
        return "%"
    currency = match["currency"]
    if currency is None:
        return None
    return currency if len(currency) == 1 else currency.upper()


def _derive(
    core: EvidenceCore,
    claims: Mapping[str, EvidenceClaim],
    answer: DerivationAnswer,
) -> tuple[Optional[Derivation], Optional[str]]:
    """Resolve the inputs and do the arithmetic, or say why neither happened."""

    expected = _INPUT_COUNT[answer.method]
    if expected is not None and len(answer.inputs) != expected:
        return None, (
            f"{answer.method.value} is over exactly {expected} inputs and was "
            f"given {len(answer.inputs)}"
        )
    if expected is None and len(answer.inputs) < 2:
        return None, f"{answer.method.value} is over two or more inputs"

    failure = _unheld(answer.inputs, claims)
    if failure is not None:
        return None, failure

    figures = {
        observation.observation_id: observation.figure
        for observation in core.observations
        if observation.figure is not None
    }
    quantities: list[Quantity] = []
    for ref in answer.inputs:
        found = [
            figures[observation_ref]
            for observation_ref in claims[ref].observation_refs
            if observation_ref in figures
        ]
        if len(found) != 1:
            return None, (
                f"claim {ref} records {len(found)} figure(s), and a calculation "
                "input is one figure the core holds"
            )
        quantity = read_amount(found[0])
        if quantity is None:
            return None, (
                f"the figure claim {ref} records ({found[0].value!r}) is not an "
                "amount code can read, and arithmetic is never left to the model"
            )
        quantities.append(quantity)

    units = {quantity.unit for quantity in quantities}
    if len(units) != 1:
        return None, (
            "the inputs are in "
            + ", ".join(sorted(str(unit) for unit in units))
            + ", and amounts in different units are not one quantity"
        )

    result = _apply(answer.method, quantities)
    if result is None:
        return None, f"{answer.method.value} over these amounts has no value"
    return Derivation(tuple(answer.inputs), answer.method, result), None


def _apply(
    method: CalculationMethod, quantities: Sequence[Quantity]
) -> Optional[Quantity]:
    """The arithmetic itself. Exact, and code's alone."""

    unit = quantities[0].unit
    amounts = [quantity.amount for quantity in quantities]
    try:
        if method is CalculationMethod.SUM:
            return Quantity(sum(amounts, Decimal(0)), unit)
        if method is CalculationMethod.DIFFERENCE:
            return Quantity(amounts[0] - amounts[1], unit)
        if method is CalculationMethod.RATIO:
            if amounts[1] == 0:
                return None
            # A ratio of two amounts in one unit is a number, not an amount in
            # that unit: "$8m against $4m" is 2, not $2m.
            return Quantity(amounts[0] / amounts[1], None)
        if amounts[0] == 0:
            return None
        return Quantity(
            (amounts[1] - amounts[0]) / amounts[0] * Decimal(100), "%"
        )
    except (InvalidOperation, DivisionByZero):  # pragma: no cover - guarded above
        return None


# ===========================================================================
# Internals
# ===========================================================================


def _request(core: EvidenceCore, approved_positions: Sequence[str]) -> str:
    """What the one call sees: the core, and the contract's approved positions.

    Not the research artifact, not the relevance assessment and not the #58
    hints. The core is the only source of facts (I-03), and a description built
    from anything beside it would describe something the core cannot carry.
    """

    observations = {
        observation.observation_id: observation for observation in core.observations
    }
    return json.dumps(
        {
            "approved_positions": sorted(
                value.strip() for value in approved_positions if value.strip()
            ),
            "claims": [
                {
                    "evidence_claim_id": claim.evidence_claim_id,
                    "statement": claim.statement,
                    "verdict": claim.verdict.value,
                    "scope": claim.scope,
                    "caveats": list(claim.caveats),
                    "observations": [
                        {
                            "observation_id": ref,
                            "kind": observations[ref].kind.value,
                            "excerpt": observations[ref].excerpt,
                            "attribution": observations[ref].attribution,
                            "is_third_party_assertion": (
                                observations[ref].is_third_party_assertion
                            ),
                            "figure": (
                                None
                                if observations[ref].figure is None
                                else observations[ref].figure.as_entity()
                            ),
                        }
                        for ref in claim.observation_refs
                    ],
                }
                for claim in core.evidence_claims
            ],
            "uncertainties": [
                {"uncertainty_id": item.uncertainty_id, "description": item.description}
                for item in core.uncertainties
            ],
            "contradictions": [
                {
                    "contradiction_id": item.contradiction_id,
                    "description": item.description,
                }
                for item in core.contradictions
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _value_fits(
    feature: MaterialFeature, value: Union[bool, FeatureFigureProvenance, Freshness]
) -> bool:
    """Does this value come from this feature's own vocabulary?"""

    if feature is MaterialFeature.FIGURE_PROVENANCE:
        return isinstance(value, FeatureFigureProvenance)
    if feature is MaterialFeature.FRESHNESS:
        return isinstance(value, Freshness)
    return isinstance(value, bool)


def _positive(
    feature: MaterialFeature, value: Union[bool, FeatureFigureProvenance, Freshness]
) -> bool:
    """Whether an answer asserts something, before it becomes a FeatureValue."""

    if isinstance(value, bool):
        return value
    if isinstance(value, FeatureFigureProvenance):
        return value is not FeatureFigureProvenance.NONE
    return value is not Freshness.LOW
