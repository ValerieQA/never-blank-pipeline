"""The safety net under a hand-edited register: §8 rules 1–10.

Requirement Q1 says a person edits these files without code and without an AI.
This is what makes that safe. The validator runs in CI on every change to
`knowledge/` and to the client folders' rule files, and again at run start, where
a failure means the run does not start at all (`run_start.py`).

The ten rules are §8's, numbered as §8 numbers them:

===== ==========================================================================
KR-01 front matter is missing a required field, or has an unknown value
KR-02 status and tier are not an allowed pair (§2.3)
KR-03 an invariant, a tier-1 approved rule, a hard check from research or a
      non-`none` threshold lacks `approved_by`
KR-04 `Applies when` does not parse, or uses a label term
KR-05 `Influences` names a stage or field that does not exist
KR-06 a check's `## Route` table differs from the route table of record
KR-07 an `id` already exists in another file, or `version` did not increase when
      the body changed
KR-08 a `K-DST-*` record lacks `verified_on`
KR-09 a client ladder lacks a universal-level mapping, is not monotonic, or could
      permit a stronger assertion than the universal ladder
KR-10 a file contains text matching credential patterns
===== ==========================================================================

`KR-00` is the eleventh finding and not one of the ten: the file could not be read
as a register file at all — no front matter, no id, a section the format does not
have, a vocabulary that does not parse or has drifted from the code it mirrors. The
ten rules judge a record; KR-00 says there is no record to judge. It is reported
the same way and it stops a run the same way, because a register that cannot be
read is not a register a run may start on.

**Where "of record" is, for rule 6.** The Step 2 §5.3 route table lives in the
stage-topology registry (`src/editorial_core/topology.py`) — one engine means one
place that says what the engine is (CE-1). A check's `## Route` rows are compared
against it directly, so a route a check invents, or a counter it spends that the
route does not, is caught against the same authority a run executes.

**Rule 7 needs history, and says so.** "Already exists in another file" is visible
in the tree. "`version` did not increase when the body changed" is not: it needs
the tree as it was before. The caller supplies that as a `baseline`, which
`scripts/ci/check_knowledge_register.py` reads from git. With no baseline the first
half is still enforced and the second is skipped — a validation that quietly
invented a comparison would be worse than one that says which half it ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, Optional, Sequence

from src.editorial_core.topology import CANONICAL_TOPOLOGY, TerminalOutcome
from src.knowledge import records as record_format
from src.knowledge.grammar import (
    STRATEGY_TERM_STAGES,
    ConditionError,
    parse_condition,
    strategy_atoms,
)
from src.knowledge.ladder import (
    CLIENT_LADDER_SLOT,
    UNIVERSAL_TOP_LEVEL,
    LadderError,
    client_ladder_problems,
    parse_universal_ladder,
)
from src.knowledge.markdown import Document, DocumentError, load_document
from src.knowledge.records import (
    CheckRecord,
    KnowledgeRecord,
    RecordError,
    RouteRow,
)
from src.knowledge.vocabulary import (
    VOCAB_DIR_NAME,
    Vocabularies,
    VocabularyError,
    load_vocabularies,
)
from src.strategy.client_contracts import ClientContractError, load_stream_contract

KR_STRUCTURE: Final[str] = "KR-00"
KR_FRONT_MATTER: Final[str] = "KR-01"
KR_STATUS_TIER: Final[str] = "KR-02"
KR_APPROVAL: Final[str] = "KR-03"
KR_CONDITION: Final[str] = "KR-04"
KR_INFLUENCES: Final[str] = "KR-05"
KR_ROUTE: Final[str] = "KR-06"
KR_IDENTITY: Final[str] = "KR-07"
KR_VERIFIED_ON: Final[str] = "KR-08"
KR_CLIENT_LADDER: Final[str] = "KR-09"
KR_CREDENTIALS: Final[str] = "KR-10"

#: Every rule, with §8's own wording. The CI script prints these, and a test
#: proves that the corpus of invalid files covers each one.
RULES: Final[tuple[tuple[str, str], ...]] = (
    (KR_STRUCTURE, "the file cannot be read as a register file at all"),
    (KR_FRONT_MATTER, "front matter is missing a required field, or has an unknown value"),
    (KR_STATUS_TIER, "status and tier are not an allowed pair"),
    (
        KR_APPROVAL,
        "an invariant, a tier-1 approved rule, a hard check from research or a "
        "non-none threshold lacks approved_by",
    ),
    (KR_CONDITION, "`Applies when` does not parse, or uses a label term"),
    (KR_INFLUENCES, "`Influences` names a stage or field that does not exist"),
    (KR_ROUTE, "a check's `## Route` table differs from the canonical route table"),
    (
        KR_IDENTITY,
        "an id already exists in another file, or version did not increase when "
        "the body changed",
    ),
    (KR_VERIFIED_ON, "a K-DST-* record lacks verified_on"),
    (
        KR_CLIENT_LADDER,
        "a client ladder lacks a universal-level mapping, is not monotonic, or "
        "could permit a stronger assertion than the universal ladder",
    ),
    (KR_CREDENTIALS, "a file contains text matching credential patterns"),
)

RECORDS_DIR_NAME: Final[str] = "records"
CHECKS_DIR_NAME: Final[str] = "checks"
LADDERS_DIR_NAME: Final[str] = record_format.LADDER_DIR_NAME

#: The universal ladder's file, which every client ladder is measured against.
DEFAULT_LADDER_NAME: Final[str] = "default.md"

#: Deliberately narrow (Q8). It is here to stop the obvious accident — a key
#: pasted into a source line, a token left in a note — not to be a secret
#: scanner. Anything it does match is refused outright: the register is committed
#: to a public repository, so there is no safe way to carry a credential in it.
_CREDENTIAL_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("an AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("an API key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("a private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "an assigned secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password|passwd|"
            r"bearer)\b\s*[:=]\s*\S{8,}"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One reason the register is refused."""

    rule: str
    path: str
    message: str

    def render(self) -> str:
        return f"{self.rule}: {self.message}"


