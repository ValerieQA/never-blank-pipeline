"""Issue #98 / Story #16: intake assignment persistence and whole-run
provenance verification.

Runs are produced through the real canonical entrypoint (injected fakes, no
live providers); verification is strictly read-only over the persisted
run-scoped evidence.
"""

from __future__ import annotations

import json
import sys
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.artifacts.provenance import (
    ProvenanceError,
    verify_run_provenance,
)
from src.intake.assignment_record import AssignmentRecord
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_visual_contract import _pimgs
from tests.test_editorial_acceptance import (
    FakeReviewTransport,
    FakeRevisionTransport,
    _review_payload,
)


SIG = legacy._SIGNAL_ID


def _full_run(tmp_path, *, evaluator_payload=None, reviewer=None):
    """One canonical generation run with real gates and valid bodies/visuals."""

    from tests.test_linkedin_composition import ARTICLE_BODY, _native_linkedin_body

    argv, patches = _entry_patches(tmp_path)
    del patches["build_visual_assets_record"]        # real visual gate
    del patches["write_visual_assets_json"]
    del patches["accept_linkedin_composition"]       # real LinkedIn gate
    del patches["write_linkedin_composition_json"]
    if reviewer is not None:
        del patches["run_editorial_acceptance"]      # real Story #13 gate
    patches["_load_package_images"] = mock.MagicMock(return_value=_pimgs(tmp_path))
    article = json.loads(json.dumps(legacy._FAKE_ARTICLE))
    article["platforms"]["long"]["body"] = ARTICLE_BODY
    article["platforms"]["medium"]["body"] = _native_linkedin_body()
    patches["generate_article"] = mock.MagicMock(return_value=article)
    evaluator, _ = _evaluator(evaluator_payload or _model_output())
    kwargs = dict(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    if reviewer is not None:
        kwargs.update(editorial_reviewer=reviewer, article_revisor=FakeRevisionTransport())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(**kwargs)
    runs = sorted(
        {p.parent.name for p in tmp_path.glob(f"{SIG}/runs/*/assignment.json")}
    )
    return code, runs


def _run_dir(tmp_path, run_id):
    return tmp_path / SIG / "runs" / run_id


def _verify(tmp_path, run_id):
    return verify_run_provenance(tmp_path, SIG, run_id)



def _config_of(tmp_path, run_id) -> dict:
    return json.loads(
        (_run_dir(tmp_path, run_id) / "assignment.json").read_text()
    )["configuration_identity"]

def _new_run_ids(before: set, tmp_path) -> list[str]:
    now = {p.parent.name for p in tmp_path.glob(f"{SIG}/runs/*/assignment.json")}
    return sorted(now - before)


# ===========================================================================
# assignment.json — canonical intake evidence
# ===========================================================================


def test_assignment_record_is_persisted_strict_and_run_bound(tmp_path):
    code, runs = _full_run(tmp_path)
    assert code == 0 and len(runs) == 1
    raw = json.loads((_run_dir(tmp_path, runs[0]) / "assignment.json").read_text())
    record = AssignmentRecord.model_validate(raw)  # strict reload
    assert record.run_id == runs[0]
    assert record.assignment.assignment_id == SIG
    assert record.assignment.strategy_ref == legacy._STRATEGY_STUB.strategy_id
    assert record.configuration_identity.configuration_hash.startswith("sha256:")
    # no unrestricted content in the envelope
    assert set(raw) == {
        "schema_version", "run_id", "execution_mode",
        "configuration_identity", "assignment", "code_identity",
        "editorial_role",  # Issue #142 — None when the run declared no role
    }


def test_assignment_record_is_create_once(tmp_path):
    code, runs = _full_run(tmp_path)
    assert code == 0
    from src.artifacts import ArtifactCollisionError, write_assignment_json
    with pytest.raises(ArtifactCollisionError):
        write_assignment_json(_run_dir(tmp_path, runs[0]), {"tamper": True})


# ===========================================================================
# Whole-run verification — complete and legitimately stopped chains
# ===========================================================================


def test_complete_generation_run_verifies_end_to_end(tmp_path):
    code, runs = _full_run(tmp_path)
    assert code == 0
    report = _verify(tmp_path, runs[0])
    assert report.run_kind == "generation"
    assert report.stopped_after == "generated"  # dry run: no publication yet
    assert set(report.verified_artifacts) >= {
        "assignment", "business_strategy", "research", "decision",
        "editorial_acceptance", "linkedin_composition", "visual_assets",
        "generated",
    }


def test_decision_stop_is_valid_provenance(tmp_path):
    code, runs = _full_run(tmp_path, evaluator_payload=_model_output(disposition="hold"))
    assert code == 1
    report = _verify(tmp_path, runs[0])
    assert report.stopped_after == "decision"
    assert "editorial_acceptance" not in report.verified_artifacts


def test_editorial_reject_stop_is_valid_provenance(tmp_path):
    reviewer = FakeReviewTransport(
        _review_payload(disposition="reject", failed=["reader-value"])
    )
    code, runs = _full_run(tmp_path, reviewer=reviewer)
    assert code == 1
    report = _verify(tmp_path, runs[0])
    assert report.stopped_after == "editorial_acceptance"
    assert "generated" not in report.verified_artifacts


# ===========================================================================
# Same signal, two runs — independent evidence
# ===========================================================================


def test_same_signal_two_runs_stay_independent(tmp_path):
    code, runs = _full_run(tmp_path)
    assert code == 0
    first = runs[0]
    first_assignment = (_run_dir(tmp_path, first) / "assignment.json").read_bytes()

    before = set(runs)
    code, _ = _full_run(tmp_path)
    assert code == 0
    new = _new_run_ids(before, tmp_path)
    assert len(new) == 1 and new[0] != first
    # first run untouched, both independently verifiable, no "latest" bleed
    assert (_run_dir(tmp_path, first) / "assignment.json").read_bytes() == first_assignment
    report_a = _verify(tmp_path, first)
    report_b = _verify(tmp_path, new[0])
    assert report_a.run_id == first and report_b.run_id == new[0]
    assert report_a.stopped_after == report_b.stopped_after == "generated"


# ===========================================================================
# Cross-run substitution fails closed
# ===========================================================================


@pytest.fixture
def two_runs(tmp_path):
    code, runs = _full_run(tmp_path)
    assert code == 0
    before = set(runs)
    code, _ = _full_run(tmp_path)
    assert code == 0
    run_b = _new_run_ids(before, tmp_path)[0]
    return tmp_path, runs[0], run_b


@pytest.mark.parametrize(
    "artifact,expect",
    [
        ("assignment.json", "different run"),
        ("research.json", "different run"),
        ("decision.json", "different run"),
        ("linkedin_composition.json", "different run"),
        ("visual_assets.json", "different run"),
        ("generated.json", "different run"),
    ],
)
def test_substituting_run_b_artifact_into_run_a_fails(two_runs, artifact, expect):
    tmp_path, run_a, run_b = two_runs
    target = _run_dir(tmp_path, run_a) / artifact
    target.unlink()
    target.write_bytes((_run_dir(tmp_path, run_b) / artifact).read_bytes())
    with pytest.raises(ProvenanceError, match=expect):
        _verify(tmp_path, run_a)


def test_tampered_research_state_breaks_decision_reference(two_runs):
    tmp_path, run_a, _ = two_runs
    path = _run_dir(tmp_path, run_a) / "research.json"
    data = json.loads(path.read_text())
    data["result"]["artifact"]["evidence"][0]["claim"] = "A silently altered claim."
    path.unlink()
    path.write_text(json.dumps(data))
    with pytest.raises(ProvenanceError, match="research digest mismatch"):
        _verify(tmp_path, run_a)


def test_tampered_article_breaks_linkedin_and_visual_lineage(two_runs):
    tmp_path, run_a, _ = two_runs
    path = _run_dir(tmp_path, run_a) / "generated.json"
    data = json.loads(path.read_text())
    data["blog_article"] = data["blog_article"] + " Silently appended sentence."
    path.unlink()
    path.write_text(json.dumps(data))
    with pytest.raises(ProvenanceError, match="does not derive from this run's accepted article"):
        _verify(tmp_path, run_a)


def test_publication_result_from_another_run_fails(two_runs):
    tmp_path, run_a, run_b = two_runs
    pub = {
        "run_id": run_b, "signal_id": SIG,
        "source_run_id": run_b, "generation_run_id": run_b,
        "execution_mode": "dry_run", "results": {}, "completed": True,
        "configuration_identity": _config_of(tmp_path, run_b),
    }
    (_run_dir(tmp_path, run_a) / "publication_results.json").write_text(json.dumps(pub))
    with pytest.raises(ProvenanceError, match="different run"):
        _verify(tmp_path, run_a)


def test_generation_publication_must_reference_itself(two_runs):
    tmp_path, run_a, run_b = two_runs
    pub = {
        "run_id": run_a, "signal_id": SIG,
        "source_run_id": run_b, "generation_run_id": run_b,
        "execution_mode": "controlled_live", "results": {}, "completed": True,
        "configuration_identity": _config_of(tmp_path, run_a),
    }
    (_run_dir(tmp_path, run_a) / "publication_results.json").write_text(json.dumps(pub))
    # a publication referencing another source flips the run to reuse-kind and
    # must then satisfy reuse semantics — a non-reused visual passport fails
    with pytest.raises(ProvenanceError, match="non-reuse visual passport"):
        _verify(tmp_path, run_a)


# ===========================================================================
# Corruption and lifecycle-consistency failures
# ===========================================================================


def test_missing_assignment_anchor_fails(two_runs):
    tmp_path, run_a, _ = two_runs
    (_run_dir(tmp_path, run_a) / "assignment.json").unlink()
    with pytest.raises(ProvenanceError, match="assignment.json is missing"):
        _verify(tmp_path, run_a)


def test_malformed_artifact_fails(two_runs):
    tmp_path, run_a, _ = two_runs
    (_run_dir(tmp_path, run_a) / "decision.json").write_text('{"broken":')
    with pytest.raises(ProvenanceError, match="malformed"):
        _verify(tmp_path, run_a)


def test_wrong_configuration_identity_fails(two_runs):
    tmp_path, run_a, _ = two_runs
    path = _run_dir(tmp_path, run_a) / "assignment.json"
    data = json.loads(path.read_text())
    data["configuration_identity"]["configuration_hash"] = "sha256:" + "b" * 64
    path.unlink()
    path.write_text(json.dumps(data))
    with pytest.raises(ProvenanceError, match="configuration identity"):
        _verify(tmp_path, run_a)


def test_downstream_artifact_without_upstream_chain_fails(two_runs):
    tmp_path, run_a, _ = two_runs
    (_run_dir(tmp_path, run_a) / "research.json").unlink()
    with pytest.raises(ProvenanceError, match="cannot exist without its upstream chain"):
        _verify(tmp_path, run_a)


def test_downstream_artifacts_after_nonproceed_decision_fail(tmp_path):
    code, runs = _full_run(tmp_path, evaluator_payload=_model_output(disposition="hold"))
    assert code == 1
    run_id = runs[0]
    # forge a downstream artifact on a decision-blocked run
    (_run_dir(tmp_path, run_id) / "editorial_acceptance.json").write_text(
        json.dumps({"run_id": run_id, "signal_id": SIG, "accepted": True,
                    "revised": False, "final_disposition": "accept",
                    "rubric": "x/1", "initial_review": {}, "final_review": None})
    )
    with pytest.raises(ProvenanceError, match="did not PROCEED"):
        _verify(tmp_path, run_id)


# ===========================================================================
# Reuse-publication runs
# ===========================================================================


def test_reuse_publication_run_verifies_against_origin(two_runs):
    tmp_path, run_a, _ = two_runs
    from tests.test_decision_lifecycle import _reuse_patches

    argv, patches = _reuse_patches(tmp_path, run_a)
    del patches["load_visual_assets_json"]
    del patches["reuse_visual_assets_record"]
    del patches["write_visual_assets_json"]
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 0
    run_b = next(
        p.parent.name
        for p in tmp_path.glob(f"{SIG}/runs/*/visual_assets.json")
        if json.loads(p.read_text()).get("reused")
    )
    report = _verify(tmp_path, run_b)
    assert report.run_kind == "reuse-publication"
    assert "visual_assets" in report.verified_artifacts


def test_reused_visual_with_false_origin_fails(two_runs):
    tmp_path, run_a, run_b = two_runs
    from tests.test_decision_lifecycle import _reuse_patches

    argv, patches = _reuse_patches(tmp_path, run_a)
    del patches["load_visual_assets_json"]
    del patches["reuse_visual_assets_record"]
    del patches["write_visual_assets_json"]
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 0
    pub_run = next(
        p.parent.name
        for p in tmp_path.glob(f"{SIG}/runs/*/visual_assets.json")
        if json.loads(p.read_text()).get("reused")
    )
    # forge a publication result disagreeing with the visual origin
    pub = {
        "run_id": pub_run, "signal_id": SIG,
        "source_run_id": run_b, "generation_run_id": run_b,
        "execution_mode": "controlled_live", "results": {}, "completed": True,
        "configuration_identity": _config_of(tmp_path, pub_run),
    }
    (_run_dir(tmp_path, pub_run) / "publication_results.json").write_text(json.dumps(pub))
    with pytest.raises(ProvenanceError, match="does not match the visual origin run"):
        _verify(tmp_path, pub_run)


# ===========================================================================
# Review follow-up: reuse publication must verify the source generation run
# ===========================================================================


def _build_reuse_run(tmp_path, source_run_id):
    from tests.test_decision_lifecycle import _reuse_patches

    argv, patches = _reuse_patches(tmp_path, source_run_id)
    del patches["load_visual_assets_json"]
    del patches["reuse_visual_assets_record"]
    del patches["write_visual_assets_json"]
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        assert main() == 0
    return next(
        p.parent.name
        for p in tmp_path.glob(f"{SIG}/runs/*/visual_assets.json")
        if json.loads(p.read_text()).get("reused")
    )


@pytest.fixture
def reuse_pair(tmp_path):
    code, runs = _full_run(tmp_path)
    assert code == 0
    run_a = runs[0]
    run_b = _build_reuse_run(tmp_path, run_a)
    return tmp_path, run_a, run_b


def test_valid_reuse_chain_verifies_against_verified_source(reuse_pair):
    tmp_path, run_a, run_b = reuse_pair
    report = _verify(tmp_path, run_b)
    assert report.run_kind == "reuse-publication"
    # and the source itself still verifies independently
    assert _verify(tmp_path, run_a).run_kind == "generation"


def test_source_article_tampered_after_reuse_fails_closed(reuse_pair):
    tmp_path, run_a, run_b = reuse_pair
    path = _run_dir(tmp_path, run_a) / "generated.json"
    data = json.loads(path.read_text())
    data["blog_article"] = data["blog_article"] + " Tampered after reuse."
    path.unlink()
    path.write_text(json.dumps(data))
    # the file still EXISTS — existence must not be provenance
    assert path.exists()
    with pytest.raises(ProvenanceError, match="source generation run .* failed provenance"):
        _verify(tmp_path, run_b)


def test_source_generated_from_another_run_fails_closed(reuse_pair, tmp_path):
    tmp_path_, run_a, run_b = reuse_pair
    # a third independent generation run C of the same signal
    before = {p.parent.name for p in tmp_path_.glob(f"{SIG}/runs/*/assignment.json")}
    code, _ = _full_run(tmp_path_)
    assert code == 0
    run_c = _new_run_ids(before, tmp_path_)[0]
    target = _run_dir(tmp_path_, run_a) / "generated.json"
    target.unlink()
    target.write_bytes((_run_dir(tmp_path_, run_c) / "generated.json").read_bytes())
    with pytest.raises(ProvenanceError, match="source generation run .* failed provenance"):
        _verify(tmp_path_, run_b)


def test_publication_configuration_laundering_fails_closed(reuse_pair):
    """B made internally self-consistent under a DIFFERENT configuration
    must still fail: reuse must match the source generation configuration."""

    from src.strategy.business_config import BusinessStrategyConfiguration
    from src.strategy.execution_context import ConfigurationIdentity

    tmp_path, run_a, run_b = reuse_pair
    b_dir = _run_dir(tmp_path, run_b)

    # craft a genuinely different configuration snapshot for B
    snapshot = json.loads((b_dir / "business_strategy.json").read_text())
    snapshot["business"]["name"] = snapshot["business"]["name"] + " (laundered)"
    laundered = BusinessStrategyConfiguration.model_validate(snapshot)
    base_identity = ConfigurationIdentity.model_validate(
        json.loads((b_dir / "assignment.json").read_text())["configuration_identity"]
    )
    laundered_identity = base_identity.from_configuration(laundered)
    assert laundered_identity != base_identity

    (b_dir / "business_strategy.json").unlink()
    (b_dir / "business_strategy.json").write_text(json.dumps(snapshot))
    assignment = json.loads((b_dir / "assignment.json").read_text())
    assignment["configuration_identity"] = json.loads(
        laundered_identity.model_dump_json()
    )
    (b_dir / "assignment.json").unlink()
    (b_dir / "assignment.json").write_text(json.dumps(assignment))

    # B is now internally self-consistent (assignment matches its snapshot)…
    with pytest.raises(
        ProvenanceError,
        match="does not match the source generation configuration",
    ):
        _verify(tmp_path, run_b)


# ===========================================================================
# Review follow-up 2: publication configuration identity is part of the chain
# ===========================================================================


def _write_pub(tmp_path, run_id, *, source, generation, config):
    pub = {
        "run_id": run_id, "signal_id": SIG,
        "source_run_id": source, "generation_run_id": generation,
        "execution_mode": "controlled_live", "results": {}, "completed": True,
        "configuration_identity": config,
    }
    (_run_dir(tmp_path, run_id) / "publication_results.json").write_text(
        json.dumps(pub)
    )


def test_valid_generation_publication_result_verifies(two_runs):
    tmp_path, run_a, _ = two_runs
    _write_pub(tmp_path, run_a, source=run_a, generation=run_a,
               config=_config_of(tmp_path, run_a))
    report = _verify(tmp_path, run_a)
    assert report.stopped_after == "publication_results"


def test_generation_publication_with_foreign_configuration_fails(two_runs):
    tmp_path, run_a, _ = two_runs
    foreign = dict(_config_of(tmp_path, run_a))
    foreign["configuration_hash"] = "sha256:" + "d" * 64
    _write_pub(tmp_path, run_a, source=run_a, generation=run_a, config=foreign)
    with pytest.raises(
        ProvenanceError,
        match="configuration different from the run's authoritative",
    ):
        _verify(tmp_path, run_a)


def test_publication_without_configuration_identity_fails(two_runs):
    tmp_path, run_a, _ = two_runs
    pub = {
        "run_id": run_a, "signal_id": SIG,
        "source_run_id": run_a, "generation_run_id": run_a,
        "execution_mode": "controlled_live", "results": {}, "completed": True,
    }
    (_run_dir(tmp_path, run_a) / "publication_results.json").write_text(json.dumps(pub))
    with pytest.raises(ProvenanceError, match="no valid configuration identity"):
        _verify(tmp_path, run_a)


def test_valid_reuse_publication_result_verifies(reuse_pair):
    tmp_path, run_a, run_b = reuse_pair
    _write_pub(tmp_path, run_b, source=run_a, generation=run_a,
               config=_config_of(tmp_path, run_b))
    report = _verify(tmp_path, run_b)
    assert report.run_kind == "reuse-publication"
    assert "publication_results" in report.verified_artifacts


def test_reuse_publication_with_foreign_configuration_fails(reuse_pair):
    tmp_path, run_a, run_b = reuse_pair
    foreign = dict(_config_of(tmp_path, run_b))
    foreign["configuration_hash"] = "sha256:" + "e" * 64
    _write_pub(tmp_path, run_b, source=run_a, generation=run_a, config=foreign)
    with pytest.raises(
        ProvenanceError,
        match="configuration different from the run's authoritative",
    ):
        _verify(tmp_path, run_b)
