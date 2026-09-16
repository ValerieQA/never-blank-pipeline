#!/usr/bin/env python3
"""Issue #247: the Wednesday Meta recovery is single-shot.

A live recovery run may publish only if no earlier live run of the recovery
workflow ever reached its publish step. A publish call whose response was lost
can still have created a post, so no earlier attempt — finished, failed,
cancelled or lost with its runner — is ever treated as safe to repeat, and no
result record is trusted to prove otherwise.

The decision is taken from GitHub's own run and job records, not from uploaded
artifacts, so a run whose artifact never uploaded still counts:

* every run of the recovery workflow except the current one is listed;
* a run is live when its run name says so (the workflow sets ``run-name``);
* a live run blocks when its "Publish saved payloads" step exists and was not
  skipped — queued, in progress, completed or cancelled all block;
* any API failure, an unexpected response shape, or a run with no readable
  run name blocks too.

Exit 0 means "no earlier live publish step ever ran". Anything else means stop.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Callable

WORKFLOW_FILE = "recovery_wednesday_meta_247.yml"
PUBLISH_STEP = "Publish saved payloads"
LIVE_MARKER = "(live)"
DRY_MARKER = "(dry_run)"


class LedgerError(RuntimeError):
    """The history could not be established; publishing must not proceed."""


def gh_api(path: str) -> list | dict:
    """``gh api --paginate --slurp``: every page, as one JSON array of pages."""
    out = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", path],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise LedgerError(f"gh api {path} failed: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def _pages(payload, key: str) -> list[dict]:
    if not isinstance(payload, list):
        raise LedgerError(f"expected a list of pages for {key}")
    items: list[dict] = []
    for page in payload:
        if not isinstance(page, dict) or not isinstance(page.get(key), list):
            raise LedgerError(f"unexpected page shape for {key}")
        items.extend(page[key])
    return items


def blocking_runs(repo: str, current_run_id: str,
                  fetch: Callable[[str], list | dict] = gh_api) -> list[str]:
    """Earlier runs that are live, or unreadable, and reached publication."""
    runs = _pages(
        fetch(f"repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=100"),
        "workflow_runs",
    )
    blocking: list[str] = []
    for run in runs:
        run_id = str(run.get("id", ""))
        if not run_id:
            raise LedgerError("a recovery run has no id")
        if run_id == str(current_run_id):
            continue
        title = run.get("display_title") or run.get("name") or ""
        if DRY_MARKER in title and LIVE_MARKER not in title:
            continue
        if LIVE_MARKER not in title:
            # Neither marker: the run cannot be classified, so it counts.
            blocking.append(f"{run_id} (unclassifiable run name {title!r})")
            continue
        jobs = _pages(fetch(f"repos/{repo}/actions/runs/{run_id}/jobs?filter=all&per_page=100"), "jobs")
        for job in jobs:
            steps = job.get("steps")
            if not isinstance(steps, list):
                raise LedgerError(f"run {run_id} job has no readable steps")
            for step in steps:
                if step.get("name") != PUBLISH_STEP:
                    continue
                if step.get("conclusion") == "skipped":
                    continue
                blocking.append(
                    f"{run_id} (publish step status={step.get('status')} "
                    f"conclusion={step.get('conclusion')})"
                )
    return blocking


def main(argv: list[str] | None = None, *,
         fetch: Callable[[str], list | dict] = gh_api) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--current-run-id", required=True)
    args = parser.parse_args(argv)

    try:
        blocking = blocking_runs(args.repo, args.current_run_id, fetch)
    except (LedgerError, ValueError, TypeError, AttributeError) as exc:
        print(f"ERROR: cannot establish recovery history — refusing to publish: {exc}")
        return 2
    if blocking:
        print("ERROR: an earlier live recovery already reached publication — "
              f"refusing to publish again: {blocking}")
        return 1
    print("No earlier live recovery reached publication.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
