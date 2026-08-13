"""Task #42 deterministic identity, immutable snapshot, and reuse gates."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.artifacts import (
    ArtifactCollisionError,
    write_business_strategy_snapshot,
)
from src.strategy.business_config import BusinessStrategyConfiguration
from src.strategy.execution_context import (
    ConfigurationIdentity,
    canonical_configuration_bytes,
    configuration_hash,
)

import test_generate_and_publish as harness


CONFIG_PATH = Path("strategy/current/business_strategy.json")


def _raw() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _model(data: dict | None = None) -> BusinessStrategyConfiguration:
    return BusinessStrategyConfiguration.model_validate(data or _raw())


def test_canonical_hash_ignores_key_order_and_insignificant_formatting(tmp_path):
    raw = _raw()
    reordered = {key: raw[key] for key in reversed(raw)}
    compact = tmp_path / "compact.json"
    pretty = tmp_path / "pretty.json"
    compact.write_text(json.dumps(raw, separators=(",", ":")), encoding="utf-8")
    pretty.write_text(json.dumps(reordered, indent=7), encoding="utf-8")

    left = _model(json.loads(compact.read_text()))
    right = _model(json.loads(pretty.read_text()))
    assert canonical_configuration_bytes(left) == canonical_configuration_bytes(right)
    assert configuration_hash(left) == configuration_hash(right)
    assert configuration_hash(left).startswith("sha256:")


def test_same_validated_model_hashes_repeatedly_and_material_change_differs():
    configuration = _model()
    assert configuration_hash(configuration) == configuration_hash(configuration)
    changed = _raw()
    changed["positioning"]["statement"] += " materially changed"
    assert configuration_hash(_model(changed)) != configuration_hash(configuration)


def test_snapshot_validates_and_hashes_to_recorded_identity(tmp_path):
    configuration = _model()
    run_dir = tmp_path / "sig" / "runs" / "run"
    write_business_strategy_snapshot(run_dir, configuration.model_dump(mode="json"))
    snapshot = _model(json.loads((run_dir / "business_strategy.json").read_text()))
    identity = ConfigurationIdentity.from_configuration(configuration)
    assert ConfigurationIdentity.from_configuration(snapshot) == identity


def test_snapshot_is_create_once_and_current_changes_cannot_rewrite_it(tmp_path):
    original = _model().model_dump(mode="json")
    run_dir = tmp_path / "sig" / "runs" / "run"
    write_business_strategy_snapshot(run_dir, original)
    path = run_dir / "business_strategy.json"
    before = path.read_bytes()
    changed = dict(original)
    changed["configuration_version"] = "later"
    with pytest.raises(ArtifactCollisionError):
        write_business_strategy_snapshot(run_dir, changed)
    assert path.read_bytes() == before


def test_failed_snapshot_write_leaves_no_final_or_temporary_file(tmp_path):
    run_dir = tmp_path / "sig" / "runs" / "run"
    with pytest.raises(TypeError):
        write_business_strategy_snapshot(run_dir, {"bad": object()})
    assert not (run_dir / "business_strategy.json").exists()
    assert not list(run_dir.glob(".tmp_*.json"))


def test_canonical_run_binds_identity_and_snapshots_before_generation(tmp_path):
    argv, patches = harness._base_patches(dry_run=True)
    patches["PACKAGES_DIR"] = tmp_path
    events: list[str] = []
    real_write = gap.write_business_strategy_snapshot
    patches["write_business_strategy_snapshot"] = mock.MagicMock(
        side_effect=lambda *args: (events.append("snapshot"), real_write(*args))[1]
    )
    patches["generate_article"] = mock.MagicMock(
        side_effect=lambda *args, **kwargs: (
            events.append("generation"), harness._FAKE_ARTICLE
        )[1]
    )

    with mock.patch("sys.argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 0

    call = patches["write_business_strategy_snapshot"].call_args
    assert events.index("snapshot") < events.index("generation")
    snapshot = _model(call.args[1])
    generated = json.loads(next(tmp_path.rglob("generated.json")).read_text())
    assert ConfigurationIdentity.from_configuration(snapshot).model_dump() == generated[
        "configuration_identity"
    ]
    assert set(generated["configuration_identity"]) == {
        "configuration_id", "configuration_version", "schema_version", "configuration_hash"
    }


def test_from_package_exact_snapshot_identity_is_accepted_and_source_unchanged(tmp_path):
    package = harness._valid_package()
    generated_path = harness._write_package(tmp_path, package)
    source_snapshot = generated_path.with_name("business_strategy.json")
    before = source_snapshot.read_bytes()
    argv, patches = harness._base_patches(dry_run=True, from_package=True)
    patches["PACKAGES_DIR"] = tmp_path
    with mock.patch("sys.argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 0
    assert source_snapshot.read_bytes() == before


def test_from_package_missing_snapshot_fails_before_downstream_side_effects(tmp_path):
    generated_path = harness._write_package(tmp_path)
    generated_path.with_name("business_strategy.json").unlink()
    _assert_reuse_blocked(tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("configuration_id", "other"),
        ("configuration_version", "other"),
        ("schema_version", "other"),
        ("configuration_hash", "sha256:" + "0" * 64),
    ],
)
def test_from_package_each_identity_mismatch_fails_before_side_effects(
    tmp_path, field, value
):
    package = harness._valid_package()
    package["configuration_identity"][field] = value
    harness._write_package(tmp_path, package)
    _assert_reuse_blocked(tmp_path)


def test_from_package_missing_hash_fails_before_side_effects(tmp_path):
    package = harness._valid_package()
    del package["configuration_identity"]["configuration_hash"]
    harness._write_package(tmp_path, package)
    _assert_reuse_blocked(tmp_path)


def _assert_reuse_blocked(tmp_path: Path) -> None:
    argv, patches = harness._base_patches(dry_run=False, from_package=True)
    patches["PACKAGES_DIR"] = tmp_path
    generation = patches["generate_article"]
    image = mock.MagicMock()
    publisher = mock.MagicMock()
    history = patches["append_published_entry"]
    with mock.patch("sys.argv", argv), mock.patch.multiple(gap, **patches), \
         mock.patch.object(gap, "VisualArtifactRequest", image), \
         mock.patch.object(gap, "WixPublisher", publisher), \
         mock.patch.object(gap, "LinkedInPublisher", publisher):
        assert main() == 1
    generation.assert_not_called()
    image.assert_not_called()
    publisher.assert_not_called()
    history.assert_not_called()
    assert not list(tmp_path.rglob("publication_results.json"))
