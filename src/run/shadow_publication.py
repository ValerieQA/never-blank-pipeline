"""S-14 in shadow mode: fingerprints, no markers, no publish call (#308, SL-7).

SL-7 runs the complete canonical chain **S-00 → S-14** on real signals and
measures what it costs before anything is optimized. S-14 is the last stage of
that chain and the first one that could reach a platform, so this module is
written so that it cannot:

- it **constructs no publisher**. The six publishers live in
  ``src/publishing/<destination>.py``; none of them is imported here, and there
  is no argument, flag or configuration value that would reach one. The property
  is structural rather than guarded, which is the same shape
  :func:`~src.run.walking_skeleton.run_golden_engine` uses for its transports;
- it **consults no idempotency authority and writes no marker**. §3.6's
  publication transaction — lookup, durable intent, external call, durable
  marker — begins with a lookup *because* a publication is about to happen. A
  run that will not publish has nothing to be idempotent about, and a lookup
  made anyway would record this run in an authority that exists to arbitrate
  real publications. ``src/publishing/publication_markers.py`` is not imported;
- it **publishes nothing and says so per destination**. Every eligible
  destination holding an accepted text gets a ``publication.json`` stating that
  the publication was withheld because this is a shadow run — the third state
  beside §3's "published" and "skipped", recorded rather than spelled as one of
  the two it is not.

What it does produce
--------------------
**The fingerprint (E-16), of which S-14 is the sole producer.** One per accepted
text, flagged with the destination's decided ``mode``, carrying the snapshots
Step 1 §4 lists: the E-05 feature values, the normalized E-13 strategy fields,
the E-14 adaptation fields, the text profile V-S02 and V-S04 describe, and the
deciding tie-breaker. It is what Portfolio Memory remembers, and it is the
reason a shadow run is worth taking at all.

**Packages where they exist.** §3's seam column extends `package.py` and
`preflight.py` to the four destinations that have neither, and SL-8/SL-9 own
that work; the existing Wix and LinkedIn builders take the *legacy* generated
artifact with its visual passport, not a canonical E-15. So the production
registry of canonical packagers is **empty today**, and every destination
records :attr:`PackageState.BUILDER_NOT_AVAILABLE` naming the slice that will
fill it. Empty rather than absent, for the reason #231 left ``_PUBLISHERS``
empty: the loop still handles whatever it is given, so SL-9 adds a row and
changes no logic here — and a stage that is offered no packager cannot package
by accident.

Two durability rules this module keeps
--------------------------------------
**A fingerprint of a text nothing published is never read as a publication.**
S-13 takes two narrow views of prior fingerprints and they are not the same
question: :class:`~src.editorial_core.text_check.TextFingerprint` is V-S05's
portfolio pressure, which counts generated texts too, and
:class:`~src.editorial_core.text_check.PriorPublication` is V-T05's "has this
already been published here", which counts only publications.
:func:`portfolio_text` therefore projects every fingerprint and
:func:`prior_publication` projects **none of a shadow run's**, because none of
them published. A single projection serving both would make a later run refuse
a text as a republication of something that was never published.

**Nothing unpublished reaches the public ledger.** §6 keeps unpublished bodies
and source excerpts out of the committed tier, and §3.4 stores a
``generate_only`` fingerprint "without the body". The workspace copy
(:meth:`Fingerprint.as_entity`, 90 days, never committed) carries the full
profile including the opening and ending sentences V-S05 compares; the ledger
copy (:meth:`Fingerprint.as_ledger_record`, indefinite, committed to a public
repository) carries the structural measurements and the content digest and no
text at all. §3.4's "similarity sketch (a MinHash-style n-gram signature)" is
not in the ledger copy either: no such signature is defined anywhere in this
repository, and inventing one here would be designing the portfolio index
rather than measuring a run. A reader of a ledger fingerprint gets ``None`` for
the fields it does not carry, which is exactly what ``TextFingerprint`` makes
every one of its dimensions optional for.

Why this module is in ``src/run/``
----------------------------------
S-14 is **not** an editorial-core stage: the topology registry's own
``editorial_core_stage_ids`` ends at S-13, because publication is where
destination capability legitimately decides what happens. So this does not
belong in ``src/editorial_core/``.

Nor can it live in ``src/publishing/`` beside the six publishers, which is the
first place a reader would look for it. AD-05's allowed import direction is one
way: ``src/run/`` and ``src/editorial_core/`` may reach into the legacy layer,
and ``src/publishing/`` and ``src/editorial/`` may never reach into the core.
This stage reads E-05, E-12, E-13, E-14, E-15 and the TextVerdict — it is made
of core types — so placing it under ``src/publishing/`` would have given the
legacy publishing layer an import of an engine it does not run, and ended the
OFF path's independence. ``src/run/`` is the canonical engine layer, outside the
editorial core and on the permitted side of the wall, which is both constraints
satisfied rather than one traded for the other.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §3 (S-14);
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §4 (E-16);
``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §2.2, §3.2,
§3.4 and §6; ``docs/editorial/architecture/07_STEP6_VERTICAL_SLICES.md`` SL-7;
``knowledge/checks/V-S02.md`` and ``knowledge/checks/V-S04.md``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final, NamedTuple, Optional, Protocol

from src.editorial_core.candidate_strategies import EditorialStrategy
from src.editorial_core.destinations import (
    Destination,
    DestinationDecision,
    DestinationMode,
    Eligibility,
    publication_order,
)
from src.editorial_core.executable_plan import ExecutablePlan
from src.editorial_core.material_features import MaterialFeatures
from src.editorial_core.strategy_selection import StrategySelection
from src.editorial_core.text_check import (
    PriorPublication,
    TextFingerprint,
    TextVerdict,
    normalized_sentence,
    shingles,
    text_ending,
    text_opening,
    text_reader_path,
)
from src.editorial_core.writer import Text
from src.run.ledger import write_record

#: The stage this module is, as §6.2 names it.
STAGE: Final[str] = "S-14"

#: Entity types, as Step 1 names them.
FINGERPRINT_ENTITY_TYPE: Final[str] = "E-16"
#: §2.2 gives ``publication.json`` no map ID: it is "package digests, preflight,
#: result refs", the record of what S-14 did rather than a typed entity of the
#: map. It is named here so a reader of the manifest can tell it from one.
PUBLICATION_ENTITY_TYPE: Final[str] = "PublicationRecord"

#: Why nothing was published. One value, because in shadow mode there is one
#: reason and it is never about the text: the run makes no external call at all.
#: A closed token rather than a sentence, because it reaches persisted evidence.
WITHHELD_IN_SHADOW_RUN: Final[str] = "withheld_in_shadow_run"

#: ``data/editorial/fingerprints/<client>/<yyyy-mm>/<fp_id>.json`` (§3.2).
FINGERPRINTS_DIRECTORY: Final[str] = "fingerprints"

#: The keys that carry text. Refused in a ledger record of a text nothing
#: published (§6), as the one check on the one function that writes there.
_TEXT_BEARING_KEYS: Final[frozenset[str]] = frozenset(
    {"body", "opening", "ending", "shingles", "segments"}
)

#: What V-S02's "first specific" is, of the four kinds its criterion lists.
#: A figure, a date and a quoted fact are all in the text; a **named party** is
#: not, because recognising one needs the core's parties and this stage reads no
#: core. The kinds actually looked for are recorded beside the count
#: (:attr:`TextProfile.specific_kinds`), so "no named party was searched for"
#: can never be read as "no named party was there".
_SPECIFIC_KINDS: Final[tuple[str, ...]] = ("figure", "date", "quoted_fact")
_SPECIFIC = re.compile(
    r"\d[\d,.]*\s*(?:%|percent|million|billion|bn|m|k)?"
    r"|\"[^\"]+\""
    r"|“[^”]+”"
)

_WORD = re.compile(r"[^\s]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class ShadowPublicationError(RuntimeError):
    """S-14 was asked for a publication record it cannot honestly make."""


# ===========================================================================
# Packaging: the seam SL-8 and SL-9 fill
# ===========================================================================


class PackageState(str, Enum):
    """What became of one destination's canonical package.

    ``BUILDER_NOT_AVAILABLE`` is a state of this repository and not of the
    text: no canonical packager exists for the destination yet. It is its own
    value rather than an absent digest, because "no package was built" and "a
    package was built and is empty" are different facts and only one of them is
    a reason to look at the text.
    """

    BUILT = "built"
    BUILDER_NOT_AVAILABLE = "builder_not_available"


class CanonicalPackager(Protocol):
    """Builds one destination's canonical package and returns its digest.

    One method and one return value, because §3's Trace column asks S-14 for
    "package digests" and nothing here needs the package itself. The package
    *type* belongs to the slice that builds it (SL-8 for the four destinations
    that have none, SL-9 for Wix and LinkedIn on canonical texts), and
    inventing one in the slice that only measures would decide its shape.
    """

    def package_digest(self, *, text: Text, plan: ExecutablePlan) -> str: ...


#: The canonical packagers in production. **Empty today**, and empty rather
#: than absent: #231 left ``_PUBLISHERS`` empty for the same reason, so that a
#: path offered nothing cannot act by accident and the slice that has something
#: to offer adds a row instead of a branch. SL-9 adds Wix and LinkedIn;
#: SL-8 adds Facebook, Instagram, Threads and Telegram.
CANONICAL_PACKAGERS: Final[Mapping[Destination, CanonicalPackager]] = {}

#: Which slice provides the packager a destination has none of. Recorded in the
#: publication record so that a reader of a shadow run can tell a missing
#: capability from a failed one, and knows where the capability comes from.
#: Two groups rather than six names, because that is what Step 6 declares: SL-9
#: is "Wix and LinkedIn on canonical texts" and SL-8a…d is "one slice per
#: destination, same shape" for the other four, without saying which letter is
#: which — and a letter chosen here would be an answer nobody wrote down.
_SL8: Final[str] = "SL-8"
_PACKAGER_SLICE: Final[Mapping[Destination, str]] = {
    Destination.WIX: "SL-9",
    Destination.LINKEDIN: "SL-9",
    Destination.FACEBOOK: _SL8,
    Destination.INSTAGRAM: _SL8,
    Destination.THREADS: _SL8,
    Destination.TELEGRAM: _SL8,
}


@dataclass(frozen=True, slots=True)
class PackageOutcome:
    """One destination's package, or the recorded absence of a builder."""

    state: PackageState
    #: The package digest, when one was built. ``None`` is the absence of a
    #: builder and never an empty package: :class:`PackageState` says which.
    digest: Optional[str] = None
    #: The slice that provides the missing builder. Present only when there is
    #: one missing.
    expected_from: Optional[str] = None

    def __post_init__(self) -> None:
        built = self.state is PackageState.BUILT
        if built != (self.digest is not None):
            raise ShadowPublicationError(
                f"a package recorded as {self.state.value} carries digest "
                f"{self.digest!r}; a built package has one and an absent "
                "builder produced nothing to digest"
            )
        if built and self.expected_from is not None:
            raise ShadowPublicationError(
                "a built package names the slice that would provide its "
                "builder; the builder is here, and naming a future one would "
                "read as a package still waiting for it"
            )

    def as_entity(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "digest": self.digest,
            "expected_from": self.expected_from,
        }


