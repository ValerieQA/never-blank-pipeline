"""Issue #336: a run states which inputs it executed against.

Step 3 §4.1 gives the manifest an `inputs` section — Client Contract,
Audience Profile, Editorial Lens, knowledge register version, platform
knowledge verification dates, reference library version, strength ladder ID,
each with a digest. Four claims, each of which has to be able to fail:

- **Every §4.1 input is stated.** Not "every input that happens to exist": an
  artifact this repository does not have yet is recorded as absent, with a
  reason, rather than given an invented identity. A written manifest carries
  all seven and round-trips through its serialization.
- **The register identity is the one the loader loaded** (Step 4 §9.1): the
  git commit of the `knowledge/` tree, plus a digest over the loaded files.
  Edited between two runs, the digest moves — which is the whole reason the
  knowledge slices can point at this identity instead of inventing one.
- **A run whose input digests do not verify is refused.** The §4.1 gate beside
  `verify_topology_digest` and `verify_run_digest`: a manifest whose inputs
  changed after the run sealed them stays readable for forensics and is never
  read as a source.
- **Manifest-last still holds** (#291). The inputs are part of the document
  the manifest seals, and sealing still ends the run.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.knowledge.loader import load_register
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_inputs import (
    NO_AUDIENCE_PROFILE,
    NO_REFERENCE_LIBRARY,
    RunInputsError,
    knowledge_register_version,
    platform_knowledge_version,
    register_tree_commit,
    run_inputs,
)
from src.run.run_manifest import (
    InputDigestMismatchError,
    InputKind,
    InputVersion,
    PlatformVerification,
    RunInputs,
    RunManifest,
    compute_inputs_digest,
    verify_input_digests,
)
from src.run.run_workspace import (
    MANIFEST_NAME,
    RunWorkspace,
    RunWorkspaceError,
    load_manifest,
    verify_run_workspace,
)
from src.strategy.client_contracts import contracts_for_role
from tests.test_295_knowledge_loader import TODAY, build_register
from tests.test_client_contracts import MONDAY_ROLE, NEVER_BLANK

TS_UTC = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)

_ANY_DIGEST = "sha256:" + "0" * 64


def _run_context(run_id: str) -> RunContext:
    return RunContext(
        run_id=run_id,
        assignment_id="sig-336",
        started_at=TS_UTC,
        strategy_ref="never-blank",
        strategy_version="1.0.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
    )


@pytest.fixture()
def register(tmp_path) -> Path:
    """The register a run loads: the shipped one plus the #294/#295 corpus."""

    return build_register(tmp_path)


@pytest.fixture()
def loaded(register):
    return load_register(register, today=TODAY)


@pytest.fixture()
def contracts():
    """The client documents this repository's own client supplies."""

    found = contracts_for_role(MONDAY_ROLE, NEVER_BLANK)
    assert found is not None, "the never_blank client governs the Monday stream"
    return found


def _seal(runs_root: Path, inputs: RunInputs) -> tuple[str, RunManifest]:
    """One complete run: nothing written, then the manifest, last.

    A run that wrote nothing still seals (#291), which is what lets these
    scenarios be about the inputs and nothing else.
    """

    run_id = create_run_id()
    workspace = RunWorkspace.create(runs_root, run_id)
    return run_id, workspace.write_manifest(_run_context(run_id), inputs=inputs)


def _keeper_edits(register: Path) -> None:
    """One offline edit between two runs: a statement reworded, a version up."""

    path = register / "records" / "mat" / "K-MAT-11.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("version: 1", "version: 2", 1)
    text = text.replace(
        "reads better than comparing several.", "reads better than a comparison."
    )
    path.write_text(
        text + "- v2, 2026-09-23: statement reworded.\n", encoding="utf-8"
    )


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


# ===========================================================================
# Acceptance: a manifest carries every §4.1 input, and round-trips
# ===========================================================================


def test_a_written_manifest_carries_every_input_with_a_digest(
    tmp_path, register, loaded, contracts
):
    runs_root = tmp_path / "editorial_runs"
    run_id, manifest = _seal(
        runs_root,
        run_inputs(contracts=contracts, knowledge=loaded, register_dir=register),
    )

    assert [entry.kind for entry in manifest.inputs.entries] == list(InputKind)
    assert [entry.kind for entry in manifest.inputs.entries if entry.present] == [
        InputKind.CLIENT_CONTRACT,
        InputKind.EDITORIAL_LENS,
        InputKind.KNOWLEDGE_REGISTER,
        InputKind.PLATFORM_KNOWLEDGE,
        InputKind.STRENGTH_LADDER,
    ]
    assert all(
        entry.digest is not None
        for entry in manifest.inputs.entries
        if entry.present
    )
    verify_run_workspace(runs_root, run_id)


