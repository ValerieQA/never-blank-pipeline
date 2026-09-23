"""The record formats: knowledge records, probe families and check records.

Step 4 §2 (knowledge records), §3 (check records) and §6 (probe families). This
module holds the **shape**: which fields and sections exist, what an id looks
like, how an `## Influences` entry and a `## Route` row are read. Whether the
values in them are *allowed* is `validator.py`, which is where §8's numbered rules
live.

That split is deliberate. A record with `status: descriptive` and `tier: 1` parses
perfectly and is refused by rule 2; if parsing refused it first, the keeper would
get "cannot read this file" where the answer is "a descriptive record is tier 3 to
6". So parsing fails only on what makes a file unreadable *as* a record — no front
matter, no id, a section the format does not have — and everything a numbered rule
judges is carried through as the keeper wrote it.

One format decision this module makes that §3 does not state: a check record
declares its `evidence_class`, exactly as a knowledge record does. §8 rule 3 has
to be able to tell a hard check that came from research (I-13: research findings
do not become hard checks without owner approval) from one that came from
platform policy, and without the class on the record there is nothing to tell them
apart with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Optional

from src.knowledge.markdown import Document, parse_table

#: §2.3. `weak-candidate` is absent on purpose: it is an *effective* status the
#: loader computes at load time from `review_by`, and is never written in a file.
FILE_STATUSES: Final[tuple[str, ...]] = (
    "invariant", "approved-rule", "descriptive", "candidate", "retired",
)

#: The effective status the loader sets past `review_by` (§5, §5.1).
WEAK_CANDIDATE: Final[str] = "weak-candidate"

TIERS: Final[tuple[str, ...]] = (
    "0a", "0b", "0c", "1", "2", "3", "4", "5", "6", "A",
)

#: §2.3: exactly one status, and the tier must be allowed for it. `retired` keeps
#: whatever tier it had, because it is kept for traceability and never loaded.
STATUS_TIERS: Final[dict[str, tuple[str, ...]]] = {
    "invariant": ("0a", "0b", "0c", "A"),
    "approved-rule": ("1", "2"),
    "descriptive": ("3", "4", "5", "6"),
    "candidate": ("3", "4", "5", "6"),
    "retired": TIERS,
}

EVIDENCE_CLASSES: Final[tuple[str, ...]] = (
    "REPO", "RES", "PLAT", "VEND", "OBS", "CLIENT", "OWNER",
    "NBX-engine", "NBX-map", "INF",
)

#: The classes whose knowledge goes stale on the platform's own schedule, so a
#: record carrying one must say when it was last verified (§2.2).
DATED_EVIDENCE_CLASSES: Final[tuple[str, ...]] = ("PLAT", "VEND")

#: The class a research finding carries. With `class: H` it is the combination
#: I-13 requires an owner to approve.
RESEARCH_EVIDENCE_CLASS: Final[str] = "RES"

CONFIDENCES: Final[tuple[str, ...]] = ("high", "medium", "low")

CHECK_CLASSES: Final[tuple[str, ...]] = ("H", "S")
CHECK_RULE_STATUSES: Final[tuple[str, ...]] = (
    "invariant", "approved-rule", "candidate",
)
CHECK_METHODS: Final[tuple[str, ...]] = (
    "code", "model-explicit-criterion", "code+model",
)

#: A soft check has no threshold unless an owner approved one (I-12).
NO_THRESHOLD: Final[str] = "none"

#: The two checks whose fault owner is decided per finding, and which therefore
#: carry a `## Branch criterion` (§3, Step 2 S-13).
BRANCHING_CHECKS: Final[tuple[str, ...]] = ("V-T01", "V-T08")

_RECORD_FIELDS: Final[tuple[str, ...]] = (
    "id", "version", "status", "tier", "evidence_class", "confidence",
    "verified_on", "review_by", "supersedes", "approved_by",
)
#: Every record has these. `verified_on`, `supersedes` and `approved_by` are
#: required by what the record *is*, and §8 rules 1, 3 and 8 say when.
RECORD_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "id", "version", "status", "tier", "evidence_class", "confidence", "review_by",
)

_CHECK_FIELDS: Final[tuple[str, ...]] = (
    "id", "version", "class", "rule_status", "method", "threshold",
    "evidence_class", "review_by", "approved_by",
)
CHECK_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "id", "version", "class", "rule_status", "method", "threshold",
    "evidence_class", "review_by",
)

_RECORD_SECTIONS: Final[tuple[str, ...]] = (
    "Statement", "Applies when", "Influences", "Conflicts", "Source", "Change log",
)
#: A probe family's two extra sections (§6).
_PROBE_SECTIONS: Final[tuple[str, ...]] = ("Probe", "Real examples")
#: The ladder's own extra section (§7).
_LADDER_SECTION: Final[str] = "Levels"
_OPTIONAL_RECORD_SECTIONS: Final[tuple[str, ...]] = ("Notes",)

_CHECK_SECTIONS: Final[tuple[str, ...]] = (
    "Rule", "Criterion", "Enforces", "Route", "Change log",
)
_BRANCH_SECTION: Final[str] = "Branch criterion"

#: `K-<FAMILY>-<n>`, where the family may itself be qualified: `K-DST-LI-03`.
#: Stable across versions, and never reused (§2.2).
RECORD_ID = re.compile(r"^K-(?P<family>[A-Z][A-Z0-9]*)(?:-[A-Z][A-Z0-9]*)*-\d+$")
CHECK_ID = re.compile(r"^V-[PTS]\d{2}$")

#: The family of a probe family record, and its directory (§6, U-1).
PROBE_FAMILY: Final[str] = "tempt"

#: Where the strength ladders live (§7).
LADDER_DIR_NAME: Final[str] = "ladders"

_ROUTE_COLUMNS: Final[tuple[str, ...]] = (
    "Finding", "Route", "Cause", "Counter", "On exhaustion",
)
#: A row that routes nowhere: the finding itself ends the scope, or is a hint.
ROUTE_TERMINAL: Final[str] = "terminal"
ROUTE_HINT: Final[str] = "hint"
#: An em dash, which is how a person writes "this row has none of that".
ROUTE_NONE: Final[str] = "—"

_ROUTE_EDGE = re.compile(r"^(?P<source>S-\d{2})\s*(?:→|->)\s*(?P<target>S-\d{2})$")

_STAGE_OR_CHECK = re.compile(r"^(?:S-\d{2}|V-[PTS]\d{2})$")
_BACKTICKED = re.compile(r"`([^`]+)`")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CHANGE_LOG_LINE = re.compile(r"^-\s*v(?P<version>\d+),")


class RecordError(ValueError):
    """The file cannot be read as a record of the declared format at all."""


@dataclass(frozen=True, slots=True)
class Influence:
    """One `## Influences` entry: the stage it shapes, and which fields."""

    stage: str
    fields: tuple[str, ...]
    text: str


@dataclass(frozen=True, slots=True)
class RouteRow:
    """One row of a check's `## Route` table (§3)."""

    finding: str
    route: str
    cause: str
    counter: str
    on_exhaustion: str

    @property
    def edge(self) -> Optional[tuple[str, str]]:
        """`(source, target)` when the row routes to a stage, else ``None``."""

        match = _ROUTE_EDGE.match(self.route)
        if match is None:
            return None
        return match.group("source"), match.group("target")

    @property
    def is_terminal(self) -> bool:
        return self.route == ROUTE_TERMINAL

    @property
    def is_hint(self) -> bool:
        return self.route == ROUTE_HINT