def _package(
    destination: Destination,
    text: Text,
    plan: ExecutablePlan,
    packagers: Mapping[Destination, CanonicalPackager],
) -> PackageOutcome:
    """Build the destination's package if a packager exists, or record that
    none does."""

    packager = packagers.get(destination)
    if packager is None:
        return PackageOutcome(
            state=PackageState.BUILDER_NOT_AVAILABLE,
            expected_from=_PACKAGER_SLICE[destination],
        )
    digest = packager.package_digest(text=text, plan=plan)
    if not isinstance(digest, str) or not digest.strip():
        raise ShadowPublicationError(
            f"the canonical packager for {destination.value} returned "
            f"{digest!r} as a package digest; §3 records package digests in the "
            "trace, and one that says nothing records nothing"
        )
    return PackageOutcome(state=PackageState.BUILT, digest=digest)


# ===========================================================================
# E-16 · the fingerprint
# ===========================================================================


@dataclass(frozen=True, slots=True)
class TextProfile:
    """E-16's ``text_profile``: V-S02's and V-S04's measurements (§4).

    Measurements and never verdicts. Both records say so in their own words —
    "the numbers are recorded as measurements", "what is recorded is the
    distribution itself, not a verdict on it" — and both are marked *not
    validated*, so no value here is compared with anything and no threshold is
    proposed (I-12).

    Every count is an integer and every list is in the text's own order, so the
    spreads V-S04 eventually wants and the fraction V-S02 eventually wants are
    **derived** by whoever asks rather than stored beside their inputs, where
    the two could disagree.
    """

    #: Words before the first figure, date or quoted fact. ``None`` when the
    #: text holds none of the three, which is not the same as ``0`` — zero is a
    #: text that opens with one.
    words_before_first_specific: Optional[int]
    #: Which kinds of "specific" were looked for. See :data:`_SPECIFIC_KINDS`.
    specific_kinds: tuple[str, ...]
    words: int
    #: Words per paragraph and per sentence, in order (V-S04's distribution).
    paragraph_words: tuple[int, ...]
    sentence_words: tuple[int, ...]
    #: The ordered part names of the text: its reader path as executed.
    reader_path: tuple[str, ...]
    #: V-S05's two edge sentences, normalized. Workspace-only: §6 keeps the text
    #: of an unpublished piece out of the committed ledger.
    opening: Optional[str] = None
    ending: Optional[str] = None
    #: V-S05's n-gram profile, in the form :func:`shingles` produces so that
    #: both sides of a comparison are built the same way. Workspace-only, for
    #: the reason the two sentences are.
    shingles: frozenset[str] = frozenset()

    def as_entity(self) -> dict[str, Any]:
        """The workspace form: everything, including the text-bearing fields."""

        return {
            **self.as_measurements(),
            "opening": self.opening,
            "ending": self.ending,
            "shingles": sorted(self.shingles),
        }

    def as_measurements(self) -> dict[str, Any]:
        """The structural form: the counts, and no text (§6)."""

        return {
            "words_before_first_specific": self.words_before_first_specific,
            "specific_kinds": list(self.specific_kinds),
            "words": self.words,
            "paragraph_words": list(self.paragraph_words),
            "sentence_words": list(self.sentence_words),
            "reader_path": list(self.reader_path),
        }


