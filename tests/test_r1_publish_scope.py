"""Issue #227: only Release 1's own channels may auto-publish.

Forensics on #159, 2026-09-07: the Daily Signal Research cron published to
Facebook, Instagram and Telegram — while Wix and LinkedIn failed — from
`scripts/research/publish_packages.py`. That stage carried its own list of six
publishers, written before Release 1 narrowed its scope and never revisited
when it did. Nothing in it had ever been told what Release 1 publishes.

It had looked harmless for weeks only because an unrelated repeated-sentence
check rejected each package first. #222 removed that check — correctly, under
the global overlap decision — and the accident it had been covering became
visible the next day. **An incidental guard is not channel authorization**, so
these scenarios pin the authorization instead, and pin that the withdrawn
overlap rule is not quietly restored to do the job again.

The visibility publisher (Tue/Thu) carried the same list and published Telegram
on 2026-08-20; it stopped only because an unrelated model-ID error began
failing the run earlier. Repairing that error must not revive non-R1
publishing, so it is authorized here too.

What is deliberately NOT changed: the publisher implementations. They are
working, tested code that a manual operator tool may still drive. The fix is
reachability from a scheduled run, not deletion.

No network call, no provider call, no model call, nothing published.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from src.publishing.release_scope import (
    NON_R1_PUBLISH_CHANNELS,
    R1_PUBLISH_CHANNELS,
    in_release_scope,
    out_of_release_scope,
    restrict_to_release_scope,
)

WORKFLOWS = Path(".github/workflows")

#: The three channels the live runs actually posted to on 2026-09-06/07.
OBSERVED = ("facebook", "instagram", "telegram")

#: Every automatic path that owns a list of publishers.
AUTOMATIC_PATHS = (
    "scripts/research/publish_packages.py",
    "scripts/generate_and_publish_visibility.py",
)


def _module(path: str) -> ast.Module:
    return ast.parse(Path(path).read_text())


def _list_of_channel_pairs(tree: ast.Module) -> list[list[str]]:
    """Every literal ``[("name", Publisher()), …]`` in a module."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        names = []
        for element in node.elts:
            if (isinstance(element, ast.Tuple) and len(element.elts) == 2
                    and isinstance(element.elts[0], ast.Constant)
                    and isinstance(element.elts[0].value, str)):
                names.append(element.elts[0].value)
        if len(names) == len(node.elts) and names:
            found.append(names)
    return found


# ===========================================================================
# The authority itself
# ===========================================================================


def test_release_1_publishes_wix_and_linkedin_and_nothing_else():
    assert R1_PUBLISH_CHANNELS == ("wix", "linkedin")
    assert set(NON_R1_PUBLISH_CHANNELS) == {
        "facebook", "instagram", "threads", "telegram",
    }
    assert not set(R1_PUBLISH_CHANNELS) & set(NON_R1_PUBLISH_CHANNELS)


@pytest.mark.parametrize("channel", OBSERVED + ("threads",))
def test_no_non_r1_channel_is_in_scope(channel):
    assert in_release_scope(channel) is False


@pytest.mark.parametrize("channel", R1_PUBLISH_CHANNELS)
def test_the_r1_channels_stay_in_scope(channel):
    assert in_release_scope(channel) is True


def test_the_filter_preserves_order_because_linkedin_needs_the_wix_url():
    filtered = restrict_to_release_scope([
        ("wix", "W"), ("linkedin", "L"), ("facebook", "F"),
        ("instagram", "I"), ("threads", "T"), ("telegram", "G"),
    ])

    assert filtered == [("wix", "W"), ("linkedin", "L")]


def test_the_authority_imports_no_publisher():
    """Authorization must not depend on implementation, or a publisher can
    never be kept in the repository without becoming reachable."""
    tree = _module("src/publishing/release_scope.py")
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.Import) for alias in node.names
    }

    assert not any("publish" in str(name) for name in imported if name)


# ===========================================================================
# Daily Signal Research — the path that actually published
# ===========================================================================