def test_a_manifest_round_trips_through_its_serialization(
    tmp_path, register, loaded, contracts
):
    runs_root = tmp_path / "editorial_runs"
    run_id, manifest = _seal(
        runs_root,
        run_inputs(contracts=contracts, knowledge=loaded, register_dir=register),
    )

    restored = load_manifest(runs_root / run_id)

    assert restored == manifest
    assert RunManifest.from_dict(manifest.to_dict()) == manifest
    verify_input_digests(restored)


def test_the_client_contract_and_lens_are_the_documents_the_run_read(contracts):
    inputs = run_inputs(contracts=contracts)

    assert inputs.client_contract.identities == (contracts.stream.identity,)
    assert inputs.client_contract.digest == contracts.stream.digest
    assert inputs.editorial_lens.identities == tuple(
        lens.identity for lens in contracts.lenses
    )


def test_an_artifact_that_does_not_exist_is_stated_absent_not_invented(
    register, loaded, contracts
):
    """#335 owns the Audience Profile. #336 records the identity it has."""

    inputs = run_inputs(
        contracts=contracts, knowledge=loaded, register_dir=register
    )

    profile = inputs.audience_profile
    assert not profile.present
    assert (profile.digest, profile.identities) == (None, ())
    assert profile.absent_reason == NO_AUDIENCE_PROFILE
    assert inputs.reference_library.absent_reason == NO_REFERENCE_LIBRARY


def test_a_run_that_read_nothing_still_states_all_seven_inputs():
    inputs = RunInputs.stated_absent("fixture run: no editorial input was read")

    assert [entry.kind for entry in inputs.entries] == list(InputKind)
    assert not any(entry.present for entry in inputs.entries)
    assert compute_inputs_digest(inputs.entries) == inputs.inputs_digest


# ===========================================================================
# Acceptance: the register identity is the one the loader loaded (§9.1)
# ===========================================================================


def test_the_register_identity_names_the_commit_of_the_knowledge_tree(
    tmp_path, register, loaded
):
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)], capture_output=True, check=True
    )
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "the register this run loads")

    version = knowledge_register_version(loaded, register_dir=register)

    assert register_tree_commit(register) == _git(tmp_path, "rev-parse", "HEAD")
    assert version.identities == (_git(tmp_path, "rev-parse", "HEAD"),)


def test_a_register_outside_a_repository_states_no_commit_and_still_digests(
    register, loaded
):
    """A fabricated commit would be worse than none — the identity is halved,
    not invented, and the digest over the loaded files still identifies it."""

    version = knowledge_register_version(loaded, register_dir=register)

    assert version.identities == ()
    assert version.present


def test_a_register_edited_between_two_runs_moves_the_recorded_identity(
    tmp_path, register
):
    runs_root = tmp_path / "editorial_runs"
    before = load_register(register, today=TODAY)
    _, first = _seal(
        runs_root, run_inputs(knowledge=before, register_dir=register)
    )

    _keeper_edits(register)
    after = load_register(register, today=TODAY)
    _, second = _seal(
        runs_root, run_inputs(knowledge=after, register_dir=register)
    )

    assert after.record("K-MAT-11").version == 2
    assert (
        first.inputs.knowledge_register.digest
        != second.inputs.knowledge_register.digest
    )
    assert first.inputs.inputs_digest != second.inputs.inputs_digest
    # Each run recorded what its own loader held, not what the tree holds now.
    assert (
        second.inputs.knowledge_register.digest
        == knowledge_register_version(after, register_dir=register).digest
    )


def test_platform_knowledge_is_recorded_by_its_verification_dates(
    register, loaded
):
    platform = run_inputs(
        knowledge=loaded, register_dir=register
    ).platform_knowledge

    dated = {entry.record_id: entry.verified_on for entry in platform.verified_on}
    assert dated
    assert dated == {
        item.identity: item.record.verified_on
        for item in loaded.records
        if item.identity.startswith("K-DST-")
    }


def test_platform_knowledge_without_a_date_is_refused(loaded):
    """§4.1 records it by its dates, and §8 rule 8 requires every one."""

    dst = loaded.record("K-DST-TG-05")
    undated = replace(dst, record=replace(dst.record, verified_on=None))
    base = replace(
        loaded,
        records=tuple(
            undated if item.identity == undated.identity else item
            for item in loaded.records
        ),
    )

    with pytest.raises(RunInputsError, match="verified_on"):
        platform_knowledge_version(base)