def text_profile(text: Text) -> TextProfile:
    """Measure one text, as V-S02 and V-S04 describe (E-16's ``text_profile``)."""

    body = text.body
    words = _WORD.findall(body)
    first = _SPECIFIC.search(body)
    return TextProfile(
        words_before_first_specific=(
            None if first is None else len(_WORD.findall(body[: first.start()]))
        ),
        specific_kinds=_SPECIFIC_KINDS,
        words=len(words),
        paragraph_words=tuple(
            len(_WORD.findall(segment.text)) for segment in text.segments
        ),
        sentence_words=tuple(
            len(_WORD.findall(sentence))
            for sentence in _SENTENCE_SPLIT.split(body.strip())
            if sentence.strip()
        ),
        reader_path=text_reader_path(text),
        opening=text_opening(text),
        ending=text_ending(text),
        shingles=shingles(body),
    )


def strategy_snapshot(strategy: EditorialStrategy) -> dict[str, Any]:
    """E-16's ``strategy``: "snapshot of E-13 fields, normalized for comparison".

    Normalized through :func:`~src.editorial_core.text_check.normalized_sentence`,
    which is the form both sides of every other portfolio comparison are
    written in — so two strategies that differ only in casing or spacing are
    one strategy here, and the comparison is not re-invented per field.
    """

    return {
        "editorial_job": normalized_sentence(strategy.editorial_job),
        "angle": normalized_sentence(strategy.angle),
        "focal_subject": strategy.focal_subject.kind.value,
        "reveal": strategy.reveal.kind.value,
        "concession": strategy.concession.present,
        "held_back": normalized_sentence(strategy.opening.held_back),
        "ending_intention": normalized_sentence(strategy.ending_intention),
        "reader_path": [
            normalized_sentence(move.purpose) for move in strategy.reader_path
        ],
    }


