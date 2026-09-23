"""The register's closed vocabularies (Step 4 §1, §4).

`knowledge/vocab/<name>.md` holds every term a record may use: the material
features, the boundary facts code computes, the destinations, the formats, the
strategy fields and audience attributes a condition may read, the stages and
entity fields a record may declare it influences, the reason categories a run may
end a scope with — and the labels, which exist only so that a record using one is
refused (I-10).

Closed means closed. A term that is not in one of these files is not a term, so a
record using it is rejected rather than applied to nothing (§10: "the term and its
code meaning ship together"). Two of these vocabularies also **mirror a list that
already exists in code** — the stages mirror the stage-topology registry, the
destinations mirror the one authorization boundary — and a register whose
vocabulary disagrees with the code is refused outright. A duplicated list is a
list that drifts (#227).

The file format is one bullet per term::

    - `figure_provenance`: own / third_party / none — who produced the figures
    - `counter_evidence` — evidence against one of the interpretations
    - `admissible_interpretation`: <count> — an interpretation the boundary admits

Values after the colon are the closed set that term may be compared against;
`<count>` instead marks a fact that is counted rather than compared, which is
what lets a condition say `boundary has at least 2 admissible_interpretations`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Optional

from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.knowledge.markdown import Document, DocumentError, load_document
from src.publishing.release_scope import (
    NON_R1_PUBLISH_CHANNELS,
    R1_PUBLISH_CHANNELS,
)

#: The directory under the register root that holds them.
VOCAB_DIR_NAME: Final[str] = "vocab"

#: Every vocabulary the register must have. Exactly these: a missing one leaves
#: a term family unsayable, and an extra one is a vocabulary no code reads.
REQUIRED_VOCABULARIES: Final[tuple[str, ...]] = (
    "audience_attributes",
    "boundary_facts",
    "destinations",
    "features",
    "fields",
    "formats",
    "labels",
    "reason_categories",
    "stages",
    "strategy_fields",
)

#: The reason category this package itself can produce (§8: a register that fails
#: validation at run start ends the run as a `SKIP` at signal scope). It is
#: mirrored against `reason_categories.md`, so the vocabulary cannot drift away
#: from the reason code actually writes.
KNOWLEDGE_REGISTER_INVALID: Final[str] = "knowledge_register_invalid"

_TERMS_HEADING: Final[str] = "Terms"

#: Marks a boundary fact that is counted rather than compared to a value.
_COUNT_MARKER: Final[str] = "<count>"

_TERM = re.compile(
    r"^`(?P<name>[^`]+)`"
    r"(?:\s*:\s*(?P<values>[^—]*?))?"
    r"(?:\s*—\s*(?P<gloss>.*))?$",
    re.S,
)

#: A value is a machine token. The prose that explains it goes after the em dash.
_VALUE = re.compile(r"^[a-z][a-z0-9_]*$")


class VocabularyError(ValueError):
    """A vocabulary file cannot be read, so no condition can be checked."""


@dataclass(frozen=True, slots=True)
class Term:
    """One term of one vocabulary."""

    name: str
    #: The closed set of values it may be compared against. Empty when the term
    #: is a fact that is simply present or absent.
    values: tuple[str, ...]
    #: True when the term may be counted (`boundary has at least 2 …`).
    countable: bool
    gloss: str


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """One `knowledge/vocab/<name>.md` file."""

    vocab_id: str
    version: str
    terms: tuple[Term, ...]
    path: str

    def term(self, name: str) -> Optional[Term]:
        for term in self.terms:
            if term.name == name:
                return term
        return None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(term.name for term in self.terms)


@dataclass(frozen=True, slots=True)
class Vocabularies:
    """Every vocabulary of one register, by id."""

    by_id: tuple[tuple[str, Vocabulary], ...]

    def get(self, vocab_id: str) -> Vocabulary:
        for name, vocabulary in self.by_id:
            if name == vocab_id:
                return vocabulary
        raise VocabularyError(
            f"the register has no `{vocab_id}` vocabulary; it has "
            f"{', '.join(name for name, _ in self.by_id) or 'none'}"
        )


def parse_vocabulary(document: Document) -> Vocabulary:
    """Read one vocabulary document. Raises :class:`VocabularyError`."""

    path = document.path
    missing = [name for name in ("vocab_id", "version") if document.field(name) is None]
    if missing:
        raise VocabularyError(
            f"{path}: front matter is missing {', '.join(missing)}"
        )
    unknown = sorted(set(document.field_names) - {"vocab_id", "version"})
    if unknown:
        raise VocabularyError(
            f"{path}: front matter has no field {', '.join(unknown)}; a "
            "vocabulary declares `vocab_id` and `version`"
        )

    body = document.section(_TERMS_HEADING)
    if body is None:
        raise VocabularyError(
            f"{path}: no `## {_TERMS_HEADING}` section; that is where the terms go"
        )

    terms: list[Term] = []
    for entry in _bullets(body, path):
        match = _TERM.match(entry)
        if match is None:
            raise VocabularyError(
                f"{path}: a term is written ``- `name`: value / value — what it "
                f"means``; got {entry[:70]!r}"
            )
        name = " ".join(match.group("name").split())
        if any(term.name == name for term in terms):
            raise VocabularyError(f"{path}: `{name}` is declared twice")
        raw_values = (match.group("values") or "").strip()
        countable = raw_values == _COUNT_MARKER
        values: tuple[str, ...] = ()
        if raw_values and not countable:
            values = tuple(part.strip() for part in raw_values.split("/"))
            bad = [value for value in values if not _VALUE.match(value)]
            if bad:
                raise VocabularyError(
                    f"{path}: `{name}` declares the value(s) "
                    f"{', '.join(repr(value) for value in bad)}, which are not "
                    f"machine tokens. Explain a value after the em dash, or use "
                    f"`{_COUNT_MARKER}` for a counted fact"
                )
            if len(set(values)) != len(values):
                raise VocabularyError(f"{path}: `{name}` repeats a value")
        terms.append(
            Term(
                name=name,
                values=values,
                countable=countable,
                gloss=" ".join((match.group("gloss") or "").split()),
            )
        )

    if not terms:
        raise VocabularyError(f"{path}: `## {_TERMS_HEADING}` declares no terms")

    vocab_id = document.field("vocab_id") or ""
    stem = Path(path).stem
    if vocab_id != stem:
        raise VocabularyError(
            f"{path}: vocab_id is {vocab_id!r} but the file is {stem}.md; the "
            "two are one name"
        )
    return Vocabulary(
        vocab_id=vocab_id,
        version=document.field("version") or "",
        terms=tuple(terms),
        path=path,
    )


def load_vocabularies(register_dir: Path) -> Vocabularies:
    """Read every vocabulary of one register. Raises :class:`VocabularyError`.

    Fails on a missing, extra, unreadable or disagreeing vocabulary, because
    every one of those leaves conditions unverifiable — and an unverifiable
    condition is exactly what §8 refuses to let into a run.
    """

    vocab_dir = register_dir / VOCAB_DIR_NAME
    if not vocab_dir.is_dir():
        raise VocabularyError(f"{vocab_dir}: the register has no vocabularies")

    found: dict[str, Vocabulary] = {}
    for path in sorted(vocab_dir.glob("*.md")):
        try:
            document = load_document(path)
        except DocumentError as exc:
            raise VocabularyError(str(exc)) from exc
        vocabulary = parse_vocabulary(document)
        found[vocabulary.vocab_id] = vocabulary

    missing = sorted(set(REQUIRED_VOCABULARIES) - set(found))
    if missing:
        raise VocabularyError(
            f"{vocab_dir}: missing vocabulary file(s) "
            f"{', '.join(name + '.md' for name in missing)}"
        )
    extra = sorted(set(found) - set(REQUIRED_VOCABULARIES))
    if extra:
        raise VocabularyError(
            f"{vocab_dir}: {', '.join(name + '.md' for name in extra)} is a "
            "vocabulary no code reads; a new vocabulary and the code that reads "
            "it ship together"
        )

    vocabularies = Vocabularies(
        by_id=tuple((name, found[name]) for name in REQUIRED_VOCABULARIES)
    )
    disagreements = mirror_disagreements(vocabularies)
    if disagreements:
        raise VocabularyError("; ".join(disagreements))
    return vocabularies


def mirror_disagreements(vocabularies: Vocabularies) -> tuple[str, ...]:
    """Where a mirrored vocabulary and the code it mirrors have drifted apart."""

    problems: list[str] = []
    problems.extend(
        _mirror(
            vocabularies.get("stages"),
            expected=set(CANONICAL_TOPOLOGY.stage_ids),
            authority="the stage-topology registry (src/editorial_core/topology.py)",
        )
    )
    problems.extend(
        _mirror(
            vocabularies.get("destinations"),
            expected={*R1_PUBLISH_CHANNELS, *NON_R1_PUBLISH_CHANNELS},
            authority="the publish channels (src/publishing/release_scope.py)",
        )
    )
    reasons = vocabularies.get("reason_categories")
    if reasons.term(KNOWLEDGE_REGISTER_INVALID) is None:
        problems.append(
            f"{reasons.path}: does not declare `{KNOWLEDGE_REGISTER_INVALID}`, "
            "which is the reason a run-start validation failure is recorded with"
        )
    return tuple(problems)


def _mirror(
    vocabulary: Vocabulary, *, expected: set[str], authority: str
) -> tuple[str, ...]:
    declared = set(vocabulary.names)
    problems: list[str] = []
    missing = sorted(expected - declared)
    extra = sorted(declared - expected)
    if missing:
        problems.append(
            f"{vocabulary.path}: does not declare {', '.join(missing)}, which "
            f"{authority} does"
        )
    if extra:
        problems.append(
            f"{vocabulary.path}: declares {', '.join(extra)}, which "
            f"{authority} does not"
        )
    return tuple(problems)


def _bullets(body: str, path: str) -> tuple[str, ...]:
    """The `- ` bullets of a section, each joined with its continuation lines."""

    entries: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            entries.append(stripped[2:].strip())
        elif entries and line[:1].isspace():
            entries[-1] = f"{entries[-1]} {stripped}"
        else:
            raise VocabularyError(
                f"{path}: every line of a vocabulary is a `- ` bullet or its "
                f"indented continuation; got {stripped[:60]!r}"
            )
    return tuple(entries)