def test_daily_research_can_only_publish_the_r1_channels():
    from scripts.research.publish_packages import _ALL_PUBLISHERS, _PUBLISHERS

    assert [name for name, _ in _PUBLISHERS] == list(R1_PUBLISH_CHANNELS)
    # the implementations are still here, and still complete
    assert [name for name, _ in _ALL_PUBLISHERS] == [
        "wix", "linkedin", "facebook", "instagram", "threads", "telegram",
    ]


@pytest.mark.parametrize("channel", OBSERVED)
def test_daily_research_cannot_auto_publish_the_channels_it_published(channel):
    """The exact regression: facebook, instagram and telegram, 2026-09-06/07."""
    from scripts.research.publish_packages import _PUBLISHERS, _WITHHELD_CHANNELS

    assert channel not in [name for name, _ in _PUBLISHERS]
    assert channel in _WITHHELD_CHANNELS


def test_daily_research_records_the_withheld_channels_rather_than_omitting_them():
    """A channel that silently disappears from the report is how this hid."""
    from scripts.research.publish_packages import _WITHHELD_CHANNELS

    assert set(_WITHHELD_CHANNELS) == set(NON_R1_PUBLISH_CHANNELS)
    source = Path("scripts/research/publish_packages.py").read_text()
    assert "PublishStatus.SKIPPED" in source
    assert "outside the Release 1 publishing scope" in source


def test_the_research_publisher_list_is_not_a_hand_maintained_literal():
    """#227 item 8: one allowlist, not a copy per path."""
    source = Path("scripts/research/publish_packages.py").read_text()
    tree = _module("scripts/research/publish_packages.py")

    assert "restrict_to_release_scope" in source
    # the only six-channel literal left is the implementation inventory
    six = [names for names in _list_of_channel_pairs(tree) if len(names) == 6]
    assert len(six) == 1, "a second hand-written channel list reappeared"


# ===========================================================================
# The visibility publisher — dormant, and must stay unable to revive
# ===========================================================================


def test_the_visibility_flow_is_scheduled_and_therefore_automatic():
    """Not a manual utility: it runs on its own every Tuesday and Thursday."""
    workflow = yaml.safe_load((WORKFLOWS / "visibility_publish.yml").read_text())
    crons = [entry["cron"] for entry in workflow[True]["schedule"]]

    assert crons == ["0 7 * * 2", "0 7 * * 4"]


@pytest.mark.parametrize("channel", OBSERVED + ("threads",))
def test_the_visibility_flow_cannot_auto_publish_non_r1_channels(channel):
    source = Path("scripts/generate_and_publish_visibility.py").read_text()
    tree = _module("scripts/generate_and_publish_visibility.py")

    assert "restrict_to_release_scope" in source
    # the loop iterates the filtered list, never the full inventory
    loops = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name)
    ]
    assert any(node.iter.id == "publishers" for node in loops)
    assert not any(node.iter.id == "all_publishers" for node in loops)
    assert channel not in R1_PUBLISH_CHANNELS


def test_repairing_the_model_id_cannot_revive_non_r1_publishing():
    """The model-ID error is deliberately NOT fixed here; this proves the fix
    would be safe when someone does make it."""
    source = Path("scripts/generate_and_publish_visibility.py").read_text()

    # authorization sits above the failure, not behind it
    scope_at = source.index("restrict_to_release_scope(all_publishers)")
    loop_at = source.index("for name, publisher in publishers:")
    assert scope_at < loop_at


# ===========================================================================
# Manual utilities keep their publishers — they are not the defect
# ===========================================================================


@pytest.mark.parametrize("script, workflow", [
    ("scripts/publish.py", "publish.yml"),
    ("scripts/live_publish_test.py", "live_publish_test.yml"),
])
def test_manual_publishers_may_still_reach_every_channel(script, workflow):
    """Inspection, not assumption: these have no schedule, so they stay whole."""
    triggers = yaml.safe_load((WORKFLOWS / workflow).read_text())[True]

    assert "schedule" not in triggers, f"{workflow} became automatic"
    assert "workflow_dispatch" in triggers
    assert "telegram" in Path(script).read_text()


