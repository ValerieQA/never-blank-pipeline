"""ENGINE: the Audience Profile, the one client context the boundary reads.

Step 1 §295: the client's right to speak, its editorial lens and its portfolio
memory do **not** enter the interpretation boundary. The boundary answers "what
is true", not "what suits us". Only the Audience Profile enters, and only so
that S-04 can say how the material connects to a reader (`E-08.reader_connection`,
which may be empty only together with a `SKIP`). Step 2 lists it among the inputs
of S-04 and S-08, and of no other stage.

It is **configuration**, the way a Client Contract is: a document the client
writes, read from the active client's directory (``NB_CLIENT_DIR``), validated on
load, and handed to the stages entitled to it. No stage produces one, and no run
changes one.

What it may say is not its own to decide. ``knowledge/vocab/audience_attributes.md``
declares the attributes a condition may read and the closed set of values each of
them takes; a profile states every declared attribute, with a value from that
attribute's own set, and may state nothing else. That is what keeps the profile
from becoming a second place client policy lives: a position, a lens or a
portfolio note has no attribute to arrive under, so there is nothing for a stage
to read it out of.

The profile reaches a condition through :meth:`AudienceProfile.for_stage`, whose
result is what ``StageInputs.audience`` evaluates `audience <attribute> is
<value>` against (Step 4 §4).

Sources: `docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md` §295 and E-08;
`docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md` S-04 and S-08 Inputs;
`docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md` §4.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Optional

from src.knowledge.markdown import Document, DocumentError, load_document, parse_table
from src.knowledge.vocabulary import Vocabulary, VocabularyError, load_vocabularies
from src.strategy.client_contracts import client_dir

#: The client's profile document, under the active client's directory. One per
#: client: an audience the stages disagree about is not an audience.
PROFILE_FILE: Final[str] = "audience.md"

#: The vocabulary that governs a profile — the same file the `audience
#: <attribute> is <value>` grammar draws its terms from, so a profile and the
#: conditions written against it cannot drift apart.
ATTRIBUTES_VOCABULARY: Final[str] = "audience_attributes"

#: The stages Step 2 gives the Audience Profile to: S-04, which needs it for the
#: reader connection, and S-08. Nothing else reads it — §295 admits the profile
#: to the boundary and admits no other context with it.
READING_STAGES: Final[tuple[str, ...]] = ("S-04", "S-08")

#: Front matter: which profile this is, and which version of it. What the profile
#: *says* is the table below, where the vocabulary decides what is sayable.
_FIELDS: Final[tuple[str, ...]] = ("profile_id", "version")

_ATTRIBUTES_SECTION: Final[str] = "Attributes"

#: `Why` is for the next keeper: a value nobody wrote a reason for is a value
#: nobody can revisit on purpose.
_COLUMNS: Final[tuple[str, ...]] = ("Attribute", "Value", "Why")


class AudienceProfileError(ValueError):
    """The Audience Profile cannot be read, and no stage may guess at one."""


@dataclass(frozen=True, slots=True)
class AudienceProfile:
    """One client's audience, as the `audience …` terms see it."""

    profile_id: str
    version: str
    #: Every attribute the vocabulary declares, in its order, each with the one
    #: value the client chose from that attribute's declared set.
    attributes: tuple[tuple[str, str], ...]
    path: str
    digest: str

    @property
    def identity(self) -> str:
        return f"{self.profile_id}/{self.version}"

    def value(self, attribute: str) -> str:
        """What the client said about this attribute."""

        for name, value in self.attributes:
            if name == attribute:
                return value
        raise AudienceProfileError(
            f"the Audience Profile says nothing about {attribute!r}; it states "
            f"{', '.join(name for name, _ in self.attributes)}"
        )

    def for_stage(self, stage: str) -> dict[str, str]:
        """What ``StageInputs.audience`` reads at ``stage``.

        A stage Step 2 does not give the profile to is refused rather than given
        an empty mapping: empty would make every `audience …` condition quietly
        false there, which is the same wrong answer with nothing to see.
        """

        if stage not in READING_STAGES:
            raise AudienceProfileError(
                f"{stage} is not given the Audience Profile; Step 2 gives it to "
                f"{' and '.join(READING_STAGES)}, and the boundary admits no "
                "other context (Step 1 §295)"
            )
        return dict(self.attributes)