def adaptation_snapshot(plan: ExecutablePlan) -> dict[str, Any]:
    """E-16's ``adaptation``: the E-14 fields adaptation decided (Step 1 §4).

    The adaptation fields and not the plan: the thesis, the focal subject and
    the reader path reach E-14 only through ``strategy_ref``, and they are
    already in :func:`strategy_snapshot`. What is here is what S-10 chose for
    this surface.
    """

    return {
        "format": plan.format.value,
        "length_target": {
            "minimum": plan.length_target.minimum,
            "maximum": plan.length_target.maximum,
            "unit": plan.length_target.unit.value,
        },
        "first_line_mechanics": normalized_sentence(plan.first_line_mechanics),
        # The segment **names**, and the key says so: ``segments`` is the key
        # E-15 keeps its prose under, and a fingerprint may carry neither that
        # field nor that name (see :data:`_TEXT_BEARING_KEYS`).
        "segment_names": [segment.name for segment in plan.segments],
        "subheadings": plan.subheadings,
        "has_hashtags": plan.hashtags is not None,
        "has_cross_destination_link": plan.cross_destination_link is not None,
    }


def features_snapshot(features: MaterialFeatures) -> dict[str, Any]:
    """E-16's ``features``: "snapshot of E-05 values".

    All twelve, by name, because E-05 holds exactly one entry per feature of
    map §8.3 and a snapshot of the positive ones would make a feature answered
    ``false`` indistinguishable from one nobody answered.
    """

    return {
        item.feature.value: (
            item.value if isinstance(item.value, bool) else item.value.value
        )
        for item in features.values
    }


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """``E-16``: what Portfolio Memory remembers about one text (Step 1 §4).

    There is **no publication field and no body field**. Step 1 makes
    ``publication`` conditional ("if published") and §3.4 keeps the body of an
    unpublished text out of the ledger; a shadow run publishes nothing, so
    neither has a value here — and there is nowhere to put one, which is what
    makes "this fingerprint is not a publication" checkable rather than
    promised. SL-11 is the slice that publishes and adds them together.

    ``label_ref`` is likewise absent: labels are written after the decision by a
    separate job (AD-07), a fingerprint without one is valid, and a field this
    stage could fill would make an asynchronous job a step of the run.
    """

    fingerprint_id: str
    client: str
    destination: Destination
    unit_id: str
    text_ref: tuple[str, int]
    content_digest: str
    #: The destination's decided mode (E-12). It says what the engine intended
    #: for this surface, never what happened to it: a ``publish``-mode
    #: fingerprint of a shadow run is still a text nothing published, and
    #: :func:`prior_publication` is where that distinction is enforced.
    mode: DestinationMode
    features: Mapping[str, Any]
    strategy: Mapping[str, Any]
    adaptation: Mapping[str, Any]
    text_profile: TextProfile
    #: From StrategySelection. ``None`` is the recorded state "one admissible
    #: candidate survived code exclusion, so no tie-breaker decided" — which is
    #: why the key is always written, with ``null``, rather than left out.
    deciding_tiebreaker: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.fingerprint_id.strip() or not self.unit_id.strip():
            raise ShadowPublicationError(
                "a fingerprint is identified by its own ID and the unit whose "
                "text it remembers"
            )
        if not self.client.strip():
            raise ShadowPublicationError(
                f"{self.fingerprint_id} names no client; the ledger partitions "
                "fingerprints by client, and one that names none has no shelf"
            )
        if not self.content_digest.strip():
            raise ShadowPublicationError(
                f"{self.fingerprint_id} carries no content digest; V-T05 and "
                "idempotency compare that digest, and a fingerprint without "
                "one answers neither"
            )

    @property
    def published(self) -> bool:
        """Did the text this remembers reach a platform?

        Always ``False`` here, and read from the shape rather than from a flag:
        this entity has no publication to carry, so there is no state in which
        it could answer otherwise.
        """

        return False

    def as_entity(self) -> dict[str, Any]:
        """The workspace copy, written to ``fingerprints/<fp_id>.json``."""

        return {
            "entity_type": FINGERPRINT_ENTITY_TYPE,
            "entity_id": self.fingerprint_id,
            **self._identity(),
            "text_profile": self.text_profile.as_entity(),
            "publication": None,
        }

    def as_ledger_record(self) -> dict[str, Any]:
        """The durable copy (§3.2), with no text in it (§3.4, §6).

        The same identity and the same snapshots, and a text profile reduced to
        its measurements: the opening, the ending and the n-grams stay in the
        90-day workspace, because this record is committed to a public
        repository and the text it describes was never published.
        """

        return {
            "schema": FINGERPRINT_ENTITY_TYPE,
            **self._identity(),
            "text_profile": self.text_profile.as_measurements(),
            "publication": None,
        }

    def relative_path(self, started_at: datetime) -> str:
        """``fingerprints/<client>/<yyyy-mm>/<fp_id>.json`` (§3.2).

        The month is the run's own start month, so the ledger partitions by
        when the run happened — the rule the RunSummary beside it follows.
        """

        month = f"{started_at.year:04d}-{started_at.month:02d}"
        return (
            f"{FINGERPRINTS_DIRECTORY}/{self.client}/{month}/"
            f"{self.fingerprint_id}.json"
        )

    def _identity(self) -> dict[str, Any]:
        text_id, version = self.text_ref
        return {
            "fingerprint_id": self.fingerprint_id,
            "client": self.client,
            "destination": self.destination.value,
            "unit_id": self.unit_id,
            "text_ref": [text_id, version],
            "content_digest": self.content_digest,
            "mode": self.mode.value,
            "published": self.published,
            "features": dict(self.features),
            "strategy": dict(self.strategy),
            "adaptation": dict(self.adaptation),
            "deciding_tiebreaker": self.deciding_tiebreaker,
            "label_ref": None,
        }


