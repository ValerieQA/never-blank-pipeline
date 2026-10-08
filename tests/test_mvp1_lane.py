"""Never Blank MVP 1 — the historical research lane, on demand (#393).

A temporary operational release so Never Blank has something demonstrably
working for prospective clients while the Golden Engine is completed. The lane
is the July one: a signal the system discovered, the package Stage 10 prepared,
and Stage 11, which generates the six final texts and publishes them.

What this file holds is the restoration's contract, not the lane's editorial
behaviour. What a restoration can get wrong is the wiring around it — spending
or publishing by accident, reaching a destination that is out of scope, hiding
one destination's failure behind another's, reposting to a destination that
already succeeded, or quietly inventing the subject.

Everything here is deterministic: YAML, repository state, the entry script's
own refusals, and the publishers' idempotency types. No provider call, no
network, no publication.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "never_blank_mvp1.yml"
ENTRY = ROOT / "scripts" / "mvp1_publish_signal.py"

INSPECT_STEP = "Inspect the signal and its package"
LIVE_STEP = "Live: generate and publish"
EVIDENCE_STEP = "Preserve the MVP 1 cycle"

#: MVP 1's destinations (owner, 2026-10-07). Threads is deliberately absent.
DESTINATIONS = ("wix", "linkedin", "facebook", "instagram", "telegram")
EXCLUDED = "threads"

#: The signal selected for the first proof (#393): discovered by the system
#: from Entrepreneur Magazine on 2026-09-18, package and hosted image present.
SIGNAL = "a71d52f27d921529"


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


def _entry(*args: str) -> subprocess.CompletedProcess:
    """Run the entry script. It reaches no provider in any case tested here."""

    return subprocess.run(
        [sys.executable, str(ENTRY), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )


# ===========================================================================
# 1 · nothing starts, spends or publishes by accident
# ===========================================================================


def test_only_a_schedule_or_a_dispatch_can_start_the_lane() -> None:
    """The schedule is the owner's decision of 2026-10-08, and replaces this
    test's original claim that the lane had none.

    What it protected is kept: nothing *else* may start a lane that publishes
    to five real surfaces — no push, no pull request, no issue event.
    """

    assert sorted(_triggers()) == ["schedule", "workflow_dispatch"]


def test_a_dispatch_defaults_to_inspect() -> None:
    """And there is deliberately no dry-run.

    Stage 11 generates before it touches a publisher, so a rehearsal through it
    costs nine model calls and posts nothing. `inspect` is free because it never
    reaches the stage (owner decision 2026-10-07).
    """

    mode = _triggers()["workflow_dispatch"]["inputs"]["mode"]

    assert mode["default"] == "inspect"
    assert mode["options"] == ["inspect", "live"]
    assert "dry" not in mode["options"]


def test_two_independent_switches_guard_a_live_cycle() -> None:
    gate = [step for step in _steps() if step.get("id") == "gate"]

    assert len(gate) == 1
    assert gate[0]["env"]["ENABLED"] == "${{ vars.NB_MVP1_ENABLED }}"
    assert '"${ENABLED}" = "true"' in gate[0]["run"]

    for step in (INSPECT_STEP, LIVE_STEP):
        assert "steps.gate.outputs.run == 'true'" in _named(step)["if"], step
    assert "== 'live'" in _named(LIVE_STEP)["if"]
    assert "== 'inspect'" in _named(INSPECT_STEP)["if"]


def test_inspect_is_given_no_credential_at_all() -> None:
    """It cannot spend or publish even if it tried."""

    step = _named(INSPECT_STEP)

    assert set(step["env"]) == {"PYTHONPATH", "SIGNAL_ID", "CHANNELS"}
    assert "secrets." not in str(step)
    assert "--mode inspect" in step["run"]


def test_no_step_interpolates_an_expression_into_a_command() -> None:
    """Values reach bash through the environment, never through `${{ }}`.

    Stated over *every* step rather than over two named inputs, because the
    schedule added a step that carries a signal id too: the resolved id from
    `steps.publish.outputs`. The property was never about which expression it
    was — it is that no expression is ever spliced into a command.
    """

    for step in _steps():
        assert "${{" not in str(step.get("run") or ""), step.get("name")


def test_the_signal_and_destinations_stay_behind_a_charset_guard() -> None:
    for name in (INSPECT_STEP, LIVE_STEP):
        step = _named(name)
        assert step["env"]["SIGNAL_ID"].startswith("${{")
        assert step["env"]["CHANNELS"].startswith("${{")
        assert '(*[!a-z0-9]*|"")' in step["run"]
        assert '(*[!a-z,]*|"")' in step["run"]


# ===========================================================================
# 2 · the lane is the historical one, and the subject is not invented
# ===========================================================================


def test_no_manual_topic_queue_is_involved() -> None:
    """The correction that started this: MVP 1 does not read a topic file.

    The owner did not supply the topics the working system published — the
    Versant lineage proves the system discovered them — so the lane reads the
    discovered store and nothing else.
    """

    for text in (WORKFLOW.read_text(encoding="utf-8"), ENTRY.read_text(encoding="utf-8")):
        assert "topics_manual" not in text
        assert "get_next_topic" not in text
        assert "scripts/generate.py" not in text
        assert "data/drafts" not in text


def test_the_subject_comes_from_the_discovered_store() -> None:
    source = ENTRY.read_text(encoding="utf-8")

    assert "data/research/signals_active.jsonl" in source
    assert "reports/content_packages" in source


def test_the_lane_runs_the_historical_stage_rather_than_restating_it() -> None:
    """Stage 11 is called; its sequence and marker logic are not duplicated."""

    source = ENTRY.read_text(encoding="utf-8")

    assert "publish_packages(" in source
    for duplicated in ("WixPublisher", "record_intent", "record_marker", "generate_article"):
        assert duplicated not in source, duplicated


def test_no_generated_package_bypass_was_added() -> None:
    """The declined capability, asserted absent (owner, 2026-10-07).

    Stage 11 has always generated the six texts at publication time. A mode
    that read `_generated.json` instead would have made a dry run free and
    would have been a new capability; it was declined, so the entry must not
    have grown one.
    """

    import ast

    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body.pop(0)
    code = ast.unparse(tree)

    # The executable code never reads the stage's own output as an input.
    assert "_generated.json" not in code
    for invented in ("skip_generation", "reuse_generated", "use_existing"):
        assert invented not in code, invented


def test_discovery_and_image_generation_are_not_reachable() -> None:
    """Asserted on what the job *executes*, not on the file's text.

    The workflow's comments name `NB_FORCE_REGENERATE_RESEARCH_IMAGES` in order
    to say it is deliberately not passed, and a sentence explaining an absence
    is not that absence. So this reads the parsed steps — every `env` key and
    every `run` body — and the entry script with its comments and docstrings
    stripped.
    """

    import ast

    for step in _steps():
        for key in step.get("env", {}):
            assert "FORCE_REGENERATE" not in key, step.get("name")
        for forbidden in ("run_daily_research", "discover.py", "generate_image"):
            assert forbidden not in str(step.get("run", "")), (step.get("name"), forbidden)

    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body.pop(0)
    code = ast.unparse(tree)
    for forbidden in (
        "run_daily_research",
        "generate_image",
        "NB_FORCE_REGENERATE_RESEARCH_IMAGES",
    ):
        assert forbidden not in code, forbidden


# ===========================================================================
# 3 · five destinations, Threads out, each independently observable
# ===========================================================================


def test_the_five_destinations_are_the_default() -> None:
    declared = _triggers()["workflow_dispatch"]["inputs"]["channels"]["default"]

    assert tuple(declared.split(",")) == DESTINATIONS
    assert EXCLUDED not in declared


def test_threads_is_out_of_the_lane_and_still_in_the_repository() -> None:
    """A scope decision, not a removal."""

    from scripts.research.publish_packages import _ALL_PUBLISHERS
    from src.publishing.release_scope import NON_R1_PUBLISH_CHANNELS

    assert (ROOT / "src" / "publishing" / "threads.py").is_file()
    assert EXCLUDED in {name for name, _ in _ALL_PUBLISHERS}
    assert EXCLUDED in NON_R1_PUBLISH_CHANNELS

    live = _named(LIVE_STEP)
    assert not any("THREADS" in key for key in live["env"])


def test_every_destination_the_lane_names_has_a_publisher() -> None:
    from scripts.research.publish_packages import _ALL_PUBLISHERS

    known = {name for name, _ in _ALL_PUBLISHERS}
    for destination in DESTINATIONS:
        assert destination in known, destination


def test_the_live_step_carries_each_destinations_credentials() -> None:
    """And nothing for a destination the lane does not publish to."""

    env = _named(LIVE_STEP)["env"]

    for required in (
        "NB_WIX_API_KEY", "NB_ZERNIO_API_KEY", "NB_META_FB_PAGE_TOKEN",
        "NB_META_IG_USER_ID", "NB_TELEGRAM_BOT_TOKEN",
    ):
        assert required in env, required


def test_the_live_step_routes_every_stage_model() -> None:
    """Live run 37689111181 died on its first call for want of these.

    The step passed only `NB_OPENAI_CHAT_MODEL`, so `model_enrich()` and every
    sibling resolved to the global fallback, whose value the provider rejects
    with HTTP 400 `invalid model ID`. `wednesday_golden.yml` records the same
    failure for run 33281894748 (#213, #236) and survives by routing the five.

    Read from the parsed step, because a comment naming a secret is not the
    secret being passed.
    """

    env = _named(LIVE_STEP)["env"]

    for stage in (
        "NB_DISCOVERY_MODEL", "NB_SCORING_MODEL", "NB_ENRICH_MODEL",
        "NB_ARTICLE_MODEL", "NB_SOCIAL_MODEL",
    ):
        assert env.get(stage) == "${{ secrets.%s }}" % stage, stage


def test_the_stage_models_match_the_restored_lanes_own_convention() -> None:
    """Same secrets, same spelling as the workflow this lane was taken from."""

    daily = yaml.safe_load(
        (WORKFLOW.parent / "daily_signal_research.yml").read_text(encoding="utf-8")
    )
    daily_env: dict = {}
    for job in daily["jobs"].values():
        for step in job["steps"]:
            daily_env.update(step.get("env") or {})
    live_env = _named(LIVE_STEP)["env"]

    for stage in (
        "NB_DISCOVERY_MODEL", "NB_SCORING_MODEL", "NB_ENRICH_MODEL",
        "NB_ARTICLE_MODEL", "NB_SOCIAL_MODEL",
    ):
        assert live_env[stage] == daily_env[stage], stage


def test_no_image_model_was_routed_with_them() -> None:
    """The package's image is reused hosted, so nothing draws one (#393).

    Guards the one member of the daily lane's model set that this lane must
    not acquire, so routing the five cannot quietly re-enable a paid image.
    """

    assert "NB_IMAGE_MODEL" not in _named(LIVE_STEP)["env"]


def test_the_lane_can_write_the_claim_it_must_push() -> None:
    """Live run 37704053905: green, six texts written, nothing published.

    `GitSharedClaim.acquire()` pushes the claim to the remote *before* a
    provider call, and a read-only token denies that push — so idempotency
    authority was never established and all five destinations fail-closed
    with `idempotency_authority_unavailable`. The grant is a prerequisite of
    publication, not bookkeeping after it.

    Read from the effective permission the job runs under, so declaring it at
    workflow level instead would satisfy this test too.
    """

    spec = _spec()
    job = spec["jobs"][next(iter(spec["jobs"]))]
    effective = {**(spec.get("permissions") or {}), **(job.get("permissions") or {})}

    assert effective.get("contents") == "write"


def test_the_cycle_is_preserved_whatever_happened() -> None:
    step = _named(EVIDENCE_STEP)

    assert step["uses"].startswith("actions/upload-artifact@")
    assert "always()" in step["if"]
    assert int(step["with"]["retention-days"]) == 90
    assert step["with"]["if-no-files-found"] in ("warn", "ignore")
    assert "_generated.json" in str(step["with"]["path"])


# ===========================================================================
# 4 · fail closed before anything outward
# ===========================================================================


def test_a_signal_the_system_never_discovered_is_refused() -> None:
    result = _entry("--signal-id", "deadbeefdeadbeef")

    assert result.returncode != 0
    assert "is not in" in result.stderr


def test_a_signal_without_a_prepared_package_is_refused() -> None:
    """`6a72b2abcc466aab` is discovered and has no package — MVP 1 makes none."""

    result = _entry("--signal-id", "6a72b2abcc466aab")

    assert result.returncode != 0
    assert "no content package" in result.stderr


@pytest.mark.parametrize("channels", ["wix,bogus", "mastodon", ""])
def test_a_malformed_destination_set_is_refused_in_inspect_too(channels) -> None:
    """Before the paid mode, not inside it.

    The stage validates its own destinations, but only a live run reaches the
    stage — so a typo would otherwise pass `inspect` and surface for the first
    time on a run that had already generated. The entry checks it up front,
    against the stage's own vocabulary.
    """

    result = _entry("--signal-id", SIGNAL, "--channels", channels)

    assert result.returncode != 0
    assert "destination" in result.stderr


def test_inspect_passes_for_the_selected_signal_and_calls_nothing() -> None:
    """The one case that must succeed, and it needs no credential to do so."""

    result = _entry("--signal-id", SIGNAL)

    assert result.returncode == 0, result.stderr
    assert "Nothing was called" in result.stdout
    assert SIGNAL in result.stdout
    # It reports what a live run would cost, rather than leaving it implied.
    assert "nine model calls" in result.stdout


# ===========================================================================
# 5 · a partial failure cannot repost to what already succeeded
# ===========================================================================


def test_the_identity_key_is_stable_across_a_regenerated_article() -> None:
    """Which matters more here than anywhere: this lane regenerates every run.

    `PublicationIdentity` is (client, destination, source signal ids) — no run
    id and no article digest — so Stage 11 producing fresh prose for the same
    signal is still the same publication, and a destination that already
    published is refused.
    """

    from src.publishing.publication_markers import PublicationIdentity

    first = PublicationIdentity(
        client="never_blank", destination="wix", source_signal_ids=(SIGNAL,)
    )
    after_regeneration = PublicationIdentity(
        client="never_blank", destination="wix", source_signal_ids=(SIGNAL,)
    )

    assert first == after_regeneration
    assert set(PublicationIdentity.__dataclass_fields__) == {
        "client", "destination", "source_signal_ids",
    }


#: Where the publication authority keeps its records, and where the lane
#: records that a signal's cycle finished.
_MARKER_ROOT = ROOT / "data" / "editorial" / "publication_markers" / "never_blank"
_CONSUMED = ROOT / "data" / "research" / "published_signal_ids.txt"


def publication_records(root: Path, signal: str) -> dict[str, dict[str, bool]]:
    """Per destination, whether this signal holds an intent and/or a marker.

    One reader for both the real store and a double, so the invariants below
    are asserted on the same code path in either.
    """

    found: dict[str, dict[str, bool]] = {}
    if not root.is_dir():
        return found
    for destination in sorted(root.iterdir()):
        if not destination.is_dir():
            continue
        files = [f.name for f in destination.glob(f"*{signal}*")]
        if not files:
            continue
        found[destination.name] = {
            "intent": any(f.endswith(".intent.json") for f in files),
            "marker": any(
                f.endswith(".json") and not f.endswith(".intent.json") for f in files
            ),
        }
    return found


def record_violations(
    root: Path, signal: str, *, consumed: bool, drivable: set[str]
) -> list[str]:
    """Every way this signal's records could contradict what the lane did.

    This replaces an assertion that the signal held *no* records at all. That
    one existed so the lane's first proof would be a real publication rather
    than a refusal, and run 37715852447 spent it: four surfaces published and
    five intents are now legitimate history. Asserting their absence would
    only be satisfiable by deleting publication evidence, which is the one
    thing a publication authority must never make convenient.

    What survives the first publication is what the records must *mean*:

    1. nothing was ever claimed for a destination this lane cannot drive;
    2. no marker exists without its intent — the authority writes the intent
       before the irreversible call and the marker after it, so a marker alone
       would be a publication nobody claimed;
    3. consumption never outruns evidence — a consumed signal means the cycle
       completed, so every destination holding an intent must hold a marker.
    """

    records = publication_records(root, signal)
    problems: list[str] = []

    for destination, state in records.items():
        if destination not in drivable:
            problems.append(f"{destination}: claimed but not drivable by this lane")
        if state["marker"] and not state["intent"]:
            problems.append(f"{destination}: marker without an intent")
        if consumed and state["intent"] and not state["marker"]:
            problems.append(f"{destination}: signal consumed with no marker")

    return problems


def _drivable() -> set[str]:
    """Every destination the stage knows, including the withheld one."""

    from scripts.research.publish_packages import _ALL_PUBLISHERS

    return {name for name, _ in _ALL_PUBLISHERS}


def _is_consumed(signal: str) -> bool:
    if not _CONSUMED.is_file():
        return False
    return signal in _CONSUMED.read_text(encoding="utf-8").split()


def test_the_selected_signals_publication_records_are_coherent() -> None:
    """The live state, read rather than assumed.

    Deterministic in both directions: it passes today with five intents and no
    markers, it would fail the moment a record meant something the lane could
    not have done, and nothing about it asks for a record to be removed.
    """

    problems = record_violations(
        _MARKER_ROOT, SIGNAL, consumed=_is_consumed(SIGNAL), drivable=_drivable()
    )

    assert problems == [], f"{SIGNAL}: " + "; ".join(problems)


def test_a_marker_without_its_intent_is_a_violation(tmp_path: Path) -> None:
    """The ordering the authority guarantees, asserted on a double."""

    destination = tmp_path / "wix"
    destination.mkdir()
    (destination / f"{SIGNAL}-abc.json").write_text("{}")

    problems = record_violations(
        tmp_path, SIGNAL, consumed=False, drivable={"wix"}
    )

    assert problems == ["wix: marker without an intent"]


def test_consumption_without_a_marker_is_a_violation(tmp_path: Path) -> None:
    """What the `success()` gate on "mark the cycle complete" exists to prevent."""

    destination = tmp_path / "linkedin"
    destination.mkdir()
    (destination / f"{SIGNAL}-abc.intent.json").write_text("{}")

    problems = record_violations(
        tmp_path, SIGNAL, consumed=True, drivable={"linkedin"}
    )

    assert problems == ["linkedin: signal consumed with no marker"]


def test_a_record_for_an_undrivable_destination_is_a_violation(tmp_path: Path) -> None:
    destination = tmp_path / "mastodon"
    destination.mkdir()
    (destination / f"{SIGNAL}-abc.intent.json").write_text("{}")

    problems = record_violations(
        tmp_path, SIGNAL, consumed=False, drivable={"wix", "linkedin"}
    )

    assert problems == ["mastodon: claimed but not drivable by this lane"]


def test_the_shape_run_37715852447_actually_left_is_coherent(tmp_path: Path) -> None:
    """Five intents, no markers, signal unconsumed — history, not a defect.

    Pins the distinction the replaced test could no longer make: an incomplete
    cycle is not an incoherent one.
    """

    for name in ("wix", "linkedin", "facebook", "instagram", "telegram"):
        destination = tmp_path / name
        destination.mkdir()
        (destination / f"{SIGNAL}-fe453cf5.intent.json").write_text("{}")

    assert record_violations(
        tmp_path, SIGNAL, consumed=False,
        drivable={"wix", "linkedin", "facebook", "instagram", "telegram"},
    ) == []


def test_a_completed_cycle_is_coherent(tmp_path: Path) -> None:
    """And the shape a settled cycle leaves, so the invariant is not one-sided."""

    for name in ("wix", "linkedin"):
        destination = tmp_path / name
        destination.mkdir()
        (destination / f"{SIGNAL}-fe453cf5.intent.json").write_text("{}")
        (destination / f"{SIGNAL}-fe453cf5.json").write_text("{}")

    assert record_violations(
        tmp_path, SIGNAL, consumed=True, drivable={"wix", "linkedin"}
    ) == []


def test_the_stage_claims_each_destination_before_calling_it() -> None:
    source = (ROOT / "scripts" / "research" / "publish_packages.py").read_text(
        encoding="utf-8"
    )

    assert "guard.check(name)" in source
    assert "guard.record_intent(name" in source
    assert 'if mode == "live"' in source


# ===========================================================================
# 6 · the Golden Engine and Release 1 are untouched
# ===========================================================================


def test_release_scope_is_untouched_and_knows_nothing_of_this_lane() -> None:
    from src.publishing.release_scope import (
        NON_R1_PUBLISH_CHANNELS,
        R1_PUBLISH_CHANNELS,
    )

    assert R1_PUBLISH_CHANNELS == ("wix", "linkedin")
    assert NON_R1_PUBLISH_CHANNELS == ("facebook", "instagram", "threads", "telegram")

    source = (ROOT / "src" / "publishing" / "release_scope.py").read_text(encoding="utf-8")
    assert "mvp" not in source.lower()


def test_the_nightly_research_job_still_publishes_nothing() -> None:
    """The default destination set has not moved, so #231 still holds for it."""

    from scripts.research.publish_packages import _publishers_for

    assert _publishers_for(None) == []

    nightly = (ROOT / ".github" / "workflows" / "daily_signal_research.yml").read_text(
        encoding="utf-8"
    )
    assert "mvp1" not in nightly.lower()
    assert 'NB_RESEARCH_PUBLISH_ENABLED: "true"' not in nightly


def test_the_canonical_lane_is_not_touched_by_this_workflow() -> None:
    workflows = ROOT / ".github" / "workflows"
    for canonical in ("canonical_shadow.yml", "monday_publish.yml", "wednesday_golden.yml"):
        text = (workflows / canonical).read_text(encoding="utf-8")
        assert "mvp1" not in text.lower(), canonical

    for text in (WORKFLOW.read_text(encoding="utf-8"), ENTRY.read_text(encoding="utf-8")):
        for forbidden in ("editorial_core", "golden_engine", "CANONICAL_SHADOW_ENABLED"):
            assert forbidden not in text, forbidden


def test_the_golden_engine_call_budgets_are_unchanged() -> None:
    from src.run.call_budget import (
        GOLDEN_ENGINE_MAX_CEILING,
        R1_MAX_CEILING,
        WEDNESDAY_MAX_CEILING,
    )

    assert (GOLDEN_ENGINE_MAX_CEILING, R1_MAX_CEILING, WEDNESDAY_MAX_CEILING) == (
        60, 40, 56,
    )
