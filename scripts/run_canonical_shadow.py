#!/usr/bin/env python3
"""Run the canonical engine on real signals, in shadow, and report (#308, SL-7).

The entry point ``.github/workflows/canonical_shadow_run.yml`` calls. It picks
candidates out of the research stream's own store, runs S-00 → S-14 over each
through :func:`~src.run.shadow_run.run_canonical_shadow`, and prints what each
run cost — model calls per stage, the six destination decisions, the
fingerprints — because measuring that cost before anything is optimized is the
whole of SL-7.

It publishes nothing, and not by choice: S-14 runs in shadow mode, the
composition root constructs no publisher, and this script imports neither a
publisher nor the marker store. It does not consult the publication idempotency
authority and does not write ``published_signal_ids.txt`` either — a run that
will not publish has nothing to be idempotent about, and recording one in an
authority that arbitrates real publications would make a measurement suppress
a publication somebody meant to make.

Which signal it runs on
-----------------------
The most recent candidates whose record states the two editorial
classifications #365 persists. That is a **scheduling** choice and not a
screening one: S-00 still applies the client's fit rules to the stated values
and still refuses a value the contract does not admit, with the rule named in
the trace. What the selector avoids is spending a scheduled run on a record
that states nothing, which no contract rule has anything to refuse and which
measures the refusal path rather than the engine. ``--any-signal`` runs the
most recent candidates regardless, for measuring exactly that path.

The 134 historical signals carry neither field by #365's deliberate decision,
so until the daily research job has enriched a signal this script selects
nothing and says so (:data:`NO_CLASSIFIED_SIGNAL`). That is a state of the
data, and a workflow that went red for it would train everybody to ignore the
colour (#231).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

# Running a script by path puts ``scripts/`` on ``sys.path``, not the
# repository root, so ``import src...`` would fail without this (#274). The
# three scripts beside this one do the same thing for the same reason.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.run.shadow_run import (  # noqa: E402
    SHADOW_CEILING_VAR,
    configured_shadow_ceiling,
    run_canonical_shadow,
    shadow_configuration,
)
from src.run.signal_adapter import (  # noqa: E402
    DOMAIN_FIELD,
    RISK_FIELD,
    SIGNAL_ID_FIELD,
)
from src.run.walking_skeleton import (  # noqa: E402
    CANONICAL_DESTINATIONS,
    GoldenEngineRun,
)

#: A completed search that selected nothing to run. The idiom
#: ``scripts/streams/resolve_research_signal.py`` uses, and the same number:
#: "nothing to do" is not a failure and must not be reported as one.
NO_CLASSIFIED_SIGNAL = 3

DEFAULT_ACTIVE_PATH = "data/research/signals_active.jsonl"


def candidates(active_path: Path) -> list[dict[str, Any]]:
    """Every intake record in the stream's store, most recent first.

    Most recent first because the store is appended to, and a shadow run wants
    the material the engine would be asked about today. A malformed line is
    skipped rather than stopping the selection: the store is written by another
    job, and one bad line must not make the measurement impossible.
    """

    if not active_path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in active_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and str(
            record.get(SIGNAL_ID_FIELD, "")
        ).strip():
            records.append(record)
    records.reverse()
    return records


def states_its_classification(record: dict[str, Any]) -> bool:
    """Does the record state both fields the client's fit rules read?

    Stated, not admitted: whether the value is one the contract allows is
    S-00's question and is answered by the rule, in the trace.
    """

    return all(
        str(record.get(field, "")).strip() for field in (DOMAIN_FIELD, RISK_FIELD)
    )


def selected(
    records: Sequence[dict[str, Any]], *, count: int, any_signal: bool
) -> list[dict[str, Any]]:
    """The records this invocation will run, in the order it will run them."""

    eligible = (
        list(records)
        if any_signal
        else [record for record in records if states_its_classification(record)]
    )
    return eligible[:count]


def report(run: GoldenEngineRun) -> str:
    """One run's measurement, as the lines the job summary prints.

    Everything here is read off the RunSummary the run already wrote, so the
    numbers in the log and the numbers in the ledger cannot disagree.
    """

    summary = run.summary
    decisions = sum(
        len(record.outputs) for record in run.records if record.stage == "S-07"
    )
    lines = [
        f"### run `{summary.run_id}`",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| signals | {', '.join(summary.signal_ids) or '—'} |",
        f"| stopped at | {run.execution.stopped_at or 'S-14'} |",
        f"| destination decisions | {decisions} of "
        f"{len(CANONICAL_DESTINATIONS)} |",
        f"| accepted texts | {len(run.execution.accepted)} |",
        f"| fingerprints | {len(run.execution.fingerprints)} |",
        f"| model calls | {summary.calls_total} of "
        f"{summary.call_budget_limit} |",
        f"| manifest verified | {run.verification.verified_entities} entities, "
        f"{run.verification.verified_stage_records} stage records |",
        f"| ledger commit | {summary.ledger_commit.value} |",
        "",
        "| Stage | Calls |",
        "|---|---|",
    ]
    lines += [
        f"| {entry.stage} | {entry.calls} |" for entry in summary.stage_calls
    ]
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the canonical engine on real signals, without publishing"
    )
    parser.add_argument(
        "--signals",
        type=int,
        default=1,
        help="how many candidates to run, most recent first",
    )
    parser.add_argument("--active-path", default=DEFAULT_ACTIVE_PATH)
    parser.add_argument(
        "--any-signal",
        action="store_true",
        help=(
            "run the most recent candidates whether or not their record states "
            "the editorial classifications S-00's fit rules read"
        ),
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="commit the run's durable learning records (§3.1)",
    )
    parser.add_argument(
        "--runs-root",
        default=None,
        help="where the run workspaces go; the repository's own root by default",
    )
    args = parser.parse_args(argv)

    if args.signals < 1:
        print(
            f"--signals is {args.signals}; a run of no signal measures nothing.",
            file=sys.stderr,
        )
        return 2

    ceiling = configured_shadow_ceiling()
    chosen = selected(
        candidates(Path(args.active_path)),
        count=args.signals,
        any_signal=args.any_signal,
    )
    if not chosen:
        print(
            "No candidate in "
            f"{args.active_path} states {DOMAIN_FIELD} and {RISK_FIELD}, so "
            "there is nothing for a canonical shadow run to measure. The "
            "research job writes both when it enriches a signal; until then "
            "this is a state of the data and not a failure.",
            file=sys.stderr,
        )
        return NO_CLASSIFIED_SIGNAL

    # Loaded once for every run of this invocation: which contract a run
    # executed against is decided by the code that loaded it, and reloading per
    # signal would let two runs of one invocation differ by an edit made
    # between them.
    configuration = shadow_configuration()
    print(f"## Canonical shadow runs ({SHADOW_CEILING_VAR}={ceiling})")
    print()
    failures = 0
    for record in chosen:
        signal_id = str(record.get(SIGNAL_ID_FIELD, "")).strip()
        try:
            run = run_canonical_shadow(
                record,
                configuration=configuration,
                runs_root=None if args.runs_root is None else Path(args.runs_root),
                commit=args.commit,
            )
        except Exception as exc:  # noqa: BLE001 — one signal must not stop the rest
            failures += 1
            print(f"### run over `{signal_id}` did not complete")
            print()
            print(f"- `{type(exc).__name__}`: {exc}")
            print()
            continue
        print(report(run))
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
