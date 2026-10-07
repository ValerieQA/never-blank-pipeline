"""Never Blank MVP 1 — the proven July lane, restored as a manual trigger.

A temporary operational release so Never Blank has something demonstrably
working for prospective clients while the Golden Engine is completed (#393).

What this file holds is the restoration's contract, not the lane's editorial
behaviour: the lane itself is `scripts/generate.py` → `data/drafts/latest/` →
`scripts/publish.py`, unchanged since July, and its behaviour is whatever those
scripts do. What a restoration can get wrong is the wiring around them —
spending by accident, publishing by accident, hiding one destination's failure
behind another's, or quietly reposting to a destination that already succeeded.

Everything here is deterministic: YAML, repository state, and the publishers'
own idempotency types. No provider call, no network, no publication.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "never_blank_mvp1.yml"

EVIDENCE_STEP = "Preserve the MVP 1 cycle"
DRY_STEP = "Dry: validate the lane"
LIVE_STEP = "Live: generate and publish"

#: The six configured destinations, in the order the proven sequence runs them.
DESTINATIONS = ("wix", "linkedin", "facebook", "instagram", "threads", "telegram")


def _spec() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers() -> dict:
    spec = _spec()
    return spec.get("on") or spec[True]


def _steps() -> list[dict]:
    return list(next(iter(_spec()["jobs"].values()))["steps"])


def _named(name: str) -> dict:
    found = [step for step in _steps() if step.get("name") == name]
    assert len(found) == 1, f"expected one {name!r} step; got {len(found)}"
    return found[0]


def _script(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


# ===========================================================================
# 1 · nothing starts, and nothing is paid for, by accident
# ===========================================================================


def test_the_lane_has_no_schedule() -> None:
    """A recurring lane is a separate decision. This one is asked for."""

    assert list(_triggers()) == ["workflow_dispatch"]


def test_a_dispatch_defaults_to_dry() -> None:
    """The default must not be able to spend or publish."""

    mode = _triggers()["workflow_dispatch"]["inputs"]["mode"]

    assert mode["default"] == "dry"
    assert mode["type"] == "choice"
    assert mode["options"] == ["dry", "live"]


def test_publication_requires_asking_for_it_explicitly() -> None:
    """`live` is the only value that reaches the publishing script."""

    assert "== 'live'" in _named(LIVE_STEP)["if"]
    assert "== 'dry'" in _named(DRY_STEP)["if"]
    for step in (LIVE_STEP, DRY_STEP):
        assert "inputs.mode || 'dry'" in _named(step)["if"], step


def test_a_second_switch_has_to_be_on_as_well() -> None:
    """Two independent conditions, for two different kinds of accident.

    The variable stops a dispatch from running at all; the mode stops a run
    from publishing. Either alone is enough to prevent a live cycle.
    """

    gate = [step for step in _steps() if step.get("id") == "gate"]
    assert len(gate) == 1
    assert gate[0]["env"]["ENABLED"] == "${{ vars.NB_MVP1_ENABLED }}"
    assert '"${ENABLED}" = "true"' in gate[0]["run"]

    for step in (DRY_STEP, LIVE_STEP):
        assert "steps.gate.outputs.run == 'true'" in _named(step)["if"], step


def test_the_dry_mode_calls_no_paid_api() -> None:
    """Each dry command is the no-call variant of its script."""

    body = _named(DRY_STEP)["run"]

    assert "scripts/generate.py --dry" in body
    assert "scripts/generate_image.py --dry-run" in body
    assert "scripts/publish.py --dry-run" in body
    for paid in ("--upload", "--live", "--qc"):
        assert paid not in body, paid


def test_the_dry_step_receives_no_provider_credential() -> None:
    """It cannot spend even if it tried: it is given nothing to spend with."""

    step = _named(DRY_STEP)

    assert set(step.get("env", {})) == {"CHANNELS"}
    assert "secrets." not in str(step)


def test_the_channel_list_cannot_become_a_command() -> None:
    """A dispatch input reaches bash through the environment, guarded."""

    step = _named(DRY_STEP)

    assert step["env"]["CHANNELS"] == "${{ inputs.channels }}"
    assert "${{ inputs.channels }}" not in step["run"]
    assert "(*[!a-z,]*|\"\")" in step["run"]


# ===========================================================================
# 2 · the lane runs the existing scripts, and no logic is duplicated
# ===========================================================================


def test_live_runs_the_proven_sequence_through_its_own_script() -> None:
    """`scheduled_publish.py` owns the order; the workflow does not restate it."""

    body = _named(LIVE_STEP)["run"]

    assert "scripts/scheduled_publish.py --force" in body
    # Full paths, because `scheduled_publish.py` contains `publish.py` as a
    # substring — the question is whether the workflow invokes the individual
    # scripts itself, not whether their names appear.
    for duplicated in (
        "--channels",
        "scripts/publish.py",
        "scripts/generate.py",
        "scripts/generate_image.py",
    ):
        assert duplicated not in body, duplicated


def test_the_proven_sequence_is_still_what_that_script_does() -> None:
    """Read from the script, so the workflow's comment cannot rot.

    Wix first, the four social channels each independently, telegram last and
    only when Wix produced a URL.
    """

    source = _script("scheduled_publish.py")

    assert 'scripts/generate.py", "--qc"' in source
    assert 'scripts/generate_image.py", "--upload"' in source
    assert '"--channels", "wix"' in source
    assert '["linkedin", "facebook", "instagram", "threads"]' in source
    assert "abort_on_fail=False" in source
    assert "--force" in source


def test_the_lane_shares_no_code_with_the_golden_engine() -> None:
    """MVP 1 is a separate lane, not a backport."""

    for name in ("scheduled_publish.py", "generate.py", "publish.py", "generate_image.py"):
        source = _script(name)
        assert "editorial_core" not in source, name
        assert "golden_engine" not in source, name


def test_the_r1_allowlist_is_neither_imported_nor_needed() -> None:
    """The lane is the manual caller `release_scope.py` was written to permit.

    Its own docstring: the module imports no publisher precisely so a publisher
    class stays "fully usable by a manual or non-R1 caller, without becoming
    reachable from a scheduled run". So MVP 1 publishes six destinations
    without touching R1's scope — and the scope itself is asserted unchanged.
    """

    from src.publishing.release_scope import (
        NON_R1_PUBLISH_CHANNELS,
        R1_PUBLISH_CHANNELS,
    )

    assert R1_PUBLISH_CHANNELS == ("wix", "linkedin")
    assert NON_R1_PUBLISH_CHANNELS == ("facebook", "instagram", "threads", "telegram")

    for name in ("scheduled_publish.py", "publish.py", "generate.py"):
        assert "release_scope" not in _script(name), name


# ===========================================================================
# 3 · all six destinations, each independently observable
# ===========================================================================


def test_all_six_destinations_are_the_default() -> None:
    declared = _triggers()["workflow_dispatch"]["inputs"]["channels"]["default"]

    assert tuple(declared.split(",")) == DESTINATIONS


def test_every_destination_has_a_publisher_behind_it() -> None:
    """Including threads, which is configured but has no proven publication.

    #393 found no marker, no index entry and no forensic record of a Threads
    post. It is included because the owner asked for all six and because its
    failure is isolated — not because it is proven.
    """

    from src.publishing.publication_markers import DESTINATIONS as KNOWN

    source = _script("publish.py")
    for destination in DESTINATIONS:
        assert destination in KNOWN, destination
        assert f'"{destination}"' in source, destination


def test_one_destination_failing_cannot_hide_the_others() -> None:
    """Each channel is its own step with its own return code."""

    source = _script("scheduled_publish.py")

    assert "abort_on_fail=False" in source
    assert "steps_failed" in source
    assert "scheduled_publish_report.json" in source


def test_the_cycle_is_preserved_whatever_happened() -> None:
    """A failed or partial cycle is the one worth reading."""

    step = _named(EVIDENCE_STEP)

    assert step["uses"].startswith("actions/upload-artifact@")
    assert "always()" in step["if"]
    assert int(step["with"]["retention-days"]) == 90
    assert step["with"]["if-no-files-found"] in ("warn", "ignore")

    paths = [
        line.strip()
        for line in str(step["with"]["path"]).splitlines()
        if line.strip()
    ]
    assert "reports/scheduled_publish_report.json" in paths
    assert "data/drafts/latest/" in paths


# ===========================================================================
# 4 · a partial failure must not repost to what already succeeded
# ===========================================================================


def test_the_identity_key_is_stable_across_a_regenerated_draft() -> None:
    """The protection the owner asked about, stated as the key's own shape.

    `PublicationIdentity` is (client, destination, source signal ids) — **no
    run id and no article digest**. So a retry that regenerates the article
    from the same topic produces the same key, and the destination that already
    published is recognised. A digest in the key would have made every rewrite
    a new publication.
    """

    from src.publishing.publication_markers import PublicationIdentity

    first = PublicationIdentity(
        client="never_blank", destination="wix", source_signal_ids=("1",)
    )
    regenerated = PublicationIdentity(
        client="never_blank", destination="wix", source_signal_ids=("1",)
    )

    assert first == regenerated
    assert set(PublicationIdentity.__dataclass_fields__) == {
        "client",
        "destination",
        "source_signal_ids",
    }


def test_a_destination_is_claimed_before_its_call_and_marked_after() -> None:
    """Intent first, marker second — per destination, in the live path only."""

    source = _script("publish.py")

    assert "guard.check(channel)" in source
    assert "guard.record_intent(channel" in source
    assert "guard.record_marker(channel" in source
    assert 'if mode == "live"' in source


def test_a_draft_that_names_no_source_publishes_nothing() -> None:
    """No identity, no authority, no publication."""

    from src.publishing.publication_markers import (
        PublicationIdentity,
        PublicationIdentityError,
    )

    with pytest.raises(PublicationIdentityError):
        PublicationIdentity(
            client="never_blank", destination="wix", source_signal_ids=()
        )


# ===========================================================================
# 5 · the input lineage — what MVP 1 will actually write about
# ===========================================================================


def test_the_subject_comes_from_the_manual_topic_queue() -> None:
    """Established deterministically, and it is not fresh discovery.

    `get_next_topic()` reads `topics_manual.csv` and takes the first row whose
    status is `pending`. Its only other branch logs that the Intelligence
    Engine is "not wired yet (Phase 7)" and returns `None`, which makes
    `generate.py` exit 1. So MVP 1 writes about a **configured** topic, and
    there is no path by which it discovers one.
    """

    from src.internal.topic_prioritizer import MANUAL_QUEUE, get_next_topic

    assert MANUAL_QUEUE.name == "topics_manual.csv"

    source = (ROOT / "src" / "internal" / "topic_prioritizer.py").read_text(
        encoding="utf-8"
    )
    assert "Intelligence Engine not wired yet" in source

    topic = get_next_topic()
    assert topic is not None, "the queue has no pending row, so the lane has no subject"


def test_the_queue_state_is_reported_rather_than_assumed() -> None:
    """What is in the queue today, so a live run cannot surprise us.

    This is the operational input step MVP 1 needs: a human adds a row. The
    single row on `main` is an **example** written for a dry run — publishing
    it live is a decision, not a default, and this test exists so that decision
    is made with the row in front of you.
    """

    rows = list(
        csv.DictReader(
            (ROOT / "topics_manual.csv").read_text(encoding="utf-8").splitlines()
        )
    )
    pending = [row for row in rows if (row.get("status") or "").strip() == "pending"]

    assert pending, "no pending topic: a live MVP 1 run would exit 1 at generation"
    assert len(pending) == 1, (
        f"{len(pending)} pending topics; the lane takes the first and the rest "
        "stay queued — worth knowing before a live run"
    )
    assert "Example manual topic" in (pending[0].get("notes") or ""), (
        "the pending row is no longer the known example; a live run would "
        "publish whatever replaced it, so this test asks you to look"
    )


def test_a_used_topic_is_not_marked_so_a_rerun_regenerates_it() -> None:
    """The one stale-material risk, named rather than papered over.

    `topic_prioritizer` has `mark_manual_topic_in_progress` and
    `mark_manual_topic_published`, and **`generate.py` calls neither**. So a
    second run takes the same first pending row again. Two things stop that
    becoming a second publication: the semantic duplicate check in
    `generate.py`, which exits 1, and the publication markers, which refuse a
    destination that already published.
    """

    generator = _script("generate.py")

    assert "mark_manual_topic_published" not in generator
    assert "mark_manual_topic_in_progress" not in generator
    assert "is_duplicate" in generator
    assert "guard.check(channel)" in _script("publish.py")


# ===========================================================================
# 6 · the Golden Engine is untouched
# ===========================================================================


def test_the_canonical_workflows_are_not_touched_by_this_lane() -> None:
    """MVP 1 adds a file. It does not edit the engine's own triggers."""

    workflows = ROOT / ".github" / "workflows"
    for canonical in (
        "canonical_shadow.yml",
        "monday_publish.yml",
        "wednesday_golden.yml",
    ):
        text = (workflows / canonical).read_text(encoding="utf-8")
        assert "mvp1" not in text.lower(), canonical
        assert "NB_MVP1_ENABLED" not in text, canonical

    assert "CANONICAL_SHADOW_ENABLED" not in WORKFLOW.read_text(encoding="utf-8")


def test_the_golden_engine_call_budgets_are_unchanged() -> None:
    from src.run.call_budget import (
        GOLDEN_ENGINE_MAX_CEILING,
        R1_MAX_CEILING,
        WEDNESDAY_MAX_CEILING,
    )

    assert (
        GOLDEN_ENGINE_MAX_CEILING,
        R1_MAX_CEILING,
        WEDNESDAY_MAX_CEILING,
    ) == (60, 40, 56)
