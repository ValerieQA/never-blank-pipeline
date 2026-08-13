"""Task #28 behavioral tests for immutable run-scoped artifacts."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from unittest import mock

import pytest

from src.artifacts import (
    ArtifactCollisionError,
    atomic_write_json,
    load_run_generated,
    resolve_run_dir,
    write_generated_json,
    write_publication_results_json,
)
from src.publishing.result import PublishResult, PublishStatus

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from tests.test_run_identity import (
    _SIGNAL_ID as CANONICAL_SIGNAL_ID,
    _base_patches,
    _valid_package,
)


SIGNAL_ID = "signal-001"
RUN_A = "11111111-2222-4333-8444-555555555555"
RUN_B = "22222222-3333-4444-9555-666666666666"


@pytest.mark.parametrize(
    "value",
    ["", "   ", "..", "../escape", "a/b", r"a\b", "/absolute", None, 7],
)
def test_unsafe_path_components_are_rejected(tmp_path, value):
    with pytest.raises(ValueError):
        resolve_run_dir(tmp_path, value, RUN_A)
    with pytest.raises(ValueError):
        resolve_run_dir(tmp_path, SIGNAL_ID, value)


@pytest.mark.story9
def test_two_runs_for_same_signal_preserve_both_generated_artifacts(tmp_path):
    run_a = resolve_run_dir(tmp_path, SIGNAL_ID, RUN_A)
    run_b = resolve_run_dir(tmp_path, SIGNAL_ID, RUN_B)
    write_generated_json(run_a, {"signal_id": SIGNAL_ID, "run_id": RUN_A, "body": "A"})
    write_generated_json(run_b, {"signal_id": SIGNAL_ID, "run_id": RUN_B, "body": "B"})

    assert load_run_generated(tmp_path, SIGNAL_ID, RUN_A)["body"] == "A"
    assert load_run_generated(tmp_path, SIGNAL_ID, RUN_B)["body"] == "B"
    assert run_a != run_b


@pytest.mark.story9
def test_generated_and_publication_results_are_separate_immutable_files(tmp_path):
    run_dir = resolve_run_dir(tmp_path, SIGNAL_ID, RUN_A)
    generated = {"signal_id": SIGNAL_ID, "run_id": RUN_A, "body": "immutable"}
    before = json.dumps(generated, sort_keys=True)
    write_generated_json(run_dir, generated)
    generated_bytes = (run_dir / "generated.json").read_bytes()

    write_publication_results_json(
        run_dir,
        {"signal_id": SIGNAL_ID, "run_id": RUN_A, "source_run_id": RUN_A},
    )

    assert (run_dir / "generated.json").read_bytes() == generated_bytes
    assert json.dumps(load_run_generated(tmp_path, SIGNAL_ID, RUN_A), sort_keys=True) == before
    assert (run_dir / "publication_results.json").exists()


@pytest.mark.story9
def test_duplicate_write_fails_without_modifying_committed_artifact(tmp_path):
    path = resolve_run_dir(tmp_path, SIGNAL_ID, RUN_A) / "generated.json"
    atomic_write_json(path, {"body": "first"})
    original = path.read_bytes()
    with pytest.raises(ArtifactCollisionError):
        atomic_write_json(path, {"body": "second"})
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".tmp_*.json"))


def test_serialization_failure_leaves_no_final_or_temp_file(tmp_path):
    path = resolve_run_dir(tmp_path, SIGNAL_ID, RUN_A) / "generated.json"
    with pytest.raises(TypeError):
        atomic_write_json(path, {"not_json": object()})
    assert not path.exists()
    assert not list(path.parent.glob(".tmp_*.json"))


def test_link_failure_cleans_temp_and_leaves_no_final(tmp_path):
    path = resolve_run_dir(tmp_path, SIGNAL_ID, RUN_A) / "generated.json"
    with mock.patch("src.artifacts.os.link", side_effect=OSError("disk failure")):
        with pytest.raises(OSError, match="disk failure"):
            atomic_write_json(path, {"body": "complete"})
    assert not path.exists()
    assert not list(path.parent.glob(".tmp_*.json"))


def test_concurrent_writers_are_create_once_without_overwrite(tmp_path):
    path = resolve_run_dir(tmp_path, SIGNAL_ID, RUN_A) / "generated.json"
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def writer(body: str) -> None:
        barrier.wait()
        try:
            atomic_write_json(path, {"body": body})
            outcomes.append("written")
        except ArtifactCollisionError:
            outcomes.append("collision")

    threads = [threading.Thread(target=writer, args=(body,)) for body in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["collision", "written"]
    assert json.loads(path.read_text())["body"] in {"A", "B"}
    assert not list(path.parent.glob(".tmp_*.json"))


@pytest.mark.story9
def test_exact_reader_never_falls_back_to_another_run(tmp_path):
    write_generated_json(
        resolve_run_dir(tmp_path, SIGNAL_ID, RUN_A),
        {"signal_id": SIGNAL_ID, "run_id": RUN_A},
    )
    with pytest.raises(FileNotFoundError):
        load_run_generated(tmp_path, SIGNAL_ID, RUN_B)


def _seed_canonical_source(tmp_path: Path, source_run_id: str = RUN_A) -> Path:
    data = _valid_package(run_id=source_run_id)
    path = resolve_run_dir(tmp_path, CANONICAL_SIGNAL_ID, source_run_id) / "generated.json"
    atomic_write_json(path, data)
    return path


def _ok_publishers():
    wix_result = PublishResult(
        platform="wix", status=PublishStatus.PUBLISHED,
        external_id="wix-id", url="https://example.com/wix",
    )
    linkedin_result = PublishResult(
        platform="linkedin", status=PublishStatus.PUBLISHED,
        external_id="linkedin-id", url="https://example.com/linkedin",
    )
    wix = mock.MagicMock(); wix.publish.return_value = wix_result
    linkedin = mock.MagicMock(); linkedin.publish.return_value = linkedin_result
    return wix, linkedin


@pytest.mark.story9
def test_from_package_reads_exact_source_and_writes_separate_publication_run(tmp_path):
    source = _seed_canonical_source(tmp_path)
    source_bytes = source.read_bytes()
    publication_run_id = RUN_B
    argv, patches = _base_patches(dry_run=False, from_package=True)
    argv[-1] = RUN_A
    patches["PACKAGES_DIR"] = tmp_path
    wix, linkedin = _ok_publishers()

    with mock.patch("uuid.uuid4", return_value=uuid.UUID(publication_run_id)), \
         mock.patch("sys.argv", argv), \
         mock.patch.multiple(gap, **patches), \
         mock.patch.object(gap, "WixPublisher", return_value=wix), \
         mock.patch.object(gap, "LinkedInPublisher", return_value=linkedin):
        assert main() == 0

    result_path = resolve_run_dir(
        tmp_path, CANONICAL_SIGNAL_ID, publication_run_id
    ) / "publication_results.json"
    result = json.loads(result_path.read_text())
    assert result["run_id"] == publication_run_id
    assert result["source_run_id"] == RUN_A
    assert result["generation_run_id"] == RUN_A
    assert source.read_bytes() == source_bytes
    assert not (source.parent / "publication_results.json").exists()


@pytest.mark.parametrize("source_run_id", [RUN_B, "missing-run"])
@pytest.mark.story9
def test_wrong_or_missing_source_fails_before_side_effects(tmp_path, source_run_id):
    _seed_canonical_source(tmp_path, RUN_A)
    argv, patches = _base_patches(dry_run=False, from_package=True)
    argv[-1] = source_run_id
    patches["PACKAGES_DIR"] = tmp_path
    image = mock.MagicMock()
    wix_cls = mock.MagicMock()
    linkedin_cls = mock.MagicMock()
    patches["_load_package_images"] = image

    with mock.patch("sys.argv", argv), \
         mock.patch.multiple(gap, **patches), \
         mock.patch.object(gap, "WixPublisher", wix_cls), \
         mock.patch.object(gap, "LinkedInPublisher", linkedin_cls):
        assert main() == 1

    image.assert_not_called()
    wix_cls.assert_not_called()
    linkedin_cls.assert_not_called()


@pytest.mark.story9
def test_serialized_source_identity_mismatch_fails_before_side_effects(tmp_path):
    source = resolve_run_dir(tmp_path, CANONICAL_SIGNAL_ID, RUN_A) / "generated.json"
    atomic_write_json(source, _valid_package(run_id=RUN_B))
    argv, patches = _base_patches(dry_run=False, from_package=True)
    argv[-1] = RUN_A
    patches["PACKAGES_DIR"] = tmp_path
    image = mock.MagicMock()
    patches["_load_package_images"] = image
    wix_cls = mock.MagicMock()

    with mock.patch("sys.argv", argv), \
         mock.patch.multiple(gap, **patches), \
         mock.patch.object(gap, "WixPublisher", wix_cls):
        assert main() == 1

    image.assert_not_called()
    wix_cls.assert_not_called()


@pytest.mark.story9
def test_missing_source_run_id_never_falls_back_to_legacy_flat_file(tmp_path):
    legacy = tmp_path / f"{CANONICAL_SIGNAL_ID}_generated.json"
    legacy.write_text(json.dumps(_valid_package(run_id=RUN_A)), encoding="utf-8")
    argv, patches = _base_patches(dry_run=False)
    argv.append("--from-package")
    patches["PACKAGES_DIR"] = tmp_path
    image = mock.MagicMock()
    patches["_load_package_images"] = image
    wix_cls = mock.MagicMock()

    with mock.patch("sys.argv", argv), \
         mock.patch.multiple(gap, **patches), \
         mock.patch.object(gap, "WixPublisher", wix_cls):
        assert main() == 1

    image.assert_not_called()
    wix_cls.assert_not_called()
    assert not (tmp_path / CANONICAL_SIGNAL_ID).exists()


def test_publication_artifact_failure_is_fatal_before_history_and_analytics(tmp_path):
    argv, patches = _base_patches(dry_run=False)
    patches["PACKAGES_DIR"] = tmp_path
    history = patches["append_published_entry"]
    analytics = patches["run_analytics_pipeline"]
    wix, linkedin = _ok_publishers()

    with mock.patch("sys.argv", argv), \
         mock.patch.multiple(gap, **patches), \
         mock.patch.object(gap, "WixPublisher", return_value=wix), \
         mock.patch.object(gap, "LinkedInPublisher", return_value=linkedin), \
         mock.patch.object(
             gap, "write_publication_results_json", side_effect=OSError("disk full")
         ):
        assert main() == 1

    history.assert_not_called()
    analytics.assert_not_called()
