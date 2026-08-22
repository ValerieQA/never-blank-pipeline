"""Issue #175: R1 pays only for the surfaces it publishes.

Release 1 publishes Wix + LinkedIn. Before this change every run also
composed `reading` (Facebook), `instagram` and `short` — three model calls
whose output R1 never publishes (`short` had no consumer at all) — plus an
Instagram hashtag call, and composited/uploaded images for four inactive
platforms. These scenarios prove the canonical path now executes only the
active surfaces, the inactive ones cost zero transport and zero image work,
and the architecture for future channels — format tables, package fields,
default all-formats behaviour — is intact, not deleted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial import platform_composer
from src.utils import llm_client
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_research_artifact_lifecycle import ReadyProvider


def _composer_chat_capture(calls: list):
    def fake(system: str, user: str, json_mode: bool = False, model: str | None = None):
        format_key = next(
            line.split(":", 1)[1].strip()
            for line in user.splitlines() if line.startswith("FORMAT:")
        )
        calls.append((format_key, model))
        counts = {"long": 450, "reading": 400, "medium": 160, "instagram": 100, "short": 40}
        body = "Evidence-led opening. " + " ".join(
            f"{format_key}{i}" for i in range(counts[format_key])
        )
        return json.dumps({"body": body, "echo_included": False,
                           "title": "T" if format_key == "long" else None})
    return fake


# ===========================================================================
# 3 & 6. The composer executes requested formats only; the tables survive
# ===========================================================================


def test_the_r1_format_set_makes_exactly_two_composition_transports(monkeypatch):
    calls: list = []
    monkeypatch.setattr(platform_composer, "chat", _composer_chat_capture(calls))

    result = platform_composer.compose_platforms(
        {"hook": "h", "discovery": {}}, formats=("long", "medium"),
    )

    assert [f for f, _ in calls] == ["long", "medium"]   # nothing else ran
    assert set(result) == {"long", "medium"}             # nothing else exists


def test_the_default_keeps_the_full_format_architecture(monkeypatch):
    calls: list = []
    monkeypatch.setattr(platform_composer, "chat", _composer_chat_capture(calls))

    result = platform_composer.compose_platforms({"hook": "h", "discovery": {}})

    assert [f for f, _ in calls] == list(platform_composer.ALL_FORMATS)
    assert set(result) == set(platform_composer.ALL_FORMATS)


def test_future_channel_definitions_remain_configurable():
    # the format tables are complete: a future channel re-enables by passing
    # its format, never by restoring deleted code
    assert platform_composer.ALL_FORMATS == (
        "long", "reading", "medium", "instagram", "short",
    )
    for table in (platform_composer._BLOCK_TABLE,
                  platform_composer._WORD_RANGE,
                  platform_composer._FORMAT_CONSTRAINTS):
        assert set(table) == set(platform_composer.ALL_FORMATS)


def test_an_unknown_format_is_refused_not_ignored(monkeypatch):
    monkeypatch.setattr(platform_composer, "chat", _composer_chat_capture([]))
    with pytest.raises(ValueError, match="unknown composer format"):
        platform_composer.compose_platforms(
            {"hook": "h", "discovery": {}}, formats=("long", "tiktok"),
        )


# ===========================================================================
# 10. #173 routing still routes the two active surfaces correctly
# ===========================================================================


def test_reduced_formats_still_route_article_and_social_models(monkeypatch):
    monkeypatch.setenv("NB_ARTICLE_MODEL", "test-article-model")
    monkeypatch.setenv("NB_SOCIAL_MODEL", "test-social-model")
    calls: list = []
    monkeypatch.setattr(platform_composer, "chat", _composer_chat_capture(calls))

    platform_composer.compose_platforms(
        {"hook": "h", "discovery": {}}, formats=("long", "medium"),
    )

    assert calls == [("long", "test-article-model"),
                     ("medium", "test-social-model")]


# ===========================================================================
# 1, 2, 3, 5. The canonical entrypoint: active surfaces only, contract intact
# ===========================================================================


def _reduced_entry(tmp_path):
    argv, patches = _entry_patches(tmp_path)
    evaluator, _ = _evaluator(_model_output())
    captured: dict = {}

    def article_without_inactive_surfaces(*args, **kwargs):
        captured["composer_formats"] = kwargs.get("composer_formats")
        return {
            "platforms": {
                "long": {"body": "Blog body text.", "title": "T"},
                "medium": {"body": "LinkedIn post text."},
            },
            "structured_article": legacy._FAKE_ARTICLE["structured_article"],
        }

    patches["generate_article"].side_effect = article_without_inactive_surfaces
    hashtag_calls: list = []
    with mock.patch.object(sys, "argv", argv), \
            mock.patch.multiple(gap, **patches), \
            mock.patch.object(gap, "generate_hashtags",
                              side_effect=lambda signal, platform:
                              hashtag_calls.append(platform) or []):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, captured, hashtag_calls, tmp_path


def test_the_canonical_run_requests_only_the_r1_formats(tmp_path):
    code, captured, hashtag_calls, _ = _reduced_entry(tmp_path)

    assert code == 0
    # the entrypoint asked the engine for exactly the active R1 formats
    assert captured["composer_formats"] == ("long", "medium")
    # and the only hashtag transport was for the published LinkedIn surface
    assert hashtag_calls == ["linkedin"]


def test_the_package_contract_is_intact_with_inactive_surfaces_empty(tmp_path):
    _, _, _, tmp = _reduced_entry(tmp_path)

    pkg = json.loads(next(tmp.glob("*/runs/*/generated.json")).read_text())
    # active surfaces: present and non-blank — validation unweakened
    assert pkg["blog_article"].strip()
    assert pkg["linkedin_post"].strip()
    # inactive prose surfaces: present (schema intact), empty (not composed)
    assert pkg["facebook_post"] == ""
    assert pkg["instagram_caption"] == ""
    # deterministic assemblies remain (zero model cost)
    assert isinstance(pkg["threads_sequence"], list)
    assert isinstance(pkg["telegram_text"], str)


def test_monday_and_wednesday_share_the_single_reduced_call_site():
    source = Path("scripts/generate_and_publish.py").read_text()
    # one canonical generate_article invocation, carrying the R1 formats —
    # both weekday workflows run this same entrypoint; there is no per-role
    # or per-weekday format branching anywhere
    assert source.count("composer_formats=_R1_COMPOSER_FORMATS") == 1
    assert source.count("composer_formats=") == 1
    assert '_R1_COMPOSER_FORMATS = ("long", "medium")' in source
    assert "weekday" not in source.split('_R1_COMPOSER_FORMATS = ("long", "medium")')[1][:200]


# ===========================================================================
# 4. Inactive surfaces cause zero image work
# ===========================================================================


def test_image_reuse_builds_assets_for_active_platforms_only():
    from scripts.research.prepare_content import _build_image_plan

    library = {
        "sig-img": {
            "url": "https://cdn.example/img.png",
            "design_version": _current_design_version(),
            "visual_family": "f", "hook_text": "h",
        }
    }
    signal = {"SIGNAL_ID": "sig-img", "HEADLINE": "h"}

    plan, _ = _build_image_plan(signal, library, platforms=["blog", "linkedin"])

    assert set(plan["platform_images"]) == {"blog", "linkedin"}
    assert plan["reused_images"] == 2      # not 6


def _current_design_version():
    from src.publishing.image_pipeline import CURRENT_DESIGN_VERSION
    return CURRENT_DESIGN_VERSION


def test_the_entrypoint_scopes_image_platforms_to_r1():
    source = Path("scripts/generate_and_publish.py").read_text()
    assert '_R1_IMAGE_PLATFORMS = ["blog", "linkedin"]' in source
    assert "platforms=_R1_IMAGE_PLATFORMS" in source


def test_daily_research_keeps_the_full_platform_set():
    # prepare_content_packages defaults to every platform: the daily
    # research pipeline is not redesigned by this change
    import inspect
    from scripts.research.prepare_content import PLATFORMS, prepare_content_packages

    assert PLATFORMS == ["blog", "linkedin", "facebook", "instagram",
                         "threads", "stories"]
    assert inspect.signature(prepare_content_packages).parameters[
        "platforms"].default is None


# ===========================================================================
# 7–9. The #170/#171/#172 contracts are untouched (spot pins; full suites
# run in the same battery)
# ===========================================================================


def test_cost_safety_contracts_survive_the_reduction(monkeypatch):
    import os
    from src.editorial.source_eligibility import SourceEligibilityError
    from src.run.call_budget import RunCallBudget, RunCallBudgetExceededError, activate_call_budget

    # #170: scope classification intact
    assert SourceEligibilityError("x").scope == "candidate"
    # #171: a reduced-format composition still charges the budget
    class _NeverReached:
        def __getattr__(self, name):
            raise AssertionError("transport must not be reached")

    monkeypatch.setattr(llm_client, "_client", _NeverReached())
    budget = RunCallBudget(limit=1)
    budget.spend()
    with activate_call_budget(budget):
        with pytest.raises(RunCallBudgetExceededError):
            llm_client.chat("s", "u")
    monkeypatch.setattr(llm_client, "_client", None)
    # #172: this test runs with credentials stripped
    assert os.environ.get("NB_OPENAI_API_KEY") is None