def fingerprint_id(run_id: str, destination: Destination) -> str:
    """One fingerprint per destination per **run**.

    Named for the run and not for the unit, although the unit is what the
    record is about: at cap = 1 a unit ID is derived from the core and a second
    run over the same signal names the same unit
    (:func:`~src.editorial_core.editorial_units.unit_id`), while the ledger is
    shared by every run and writes each record once (P1, §3.1). A unit-derived
    name would therefore make the second remembrance of a signal collide with
    the first — and the portfolio wants both: they are two texts. The unit, the
    text version and the destination are all fields of the record, so naming it
    for the run loses nothing a reader needs.
    """

    return f"fp-{run_id}-{destination.value}"


def write_fingerprint_record(
    fingerprint: Fingerprint,
    *,
    started_at: datetime,
    root: Optional[Path] = None,
) -> Path:
    """Write one fingerprint into the durable ledger and return its path.

    The one writer of a fingerprint into tier 2, and therefore the one place
    §6's rule can be enforced: a record of a text nothing published may carry no
    text, and this refuses to write one that does rather than trusting the
    serializer that produced it. Create-once, like every other ledger record.
    """

    payload = fingerprint.as_ledger_record()
    if not fingerprint.published:
        carried = sorted(_TEXT_BEARING_KEYS & _keys(payload))
        if carried:
            raise ShadowPublicationError(
                f"{fingerprint.fingerprint_id} is a fingerprint of a text "
                "nothing published and its ledger record carries "
                + ", ".join(carried)
                + "; §6 keeps unpublished bodies and source excerpts out of the "
                "committed tier, and this record is committed to a public "
                "repository"
            )
    return write_record(fingerprint.relative_path(started_at), payload, root=root)