@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    """One `knowledge/records/…` or `knowledge/ladders/…` file, as written."""

    document: Document
    record_id: str
    family: str
    version: Optional[str]
    status: Optional[str]
    tier: Optional[str]
    evidence_classes: tuple[str, ...]
    confidence: Optional[str]
    verified_on: Optional[str]
    review_by: Optional[str]
    supersedes: Optional[str]
    approved_by: Optional[str]
    applies_when: str
    influences: tuple[Influence, ...]
    is_probe_family: bool
    is_ladder: bool

    @property
    def path(self) -> str:
        return self.document.path

    @property
    def version_number(self) -> Optional[int]:
        return _positive_integer(self.version)

    @property
    def change_log_versions(self) -> tuple[int, ...]:
        return _change_log_versions(self.document.section("Change log") or "")


@dataclass(frozen=True, slots=True)
class CheckRecord:
    """One `knowledge/checks/<V-ID>.md` file, as written (§3)."""

    document: Document
    check_id: str
    version: Optional[str]
    check_class: Optional[str]
    rule_status: Optional[str]
    method: Optional[str]
    threshold: Optional[str]
    evidence_classes: tuple[str, ...]
    review_by: Optional[str]
    approved_by: Optional[str]
    routes: tuple[RouteRow, ...]
    branch_criterion: Optional[str]

    @property
    def path(self) -> str:
        return self.document.path

    @property
    def version_number(self) -> Optional[int]:
        return _positive_integer(self.version)

    @property
    def change_log_versions(self) -> tuple[int, ...]:
        return _change_log_versions(self.document.section("Change log") or "")

    @property
    def is_hard(self) -> bool:
        return self.check_class == "H"