def parse_audience_profile(
    document: Document, attributes: Vocabulary
) -> AudienceProfile:
    """Read one profile document against its vocabulary.

    Raises :class:`AudienceProfileError`.
    """

    path = document.path
    missing = [name for name in _FIELDS if document.field(name) is None]
    if missing:
        raise AudienceProfileError(
            f"{path}: front matter is missing {', '.join(missing)}"
        )
    unknown = sorted(set(document.field_names) - set(_FIELDS))
    if unknown:
        raise AudienceProfileError(
            f"{path}: front matter has no field {', '.join(unknown)}; an Audience "
            f"Profile declares {' and '.join(_FIELDS)}"
        )

    body = document.section(_ATTRIBUTES_SECTION)
    if body is None:
        raise AudienceProfileError(
            f"{path}: no `## {_ATTRIBUTES_SECTION}` section; that is where the "
            "profile says who the reader is"
        )
    try:
        rows = parse_table(
            body, path=path, section=_ATTRIBUTES_SECTION, columns=_COLUMNS
        )
    except DocumentError as exc:
        raise AudienceProfileError(str(exc)) from exc

    stated: dict[str, str] = {}
    for row in rows:
        name, value, why = row[0], row[1], row[2]
        term = attributes.term(name)
        if term is None:
            raise AudienceProfileError(
                f"{path}: `{name}` is not an audience attribute. {attributes.path} "
                f"declares {', '.join(attributes.names)}, and a profile states "
                "those and nothing else: the boundary reads the audience, never "
                "the client's positions, lens or portfolio (Step 1 §295)"
            )
        if name in stated:
            raise AudienceProfileError(f"{path}: `{name}` is stated twice")
        if value not in term.values:
            raise AudienceProfileError(
                f"{path}: `{name}` cannot be {value!r}; {attributes.path} declares "
                f"{' / '.join(term.values) or 'no values for it'}"
            )
        if not why:
            raise AudienceProfileError(
                f"{path}: `{name}` is {value!r} for no stated reason; the `Why` "
                "column is what lets the next keeper change it on purpose"
            )
        stated[name] = value

    absent = [name for name in attributes.names if name not in stated]
    if absent:
        raise AudienceProfileError(
            f"{path}: states nothing for {', '.join(absent)}; {attributes.path} "
            "declares what a profile answers, and a condition on an attribute the "
            "profile left out could only ever be false"
        )

    return AudienceProfile(
        profile_id=document.field("profile_id") or "",
        version=document.field("version") or "",
        attributes=tuple((name, stated[name]) for name in attributes.names),
        path=path,
        digest=document.digest,
    )


def load_audience_profile(path: Path, attributes: Vocabulary) -> AudienceProfile:
    """Read one profile file. Raises :class:`AudienceProfileError`."""

    try:
        document = load_document(path)
    except DocumentError as exc:
        raise AudienceProfileError(str(exc)) from exc
    return parse_audience_profile(document, attributes)


def audience_profile(
    register_dir: Path, *, directory: Optional[Path] = None
) -> AudienceProfile:
    """The active client's Audience Profile, checked against this register.

    ``register_dir`` is where `vocab/audience_attributes.md` lives. A profile is
    only as good as the vocabulary it was read against, so the caller says which
    register the run is on rather than this module assuming one.
    """

    root = directory if directory is not None else client_dir()
    path = root / PROFILE_FILE
    if not path.is_file():
        raise AudienceProfileError(
            f"{path}: this client has no Audience Profile. S-04 needs one for the "
            "reader connection (Step 2), so a client without one cannot run"
        )
    try:
        attributes = load_vocabularies(register_dir).get(ATTRIBUTES_VOCABULARY)
    except VocabularyError as exc:
        raise AudienceProfileError(str(exc)) from exc
    return load_audience_profile(path, attributes)