def _keys(payload: Mapping[str, Any]) -> set[str]:
    """Every key of a nested payload, so a text cannot hide one level down."""

    found: set[str] = set()
    for key, value in payload.items():
        found.add(key)
        if isinstance(value, Mapping):
            found |= _keys(value)
    return found


# ===========================================================================
# The two narrow views a later run reads these through
# ===========================================================================


def portfolio_text(fingerprint: Fingerprint) -> TextFingerprint:
    """One fingerprint as V-S05 compares against it.

    **Every** fingerprint projects: E-16 remembers generated texts too, flagged,
    and V-S05 is portfolio pressure rather than a republication check. A
    fingerprint read back from the ledger carries no opening, ending or
    shingles, and answers ``None`` for each — which is what every dimension of
    :class:`~src.editorial_core.text_check.TextFingerprint` is optional for.
    """

    profile = fingerprint.text_profile
    return TextFingerprint(
        fingerprint_id=fingerprint.fingerprint_id,
        destination=fingerprint.destination,
        reader_path=profile.reader_path,
        opening=profile.opening,
        ending=profile.ending,
        shingles=profile.shingles,
    )


def prior_publication(fingerprint: Fingerprint) -> Optional[PriorPublication]:
    """One fingerprint as V-T05 counts it, or ``None`` when it is not one.

    V-T05 asks whether this text "has already been published here", and a
    shadow run's fingerprints answer no — none of them published. Returning
    ``None`` rather than a record with a flag is the fail-closed half: a caller
    that forgot to read a flag would hand V-T05 a prior publication that does
    not exist, and a text would be refused as a republication of something
    nobody can open.
    """

    if not fingerprint.published:
        return None
    return PriorPublication(  # pragma: no cover - SL-11 is what publishes
        fingerprint_id=fingerprint.fingerprint_id,
        destination=fingerprint.destination,
        content_digest=fingerprint.content_digest,
        shingles=fingerprint.text_profile.shingles,
    )