def parse_knowledge_record(document: Document) -> KnowledgeRecord:
    """Read one knowledge record, probe family or ladder. Raises `RecordError`."""

    identity = _identity(document, RECORD_ID, "K-<FAMILY>-<n>")
    family = (identity.group("family") or "").lower()

    directory = Path(document.path).parent.name
    is_probe_family = directory == PROBE_FAMILY
    is_ladder = directory == LADDER_DIR_NAME
    expected = list(_RECORD_SECTIONS)
    if is_probe_family:
        expected.extend(_PROBE_SECTIONS)
    if is_ladder:
        expected.append(_LADDER_SECTION)

    _check_fields(document, _RECORD_FIELDS, "a knowledge record")
    _check_sections(document, tuple(expected), _OPTIONAL_RECORD_SECTIONS)

    return KnowledgeRecord(
        document=document,
        record_id=identity.group(0),
        family=family,
        version=document.field("version"),
        status=document.field("status"),
        tier=document.field("tier"),
        evidence_classes=_comma_separated(document.field("evidence_class")),
        confidence=document.field("confidence"),
        verified_on=document.field("verified_on"),
        review_by=document.field("review_by"),
        supersedes=document.field("supersedes"),
        approved_by=document.field("approved_by"),
        applies_when=" ".join((document.section("Applies when") or "").split()),
        influences=_influences(document),
        is_probe_family=is_probe_family,
        is_ladder=is_ladder,
    )


def parse_check_record(document: Document) -> CheckRecord:
    """Read one check record. Raises :class:`RecordError`."""

    check_id = _identity(document, CHECK_ID, "V-P01 … V-S10").group(0)
    _check_fields(document, _CHECK_FIELDS, "a check record")

    expected = list(_CHECK_SECTIONS)
    if check_id in BRANCHING_CHECKS:
        expected.append(_BRANCH_SECTION)
    _check_sections(document, tuple(expected), ())

    body = document.section("Route") or ""
    rows = parse_table(
        body, path=document.path, section="Route", columns=_ROUTE_COLUMNS
    )
    routes = tuple(
        RouteRow(
            finding=row[0],
            route=row[1],
            cause=row[2],
            counter=row[3],
            on_exhaustion=row[4],
        )
        for row in rows
    )
    for row in routes:
        if row.route in (ROUTE_TERMINAL, ROUTE_HINT):
            continue
        if row.edge is None:
            raise RecordError(
                f"{document.path}: the `## Route` row {row.finding[:40]!r} routes "
                f"to {row.route!r}; a route is `S-13 → S-12`, `{ROUTE_TERMINAL}` "
                f"or `{ROUTE_HINT}`"
            )

    return CheckRecord(
        document=document,
        check_id=check_id,
        version=document.field("version"),
        check_class=document.field("class"),
        rule_status=document.field("rule_status"),
        method=document.field("method"),
        threshold=document.field("threshold"),
        evidence_classes=_comma_separated(document.field("evidence_class")),
        review_by=document.field("review_by"),
        approved_by=document.field("approved_by"),
        routes=routes,
        branch_criterion=document.section(_BRANCH_SECTION),
    )