@dataclass(frozen=True, slots=True)
class RecordBaseline:
    """One record as it was before this change, for rule 7's second half."""

    version: int
    version_surface_digest: str


def validate_register(
    register_dir: Path,
    *,
    client_rule_paths: Sequence[Path] = (),
    baseline: Optional[Mapping[str, RecordBaseline]] = None,
) -> tuple[Finding, ...]:
    """Every reason this register is refused. Empty means it is accepted."""

    if not register_dir.is_dir():
        return (
            Finding(
                rule=KR_STRUCTURE,
                path=str(register_dir),
                message=f"{register_dir}: there is no knowledge register here",
            ),
        )

    try:
        vocabularies = load_vocabularies(register_dir)
    except VocabularyError as exc:
        # Nothing else is checkable: every condition and every `Influences`
        # entry is judged against the vocabularies, so a register without usable
        # ones is refused on that alone rather than reported rule by rule.
        return (
            Finding(
                rule=KR_STRUCTURE,
                path=str(register_dir / VOCAB_DIR_NAME),
                message=str(exc),
            ),
        )

    findings: list[Finding] = []
    knowledge: list[KnowledgeRecord] = []
    checks: list[CheckRecord] = []

    for path in _register_files(register_dir):
        findings.extend(_credential_findings(path))

    for path in _record_paths(register_dir):
        document = _document(path, findings)
        if document is None:
            continue
        try:
            record = record_format.parse_knowledge_record(document)
        except RecordError as exc:
            findings.append(Finding(KR_STRUCTURE, str(path), str(exc)))
            continue
        findings.extend(_family_findings(register_dir, record))
        knowledge.append(record)

    for path in _check_paths(register_dir):
        document = _document(path, findings)
        if document is None:
            continue
        try:
            check = record_format.parse_check_record(document)
        except (RecordError, DocumentError) as exc:
            findings.append(Finding(KR_STRUCTURE, str(path), str(exc)))
            continue
        checks.append(check)

    for record in knowledge:
        findings.extend(_record_front_matter(record))
        findings.extend(_status_and_tier(record))
        findings.extend(_record_approval(record))
        findings.extend(_condition(record, vocabularies))
        findings.extend(_influences(record, vocabularies))
        findings.extend(_verified_on(record))

    for check in checks:
        findings.extend(_check_front_matter(check))
        findings.extend(_check_approval(check))
        findings.extend(_route_table(check))

    findings.extend(_identity(knowledge, checks, baseline))
    universal_top, ladder_findings = _universal_ladder(register_dir, knowledge)
    findings.extend(ladder_findings)

    for path in client_rule_paths:
        findings.extend(_credential_findings(path))
        findings.extend(_client_ladder(path, universal_top))

    return tuple(findings)


