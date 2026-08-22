"""Issue #174: a late-stage retry republished a package, it does not repay for one.

The canonical entrypoint has supported ``--from-package --source-run-id``
since Option B; neither weekday workflow exposed it, so every late-stage
failure cost a full regeneration (~14–15 text calls). These scenarios prove
the wiring and its safety: an empty ``source_run_id`` is byte-identical to
today, a valid one publishes the exact prior package with zero text-model
and zero image transports, every invalid reference fails closed with no
silent regeneration, the reused package stays bound to its signal, run,
role and configuration identity — including Monday's ``decision_policy.json``
authority, which the reuse gate previously could not honour — and both
weekday workflows carry the identical retry semantics.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.utils import llm_client
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import (
    _build_source_run,
    _entry_patches,
    _evaluator,
    _model_output,
    _reuse_patches,
)
from tests.test_monday_stream import MONDAY_ROLE, _run_with_role
from tests.test_research_artifact_lifecycle import ReadyProvider


class ExplodingClient:
    def __getattr__(self, name):
        raise AssertionError("a text-model transport was reached during reuse")


def _reuse_main(tmp_path, source_run_id, *, argv_extra=(), monkeypatch=None,
                evaluator=None):
    argv, patches = _reuse_patches(tmp_path, source_run_id)
    argv = argv + list(argv_extra)
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch(
                "scripts.research.prepare_content.prepare_content_packages",
                side_effect=AssertionError("image generation was reached during reuse"),
            ):
        code = main(decision_evaluator=evaluator)
    return code, patches


# ===========================================================================
# 2–4. Valid reuse: the from-package path, zero model and zero image work
# ===========================================================================


def test_valid_reuse_publishes_with_zero_model_and_zero_image_transports(
    tmp_path, monkeypatch, capsys
):
    source_run_id = _build_source_run(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr(llm_client, "_client", ExplodingClient())

    counting_evaluator, transport = _evaluator(_model_output())
    code, patches = _reuse_main(tmp_path, source_run_id, evaluator=counting_evaluator)

    assert code == 0
    assert transport.calls == []                       # lens never re-ran
    assert patches["generate_article"].called is False  # engine never ran
    out = capsys.readouterr().out
    # #171's own accounting agrees: not one budgeted text call was made
    assert "text-model call budget: 0 used" in out
    monkeypatch.setattr(llm_client, "_client", None)


# ===========================================================================
# 5–8. Every invalid reference fails closed — never silent regeneration
# ===========================================================================


def test_a_missing_source_run_fails_closed(tmp_path):
    _build_source_run(tmp_path)

    code, patches = _reuse_main(tmp_path, "00000000-dead-4000-8000-000000000000")

    assert code == 1
    assert patches["generate_article"].called is False   # no fallback regen


def test_a_malformed_package_fails_closed(tmp_path):
    source_run_id = _build_source_run(tmp_path)
    pkg_path = next(tmp_path.glob(f"*/runs/{source_run_id}/generated.json"))
    pkg_path.write_text('{"broken":')

    code, patches = _reuse_main(tmp_path, source_run_id)

    assert code == 1
    assert patches["generate_article"].called is False


def test_a_tampered_package_run_identity_fails_closed(tmp_path):
    source_run_id = _build_source_run(tmp_path)
    pkg_path = next(tmp_path.glob(f"*/runs/{source_run_id}/generated.json"))
    pkg = json.loads(pkg_path.read_text())
    pkg["run_id"] = "00000000-0000-4000-8000-00000000beef"
    pkg_path.write_text(json.dumps(pkg))

    code, patches = _reuse_main(tmp_path, source_run_id)

    assert code == 1
    assert patches["generate_article"].called is False


def test_a_source_run_of_another_signal_cannot_publish_here(tmp_path):
    # the run namespace is addressed by (signal_id, run_id): a run id that
    # exists under a different signal resolves to nothing under this one
    source_run_id = _build_source_run(tmp_path)
    other = tmp_path / "sig-other" / "runs" / source_run_id
    other.mkdir(parents=True)
    real = next(tmp_path.glob(f"*/runs/{source_run_id}/generated.json"))
    (other / "generated.json").write_bytes(real.read_bytes())
    # dispatch stays on the legacy signal, but the source dir is emptied
    real.unlink()

    code, patches = _reuse_main(tmp_path, source_run_id)

    assert code == 1
    assert patches["generate_article"].called is False


# ===========================================================================
# Identity: Monday's decision_policy.json authority is honoured, exactly
# ===========================================================================


def _build_monday_source_run(tmp_path) -> str:
    code, _, _ = _run_with_role(tmp_path, MONDAY_ROLE)
    assert code == 0
    policies = list(tmp_path.glob("*/runs/*/decision_policy.json"))
    assert len(policies) == 1
    return policies[0].parent.name


def test_a_monday_policy_run_can_be_republished_without_any_lens(tmp_path, monkeypatch):
    source_run_id = _build_monday_source_run(tmp_path)
    monkeypatch.setattr(llm_client, "_client", ExplodingClient())
    policy_path = next(tmp_path.glob(f"*/runs/{source_run_id}/decision_policy.json"))
    before = policy_path.read_bytes()

    counting_evaluator, transport = _evaluator(_model_output())
    code, patches = _reuse_main(
        tmp_path, source_run_id,
        argv_extra=["--editorial-role", MONDAY_ROLE],
        evaluator=counting_evaluator,
    )

    assert code == 0
    assert transport.calls == []                     # lens never consulted
    assert policy_path.read_bytes() == before        # authority never rewritten
    assert patches["generate_article"].called is False
    monkeypatch.setattr(llm_client, "_client", None)


def test_the_xor_contract_holds_on_reuse(tmp_path):
    source_run_id = _build_monday_source_run(tmp_path)
    run_dir = next(tmp_path.glob(f"*/runs/{source_run_id}/"))
    (run_dir / "decision.json").write_text("{}")     # corrupt: both authorities

    code, patches = _reuse_main(
        tmp_path, source_run_id, argv_extra=["--editorial-role", MONDAY_ROLE],
    )

    assert code == 1
    assert patches["generate_article"].called is False


def test_a_tampered_policy_record_fails_verification(tmp_path):
    source_run_id = _build_monday_source_run(tmp_path)
    policy_path = next(tmp_path.glob(f"*/runs/{source_run_id}/decision_policy.json"))
    policy = json.loads(policy_path.read_text())
    policy["run_id"] = "00000000-0000-4000-8000-00000000beef"
    policy_path.write_text(json.dumps(policy))

    code, patches = _reuse_main(
        tmp_path, source_run_id, argv_extra=["--editorial-role", MONDAY_ROLE],
    )

    assert code == 1
    assert patches["generate_article"].called is False


def test_a_roleless_dispatch_cannot_reuse_a_policy_run(tmp_path):
    # role/configuration identity binding: the source run's authority is a
    # role-scoped policy record; a dispatch expecting a Decision Lens
    # decision must refuse it, never adapt it
    source_run_id = _build_monday_source_run(tmp_path)

    code, patches = _reuse_main(tmp_path, source_run_id)

    assert code == 1
    assert patches["generate_article"].called is False


# ===========================================================================
# 1, 9–12. Workflow wiring: identical semantics, unchanged normal path
# ===========================================================================

_WF = {
    "monday": ".github/workflows/monday_publish.yml",
    "wednesday": ".github/workflows/wednesday_golden.yml",
}


def _wf(stream):
    return yaml.safe_load(Path(_WF[stream]).read_text())


def _steps(stream):
    job = next(iter(_wf(stream)["jobs"].values()))
    return {s.get("name", s.get("uses", "")): s for s in job["steps"]}


def _resolve_step(stream):
    steps = _steps(stream)
    name = "Select eligible signal" if stream == "monday" else "Resolve Wednesday signal"
    return steps[name]


def _generate_step(stream):
    steps = _steps(stream)
    return next(s for n, s in steps.items() if "Generate + Publish" in n)


@pytest.mark.parametrize("stream", ["monday", "wednesday"])
def test_source_run_id_is_an_optional_input_defaulting_to_the_normal_path(stream):
    inputs = _wf(stream)[True]["workflow_dispatch"]["inputs"]
    assert inputs["source_run_id"]["required"] is False
    assert inputs["source_run_id"]["default"] == ""


@pytest.mark.parametrize("stream", ["monday", "wednesday"])
def test_the_retry_short_circuit_is_guarded_and_skips_the_selector(stream):
    step = _resolve_step(stream)
    run = step["run"]
    # quoted env vars, never inline interpolation of the retry inputs
    assert step["env"]["RETRY_RUN_ID"] == "${{ inputs.source_run_id }}"
    assert step["env"]["RETRY_SIGNAL_ID"] == "${{ inputs.signal_id }}"
    assert 'if [ -n "$RETRY_RUN_ID" ]' in run
    # charset guards close shell injection and path traversal
    assert '(*[!A-Za-z0-9-]*)' in run
    assert '(*[!A-Za-z0-9_-]*)' in run
    # a consumed signal can never be published twice through a retry
    assert 'grep -Fxq "$RETRY_SIGNAL_ID" data/research/published_signal_ids.txt' in run
    # signal_id is mandatory for a retry
    assert "source_run_id requires signal_id" in run
    # and the selector is skipped: the short-circuit exits before it
    assert run.index('exit 0') < run.index("select_eligible_signal.py")


@pytest.mark.parametrize("stream", ["monday", "wednesday"])
def test_the_generate_step_forwards_the_from_package_flags(stream):
    step = _generate_step(stream)
    assert step["env"]["SOURCE_RUN_ID"] == "${{ inputs.source_run_id }}"
    run = step["run"]
    assert '--from-package --source-run-id $SOURCE_RUN_ID' in run
    # dry-run appends: it can never silently drop the from-package flags
    assert 'FLAGS="$FLAGS --dry-run"' in run


@pytest.mark.parametrize("stream", ["monday", "wednesday"])
def test_the_normal_scheduled_path_is_unchanged(stream):
    step = _resolve_step(stream)
    run = step["run"]
    # empty source_run_id falls through the guard to the exact selector
    # invocation and exit-code handling that existed before #174
    assert "select_eligible_signal.py" in run
    assert 'if [ "$RC" = "3" ]' in run
    # consumption conditions untouched: success only, never dry-run
    mark = _steps(stream)["Mark signal as published"]
    assert "success()" in mark["if"] and "dry_run != 'true'" in mark["if"]


def test_monday_and_wednesday_retry_semantics_are_identical():
    def normalized_retry(stream):
        run = _resolve_step(stream)["run"]
        block = run.split('if [ -n "$RETRY_RUN_ID" ]')[1].split("set +e")[0]
        return re.sub(r"\s+", " ", block).replace("monday", "").replace("wednesday", "")

    assert normalized_retry("monday") == normalized_retry("wednesday")


# ===========================================================================
# Correction round: the source assignment's editorial role binds reuse
# ===========================================================================

WEDNESDAY_ROLE = "never-blank-wednesday-golden"


def _build_wednesday_source_run(tmp_path) -> str:
    code, _, _ = _run_with_role(tmp_path, WEDNESDAY_ROLE)
    assert code == 0
    decisions = list(tmp_path.glob("*/runs/*/decision.json"))
    assert len(decisions) == 1          # Wednesday takes the Decision Lens
    return decisions[0].parent.name


def _source_assignment_path(tmp_path, source_run_id):
    return next(tmp_path.glob(f"*/runs/{source_run_id}/assignment.json"))


def test_a_wednesday_source_republishes_under_the_wednesday_role(
    tmp_path, monkeypatch, capsys
):
    source_run_id = _build_wednesday_source_run(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr(llm_client, "_client", ExplodingClient())
    assignment_before = _source_assignment_path(tmp_path, source_run_id).read_bytes()

    counting_evaluator, transport = _evaluator(_model_output())
    code, patches = _reuse_main(
        tmp_path, source_run_id,
        argv_extra=["--editorial-role", WEDNESDAY_ROLE],
        evaluator=counting_evaluator,
    )

    assert code == 0
    assert transport.calls == []                       # lens never re-ran
    assert patches["generate_article"].called is False
    # the anchor was read, never rewritten
    assert _source_assignment_path(
        tmp_path, source_run_id).read_bytes() == assignment_before
    assert "text-model call budget: 0 used" in capsys.readouterr().out
    monkeypatch.setattr(llm_client, "_client", None)


def test_a_roleless_source_cannot_be_republished_under_a_role(tmp_path):
    # roleless Decision-Lens source + Wednesday dispatch → refused: the
    # package was not produced under the identity now claiming it
    source_run_id = _build_source_run(tmp_path)      # roleless source

    code, patches = _reuse_main(
        tmp_path, source_run_id,
        argv_extra=["--editorial-role", WEDNESDAY_ROLE],
    )

    assert code == 1
    assert patches["generate_article"].called is False
    # the refusal happens at the reuse gate — long before any publisher


def test_a_role_scoped_source_cannot_be_republished_rolelessly(tmp_path):
    # Wednesday-role source + roleless dispatch → refused (previously this
    # passed the lens branch unchecked — the exact blocking finding)
    source_run_id = _build_wednesday_source_run(tmp_path)

    code, patches = _reuse_main(tmp_path, source_run_id)

    assert code == 1
    assert patches["generate_article"].called is False


def test_a_source_produced_under_another_role_is_refused(tmp_path):
    # Wednesday-role source + Monday dispatch: same-signal, valid package,
    # wrong identity. (Monday's dispatch takes the policy branch, which
    # also lacks a policy record here — the binding refusal must come first
    # and by role, not by artifact absence.)
    source_run_id = _build_wednesday_source_run(tmp_path)

    code, patches = _reuse_main(
        tmp_path, source_run_id, argv_extra=["--editorial-role", MONDAY_ROLE],
    )

    assert code == 1
    assert patches["generate_article"].called is False


def test_a_tampered_source_role_id_fails_binding(tmp_path):
    source_run_id = _build_wednesday_source_run(tmp_path)
    path = _source_assignment_path(tmp_path, source_run_id)
    record = json.loads(path.read_text())
    record["editorial_role"]["role_id"] = "never-blank-monday-documented-case"
    path.write_text(json.dumps(record))

    code, patches = _reuse_main(
        tmp_path, source_run_id,
        argv_extra=["--editorial-role", WEDNESDAY_ROLE],
    )

    assert code == 1
    assert patches["generate_article"].called is False


def test_a_tampered_role_configuration_version_fails_binding(tmp_path):
    source_run_id = _build_wednesday_source_run(tmp_path)
    path = _source_assignment_path(tmp_path, source_run_id)
    record = json.loads(path.read_text())
    record["editorial_role"]["configuration_version"] = "999"
    path.write_text(json.dumps(record))

    code, patches = _reuse_main(
        tmp_path, source_run_id,
        argv_extra=["--editorial-role", WEDNESDAY_ROLE],
    )

    assert code == 1
    assert patches["generate_article"].called is False


def test_a_malformed_source_assignment_fails_binding(tmp_path):
    source_run_id = _build_wednesday_source_run(tmp_path)
    _source_assignment_path(tmp_path, source_run_id).write_text('{"broken":')

    code, patches = _reuse_main(
        tmp_path, source_run_id,
        argv_extra=["--editorial-role", WEDNESDAY_ROLE],
    )

    assert code == 1
    assert patches["generate_article"].called is False