def is_date(value: Optional[str]) -> bool:
    """Is this a date a person wrote correctly? `2026-13-01` is not."""

    if value is None or not _DATE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def expected_supersedes(record_id: str, version: int) -> str:
    """What `supersedes` must say at this version (§2.2)."""

    return f"{record_id} v{version - 1}"


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _identity(
    document: Document, pattern: re.Pattern[str], shape: str
) -> re.Match[str]:
    value = document.field("id")
    if not value:
        raise RecordError(
            f"{document.path}: no `id` in the front matter; the id is what every "
            "reference to this record resolves through"
        )
    match = pattern.match(value)
    if match is None:
        raise RecordError(f"{document.path}: id {value!r} is not of the form {shape}")
    return match


def _check_fields(document: Document, allowed: tuple[str, ...], kind: str) -> None:
    unknown = [name for name in document.field_names if name not in allowed]
    if unknown:
        raise RecordError(
            f"{document.path}: {kind} has no field {', '.join(unknown)}. Its "
            f"fields are {', '.join(allowed)}"
        )


def _check_sections(
    document: Document, required: tuple[str, ...], optional: tuple[str, ...]
) -> None:
    present = set(document.section_names)
    missing = [name for name in required if name not in present]
    if missing:
        raise RecordError(
            f"{document.path}: missing section(s) "
            f"{', '.join('## ' + name for name in missing)}"
        )
    unknown = [
        name
        for name in document.section_names
        if name not in required and name not in optional
    ]
    if unknown:
        where_else = (
            " Anything a person needs to add goes under `## Notes`." if optional else ""
        )
        raise RecordError(
            f"{document.path}: {', '.join('## ' + name for name in unknown)} is "
            f"not a section of this format.{where_else}"
        )
    if not document.title:
        raise RecordError(f"{document.path}: no `# ` title")


def _influences(document: Document) -> tuple[Influence, ...]:
    """Each `## Influences` entry, which begins with the stage it shapes."""

    raw: list[str] = []
    for line in (document.section("Influences") or "").splitlines():
        text = line.strip()
        if not text:
            continue
        if raw and line[:1].isspace() and not text.startswith("- "):
            raw[-1] = f"{raw[-1]} {text}"
            continue
        raw.append(text[2:].strip() if text.startswith("- ") else text)

    entries: list[Influence] = []
    for text in raw:
        head = text.split(maxsplit=1)[0].strip(".,;:")
        if not _STAGE_OR_CHECK.match(head):
            raise RecordError(
                f"{document.path}: an `## Influences` entry begins with the stage "
                "it shapes, for example ``S-10 · `E-14.format` — where the link "
                f"goes``; got {text[:60]!r}"
            )
        entries.append(
            Influence(stage=head, fields=tuple(_BACKTICKED.findall(text)), text=text)
        )
    if not entries:
        raise RecordError(
            f"{document.path}: `## Influences` names nothing; a record that "
            "shapes no stage cannot reach one"
        )
    return tuple(entries)


def _comma_separated(value: Optional[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _positive_integer(value: Optional[str]) -> Optional[int]:
    if value is None or not value.isdigit():
        return None
    number = int(value)
    return number if number >= 1 else None


def _change_log_versions(body: str) -> tuple[int, ...]:
    versions: list[int] = []
    for line in body.splitlines():
        match = _CHANGE_LOG_LINE.match(line.strip())
        if match is not None:
            versions.append(int(match.group("version")))
    return tuple(versions)
