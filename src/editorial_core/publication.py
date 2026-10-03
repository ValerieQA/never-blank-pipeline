"""S-14 · Publication and fingerprint, in shadow (Issue #308, slice SL-7).

The stage Step 2 §1 specifies as "package, preflight, publish ``publish``-mode
texts in dependency order, store ``generate_only`` texts, and write
fingerprints. **No model and no editorial decision**" — and the one stage of
S-00…S-14 that had no module at all. ``UNWIRED_STAGES`` named it unwired, which
was honest in a stronger sense than it read: there was no entry function to
wire.

**Shadow is a mode of this stage, not a different stage.** SL-7 runs the whole
canonical chain on real signals to measure what it costs *before* anything is
optimized, and measurement must not publish. So this module does the half of
S-14 that has no external effect — package where a package can be built, and
fingerprint every accepted text — and does not do the half that reaches a
provider. What it omits it omits by not calling it, never by a flag inside a
publisher: there is no code path here that reaches a publisher, an image
provider or a marker store, which is why "no publish call" is checkable rather
than promised.

**Zero model calls.** §1's Decider column is ``code`` and its Calls column is
``0``. Nothing here takes a transport, so the stage cannot acquire a model call
by someone adding one later without changing this signature.

**Three package states, and they are not one state with a missing value**
(owner decision, 2026-10-02). A package that was built, a package whose
required input this shadow run cannot produce, and a destination whose package
type does not exist yet are three different facts about three different causes,
and #310–#313 will turn the third into one of the first two. They are recorded
as a state and a reason, because an ambiguous ``None`` would make the slice that
reads them guess which one it was looking at.

**The absorbed refusal is exactly one, and it is identified by what this stage
did rather than by what the error said.** The canonical path produces no
visuals — no stage S-00…S-13 touches one — and
``build_wix_publication_package`` requires a ``VisualAssetsRecord`` before it
reads anything else. So when this stage has no passport to pass, it passes none,
the builder's first gate refuses, and *that* refusal is the expected shadow
state. Any other refusal, and any refusal at all once a passport was supplied,
is a real failure and is raised: ``PackageFailureCategory.PROVENANCE`` covers
more than the passport gate — a generated artifact missing its headline raises
it too — so the category alone would be the wrong discriminator and is not used
as one.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §1 (S-14);
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §E-16;
``docs/editorial/architecture/07_STEP6_VERTICAL_SLICES.md`` SL-7.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping, Optional, Sequence

from src.editorial_core.destinations import (
    Destination,
    DestinationDecision,
    DestinationMode,
)
from src.editorial_core.executable_plan import ExecutablePlan
from src.editorial_core.material_features import MaterialFeatures
from src.editorial_core.candidate_strategies import EditorialStrategy
from src.editorial_core.writer import Text

#: The stage this module is, as the topology registry spells it.
STAGE: Final[str] = "S-14"

#: The destinations whose canonical publication package exists today. The other
#: four are #310–#313's (``NB-08fb``, ``NB-08ig``, ``NB-08th``, ``NB-08tg``),
#: each of which builds its own package, preflight and markers — so this slice
#: records them as having no package type rather than inventing four.
PACKAGED_DESTINATIONS: Final[tuple[Destination, ...]] = (
    Destination.WIX,
    Destination.LINKEDIN,
)

#: Why a shadow run has no visual passport. Stated once, because it is one fact
#: about this slice and not a per-destination judgment: the canonical engine
#: produces no visuals, and producing them means running the image pipeline,
#: which is an external side effect SL-7 excludes.
NO_VISUAL_PASSPORT: Final[str] = (
    "the required visual passport was unavailable in this shadow run: the "
    "canonical engine produces no visuals and this run does not call the image "
    "pipeline"
)

#: Why `text_profile` carries no abstraction measurement. V-S02's own criterion
#: asks "how much abstraction precedes it", which is a judgment its code would
#: make — and V-S02 has no implementation on this main. Recorded as absent with
#: this reason rather than as a zero nobody measured (owner decision,
#: 2026-10-02).
NO_VS02_PRODUCER: Final[str] = (
    "no producer on main: V-S02 is a candidate check with a record in "
    "knowledge/checks/ and no implementation, so the abstraction preceding the "
    "first evidence was not measured"
)

#: How a sentence ends, as the rest of this layer already splits them.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

#: A word, as the shingle profile already counts them.
_WORD = re.compile(r"[a-z0-9']+")


class PublicationError(RuntimeError):
    """S-14 was asked to publish or fingerprint something it cannot."""


# ===========================================================================
# A measurement that was made, or was not — never both, and never neither
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ScalarMetric:
    """One number the profile carries, or a stated reason it carries none.

    The shape ``InputVersion`` uses for a §4.1 input, for the same reason: a
    reader must be able to tell a measurement whose value is zero from a metric
    nobody measured, and a bare ``None`` tells them neither. Exactly one of the
    two is set, and the constructor refuses anything else.
    """

    name: str
    value: Optional[float] = None
    absent_reason: Optional[str] = None

    def __post_init__(self) -> None:
        _measured_or_stated_absent(
            self.name, self.value is not None, self.absent_reason
        )

    @property
    def measured(self) -> bool:
        return self.value is not None

    def as_entity(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "absent_reason": self.absent_reason,
        }


@dataclass(frozen=True, slots=True)
class DistributionMetric:
    """A distribution the profile carries, or a stated reason it carries none.

    ``values`` is ``None`` when the metric was not measured and a tuple when it
    was — including the empty tuple, which is a measurement: a text with no
    paragraph has a paragraph-length distribution of nothing, and that is not
    the same fact as a distribution nobody computed. Keeping those two apart in
    the serialized form is the whole point of this type.
    """

    name: str
    values: Optional[tuple[int, ...]] = None
    absent_reason: Optional[str] = None

    def __post_init__(self) -> None:
        _measured_or_stated_absent(
            self.name, self.values is not None, self.absent_reason
        )

    @property
    def measured(self) -> bool:
        return self.values is not None

    @property
    def spread(self) -> Optional[float]:
        """The spread V-S04 asks for, over a measured distribution of two or more.

        ``None`` where there is nothing to spread — one value, or none — which
        is a property of the measurement rather than a second absence.
        """

        if self.values is None or len(self.values) < 2:
            return None
        return statistics.pstdev(self.values)

    def as_entity(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "values": None if self.values is None else list(self.values),
            "spread": self.spread,
            "absent_reason": self.absent_reason,
        }


def _measured_or_stated_absent(
    name: str, measured: bool, absent_reason: Optional[str]
) -> None:
    if measured and absent_reason is not None:
        raise PublicationError(
            f"{name} carries both a measurement and a reason for having none; "
            "a metric is one or the other, and a record that is both cannot be "
            "read as either"
        )
    if not measured and absent_reason is None:
        raise PublicationError(
            f"{name} carries neither a measurement nor a reason for having "
            "none; an unmeasured metric says why, so that a reader never has "
            "to decide whether a missing value meant zero"
        )


# ===========================================================================
# E-16's text profile
# ===========================================================================


@dataclass(frozen=True, slots=True)
class TextProfile:
    """``E-16.text_profile``: "position of the first evidence, paragraph and
    sentence length distribution, and other V-S02/V-S04 metrics".

    Partially populated on purpose (owner decision, 2026-10-02). The three the
    entity names are measured here from production artifacts and plain counting;
    the V-S02 metric that needs V-S02's unimplemented judgment is carried as an
    explicit absence. The field itself stays required, because a fingerprint
    with no profile at all could not be told from one whose text had nothing to
    measure.
    """

    first_evidence_position: ScalarMetric
    paragraph_lengths: DistributionMetric
    sentence_lengths: DistributionMetric
    #: The metrics the entity's "and other V-S02/V-S04 metrics" names and this
    #: main cannot produce. Present, named and absent — never omitted.
    unmeasured: tuple[ScalarMetric, ...] = ()

    def __post_init__(self) -> None:
        for metric in self.unmeasured:
            if metric.measured:
                raise PublicationError(
                    f"{metric.name} is listed among the unmeasured metrics and "
                    "carries a value; a measurement belongs in the profile's "
                    "own field, where a reader looks for it"
                )

    def as_entity(self) -> dict[str, Any]:
        return {
            "first_evidence_position": self.first_evidence_position.as_entity(),
            "paragraph_lengths": self.paragraph_lengths.as_entity(),
            "sentence_lengths": self.sentence_lengths.as_entity(),
            "unmeasured": [metric.as_entity() for metric in self.unmeasured],
        }


def text_profile(
    text: Text, plan: ExecutablePlan, strategy: EditorialStrategy
) -> TextProfile:
    """Measure the accepted text, and say what was not measured.

    Three measurements and one stated absence. Nothing here decides what counts
    as evidence or as a specific: **E-13 already said**, by giving each move its
    ``refs``, and E-14 said which part carries which move. So the first
    evidence's position is read off the run's own artifacts rather than found by
    a rule about prose, which is what keeps this a measurement rather than the
    heuristic V-S02 would have to make.
    """

    body = text.body
    words = _WORD.findall(body.lower())
    paragraphs = tuple(
        len(_WORD.findall(part.lower()))
        for part in body.split("\n\n")
        if part.strip()
    )
    sentences = tuple(
        len(_WORD.findall(part.lower()))
        for part in _SENTENCE.split(body.strip())
        if part.strip()
    )
    return TextProfile(
        first_evidence_position=_first_evidence_position(
            text, plan, strategy, total=len(words)
        ),
        paragraph_lengths=DistributionMetric(
            name="paragraph_lengths", values=paragraphs
        ),
        sentence_lengths=DistributionMetric(
            name="sentence_lengths", values=sentences
        ),
        unmeasured=(
            ScalarMetric(
                name="abstraction_before_first_evidence",
                absent_reason=NO_VS02_PRODUCER,
            ),
        ),
    )


def _first_evidence_position(
    text: Text,
    plan: ExecutablePlan,
    strategy: EditorialStrategy,
    *,
    total: int,
) -> ScalarMetric:
    """Where the first part carrying evidence begins, as a fraction of the text.

    Composed entirely of fields the run already holds: a move's ``refs`` (E-13),
    the ``move_indices`` a segment carries (E-14), and the ordered parts aligned
    to those segments by name (E-15). The position is the word offset at which
    that part begins, over the body's word count.

    Absent — stated, not defaulted — when the text carries no word at all,
    because a fraction of nothing is not zero.
    """

    name = "first_evidence_position"
    if total == 0:
        return ScalarMetric(
            name=name,
            absent_reason=(
                "the accepted text carries no word, so there is no text for a "
                "position to be a fraction of"
            ),
        )
    carrying = {
        segment.name
        for segment in plan.segments
        if any(
            strategy.reader_path[index - 1].refs
            for index in segment.move_indices
            if 1 <= index <= len(strategy.reader_path)
        )
    }
    offset = 0
    for part in text.segments:
        if part.name in carrying:
            return ScalarMetric(name=name, value=offset / total)
        offset += len(_WORD.findall(part.text.lower()))
    return ScalarMetric(
        name=name,
        absent_reason=(
            "no part of the accepted text realizes a plan segment whose moves "
            "carry an evidence reference, so the text holds no first evidence "
            "to position"
        ),
    )


# ===========================================================================
# The three package states (owner decision, 2026-10-02)
# ===========================================================================


class PackageState(str, Enum):
    """What happened to one destination's canonical publication package.

    Three states because there are three causes, and a later slice turns the
    third into one of the first two: #310–#313 give Facebook, Instagram,
    Threads and Telegram a package type, and the destinations that have one
    then either build it or say which input was missing.
    """

    BUILT = "built"
    REQUIRED_INPUT_UNAVAILABLE = "required_input_unavailable"
    NO_PACKAGE_TYPE = "no_package_type"


@dataclass(frozen=True, slots=True)
class PackageRecord:
    """One destination's package, or the reason there is none.

    ``digest`` is set exactly for a package that was built and ``reason``
    exactly for one that was not, with the same discipline the metrics keep: a
    reader never has to work out whether an absent package meant "not attempted",
    "attempted and refused" or "no such thing yet", because the state says
    which and the reason says why.
    """

    destination: Destination
    state: PackageState
    digest: Optional[str] = None
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        built = self.state is PackageState.BUILT
        if built and (self.digest is None or self.reason is not None):
            raise PublicationError(
                f"{self.destination.value}'s package is recorded as built and "
                "carries no digest, or carries a reason as well; a built "
                "package is identified by what it contains"
            )
        if not built and (self.digest is not None or self.reason is None):
            raise PublicationError(
                f"{self.destination.value}'s package is recorded as "
                f"{self.state.value} and carries a digest, or carries no "
                "reason; a package that was not built says why"
            )

    @property
    def built(self) -> bool:
        return self.state is PackageState.BUILT

    def as_entity(self) -> dict[str, Any]:
        return {
            "destination": self.destination.value,
            "state": self.state.value,
            "digest": self.digest,
            "reason": self.reason,
        }


# ===========================================================================
# E-16 · the fingerprint
# ===========================================================================


def fingerprint_id(run_id: str, destination: Destination) -> str:
    """``E-16.fingerprint_id``: one fingerprint per run per destination.

    Named for the **run** and not for the unit, which the pass-through
    skeleton's ``fp-<unit_id>-<destination>`` was: that shape is unique inside
    one run and collides across runs, and it could because the skeleton wrote
    no durable record. E-16 is durable — Step 3 §3.2 retains it indefinitely at
    ``fingerprints/<client>/<yyyy-mm>/<fp_id>.json`` and the ledger is
    create-once — so a second run over the same signal must file a second
    fingerprint rather than be refused as a duplicate of the first. Two runs of
    one signal are two things Portfolio Memory has to remember, not one.

    The unit, the text version and the digest are all still on the record; what
    the ID has to carry is only enough to make the path unique.
    """

    if not run_id.strip():
        raise PublicationError(
            "a fingerprint is named for the run whose text it remembers"
        )
    return f"fp-{run_id}-{destination.value}"


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """``E-16``: what Portfolio Memory remembers about one accepted text.

    Step 1 §E-16's field set, and only it. The two fields that may legitimately
    be absent are absent here for stated reasons rather than by omission:

    - ``label_ref`` — labels are written after the decision and are never
      routed to S-00…S-13 (AD-07), so a fingerprint without one is valid and
      this slice produces none;
    - ``publication`` — "if published", and a shadow run publishes nothing, so
      it is absent because nothing happened rather than because nothing was
      recorded.

    ``deciding_tiebreaker`` is ``None`` for the ordinary case where code
    exclusion left one admissible candidate and no tie-break was needed. That
    is a measured fact about the selection, not an unmeasured metric, which is
    why it is a plain optional and not a :class:`ScalarMetric`.
    """

    fingerprint_id: str
    client: str
    destination: Destination
    unit_id: str
    text_ref: tuple[str, int]
    content_digest: str
    mode: DestinationMode
    features: Mapping[str, Any]
    strategy: Mapping[str, Any]
    adaptation: Mapping[str, Any]
    text_profile: TextProfile
    deciding_tiebreaker: Optional[str] = None
    label_ref: Optional[str] = None
    publication: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        if not self.fingerprint_id.strip() or not self.client.strip():
            raise PublicationError(
                "a fingerprint is identified by its own ID and the client whose "
                "portfolio remembers it"
            )
        if not self.content_digest.startswith("sha256:"):
            raise PublicationError(
                f"{self.fingerprint_id} carries {self.content_digest!r} as the "
                "digest of what was remembered; E-16 remembers a text by the "
                "digest E-15 derives, and a value in another shape is a "
                "comparison nobody can make"
            )

    def as_entity(self) -> dict[str, Any]:
        """The E-16 record, as the durable ledger stores it.

        Flat and serializable, because Portfolio Memory outlives the 90-day run
        workspace: a reader a year from now has this file and no objects.
        """

        return {
            "fingerprint_id": self.fingerprint_id,
            "client": self.client,
            "destination": self.destination.value,
            "unit_id": self.unit_id,
            "text_ref": list(self.text_ref),
            "content_digest": self.content_digest,
            "mode": self.mode.value,
            "features": dict(self.features),
            "strategy": dict(self.strategy),
            "adaptation": dict(self.adaptation),
            "text_profile": self.text_profile.as_entity(),
            "deciding_tiebreaker": self.deciding_tiebreaker,
            "label_ref": self.label_ref,
            "publication": None if self.publication is None else dict(self.publication),
        }


# ===========================================================================
# What one accepted text is fingerprinted from
# ===========================================================================


@dataclass(frozen=True, slots=True)
class AcceptedText:
    """One accepted ``E-15`` and the artifacts E-16 snapshots beside it.

    Handed over rather than looked up: S-14 reads what the run produced, and a
    stage that went looking for its own inputs could fingerprint a version the
    run did not accept. ``features``, ``strategy`` and ``adaptation`` are the
    three snapshots §E-16 requires, each taken from the entity that owns it.
    """

    text: Text
    decision: DestinationDecision
    plan: ExecutablePlan
    strategy: EditorialStrategy
    features: MaterialFeatures
    deciding_tiebreaker: Optional[str] = None

    def __post_init__(self) -> None:
        if self.decision.destination is not self.text.destination:
            raise PublicationError(
                f"{self.text.text_id} is for {self.text.destination.value} and "
                f"carries {self.decision.destination.value}'s decision; a "
                "fingerprint records one destination's text, and a crossed pair "
                "would remember the wrong one"
            )
        if self.decision.mode is None:
            raise PublicationError(
                f"{self.decision.destination.value} reached S-14 with no mode; "
                "§E-16 flags every fingerprint `publish` or `generate_only`, "
                "and a text whose destination was never made eligible has "
                "neither"
            )


@dataclass(frozen=True, slots=True)
class PackageInputs:
    """What the existing canonical package builders require, as the run holds it.

    Every field optional, and that is the point: this slice does not fabricate
    a single one of them. ``build_wix_publication_package`` and its LinkedIn
    counterpart take a legacy ``generated`` artifact, a non-secret target
    identity and a visual passport, and a canonical shadow run holds none of
    the three — it produces ``E-15``, it calls no image pipeline, and it reads
    no publication target. So the attempt is made when a caller can supply
    them, and recorded as unavailable, **naming each one that is missing**, when
    it cannot.
    """

    generated: Optional[Mapping[str, Any]] = None
    visual_record: Optional[Any] = None
    wix_target: Optional[Any] = None
    linkedin_target: Optional[Any] = None
    linkedin_composition: Optional[Mapping[str, Any]] = None
    run_id: Optional[str] = None
    signal_id: Optional[str] = None
    configuration_identity: Optional[Any] = None

    def missing_for(self, destination: Destination) -> tuple[str, ...]:
        """Which inputs the call itself cannot be made without.

        **The visual passport is not among them**, deliberately. ``None`` is a
        legal value for it — the builders take ``Optional[VisualAssetsRecord]``
        and refuse it at their own first gate — so withholding the call because
        the passport is absent would mean the package was never attempted, and
        the attempt is what the owner's decision asks for. Everything listed
        here is different: without it there is no call to make at all, because
        the argument is not optional.
        """

        required: list[tuple[str, Any]] = [
            ("run_id", self.run_id),
            ("signal_id", self.signal_id),
            ("configuration_identity", self.configuration_identity),
            ("generated", self.generated),
        ]
        if destination is Destination.WIX:
            required.append(("wix target", self.wix_target))
        else:
            required.append(("linkedin target", self.linkedin_target))
            required.append(("linkedin composition", self.linkedin_composition))
        return tuple(name for name, value in required if value is None)


# ===========================================================================
# The stage
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ShadowPublication:
    """What S-14 made of one unit's accepted texts, publishing nothing.

    ``calls`` is zero and is carried so the trace can record it as zero rather
    than leave a reader to infer it: §1 gives S-14 ``0`` calls, and a stage that
    silently made one would be indistinguishable from one that did not.
    """

    fingerprints: tuple[Fingerprint, ...] = ()
    packages: tuple[PackageRecord, ...] = ()
    calls: int = 0

    def package_for(self, destination: Destination) -> PackageRecord:
        for record in self.packages:
            if record.destination is destination:
                return record
        raise PublicationError(
            f"no package record for {destination.value}; S-14 records one per "
            "accepted text, including the destinations whose package type does "
            "not exist yet"
        )


def publish_in_shadow(
    *,
    accepted: Sequence[AcceptedText],
    unit_id: str,
    run_id: str,
    client: str,
    inputs: Optional[PackageInputs] = None,
) -> ShadowPublication:
    """Fingerprint every accepted text, and package what can be packaged.

    The shadow half of S-14. It reaches no provider, no image pipeline and no
    marker store — not by a flag, but because no such call exists in this
    function or anything it calls. ``publication`` is therefore absent on every
    fingerprint, which is the honest record of a run that published nothing.

    Raises :class:`PublicationError` for a run that cannot honestly be
    fingerprinted — an accepted text whose destination has no mode, a crossed
    text and decision — and lets every unexpected package refusal through.
    """

    if not unit_id.strip() or not run_id.strip():
        raise PublicationError(
            "S-14 fingerprints one unit's accepted texts in one run, and this "
            "round names no unit or no run"
        )
    supplied = inputs if inputs is not None else PackageInputs()
    fingerprints: list[Fingerprint] = []
    packages: list[PackageRecord] = []
    for item in accepted:
        destination = item.decision.destination
        assert item.decision.mode is not None  # refused in AcceptedText
        fingerprints.append(
            Fingerprint(
                fingerprint_id=fingerprint_id(run_id, destination),
                client=client,
                destination=destination,
                unit_id=unit_id,
                text_ref=item.text.text_ref,
                content_digest=item.text.content_digest,
                mode=item.decision.mode,
                features=item.features.as_entity(),
                strategy=_normalized_strategy(item),
                adaptation=item.plan.as_entity(),
                text_profile=text_profile(item.text, item.plan, item.strategy),
                deciding_tiebreaker=item.deciding_tiebreaker,
                # label_ref: AD-07 — labels are post-decision and never routed
                # to S-00…S-13, so this slice produces none and says so by
                # carrying none.
                label_ref=None,
                # publication: "if published". Nothing was.
                publication=None,
            )
        )
        packages.append(_packaged(destination, supplied))
    return ShadowPublication(
        fingerprints=tuple(fingerprints), packages=tuple(packages), calls=0
    )


def _normalized_strategy(item: AcceptedText) -> dict[str, Any]:
    """``E-16.strategy``: "snapshot of E-13 fields, normalized for comparison".

    Normalized the way the portfolio already compares texts: V-S05's own
    projection reads a prior publication's reader path, opening and ending
    through ``text_reader_path``, ``text_opening`` and ``text_ending``, so a
    fingerprint written here is in the form the check that will read it expects.
    Writing a second normalization would make the two incomparable, which is
    the one thing a comparison snapshot must not be.
    """

    from src.editorial_core.text_check import (
        shingles,
        text_ending,
        text_opening,
        text_reader_path,
    )

    return {
        "strategy_id": item.strategy.strategy_id,
        "reader_path": list(text_reader_path(item.text)),
        "opening": text_opening(item.text),
        "ending": text_ending(item.text),
        "shingles": sorted(shingles(item.text.body)),
    }


def _packaged(
    destination: Destination, inputs: PackageInputs
) -> PackageRecord:
    """Attempt one destination's canonical package, or say why there is none.

    Three outcomes and one escape. A destination with no package type is
    recorded as such; a destination whose builder exists is **called** when the
    run can supply its inputs and recorded as unavailable, naming them, when it
    cannot; and the builder's own refusal is absorbed only in the single case
    this stage caused — see :func:`_absorbed`.
    """

    if destination not in PACKAGED_DESTINATIONS:
        return PackageRecord(
            destination=destination,
            state=PackageState.NO_PACKAGE_TYPE,
            reason=(
                f"no canonical publication package exists for "
                f"{destination.value} yet; it is built by the capability slice "
                "that owns the destination, and this slice does not invent one"
            ),
        )
    missing = inputs.missing_for(destination)
    if missing:
        stated = f"{destination.value}'s package could not be attempted: this "
        stated += "shadow run cannot supply " + ", ".join(missing)
        return PackageRecord(
            destination=destination,
            state=PackageState.REQUIRED_INPUT_UNAVAILABLE,
            reason=stated,
        )
    return _built(destination, inputs)


def _built(destination: Destination, inputs: PackageInputs) -> PackageRecord:
    """Call the existing builder, and absorb exactly one refusal.

    The builders are reused, never duplicated: this is the production
    ``build_wix_publication_package`` / ``build_linkedin_publication_package``
    with the run's own evidence, and nothing here relaxes a gate.
    """

    from src.publishing.package import (
        PublicationPackageError,
        build_linkedin_publication_package,
        build_wix_publication_package,
    )

    shared = {
        "run_id": inputs.run_id,
        "signal_id": inputs.signal_id,
        "configuration_identity": inputs.configuration_identity,
        "generated": inputs.generated,
        "visual_record": inputs.visual_record,
    }
    try:
        if destination is Destination.WIX:
            package = build_wix_publication_package(
                **shared, target=inputs.wix_target
            )
        else:
            package = build_linkedin_publication_package(
                **shared,
                linkedin_composition=inputs.linkedin_composition,
                target=inputs.linkedin_target,
            )
    except PublicationPackageError as refused:
        absorbed = _absorbed(refused, visual_record=inputs.visual_record)
        if absorbed is None:
            # Not the absence this slice causes. A malformed visual record, a
            # provenance or lineage mismatch, configuration drift, an unusable
            # target or payload — each is a real failure of a run that had
            # everything it needed, and turning them all into "unavailable"
            # would make the one expected state unreadable.
            raise
        return PackageRecord(
            destination=destination,
            state=PackageState.REQUIRED_INPUT_UNAVAILABLE,
            reason=absorbed,
        )
    return PackageRecord(
        destination=destination,
        state=PackageState.BUILT,
        digest=_package_digest(package),
    )


def _absorbed(refused: Exception, *, visual_record: Any) -> Optional[str]:
    """Is this the refusal this stage caused by having no passport to pass?

    Two facts together, and neither alone:

    1. **this stage passed no passport** — so the only gate it can have tripped
       is the one that asks for it, which is the first statement of both
       builders. Nothing after it has run, so no later ``PROVENANCE`` failure is
       reachable;
    2. the refusal is ``PROVENANCE``-scoped.

    The category alone would be the wrong test: a generated artifact missing its
    headline raises ``PROVENANCE`` too, and absorbing that would hide a real
    defect behind an expected state. The message is not matched at all, because
    a refusal's wording is not an interface.
    """

    from src.publishing.package import PackageFailureCategory

    if visual_record is not None:
        return None
    category = getattr(refused, "category", None)
    if category is not PackageFailureCategory.PROVENANCE:
        return None
    return f"{NO_VISUAL_PASSPORT} (the builder refused: {refused})"


def _package_digest(package: Any) -> str:
    """A built package, identified by what it contains.

    Over the package's own canonical serialization, so two runs that built the
    same package agree and a run that built a different one does not.
    """

    import hashlib
    import json

    body = package.model_dump(mode="json")
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ===========================================================================
# Where a fingerprint is kept
# ===========================================================================

#: The ledger directory Step 3 §3.2 gives E-16:
#: ``data/editorial/fingerprints/<client>/<yyyy-mm>/<fp_id>.json``, retained
#: indefinitely. The run workspace keeps its own copy at
#: ``fingerprints/<fp_id>.json`` (§2.2) and that one expires with the run — so
#: the ledger copy is the one Portfolio Memory reads a year later, which is why
#: ``data/editorial/`` is committed on purpose and deliberately un-ignored.
FINGERPRINTS_DIRECTORY: Final[str] = "fingerprints"


def fingerprint_ledger_path(fingerprint: Fingerprint, *, month: str) -> str:
    """One fingerprint's durable path, relative to the ledger root (§3.2)."""

    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise PublicationError(
            f"a fingerprint is filed under the month it was made, as "
            f"`yyyy-mm`; got {month!r}"
        )
    return (
        f"{FINGERPRINTS_DIRECTORY}/{fingerprint.client}/{month}/"
        f"{fingerprint.fingerprint_id}.json"
    )


def write_fingerprint_to_ledger(
    fingerprint: Fingerprint, *, month: str, root: Optional[Any] = None
) -> Any:
    """Commit one E-16 to the durable ledger, create-once (P1, P4).

    The ledger's own writer, not a second one: one record, one file, and a
    second run that produced the same path is refused rather than merged,
    because Portfolio Memory is append-only and an edit is a new record.
    """

    from src.run.ledger import write_record

    return write_record(
        fingerprint_ledger_path(fingerprint, month=month),
        fingerprint.as_entity(),
        root=root,
    )
