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
from src.run.transports import (
    configured_golden_engine_model,
    golden_engine_transports,
)
from src.run.walking_skeleton import canonical_run_context, run_golden_engine
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.execution_context import StrategyExecutionContext

#: Where the canonical register and the client contract live.
REGISTER_DIR = Path("knowledge")
CLIENT_DIR = Path("clients/never_blank")

#: Where the legacy content packages live, for the research lineage S-01 wraps.
#: **Not** the intake source — see :data:`ACTIVE_SIGNALS`. A prepared package
#: holds five keys (``HEADLINE``, ``SIGNAL_ID``, ``content``, ``images``,
#: ``prepared_at``) and is an output of the legacy pipeline, not an input to
#: this one.
PACKAGES_DIR = Path("reports/content_packages")

#: The intake record S-00 reads, "spelled as intake spells it"
#: (``src/run/signal_adapter.py``). The same file the production selector reads
#: (``select_eligible_signal.py --active-path``) and the one
#: ``src/strategy/contract_fit.py`` calls "the real intake record".
ACTIVE_SIGNALS = Path("data/research/signals_active.jsonl")


def _signal(signal_id: str) -> dict:
    """The intake record, read from the research queue as intake wrote it.

    By ``SIGNAL_ID`` out of the queue, and handed on **unchanged**. Nothing here
    screens the record for the fields the contract's fit rules require: those
    rules own that refusal, and ``signal_adapter`` states why taking it away
    would be wrong — a pre-screen "would take the refusal away from the rule
    that owns it and leave the trace unable to say which rule decided". A
    record S-00 will refuse is therefore read, passed on, and refused in the
    trace, which is the outcome a measurement run needs to record.
    """

    if not ACTIVE_SIGNALS.exists():
        raise SystemExit(
            f"no research queue at {ACTIVE_SIGNALS}; a shadow run is over a "
            "real signal, and inventing one would measure a run nobody will "
            "ever make"
        )
    for line in ACTIVE_SIGNALS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if str(record.get("SIGNAL_ID", "")).strip() == signal_id:
            return record
    raise SystemExit(
        f"{signal_id} is not in {ACTIVE_SIGNALS}; a shadow run is over a signal "
        "intake really wrote, and the queue is where intake writes them"
    )


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
    parser.add_argument(
        "--commit",
        action="store_true",
        help=(
            "commit and push the durable learning records this run writes "
            "(§3.1). Off by default, like run_golden_engine's own posture: a "
            "local measurement run should not write to the repository. The "
            "workflow passes it, because a record only the expired runner "
            "holds is not Portfolio Memory"
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
    # One authoritative model identity for the whole canonical run.
    #
    # `golden_engine_transports()` already reads `NB_GOLDEN_ENGINE_MODEL` for
    # the ten stage transports — and ten was exactly the hole. The three seams
    # at the front of the chain are not Golden Engine transports and resolved
    # their own model through `model_enrich()`, so #308's first attempted
    # acceptance run spent its only call on `gpt-4o` while
    # `NB_GOLDEN_ENGINE_MODEL` named another model, and the judgement that
    # ended the run was made by a model nobody authorized for it.
    #
    # Injected here rather than changed in those classes: their default is
    # untouched, so Monday, Wednesday and every legacy caller keep the model
    # routing they have. What changes is only what *this* composition root
    # asks for.
    model = configured_golden_engine_model()
    seams = GoldenEngineSeams(
        transports=golden_engine_transports(),
        research=research,
        eligibility=LlmChatSourceEligibilityTransport(model),
        evidence_judgment=LlmChatEvidenceJudgmentTransport(model),
        # The maintained Release 1 evaluator, built by its own factory rather
        # than assembled here: the instructions it reads are that module's to
        # choose. The model is not — this run names it.
        relevance=production_evaluator(model=model),
    )

    run = run_golden_engine(
        seams=seams,
        configuration=golden,
        signal=signal,
        binding=binding,
        run_context=run_context,
        call_budget_limit=args.call_budget,
        now=now,
        # The canonical mechanism commits the exact E-16 records S-14 wrote,
        # by path, and the summary states that commit's status. There is no
        # second, broader commit step: one that staged the ledger directory
        # would report success over files this run never produced.
        commit=args.commit,
        repo_root=Path.cwd() if args.commit else None,
        # The identity this root chose, handed over rather than re-read: an
        # early-stop record that consulted the environment again could name a
        # model the run did not actually use.
        model=model,
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
    print(f"  ledger commit     {summary.ledger_commit.value}")
    print(f"  model             {model}")
    print(f"  workspace         {run.run_dir}")
    if run.early_stop_path is not None:
        print(f"  early stop        {run.early_stop_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the workflow's entry
    sys.exit(main())