# ----------------------------------------------------------------------
# KR-00 · the file is not a register file
# ----------------------------------------------------------------------


def _document(path: Path, findings: list[Finding]) -> Optional[Document]:
    try:
        return load_document(path)
    except DocumentError as exc:
        findings.append(Finding(KR_STRUCTURE, str(path), str(exc)))
        return None


def _family_findings(
    register_dir: Path, record: KnowledgeRecord
) -> tuple[Finding, ...]:
    """A record is filed under its own family (§1)."""

    directory = Path(record.path).parent
    if directory == register_dir / LADDERS_DIR_NAME:
        return ()
    if directory.name == record.family:
        return ()
    return (
        Finding(
            rule=KR_STRUCTURE,
            path=record.path,
            message=(
                f"{record.path}: {record.record_id} belongs in "
                f"{RECORDS_DIR_NAME}/{record.family}/, not in {directory.name}/"
            ),
        ),
    )


def _universal_ladder(
    register_dir: Path, knowledge: Sequence[KnowledgeRecord]
) -> tuple[int, tuple[Finding, ...]]:
    """The universal ladder's top level, and what is wrong with the ladder (§7)."""

    path = register_dir / LADDERS_DIR_NAME / DEFAULT_LADDER_NAME
    ladder = next(
        (record for record in knowledge if Path(record.path) == path), None
    )
    if ladder is None:
        return (
            UNIVERSAL_TOP_LEVEL,
            (
                Finding(
                    rule=KR_STRUCTURE,
                    path=str(path),
                    message=(
                        f"{path}: the universal strength ladder is missing; every "
                        "client ladder is measured against it"
                    ),
                ),
            ),
        )
    try:
        levels = parse_universal_ladder(ladder)
    except LadderError as exc:
        return UNIVERSAL_TOP_LEVEL, (Finding(KR_STRUCTURE, ladder.path, str(exc)),)
    if len(levels) != UNIVERSAL_TOP_LEVEL:
        return (
            len(levels),
            (
                Finding(
                    rule=KR_STRUCTURE,
                    path=ladder.path,
                    message=(
                        f"{ladder.path}: the ladder has {len(levels)} levels and "
                        f"the code that reads it expects {UNIVERSAL_TOP_LEVEL}; "
                        "the wording is the keeper's, the number of levels is "
                        "architecture (§7)"
                    ),
                ),
            ),
        )
    return len(levels), ()


# ----------------------------------------------------------------------
# KR-01 · front matter
# ----------------------------------------------------------------------


def _record_front_matter(record: KnowledgeRecord) -> tuple[Finding, ...]:
    problems: list[str] = []
    for name in record_format.RECORD_REQUIRED_FIELDS:
        if not (record.document.field(name) or "").strip():
            problems.append(f"`{name}` is missing")

    if record.version is not None and record.version_number is None:
        problems.append(
            f"`version` is {record.version!r}; it is a whole number from 1 upwards"
        )
    if record.status == record_format.WEAK_CANDIDATE:
        problems.append(
            f"`status` is `{record_format.WEAK_CANDIDATE}`, which the loader "
            "computes from `review_by` and is never written in a file (§2.3)"
        )
    elif record.status is not None and record.status not in record_format.FILE_STATUSES:
        problems.append(
            f"`status` is {record.status!r}; it is one of "
            f"{', '.join(record_format.FILE_STATUSES)}"
        )
    if record.tier and record.tier not in record_format.TIERS:
        problems.append(
            f"`tier` is {record.tier!r}; it is one of "
            f"{', '.join(record_format.TIERS)}"
        )
    unknown_classes = [
        value
        for value in record.evidence_classes
        if value not in record_format.EVIDENCE_CLASSES
    ]
    if unknown_classes:
        problems.append(
            f"`evidence_class` has no class {', '.join(unknown_classes)}; the "
            f"classes are {', '.join(record_format.EVIDENCE_CLASSES)}"
        )
    if record.confidence and record.confidence not in record_format.CONFIDENCES:
        problems.append(
            f"`confidence` is {record.confidence!r}; it is one of "
            f"{', '.join(record_format.CONFIDENCES)}"
        )
    problems.extend(_dates(record.review_by, record.verified_on))
    if (
        record.verified_on is None
        and set(record.evidence_classes) & set(record_format.DATED_EVIDENCE_CLASSES)
    ):
        problems.append(
            "`verified_on` is missing, and platform and vendor knowledge has to "
            "say when it was last checked (§2.2)"
        )
    return _findings(KR_FRONT_MATTER, record.path, problems)


