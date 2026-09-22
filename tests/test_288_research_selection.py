"""NB-00b: the research stream asks the marker authority, not just the file.

`data/research/published_signal_ids.txt` is written only when a whole job
succeeded. A run that published Wix and then failed LinkedIn leaves it
untouched, so the signal still looks unused and selecting it again sends the
same publication back to the destination that already took it — the
partial-success hole in Step 5 §1.1.

These drive the real resolver and the real workflow file. No network, no
model, no publisher.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.streams.resolve_research_signal import NO_ELIGIBLE, main
from src.publishing.publication_markers import MarkerStore, PublicationIdentity

_WORKFLOW = Path(".github/workflows/research_generate_and_publish.yml")


def _store(tmp_path: Path) -> MarkerStore:
    root = tmp_path / "markers"
    root.mkdir(parents=True, exist_ok=True)
    return MarkerStore(root, require_shared_claim=False)


def _feed(tmp_path: Path, *signal_ids: str) -> tuple[str, str]:
    active = tmp_path / "signals_active.jsonl"
    active.write_text(
        "".join(json.dumps({"SIGNAL_ID": s}) + "\n" for s in signal_ids),
        encoding="utf-8",
    )
    published = tmp_path / "published_signal_ids.txt"
    published.write_text("", encoding="utf-8")
    return str(active), str(published)


def _argv(tmp_path: Path, *signal_ids: str, requested: str = "") -> list[str]:
    active, published = _feed(tmp_path, *signal_ids)
    return [
        "--active-path", active,
        "--published-path", published,
        *(("--signal-id", requested) if requested else ()),
    ]


def _publish(store: MarkerStore, signal_id: str, destination: str = "wix") -> None:
    identity = PublicationIdentity("never_blank", destination, (signal_id,))
    assert store.record_intent(identity, run_id="earlier") is not None
    assert store.record_marker(identity, external_id="x-1", run_id="earlier") is not None


def _claim_only(store: MarkerStore, signal_id: str, destination: str = "wix") -> None:
    """An intent with no marker: the call may have reached the platform."""

    identity = PublicationIdentity("never_blank", destination, (signal_id,))
    assert store.record_intent(identity, run_id="earlier") is not None


# ── the gap the review named ───────────────────────────────────────────────


def test_a_signal_the_file_calls_unused_is_refused_when_a_marker_exists(
    tmp_path, capsys
):
    """The partial-success hole: Wix published, the job failed, file untouched."""

    store = _store(tmp_path)
    _publish(store, "sig-a")

    code = main(_argv(tmp_path, "sig-a", "sig-b"), store=store)

    assert code == 0
    assert capsys.readouterr().out.strip() == "sig-b", "sig-a was already published"


def test_a_signal_with_an_intent_and_no_marker_is_also_passed_over(tmp_path, capsys):
    """A call that may have reached the platform is not a free signal."""

    store = _store(tmp_path)
    _claim_only(store, "sig-a")

    code = main(_argv(tmp_path, "sig-a", "sig-b"), store=store)

    assert code == 0
    assert capsys.readouterr().out.strip() == "sig-b"


@pytest.mark.parametrize("destination", ["wix", "linkedin", "telegram", "instagram"])
def test_a_marker_at_any_destination_refuses_the_signal(tmp_path, destination):
    store = _store(tmp_path)
    _publish(store, "sig-a", destination)

    assert main(_argv(tmp_path, "sig-a"), store=store) == NO_ELIGIBLE


# ── an explicitly dispatched signal does not bypass the authority ──────────


def test_a_dispatched_signal_is_still_checked(tmp_path):
    """Naming a signal says which one to consider, not that the authority
    may be ignored."""

    store = _store(tmp_path)
    _publish(store, "sig-a")

    assert main(_argv(tmp_path, "sig-a", requested="sig-a"), store=store) == NO_ELIGIBLE


def test_a_dispatched_signal_the_authority_has_not_spent_is_selected(tmp_path, capsys):
    store = _store(tmp_path)

    assert main(_argv(tmp_path, "sig-a", requested="sig-a"), store=store) == 0
    assert capsys.readouterr().out.strip() == "sig-a"


# ── an authority that cannot answer stops the search ───────────────────────


def test_an_unavailable_authority_selects_nothing(tmp_path, capsys):
    """Never read as "nothing was published" — that is the fresh-checkout trap."""

    missing = MarkerStore(tmp_path / "never-checked-out", require_shared_claim=False)

    code = main(_argv(tmp_path, "sig-a", "sig-b"), store=missing)

    assert code == NO_ELIGIBLE
    assert "idempotency_authority_unavailable" in capsys.readouterr().err


def test_an_unavailable_authority_refuses_a_dispatched_signal_too(tmp_path):
    missing = MarkerStore(tmp_path / "never-checked-out", require_shared_claim=False)

    assert main(_argv(tmp_path, "sig-a", requested="sig-a"), store=missing) == NO_ELIGIBLE


def test_nothing_left_is_a_completed_search_not_a_failure(tmp_path):
    store = _store(tmp_path)
    _publish(store, "sig-a")

    assert main(_argv(tmp_path, "sig-a"), store=store) == NO_ELIGIBLE


# ── the workflow actually uses it ──────────────────────────────────────────


def _steps() -> list[dict]:
    data = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return [step for job in data["jobs"].values() for step in job.get("steps", [])]


def test_the_workflow_resolves_through_the_marker_aware_resolver():
    resolve = next(step for step in _steps() if step.get("id") == "resolve")

    assert "resolve_research_signal.py" in str(resolve.get("run", "")), (
        "the research workflow must consult the marker authority, not the "
        "published-signals file alone"
    )


def test_the_workflow_no_longer_selects_on_the_published_file_alone():
    resolve = next(step for step in _steps() if step.get("id") == "resolve")
    run = str(resolve.get("run", ""))

    assert "published_signal_ids.txt" not in run, (
        "the inline membership check is what NB-00b replaces"
    )


def test_nothing_is_published_when_the_resolver_selected_nothing():
    publish = next(
        step for step in _steps()
        if "generate_and_publish.py" in str(step.get("run", ""))
    )

    assert "steps.resolve.outputs.signal_id != ''" in str(publish.get("if", "")), (
        "an empty selection must not reach the publisher"
    )
