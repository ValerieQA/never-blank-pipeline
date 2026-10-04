"""A manual research dispatch produces classified signals and nothing else.

Why this mode exists. #308's acceptance runs need signals carrying the #365
Stage 4 classification (``EDITORIAL_DOMAIN`` / ``EDITORIAL_RISK``), and the
existing 134 records predate it — `EDITORIAL_DOMAIN` reached `enrich.py` on
2026-09-29 and the research workflow last ran on 2026-09-21, so no run has ever
executed with the classifier. #365 forbids backfilling the old records, so the
only honest route is a fresh research run. But the full research path also
builds content packages, spends a billed base image per signal, uploads it to a
media host, and can reach Stage 11 publishing depending on a secret whose value
the person dispatching cannot see.

So a manual dispatch is **research-only by default**: discovery, scoring, the
Stage 4 classification, the Stage 6 save — and nothing after them. Full
production on a manual run is an explicit opt-in, never an inherited default.

The four properties below are the ones that make that claim worth believing.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily_signal_research.yml"
SCRIPT = ROOT / "scripts" / "research" / "run_daily_research.py"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def triggers(workflow) -> dict:
    # Bare `on:` parses as the boolean True in YAML 1.1.
    return workflow.get("on") or workflow[True]


@pytest.fixture(scope="module")
def research_step(workflow) -> dict:
    steps = workflow["jobs"]["daily-research"]["steps"]
    return next(s for s in steps if s.get("id") == "research")


# ===========================================================================
# 1 · the scheduled path is unchanged
# ===========================================================================


def test_the_scheduled_path_cannot_enter_research_only_mode(research_step):
    """The guard names the event, so a schedule never reaches the exports.

    This is the whole reason the condition tests `github.event_name` rather
    than only the input: on a scheduled run `inputs.full_production` is empty,
    which is not `"true"`, so a guard written on the input alone would have
    silently turned production into research-only.
    """

    run = research_step["run"]
    assert 'github.event_name }}" = "workflow_dispatch"' in run
    assert 'inputs.full_production }}" != "true"' in run

    # The two exports live inside that branch and nowhere else.
    guarded = run.split('github.event_name }}" = "workflow_dispatch"', 1)[1]
    guarded = guarded.split("fi", 1)[0]
    assert "export NB_RESEARCH_ONLY=true" in guarded
    assert "export NB_RESEARCH_PUBLISH_ENABLED=false" in guarded
    assert run.count("export NB_RESEARCH_ONLY=true") == 1


def test_the_schedule_and_the_wednesday_rule_are_untouched(triggers, research_step):
    """Nothing about the configured behaviour moved."""

    assert triggers["schedule"] == [{"cron": "0 8 * * *"}]
    # The pre-existing Wednesday override still stands on its own.
    assert '"$(TZ=America/New_York date +%u)" = "3"' in research_step["run"]
    assert "python scripts/research/run_daily_research.py" in research_step["run"]


def test_the_manual_default_is_the_safe_value(triggers):
    """Fail-safe: full production on a manual run is an opt-in, not a default."""

    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["full_production"]["default"] is False
    assert inputs["full_production"]["type"] == "boolean"
    # And the original input is still there, unchanged.
    assert inputs["force"]["default"] is False


def test_absence_of_the_variable_means_the_full_path(source_tree=None):
    """Read from the environment with no default of its own.

    The fail-safe default belongs to the dispatch input, where a person chooses
    it. Here, absence must mean "behave as before", or merely importing this
    script somewhere else would change what production does.
    """

    tree = ast.parse(SCRIPT.read_text())
    getenvs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "NB_RESEARCH_ONLY"
    ]
    assert len(getenvs) == 1
    (call,) = getenvs
    assert len(call.args) == 2 and call.args[1].value == "", (
        "an absent variable must read as the full path, not as research-only"
    )


# ===========================================================================
# 2–4 · what the mode actually does, by running it
# ===========================================================================


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """`run()` over stubbed stages, so the control flow is the thing measured.

    Every stage is replaced, including the two that cost money in the path this
    mode exists to avoid: `prepare_content_packages` and `publish_packages`
    raise if they are called at all. A stub that merely recorded the call would
    pass a test that the real path would fail.
    """

    import scripts.research.run_daily_research as rdr

    calls: dict[str, int] = {}
    saved: list[dict] = []

    classified = [
        {
            "SIGNAL_ID": "sig-research-only-1",
            "HEADLINE": "A classified signal",
            "SOURCE_URL": "https://example.test/a",
            "ARTICLE_READINESS_SCORE": 10,
            "EDITORIAL_DOMAIN": "customer trust",
            "EDITORIAL_RISK": "low",
            "EDITORIAL_DOMAIN_OUTCOME": "classified",
            "EDITORIAL_RISK_OUTCOME": "classified",
            # Admitted and article-ready, so the selection gate really selects
            # it: a stub the gate rejects would make "Stage 10 was skipped"
            # true for the wrong reason.
            "ARTICLE_READY": True,
            "RECOMMENDED_FOR_ARTICLE": True,
            "SCORE_RECOMMENDED_FOR_ARTICLE": True,
            "SOURCE_PREMISE_VERIFIED": True,
        }
    ]

    def counted(name, result):
        def stub(*args, **kwargs):
            calls[name] = calls.get(name, 0) + 1
            return result
        return stub

    def forbidden(name):
        def stub(*args, **kwargs):
            raise AssertionError(f"{name} must not be reached in research-only mode")
        return stub

    monkeypatch.setattr(
        rdr,
        "_load_weights",
        lambda: {"thresholds": {"select_minimum": 7, "top_n_to_select": 3}},
    )
    monkeypatch.setattr(rdr, "_load_seen", lambda: {})
    monkeypatch.setattr(rdr, "_save_seen", lambda seen: None)
    monkeypatch.setattr(rdr, "run_discovery", counted("discovery", list(classified)))
    monkeypatch.setattr(
        rdr, "score_candidates", counted("scoring", list(classified))
    )
    monkeypatch.setattr(
        rdr, "enrich_candidates", counted("enrichment", list(classified))
    )
    monkeypatch.setattr(rdr, "add_angles", counted("angles", list(classified)))
    monkeypatch.setattr(rdr, "sync_to_sheets", counted("sheets", True))
    monkeypatch.setattr(rdr, "run_archive", counted("archive", 0))
    monkeypatch.setattr(
        rdr, "prepare_content_packages", forbidden("prepare_content_packages")
    )
    monkeypatch.setattr(rdr, "publish_packages", forbidden("publish_packages"))

    def record(path, signals):
        calls["append"] = calls.get("append", 0) + 1
        if path == rdr.ACTIVE_FILE:
            saved.extend(signals)

    monkeypatch.setattr(rdr, "_append_jsonl", record)
    monkeypatch.setattr(
        rdr, "_write_summary_artifact", lambda *a, **k: None, raising=False
    )
    return rdr, calls, saved


def test_a_default_manual_dispatch_never_enters_the_package_or_image_path(
    harness, monkeypatch
):
    """Requirement 2: it stops after the research outputs are saved."""

    rdr, calls, _ = harness
    monkeypatch.setenv("NB_RESEARCH_ONLY", "true")

    summary = rdr.run()

    assert calls.get("discovery") == 1
    assert calls.get("scoring") == 1
    assert calls.get("enrichment") == 1, "the #365 classification still runs"
    assert summary["content_packages"] == 0
    assert summary["images_new"] == 0 and summary["images_reused"] == 0
    assert summary["_classification"] == "research-only"
    assert summary["selected_for_content"] == 1, (
        "the signal WAS selected, so Stage 10 was skipped by the mode and not "
        "because there was nothing to package"
    )
    # `prepare_content_packages` and `publish_packages` are the stubs that raise.


def test_publishing_is_unreachable_even_with_the_secret_on(harness, monkeypatch):
    """Requirement 3: the mode does not depend on the publish flag being off.

    The workflow exports both variables, but a guarantee that rests on one
    export is one typo from gone. So the mode refuses publishing by itself,
    with the flag explicitly set to `true`.
    """

    rdr, _, _ = harness
    monkeypatch.setenv("NB_RESEARCH_ONLY", "true")
    monkeypatch.setenv("NB_RESEARCH_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("NB_PUBLISH_MODE", "live")

    summary = rdr.run()

    assert "publish_reports" not in summary or summary["publish_reports"] == []
    assert summary["_publish_reports"] == []


def test_the_classified_signals_are_saved_before_the_run_stops(harness, monkeypatch):
    """Requirement 4: Stage 6 completed, and it carries #365's fields."""

    rdr, calls, saved = harness
    monkeypatch.setenv("NB_RESEARCH_ONLY", "true")

    summary = rdr.run()

    assert calls.get("append"), "Stage 6 wrote the queue"
    assert saved, "and it wrote to signals_active.jsonl specifically"
    assert summary["new_signals_added"] == len(saved)
    for record in saved:
        assert record["EDITORIAL_DOMAIN"], "the whole point of the run"
        assert record["EDITORIAL_RISK"]
    # Bookkeeping after Stage 6 is unchanged: it reads the queue and writes no
    # package, image or publication. Stated rather than skipped silently.
    assert calls.get("sheets") == 1 and calls.get("archive") == 1


def test_the_full_path_is_still_the_behaviour_without_the_variable(
    harness, monkeypatch
):
    """Requirement 1, behaviourally: unset means the old path, calls and all."""

    rdr, calls, _ = harness
    monkeypatch.delenv("NB_RESEARCH_ONLY", raising=False)
    reached: list[str] = []
    monkeypatch.setattr(
        rdr,
        "prepare_content_packages",
        lambda selected: reached.append("packages") or [],
    )

    with pytest.raises(RuntimeError, match="no content packages"):
        rdr.run()

    assert reached == ["packages"], (
        "without the variable the run enters the package path, as it always did"
    )
