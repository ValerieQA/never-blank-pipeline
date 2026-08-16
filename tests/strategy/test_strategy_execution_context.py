"""Task #41 typed strategy views and canonical R1 wiring tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

import scripts.generate_and_publish as gap
import src.editorial.platform_composer as platform_composer
from scripts.generate_and_publish import main
from src.publishing.result import PublishResult, PublishStatus
from src.strategy.business_config import (
    BusinessStrategyConfigurationNotFound,
    load_business_strategy_configuration,
)
from src.strategy.execution_context import (
    ConfigurationIdentity,
    DecisionLensEditorialStrategyView,
    LinkedInStrategyView,
    ResearchStrategyView,
    StrategyExecutionContext,
    StrategyExecutionError,
    VisualStrategyView,
    WixStrategyView,
    require_configuration_identity,
)
from src.visual import VisualArtifactRequest

import test_generate_and_publish as harness


PRODUCTION_CONFIG = Path("strategy/current/business_strategy.json")


def _execution() -> StrategyExecutionContext:
    return StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration(PRODUCTION_CONFIG)
    )


def test_execution_context_exposes_only_declared_immutable_views():
    execution = _execution()

    assert isinstance(execution.research, ResearchStrategyView)
    assert isinstance(
        execution.decision_lens_editorial, DecisionLensEditorialStrategyView
    )
    assert isinstance(execution.wix, WixStrategyView)
    assert isinstance(execution.linkedin, LinkedInStrategyView)
    assert isinstance(execution.visual, VisualStrategyView)
    assert execution.wix.rules != execution.linkedin.rules
    def field_names(value):
        if isinstance(value, dict):
            return set(value) | set().union(
                *(field_names(item) for item in value.values()), set()
            )
        if isinstance(value, (list, tuple)):
            return set().union(*(field_names(item) for item in value), set())
        return set()

    names = field_names(execution.model_dump())
    assert {"api_key", "token", "credentials", "provider_payload"}.isdisjoint(names)

    with pytest.raises(ValidationError):
        execution.identity.configuration_version = "stale"


def test_mismatched_view_identity_fails_closed():
    execution = _execution()
    stale = ConfigurationIdentity(
        schema_version=execution.identity.schema_version,
        configuration_id=execution.identity.configuration_id,
        configuration_version="stale",
        configuration_hash=execution.identity.configuration_hash,
    )

    with pytest.raises(StrategyExecutionError, match="identity mismatch"):
        require_configuration_identity(execution.identity, stale, "editorial")


def test_platform_composer_uses_distinct_wix_and_linkedin_rules():
    execution = _execution()
    calls = []

    def compose(structured, format_key, cta_mode="none", strategy_rules=()):
        calls.append((format_key, strategy_rules))
        return {"word_count": 1, "body": "ok", "echo_included": False}

    with mock.patch.object(platform_composer, "_compose_one", side_effect=compose):
        platform_composer.compose_platforms(
            {},
            wix_strategy=execution.wix,
            linkedin_strategy=execution.linkedin,
        )

    rules_by_format = dict(calls)
    assert rules_by_format["long"]
    assert rules_by_format["medium"]
    assert rules_by_format["long"] != rules_by_format["medium"]
    assert rules_by_format["reading"] == ()
    assert rules_by_format["instagram"] == ()
    assert rules_by_format["short"] == ()


def test_missing_business_configuration_blocks_before_campaign_or_signal():
    argv, patches = harness._base_patches(dry_run=True)
    campaign_loader = patches["load_active_strategy"]
    signal_loader = patches["_load_signal"]
    patches["load_business_strategy_configuration"] = mock.MagicMock(
        side_effect=BusinessStrategyConfigurationNotFound("missing config")
    )

    with mock.patch("sys.argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 1

    campaign_loader.assert_not_called()
    signal_loader.assert_not_called()


def test_same_configuration_identity_reaches_every_r1_boundary(tmp_path):
    argv, patches = harness._base_patches(dry_run=False)
    patches["PACKAGES_DIR"] = tmp_path
    expected = _execution().identity

    research_contexts = []

    def build_research(assignment, raw_signal, run_ctx):
        rc = harness._make_rc_mock(run_ctx.run_id)
        research_contexts.append(rc)
        return rc

    patches["_build_legacy_research_context"] = build_research

    editorial_generator = patches["generate_article"]
    visual_requests: list[VisualArtifactRequest] = []

    def build_visual(**kwargs):
        request = VisualArtifactRequest(**kwargs)
        visual_requests.append(request)
        return request

    wix_result = PublishResult(
        platform="wix",
        status=PublishStatus.PUBLISHED,
        external_id="wix-id",
        url="https://example.com/wix",
    )
    linkedin_result = PublishResult(
        platform="linkedin",
        status=PublishStatus.PUBLISHED,
        external_id="linkedin-id",
        url="https://example.com/linkedin",
    )
    wix = mock.MagicMock()
    wix.publish.return_value = wix_result
    linkedin = mock.MagicMock()
    linkedin.publish.return_value = linkedin_result

    with mock.patch("sys.argv", argv), \
         mock.patch.multiple(gap, **patches), \
         mock.patch.object(gap, "VisualArtifactRequest", side_effect=build_visual), \
         mock.patch.object(gap, "WixPublisher", return_value=wix), \
         mock.patch.object(gap, "LinkedInPublisher", return_value=linkedin):
        assert main() == 0

    assert research_contexts[0].strategy_view.identity == expected

    editorial_view = editorial_generator.call_args.kwargs["strategy_context"]
    assert isinstance(editorial_view, DecisionLensEditorialStrategyView)
    assert editorial_view.identity == expected
    assert editorial_generator.call_args.kwargs["wix_strategy"].identity == expected
    assert editorial_generator.call_args.kwargs["linkedin_strategy"].identity == expected

    assert len(visual_requests) == 1
    assert visual_requests[0].strategy_view.identity == expected

    wix_view = wix.publish.call_args.kwargs["strategy_view"]
    linkedin_view = linkedin.publish.call_args.kwargs["strategy_view"]
    assert isinstance(wix_view, WixStrategyView)
    assert isinstance(linkedin_view, LinkedInStrategyView)
    assert wix_view.identity == linkedin_view.identity == expected
    assert wix_view.rules != linkedin_view.rules

    # Issue #101: each channel receives its own frozen canonical package;
    # both must carry the one authoritative configuration identity of the run.
    wix_package = wix.publish.call_args.args[0]
    linkedin_package = linkedin.publish.call_args.args[0]
    assert wix_package is not linkedin_package
    assert wix_package.run_id == linkedin_package.run_id

    generated = next(tmp_path.rglob("generated.json"))
    assert json.loads(generated.read_text())["configuration_identity"] == expected.model_dump()


def test_stale_package_configuration_blocks_before_visual_and_publishers(tmp_path):
    package = harness._valid_package()
    package["configuration_identity"]["configuration_version"] = "stale"
    harness._write_package(tmp_path, package)

    argv, patches = harness._base_patches(dry_run=False, from_package=True)
    patches["PACKAGES_DIR"] = tmp_path
    visual = mock.MagicMock()
    wix = mock.MagicMock()
    linkedin = mock.MagicMock()

    with mock.patch("sys.argv", argv), \
         mock.patch.multiple(gap, **patches), \
         mock.patch.object(gap, "VisualArtifactRequest", visual), \
         mock.patch.object(gap, "WixPublisher", wix), \
         mock.patch.object(gap, "LinkedInPublisher", linkedin):
        assert main() == 1

    visual.assert_not_called()
    wix.assert_not_called()
    linkedin.assert_not_called()
    assert not list(tmp_path.rglob("publication_results.json"))
