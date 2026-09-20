"""ENGINE: the shared mechanical gate — machine tells, never taste (#269).

Two different things were being asked of one editorial reviewer. "Does this
read like a machine wrote it?" and "is this the article the client wanted?"
are not the same question, and only the first can be answered mechanically.
This module answers the first, for every client, from a versioned document
(``config/machine_tells/shared.yaml``) rather than from a prompt: banned LLM
constructions and transitions, banned lede moves, repeated fragment and triad
patterns as the approved list defines them, and figures that trace to nothing
in the run's evidence package.

**Tiers are not flattened.** Each entry declares the evidence tier behind it,
and the tier decides what a match does — hard evidence is a ``gate``,
directional is a ``warning``, observed practice is a ``suggestion``, and an
editorial judgement goes to ``owner_review``. Turning a rule we merely suspect
into a rule that stops a run is the failure this ordering exists to prevent;
so is the opposite, quietly downgrading a proven tell to advice.

**Shared, and extended by the client.** The list above is the Engine's and
holds for every client. A client extends it with its own ``lists/*.md``
documents (``src/strategy/client_contracts.py``), which reach the scan as
``client_entries``. A client list says "this client never publishes these
words" — an explicit prohibition rather than an evidence-tiered heuristic —
so a client entry gates. The Engine matches; what is in either list is
policy written by people.

Nothing here knows a client, a brand, an audience or an argument, and nothing
here is an editorial opinion: a machine tell is a machine tell whoever is
writing, and a figure that traces to nothing is unsupported whoever states it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_MACHINE_TELLS_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2] / "config" / "machine_tells" / "shared.yaml"
)

#: What a match does. The four outcomes are the owner's tier ladder (#269) and
#: only the first one stops anything.
GATE: Final[str] = "gate"
WARNING: Final[str] = "warning"
SUGGESTION: Final[str] = "suggestion"
OWNER_REVIEW: Final[str] = "owner_review"

#: Evidence tier → what a match of an entry carrying it does. Declared here
#: once so no caller can decide for itself that its own tier is a hard rule.
TIER_OUTCOMES: Final[dict[str, str]] = {
    "hard_evidence": GATE,
    "directional": WARNING,
    "observed_practice": SUGGESTION,
    "owner_judgement": OWNER_REVIEW,
}

#: What a document entry may declare.
ENTRY_KINDS: Final[frozenset[str]] = frozenset({
    "llm_construction", "transition", "lede_move", "repeated_pattern",
})

#: Produced by the scan rather than declared: a figure the run's evidence does
#: not contain. Hard by construction — it is not a matter of taste whether a
#: number the evidence never states is traceable.
UNTRACEABLE_FIGURE: Final[str] = "untraceable_figure"

#: An entry from the client's own banned list. The client wrote a prohibition,
#: not a heuristic, so it gates — see the module docstring.
CLIENT_BANNED: Final[str] = "client_banned"

#: Where an entry is looked for. ``lede`` is the first paragraph, which is the
#: only place a lede move can be one.
SCOPES: Final[frozenset[str]] = frozenset({"article", "lede"})


class MachineTellError(ValueError):
    """The shared list cannot be read; nothing may be scanned against it."""


class MachineTellEntry(BaseModel):
    """One approved entry: what to look for, where, and on what evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=80)
    kind: str
    tier: str
    #: A literal, matched whatever its spacing, case or line breaks.
    text: str = ""
    #: A regular expression, matched case-insensitively. It is never compiled
    #: MULTILINE, so a start-of-string anchor anchors the SCOPE, not a line.
    pattern: str = ""
    scope: str = "article"
    #: A finding only above this count, so "repeated" can mean repeated.
    max_occurrences: int = Field(default=0, ge=0)
    #: A note for people; never delivered anywhere.
    note: str = ""

    @model_validator(mode="after")
    def _one_matcher(self) -> Self:
        if self.kind not in ENTRY_KINDS:
            raise ValueError(
                f"entry {self.id!r}: kind {self.kind!r} is not one the Engine "
                f"matches ({', '.join(sorted(ENTRY_KINDS))})"
            )
        if self.tier not in TIER_OUTCOMES:
            raise ValueError(
                f"entry {self.id!r}: tier {self.tier!r} is not an evidence tier "
                f"({', '.join(TIER_OUTCOMES)})"
            )
        if self.scope not in SCOPES:
            raise ValueError(
                f"entry {self.id!r}: scope {self.scope!r} is not one of "
                f"{', '.join(sorted(SCOPES))}"
            )
        if bool(self.text.strip()) == bool(self.pattern.strip()):
            raise ValueError(
                f"entry {self.id!r} must declare exactly one of `text` or `pattern`"
            )
        try:
            _ = self.matcher
        except re.error as exc:
            raise ValueError(f"entry {self.id!r}: {exc}") from exc
        return self

    @property
    def outcome(self) -> str:
        return TIER_OUTCOMES[self.tier]

    @property
    def matcher(self) -> re.Pattern[str]:
        return (
            re.compile(self.pattern, re.IGNORECASE)
            if self.pattern.strip()
            else _literal(self.text)
        )


