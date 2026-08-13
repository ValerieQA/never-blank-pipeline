"""Story #10 acceptance gate: replaceable strategy meaning and run isolation.

Run only this gate with::

    python3 -m pytest -m story10

All provider calls are replaced at declared boundaries.  No credentials or
network access are required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from scripts.research.prepare_content import _generate_content_package
from src.editorial.decision_lens_lite import generate_decision_lens
from src.editorial.never_blank_voice import finalize_article
from src.editorial.platform_composer import compose_platforms
from src.strategy.business_config import (
    BusinessStrategyConfiguration,
    BusinessStrategyConfigurationInactiveError,
    BusinessStrategyConfigurationNotFound,
    BusinessStrategyConfigurationParseError,
    BusinessStrategyConfigurationValidationError,
    load_business_strategy_configuration,
)
from src.strategy.execution_context import (
    ConfigurationIdentity,
    StrategyExecutionContext,
)

import test_generate_and_publish as harness


pytestmark = pytest.mark.story10

PRODUCTION_CONFIG = Path("strategy/current/business_strategy.json")
ALTERNATE_CONFIG = Path("tests/fixtures/business_strategy_alternate.json")


def _configuration(path: Path) -> BusinessStrategyConfiguration:
    return load_business_strategy_configuration(path)


def _execution(configuration: BusinessStrategyConfiguration) -> StrategyExecutionContext:
    return StrategyExecutionContext.from_configuration(configuration)


def _lens_output() -> str:
    return json.dumps({
        "core_pattern": "bounded pattern",
        "owner_system_objective": "bounded objective",
        "delivery_vs_presence_conflict": "bounded conflict",
        "customer_memory_consequence": "bounded consequence",
        "structural_cause": "bounded cause",
        "never_blank_insight": "bounded insight",
    })


def _voice_output() -> str:
    return json.dumps({
        "echo_candidates": ["A bounded close."],
        "echo_line": "A bounded close.",
        "cta_line": "Compare one workflow.",
        "checklist_pass": True,
        "checklist_notes": "",
    })


def test_alternate_fixture_passes_strict_contract_without_core_leakage():
    production = _configuration(PRODUCTION_CONFIG)
    alternate = _configuration(ALTERNATE_CONFIG)

    assert alternate.configuration_id != production.configuration_id
    assert alternate.configuration_version != production.configuration_version
    assert alternate.business != production.business
    assert alternate.audiences != production.audiences
    assert alternate.positioning != production.positioning
    assert alternate.brand_editorial != production.brand_editorial
    assert alternate.calls_to_action != production.calls_to_action
    assert alternate.channels.wix != production.channels.wix
    assert alternate.channels.linkedin != production.channels.linkedin
    assert set(alternate.channels.model_dump()) == {"wix", "linkedin"}

    serialized = json.dumps(alternate.model_dump(mode="json")).casefold()
    for forbidden in ("api_key", "credential", "provider_payload", "access_token"):
        assert forbidden not in serialized


@pytest.mark.parametrize("failure", ["missing", "corrupt", "inactive", "blank", "unknown"])
def test_strict_loading_fails_closed_without_defaults(tmp_path: Path, failure: str):
    path = tmp_path / "business_strategy.json"
    if failure == "missing":
        with pytest.raises(BusinessStrategyConfigurationNotFound):
            load_business_strategy_configuration(path)
        return
    if failure == "corrupt":
        path.write_text("{not-json", encoding="utf-8")
        expected = BusinessStrategyConfigurationParseError
    else:
        data = json.loads(ALTERNATE_CONFIG.read_text(encoding="utf-8"))
        if failure == "inactive":
            data["status"] = "inactive"
            expected = BusinessStrategyConfigurationInactiveError
        elif failure == "blank":
            data["configuration_id"] = "   "
            expected = BusinessStrategyConfigurationValidationError
        else:
            data["unknown_contract_field"] = True
            expected = BusinessStrategyConfigurationValidationError
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(expected):
        load_business_strategy_configuration(path)


def test_alternate_configuration_changes_actual_consumer_inputs():
    production = _execution(_configuration(PRODUCTION_CONFIG))
    alternate = _execution(_configuration(ALTERNATE_CONFIG))
    executions = (
        (production, production.research.select_audience("agencies")),
        (alternate, alternate.research.select_audience("operators")),
    )

    research_prompts: list[str] = []
    lens_prompts: list[str] = []
    voice_prompts: list[str] = []
    channel_inputs: list[dict[str, tuple[str, ...]]] = []

    for execution, research_audience in executions:
        editorial_audience = execution.decision_lens_editorial.select_audience(
            research_audience.audience_id
        )
        with mock.patch(
            "scripts.research.prepare_content.chat", return_value="{}"
        ) as research_chat:
            _generate_content_package({}, execution.research, research_audience)
        research_prompts.append(research_chat.call_args.args[1])

        with mock.patch(
            "src.editorial.decision_lens_lite.chat", return_value=_lens_output()
        ) as lens_chat:
            generate_decision_lens(
                {}, execution.decision_lens_editorial, editorial_audience
            )
        lens_prompts.append(lens_chat.call_args.kwargs["user"])

        selected_cta = execution.decision_lens_editorial.cta("reflection")
        with mock.patch(
            "src.editorial.never_blank_voice.chat", return_value=_voice_output()
        ) as voice_chat:
            voice_result = finalize_article(
                {}, None, {}, {}, {}, {}, {}, "reflection",
                execution.decision_lens_editorial,
                editorial_audience,
                selected_cta,
            )
        voice_prompts.append(voice_chat.call_args.kwargs["user"])
        assert voice_result["configured_cta"]["rules"] == list(selected_cta.rules)

        captured: dict[str, tuple[str, ...]] = {}

        def compose(structured, format_key, cta_mode="none", strategy_rules=()):
            captured[format_key] = strategy_rules
            return {"word_count": 1, "body": "accepted", "echo_included": False}

        with mock.patch(
            "src.editorial.platform_composer._compose_one", side_effect=compose
        ):
            compose_platforms(
                {}, wix_strategy=execution.wix, linkedin_strategy=execution.linkedin
            )
        channel_inputs.append(captured)

    assert research_prompts[0] != research_prompts[1]
    assert lens_prompts[0] != lens_prompts[1]
    assert voice_prompts[0] != voice_prompts[1]
    assert executions[0][0].research.positioning.statement in research_prompts[0]
    assert executions[1][0].research.positioning.statement in research_prompts[1]
    assert executions[0][0].decision_lens_editorial.positioning.proof_points[0] in lens_prompts[0]
    assert executions[1][0].decision_lens_editorial.positioning.proof_points[0] in lens_prompts[1]
    assert executions[0][0].decision_lens_editorial.brand_editorial.voice[0] in voice_prompts[0]
    assert executions[1][0].decision_lens_editorial.brand_editorial.voice[0] in voice_prompts[1]
    assert channel_inputs[0]["long"] != channel_inputs[1]["long"]
    assert channel_inputs[0]["medium"] != channel_inputs[1]["medium"]
    for captured in channel_inputs:
        assert captured["long"]
        assert captured["medium"]
        assert captured["long"] != captured["medium"]
    print(
        "stage-trace:",
        production.identity.configuration_id,
        "and",
        alternate.identity.configuration_id,
        "changed research/decision-lens/voice/wix/linkedin inputs",
    )


def _run_dry_configuration(
    packages_dir: Path,
    configuration: BusinessStrategyConfiguration,
    audience_term: str,
) -> Path:
    argv, patches = harness._base_patches(dry_run=True)
    patches["PACKAGES_DIR"] = packages_dir
    patches["load_business_strategy_configuration"] = mock.MagicMock(
        return_value=configuration
    )
    patches["_load_signal"] = mock.MagicMock(
        return_value=dict(harness._RAW_SIGNAL, TARGET_AUDIENCE=audience_term)
    )
    before = set(packages_dir.rglob("generated.json"))
    with mock.patch("sys.argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 0
    created = set(packages_dir.rglob("generated.json")) - before
    assert len(created) == 1
    return created.pop().parent


def test_two_configurations_preserve_distinct_hashes_and_exact_snapshots(tmp_path: Path):
    production = _configuration(PRODUCTION_CONFIG)
    alternate = _configuration(ALTERNATE_CONFIG)
    production_run = _run_dry_configuration(tmp_path, production, "agencies")
    alternate_run = _run_dry_configuration(tmp_path, alternate, "operators")

    expected = {
        production_run: (production, ConfigurationIdentity.from_configuration(production)),
        alternate_run: (alternate, ConfigurationIdentity.from_configuration(alternate)),
    }
    hashes = set()
    for run_dir, (configuration, identity) in expected.items():
        snapshot_path = run_dir / "business_strategy.json"
        generated_path = run_dir / "generated.json"
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot = BusinessStrategyConfiguration.model_validate_json(snapshot_bytes)
        generated = json.loads(generated_path.read_text(encoding="utf-8"))
        assert snapshot == configuration
        assert ConfigurationIdentity.from_configuration(snapshot) == identity
        assert generated["configuration_identity"] == identity.model_dump()
        assert snapshot_path.read_bytes() == snapshot_bytes
        hashes.add(identity.configuration_hash)
    assert len(hashes) == 2
    print(
        "configuration-identities:",
        production.configuration_id,
        ConfigurationIdentity.from_configuration(production).configuration_hash,
        alternate.configuration_id,
        ConfigurationIdentity.from_configuration(alternate).configuration_hash,
    )


@pytest.mark.parametrize("foreign_part", ["generated", "snapshot"])
def test_cross_configuration_reuse_fails_before_generation_or_publishers(
    tmp_path: Path, foreign_part: str
):
    alternate = _configuration(ALTERNATE_CONFIG)
    alternate_identity = ConfigurationIdentity.from_configuration(alternate).model_dump()
    package = harness._valid_package()
    if foreign_part == "snapshot":
        package["configuration_identity"] = alternate_identity
    source_generated = harness._write_package(tmp_path, package)
    source_snapshot = source_generated.with_name("business_strategy.json")
    source_generated_before = source_generated.read_bytes()
    source_snapshot_before = source_snapshot.read_bytes()

    argv, patches = harness._base_patches(dry_run=False, from_package=True)
    patches["PACKAGES_DIR"] = tmp_path
    patches["load_business_strategy_configuration"] = mock.MagicMock(
        return_value=alternate
    )
    patches["_load_signal"] = mock.MagicMock(
        return_value=dict(harness._RAW_SIGNAL, TARGET_AUDIENCE="operators")
    )
    generation = patches["generate_article"]
    report = patches["_emit_run_report"]
    publisher = mock.MagicMock()
    with mock.patch("sys.argv", argv), mock.patch.multiple(gap, **patches), \
         mock.patch.object(gap, "WixPublisher", publisher), \
         mock.patch.object(gap, "LinkedInPublisher", publisher):
        assert main() == 1

    generation.assert_not_called()
    publisher.assert_not_called()
    report.assert_not_called()
    assert source_generated.read_bytes() == source_generated_before
    assert source_snapshot.read_bytes() == source_snapshot_before
    assert not list(tmp_path.rglob("publication_results.json"))

    # A rejected reuse may have a run directory containing its create-once
    # configuration snapshot.  Without generated/publication results or a
    # completed report it is not a successful or complete artifact set.
    orphan_dirs = [
        path for path in tmp_path.rglob("business_strategy.json")
        if path != source_snapshot
    ]
    assert len(orphan_dirs) == 1
    orphan_run = orphan_dirs[0].parent
    assert not (orphan_run / "generated.json").exists()
    assert not (orphan_run / "publication_results.json").exists()
    print("rejected-mismatch:", foreign_part, "source unchanged; no completed artifact set")
