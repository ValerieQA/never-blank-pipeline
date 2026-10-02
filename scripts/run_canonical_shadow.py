#!/usr/bin/env python3
"""The canonical shadow run: S-00 → S-14 on a real signal, publishing nothing.

SL-7's entry point (Issue #308). It assembles the production seams and calls
``run_golden_engine`` — the same function #351 proved and #370 nets — and it
publishes nothing because S-14 runs in shadow: the stage packages what can be
packaged and fingerprints every accepted text, and reaches no publisher, no
image pipeline and no marker store.

**It is a composition root and nothing else.** Every producer here is the
production one: ``golden_engine_configuration`` for the twelve authorities,
``golden_engine_transports`` for the ten model bindings, ``ExaResearchAdapter``
for research with the same fail-closed fallback the legacy root uses,
``resolve_editorial_role`` for the role, ``build_research_request`` for the
request. Nothing is defaulted or invented here; a missing input fails the run.

**Why it costs money.** SL-7 exists to measure what the canonical chain costs
before anything is optimized, and measuring means making the calls. So this is
not enabled by a schedule alone: the workflow that calls it is gated on a
repository variable that is unset by default, and an unset variable is "nobody
has turned this on", not "run it".

Usage:
    python3 scripts/run_canonical_shadow.py --signal-id <id> [--role <role>]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.artifacts import resolve_run_dir
from src.editorial.decision_lens_evaluator import production_evaluator
from src.editorial.decision_lifecycle import RELEASE1_LENS_PROFILE
from src.editorial.editorial_role import resolve_editorial_role
from src.editorial.source_eligibility import LlmChatSourceEligibilityTransport
from src.intake.content_assignment import from_jsonl_signal
from src.research.adapters.exa import ExaResearchAdapter
from src.research.assessment import LlmChatEvidenceJudgmentTransport
from src.research.lifecycle import (
    MissingCredentialResearchProvider,
    build_research_request,
)
from src.run.call_budget import GOLDEN_ENGINE_MAX_CEILING
from src.run.golden_engine import (
    GoldenEngineSeams,
    ResearchBinding,
    golden_engine_configuration,
)
from src.run.transports import golden_engine_transports
from src.run.walking_skeleton import canonical_run_context, run_golden_engine
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext

#: Where the canonical register and the client contract live.
REGISTER_DIR = Path("knowledge")
CLIENT_DIR = Path("clients/never_blank")

#: Where the legacy content packages live, for the research lineage S-01 wraps.
PACKAGES_DIR = Path("reports/content_packages")


def _signal(signal_id: str) -> dict:
    """The intake record, read from the research queue as intake wrote it."""

    path = PACKAGES_DIR / f"{signal_id}.json"
    if not path.exists():
        raise SystemExit(
            f"no intake record at {path}; a shadow run is over a real signal, "
            "and inventing one would measure a run nobody will ever make"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-id", required=True)
    parser.add_argument(
        "--role",
        default="never-blank-monday-documented-case",
        help="a role the business strategy configuration declares",
    )
    parser.add_argument(
        "--call-budget",
        type=int,
        default=GOLDEN_ENGINE_MAX_CEILING,
        help=(
            "the run's ceiling. SL-7 asks for one high enough not to truncate "
            "the measurement, and the canonical path's hard maximum is its own"
        ),
    )
    args = parser.parse_args(argv)

    now = datetime.now(tz=timezone.utc)
    signal = _signal(args.signal_id)
    configuration = load_business_strategy_configuration()
    _, role = resolve_editorial_role(configuration, args.role)
    golden = golden_engine_configuration(
        register_dir=REGISTER_DIR, client_dir=CLIENT_DIR, role=role
    )
    context = StrategyExecutionContext.from_configuration(configuration)
    view = context.decision_lens_editorial

    run_context = canonical_run_context(args.signal_id, now)
    assignment = from_jsonl_signal(
        signal,
        strategy_ref=run_context.strategy_ref,
        strategy_version=run_context.strategy_version,
    )
    legacy_run_dir = resolve_run_dir(
        PACKAGES_DIR, args.signal_id, run_context.run_id
    )
    legacy_run_dir.mkdir(parents=True, exist_ok=True)
    binding = ResearchBinding(
        request=build_research_request(
            run_context, assignment, signal, context.research, now=now
        ),
        identity=view.identity,
        strategy_view=view,
        audience_selection=view.select_audience(None),
        lens_profile=RELEASE1_LENS_PROFILE,
        assignment_id=assignment.assignment_id,
        run_dir=legacy_run_dir,
        run_started_at=now,
    )
    try:
        research = ExaResearchAdapter()
    except EnvironmentError:
        # The same fail-closed fallback the legacy composition root uses: a run
        # without credentials records a research failure rather than inventing
        # evidence.
        research = MissingCredentialResearchProvider()
    seams = GoldenEngineSeams(
        transports=golden_engine_transports(),
        research=research,
        eligibility=LlmChatSourceEligibilityTransport(),
        evidence_judgment=LlmChatEvidenceJudgmentTransport(),
        # The maintained Release 1 evaluator, built by its own factory rather
        # than assembled here: the instructions it reads and the transport it
        # speaks through are that module's to choose.
        relevance=production_evaluator(),
    )

    run = run_golden_engine(
        seams=seams,
        configuration=golden,
        signal=signal,
        binding=binding,
        run_context=run_context,
        call_budget_limit=args.call_budget,
        now=now,
    )
    summary = run.summary
    print(f"  run_id            {summary.run_id}")
    print(f"  calls             {summary.calls_total} of {summary.call_budget_limit}")
    print(f"  accepted          {len(run.execution.accepted)} destination(s)")
    print(f"  fingerprints      {len(summary.fingerprint_ids)}")
    print(f"  publications      {len(summary.publications)} (shadow: none)")
    for record in run.execution.packages:
        print(f"  package {record.destination.value:10} {record.state.value}")
    print(f"  summary           {run.summary_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the workflow's entry
    sys.exit(main())