def _check_front_matter(check: CheckRecord) -> tuple[Finding, ...]:
    problems: list[str] = []
    for name in record_format.CHECK_REQUIRED_FIELDS:
        if not (check.document.field(name) or "").strip():
            problems.append(f"`{name}` is missing")

    if check.version is not None and check.version_number is None:
        problems.append(
            f"`version` is {check.version!r}; it is a whole number from 1 upwards"
        )
    if check.check_class and check.check_class not in record_format.CHECK_CLASSES:
        problems.append(
            f"`class` is {check.check_class!r}; a check is `H` (hard) or `S` (soft)"
        )
    if (
        check.rule_status
        and check.rule_status not in record_format.CHECK_RULE_STATUSES
    ):
        problems.append(
            f"`rule_status` is {check.rule_status!r}; it is one of "
            f"{', '.join(record_format.CHECK_RULE_STATUSES)}"
        )
    if check.method and check.method not in record_format.CHECK_METHODS:
        problems.append(
            f"`method` is {check.method!r}; it is one of "
            f"{', '.join(record_format.CHECK_METHODS)}"
        )
    unknown_classes = [
        value
        for value in check.evidence_classes
        if value not in record_format.EVIDENCE_CLASSES
    ]
    if unknown_classes:
        problems.append(
            f"`evidence_class` has no class {', '.join(unknown_classes)}; the "
            f"classes are {', '.join(record_format.EVIDENCE_CLASSES)}"
        )
    problems.extend(_dates(check.review_by, None))
    return _findings(KR_FRONT_MATTER, check.path, problems)


def _dates(review_by: Optional[str], verified_on: Optional[str]) -> tuple[str, ...]:
    problems: list[str] = []
    if review_by and not record_format.is_date(review_by):
        problems.append(f"`review_by` is {review_by!r}; a date is `YYYY-MM-DD`")
    if verified_on and not record_format.is_date(verified_on):
        problems.append(f"`verified_on` is {verified_on!r}; a date is `YYYY-MM-DD`")
    return tuple(problems)


# ----------------------------------------------------------------------
# KR-02 · status and tier
# ----------------------------------------------------------------------


def _status_and_tier(record: KnowledgeRecord) -> tuple[Finding, ...]:
    allowed = record_format.STATUS_TIERS.get(record.status or "")
    if allowed is None or not record.tier:
        # An unknown status or a missing tier is rule 1's finding, not this one.
        return ()
    if record.tier in allowed:
        return ()
    return _findings(
        KR_STATUS_TIER,
        record.path,
        [
            f"a `{record.status}` record is tier {' or '.join(allowed)}, "
            f"not tier {record.tier}"
        ],
    )


# ----------------------------------------------------------------------
# KR-03 · approvals (Q5, I-12, I-13)
# ----------------------------------------------------------------------


def _record_approval(record: KnowledgeRecord) -> tuple[Finding, ...]:
    needs = ""
    if record.status == "invariant":
        needs = "an invariant must always hold, so making one is the owner's call"
    elif record.status == "approved-rule" and record.tier == "1":
        needs = "a tier-1 hard rule is enforced without appeal, so it is the owner's"
    if not needs:
        return ()
    return _findings(
        KR_APPROVAL, record.path, _approval_problems(record.approved_by, needs)
    )