def test_the_publisher_implementations_were_not_deleted():
    for module in ("telegram", "instagram", "facebook", "threads"):
        source = Path(f"src/publishing/{module}.py").read_text()
        assert "class " in source and "def publish" in source


# ===========================================================================
# Canonical Monday / Wednesday / Friday unchanged
# ===========================================================================


def test_the_canonical_entrypoint_still_declares_the_same_scope():
    from scripts.generate_and_publish import _NON_R1_PUBLISHERS, _R1_PUBLISHERS

    assert tuple(_R1_PUBLISHERS) == ("wix", "linkedin")
    assert set(_NON_R1_PUBLISHERS) == {
        "facebook", "instagram", "threads", "telegram",
    }


def test_the_canonical_entrypoint_never_constructed_a_non_r1_publisher():
    """The non-R1 classes stay importable there and are never referenced.

    Deliberately left importable: ``test_generate_and_publish.py`` patches each
    class and runs the real ``main()`` to prove none is ever constructed, which
    is a stronger guarantee than an absent import — and it needs the name to be
    patchable. This scenario adds the cheap static half of the same claim.
    """
    tree = _module("scripts/generate_and_publish.py")
    names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for publisher in ("TelegramPublisher", "FacebookPublisher",
                      "InstagramPublisher", "ThreadsPublisher"):
        assert publisher not in names


@pytest.mark.parametrize("workflow, script", [
    ("monday_publish.yml", "scripts/generate_and_publish.py"),
    ("wednesday_golden.yml", "scripts/generate_and_publish.py"),
])
def test_the_canonical_streams_still_run_the_canonical_entrypoint(workflow, script):
    assert script in (WORKFLOWS / workflow).read_text()


def test_the_friday_publisher_reaches_no_channel_of_its_own():
    """It shells out to the canonical entrypoint; it constructs no publisher."""
    tree = _module("scripts/scheduled_publish.py")
    names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }

    assert not any(name.endswith("Publisher") for name in names)


# ===========================================================================
# #222 is not quietly restored to do this job
# ===========================================================================


def test_the_withdrawn_overlap_rule_did_not_come_back_as_the_fix():
    """The right fix is authorization. A sentence-overlap check must not
    reappear as a substitute — that accident is what hid this for weeks."""
    for path in AUTOMATIC_PATHS + ("src/publishing/release_scope.py",):
        source = Path(path).read_text()
        assert "repeated_cross_platform_phrases" not in source
        assert "Cross-platform copy detected" not in source
        for threshold in ("SequenceMatcher", "difflib", "similarity",
                          "overlap_ratio", "paraphrase"):
            assert threshold not in source, f"{path}: {threshold}"


def test_a_shared_hook_across_surfaces_is_still_accepted():
    """#221 semantics untouched: recurrence alone rejects nothing."""
    from scripts.research.publish_packages import _validate_package

    hook = ("Investors cheered not because ChargePoint promised more growth, "
            "but because it finally slowed down.")
    bodies = {
        surface: f"{hook} A body written for {surface} in its own shape here."
        for surface in ("blog", "linkedin", "facebook", "instagram", "telegram")
    }

    _validate_package(bodies, [f"{hook} One.", "Two post here.", "Three post."])


# ===========================================================================
# Nothing here can reach a provider
# ===========================================================================


def test_no_scenario_here_needs_a_credential_or_a_network_call():
    """Read the imports, not the text — a source-grep of this file would match
    its own list of forbidden names."""
    tree = _module(__file__)
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not imported & {"requests", "httpx", "urllib", "openai", "socket", "http"}
    # and nothing here reads an environment variable
    calls = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "getenv" not in calls and "environ" not in calls


def test_importing_the_authority_constructs_nothing():
    """It must be safe to import anywhere — including from a test with no
    environment at all."""
    import importlib

    module = importlib.import_module("src.publishing.release_scope")

    assert not [
        name for name in dir(module)
        if name.endswith("Publisher") or name.endswith("_INSTANCE")
    ]
