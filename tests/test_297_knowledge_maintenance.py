"""Issue #297: the Knowledge Maintenance job — expiry review, offline.

Patch S4-R1 split the producers of a KnowledgeQueueItem, and §5.2 gives the
`expiry_review` kind to a scheduled offline job rather than to a run. Four
claims, each of which has to be able to fail:

- **One item per record per expiry, however often the job runs** (§5.2). The
  acceptance evidence of the issue: an expired record in a fixture register
  produces exactly one queue item across repeated passes. It is the derived id
  plus the create-once ledger write that makes that true, so the test runs the
  job three times and counts files.
- **No dependency on publications, and none on a run** (§5.2). The job is
  driven here with nothing but a register directory and a date: no workspace,
  no run summary, no publication marker, no published index. A register whose
  reviews were raised by runs would go quiet exactly in the weeks nothing was
  published.
- **It changes no knowledge status.** The scope line of the issue and I-02: it
  asks the keeper and decides nothing. The fixture register is compared byte
  for byte before and after a pass.
- **What the item says about the record is §5's answer, not a second one.** An
  expired `candidate` is a `weak-candidate`; an expired tier-1 rule is still an
  `approved-rule`; an expired check keeps its rule status; a retired record is
  not asked about at all.

The register under test is `tests/fixtures/knowledge_maintenance/`, whose dates
are fixed so that `TODAY` decides which records are due. One file in it cannot
be read on purpose.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts.knowledge_maintenance import client_record_paths
from src.artifacts import ArtifactCollisionError
from src.editorial_core.arp import KnowledgeStatus, KnowledgeTier
from src.knowledge import maintenance
from src.knowledge.maintenance import (
    MaintenanceError,
    MaintenanceReport,
    register_files,
    run_maintenance,
    scan,
)
from src.run.knowledge_queue import (
    QUEUE_DIRECTORY,
    ExpiryReviewItem,
    KnowledgeQueueError,
    QueueItemKind,
    RegisterRecordKind,
    RegisterSource,
    write_queue_item,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "knowledge_maintenance"
REGISTER = FIXTURE / "register"
CLIENT_RULES = client_record_paths(FIXTURE / "clients")

#: The day the job runs for. `K-FX-04` falls inside the warning window on it,
#: and everything with an earlier `review_by` is already past.
TODAY = date(2026, 6, 1)

#: What the fixture register is due for on :data:`TODAY`.
EXPECTED_DUE = {
    "K-DST-FX-01",
    "K-DST-FX-02",
    "K-FX-04",
    "K-FXC-01",
    "K-LAD-FX-01",
    "V-S01",
}


#: The window these fixture passes run with. It is a property of the fixtures —
#: chosen so that `K-FX-04` sits inside it and `K-FX-03` does not — and not a
#: product default. There is deliberately no default window in the code under
#: test; see `src/knowledge/maintenance.py`.
FIXTURE_WARNING_DAYS: int = 14


def pass_over(
    ledger: Path,
    *,
    today: date = TODAY,
    warning_days: int = FIXTURE_WARNING_DAYS,
) -> MaintenanceReport:
    """One scheduled pass of the job over the fixture register."""

    return run_maintenance(
        REGISTER,
        client_rule_paths=CLIENT_RULES,
        today=today,
        warning_days=warning_days,
        ledger_root=ledger,
    )


def queue_files(ledger: Path) -> list[Path]:
    return sorted((ledger / QUEUE_DIRECTORY).glob("*.json"))


def queued_for(ledger: Path, record_id: str) -> list[Path]:
    return [path for path in queue_files(ledger) if record_id in path.name]


def item_of(report: MaintenanceReport, record_id: str) -> ExpiryReviewItem:
    for item in report.due:
        if item.record_id == record_id:
            return item
    raise AssertionError(f"{record_id} is not among the records due for review")


def tree_digest(directory: Path) -> str:
    """A digest over every file of a directory, content and name."""

    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(directory)).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


# ----------------------------------------------------------------------
# The acceptance evidence: one item per record per expiry (§5.2)
# ----------------------------------------------------------------------


def test_an_expired_record_makes_exactly_one_queue_item_across_repeated_runs(
    tmp_path,
):
    """The issue's first acceptance line, and the reason the id is derived."""

    first = pass_over(tmp_path)
    assert "K-DST-FX-01" in {item.record_id for item in first.due}
    assert len(queued_for(tmp_path, "K-DST-FX-01")) == 1

    after_first = queue_files(tmp_path)
    second = pass_over(tmp_path)
    third = pass_over(tmp_path, today=TODAY + timedelta(days=9))

    # The later passes still see the expiry — it is unanswered, so it is still
    # due — and they add nothing to the queue.
    assert "K-DST-FX-01" in {item.record_id for item in second.due}
    assert "K-DST-FX-01" in {item.record_id for item in third.due}
    assert second.written == ()
    assert third.written == ()
    assert second.already_queued == tuple(item.item_id for item in second.due)
    assert queue_files(tmp_path) == after_first


