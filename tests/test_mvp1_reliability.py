"""What run 37715852447 cost, turned into tests (#393).

That cycle published to four surfaces, failed LinkedIn, persisted no durable
evidence of any of it, and exited 0. Four separate deficits, each covered here:

* ``_swap_image`` enumerated its fields and so dropped the five it did not
  name — including the target identity LinkedIn requires;
* ``record_marker`` writes locally and never pushes, so persistence is the
  workflow's duty and this lane was the one publishing workflow that never
  called the script written for it (#287);
* nothing distinguished *this destination published* from *the cycle is
  complete*, so a partial run had nowhere safe to stop;
* the entry returned 0 whatever its own table said.

No test here makes a provider call. The git doubles are local bare
repositories: the persistence seam is git, so proving it needs git and nothing
else.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from src.publishing.base import DraftPackage
from src.publishing.publication_markers import PUBLICATION_UNCONFIRMED

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "never_blank_mvp1.yml"
PERSIST = ROOT / "scripts" / "ci" / "persist_publication_markers.sh"
STORE = "data/editorial/publication_markers"

PERSIST_STEP = "Live: persist publication markers"
COMPLETE_STEP = "Live: mark the cycle complete"
LIVE_STEP = "Live: generate and publish"


# ───────────────────────────── shared fixtures ──────────────────────────────


def _steps() -> list[dict]:
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return spec["jobs"][next(iter(spec["jobs"]))]["steps"]


def _named(name: str) -> dict:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r}")


def _entry_module():
    """The live entry, imported rather than run, so exit codes are testable."""

    spec = importlib.util.spec_from_file_location(
        "mvp1_entry", ROOT / "scripts" / "mvp1_publish_signal.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _full_draft() -> DraftPackage:
    """Every field populated and distinguishable, so a dropped one is visible."""

    return DraftPackage(
        draft_dir=Path("/tmp/draft"),
        blog_title="title",
        blog_body="blog body",
        blog_meta={"title": "title", "wix_slug": "slug"},
        linkedin_text="linkedin text",
        instagram_text="instagram caption",
        facebook_text="facebook text",
        threads_sequence=["one", "two"],
        telegram_text="telegram text",
        image_url="https://example.test/blog.png",
        platform_image_urls={"instagram": "https://example.test/ig.png"},
        wix_slug="slug",
        wix_category_id="cat-1",
        wix_tags=["tag-1"],
        wix_site_id="site-1",
        wix_owner_member_id="owner-1",
        linkedin_account_id="acct-1",
        run_id="run-1",
        metadata={"signal_id": "sig"},
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )


def _clone_with_remote(tmp_path: Path, *, depth: int = 1) -> tuple[Path, Path]:
    """A bare remote and a shallow clone of it — the runner's actual shape.

    ``actions/checkout`` fetches at depth 1 and #398 deliberately left it
    there, so the double is shallow on purpose: if the persistence seam needed
    full history, this is where that would show.
    """

    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))

    seed = tmp_path / "seed"
    _git(tmp_path, "clone", str(remote), str(seed))
    (seed / STORE).mkdir(parents=True)
    (seed / STORE / ".gitkeep").write_text("")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=seed", "-c", "user.email=s@e.test",
         "commit", "-m", "seed")
    _git(seed, "push", "origin", "main")

    work = tmp_path / "work"
    _git(tmp_path, "clone", "--depth", str(depth), str(remote), str(work))
    return remote, work


def _run_persist(work: Path, **env: str) -> subprocess.CompletedProcess:
    environment = {
        **os.environ,
        "GITHUB_RUN_ID": "test-run",
        "HOME": str(work),
        **env,
    }
    return subprocess.run(
        ["bash", str(PERSIST)],
        cwd=work, capture_output=True, text=True, env=environment,
    )


# ══════════════════════════ 1 · the copy that dropped five ══════════════════


def test_swapping_an_image_changes_the_image_and_nothing_else() -> None:
    """Derived from the dataclass, so a field added later is covered too.

    The defect was never about three particular names — it was that a copy
    enumerating fields silently loses whichever it does not mention.
    """

    from scripts.research.publish_packages import _swap_image

    draft = _full_draft()
    swapped = _swap_image(draft, "https://example.test/linkedin.png")

    assert swapped.image_url == "https://example.test/linkedin.png"
    for field in dataclasses.fields(DraftPackage):
        if field.name == "image_url":
            continue
        assert getattr(swapped, field.name) == getattr(draft, field.name), field.name


def test_swapping_an_image_preserves_the_target_identity() -> None:
    """The three fields whose loss failed LinkedIn after four surfaces published."""

    from scripts.research.publish_packages import _swap_image

    swapped = _swap_image(_full_draft(), "https://example.test/x.png")

    assert swapped.wix_site_id == "site-1"
    assert swapped.wix_owner_member_id == "owner-1"
    assert swapped.linkedin_account_id == "acct-1"


def test_swapping_an_image_preserves_run_id_metadata_and_platform_images() -> None:
    """The other two casualties, less visible and equally dropped."""

    from scripts.research.publish_packages import _swap_image

    swapped = _swap_image(_full_draft(), "https://example.test/x.png")

    assert swapped.run_id == "run-1"
    assert swapped.metadata == {"signal_id": "sig"}
    assert swapped.platform_image_urls == {"instagram": "https://example.test/ig.png"}


def test_swapping_an_image_preserves_every_text() -> None:
    """A digest is computed over these, so a lost text is a lost marker key."""

    from scripts.research.publish_packages import _swap_image

    draft = _full_draft()
    swapped = _swap_image(draft, "https://example.test/x.png")

    assert swapped.blog_body == draft.blog_body
    assert swapped.linkedin_text == draft.linkedin_text
    assert swapped.facebook_text == draft.facebook_text
    assert swapped.instagram_text == draft.instagram_text
    assert swapped.telegram_text == draft.telegram_text
    assert swapped.threads_sequence == draft.threads_sequence


def test_the_copy_no_longer_enumerates_fields() -> None:
    """The mechanism, not the symptom — asserted on executable source.

    Restoring the field list would pass every test above while reopening the
    defect for the next field somebody adds.
    """

    import ast
    import inspect

    from scripts.research.publish_packages import _swap_image

    tree = ast.parse(inspect.getsource(_swap_image).strip())
    body = tree.body[0].body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
    ):
        body.pop(0)
    code = ast.unparse(tree)

    assert "DraftPackage(" not in code
    assert "dataclasses.replace" in code


# ══════════════════ 2 · persistence wired, and compatible ═══════════════════


def test_the_lane_persists_markers_under_always() -> None:
    """Not `success()`: the marker of a destination that DID publish is
    exactly what has to survive the failure of a later one."""

    step = _named(PERSIST_STEP)

    assert step["if"].startswith("always()")
    assert "persist_publication_markers.sh" in step["run"]


def test_markers_are_persisted_for_live_runs_only() -> None:
    """An inspect run makes no call; evidence of one would suppress a real
    publication later."""

    step = _named(PERSIST_STEP)

    assert "(inputs.mode || 'inspect') == 'live'" in step["if"]
    assert step["env"]["DRY_RUN"] == "${{ (inputs.mode || 'inspect') != 'live' }}"


def test_the_persist_script_exists_and_is_executable_as_invoked() -> None:
    assert PERSIST.is_file()
    assert "bash" in _named(PERSIST_STEP)["run"]


def test_markers_are_persisted_before_the_cycle_is_marked_complete() -> None:
    """Evidence outlives bookkeeping, so the order is part of the contract."""

    names = [s.get("name") for s in _steps()]

    assert names.index(PERSIST_STEP) > names.index(LIVE_STEP)
    assert names.index(PERSIST_STEP) < names.index(COMPLETE_STEP)


def test_persisting_commits_only_the_store_and_pushes(tmp_path: Path) -> None:
    """The happy path on a shallow clone, with a claim commit already pushed.

    Mirrors the runner: `GitSharedClaim` has pushed its intents from this very
    workspace during the run, so HEAD is a claim commit and the remote agrees.
    """

    remote, work = _clone_with_remote(tmp_path)

    # A GitSharedClaim intent, committed and pushed mid-run exactly as the
    # real claim does.
    intent = work / STORE / "never_blank" / "wix"
    intent.mkdir(parents=True)
    (intent / "sig-abc.intent.json").write_text('{"run_id": "test-run"}')
    _git(work, "add", "--", STORE)
    _git(work, "-c", "user.name=claim", "-c", "user.email=c@e.test",
         "commit", "-m", "publication claim [skip ci]", "--", STORE)
    _git(work, "push", "origin", "HEAD:main")

    # The completion marker, written locally by record_marker and never pushed.
    (intent / "sig-abc.json").write_text('{"external_id": "post-1"}')
    # An unrelated dirty file: the index write, which this step must not touch.
    (work / "strategy").mkdir()
    (work / "strategy" / "published_content_index.jsonl").write_text("{}\n")

    before = _git(work, "rev-parse", "HEAD").stdout.strip()
    result = _run_persist(work)

    assert result.returncode == 0, result.stdout + result.stderr
    after = _git(work, "rev-parse", "HEAD").stdout.strip()
    assert after != before

    touched = _git(work, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert touched == [f"{STORE}/never_blank/wix/sig-abc.json"]

    pushed = _git(work, "ls-remote", str(remote), "main").stdout.split()[0]
    assert pushed == after

    # The index is still dirty and uncommitted — this step is evidence only.
    # `-uall` so git names the file rather than collapsing it to its directory.
    assert "published_content_index.jsonl" in _git(
        work, "status", "--porcelain", "-uall"
    ).stdout


def test_persisting_recovers_when_the_remote_branch_moved(tmp_path: Path) -> None:
    """Another publisher pushed first: rebase and retry, never force."""

    remote, work = _clone_with_remote(tmp_path)

    other = tmp_path / "other"
    _git(tmp_path, "clone", str(remote), str(other))
    (other / "unrelated.txt").write_text("someone else's commit\n")
    _git(other, "add", "-A")
    _git(other, "-c", "user.name=other", "-c", "user.email=o@e.test",
         "commit", "-m", "unrelated")
    _git(other, "push", "origin", "main")

    marker = work / STORE / "never_blank" / "telegram"
    marker.mkdir(parents=True)
    (marker / "sig-xyz.json").write_text('{"external_id": "57"}')

    result = _run_persist(work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "rebasing onto origin/main" in result.stdout

    head = _git(work, "rev-parse", "HEAD").stdout.strip()
    assert _git(work, "ls-remote", str(remote), "main").stdout.split()[0] == head
    # Nobody else's work was discarded.
    assert "unrelated.txt" in _git(
        work, "ls-tree", "-r", "--name-only", "HEAD"
    ).stdout


def test_a_rehearsal_persists_nothing(tmp_path: Path) -> None:
    _, work = _clone_with_remote(tmp_path)
    marker = work / STORE / "never_blank" / "wix"
    marker.mkdir(parents=True)
    (marker / "sig.json").write_text("{}")

    before = _git(work, "rev-parse", "HEAD").stdout.strip()
    result = _run_persist(work, DRY_RUN="true")

    assert result.returncode == 0
    assert _git(work, "rev-parse", "HEAD").stdout.strip() == before


# ═══════════ 3 · durable bookkeeping that does not overclaim ════════════════


def test_the_cycle_is_marked_complete_only_on_success() -> None:
    """A partial run keeps its markers and keeps the signal eligible."""

    step = _named(COMPLETE_STEP)

    assert step["if"].startswith("success()")
    assert "always()" not in step["if"]


def test_marking_complete_persists_consumption_and_the_index_together() -> None:
    """`append_published_entry` has no duplicate guard, so a committed index
    without a consumed signal would give a later run a second row."""

    run = _named(COMPLETE_STEP)["run"]

    assert "data/research/published_signal_ids.txt" in run
    assert "strategy/published_content_index.jsonl" in run
    assert "git push" in run


def test_marking_complete_cannot_be_driven_by_a_crafted_signal_id() -> None:
    run = _named(COMPLETE_STEP)["run"]

    assert 'case "${SIGNAL_ID}"' in run
    assert "${{ inputs.signal_id }}" not in run


def test_marking_complete_is_live_only() -> None:
    assert "(inputs.mode || 'inspect') == 'live'" in _named(COMPLETE_STEP)["if"]


# ═════════════ 4 · an exit code that means what it says ═════════════════════


def _report(results: dict, unconfirmed: list[str] | None = None) -> list[dict]:
    return [{
        "signal_id": "sig",
        "results": {
            name: {"status": status, "error_message": reason, "url": ""}
            for name, (status, reason) in results.items()
        },
        PUBLICATION_UNCONFIRMED: unconfirmed or [],
    }]


def test_a_partial_cycle_does_not_report_success() -> None:
    """Run 37715852447 exactly: four published, LinkedIn failed, exit 0."""

    entry = _entry_module()
    settled, expected, unresolved = entry.classify(_report({
        "wix":       ("PUBLISHED", ""),
        "facebook":  ("PUBLISHED", ""),
        "instagram": ("PUBLISHED", ""),
        "telegram":  ("PUBLISHED", ""),
        "linkedin":  ("FAILED", "Missing package target identity"),
        "threads":   ("SKIPPED", "outside the Release 1 publishing scope (#227)"),
    }))

    assert sorted(settled) == ["facebook", "instagram", "telegram", "wix"]
    assert expected == ["threads"]
    assert [name for name, _ in unresolved] == ["linkedin"]


def test_a_complete_cycle_reports_success() -> None:
    entry = _entry_module()
    _, _, unresolved = entry.classify(_report({
        "wix":       ("PUBLISHED", ""),
        "linkedin":  ("PUBLISHED", ""),
        "facebook":  ("PUBLISHED", ""),
        "instagram": ("PUBLISHED", ""),
        "telegram":  ("PUBLISHED", ""),
        "threads":   ("SKIPPED", "outside the Release 1 publishing scope (#227)"),
    }))

    assert unresolved == []


def test_a_repeat_of_a_settled_cycle_reports_success() -> None:
    """REUSED is prior canonical proof (#105) — the correct shape of a re-run,
    and it must not be mistaken for a failure."""

    entry = _entry_module()
    settled, _, unresolved = entry.classify(_report({
        name: ("REUSED", "") for name in
        ("wix", "linkedin", "facebook", "instagram", "telegram")
    }))

    assert len(settled) == 5
    assert unresolved == []


def test_a_cycle_that_published_nothing_does_not_report_success() -> None:
    """Run 37704053905: green, six texts written, every destination refused."""

    entry = _entry_module()
    settled, _, unresolved = entry.classify(_report({
        name: ("SKIPPED", "idempotency_authority_unavailable") for name in
        ("wix", "linkedin", "facebook", "instagram", "telegram")
    }))

    assert settled == []
    assert len(unresolved) == 5


def test_an_unconfirmed_publication_does_not_report_success() -> None:
    """The post exists and its marker does not, so the next run will skip it."""

    entry = _entry_module()
    _, _, unresolved = entry.classify(
        _report(
            {name: ("PUBLISHED", "") for name in ("wix", "linkedin")},
            unconfirmed=["never_blank/linkedin/sig-abc"],
        )
    )

    assert [why for _, why in unresolved] == [PUBLICATION_UNCONFIRMED]


@pytest.mark.parametrize("status", ["DRAFT_CREATED", "PROVIDER_DUPLICATE", "", "WAT"])
def test_nothing_but_proof_settles_a_destination(status: str) -> None:
    """A draft is not a live post, and a provider duplicate never says which
    post (#108). An unrecognised status is unresolved by construction."""

    entry = _entry_module()
    settled, _, unresolved = entry.classify(_report({"wix": (status, "")}))

    assert settled == []
    assert len(unresolved) == 1


def test_a_skip_that_is_not_the_scope_refusal_is_unresolved() -> None:
    """SKIPPED alone proves nothing; only the stated scope reason is expected."""

    entry = _entry_module()
    _, expected, unresolved = entry.classify(
        _report({"wix": ("SKIPPED", "something else entirely")})
    )

    assert expected == []
    assert len(unresolved) == 1


def test_the_entry_has_a_distinct_code_for_an_unsettled_cycle() -> None:
    entry = _entry_module()

    assert entry.CYCLE_INCOMPLETE != 0
    assert entry.CYCLE_INCOMPLETE != entry.BAD_INPUT
