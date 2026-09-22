"""NB-00c: run evidence is kept for 90 days because the workflow says so.

The repository default is 90 days today (``days: 90``,
``maximum_allowed_days: 90``, read from the Actions API on 2026-09-22). A
default is a setting a person can change, and the evidence a published run
leaves behind — the generated package, the run namespace, the selection audit
— is what a later investigation has to read. So every upload states its own
retention rather than inheriting one.

These are the two that did not (#289 audit): the ``generated-*`` package in
``monday_publish.yml`` and in ``research_generate_and_publish.yml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_WORKFLOWS = Path(".github/workflows")

#: 90 is the maximum the repository allows, so it is also the longest an
#: artifact can be kept: asking for more would fail the upload.
_REQUIRED_RETENTION = 90


def _upload_steps(workflow: Path) -> list[dict]:
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    return [
        step
        for job in (data.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]


def _artifact_name(step: dict) -> str:
    return str((step.get("with") or {}).get("name", ""))


def _is_generated_package(step: dict) -> bool:
    """The run-evidence package, identified by what it uploads.

    By path, not by name: ``generate_image.yml`` uploads
    ``generated-image-<run>`` from ``data/images/`` and deliberately keeps it
    for 30 days. That is a manual utility's output, not the evidence a
    published run leaves behind, and matching on the ``generated-`` prefix
    would drag it in.
    """

    path = str((step.get("with") or {}).get("path", ""))
    return "reports/content_packages" in path and _artifact_name(step).startswith(
        "generated-"
    )


@pytest.mark.parametrize(
    "workflow", sorted(p.name for p in _WORKFLOWS.glob("*.yml"))
)
def test_every_generated_package_upload_states_its_retention(workflow):
    """A ``generated-*`` artifact is run evidence, not scratch."""

    for step in _upload_steps(_WORKFLOWS / workflow):
        if not _is_generated_package(step):
            continue
        retention = (step.get("with") or {}).get("retention-days")
        assert retention is not None, (
            f"{workflow}: the generated package upload inherits the repository "
            "default instead of stating its retention"
        )
        assert int(retention) == _REQUIRED_RETENTION, (
            f"{workflow}: generated package retention is {retention}, "
            f"expected {_REQUIRED_RETENTION}"
        )


def test_the_two_workflows_the_audit_named_upload_a_generated_package():
    """The test above passes vacuously if the steps are ever renamed away."""

    for workflow in ("monday_publish.yml", "research_generate_and_publish.yml"):
        steps = _upload_steps(_WORKFLOWS / workflow)
        assert any(_is_generated_package(step) for step in steps), (
            f"{workflow} no longer uploads a generated package: the retention "
            "rule above would stop checking anything"
        )


@pytest.mark.parametrize(
    "workflow", sorted(p.name for p in _WORKFLOWS.glob("*.yml"))
)
def test_no_upload_asks_for_more_than_the_repository_allows(workflow):
    """90 is ``maximum_allowed_days``; asking for more fails the upload."""

    for step in _upload_steps(_WORKFLOWS / workflow):
        retention = (step.get("with") or {}).get("retention-days")
        if retention is None:
            continue
        assert int(retention) <= _REQUIRED_RETENTION, (
            f"{workflow}: {_artifact_name(step)!r} asks for {retention} days, "
            f"more than the repository allows ({_REQUIRED_RETENTION})"
        )