def test_the_item_a_second_pass_did_not_write_is_the_one_the_first_wrote(tmp_path):
    """Idempotency is "nothing happened", not "it was rewritten the same"."""

    pass_over(tmp_path)
    (path,) = queued_for(tmp_path, "K-DST-FX-01")
    written = json.loads(path.read_text(encoding="utf-8"))

    pass_over(tmp_path, today=TODAY + timedelta(days=30))

    assert json.loads(path.read_text(encoding="utf-8")) == written
    assert written["raised_on"] == TODAY.isoformat()


def test_a_review_the_keeper_moved_forward_is_a_new_expiry_and_a_new_item(
    tmp_path,
):
    """The other half of one-per-expiry: a re-reviewed record comes back.

    The keeper answers the item by re-reviewing the record and setting the next
    `review_by`. Nothing records that the question was answered, and nothing
    needs to: the record is not due again until its new date, and when it is,
    it is a different expiry and therefore a different item.
    """

    register = tmp_path / "register"
    shutil.copytree(REGISTER, register)
    ledger = tmp_path / "ledger"

    run_maintenance(
        register, today=TODAY, warning_days=FIXTURE_WARNING_DAYS,
        ledger_root=ledger,
    )
    assert len(queued_for(ledger, "K-DST-FX-01")) == 1

    record = register / "records" / "dst" / "K-DST-FX-01.md"
    record.write_text(
        record.read_text(encoding="utf-8").replace(
            "review_by: 2026-03-01", "review_by: 2027-03-01"
        ),
        encoding="utf-8",
    )

    answered = run_maintenance(
        register, today=TODAY, warning_days=FIXTURE_WARNING_DAYS,
        ledger_root=ledger,
    )
    assert "K-DST-FX-01" not in {item.record_id for item in answered.due}

    run_maintenance(
        register, today=date(2027, 3, 2), warning_days=FIXTURE_WARNING_DAYS,
        ledger_root=ledger,
    )
    assert len(queued_for(ledger, "K-DST-FX-01")) == 2


# ----------------------------------------------------------------------
# The acceptance evidence: no dependency on publications (§5.2)
# ----------------------------------------------------------------------


def test_the_job_needs_only_a_register_and_a_date(tmp_path):
    """Nothing published, no run, no workspace — and the reviews still happen.

    The job is called with a register directory, a date and an empty ledger.
    There is no run summary in it, no fingerprint, no publication observation
    and no marker anywhere, which is the state a month with nothing published
    leaves behind. Expiry review continues through it.
    """

    report = pass_over(tmp_path)

    assert {item.record_id for item in report.due} == EXPECTED_DUE
    assert len(report.written) == len(EXPECTED_DUE)
    assert sorted(path.parent.name for path in report.written) == [
        QUEUE_DIRECTORY
    ] * len(EXPECTED_DUE)
    # The ledger holds queue items and nothing else: the job wrote no run
    # record, and read none.
    assert {path.name for path in tmp_path.iterdir()} == {QUEUE_DIRECTORY}


@pytest.mark.parametrize(
    "module",
    ["src/knowledge/maintenance.py", "src/run/knowledge_queue.py"],
)
def test_neither_module_the_job_is_built_from_names_a_run_or_a_publication(
    module: str,
):
    """A different claim from the test above, and a stricter one.

    That test proves the job runs when nothing was published; this proves it
    cannot start reading one. Both modules the job is made of are checked, so
    the dependency cannot arrive through the record on the way to the ledger —
    which is how "expiry review continues even when nothing is published"
    stops being true without anybody deciding that it should.
    """

    source = (_REPO_ROOT / module).read_text(encoding="utf-8")
    for forbidden in (
        "src.publishing",
        "publication_markers",
        "published_content_index",
        "src.run.run_workspace",
        "src.run.run_summary",
        "src.run.run_manifest",
    ):
        assert forbidden not in source


def test_the_job_changes_no_knowledge_status(tmp_path):
    """§5.2's scope line, and I-02: the keeper decides, the job asks."""

    before = tree_digest(REGISTER)
    pass_over(tmp_path)
    assert tree_digest(REGISTER) == before


# ----------------------------------------------------------------------
# What the item says about the record (§5)
# ----------------------------------------------------------------------


def test_an_expired_candidate_is_recorded_as_the_weak_candidate_it_became(
    tmp_path,
):
    report = pass_over(tmp_path)
    item = item_of(report, "K-DST-FX-01")

    assert item.expired is True
    assert item.file_status is KnowledgeStatus.CANDIDATE
    assert item.effective_status is KnowledgeStatus.WEAK_CANDIDATE
    assert item.tier is KnowledgeTier.PLATFORM_RANKING
    assert item.record_version == 2
    assert item.source is RegisterSource.REGISTER
    assert item.record_kind is RegisterRecordKind.KNOWLEDGE


