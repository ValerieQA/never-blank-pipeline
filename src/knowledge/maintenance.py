"""The Knowledge Maintenance job: expiry review, offline and scheduled (§5.2).

Patch S4-R1 took expiry and review queue items away from the run and gave them
to a job of their own, and §5.2 says why in one line: "It does not depend on a
publication or a run happening, so expiry review continues even when nothing is
published." Knowledge goes stale on the calendar's schedule, not on the
engine's. A register whose reviews were raised by runs would stop asking for
them exactly in the weeks nothing was published — which are the weeks the
platform knowledge in it is quietly getting older.

So this job takes a register directory and a date, and nothing else. It reads
no run, no workspace, no publication and no marker; there is nothing for it to
be blocked by and nothing it can block. It runs outside every production run
(§5.2), and a run that starts while it is running is unaffected: the run's
loader computes §5 demotion for itself, from the same `review_by` field, and
**the loader writes no queue items**.

What it does, and what it deliberately does not
------------------------------------------------
It writes one ``expiry_review`` KnowledgeQueueItem per record per expiry, for
every record past its `review_by` or inside the warning window before it, and
it **changes no status** — that is I-02, and it is also §5.2's own scope line.
The keeper decides offline; this job is what makes sure they are asked.

Idempotency is not a bookkeeping file. The item's id is derived from the record
and the `review_by` that lapsed (`ExpiryReviewItem.identity_for`), the ledger
write is create-once, and so the tenth scheduled pass over an unanswered expiry
writes nothing. A `review_by` the keeper moves forward is a different expiry and
therefore a different item, which is how a re-reviewed record comes back into
the queue when its next review falls due.

**A file it cannot read is reported and stepped over**, and the scan goes on.
Refusing the whole pass would be the validator's verdict (`validator.py`, §8),
delivered by the one part of the system whose job is to keep asking questions:
one broken record would then silence the review of every sound one, at no cost
to whoever broke it.

Sources: ``docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md`` §1, §5
and §5.2, with patch ``PATCH_S4R1_STEP4.md``;
``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §3.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Sequence

from pydantic import ValidationError as _PydanticValidationError

from src.artifacts import ArtifactCollisionError
from src.editorial_core.arp import KnowledgeStatus, KnowledgeTier
from src.knowledge import records as record_format
from src.knowledge.loader import effective_status
from src.knowledge.markdown import DocumentError, load_document
from src.knowledge.records import RecordError
from src.knowledge.validator import (
    CHECKS_DIR_NAME,
    LADDERS_DIR_NAME,
    RECORDS_DIR_NAME,
)
from src.run.knowledge_queue import (
    ExpiryReviewItem,
    RegisterRecordKind,
    RegisterSource,
    write_queue_item,
)

#: There is deliberately no default warning window here.
#:
#: §5.2 asks the job to scan for records past `review_by` "or within a warning
#: window before it", and fixes no duration. How much notice a keeper wants
#: before a review falls due is an owner and keeper judgement about how they
#: work, not a fact about the architecture — so choosing a number here would
#: settle an open product question in code, which this issue's escalation rule
#: forbids.
#:
#: Every caller therefore states the window itself: `warning_days` is a
#: required argument, the command line requires `--warning-days`, and the
#: scheduled workflow reads it from repository configuration. `0` is a real and
#: meaningful value, not a stand-in for a missing one: it means the warning
#: window is not in use, and the job queues exactly what the first half of §5.2
#: asks for — the records already past `review_by`.


class MaintenanceError(ValueError):
    """The job was asked for something it refuses to do."""


@dataclass(frozen=True, slots=True)
class RegisterFile:
    """One file the job scans, and what reading it would make of it."""

    path: Path
    record_kind: RegisterRecordKind
    source: RegisterSource


@dataclass(frozen=True, slots=True)
class MaintenanceReport:
    """One pass of the job: what it read, raised, and could not read."""

    ran_on: date
    scanned: int
    #: Every record whose review is due, as the items for them, oldest expiry
    #: first. Raised on this pass or on an earlier one.
    due: tuple[ExpiryReviewItem, ...]
    written: tuple[Path, ...]
    #: The items that were already in the queue: an expiry nobody has answered
    #: yet, asked once (§5.2).
    already_queued: tuple[str, ...]
    #: One line per file the job stepped over. The validator is what refuses a
    #: register; this only says which records it could not ask about.
    unreadable: tuple[str, ...]

    @property
    def clean(self) -> bool:
        """Did the pass read every file it scanned?"""

        return not self.unreadable

    def summary(self) -> str:
        """One line, for the scheduled job's log."""

        return (
            f"{self.ran_on.isoformat()}: scanned {self.scanned} record(s), "
            f"{len(self.due)} review(s) due, {len(self.written)} queue item(s) "
            f"written, {len(self.already_queued)} already queued, "
            f"{len(self.unreadable)} file(s) unreadable"
        )