def _check_approval(check: CheckRecord) -> tuple[Finding, ...]:
    problems: list[str] = []
    if check.rule_status == "invariant":
        problems.extend(
            _approval_problems(
                check.approved_by,
                "a check whose rule status is `invariant` enforces something that "
                "must always hold, and making one is the owner's call",
            )
        )
    threshold = (check.threshold or "").strip()
    if threshold and threshold != record_format.NO_THRESHOLD:
        problems.extend(
            _approval_problems(
                check.approved_by,
                f"`threshold: {threshold}` is a number a soft signal acts on, and "
                "only an owner may set one (I-12)",
            )
        )
    if check.is_hard and record_format.RESEARCH_EVIDENCE_CLASS in check.evidence_classes:
        problems.extend(
            _approval_problems(
                check.approved_by,
                "a hard check drawn from research needs the owner's approval: a "
                "research finding does not become a hard check on its own (I-13)",
            )
        )
    return _findings(KR_APPROVAL, check.path, problems)


def _approval_problems(approved_by: Optional[str], why: str) -> tuple[str, ...]:
    value = (approved_by or "").strip()
    if not value:
        return (f"`approved_by` is missing: {why}",)
    if not re.search(r"\d{4}-\d{2}-\d{2}", value):
        return (
            f"`approved_by` is {value!r}, without a date; it records who approved "
            "it and when",
        )
    return ()


# ----------------------------------------------------------------------
# KR-04 · the condition (Q4, I-10)
# ----------------------------------------------------------------------


def _condition(
    record: KnowledgeRecord, vocabularies: Vocabularies
) -> tuple[Finding, ...]:
    try:
        condition = parse_condition(record.applies_when, vocabularies)
    except ConditionError as exc:
        return _findings(KR_CONDITION, record.path, [str(exc)])

    strategy = strategy_atoms(condition)
    if not strategy:
        return ()
    stages = {influence.stage for influence in record.influences}
    if stages & set(STRATEGY_TERM_STAGES):
        return ()
    return _findings(
        KR_CONDITION,
        record.path,
        [
            f"the condition reads `{strategy[0].text}`, and this record influences "
            f"{', '.join(sorted(stages))}. A strategy term may only be read at "
            f"{STRATEGY_TERM_STAGES[0]}…{STRATEGY_TERM_STAGES[-1]}, where a "
            "strategy exists; earlier the condition could only ever be false"
        ],
    )


# ----------------------------------------------------------------------
# KR-05 · what a record influences
# ----------------------------------------------------------------------


def _influences(
    record: KnowledgeRecord, vocabularies: Vocabularies
) -> tuple[Finding, ...]:
    stages = vocabularies.get("stages")
    fields = vocabularies.get("fields")
    problems: list[str] = []
    for influence in record.influences:
        if stages.term(influence.stage) is None:
            problems.append(
                f"`## Influences` names the stage {influence.stage}, which "
                f"{stages.path} does not have"
            )
        for name in influence.fields:
            if fields.term(name) is None:
                problems.append(
                    f"`## Influences` names the field `{name}`, which "
                    f"{fields.path} does not have"
                )
    return _findings(KR_INFLUENCES, record.path, problems)


# ----------------------------------------------------------------------
# KR-06 · a check's route table against the registry
# ----------------------------------------------------------------------


def _route_table(check: CheckRecord) -> tuple[Finding, ...]:
    problems: list[str] = []
    edges = [row.edge for row in check.routes]
    sources = {edge[0] for edge in edges if edge is not None}
    if len(sources) > 1:
        problems.append(
            f"the `## Route` rows leave {', '.join(sorted(sources))}; one check is "
            "applied at one stage"
        )

    for row in check.routes:
        if row.is_hint:
            problems.extend(_hint_row(check, row))
            continue
        if row.is_terminal:
            problems.extend(_terminal_row(row))
            continue
        problems.extend(_routed_row(row))

    if check.check_class == "S" and any(not row.is_hint for row in check.routes):
        problems.append(
            "a soft check routes nothing: its results are hints and portfolio "
            "signals, and never block (I-12)"
        )
    return _findings(KR_ROUTE, check.path, problems)