class MachineTellList(BaseModel):
    """The shared list as one versioned artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    list_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    entries: tuple[MachineTellEntry, ...] = Field(min_length=1)

    @property
    def identity(self) -> str:
        return f"{self.list_id}/{self.version}"

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [entry.id for entry in self.entries]
        if len(set(ids)) != len(ids):
            raise ValueError("machine-tell entry ids must be unique")
        return self

    @classmethod
    def load(cls, path: Path | str = DEFAULT_MACHINE_TELLS_PATH) -> MachineTellList:
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise MachineTellError(f"{path}: cannot be read ({exc})") from exc
        except yaml.YAMLError as exc:
            raise MachineTellError(f"{path}: is not valid YAML ({exc})") from exc
        if not isinstance(data, dict):
            raise MachineTellError(f"machine-tell artifact {path} is not a mapping")
        try:
            return cls.model_validate(data)
        except ValueError as exc:
            raise MachineTellError(f"{path}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class MachineTell:
    """One match, and what its tier says to do about it."""

    entry_id: str
    kind: str
    tier: str
    outcome: str
    quote: str
    occurrences: int
    #: The list identity the entry came from — the shared one or a client's.
    source: str
    detail: str = ""

    def as_evidence(self) -> dict:
        return {
            "entry_id": self.entry_id, "kind": self.kind, "tier": self.tier,
            "outcome": self.outcome, "quote": self.quote,
            "occurrences": self.occurrences, "source": self.source,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MachineTellScan:
    """Everything one article matched, kept in its tiers."""

    findings: tuple[MachineTell, ...] = ()
    #: Every list the scan ran, so a record says what it was scanned against.
    sources: tuple[str, ...] = ()
    #: Quantities this article states that the evidence does not provably
    #: state in any equivalent spelling (#269). Questions for the semantic
    #: factual reviewer, never findings: mechanics cannot tell a faithful
    #: rephrase from a changed meaning, and must not pretend to.
    figures_to_verify: tuple[str, ...] = ()

    def of(self, outcome: str) -> tuple[MachineTell, ...]:
        return tuple(found for found in self.findings if found.outcome == outcome)

    @property
    def gated(self) -> tuple[MachineTell, ...]:
        return self.of(GATE)

    @property
    def warnings(self) -> tuple[MachineTell, ...]:
        return self.of(WARNING)

    @property
    def suggestions(self) -> tuple[MachineTell, ...]:
        return self.of(SUGGESTION)

    @property
    def owner_review(self) -> tuple[MachineTell, ...]:
        return self.of(OWNER_REVIEW)

    @property
    def blocks(self) -> bool:
        """Whether anything here may stop an article. Only hard evidence does."""
        return bool(self.gated)

    def as_evidence(self) -> dict:
        return {
            "lists": list(self.sources),
            "findings": [found.as_evidence() for found in self.findings],
            "gated": [found.entry_id for found in self.gated],
            "warnings": [found.entry_id for found in self.warnings],
            "suggestions": [found.entry_id for found in self.suggestions],
            "owner_review": [found.entry_id for found in self.owner_review],
        }


def scan(
    text: str,
    *,
    tells: MachineTellList | None = None,
    client_entries: Sequence[tuple[str, str]] = (),
    traceable: str = "",
) -> MachineTellScan:
    """Every machine tell in ``text``, each carrying its own tier's outcome.

    ``client_entries`` are ``(entry, list identity)`` pairs exactly as an
    ``EditorialPlan`` carries them; ``traceable`` is the evidence a figure may
    trace to — the run's usable evidence package as text. An empty
    ``traceable`` means the run has no evidence package to trace against, and
    then no figure is judged: the gate reports what it can prove and nothing
    else.
    """
    findings: list[MachineTell] = []
    sources: list[str] = []
    if tells is not None:
        sources.append(tells.identity)
        for entry in tells.entries:
            scoped = _lede(text) if entry.scope == "lede" else (text or "")
            quotes = _matches(entry.matcher, scoped)
            if len(quotes) <= entry.max_occurrences:
                continue
            findings.append(MachineTell(
                entry_id=entry.id, kind=entry.kind, tier=entry.tier,
                outcome=entry.outcome, quote=quotes[0], occurrences=len(quotes),
                source=tells.identity,
                detail=(
                    f"{len(quotes)} occurrence(s) where the list permits "
                    f"{entry.max_occurrences}"
                    if entry.max_occurrences
                    else f"the shared list does not permit this in the {entry.scope}"
                ),
            ))
    for entry_text, list_identity in client_entries:
        if list_identity not in sources:
            sources.append(list_identity)
        if not entry_text.strip():
            continue
        quotes = _matches(_literal(entry_text), text or "")
        if not quotes:
            continue
        findings.append(MachineTell(
            entry_id=entry_text, kind=CLIENT_BANNED, tier="hard_evidence",
            outcome=GATE, quote=quotes[0], occurrences=len(quotes),
            source=list_identity,
            detail="the client's own list says this is never published",
        ))
    return MachineTellScan(
        tuple(findings), tuple(sources), figures_to_verify(text, traceable)
    )


# ── matching ────────────────────────────────────────────────────────────────


def _literal(text: str) -> re.Pattern[str]:
    """A literal entry, matched however it is spaced, cased or line-broken."""
    body = r"\s+".join(re.escape(word) for word in text.split())
    prefix = r"(?<!\w)" if text[:1].isalnum() else ""
    suffix = r"(?!\w)" if text[-1:].isalnum() else ""
    return re.compile(prefix + body + suffix, re.IGNORECASE)


def _matches(matcher: re.Pattern[str], text: str) -> list[str]:
    """Every match, as the reader meets it, in document order.

    Occurrences are counted, not deduplicated: an entry that permits a
    construction once and refuses it twice can only mean the second *use*,
    whether or not it is worded the same way.
    """
    return [" ".join(match.group(0).split()) for match in matcher.finditer(text)]


def _lede(text: str) -> str:
    """The opening paragraph — the only place a lede move can be one."""
    for block in re.split(r"\n\s*\n", text or ""):
        if block.strip():
            return block
    return ""


# ── figures: a quantity is faithful, ambiguous, or neither ──────────────────
#
# Owner decision (#269): a faithful rephrase is allowed, new or strengthened
# meaning is not. String equality answers neither question. What deterministic
# code can honestly do is extract the quantities and recognise the
# normalizations that provably preserve one — 1,200,000 and 1.2 million are the
# same quantity, and no judgement is involved in saying so. Everything past
# that is meaning, which belongs to the semantic factual reviewer: a token the
# evidence does not spell the same way is a question to ask, never a verdict.

#: A figure as a reader meets it, with the scale word that belongs to it.
#: Digits hanging off a word are an identifier rather than a quantity — the
#: 114 in recall notice `R-114` is a name, and an article that repeats the
#: name states no number. Digits *followed* by letters are a measurement
#: (`8mm`, `14-week`) and stay.
_FIGURE: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9.,\-])(\d+(?:[.,]\d+)*)\s*"
    r"(thousand|million|billion|trillion)?",
    re.IGNORECASE,
)

#: An address is not a quantity. A Sources line citing `.../2026/07/report`
#: states no number, and a gate that said it did would be unusable.
_ADDRESS: Final[re.Pattern[str]] = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)

#: `1.` or `2)` opening a line is a list marker, not a quantity the article states.
_LIST_MARKER: Final[re.Pattern[str]] = re.compile(r"^[ \t]*\d+[.)](?=\s)", re.MULTILINE)

_SCALES: Final[dict[str, int]] = {
    "thousand": 1000, "million": 1_000_000,
    "billion": 1_000_000_000, "trillion": 1_000_000_000_000,
}


def _value(digits: str, scale: str | None) -> Decimal | None:
    """One figure as a number, or ``None`` when it is not one.

    ``1,200`` and ``1200`` are one value; so are ``1.2 million`` and
    ``1,200,000``. A separator that is neither a thousands group nor a decimal
    point — a date, a version, an address fragment — has no single value and
    gets none.
    """
    text = digits.strip()
    try:
        if "," in text and "." in text:
            normalized = text.replace(",", "")
        elif "," in text:
            parts = text.split(",")
            # 1,200,000 is a thousands group; 1,2 is not a number we can read
            if all(len(part) == 3 for part in parts[1:]) and parts[0]:
                normalized = "".join(parts)
            else:
                return None
        else:
            normalized = text
        if normalized.count(".") > 1:
            return None
        value = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None
    if scale:
        value *= _SCALES[scale.casefold()]
    return value


def figures(text: str) -> set[str]:
    """Every quantity the text states, as canonical values.

    List markers and addresses are not quantities. Whatever survives is
    returned in one spelling, so equivalent representations meet as one value.
    """
    cleaned = _LIST_MARKER.sub(" ", _ADDRESS.sub(" ", text or ""))
    found: set[str] = set()
    for match in _FIGURE.finditer(cleaned):
        value = _value(match.group(1), match.group(2))
        if value is None:
            continue
        found.add(format(value.normalize(), "f"))
    return found


def figures_to_verify(text: str, traceable: str) -> tuple[str, ...]:
    """Quantities in ``text`` the evidence does not provably state (#269).

    Not a verdict. A value the evidence states in any equivalent spelling
    clears here and is never asked about again; what remains is what
    deterministic code cannot vouch for, and that goes to the semantic factual
    reviewer, which can weigh meaning and provenance as string comparison
    never could. A quantity the evidence does not support, or one carrying a
    changed meaning, fails there — on a reading, not on a token.
    """
    if not traceable.strip():
        return ()
    return tuple(sorted(
        figures(text) - figures(traceable), key=lambda v: (len(v), v)
    ))