def register_files(
    register_dir: Path, *, client_rule_paths: Sequence[Path] = ()
) -> tuple[RegisterFile, ...]:
    """Every file §5.2 asks the job to scan: the register and client rules.

    The register's own three directories, and the client rule files the caller
    names. Client rules stay in the client folder (§1), so the job cannot find
    them by walking the register — which is the same reason
    :func:`~src.knowledge.run_start.validate_at_run_start` takes them as an
    argument, and they are passed here the same way.
    """

    files: list[RegisterFile] = []
    for directory, pattern, kind in (
        # The same three directories the loader reads (§9.2), and the record
        # format each of them holds.
        (RECORDS_DIR_NAME, "**/*.md", RegisterRecordKind.KNOWLEDGE),
        (LADDERS_DIR_NAME, "*.md", RegisterRecordKind.KNOWLEDGE),
        (CHECKS_DIR_NAME, "*.md", RegisterRecordKind.CHECK),
    ):
        files.extend(
            RegisterFile(
                path=path,
                record_kind=kind,
                source=RegisterSource.REGISTER,
            )
            for path in sorted((register_dir / directory).glob(pattern))
        )
    files.extend(
        RegisterFile(
            path=path,
            record_kind=RegisterRecordKind.KNOWLEDGE,
            source=RegisterSource.CLIENT,
        )
        for path in client_rule_paths
    )
    return tuple(files)


def scan(
    register_dir: Path,
    *,
    client_rule_paths: Sequence[Path] = (),
    today: Optional[date] = None,
    warning_days: int,
) -> MaintenanceReport:
    """Read the register and say whose review is due. Writes nothing.

    The reading half of the job, separate from the writing half so that a
    person can ask what the queue would receive without putting anything in
    it — and so that the one-item-per-expiry claim is testable on ids rather
    than on the ledger's directory listing.
    """

    if warning_days < 0:
        raise MaintenanceError(
            "a warning window is a number of days before `review_by`; got "
            f"{warning_days}"
        )
    when = today or date.today()

    due: list[ExpiryReviewItem] = []
    unreadable: list[str] = []
    files = register_files(register_dir, client_rule_paths=client_rule_paths)
    for entry in files:
        try:
            item = _item_for(entry, today=when, warning_days=warning_days)
        except (DocumentError, RecordError, MaintenanceError) as exc:
            unreadable.append(str(exc))
            continue
        if item is not None:
            due.append(item)

    return MaintenanceReport(
        ran_on=when,
        scanned=len(files),
        due=tuple(sorted(due, key=lambda item: (item.review_by, item.record_id))),
        written=(),
        already_queued=(),
        unreadable=tuple(unreadable),
    )