def test_the_strength_ladder_is_recorded_by_its_id(register, loaded):
    ladder = run_inputs(knowledge=loaded, register_dir=register).strength_ladder

    assert ladder.identities == ("K-LAD-01",)
    assert ladder.digest == loaded.record("K-LAD-01").digest


def test_a_loaded_register_is_identified_by_its_directory_as_well(loaded):
    with pytest.raises(RunInputsError, match="register_dir"):
        run_inputs(knowledge=loaded)


# ===========================================================================
# Acceptance: inputs that do not verify are refused
# ===========================================================================


def test_a_manifest_whose_input_digest_does_not_verify_is_refused(
    tmp_path, register, loaded
):
    runs_root = tmp_path / "editorial_runs"
    run_id, _ = _seal(
        runs_root, run_inputs(knowledge=loaded, register_dir=register)
    )
    path = runs_root / run_id / MANIFEST_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    data["inputs"]["knowledge_register"]["identities"] = ["0" * 40]
    path.write_text(json.dumps(data), encoding="utf-8")

    tampered = load_manifest(runs_root / run_id)  # readable, for forensics

    with pytest.raises(InputDigestMismatchError, match="sealed them"):
        verify_input_digests(tampered)
    with pytest.raises(InputDigestMismatchError):
        verify_run_workspace(runs_root, run_id)


def test_a_manifest_without_the_input_versions_is_refused(
    tmp_path, register, loaded
):
    """A document with no `inputs` is a schema 1.1 manifest, and says so."""

    runs_root = tmp_path / "editorial_runs"
    _, manifest = _seal(
        runs_root, run_inputs(knowledge=loaded, register_dir=register)
    )
    without = manifest.to_dict()
    del without["inputs"]

    with pytest.raises(ValueError, match="1.1"):
        RunManifest.from_dict(without)


def test_an_input_version_is_either_read_or_stated_absent():
    with pytest.raises(ValueError, match="does neither"):
        InputVersion(kind=InputKind.CLIENT_CONTRACT)

    with pytest.raises(ValueError, match="states both"):
        InputVersion(
            kind=InputKind.CLIENT_CONTRACT,
            digest=_ANY_DIGEST,
            absent_reason="and also absent",
        )


def test_an_input_the_run_did_not_read_has_nothing_to_identify():
    with pytest.raises(ValueError, match="nothing to identify"):
        InputVersion(
            kind=InputKind.CLIENT_CONTRACT,
            identities=("never-blank-monday/1",),
            absent_reason="not read",
        )


def test_verification_dates_belong_to_platform_knowledge():
    with pytest.raises(ValueError, match="platform_knowledge"):
        InputVersion(
            kind=InputKind.CLIENT_CONTRACT,
            digest=_ANY_DIGEST,
            verified_on=(
                PlatformVerification(
                    record_id="K-DST-LI-03", verified_on="2026-09-01"
                ),
            ),
        )


def test_an_input_filed_under_another_name_is_refused():
    lens = InputVersion.absent(InputKind.EDITORIAL_LENS, "no lens")

    with pytest.raises(ValueError, match="filed under another name"):
        RunInputs.of(
            client_contract=lens,
            audience_profile=InputVersion.absent(
                InputKind.AUDIENCE_PROFILE, "none"
            ),
            editorial_lens=lens,
            knowledge_register=InputVersion.absent(
                InputKind.KNOWLEDGE_REGISTER, "none"
            ),
            platform_knowledge=InputVersion.absent(
                InputKind.PLATFORM_KNOWLEDGE, "none"
            ),
            reference_library=InputVersion.absent(
                InputKind.REFERENCE_LIBRARY, "none"
            ),
            strength_ladder=InputVersion.absent(
                InputKind.STRENGTH_LADDER, "none"
            ),
        )


# ===========================================================================
# Acceptance: manifest-last and the seal (#291) still hold
# ===========================================================================


def test_the_manifest_is_still_written_last_and_still_seals(
    tmp_path, register, loaded
):
    runs_root = tmp_path / "editorial_runs"
    run_id = create_run_id()
    workspace = RunWorkspace.create(runs_root, run_id)
    inputs = run_inputs(knowledge=loaded, register_dir=register)

    assert not workspace.sealed
    workspace.write_manifest(_run_context(run_id), inputs=inputs)

    assert workspace.sealed
    with pytest.raises(RunWorkspaceError, match="nothing follows"):
        workspace.write_manifest(_run_context(run_id), inputs=inputs)