def _routed_row(row: RouteRow) -> tuple[str, ...]:
    edge = row.edge
    if edge is None:  # pragma: no cover - parsing has already refused it
        return ()
    source, target = edge
    declared = [
        route
        for route in CANONICAL_TOPOLOGY.replan_routes
        if route.source == source and route.cause == row.cause
    ]
    if not declared:
        causes = sorted(
            route.cause
            for route in CANONICAL_TOPOLOGY.replan_routes
            if route.source == source
        )
        return (
            f"the row {row.finding[:40]!r} routes {source} → {target} for the "
            f"cause {row.cause!r}, which the canonical route table does not have. "
            f"From {source} it declares: {', '.join(causes) or 'no route at all'}",
        )
    route = declared[0]
    problems: list[str] = []
    if route.target != target:
        problems.append(
            f"the row {row.finding[:40]!r} routes {source} → {target}; "
            f"{row.cause} goes to {route.target}"
        )
    if route.counter != row.counter:
        problems.append(
            f"the row {row.finding[:40]!r} spends {row.counter!r}; "
            f"{row.cause} spends {route.counter}"
        )
    if route.on_exhaustion.value != row.on_exhaustion:
        problems.append(
            f"the row {row.finding[:40]!r} ends as {row.on_exhaustion!r} when the "
            f"counter runs out; {row.cause} ends as {route.on_exhaustion.value}"
        )
    return tuple(problems)


def _terminal_row(row: RouteRow) -> tuple[str, ...]:
    problems: list[str] = []
    if row.on_exhaustion not in {outcome.value for outcome in TerminalOutcome}:
        problems.append(
            f"the terminal row {row.finding[:40]!r} ends as "
            f"{row.on_exhaustion!r}, which is not an outcome the topology has"
        )
    for column, value in (("Cause", row.cause), ("Counter", row.counter)):
        if value != record_format.ROUTE_NONE:
            problems.append(
                f"the terminal row {row.finding[:40]!r} names a {column.lower()} "
                f"({value!r}); a terminal finding spends nothing, so the column "
                f"is `{record_format.ROUTE_NONE}`"
            )
    return tuple(problems)


def _hint_row(check: CheckRecord, row: RouteRow) -> tuple[str, ...]:
    if check.check_class == "H":
        return (
            f"the row {row.finding[:40]!r} is a hint, and a hard check does not "
            "produce hints",
        )
    named = [
        column
        for column, value in (
            ("Cause", row.cause),
            ("Counter", row.counter),
            ("On exhaustion", row.on_exhaustion),
        )
        if value != record_format.ROUTE_NONE
    ]
    if named:
        return (
            f"the hint row {row.finding[:40]!r} fills in "
            f"{', '.join(named)}; a hint routes nothing",
        )
    return ()


# ----------------------------------------------------------------------
# KR-07 · identity and versioning
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Identified:
    """A knowledge record and a check record, seen only as identified things."""

    identity: str
    path: str
    version: Optional[int]
    document: Document
    change_log_versions: tuple[int, ...]


def _identity(
    knowledge: Sequence[KnowledgeRecord],
    checks: Sequence[CheckRecord],
    baseline: Optional[Mapping[str, RecordBaseline]],
) -> tuple[Finding, ...]:
    entries = [
        *(
            _Identified(
                identity=record.record_id,
                path=record.path,
                version=record.version_number,
                document=record.document,
                change_log_versions=record.change_log_versions,
            )
            for record in knowledge
        ),
        *(
            _Identified(
                identity=check.check_id,
                path=check.path,
                version=check.version_number,
                document=check.document,
                change_log_versions=check.change_log_versions,
            )
            for check in checks
        ),
    ]

    findings: list[Finding] = []
    seen: dict[str, str] = {}
    for entry in entries:
        first = seen.get(entry.identity)
        if first is None:
            seen[entry.identity] = entry.path
            continue
        findings.append(
            Finding(
                rule=KR_IDENTITY,
                path=entry.path,
                message=(
                    f"{entry.path}: {entry.identity} is already the id of {first}. "
                    "An id is stable across versions and is never reused"
                ),
            )
        )

    for entry in entries:
        version = entry.version
        if version is None:
            continue  # rule 1 has already said the version is unreadable
        findings.extend(_version_story(entry))
        previous = None if baseline is None else baseline.get(entry.identity)
        if previous is None:
            continue
        if (
            previous.version_surface_digest != entry.document.version_surface_digest()
            and version <= previous.version
        ):
            findings.append(
                Finding(
                    rule=KR_IDENTITY,
                    path=entry.path,
                    message=(
                        f"{entry.path}: {entry.identity} has changed and is still "
                        f"version {version}. Every change below the front "
                        "matter, and every change of status, tier or confidence, "
                        "is a new version with a change-log line (§2.2)"
                    ),
                )
            )
    return tuple(findings)