def test_an_expired_hard_platform_rule_is_still_an_approved_rule(tmp_path):
    """§5: dropping a hard rule nobody re-checked is the unsafe direction."""

    item = item_of(pass_over(tmp_path), "K-DST-FX-02")

    assert item.expired is True
    assert item.file_status is KnowledgeStatus.APPROVED_RULE
    assert item.effective_status is KnowledgeStatus.APPROVED_RULE
    assert item.tier is KnowledgeTier.HARD_PLATFORM_POLICY


def test_an_expired_check_keeps_its_rule_status(tmp_path):
    """§5's check row: a check is flagged, never demoted — and has no tier."""

    item = item_of(pass_over(tmp_path), "V-S01")

    assert item.record_kind is RegisterRecordKind.CHECK
    assert item.expired is True
    assert item.file_status is KnowledgeStatus.CANDIDATE
    assert item.effective_status is KnowledgeStatus.CANDIDATE
    assert item.tier is None


def test_a_record_inside_the_warning_window_is_raised_before_it_expires(tmp_path):
    """The point of the window: the review happens while the record still counts."""

    item = item_of(pass_over(tmp_path), "K-FX-04")

    assert item.review_by > TODAY
    assert item.expired is False
    assert item.effective_status is KnowledgeStatus.CANDIDATE


def test_a_record_whose_review_is_months_away_is_not_asked_about(tmp_path):
    report = pass_over(tmp_path)
    assert "K-FX-03" not in {item.record_id for item in report.due}


def test_a_retired_record_is_not_asked_about(tmp_path):
    """§2.3: it is kept for traceability, and the keeper already closed it."""

    report = pass_over(tmp_path)
    assert "K-FX-05" not in {item.record_id for item in report.due}


def test_a_client_rule_is_scanned_where_it_lives(tmp_path):
    """§1: client rules stay in the client folder, and §5.2 scans them too."""

    item = item_of(pass_over(tmp_path), "K-FXC-01")

    assert item.source is RegisterSource.CLIENT
    assert item.tier is KnowledgeTier.APPROVED_CLIENT_RULE


def test_the_job_refuses_to_choose_a_warning_window_for_the_caller():
    """§5.2 fixes no duration, so neither may the code (#297 escalation rule).

    The window is a required argument everywhere it is asked for. A default
    here would settle an open product question on the owner's behalf, which is
    exactly what the first review of this work found and rejected, so the
    regression is that calling without one fails rather than picking a number.
    """

    with pytest.raises(TypeError):
        scan(REGISTER, today=TODAY)  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        run_maintenance(REGISTER, today=TODAY)  # type: ignore[call-arg]

    assert not hasattr(maintenance, "DEFAULT_WARNING_DAYS")


def test_the_window_decides_what_is_due():
    """The warning window is a parameter, and it is the one doing the deciding."""

    narrow = scan(
        REGISTER, client_rule_paths=CLIENT_RULES, today=TODAY, warning_days=0
    )
    wide = scan(
        REGISTER, client_rule_paths=CLIENT_RULES, today=TODAY, warning_days=200
    )

    assert "K-FX-04" not in {item.record_id for item in narrow.due}
    assert "K-FX-03" in {item.record_id for item in wide.due}
    with pytest.raises(MaintenanceError):
        scan(REGISTER, today=TODAY, warning_days=-1)


# ----------------------------------------------------------------------
# A file it cannot read
# ----------------------------------------------------------------------


def test_a_file_it_cannot_read_is_reported_and_the_scan_goes_on(tmp_path):
    """One broken record must not silence the review of every sound one."""

    report = pass_over(tmp_path)

    assert len(report.unreadable) == 1
    assert "K-FX-BROKEN.md" in report.unreadable[0]
    assert report.clean is False
    assert {item.record_id for item in report.due} == EXPECTED_DUE


def test_the_shipped_register_is_one_the_job_can_read():
    """The fixture proves the rules; this proves they are about real files.

    Every record and check the repository ships, and Never Blank's own rules in
    the client folder. The pass is run for a date past every `review_by` in the
    tree, so the job does not merely parse them — it builds an item for each,
    against their real ids, statuses and tiers.

    What is due on any particular day is the calendar's business and is not
    asserted here.
    """

    report = scan(
        _REPO_ROOT / "knowledge",
        client_rule_paths=client_record_paths(_REPO_ROOT / "clients"),
        today=date(2030, 1, 1),
        warning_days=0,
    )

    assert report.unreadable == ()
    assert len(report.due) > 0