# ===========================================================================
# publication.json · what S-14 did about one destination
# ===========================================================================


@dataclass(frozen=True, slots=True)
class DestinationPublication:
    """``publication.json``: "package digests, preflight, result refs" (§2.2).

    ``published`` is ``False`` and ``withheld`` says why. Both, because they are
    two facts: that nothing reached a platform, and that nothing was *meant* to
    — a destination whose publication failed and one whose run never publishes
    are the same ``False`` and must not be the same record.
    """

    unit_id: str
    destination: Destination
    mode: DestinationMode
    text_ref: tuple[str, int]
    verdict_ref: str
    fingerprint_id: str
    package: PackageOutcome
    #: Not evaluated, and recorded as that rather than as a passing verdict:
    #: §3's preflight runs against a package, and there is none to run against.
    #: SL-8/SL-9 prove "preflight ALLOW on SL-7 texts", which is their evidence
    #: and not something this slice may claim on their behalf.
    preflight: Optional[str] = None
    published: bool = False
    withheld: str = WITHHELD_IN_SHADOW_RUN

    def __post_init__(self) -> None:
        if self.published:
            raise ShadowPublicationError(
                f"{self.destination.value} is recorded as published by the "
                "shadow stage; this stage constructs no publisher and makes no "
                "external call, so a record saying otherwise describes a run "
                "that did not happen"
            )
        if not self.withheld.strip():
            raise ShadowPublicationError(
                f"{self.destination.value} published nothing and records no "
                "reason; 'nothing happened' with no reason beside it reads as a "
                "publication that was attempted and lost"
            )

    @property
    def publication_id(self) -> str:
        """One record per destination of one unit (§2.2: one file each)."""

        return f"pub-{self.unit_id}-{self.destination.value}"

    def as_entity(self) -> dict[str, Any]:
        text_id, version = self.text_ref
        return {
            "entity_type": PUBLICATION_ENTITY_TYPE,
            "entity_id": self.publication_id,
            "unit_id": self.unit_id,
            "destination": self.destination.value,
            "mode": self.mode.value,
            "text_ref": [text_id, version],
            "verdict_ref": self.verdict_ref,
            "fingerprint_id": self.fingerprint_id,
            "package": self.package.as_entity(),
            "preflight": self.preflight,
            "published": self.published,
            "withheld": self.withheld,
        }


# ===========================================================================
# The stage
# ===========================================================================


@dataclass(frozen=True, slots=True)
class AcceptedText:
    """One destination's accepted text and everything E-16 snapshots of it.

    Assembled by the harness, which is the only thing that holds all six: §3's
    Inputs column asks S-14 for the accepted E-15 with its TextVerdict, the
    E-12 mode, and E-14, E-13 and E-05 for the fingerprint snapshot.
    """

    decision: DestinationDecision
    text: Text
    verdict: TextVerdict
    plan: ExecutablePlan
    strategy: EditorialStrategy
    features: MaterialFeatures
    #: S-09's selection, for the tie-breaker. ``None`` when the lane never
    #: recorded one, which :class:`Fingerprint` keeps distinct from "no
    #: tie-breaker was needed" by writing the key either way.
    selection: Optional[StrategySelection] = None


class ShadowPublication(NamedTuple):
    """What one shadow execution of S-14 produced, in publication order."""

    records: tuple[DestinationPublication, ...]
    fingerprints: tuple[Fingerprint, ...]


