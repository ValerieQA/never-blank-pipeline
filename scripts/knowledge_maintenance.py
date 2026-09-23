#!/usr/bin/env python3
"""Run the Knowledge Maintenance job (Issue #297, Step 4 §5.2).

The scheduled entry point of `src/knowledge/maintenance.py`: it scans the
register and the client rule files, and writes one `expiry_review`
KnowledgeQueueItem per record per expiry into the durable ledger.

    python3 scripts/knowledge_maintenance.py
    python3 scripts/knowledge_maintenance.py --dry-run
    python3 scripts/knowledge_maintenance.py --warning-days 30 --commit

**Offline, and outside every run.** §5.2: the job does not depend on a
publication or a run happening, and it never blocks one. Nothing here reads a
run workspace, a publication marker or the published index, and nothing here
changes a knowledge status — the keeper decides offline (I-02), and this is
what makes sure they are asked.

**Repeating it is safe.** The item id is derived from the record and the
`review_by` that lapsed, and the ledger write is create-once, so a second pass
over an unanswered expiry writes nothing. That is what makes a daily schedule
harmless.

**`--commit` is opt-in.** Writing the item makes it exist; committing it makes
it durable, and the two are separate steps because a commit can fail and a
written record must not depend on one (Step 3 §3.1). A scheduled job that is
meant to leave something behind asks for the commit by name.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

from src.knowledge.maintenance import (
    DEFAULT_WARNING_DAYS,
    MaintenanceError,
    MaintenanceReport,
    run_maintenance,
    scan,
)
from src.run.ledger import LedgerCommitStatus, commit_ledger

#: The register, and the client folders whose rule files are scanned with it
#: (§1: client rules stay with the client).
DEFAULT_REGISTER = Path("knowledge")
DEFAULT_CLIENTS = Path("clients")

#: The pass ran and read everything it scanned.
EXIT_OK = 0
#: The pass ran and stepped over a file it could not read, or could not make
#: its records durable. Neither stops a production run; both want a person.
EXIT_INCOMPLETE = 1


def client_record_paths(clients_dir: Path) -> tuple[Path, ...]:
    """Every client rule record: `clients/<client>/rules/<K-ID>.md` (§1, §2).

    By id and not by suffix. A rules directory also holds a README explaining
    itself to the keeper who edits it, and a job that read that as a record
    would report a broken register once per client, every day.
    """

    if not clients_dir.is_dir():
        return ()
    return tuple(sorted(clients_dir.glob("*/rules/K-*.md")))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--register", type=Path, default=DEFAULT_REGISTER,
        help="the knowledge register (default: knowledge)",
    )
    parser.add_argument(
        "--clients", type=Path, default=DEFAULT_CLIENTS,
        help="the client directories whose rule files are scanned too",
    )
    parser.add_argument(
        "--warning-days", type=int, default=DEFAULT_WARNING_DAYS,
        help=(
            "how long before `review_by` a record is queued "
            f"(default: {DEFAULT_WARNING_DAYS})"
        ),
    )
    parser.add_argument(
        "--today", default=None,
        help="the date the pass runs for, ISO-8601 (default: today)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="say whose review is due and write nothing",
    )
    parser.add_argument(
        "--commit", action="store_true",
        help=(
            "commit and push the items this pass wrote. Off by default: "
            "writing a record and committing it are separate steps, because a "
            "commit can fail and a written record must not depend on one"
        ),
    )
    arguments = parser.parse_args(argv)

    try:
        today = date.fromisoformat(arguments.today) if arguments.today else None
    except ValueError:
        print(
            f"--today is {arguments.today!r}, which is not an ISO-8601 date",
            file=sys.stderr,
        )
        return EXIT_INCOMPLETE

    clients = client_record_paths(arguments.clients)
    try:
        if arguments.dry_run:
            report = scan(
                arguments.register,
                client_rule_paths=clients,
                today=today,
                warning_days=arguments.warning_days,
            )
        else:
            report = run_maintenance(
                arguments.register,
                client_rule_paths=clients,
                today=today,
                warning_days=arguments.warning_days,
            )
    except MaintenanceError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INCOMPLETE

    status = report_pass(report, dry_run=arguments.dry_run)
    if arguments.commit and report.written:
        status = max(status, commit_pass(report))
    return status


def report_pass(report: MaintenanceReport, *, dry_run: bool) -> int:
    """Print what the pass found, and return its exit status."""

    print(report.summary())
    for item in report.due:
        state = "expired" if item.expired else "due"
        print(
            f"  {item.record_id} v{item.record_version} "
            f"({item.source.value}, {item.file_status.value} → "
            f"{item.effective_status.value}) {state} {item.review_by.isoformat()} "
            f"· {item.item_id}"
        )
    if dry_run:
        print("--dry-run: nothing was written.")
    for line in report.unreadable:
        print(line, file=sys.stderr)
    if report.unreadable:
        print(
            "\nThese records were stepped over, and their reviews were not "
            "raised. The register validator is what refuses a broken file "
            "(scripts/ci/check_knowledge_register.py); this job only says "
            "which keeper questions it could not ask.",
            file=sys.stderr,
        )
        return EXIT_INCOMPLETE
    return EXIT_OK


def commit_pass(report: MaintenanceReport) -> int:
    """Commit the items this pass wrote, and say what became of them."""

    commit = commit_ledger(
        paths=report.written,
        message=(
            f"knowledge queue: {len(report.written)} expiry review item(s) "
            f"from the maintenance pass of {report.ran_on.isoformat()}"
        ),
    )
    print(f"ledger commit: {commit.status.value}")
    if commit.status is LedgerCommitStatus.COMMITTED:
        return EXIT_OK
    failure = commit.failure.value if commit.failure else "not_attempted"
    print(
        f"the items were written but not committed ({failure}). They are on "
        "disk, no run is affected, and the next pass writes nothing for an "
        "expiry this one already raised — recovering them is offline "
        "maintenance.",
        file=sys.stderr,
    )
    return EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