def test_every_file_of_the_register_and_the_client_folder_is_scanned():
    files = register_files(REGISTER, client_rule_paths=CLIENT_RULES)

    assert {entry.path.name for entry in files} == {
        "K-DST-FX-01.md",
        "K-DST-FX-02.md",
        "K-FX-03.md",
        "K-FX-04.md",
        "K-FX-05.md",
        "K-FX-BROKEN.md",
        "default.md",
        "V-S01.md",
        "K-FXC-01.md",
    }
    assert {
        entry.record_kind for entry in files if entry.path.name == "V-S01.md"
    } == {RegisterRecordKind.CHECK}


# ----------------------------------------------------------------------
# The record itself
# ----------------------------------------------------------------------


def _item(**overrides: Any) -> ExpiryReviewItem:
    fields: dict[str, Any] = {
        "item_id": ExpiryReviewItem.identity_for("K-DST-FX-01", date(2026, 3, 1)),
        "raised_on": TODAY,
        "record_id": "K-DST-FX-01",
        "record_version": 2,
        "record_kind": RegisterRecordKind.KNOWLEDGE,
        "source": RegisterSource.REGISTER,
        "review_by": date(2026, 3, 1),
        "file_status": KnowledgeStatus.CANDIDATE,
        "effective_status": KnowledgeStatus.WEAK_CANDIDATE,
        "tier": KnowledgeTier.PLATFORM_RANKING,
        "expired": True,
    }
    fields.update(overrides)
    return ExpiryReviewItem(**fields)


def test_an_item_goes_to_the_queue_of_the_ledger(tmp_path):
    path = write_queue_item(_item(), root=tmp_path)

    assert path.parent == tmp_path / QUEUE_DIRECTORY
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["kind"] == QueueItemKind.EXPIRY_REVIEW.value
    assert ExpiryReviewItem.from_dict(stored) == _item()

    with pytest.raises(ArtifactCollisionError):
        write_queue_item(_item(), root=tmp_path)


def test_the_queue_path_is_not_ignored_by_this_repository():
    """`data/*` is ignored wholesale; the keeper's queue must not be.

    The same condition `test_293_ledger` states for the run records, for the
    same reason: an item git refuses to add is a question the keeper never
    sees, and `commit_ledger` would report `nothing_staged` for every pass.
    """

    name = "KQ-expiry_review-K-X-01-2026-01-01.json"
    checked = subprocess.run(
        ["git", "check-ignore", "-q", f"data/editorial/{QUEUE_DIRECTORY}/{name}"],
        capture_output=True,
        check=False,
    )

    # git check-ignore: 0 = ignored, 1 = not ignored.
    assert checked.returncode == 1


@pytest.mark.parametrize(
    "overrides",
    [
        # An id that is not the one this record and this expiry make: the
        # derived id is what keeps one expiry to one item.
        {"item_id": "KQ-expiry_review-K-DST-FX-01-2026-03-02"},
        # Expiry is the comparison of two dates, not an opinion about it.
        {"expired": False},
        # A status the loader computes and a file never holds.
        {
            "file_status": KnowledgeStatus.WEAK_CANDIDATE,
            "effective_status": KnowledgeStatus.WEAK_CANDIDATE,
        },
        # A record the keeper already closed.
        {
            "file_status": KnowledgeStatus.RETIRED,
            "effective_status": KnowledgeStatus.RETIRED,
        },
        # §5 demotes an expired candidate and leaves every other status alone.
        {
            "file_status": KnowledgeStatus.APPROVED_RULE,
            "effective_status": KnowledgeStatus.CANDIDATE,
        },
        # And the one demotion it makes is from `descriptive` or `candidate`:
        # an expired rule recorded as a weak candidate tells the keeper their
        # rule stopped applying, which is the reading §5 exists to refuse.
        {
            "file_status": KnowledgeStatus.APPROVED_RULE,
            "effective_status": KnowledgeStatus.WEAK_CANDIDATE,
        },
        # A check is flagged and never demoted, whatever its rule status (§3).
        {"record_kind": RegisterRecordKind.CHECK, "tier": None},
        # A check has a rule status and no tier; a record has a tier.
        {"record_kind": RegisterRecordKind.CHECK},
        {"tier": None},
        # One kind, one producer (§3.2).
        {"kind": QueueItemKind.OBSERVATION},
    ],
)
def test_the_item_refuses_what_the_register_cannot_have_said(
    overrides: dict[str, Any],
):
    with pytest.raises(ValueError):
        _item(**overrides)


def test_an_item_reloads_strictly_or_says_what_is_wrong():
    stored = _item().to_dict()
    stored["record_version"] = 0

    with pytest.raises(KnowledgeQueueError) as refused:
        ExpiryReviewItem.from_dict(stored)
    assert "record_version" in str(refused.value)