def publish_in_shadow(
    *,
    run_id: str,
    client: str,
    unit_id: str,
    accepted: Sequence[AcceptedText],
    packagers: Mapping[Destination, CanonicalPackager] = CANONICAL_PACKAGERS,
) -> ShadowPublication:
    """Package what can be packaged, fingerprint every accepted text, publish
    nothing.

    The order is :func:`~src.editorial_core.destinations.publication_order`'s —
    §3 keeps "the existing Wix-before-LinkedIn order inside S-14" because the
    social posts may link to the article — and it is kept even though nothing
    is published, so that a shadow trace and a live trace are the same shape.

    Raises :class:`ShadowPublicationError` for a unit of work that may not reach
    this stage at all: a text whose verdict is not accepted (§3: "only accepted
    texts reach S-14"), a verdict that judges a different text version, a text
    at a destination the decision was not made for, or a destination the
    contract excluded. Each is a harness defect and each fails closed, because
    the alternative is a fingerprint remembering a text no check approved.
    """

    by_destination = {item.decision.destination: item for item in accepted}
    if len(by_destination) != len(accepted):
        raise ShadowPublicationError(
            f"{unit_id} offers two accepted texts for one destination; §2.5 "
            "gives a destination one accepted text, and a second would write "
            "the fingerprint of the first twice"
        )
    # Every one of them, before the order is computed: `publication_order`
    # keeps only the eligible decisions, so a loop that checked as it went
    # would silently drop an excluded one instead of refusing it — and the
    # guard against an excluded destination reaching this stage would be a
    # guard that never runs.
    for item in accepted:
        _check(unit_id, item)
    ordered = publication_order([item.decision for item in accepted])
    records: list[DestinationPublication] = []
    fingerprints: list[Fingerprint] = []
    for destination in ordered:
        item = by_destination[destination]
        identity = fingerprint_id(run_id, destination)
        mode = item.decision.mode
        assert mode is not None  # _check: an eligible decision carries one
        selection = item.selection
        tiebreaker = (
            None
            if selection is None or selection.deciding_tiebreaker is None
            else selection.deciding_tiebreaker.value
        )
        fingerprints.append(
            Fingerprint(
                fingerprint_id=identity,
                client=client,
                destination=destination,
                unit_id=unit_id,
                text_ref=(item.text.text_id, item.text.version),
                content_digest=item.text.content_digest,
                mode=mode,
                features=features_snapshot(item.features),
                strategy=strategy_snapshot(item.strategy),
                adaptation=adaptation_snapshot(item.plan),
                text_profile=text_profile(item.text),
                deciding_tiebreaker=tiebreaker,
            )
        )
        records.append(
            DestinationPublication(
                unit_id=unit_id,
                destination=destination,
                mode=mode,
                text_ref=(item.text.text_id, item.text.version),
                verdict_ref=item.verdict.verdict_id,
                fingerprint_id=identity,
                package=_package(destination, item.text, item.plan, packagers),
            )
        )
    return ShadowPublication(tuple(records), tuple(fingerprints))


def _check(unit_id: str, item: AcceptedText) -> None:
    """Everything §3's Pre column requires of one unit of work reaching S-14."""

    destination = item.decision.destination
    if item.decision.eligibility is not Eligibility.ELIGIBLE:
        raise ShadowPublicationError(
            f"{destination.value} reached {STAGE} with an excluded decision; a "
            "destination S-07 refused has no text to remember, and a "
            "fingerprint of one would enter the portfolio as a surface the "
            "contract declined"
        )
    if item.decision.mode is None:
        raise ShadowPublicationError(
            f"{destination.value} reached {STAGE} with an eligible decision "
            "that states no mode; E-16 flags every fingerprint publish or "
            "generate_only, and one whose mode nobody decided would be flagged "
            "by this stage"
        )
    if not item.verdict.accepted:
        raise ShadowPublicationError(
            f"{destination.value} reached {STAGE} with verdict "
            f"{item.verdict.verdict_id} ({item.verdict.result.value}); §3 lets "
            "only an accepted text reach this stage, and remembering one the "
            "checks sent back would put it in the portfolio as a text that held"
        )
    if item.verdict.text_ref != (item.text.text_id, item.text.version):
        raise ShadowPublicationError(
            f"{destination.value} offers text "
            f"{item.text.text_id} v{item.text.version} with a verdict on "
            f"{item.verdict.text_ref}; §2.5 gives one verdict per text version, "
            "and a fingerprint of a version nothing judged is a text that "
            "passed no check"
        )
    if item.text.destination is not destination or item.text.unit_id != unit_id:
        raise ShadowPublicationError(
            f"{destination.value} of {unit_id} offers text "
            f"{item.text.text_id}, which belongs to "
            f"{item.text.destination.value} of {item.text.unit_id}; a "
            "fingerprint names what it remembers"
        )
