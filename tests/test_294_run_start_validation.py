"""Issue #294: a run does not start on a register it cannot trust (Step 4 §8).

CI validates the register on every change, and CI is not enough: the register is a
directory of files, and it can be edited between the change CI checked and the run
that reads it. So the first thing a run does is validate it, and a failure means the
run does not start — a `SKIP` at signal scope, reason `knowledge_register_invalid`.

The fixture run below is not an engine. It holds no stage logic; it walks the
canonical topology's own stage order and records what it executed, so that "the run
did not start" is something the run *produces* rather than something the test
asserts about a flag. Every invalid file of the corpus is put in front of it, and
none of them lets a stage run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from src.editorial_core.topology import CANONICAL_TOPOLOGY, TerminalOutcome
from src.knowledge.run_start import (
    KNOWLEDGE_REGISTER_INVALID,
    RunStartDecision,
    validate_at_run_start,
)
from src.knowledge.validator import KR_APPROVAL
from src.knowledge.vocabulary import load_vocabularies
from tests.test_294_knowledge_register import (
    CASES_NEEDING_A_BASELINE,
    INVALID,
    REGISTER,
    build_register,
    invalid_cases,
)

#: The scope a run-start failure ends. Nothing has been read yet, so it is the
#: whole signal.
SIGNAL = "signal"


class _FixtureRun:
    """A run whose first act is to validate the register it is about to read.

    It executes the canonical topology's stages in order, and only if the gate let
    it start. What it yields is an executed path and an outcome, which is what §8's
    "the run does not start" is a claim about.
    """

    def __init__(self, register: Path, client_rule_paths: tuple[Path, ...] = ()) -> None:
        self.decision: RunStartDecision = validate_at_run_start(
            register, client_rule_paths=client_rule_paths
        )
        self.executed: list[str] = []
        self.outcomes: list[tuple[str, Optional[TerminalOutcome], Optional[str]]] = []

        if not self.decision.may_start:
            self.outcomes.append(
                (SIGNAL, self.decision.outcome, self.decision.reason)
            )
            return
        self.executed.extend(CANONICAL_TOPOLOGY.stage_ids)


def test_a_run_starts_on_a_valid_register(tmp_path):
    built = build_register(tmp_path)

    run = _FixtureRun(built.register, built.client_paths)

    assert run.decision.may_start
    assert run.executed == list(CANONICAL_TOPOLOGY.stage_ids)
    assert run.outcomes == []
    assert (run.decision.outcome, run.decision.reason) == (None, None)


def test_a_broken_register_skips_the_signal_before_any_stage_runs(tmp_path):
    built = build_register(
        tmp_path, overlay=INVALID / "rule_03_invariant_without_approval"
    )

    run = _FixtureRun(built.register, built.client_paths)

    assert run.executed == []
    assert run.outcomes == [
        (SIGNAL, TerminalOutcome.SKIP_SIGNAL, KNOWLEDGE_REGISTER_INVALID)
    ]
    # The trace says which rule, so the record is fixed offline rather than
    # guessed at.
    assert KR_APPROVAL in run.decision.summary()
    assert "approved_by" in run.decision.summary()


@pytest.mark.parametrize(
    "case",
    [case for case in invalid_cases() if case.name not in CASES_NEEDING_A_BASELINE],
    ids=lambda path: path.name,
)
def test_no_invalid_file_lets_a_run_start(case, tmp_path):
    built = build_register(tmp_path, overlay=case)

    run = _FixtureRun(built.register, built.client_paths)

    assert run.executed == []
    assert run.decision.reason == KNOWLEDGE_REGISTER_INVALID


def test_a_register_that_is_not_there_stops_the_run_too(tmp_path):
    run = _FixtureRun(tmp_path / "nothing-here")

    assert run.executed == []
    assert run.decision.reason == KNOWLEDGE_REGISTER_INVALID


def test_the_reason_is_a_term_of_the_register_s_own_vocabulary():
    reasons = load_vocabularies(REGISTER).get("reason_categories")
    assert reasons.term(KNOWLEDGE_REGISTER_INVALID) is not None


def test_the_gate_reads_the_register_and_nothing_else(tmp_path):
    """No stage, no configuration, no weekday: only the files it validates."""

    built = build_register(tmp_path)
    first = validate_at_run_start(built.register, client_rule_paths=built.client_paths)
    second = validate_at_run_start(built.register, client_rule_paths=built.client_paths)

    assert first == second
    assert first.may_start