def run_maintenance(
    register_dir: Path,
    *,
    client_rule_paths: Sequence[Path] = (),
    today: Optional[date] = None,
    warning_days: int,
    ledger_root: Optional[Path] = None,
) -> MaintenanceReport:
    """One scheduled pass: scan, and write the items that are not queued yet.

    An item the ledger already holds is not written again and not an error
    (§5.2): the create-once write is the check, so two passes that overlap
    cannot both add the same expiry.
    """

    report = scan(
        register_dir,
        client_rule_paths=client_rule_paths,
        today=today,
        warning_days=warning_days,
    )

    written: list[Path] = []
    already_queued: list[str] = []
    for item in report.due:
        try:
            written.append(write_queue_item(item, root=ledger_root))
        except ArtifactCollisionError:
            already_queued.append(item.item_id)

    return MaintenanceReport(
        ran_on=report.ran_on,
        scanned=report.scanned,
        due=report.due,
        written=tuple(written),
        already_queued=tuple(already_queued),
        unreadable=report.unreadable,
    )


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _item_for(
    entry: RegisterFile, *, today: date, warning_days: int
) -> Optional[ExpiryReviewItem]:
    """The item this file is due for, or ``None`` when its review is not.

    Raises what reading the file raised, and :class:`MaintenanceError` for a
    file that parses as a record and then says nothing this job can act on —
    an unreadable `review_by`, a version that is not a version, a status
    outside the vocabulary. Each of those is a §8 rule the validator already
    refuses; here it is one record the keeper is not asked about, named.
    """

    document = load_document(entry.path)
    identity: str
    version: Optional[int]
    review_by: Optional[str]
    status_value: Optional[str]
    tier_value: Optional[str]
    if entry.record_kind is RegisterRecordKind.CHECK:
        check = record_format.parse_check_record(document)
        identity = check.check_id
        version = check.version_number
        review_by = check.review_by
        status_value = check.rule_status
        tier_value = None
    else:
        record = record_format.parse_knowledge_record(document)
        identity = record.record_id
        version = record.version_number
        review_by = record.review_by
        status_value = record.status
        tier_value = record.tier

    if version is None:
        raise MaintenanceError(
            f"{entry.path}: `version` is not a whole number from 1 upwards, and "
            "the keeper is asked about a record at a version"
        )
    if not record_format.is_date(review_by):
        raise MaintenanceError(
            f"{entry.path}: `review_by` is {review_by!r}, and the review this job "
            "raises is the one that date falls due on (§5)"
        )
    lapses_on = date.fromisoformat(review_by or "")
    if today < lapses_on - timedelta(days=warning_days):
        return None

    file_status = _status(
        status_value,
        entry.path,
        # A check declares its authority as `rule_status`, separately from its
        # detection method (§3, Q3), so the two formats name the field
        # differently and a message that said `status` would send the keeper
        # looking for a field their file does not have.
        named="rule_status"
        if entry.record_kind is RegisterRecordKind.CHECK
        else "status",
    )
    if file_status is KnowledgeStatus.RETIRED:
        # Kept for traceability and never loaded (§2.3). The keeper closed it;
        # asking them to review it again is asking about a decision they made.
        return None

    if entry.record_kind is RegisterRecordKind.CHECK:
        # §5: a check past its `review_by` keeps its rule status and is
        # flagged, for the reason a hard rule is — dropping the authority of a
        # check nobody re-checked is the unsafe direction.
        status, expired = file_status, lapses_on < today
    else:
        status, expired = effective_status(file_status, lapses_on, today=today)

    try:
        return ExpiryReviewItem(
            item_id=ExpiryReviewItem.identity_for(identity, lapses_on),
            raised_on=today,
            record_id=identity,
            record_version=version,
            record_kind=entry.record_kind,
            source=entry.source,
            review_by=lapses_on,
            file_status=file_status,
            effective_status=status,
            tier=None if tier_value is None else _tier(tier_value, entry.path),
            expired=expired,
        )
    except _PydanticValidationError as exc:
        # The item refuses what the register should never have held — a
        # `weak-candidate` written in a file, an id that is not an identifier.
        # Reported as one record stepped over, with the field that said so.
        first = exc.errors()[0]
        field = " -> ".join(str(part) for part in first["loc"]) or "value"
        raise MaintenanceError(
            f"{entry.path}: no queue item can be raised for {identity}: "
            f"{field}: {first['msg']}"
        ) from exc


def _status(value: Optional[str], path: Path, *, named: str) -> KnowledgeStatus:
    try:
        return KnowledgeStatus(value)
    except ValueError as exc:
        raise MaintenanceError(
            f"{path}: `{named}` is {value!r}, which is not one of "
            f"{', '.join(member.value for member in KnowledgeStatus)}"
        ) from exc


def _tier(value: str, path: Path) -> KnowledgeTier:
    try:
        return KnowledgeTier(value)
    except ValueError as exc:
        raise MaintenanceError(
            f"{path}: `tier` is {value!r}, which is not one of "
            f"{', '.join(member.value for member in KnowledgeTier)}"
        ) from exc
