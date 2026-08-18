"""Discovery results must survive a failure in optional Stage 11 publishing.

`run_daily_research.py` is explicitly *not* a Release 1 canonical run — its own
docstring says so and names `generate_and_publish.py` as the canonical entry
point. Yet a failure in its optional publishing stage used to abandon the whole
step, so the workflow skipped the commit and discarded signals that had already
been discovered and written to disk. Fresh signals stopped reaching `main`.

These tests hold the boundary: successful discovery persists, optional
publishing fails loudly without erasing it, and a genuine discovery failure
still persists nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "research" / "run_daily_research.py"
WORKFLOW = ROOT / ".github" / "workflows" / "daily_signal_research.yml"


@pytest.fixture(scope="module")
def source() -> str:
    return SCRIPT.read_text()


@pytest.fixture(scope="module")
def commit_step() -> dict:
    spec = yaml.safe_load(WORKFLOW.read_text())
    steps = list(spec["jobs"].values())[0]["steps"]
    for step in steps:
        if step.get("name") == "Commit research data":
            return step
    raise AssertionError("the research workflow no longer commits research data")


# ── 1–2. discovery survives an optional publishing failure ───────────────────

def test_publishing_failure_no_longer_aborts_the_run(source: str):
    """Stage 11 records its failure instead of raising mid-pipeline."""

    assert 'summary["publish_failures"] = failures' in source
    assert 'raise RuntimeError("Live publishing blocked/failed' not in source


def test_the_failure_is_deferred_not_hidden(source: str):
    """The run must still fail — after its evidence is on disk, not before."""

    tail = source.split('if __name__ == "__main__":', 1)[1]
    assert "json.dump(result, f, indent=2)" in tail
    exit_at = tail.index("sys.exit(1)")
    persist_at = tail.index("json.dump(result, f, indent=2)")
    assert persist_at < exit_at, "the run must persist before it exits non-zero"
    assert 'result.get("publish_failures")' in tail


def test_later_stages_are_no_longer_collateral_damage(source: str):
    """Sheets sync and archive ran after Stage 11 and were skipped by the raise."""

    body = source.split("def run(", 1)[1].split("def _print_summary", 1)[0]
    assert body.index("Stage 11") < body.index("Stage 7: Sheets Sync")
    assert body.index("Stage 11") < body.index("Stage 9: Archive")


def test_persistence_is_not_gated_on_step_success(commit_step: dict):
    assert commit_step["if"] == "always()"


# ── 3. a failed discovery still persists nothing ─────────────────────────────

def test_a_failed_discovery_commits_nothing(commit_step: dict):
    """always() is guarded, not bare — the distinction the fix rests on.

    A discovery failure raises before the summary artifact is written, so the
    guard finds no report and commits nothing. Without it, `always()` would
    commit partial output from a run whose research stage had failed.
    """

    run = commit_step["run"]
    assert 'REPORT="reports/research_$(date -u +%Y-%m-%d).json"' in run
    assert 'if [ ! -f "$REPORT" ]; then' in run
    guard_at = run.index("$REPORT")
    commit_at = run.index("git add")
    assert guard_at < commit_at, "the guard must precede any staging"


def test_the_summary_artifact_is_written_only_after_run_returns(source: str):
    """That ordering is what makes the artifact a truthful discovery marker."""

    tree = ast.parse(source)
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body
    )
    tail = source.split('if __name__ == "__main__":', 1)[1]
    assert tail.index("result = run()") < tail.index("report_path = Path(")


# ── 4–6. the canonical boundary is unchanged ─────────────────────────────────

def test_stage_11_remains_disabled_by_default(source: str):
    assert 'os.environ.get("NB_RESEARCH_PUBLISH_ENABLED", "false")' in source


def test_the_script_still_declares_itself_non_canonical(source: str):
    assert "NOT a Release 1 canonical run" in source
    assert "scripts/generate_and_publish.py" in source


def test_discovery_never_marks_a_signal_published(source: str):
    """Consumption belongs to the canonical publish path, not to discovery."""

    assert "published_signal_ids" not in source
    workflow = WORKFLOW.read_text()
    assert "published_signal_ids" not in workflow


def test_the_canonical_publish_path_is_untouched():
    canonical = (ROOT / ".github" / "workflows" / "research_generate_and_publish.yml").read_text()
    assert "scripts/generate_and_publish.py --signal-id" in canonical
    assert "data/research/published_signal_ids.txt" in canonical
