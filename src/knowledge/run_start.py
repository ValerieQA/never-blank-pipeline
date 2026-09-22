"""Run-start validation: a broken register stops the run before it starts (§8).

The validator runs in CI, and CI is not enough. A register is a directory of files
in a working tree: it can be edited between the change that CI checked and the run
that reads it, and a run that starts on a register it cannot trust would make
editorial decisions on knowledge nobody validated.

So the first thing a run does is validate the register. If anything is wrong the
run **does not start**: the outcome is a `SKIP` at signal scope, with the reason
`knowledge_register_invalid`. That is fail-closed, and it needs no human during the
run (I-01) — the broken record is fixed offline, and the next run reads it.

This module is the gate and nothing else. It takes no stage, makes no call, and
writes nothing: given a register it answers whether a run may start on it. Wiring
it into the scheduled entry points belongs with the loader that reads the register
into a run, in the slice that builds one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from src.editorial_core.topology import TerminalOutcome
from src.knowledge.validator import Finding, RecordBaseline, validate_register

# The reason a run records when it refuses to start (§8). It is defined beside the
# vocabulary it is mirrored against, so the term in `reason_categories.md` and the
# term code writes cannot drift apart.
from src.knowledge.vocabulary import KNOWLEDGE_REGISTER_INVALID

#: A register failure is not specific to a unit or a destination: nothing has been
#: read yet, so the whole signal is skipped.
REGISTER_FAILURE_OUTCOME = TerminalOutcome.SKIP_SIGNAL


@dataclass(frozen=True, slots=True)
class RunStartDecision:
    """Whether a run may start, and — when it may not — why it did not."""

    #: Every reason the register was refused. Empty when it was accepted.
    findings: tuple[Finding, ...]

    @property
    def may_start(self) -> bool:
        return not self.findings

    @property
    def outcome(self) -> Optional[TerminalOutcome]:
        """The ARP outcome, or ``None`` when the run starts normally."""

        return None if self.may_start else REGISTER_FAILURE_OUTCOME

    @property
    def reason(self) -> Optional[str]:
        """The reason category, or ``None`` when the run starts normally."""

        return None if self.may_start else KNOWLEDGE_REGISTER_INVALID

    def summary(self) -> str:
        """One line per finding, for the run's trace and for a person."""

        if self.may_start:
            return "the knowledge register is valid"
        return "\n".join(finding.render() for finding in self.findings)


def validate_at_run_start(
    register_dir: Path,
    *,
    client_rule_paths: Sequence[Path] = (),
    baseline: Optional[Mapping[str, RecordBaseline]] = None,
) -> RunStartDecision:
    """Decide whether a run may start on this register.

    `baseline` is accepted and defaults to none on purpose: at run start there is
    no earlier tree to compare against, so rule 7's version-increase half is CI's
    to enforce. Everything else is enforced here exactly as it is there — one
    validator, two places that call it, and no rule that only one of them applies.
    """

    return RunStartDecision(
        findings=validate_register(
            register_dir,
            client_rule_paths=client_rule_paths,
            baseline=baseline,
        )
    )
