"""Which workflows hold the canonical publishing contract, derived not listed.

#326. The legacy `research_generate_and_publish.yml` carried a set of real
safety invariants — evidence preservation, credential sourcing, the order of
bookkeeping — pinned to that one file. Deleting the file would have stranded
them, so they are re-homed here, onto the thing that actually owns them: **any
workflow that runs the canonical entrypoint and can publish.**

Derived from the workflows rather than listed, for one reason: a listed set is
a thing somebody has to remember to extend. The two holes this repository has
already paid for — #229's Telegram path and #231's Stage 11 — were both "a
publishing route nobody added to the list". A new publishing workflow now
inherits every invariant in :mod:`tests.test_story21_hosted_evidence` and
:mod:`tests.test_canonical_publish_credentials` on the day it is written.

Membership is one question: does the workflow invoke
``scripts/generate_and_publish.py``? That script is the canonical entrypoint —
the only path to a publication — so invoking it is what makes a workflow able
to publish, and nothing else here infers it from a name or a schedule.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

#: The canonical entrypoint. A workflow that runs it can publish.
ENTRYPOINT = "scripts/generate_and_publish.py"


def publishing_workflows() -> tuple[str, ...]:
    """Every workflow that invokes the canonical entrypoint, sorted.

    Empty would mean the repository lost its publishing path entirely, which is
    not a state any test here should pass in — so it is refused rather than
    returned, the same anti-vacuous posture ``PASS_THROUGH_MARKER == 0`` holds
    for the Golden Engine.
    """

    found = tuple(
        sorted(
            path.name
            for path in WORKFLOWS.glob("*.yml")
            if ENTRYPOINT in path.read_text(encoding="utf-8")
        )
    )
    if not found:
        raise AssertionError(
            f"no workflow invokes {ENTRYPOINT}; either the canonical entrypoint "
            "moved and this module is now blind, or the repository has no "
            "publishing path at all. Both are worth failing on"
        )
    return found


def job_steps(workflow: str) -> list[dict[str, Any]]:
    """The steps of ``workflow``'s single job, in order."""

    spec = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    jobs = spec["jobs"]
    assert len(jobs) == 1, f"{workflow} has {len(jobs)} jobs; this reader assumes one"
    return list(next(iter(jobs.values()))["steps"])


def step_index(steps: list[dict[str, Any]], predicate) -> int:
    """Where the one step matching ``predicate`` is, or -1."""

    matches = [index for index, step in enumerate(steps) if predicate(step)]
    assert len(matches) <= 1, f"{len(matches)} steps match; expected at most one"
    return matches[0] if matches else -1


def named(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """The step called ``name``. Absent is a failure, never a skip."""

    index = step_index(steps, lambda step: step.get("name") == name)
    assert index >= 0, f"no step named {name!r}; the invariant it holds is unguarded"
    return steps[index]


def entrypoint_step(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The step that runs the canonical entrypoint."""

    index = step_index(steps, lambda step: ENTRYPOINT in str(step.get("run", "")))
    assert index >= 0, "no step runs the canonical entrypoint"
    return steps[index]
