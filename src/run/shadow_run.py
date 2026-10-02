"""The scheduled canonical shadow run: production seams, no publication (#308).

SL-7 asks for "the complete canonical chain S-00 → S-14 (no external publish
call) for all six destinations **on real signals**", on a schedule, with its own
ceiling "set high enough not to truncate the measurement". #351 built the engine
and :func:`~src.run.walking_skeleton.run_golden_engine` runs it; what was
missing is the composition root — the one place that builds the real boundaries,
reads the real contracts and hands an intake record to the engine. This is it.

What makes it a shadow run, and not a flag
------------------------------------------
Three things, and none of them is a condition anything evaluates:

1. **S-14 is the shadow stage.** :mod:`src.run.shadow_publication`
   constructs no publisher, consults no idempotency authority and writes no
   marker. There is no argument here that would turn that into a live stage;
2. **nothing in this module imports a publisher or the marker store.** The
   seams it builds are the research provider, the eleven model boundaries and
   the Decision-Lens evaluator — the inputs a run *reads*. Nothing it builds
   can write to a platform;
3. **the ceiling is its own.** :func:`configured_shadow_ceiling` is a separate
   variable from ``NB_RUN_TEXT_CALL_BUDGET``, so raising the measurement
   ceiling cannot raise the legacy engine's, and its floor is the measured cost
   of a clean six-destination run — a ceiling below that would stop the run
   in the middle and the measurement would be of the stop.

The research provider is chosen the way the existing production composition
root chooses it (``scripts/generate_and_publish.py``): the Exa adapter when its
credential is configured, and
:class:`~src.research.lifecycle.MissingCredentialResearchProvider` when it is
not. The second is a typed fail-closed provider, not a stub — S-01 records
``research_failed`` and skips the signal — so an unconfigured shadow run
measures an outage honestly instead of inventing evidence.

Sources: ``docs/editorial/architecture/07_STEP6_VERTICAL_SLICES.md`` SL-7;
``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.3 and §6;
``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §4.1.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Optional

from src.artifacts import resolve_run_dir
from src.editorial.decision_lens_evaluator import production_evaluator
from src.editorial.decision_lifecycle import RELEASE1_LENS_PROFILE
from src.editorial.editorial_role import resolve_editorial_role
from src.editorial.source_eligibility import LlmChatSourceEligibilityTransport
from src.editorial_core.signal_selection import PortfolioFingerprint
from src.editorial_core.text_check import PriorPublication, TextFingerprint
from src.intake.content_assignment import from_jsonl_signal
from src.research.adapters import ExaResearchAdapter
from src.research.assessment import LlmChatEvidenceJudgmentTransport
from src.research.lifecycle import (
    MissingCredentialResearchProvider,
    build_research_request,
)
from src.research.provider import ResearchProvider
from src.run.call_budget import (
    CallBudgetConfigurationError,
    GOLDEN_ENGINE_MAX_CEILING,
)
from src.run.golden_engine import (
    GoldenEngineConfiguration,
    GoldenEngineSeams,
    ResearchBinding,
    golden_engine_configuration,
)
from src.run.run_inputs import run_inputs
from src.run.transports import golden_engine_transports
from src.run.walking_skeleton import (
    GoldenEngineRun,
    canonical_run_context,
    run_golden_engine,
)
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.client_contracts import contracts_for_role
from src.strategy.execution_context import StrategyExecutionContext

#: The register and the client directory a production shadow run reads. The
#: repository's own, so a contract that changes changes what the run executed
#: against — and named here rather than defaulted inside the engine, which
#: loads no contract of its own.
REGISTER_DIR: Final[Path] = Path("knowledge")
CLIENT_DIR: Final[Path] = Path("clients/never_blank")

#: Where the legacy content-package artifacts of the wrapped research contract
#: go (``research.json``, ``decision.json``). Not the canonical workspace: the
#: canonical run references those two by path and digest.
PACKAGES_DIR: Final[Path] = Path("reports/content_packages")

#: The declared role a canonical shadow run executes under. ``wednesday-golden``
#: is the role that states source-eligibility criteria, so S-00's eligibility
#: transport is exercised rather than skipped as "this role restricts nothing".
ROLE_ID: Final[str] = "never-blank-wednesday-golden"

#: The measurement ceiling's own variable. Deliberately **not**
#: ``NB_RUN_TEXT_CALL_BUDGET``: that one is the legacy engine's and is capped at
#: ``R1_MAX_CEILING`` (40), which no six-destination canonical run has ever fit
#: inside. Raising one must not raise the other.
SHADOW_CEILING_VAR: Final[str] = "NB_CANONICAL_SHADOW_CALL_BUDGET"

#: The lowest ceiling that does not truncate the measurement. #351's
#: deterministic execution of a clean six-destination run costs exactly 50
#: logical calls — Step 2 §6's six-destination minimum of 44 plus one S-09
#: ranking per destination, which that minimum assumes away — so a run given
#: less than this stops partway through and what it measures is the stop. It is
#: a floor on the *configuration*, not a target spend and not a prediction: a
#: run that legitimately costs less simply costs less.
SHADOW_MEASUREMENT_FLOOR: Final[int] = 50


def configured_shadow_ceiling() -> int:
    """The shadow run's ``RunCallBudget`` ceiling, strictly validated.

    Unset means :data:`~src.run.call_budget.GOLDEN_ENGINE_MAX_CEILING`, the
    canonical path's own ceiling. A configured value is accepted only as the
    canonical decimal representation of an integer **between**
    :data:`SHADOW_MEASUREMENT_FLOOR` and that maximum, and both ends are
    checked: a value above the maximum is a ceiling nobody may raise from here,
    and a value below the floor is a measurement that would be cut short and
    then read as the cost of a complete run — the one mistake SL-7's "set high
    enough not to truncate the measurement" exists to prevent.

    Empty and whitespace-only are **unset**, not invalid: GitHub Actions
    renders an unconfigured variable as an empty string in ``env:`` (#173), and
    refusing one would make a scheduled run fail for a value nobody set. It is
    safe to default here and nowhere else in this function, because the default
    is the maximum — a runaway guard, never a target — and the floor still
    applies to every value anybody does state.

    Anything else is refused, never clamped, for the reason
    ``configured_run_call_ceiling`` refuses: silently repairing a configured
    number hides the next mistake.
    """

    raw = os.environ.get(SHADOW_CEILING_VAR)
    if raw is None or not raw.strip():
        return GOLDEN_ENGINE_MAX_CEILING
    if raw.isascii() and raw.isdigit() and str(int(raw)) == raw:
        value = int(raw)
        if SHADOW_MEASUREMENT_FLOOR <= value <= GOLDEN_ENGINE_MAX_CEILING:
            return value
    raise CallBudgetConfigurationError(
        f"{SHADOW_CEILING_VAR} must be a canonical integer between "
        f"{SHADOW_MEASUREMENT_FLOOR} and {GOLDEN_ENGINE_MAX_CEILING}; got "
        f"{raw!r}. The floor is what a clean six-destination canonical run "
        "costs, and a ceiling below it measures a truncated run; the maximum "
        "is the canonical path's own. Refusing to start a shadow run with an "
        "invalid ceiling."
    )


def research_provider() -> ResearchProvider:
    """The retrieval boundary, chosen as the production composition root does.

    The Exa adapter when ``NB_EXA_API_KEY`` is configured, and the typed
    fail-closed provider when it is not — which is a refusal S-01 records as
    ``research_failed`` and skips the signal on, not a stub that answers. A
    shadow run with no credential therefore measures an outage rather than
    reasoning from evidence nobody retrieved.
    """

    try:
        return ExaResearchAdapter()
    except EnvironmentError:
        return MissingCredentialResearchProvider()


def production_seams() -> GoldenEngineSeams:
    """The five boundaries a canonical run is handed, all of them production.

    Built here and nowhere inside the engine: ``run_golden_engine`` takes its
    seams as an argument precisely so that a run can state where each came
    from, and so that nothing in the engine can construct a provider of its
    own. Raises before any seam exists when ``NB_GOLDEN_ENGINE_MODEL`` is not
    configured — the ten model boundaries have no fallback.
    """

    return GoldenEngineSeams(
        transports=golden_engine_transports(),
        research=research_provider(),
        eligibility=LlmChatSourceEligibilityTransport(),
        evidence_judgment=LlmChatEvidenceJudgmentTransport(),
        relevance=production_evaluator(),
    )


def shadow_configuration(
    *,
    register_dir: Path = REGISTER_DIR,
    client_dir: Path = CLIENT_DIR,
    role_id: str = ROLE_ID,
) -> GoldenEngineConfiguration:
    """Every authority the run executes against, from its own producer.

    The role is resolved against the declared business strategy configuration
    rather than authored: which role a run executes under decides what a
    candidate is judged against, and a composition root that invented one would
    be choosing the criteria.
    """

    configuration = load_business_strategy_configuration()
    _, role = resolve_editorial_role(configuration, role_id, client_dir)
    return golden_engine_configuration(
        register_dir=register_dir, client_dir=client_dir, role=role
    )


def run_canonical_shadow(
    signal: Mapping[str, Any],
    *,
    configuration: Optional[GoldenEngineConfiguration] = None,
    seams: Optional[GoldenEngineSeams] = None,
    role_id: str = ROLE_ID,
    client_dir: Path = CLIENT_DIR,
    packages_dir: Path = PACKAGES_DIR,
    runs_root: Optional[Path] = None,
    ledger_dir: Optional[Path] = None,
    commit: bool = False,
    repo_root: Optional[Path] = None,
    started_at: Optional[datetime] = None,
    call_budget_limit: Optional[int] = None,
    portfolio: Sequence[PortfolioFingerprint] = (),
    priors: Sequence[PriorPublication] = (),
    text_portfolio: Sequence[TextFingerprint] = (),
) -> GoldenEngineRun:
    """Run S-00 → S-14 over one real intake record, in shadow, and report.

    ``signal`` is a parsed ``data/research/signals_active.jsonl`` line — the
    record as intake wrote it. It is handed on unchanged: a record that states
    no editorial domain or risk is refused **by S-00's own fit rule**, with the
    rule named in the trace, and pre-screening it here would take the refusal
    away from the rule that owns it.

    ``priors`` is empty by default and that is the honest value: V-T05 asks
    whether a text has already been published, this run publishes nothing, and
    a shadow run that handed itself a prior publication would be comparing
    against something that does not exist
    (:func:`~src.run.shadow_publication.prior_publication` is where that
    rule lives). ``text_portfolio`` and ``portfolio`` are the soft portfolio
    inputs and are likewise the caller's to supply.

    ``commit`` is off by default, as it is for every run of this engine: a
    shadow run that wrote to the repository because nobody said otherwise would
    be a production effect.
    """

    moment = started_at or datetime.now(tz=timezone.utc)
    golden = (
        configuration
        if configuration is not None
        else shadow_configuration(client_dir=client_dir, role_id=role_id)
    )
    run_context = canonical_run_context(
        str(signal.get("SIGNAL_ID") or "unidentified-signal"), moment
    )
    assignment = from_jsonl_signal(
        dict(signal),
        strategy_ref=run_context.strategy_ref,
        strategy_version=run_context.strategy_version,
    )
    context = StrategyExecutionContext.from_configuration(
        load_business_strategy_configuration()
    )
    strategy_view = context.decision_lens_editorial
    legacy_run_dir = resolve_run_dir(
        packages_dir, assignment.assignment_id, run_context.run_id
    )
    legacy_run_dir.mkdir(parents=True, exist_ok=True)
    binding = ResearchBinding(
        request=build_research_request(
            run_context, assignment, dict(signal), context.research, now=moment
        ),
        identity=strategy_view.identity,
        strategy_view=strategy_view,
        audience_selection=strategy_view.select_audience(None),
        lens_profile=RELEASE1_LENS_PROFILE,
        assignment_id=assignment.assignment_id,
        run_dir=legacy_run_dir,
        run_started_at=moment,
    )
    return run_golden_engine(
        seams=seams if seams is not None else production_seams(),
        configuration=golden,
        signal=signal,
        binding=binding,
        run_context=run_context,
        runs_root=runs_root,
        call_budget_limit=(
            call_budget_limit
            if call_budget_limit is not None
            else configured_shadow_ceiling()
        ),
        now=moment,
        portfolio=portfolio,
        priors=priors,
        text_portfolio=text_portfolio,
        # §4.1: what the run read, derived from the reading. The engine's own
        # configuration carries the register it loaded, so the manifest states
        # the identities of the documents this run executed against rather than
        # the sentence a run with no record of them states.
        inputs=run_inputs(
            contracts=contracts_for_role(role_id, client_dir),
            knowledge=golden.knowledge,
            register_dir=golden.register_dir,
        ),
        ledger_dir=ledger_dir,
        commit=commit,
        repo_root=repo_root,
    )