def _version_story(entry: _Identified) -> tuple[Finding, ...]:
    """The change log and `supersedes` agree with `version` (§2.2)."""

    identity, path, version = entry.identity, entry.path, entry.version or 1
    problems: list[str] = []
    logged = entry.change_log_versions
    expected = tuple(range(version, 0, -1))
    if logged != expected:
        problems.append(
            f"`## Change log` lists version(s) "
            f"{', '.join(str(number) for number in logged) or 'none'}; at version "
            f"{version} it has one line per version, newest first: "
            f"{', '.join(str(number) for number in expected)}"
        )
    supersedes = (entry.document.field("supersedes") or "").strip()
    if version == 1 and supersedes:
        problems.append(
            f"`supersedes` is {supersedes!r}, and version 1 supersedes nothing"
        )
    if version > 1:
        wanted = record_format.expected_supersedes(identity, version)
        if supersedes != wanted:
            problems.append(
                f"`supersedes` is {supersedes!r}; version {version} supersedes "
                f"`{wanted}`"
            )
    return _findings(KR_IDENTITY, path, problems)


# ----------------------------------------------------------------------
# KR-08 · platform knowledge says when it was checked
# ----------------------------------------------------------------------


def _verified_on(record: KnowledgeRecord) -> tuple[Finding, ...]:
    if not record.record_id.startswith("K-DST-") or record.verified_on:
        return ()
    return _findings(
        KR_VERIFIED_ON,
        record.path,
        [
            "`verified_on` is missing. Destination knowledge is only as good as "
            "the day it was checked, and expiry is computed from that day (§5)"
        ],
    )


# ----------------------------------------------------------------------
# KR-09 · client ladders
# ----------------------------------------------------------------------


def _client_ladder(path: Path, universal_top: int) -> tuple[Finding, ...]:
    try:
        contract = load_stream_contract(path)
    except ClientContractError as exc:
        return (Finding(KR_STRUCTURE, str(path), str(exc)),)
    declared = contract.plan_slots
    values = next(
        (levels for slot, levels in declared if slot == CLIENT_LADDER_SLOT), ()
    )
    if not values:
        # A contract that declares no ladder uses the universal one. That is a
        # choice, not an omission.
        return ()
    problems = client_ladder_problems(
        values, path=str(path), universal_top=universal_top
    )
    return tuple(
        Finding(rule=KR_CLIENT_LADDER, path=str(path), message=problem)
        for problem in problems
    )


# ----------------------------------------------------------------------
# KR-10 · credentials (Q8)
# ----------------------------------------------------------------------


def _credential_findings(path: Path) -> tuple[Finding, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return (
            Finding(KR_STRUCTURE, str(path), f"{path}: cannot be read ({exc})"),
        )
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for what, pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(line):
                problems.append(
                    f"line {number} looks like {what}. The register is committed "
                    "to a public repository, so no file in it may carry one — and "
                    "a credential that has been committed is a credential to "
                    "rotate, not to delete"
                )
                break
    return _findings(KR_CREDENTIALS, str(path), problems)


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------


def _record_paths(register_dir: Path) -> tuple[Path, ...]:
    return (
        *sorted((register_dir / RECORDS_DIR_NAME).rglob("*.md")),
        *sorted((register_dir / LADDERS_DIR_NAME).glob("*.md")),
    )


def _check_paths(register_dir: Path) -> tuple[Path, ...]:
    return tuple(sorted((register_dir / CHECKS_DIR_NAME).glob("*.md")))


def _register_files(register_dir: Path) -> tuple[Path, ...]:
    """Every file of the register, for the credential scan."""

    return tuple(sorted(path for path in register_dir.rglob("*") if path.is_file()))


def _findings(rule: str, path: str, problems: Sequence[str]) -> tuple[Finding, ...]:
    return tuple(
        Finding(rule=rule, path=path, message=f"{path}: {problem}")
        for problem in problems
    )
