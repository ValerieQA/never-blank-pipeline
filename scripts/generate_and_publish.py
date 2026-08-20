"""
Never Blank — Canonical Release 1 entry point.

This script is the single authorized controlled execution path for Release 1.

Canonical call flow
-------------------
  CLI --signal-id
  → load active strategy (required)
  → load JSONL signal
  → DEFAULT_INTAKE_ADAPTER.adapt() → ContentAssignment
  → RunContext.from_assignment()  → one RunContext per execution (run_id immutable)
  → _require_run_id()             → fail-closed guard at intake
  → _build_legacy_research_context()  → ResearchContext with run_id injected
  → _assert_run_id_match()        → identity check at research boundary
  → [fresh-gen] execute_and_persist_research() → run-scoped research.json
  → [fresh-gen] evaluate_and_persist_decision() → run-scoped decision.json
  → require_proceed()             → ONLY a reloaded PROCEED decision continues;
                                    every other disposition or evaluator failure
                                    stops the run before narrative/editorial/
                                    visual/package/publisher work (Issue #60)
  → [fresh-gen] rc.to_editorial() → EditorialContext with run_id propagated
  → [fresh-gen] _assert_run_id_match() → identity check at editorial boundary
  → [fresh-gen] run_editorial_acceptance() → explicit editorial verdict on the
                                    Wix article: ACCEPT continues; REVISE gets
                                    exactly one controlled revision + recheck;
                                    everything else stops before packaging and
                                    publication (Issue #89 / Story #13)
  → VisualArtifactRequest         → visual boundary typed adapter (blocked stub)
  → _require_run_id()             → guard at image-preparation
  → _require_run_id()             → guard at validation
  → validate_article_for_publish() → ValidationResult per platform
  → _assert_run_id_match()        → identity check on each ValidationResult
  → canonical packages            → frozen Wix/LinkedIn publication packages
  → evaluate_publication_preflight() → per-channel ALLOW/BLOCK verdict
  → write_preflight_result_json() → verdict persisted before any external call
  → _require_run_id()             → guard at publication
  → publisher.publish()           → PublishResult (run_id empty from publisher)
  → _normalize_publish_result()   → inject/verify run_id, fail closed on mismatch
  → R1RunReport                   → final run-report boundary
  → _emit_run_report()            → logs report (persistent storage: Issue #16)

Artifact layout (Task #28)
--------------------------
  reports/content_packages/<signal_id>/runs/<run_id>/research.json
  reports/content_packages/<signal_id>/runs/<run_id>/decision.json
  reports/content_packages/<signal_id>/runs/<run_id>/editorial_acceptance.json
  reports/content_packages/<signal_id>/runs/<run_id>/generated.json
  reports/content_packages/<signal_id>/runs/<run_id>/publication_results.json

  editorial_acceptance.json — editorial audit record written once for every
                         run that reaches editorial acceptance, accepted or
                         blocked (rubric identity, both reviews, disposition).
                         generated.json exists only for accepted articles.

  decision.json        — canonical Issue #58 Decision Lens artifact, written
                         exactly once after research, before any editorial work.
                         Immutable; create-once; reused runs revalidate it.

  generated.json       — written exactly once, immediately after content generation.
                         Immutable. Never overwritten by publication or re-publication.
  publication_results.json — written once after Wix/LinkedIn attempt.
                         Carries run_id, source_run_id, generation_run_id, results.
  Both are written atomically with create-once semantics and fail closed on collision.

--from-package lifecycle (Option B — publication is a new run)
--------------------------------------------------------------
  --from-package --source-run-id <generation_run_id>

  Reads <signal_id>/runs/<source_run_id>/generated.json exactly.
  Creates a new RunContext (pub run_id). Writes publication_results.json
  under the new pub run directory. The source generated.json is never modified.

  For fresh-gen runs: source_run_id == run_id == generation_run_id.
  For from-package:   source_run_id == original generation run_id (stable).

--legacy-package mode
---------------------
  --legacy-package reads the flat legacy artifact:
      reports/content_packages/{signal_id}_generated.json
  Requires explicit CLI flag; never falls back automatically.
  Never writes back to the legacy path.
  Writes publication_results.json to the current run's run-scoped directory.
  Legacy provenance is recorded explicitly in publication_results.json.

Release 1 publishing scope: Wix and LinkedIn.
Facebook, Instagram, Threads, and Telegram are excluded from this path
and reported as [skipped-not-r1].

Usage (local):
    NB_OPENAI_API_KEY=... python scripts/generate_and_publish.py --signal-id <id> [--dry-run]

Args:
    --signal-id      : SIGNAL_ID from data/research/selected_signals.jsonl or signals_active.jsonl
    --dry-run        : Generate and validate content, save generated.json, but do NOT publish
    --from-package   : Skip LLM generation — publish run-scoped generated.json (requires --source-run-id)
    --source-run-id  : run_id of the source generated.json to load (required with --from-package)
    --legacy-package : Read legacy flat artifact {signal_id}_generated.json (explicit adapter)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.intake import (
    ContentAssignment,
    IntakeAdapter,
    IntakeAdapterError,
    JsonlIntakeAdapter,
)
from src.intake.assignment_record import AssignmentRecord
from src.intake.audience_routing import audience_request
from src.run.code_identity import resolve_code_identity
from src.lifecycle.signal_lifecycle import ResearchContext
from src.research.provider import ResearchProvider
from src.research.adapters.exa import ExaResearchAdapter
from src.research.assessment import EvidenceAssessmentError, EvidenceJudgmentTransport
from src.research.lifecycle import (
    ResearchGateError,
    build_research_request,
    execute_and_persist_research,
    load_research_envelope,
    validate_research_envelope,
    MissingCredentialResearchProvider,
)
from src.run import ExecutionMode, RunContext
from src.analytics.blog import BlogCollector
from src.analytics.linkedin import LinkedInCollector
from src.analytics.orchestrator import run_analytics_pipeline
from src.editorial.editorial_role import (
    EditorialRoleError,
    render_editorial_role_rules,
    resolve_editorial_role,
)
from src.editorial.source_transparency import (
    SourceTransparencyError,
    validate_source_transparency,
)
from src.editorial.pipeline import ArticleGenerationError, generate_article
from src.editorial.decision_lens_evaluator import (
    DecisionLensEvaluator,
    production_evaluator,
)
from src.editorial.decision_lifecycle import (
    RELEASE1_LENS_PROFILE,
    DecisionGateError,
    evaluate_and_persist_decision,
    load_decision_artifact,
    require_proceed,
)
from src.editorial.linkedin_composition import (
    LinkedInCompositionError,
    accept_linkedin_composition,
)
from src.visual.contract import (
    VisualGateError,
    build_visual_assets_record,
    reuse_visual_assets_record,
)
from src.editorial.editorial_acceptance import (
    ArticleRevisionTransport,
    EditorialAcceptanceError,
    EditorialAcceptanceRubric,
    EditorialReviewTransport,
    LlmChatArticleRevisionTransport,
    LlmChatEditorialReviewTransport,
    run_editorial_acceptance,
)
from src.publishing import formatting
from src.publishing.image_pipeline import CURRENT_DESIGN_VERSION
from src.publishing.hashtags import generate_hashtags
from src.publishing.facebook import FacebookPublisher
from src.publishing.instagram import InstagramPublisher
from src.publishing.linkedin import LinkedInPublisher
from pydantic import ValidationError as PydanticValidationError

from src.publishing.idempotency import (
    LinkedInPublicationIdentity,
    WixPublicationIdentity,
    find_prior_linkedin_publication,
    find_prior_wix_publication,
)
from src.publishing.preflight import (
    ChannelPackageOutcome,
    FreshnessVerdict,
    PreflightDisposition,
    ReadinessVerdict,
    evaluate_publication_preflight,
)
from src.publishing.package import (
    LinkedInPublicationTarget,
    PackageFailureCategory,
    PublicationPackageError,
    WixPublicationTarget,
    build_linkedin_publication_package,
    build_wix_publication_package,
    canonical_slug,
)
from src.publishing.result import PublishResult, PublishStatus
from src.publishing.telegram import TelegramPublisher
from src.publishing.threads import ThreadsPublisher
from src.publishing.wix import WixPublisher
from src.artifacts import (
    ArtifactCollisionError,
    load_run_generated,
    load_business_strategy_snapshot,
    resolve_run_dir,
    load_linkedin_composition_json,
    load_visual_assets_json,
    write_assignment_json,
    write_editorial_acceptance_json,
    write_editorial_review_content_json,
    write_generated_json,
    write_linkedin_composition_json,
    write_visual_assets_json,
    write_business_strategy_snapshot,
    write_preflight_result_json,
    write_publication_results_json,
    write_run_report_json,
)
from src.reporting import R1RunReport
from src.reporting.run_report import (
    RunReportError,
    TerminalDisposition,
    TerminalStage,
    build_run_report,
)
from src.strategy.history import append_published_entry
from src.strategy.business_config import (
    BusinessStrategyConfiguration,
    BusinessStrategyConfigurationError,
    load_business_strategy_configuration,
)
from src.strategy.execution_context import (
    StrategyExecutionContext,
    StrategyExecutionError,
    assert_campaign_reference,
    identity_from_mapping,
    require_configuration_identity,
)
# get_strategy_context remains imported for legacy test/caller patch surfaces;
# the canonical path no longer calls it.
from src.strategy.loader import get_cta_mode, get_strategy_context, load_active_strategy
from src.strategy.models import PlatformPublication, PublishedEntry
from src.strategy.validators import ValidationResult, validate_article_for_publish
from src.utils.logger import get_logger
from src.visual import VisualArtifactRequest

log = get_logger("generate_and_publish")

PACKAGES_DIR   = Path("reports/content_packages")
PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
SIGNALS_FILES  = [
    Path("data/research/selected_signals.jsonl"),
    Path("data/research/signals_active.jsonl"),
]
HISTORY_FILE   = Path("strategy/published_content_index.jsonl")
SEP            = "─" * 64
_OK_STATUSES   = {"PUBLISHED", "DRAFT_CREATED", "published_url_unavailable"}
# Issue #105: a REUSED channel is not a failure — the article is live from the
# earlier publication — but it is deliberately NOT an OK status, so a retry can
# never be recorded as a second fresh publication in the history index.
#
# Issue #108: PROVIDER_DUPLICATE belongs to NEITHER set. A provider duplicate
# response proves a duplicate exists but never which post, so the channel is
# neither a successful publication nor a completed one.
_COMPLETED_STATUSES = _OK_STATUSES | {"REUSED"}
DEFAULT_INTAKE_ADAPTER: IntakeAdapter = JsonlIntakeAdapter()


def _load_signal(signal_id: str) -> dict:
    for path in SIGNALS_FILES:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("SIGNAL_ID") == signal_id:
                    return obj
            except Exception:
                pass
    raise FileNotFoundError(
        f"Signal {signal_id!r} not found in:\n"
        + "\n".join(f"  {p}" for p in SIGNALS_FILES)
    )


def _load_package_images(signal_id: str) -> dict:
    path = PACKAGES_DIR / f"{signal_id}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data.get("images", {}).get("platform_images", {})
        except Exception:
            pass
    return {}


def _slugify(text: str) -> str:
    # Canonical implementation lives with the publication package contract.
    return canonical_slug(text)


def _build_threads(structured: dict) -> list[str]:
    discovery = structured.get("discovery", {})
    candidates = [
        structured.get("hook", ""),
        discovery.get("aha_setup") or discovery.get("first_wrong_explanation", ""),
        structured.get("surviving_explanation", ""),
        structured.get("reframe", ""),
        structured.get("echo_line", ""),
    ]
    sequence: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        post = re.sub(r"\s+", " ", (value or "").strip())
        words = post.split()
        if len(words) > 55:
            post = " ".join(words[:55]).rstrip(" ,;:") + "."
        key = post.lower()
        if post and key not in seen:
            sequence.append(post)
            seen.add(key)
    if not 3 <= len(sequence) <= 5:
        raise ValueError(f"Threads requires 3–5 distinct posts; generated {len(sequence)}")
    return sequence


def _clean_line(value: str, max_words: int = 34) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    words = value.split()
    if len(words) <= max_words:
        return value
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


def _build_telegram(structured: dict, wix_url: str = "") -> str:
    discovery = structured.get("discovery", {})
    observation = (
        discovery.get("aha_setup")
        or discovery.get("first_wrong_explanation")
        or structured.get("hook")
        or structured.get("narrative_spine")
    )
    implication = structured.get("business_translation") or structured.get("reframe")
    lines = [_clean_line(observation), _clean_line(implication)]
    if wix_url:
        lines.append(wix_url.strip())
    return "\n".join(line for line in lines if line)


def _save_generated(
    path: Path,
    signal_id: str,
    headline: str,
    blog_body: str,
    linkedin: str,
    facebook: str,
    instagram: str,
    threads: list[str],
    telegram: str,
    wix_url: str,
    strategy_id: str,
    strategy_started_at: str,
    strategy_version: str,
    generated_at: str | None = None,
    run_id: str = "",
    generation_run_id: str = "",
) -> None:
    data: dict = {
        "run_id":              run_id,
        "signal_id":           signal_id,
        "headline":            headline,
        "generated_at":        generated_at or datetime.now(timezone.utc).isoformat(),
        "strategy_id":         strategy_id,
        "strategy_version":    strategy_version,
        "strategy_started_at": strategy_started_at,
        "wix_url":             wix_url,
        "blog_article":        blog_body,
        "linkedin_post":       linkedin,
        "facebook_post":       facebook,
        "instagram_caption":   instagram,
        "threads_sequence":    threads,
        "telegram_text":       telegram,
    }
    if generation_run_id:
        data["generation_run_id"] = generation_run_id
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# Release 1 publishing scope — only these two publishers are invoked.
_R1_PUBLISHERS = ("wix", "linkedin")
_NON_R1_PUBLISHERS = ("facebook", "instagram", "threads", "telegram")


def _stop_with_preflight(
    *,
    run_dir: Path,
    run_id: str,
    signal_id: str,
    configuration_identity,
    readiness: ReadinessVerdict,
    override_attempted: bool,
    freshness: Optional[FreshnessVerdict] = None,
) -> int:
    """Persist the authorization verdict for a stop that precedes packaging.

    Issue #101: a publication decision inside Story #17's authorization model
    is never taken outside the canonical preflight boundary. When no channel
    package can exist yet, every channel is recorded in the explicit
    fail-closed state "the canonical package could not be constructed".
    """

    outcomes = [
        ChannelPackageOutcome.failed(
            channel,
            "no canonical package was constructed: the run was blocked before "
            "publication packaging",
        )
        for channel in _R1_PUBLISHERS
    ]
    try:
        verdict = evaluate_publication_preflight(
            packages_dir=PACKAGES_DIR,
            run_id=run_id,
            signal_id=signal_id,
            configuration_identity=configuration_identity,
            channel_outcomes=outcomes,
            override_attempted=override_attempted,
            readiness=readiness,
            freshness=freshness or FreshnessVerdict(verified=True),
        )
        write_preflight_result_json(run_dir, json.loads(verdict.model_dump_json()))
        print(
            f"  preflight: run={verdict.run_disposition.value} "
            f"({run_dir / 'preflight_result.json'})"
        )
    except (ArtifactCollisionError, OSError, ValueError) as exc:
        print(f"  ERROR: publication preflight could not be committed: {exc}")
    return 1


def _require_run_id(run_id: str, stage: str) -> None:
    """
    Fail-closed guard: raise RuntimeError when run_id is missing or blank.

    Called at intake, validation, image-preparation, and publication to ensure
    run identity is always valid before any side effect is triggered.
    """
    if not run_id or not run_id.strip():
        raise RuntimeError(
            f"run_id is missing or blank at stage {stage!r}. "
            "RunContext must be created before any stage is entered."
        )


def _assert_run_id_match(expected: str, actual: str, boundary: str) -> None:
    """
    Fail-closed identity assertion: raise RuntimeError when actual != expected.

    Called at every named stage boundary to prevent silent run_id drift.
    The contract requires one immutable run_id from intake through all boundaries.
    """
    if actual != expected:
        raise RuntimeError(
            f"run_id identity mismatch at boundary {boundary!r}: "
            f"expected={expected!r} actual={actual!r}"
        )


def _normalize_publish_result(
    result: PublishResult,
    expected_run_id: str,
    platform: str,
) -> PublishResult:
    """
    Normalize publisher result run identity — called immediately after publish().

    Publishers do not set run_id (they operate without RunContext knowledge).
    This adapter:
      - Injects expected_run_id when result.run_id is empty (backward compat).
      - Fails closed when result.run_id is non-empty but does not match expected.

    Returns the result with run_id guaranteed to equal expected_run_id.
    """
    if not result.run_id:
        result.run_id = expected_run_id
    elif result.run_id != expected_run_id:
        raise RuntimeError(
            f"PublishResult run_id mismatch for {platform!r}: "
            f"result={result.run_id!r} expected={expected_run_id!r}"
        )
    return result


class _TerminalState:
    """What the run has proven so far, for the single terminalization seam.

    The business body advances this as it goes, so no return path has to
    build a report itself and none can be forgotten. A run that never
    receives a run identity — argument or configuration failures, before the
    run namespace exists — leaves the state empty and is not reportable:
    there is no run to account for.
    """

    __slots__ = ("run_id", "signal_id", "execution_mode", "packages_dir",
                 "stage", "disposition", "errors")

    def __init__(self) -> None:
        self.run_id: Optional[str] = None
        self.signal_id: Optional[str] = None
        self.execution_mode: str = "unknown"
        self.packages_dir: Optional[Path] = None
        self.stage: TerminalStage = TerminalStage.INTAKE
        self.disposition: TerminalDisposition = TerminalDisposition.FAILED
        self.errors: list = []

    def begin(self, *, run_id: str, signal_id: str, execution_mode: str,
              packages_dir: Path) -> None:
        self.run_id = run_id
        self.signal_id = signal_id
        self.execution_mode = execution_mode
        self.packages_dir = packages_dir

    def reached(self, stage: TerminalStage) -> None:
        """Record the last lifecycle stage the run actually reached."""
        self.stage = stage

    def ended(self, stage: TerminalStage, disposition: TerminalDisposition,
              *errors: str) -> None:
        self.stage = stage
        self.disposition = disposition
        self.errors.extend(str(item) for item in errors if item)

    @property
    def reportable(self) -> bool:
        return bool(self.run_id and self.signal_id and self.packages_dir)


def _emit_terminal_report(state: "_TerminalState", exit_code: int) -> None:
    """Persist the authoritative account of one terminal run (Issue #112).

    Called exactly once, after the business run has fully returned, so every
    canonical artifact it references is already committed. A failure here is
    logged and never rewrites the business outcome: a run that failed for a
    reason still fails for that reason, and a successful run is never turned
    into a failure because its account could not be written.
    """

    if not state.reportable:
        return                       # no run namespace — nothing to account for

    disposition = state.disposition
    if exit_code == 0 and disposition is TerminalDisposition.FAILED:
        disposition = TerminalDisposition.COMPLETED

    try:
        report = build_run_report(
            state.packages_dir,
            run_id=state.run_id,
            signal_id=state.signal_id,
            execution_mode=state.execution_mode,
            terminal_stage=state.stage,
            terminal_disposition=disposition,
            errors=tuple(state.errors),
        )
        write_run_report_json(
            resolve_run_dir(state.packages_dir, state.signal_id, state.run_id),
            json.loads(report.model_dump_json()),
        )
        log.info(
            "run_report: run_id=%s stage=%s disposition=%s completed=%s",
            report.run_id, report.terminal_stage.value,
            report.terminal_disposition.value, report.completed,
        )
    except ArtifactCollisionError:
        # An existing report is never overwritten and never silently updated.
        log.warning(
            "run_report already exists for run_id=%s — the existing report stands",
            state.run_id,
        )
    except (RunReportError, OSError, TypeError, ValueError) as exc:
        # Never let the account rewrite the outcome it describes.
        log.warning(
            "run_report could not be written for run_id=%s (%s) — "
            "the run outcome is unchanged",
            state.run_id, type(exc).__name__,
        )


def _emit_run_report(report: R1RunReport) -> None:
    """
    Emit the final run report.  Release 1: log only.
    Persistent storage, artifact naming, and evidence provenance: Issue #16.
    """
    log.info(
        "R1RunReport: run_id=%s signal_id=%s mode=%s completed=%s ok=%s errors=%r",
        report.run_id,
        report.signal_id,
        report.execution_mode,
        report.completed,
        report.ok(),
        report.errors,
    )


def _build_legacy_research_context(
    assignment: ContentAssignment,
    raw_signal: dict,
    run_ctx: "RunContext",
) -> ResearchContext:
    """
    Compatibility boundary — converts a ContentAssignment + raw JSONL signal dict
    into the legacy ResearchContext expected by downstream pipeline stages.
    Injects run_id from RunContext so ResearchContext carries run identity.

    The assignment_id must match the raw signal's SIGNAL_ID.  Mismatched identifiers
    are rejected to prevent stale or unrelated signal data from being injected.

    TODO Task #29: remove this boundary once downstream stages accept
    ContentAssignment directly.
    """
    raw_signal_id = raw_signal.get("SIGNAL_ID", "")
    if assignment.assignment_id != raw_signal_id:
        raise ValueError(
            f"assignment.assignment_id {assignment.assignment_id!r} does not match "
            f"raw_signal SIGNAL_ID {raw_signal_id!r}. "
            "Mismatched identifiers are not allowed at the compatibility boundary."
        )
    rc = ResearchContext.from_dict(raw_signal)
    rc.run_id = run_ctx.run_id
    return rc


def main(
    *,
    research_provider: ResearchProvider | None = None,
    evidence_judgment: "EvidenceJudgmentTransport | None" = None,
    decision_evaluator: DecisionLensEvaluator | None = None,
    editorial_reviewer: EditorialReviewTransport | None = None,
    article_revisor: ArticleRevisionTransport | None = None,
) -> int:
    """Run one signal end to end and account for it exactly once.

    Issue #112: the business run lives in ``_run``; this wrapper is the single
    terminalization seam that persists the authoritative ``run_report.json``
    after the run has fully finished — so the report is never written before
    the terminal evidence is stable, never written twice, and never able to
    rewrite the business outcome it describes.
    """

    state = _TerminalState()
    exit_code = _run(
        state,
        research_provider=research_provider,
        evidence_judgment=evidence_judgment,
        decision_evaluator=decision_evaluator,
        editorial_reviewer=editorial_reviewer,
        article_revisor=article_revisor,
    )
    _emit_terminal_report(state, exit_code)
    return exit_code


def _run(
    state: "_TerminalState",
    *,
    research_provider: ResearchProvider | None = None,
    evidence_judgment: "EvidenceJudgmentTransport | None" = None,
    decision_evaluator: DecisionLensEvaluator | None = None,
    editorial_reviewer: EditorialReviewTransport | None = None,
    article_revisor: ArticleRevisionTransport | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Generate + publish one signal end-to-end")
    parser.add_argument("--signal-id", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate and validate content, save generated.json, but do not publish")
    parser.add_argument("--from-package", action="store_true",
                        help="Skip LLM generation — publish run-scoped generated.json (requires --source-run-id)")
    parser.add_argument("--source-run-id",
                        help="run_id of the source generated.json to load (required with --from-package)")
    parser.add_argument("--legacy-package", action="store_true",
                        help="Read legacy flat artifact {signal_id}_generated.json (explicit adapter; never auto-fallback)")
    parser.add_argument("--editorial-role", default="",
                        help="Editorial role id declared by the business configuration "
                             "(Issue #142); recorded on the run and applied to composition")
    parser.add_argument("--delete-wix-post-id",
                        help="Delete this Wix post ID before publishing (use when replacing an existing post)")
    args = parser.parse_args()
    signal_id = args.signal_id

    # Validate mutually exclusive modes and required co-arguments.
    if args.from_package and args.legacy_package:
        print("  ERROR: --from-package and --legacy-package are mutually exclusive")
        return 1
    if args.from_package and not args.source_run_id:
        print("  ERROR: --from-package requires --source-run-id <run_id>")
        return 1
    if args.source_run_id and not args.from_package:
        print("  ERROR: --source-run-id is only valid with --from-package")
        return 1

    mode = ("dry-run (no publish)" if args.dry_run
            else "from-package" if args.from_package
            else "legacy-package" if args.legacy_package
            else "live (LLM generate)")
    print(f"\n{SEP}")
    print("  Never Blank — Generate + Publish")
    print(f"  Signal: {signal_id}")
    print(f"  Mode:   {mode}")
    print(SEP)

    # ── 1. Load strict business configuration before any judgment ────────────
    print("\n[1/6] Loading business configuration and active campaign…")
    try:
        business_configuration = load_business_strategy_configuration()
        strategy_execution = StrategyExecutionContext.from_configuration(
            business_configuration
        )
        strategy_execution.assert_consistent()
    except (BusinessStrategyConfigurationError, StrategyExecutionError) as exc:
        print(f"  ERROR: {exc}")
        return 1

    # Issue #142: which editorial role this run produces. Requested explicitly
    # by the caller and resolved against the declared roles — never inferred
    # from the weekday, the cron, the source title, or the prompt. An unknown
    # role fails closed: a run with no rules to follow must not quietly
    # produce a default article under a role name it never honoured.
    _editorial_role_identity = None
    _editorial_role_rules = None
    if args.editorial_role:
        try:
            _editorial_role_identity, _role = resolve_editorial_role(
                business_configuration, args.editorial_role
            )
        except EditorialRoleError as exc:
            print(f"  ERROR: {exc}")
            return 1
        # Per-format rendering: the role's surface-scoped rules reach exactly
        # the surface they are for. ``long`` is the Wix article and ``medium``
        # the LinkedIn artifact — the same mapping this entrypoint already
        # relies on when it publishes them.
        _editorial_role_rules = {
            "long": render_editorial_role_rules(_role, surface="wix"),
            "medium": render_editorial_role_rules(_role, surface="linkedin"),
        }
        print(f"  ✓  editorial role: {_editorial_role_identity.role_id}")

    active_strategy = load_active_strategy()
    if active_strategy is None:
        print("  ERROR: No active strategy found at strategy/current/strategy.json")
        print("  Cannot generate content without an active strategy.")
        return 1

    cta_mode            = get_cta_mode(active_strategy)
    strategy_id         = active_strategy.strategy_id
    strategy_started_at = str(active_strategy.started_at) if active_strategy.started_at else ""
    strategy_version    = active_strategy.strategy_version

    try:
        assert_campaign_reference(
            business_configuration, campaign_version=strategy_version
        )
        strategy_execution.decision_lens_editorial.cta(cta_mode)
    except StrategyExecutionError as exc:
        print(f"  ERROR: {exc}")
        return 1

    print(
        "  ✓  business configuration: "
        f"{strategy_execution.identity.configuration_id}@"
        f"{strategy_execution.identity.configuration_version} "
        f"(schema {strategy_execution.identity.schema_version})"
    )
    print(f"  ✓  strategy_id:   {strategy_id}")
    print(f"  ✓  started_at:    {strategy_started_at}")
    print(f"  ✓  cta_mode:      {cta_mode}")

    # ── 2. Load signal ─────────────────────────────────────────────────────────
    print(f"\n[2/6] Loading signal {signal_id}…")
    try:
        signal = _load_signal(signal_id)
    except FileNotFoundError as exc:
        print(f"  ERROR: {exc}")
        return 1

    headline = signal.get("HEADLINE", signal_id)
    print(f"  ✓  Headline: {headline[:70]}")

    # ── Normalized intake + run identity ──────────────────────────────────────
    execution_mode = ExecutionMode.DRY_RUN if args.dry_run else ExecutionMode.CONTROLLED_LIVE
    try:
        assignment = DEFAULT_INTAKE_ADAPTER.adapt(
            signal,
            strategy_ref=active_strategy.strategy_id,
            strategy_version=active_strategy.strategy_version,
            submitted_at=datetime.now(timezone.utc),
        )
    except IntakeAdapterError as exc:
        print(f"  ERROR: {exc}")
        return 1
    run_ctx = RunContext.from_assignment(
        assignment,
        execution_mode,
        configuration_identity=strategy_execution.identity,
    )
    _require_run_id(run_ctx.run_id, "intake")
    print(f"  ✓  run_id:        {run_ctx.run_id}")
    print(f"  ✓  assignment_id: {run_ctx.assignment_id}")
    print(f"  ✓  execution_mode:{run_ctx.execution_mode.value}")

    require_configuration_identity(
        strategy_execution.identity,
        run_ctx.configuration_identity,
        "run-context",
    )
    run_dir = resolve_run_dir(PACKAGES_DIR, signal_id, run_ctx.run_id)
    # From here the run has a namespace and is reportable (Issue #112).
    state.begin(
        run_id=run_ctx.run_id,
        signal_id=signal_id,
        execution_mode=run_ctx.execution_mode.value,
        packages_dir=PACKAGES_DIR,
    )
    try:
        write_business_strategy_snapshot(
            run_dir, business_configuration.model_dump(mode="json")
        )
        # Canonical intake evidence (Issue #98 / Story #16): the immutable
        # record of what this run was asked to process — the anchor of the
        # run's provenance chain. Written for every run, both branches.
        # Which code is executing this run (Issue #114 / Story #21), read
        # from the local checkout before the run writes anything. Resolved
        # here rather than at report time because the report must describe the
        # code that ran, not whatever is checked out when the run ends.
        _assignment_record = AssignmentRecord(
            run_id=run_ctx.run_id,
            execution_mode=run_ctx.execution_mode.value,
            configuration_identity=strategy_execution.identity,
            assignment=assignment,
            code_identity=resolve_code_identity(),
            editorial_role=_editorial_role_identity,
        )
        write_assignment_json(
            run_dir, json.loads(_assignment_record.model_dump_json())
        )
    except ArtifactCollisionError as exc:
        print(f"  ERROR: {exc}")
        return 1

    try:
        # Issue #121: a coarse discovery label is source metadata, not a
        # request. When it names no configured audience the configured default
        # supplies identity and says so, so the case reaches Decision Lens —
        # which is what decides whether the evidence supports a bounded claim
        # for that audience. An explicit request is still strict and still
        # fails closed; a routing error is never rescued by a default.
        _requested_audience = audience_request(
            assignment, strategy_execution.decision_lens_editorial
        )
        audience_selection = strategy_execution.decision_lens_editorial.select_audience(
            _requested_audience
        )
        research_audience = strategy_execution.research.select_audience(
            _requested_audience
        )
        if audience_selection != research_audience:
            raise StrategyExecutionError("audience selection differs across strategy views")
    except StrategyExecutionError as exc:
        print(f"  ERROR: {exc}")
        return 1

    # ── Compatibility boundary: ContentAssignment → legacy ResearchContext ────
    # Injects run_id so ResearchContext carries run identity into the editorial
    # boundary.  TODO Task #29: remove once downstream stages accept
    # ContentAssignment directly.
    rc = _build_legacy_research_context(assignment, signal, run_ctx)
    rc.strategy_view = strategy_execution.research
    require_configuration_identity(
        strategy_execution.identity, rc.strategy_view.identity, "research-context"
    )
    _assert_run_id_match(run_ctx.run_id, rc.run_id, "research-context")

    # Readiness gate (Issue #101): Release 1 has no trustworthy authorization
    # identity, so a raw override boolean never bypasses a blocking condition.
    # The attempt is carried forward and recorded truthfully in the preserved
    # preflight verdict; it never becomes an authorization claim.
    # Readiness (Issue #101): the rule is unchanged, but its final publication
    # authorization decision belongs to the canonical preflight boundary, so a
    # readiness stop — and any override attempted against it — is preserved
    # evidence instead of an undocumented pre-preflight return.
    _override_attempted = bool(rc.force_override)
    if rc.article_ready:
        _readiness = ReadinessVerdict(verified=True)
    else:
        field_note = (
            "field absent (pre-dates readiness gate)"
            if not signal.get("ARTICLE_READY")
            else f"ARTICLE_READY={rc.article_ready!r}"
        )
        _readiness = ReadinessVerdict(
            verified=False,
            failure_reason=(
                f"{field_note}; SOURCE_PREMISE_VERIFIED="
                f"{rc.source_premise_verified}"
            ),
        )
        if _override_attempted:
            print(
                f"  NOTE: an override was attempted for {signal_id!r} "
                "(FORCE_PUBLISH_OVERRIDE / APPROVED_OVERRIDE). Release 1 has "
                "no trustworthy authorization identity, so an override never "
                "converts a blocking condition into permission to publish."
            )
        print(
            f"  ERROR: Signal {signal_id!r} blocked by readiness — {field_note} "
            f"(SOURCE_PREMISE_VERIFIED={rc.source_premise_verified}). "
            "This signal did not pass enrichment verification and cannot be published."
        )
        # No canonical package can exist for an unready signal: every channel
        # is recorded as an explicit fail-closed "package not constructed"
        # state, and the verdict is persisted before the run stops.
        state.ended(TerminalStage.READINESS, TerminalDisposition.BLOCKED, field_note)
        return _stop_with_preflight(
            run_dir=run_dir,
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            configuration_identity=strategy_execution.identity,
            readiness=_readiness,
            override_attempted=_override_attempted,
        )

    # Run-scoped artifact directory for this execution.
    echo_line = ""
    _generation_run_id: str = run_ctx.run_id   # fresh-gen default; overridden below
    _source_run_id: str     = run_ctx.run_id   # fresh-gen default; overridden below
    research_artifact = None

    if not args.from_package and not args.legacy_package:
        try:
            research_request = build_research_request(
                run_ctx, assignment, signal, strategy_execution.research,
                now=datetime.now(timezone.utc),
            )
            if research_provider is not None:
                provider = research_provider
            else:
                try:
                    provider = ExaResearchAdapter()
                except EnvironmentError:
                    provider = MissingCredentialResearchProvider()
            research_artifact = execute_and_persist_research(
                provider, research_request, run_dir,
                identity=strategy_execution.identity,
                run_started_at=run_ctx.started_at,
                judgment_transport=evidence_judgment,
            )
        except EvidenceAssessmentError as exc:
            # Assessment failed — which is not retrieval failing, and must not
            # be reported as though the provider broke. Nothing is promoted.
            print(f"  ERROR: evidence assessment blocked generation: {exc}")
            state.ended(TerminalStage.RESEARCH, TerminalDisposition.FAILED,
                        f"evidence assessment: {type(exc).__name__}")
            return 1
        except (ResearchGateError, ArtifactCollisionError, OSError, ValueError, EnvironmentError) as exc:
            print(f"  ERROR: research gate blocked generation: {exc}")
            state.ended(TerminalStage.RESEARCH, TerminalDisposition.FAILED,
                        f"research gate: {type(exc).__name__}")
            return 1
        print(f"  ✓  research: READY ({run_dir / 'research.json'})")
        state.reached(TerminalStage.RESEARCH)

        # ── Decision Lens gate (Issue #60) ────────────────────────────────────
        # The Decision Lens verdict is the mandatory business gate between
        # research and all narrative/editorial/downstream work. The persisted
        # and strict-reloaded decision.json — not the in-memory result — is
        # the artifact that authorizes continuation, and only PROCEED passes.
        try:
            evaluator = (
                decision_evaluator
                if decision_evaluator is not None
                else production_evaluator()
            )
            decision_artifact = evaluate_and_persist_decision(
                evaluator,
                research=research_artifact,
                strategy_view=strategy_execution.decision_lens_editorial,
                audience=audience_selection,
                configuration_identity=strategy_execution.identity,
                lens_profile=RELEASE1_LENS_PROFILE,
                run_id=run_ctx.run_id,
                assignment_id=assignment.assignment_id,
                # The authoritative signal identity is the one carried by the
                # validated current-run research artifact — never derived from
                # the assignment identity. run/assignment/signal remain three
                # independently correct identities in decision.json.
                signal_id=research_artifact.signal_id,
                run_dir=run_dir,
            )
            require_proceed(decision_artifact)
        except (DecisionGateError, ArtifactCollisionError, OSError, ValueError) as exc:
            print(f"  ERROR: decision gate blocked generation: {exc}")
            state.ended(TerminalStage.DECISION, TerminalDisposition.STOPPED,
                        f"decision gate: {type(exc).__name__}")
            return 1
        state.reached(TerminalStage.DECISION)
        print(
            f"  ✓  decision: PROCEED ({run_dir / 'decision.json'}) "
            f"[{decision_artifact.decision_lens_version}]"
        )
    elif args.legacy_package:
        print("  ERROR: legacy prepared packages have no canonical research lineage")
        return 1

    if args.from_package or args.legacy_package:
        # ── 3a. Load, verify, and validate existing package ──────────────────
        # All checks complete before any image-generation side effect.
        if args.from_package:
            print(f"\n[3/6] Loading run-scoped package (--from-package)…")
            _source_run_id = args.source_run_id
            try:
                pkg = load_run_generated(PACKAGES_DIR, signal_id, _source_run_id)
            except FileNotFoundError as exc:
                print(f"  ERROR: {exc}")
                return 1
            except ValueError as exc:
                print(f"  ERROR: Package could not be parsed: {exc}")
                return 1

            # Source-identity verification — loaded artifact must match requested address.
            _pkg_run_id = pkg.get("run_id", "")
            if _pkg_run_id != _source_run_id:
                print(
                    f"  ERROR: source identity mismatch: "
                    f"artifact run_id={_pkg_run_id!r} requested source_run_id={_source_run_id!r}"
                )
                return 1
        else:
            # --legacy-package: explicit adapter for flat legacy artifact.
            print(f"\n[3/6] Loading legacy package (--legacy-package)…")
            _legacy_path = PACKAGES_DIR / f"{signal_id}_generated.json"
            if not _legacy_path.exists():
                print(f"  ERROR: Legacy artifact {_legacy_path} not found — "
                      "run without --legacy-package to generate a run-scoped artifact")
                return 1
            try:
                pkg = json.loads(_legacy_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                print(f"  ERROR: Legacy artifact could not be read or parsed: {exc}")
                return 1
            _source_run_id = pkg.get("run_id") or "legacy-unknown"
            print(f"  ⚠  Legacy source (not a run-scoped artifact). source_run_id={_source_run_id!r}")

        # Shape check — must be a JSON object, not an array, scalar, or null.
        if not isinstance(pkg, dict):
            print(f"  ERROR: Package is not a JSON object (got {type(pkg).__name__})")
            return 1

        # Field-type checks — strategy_id, strategy_version, and generated_at
        # must be non-blank strings before any further processing.
        for _field in ("strategy_id", "strategy_version", "generated_at"):
            _val = pkg.get(_field)
            if not isinstance(_val, str) or not _val.strip():
                print(
                    f"  ERROR: Package field {_field!r} must be a non-blank string "
                    f"(got {type(_val).__name__ if _val is not None else 'missing'})"
                )
                return 1

        # signal_id identity check — must match CLI arg and ContentAssignment.
        _pkg_signal_id = pkg.get("signal_id")
        if not isinstance(_pkg_signal_id, str) or not _pkg_signal_id.strip():
            print(
                f"  ERROR: Package field 'signal_id' must be a non-blank string "
                f"(got {type(_pkg_signal_id).__name__ if _pkg_signal_id is not None else 'missing'})"
            )
            return 1
        if _pkg_signal_id != signal_id:
            print(
                f"  ERROR: signal_id mismatch: package={_pkg_signal_id!r} "
                f"requested={signal_id!r}"
            )
            return 1
        if _pkg_signal_id != assignment.assignment_id:
            print(
                f"  ERROR: signal_id mismatch: package={_pkg_signal_id!r} "
                f"assignment_id={assignment.assignment_id!r}"
            )
            return 1

        # Provenance / staleness check (fail-closed)
        pkg_strategy_id = pkg["strategy_id"]
        if pkg_strategy_id != strategy_id:
            print(f"  ERROR: strategy_id mismatch: package={pkg_strategy_id!r} active={strategy_id!r}")
            return 1
        pkg_strategy_version = pkg["strategy_version"]
        if pkg_strategy_version != strategy_version:
            print(
                f"  ERROR: strategy_version mismatch: "
                f"package={pkg_strategy_version!r} active={strategy_version!r}"
            )
            return 1
        try:
            package_configuration_identity = identity_from_mapping(
                pkg.get("configuration_identity"), boundary="generated-package"
            )
            require_configuration_identity(
                strategy_execution.identity,
                package_configuration_identity,
                "generated-package",
            )
            if args.from_package:
                snapshot_data = load_business_strategy_snapshot(
                    PACKAGES_DIR, signal_id, _source_run_id
                )
                try:
                    snapshot_configuration = BusinessStrategyConfiguration.model_validate(
                        snapshot_data
                    )
                except Exception as exc:
                    raise StrategyExecutionError(
                        "business strategy snapshot is invalid at source-run"
                    ) from exc
                snapshot_identity = strategy_execution.identity.from_configuration(
                    snapshot_configuration
                )
                require_configuration_identity(
                    package_configuration_identity,
                    snapshot_identity,
                    "source-run-snapshot",
                )
                require_configuration_identity(
                    strategy_execution.identity,
                    snapshot_identity,
                    "current-configuration/source-run-snapshot",
                )
                source_envelope = load_research_envelope(
                    PACKAGES_DIR, signal_id, _source_run_id
                )
                research_artifact = validate_research_envelope(
                    source_envelope,
                    run_id=_source_run_id,
                    assignment_id=assignment.assignment_id,
                    signal_id=signal_id,
                    identity=strategy_execution.identity,
                    run_started_at=source_envelope.request.freshness.retrieved_not_before,
                    now=datetime.now(timezone.utc),
                )
                # ── Decision Lens reuse gate (Issue #60) ──────────────────────
                # Reuse loads the original generation run's immutable
                # decision.json; the Decision Lens is never re-run and the
                # artifact is never rewritten. Only an original validated
                # PROCEED decision allows reuse to continue.
                source_decision = load_decision_artifact(
                    PACKAGES_DIR,
                    signal_id,
                    _source_run_id,
                    research=research_artifact,
                    audience=audience_selection,
                    configuration_identity=strategy_execution.identity,
                    lens_profile=RELEASE1_LENS_PROFILE,
                )
                require_proceed(source_decision)
                print(
                    f"  ✓  decision: PROCEED (reused from source run "
                    f"{_source_run_id}) [{source_decision.decision_lens_version}]"
                )
        except (FileNotFoundError, ValueError, ResearchGateError, DecisionGateError) as exc:
            print(f"  ERROR: {exc}")
            return 1
        except StrategyExecutionError as exc:
            print(f"  ERROR: {exc}")
            return 1
        raw_gen_at = pkg["generated_at"]
        try:
            from datetime import date
            gen_dt = datetime.fromisoformat(raw_gen_at).date()
        except ValueError:
            print(f"  ERROR: generated_at {raw_gen_at!r} could not be parsed as ISO 8601")
            return 1
        strategy_start = active_strategy.started_at if active_strategy and active_strategy.started_at else None
        if strategy_start and isinstance(strategy_start, str):
            from datetime import date
            strategy_start = date.fromisoformat(strategy_start)
        if strategy_start and gen_dt < strategy_start:
            print(f"  ERROR: Package generated BEFORE active strategy started ({gen_dt} < {strategy_start})")
            return 1

        # generation_run_id: for run-scoped packages the source_run_id IS the
        # generation identity (generated.json belongs to the generation run).
        # For legacy packages, use source_run_id as best-effort provenance.
        _generation_run_id = _source_run_id

        # Preserve original generation timestamp.
        _generated_at = raw_gen_at

        headline       = pkg.get("headline", headline)
        blog_body      = pkg.get("blog_article", "")
        linkedin_text  = pkg.get("linkedin_post", "")
        facebook_text  = pkg.get("facebook_post", "")
        instagram_text = pkg.get("instagram_caption", "")
        threads_seq    = pkg.get("threads_sequence", [])
        telegram_text  = pkg.get("telegram_text", "")
        echo_line      = pkg.get("echo_line", "")

        # Content field type validation — before any slicing, len(), or replace() calls.
        _content_errors: list[str] = []
        for _fname, _fval in [
            ("headline",     headline),
            ("blog_article", blog_body),
            ("linkedin_post", linkedin_text),
        ]:
            if not isinstance(_fval, str) or not _fval.strip():
                _content_errors.append(
                    f"{_fname!r} must be a non-blank string "
                    f"(got {type(_fval).__name__ if not isinstance(_fval, str) else 'blank'})"
                )
        for _fname, _fval in [
            ("facebook_post",    facebook_text),
            ("instagram_caption", instagram_text),
            ("telegram_text",    telegram_text),
            ("echo_line",        echo_line),
        ]:
            if not isinstance(_fval, str):
                _content_errors.append(
                    f"{_fname!r} must be a string (got {type(_fval).__name__})"
                )
        if not isinstance(threads_seq, list) or not all(isinstance(t, str) for t in threads_seq):
            _content_errors.append("'threads_sequence' must be a list of strings")
        if _content_errors:
            for _err in _content_errors:
                print(f"  ERROR: {_err}")
            return 1

        print(f"  ✓  headline:            {headline[:70]}")
        print(f"  ✓  blog:                {len(blog_body)} chars")
        print(f"  ✓  linkedin:            {len(linkedin_text)} chars")
        print(f"  ✓  strategy_id:         {pkg_strategy_id}")
        print(f"  ✓  strategy_version:    {pkg_strategy_version}")
        print(f"  ✓  generated_at:        {raw_gen_at[:10]}")
        print(f"  ✓  generation_run_id:   {_generation_run_id}")
        print(f"  ✓  publication_run_id:  {run_ctx.run_id}")
        print(f"\n  LinkedIn preview (first 400 chars):")
        print(f"  {linkedin_text[:400].replace(chr(10), chr(10)+'  ')}")

        # ── Validate content (before any image side effect) ───────────────────
        _require_run_id(run_ctx.run_id, "validation")
        print(f"\n[4/6] Validating loaded package content…")
        validation_results: list[ValidationResult] = []
        for _platform, _text in [("blog", blog_body), ("linkedin", linkedin_text)]:
            try:
                validate_article_for_publish(_text, platform=_platform, run_id=run_ctx.run_id)
                _vr = ValidationResult(platform=_platform, run_id=run_ctx.run_id, passed=True)
                print(f"  ✓  {_platform} validation passed")
            except Exception as exc:
                _vr = ValidationResult(
                    platform=_platform, run_id=run_ctx.run_id,
                    passed=False, error_message=str(exc),
                )
                print(f"  ✗  {_platform} validation FAILED: {exc}")
            _assert_run_id_match(run_ctx.run_id, _vr.run_id, f"validation-result:{_platform}")
            validation_results.append(_vr)

        if any(not vr.passed for vr in validation_results):
            print(f"\n  ERROR: validation error(s) in loaded package — not publishing")
            return 1

        # ── Visual boundary — typed adapter ───────────────────────────────────
        # Full implementation deferred to Visual System story.
        # Adapter constructed here so visual boundary carries run_id.
        _require_run_id(run_ctx.run_id, "image-preparation")
        _vis_req = VisualArtifactRequest(
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            design_version=CURRENT_DESIGN_VERSION,
            strategy_view=strategy_execution.visual,
        )
        _vis_req.assert_identity(run_ctx.run_id)
        _vis_req.assert_configuration_identity(strategy_execution.identity)
        log.info(
            "visual-boundary: run_id=%s blocked=%s reason=%r",
            _vis_req.run_id, _vis_req.blocked, _vis_req.blocked_reason,
        )

        # ── Visual reuse gate — truthful provenance (Issue #96 / Story #15) ──
        # --from-package is a NEW publication run reusing artifacts produced
        # by the original generation run. The ONLY accepted provenance source
        # is that run's immutable visual passport: origin is never inferred
        # from signal_id or legacy signal-scoped image mappings, the current
        # publication run is never stamped as the visual origin, and the
        # publication uses exactly the derivatives that passport proves.
        # Sources without a trustworthy passport fail closed.
        try:
            _source_visual = load_visual_assets_json(
                PACKAGES_DIR, signal_id, _source_run_id
            )
            _visual_record = reuse_visual_assets_record(
                _source_visual,
                source_run_id=_source_run_id,
                publication_run_id=run_ctx.run_id,
                article_body=blog_body,
            )
            write_visual_assets_json(
                run_dir, json.loads(_visual_record.model_dump_json())
            )
        except (VisualGateError, FileNotFoundError, ValueError,
                ArtifactCollisionError, OSError) as exc:
            print(f"  ERROR: visual gate blocked publication: {exc}")
            state.ended(TerminalStage.VISUAL, TerminalDisposition.BLOCKED,
                        f"visual gate: {type(exc).__name__}")
            return 1
        print(
            f"  ✓  visuals: {_visual_record.status} reused "
            f"(origin run {_visual_record.origin_run_id}; "
            f"linkedin {_visual_record.linkedin_visual.value}) "
            f"({run_dir / 'visual_assets.json'})"
        )

        blog_image_url: Optional[str] = _visual_record.wix_url
        platform_image_urls = {
            p: url
            for p, url in (
                ("blog", _visual_record.wix_url),
                ("linkedin", _visual_record.linkedin_url),
            )
            if url
        }
        print(f"  ✓  Blog image: {blog_image_url[:60] if blog_image_url else '— (none)'}")
        print(f"  ✓  Platform images: {list(platform_image_urls.keys())}")

    else:
        # ── Visual boundary — typed adapter (fresh-gen path) ──────────────────
        _vis_req = VisualArtifactRequest(
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            design_version=CURRENT_DESIGN_VERSION,
            strategy_view=strategy_execution.visual,
        )
        _vis_req.assert_identity(run_ctx.run_id)
        _vis_req.assert_configuration_identity(strategy_execution.identity)
        log.info(
            "visual-boundary: run_id=%s blocked=%s reason=%r",
            _vis_req.run_id, _vis_req.blocked, _vis_req.blocked_reason,
        )

        # ── Image preparation (fresh-gen path) ───────────────────────────────
        pimgs = _load_package_images(signal_id)
        editorial_package: dict = {"images": {"platform_images": pimgs}}
        pkg_design_version = pimgs.get("_design_version") if pimgs else None
        needs_regen = (
            not pimgs.get("blog", {}).get("url")
            or pkg_design_version != CURRENT_DESIGN_VERSION
        )
        if needs_regen:
            reason = "no pre-generated image" if not pimgs else f"stale design v{pkg_design_version} (current: v{CURRENT_DESIGN_VERSION})"
            print(f"  — {reason} — generating images for all platforms…")
            try:
                from scripts.research.prepare_content import prepare_content_packages
                pkgs = prepare_content_packages(
                    [signal], strategy_execution.research, research_audience
                )
                if pkgs:
                    editorial_package = pkgs[0]
                    pimgs = pkgs[0].get("images", {}).get("platform_images", {})
                    blog_url = pimgs.get("blog", {}).get("url") or ""
                    print(f"  ✓  Images generated: {blog_url[:60] if blog_url else '(none)'}")
                else:
                    print(f"  ⚠  Image generation returned no packages — visual platforms will skip")
            except Exception as exc:
                print(f"  ⚠  Image generation failed ({exc}) — visual platforms will skip")

        blog_image_url: Optional[str] = pimgs.get("blog", {}).get("url") or None
        platform_image_urls = {
            p: (pimgs.get(p, {}).get("url") or None)
            for p in ("blog", "linkedin", "facebook", "instagram", "threads", "stories")
            if pimgs.get(p, {}).get("url")
        }
        print(f"  ✓  Blog image: {blog_image_url[:60] if blog_image_url else '— (none)'}")
        print(f"  ✓  Platform images: {list(platform_image_urls.keys())}")

        # ── 3b. Generate content via LLM ─────────────────────────────────────
        print(f"\n[3/6] Generating content (LLM — Editorial Engine V2)…")
        print(f"  strategy context injected: strategy_id={strategy_id}")
        try:
            editorial = rc.to_editorial(editorial_package)
            _assert_run_id_match(run_ctx.run_id, editorial.run_id, "editorial-context")
            article    = generate_article(
                editorial.to_legacy_dict(),
                cta_mode=cta_mode,
                strategy_context=strategy_execution.decision_lens_editorial,
                wix_strategy=strategy_execution.wix,
                linkedin_strategy=strategy_execution.linkedin,
                audience_selection=audience_selection,
                research_artifact=research_artifact,
                editorial_role_rules=_editorial_role_rules,
            )
            platforms  = article["platforms"]
            structured = article["structured_article"]
        except ArticleGenerationError as exc:
            print(f"  ERROR: Editorial Engine failed at stage {exc.stage!r}: {exc.original}")
            return 1

        blog_body      = platforms["long"]["body"]
        linkedin_text  = platforms["medium"]["body"]
        # The published title is the article's own hook when the composition
        # produced one. Before this, Wix received the source signal's headline —
        # the RSS feed's words on our page. An absent title keeps the previous
        # behaviour rather than inventing one.
        _composed_title = platforms["long"].get("title")
        if _composed_title:
            headline = _composed_title
            print(f"  ✓  article title: {headline[:70]}")
        facebook_text  = platforms["reading"]["body"]
        instagram_text = platforms["instagram"]["body"]
        threads_seq    = _build_threads(structured)
        telegram_text  = _build_telegram(structured)
        echo_line      = structured.get("echo_line", "")

        # ── Editorial acceptance gate (Issue #89 / Story #13) ────────────────
        # A technically valid article is not automatically publishable. One
        # explicit editorial decision on the canonical Wix article: ACCEPT
        # continues, REVISE triggers exactly one controlled revision followed
        # by one recheck, everything else stops before packaging/publication.
        # Revision touches the Wix article body only — no other channel is
        # regenerated.
        try:
            _acceptance_rubric = EditorialAcceptanceRubric.load()
            _acceptance = run_editorial_acceptance(
                article_body=blog_body,
                research=research_artifact,
                run_id=run_ctx.run_id,
                rubric=_acceptance_rubric,
                reviewer=(
                    editorial_reviewer
                    if editorial_reviewer is not None
                    else LlmChatEditorialReviewTransport()
                ),
                revisor=(
                    article_revisor
                    if article_revisor is not None
                    else LlmChatArticleRevisionTransport()
                ),
            )
        except (EditorialAcceptanceError, ValueError, OSError) as exc:
            print(f"  ERROR: editorial acceptance blocked publication: {exc}")
            state.ended(TerminalStage.EDITORIAL, TerminalDisposition.BLOCKED,
                        f"editorial acceptance: {type(exc).__name__}")
            return 1
        # The editorial verdict is persisted for every run that reaches
        # acceptance — accepted or blocked — so the decision history stays
        # auditable. Persisting the audit is NOT permission to continue: the
        # accepted check below still stops every non-ACCEPT outcome before
        # any packaging or publication effect.
        try:
            write_editorial_acceptance_json(
                run_dir,
                {
                    "run_id": run_ctx.run_id,
                    "signal_id": signal_id,
                    **_acceptance.audit,
                },
            )
        except (ArtifactCollisionError, OSError) as exc:
            print(f"  ERROR: editorial acceptance audit could not be persisted: {exc}")
            return 1
        print(f"  ✓  editorial audit: {run_dir / 'editorial_acceptance.json'}")
        if not _acceptance.accepted:
            _final = _acceptance.final_review or _acceptance.initial_review
            # Issue #134: preserve what this run produced so a human can read
            # the article the reviewer refused. Review-only, never a
            # publication input, and never a reason to continue: the block
            # below is unchanged and still ends the run.
            try:
                write_editorial_review_content_json(
                    run_dir,
                    {
                        "run_id": run_ctx.run_id,
                        "signal_id": signal_id,
                        "assignment_id": assignment.assignment_id,
                        "editorial": {
                            "rubric": _acceptance_rubric.identity,
                            "final_disposition": _final.disposition.value,
                            "failed_criterion_ids": list(_final.failed_criterion_ids),
                            "revised": _acceptance.revised,
                        },
                        "content": {
                            "article_as_generated": blog_body,
                            "article_after_revision": (
                                _acceptance.final_article_body
                                if _acceptance.revised
                                else None
                            ),
                            "linkedin_body": linkedin_text,
                        },
                        "visuals": dict(platform_image_urls),
                    },
                )
                print(
                    "  ✓  produced content preserved for review: "
                    f"{run_dir / 'editorial_review_content.json'} (not publishable)"
                )
            except (ArtifactCollisionError, OSError) as exc:
                # Losing the review copy must not change the verdict or hide
                # the real reason the run stopped.
                print(f"  ⚠  produced content could not be preserved: {exc}")
            state.ended(TerminalStage.EDITORIAL, TerminalDisposition.BLOCKED,
                        f"editorial disposition={_final.disposition.value}")
            print(
                "  ERROR: editorial acceptance blocked publication: "
                f"disposition={_final.disposition.value!r} "
                f"failed_criteria={list(_final.failed_criterion_ids)} "
                f"[{_acceptance_rubric.identity}] — the article does not "
                "continue toward packaging or publication"
            )
            return 1
        state.reached(TerminalStage.EDITORIAL)
        blog_body = _acceptance.final_article_body
        print(
            f"  ✓  editorial acceptance: ACCEPT "
            f"({'after one revision' if _acceptance.revised else 'original article'}) "
            f"[{_acceptance_rubric.identity}]"
        )

        # Issue #142 review round 2: a role may require source transparency
        # as a fail-closed publication condition. The prompt asked for
        # attribution; here the accepted article and the LinkedIn body are
        # verified against the run's ACTUAL sources — a model that ignored the
        # instruction, or invented a link, stops the run before any publisher
        # is called. Roles without the requirement (every other stream, and
        # every run with no role) are never checked.
        if _editorial_role_identity is not None and _role.require_source_transparency:
            try:
                validate_source_transparency(
                    article_body=blog_body,
                    linkedin_body=linkedin_text,
                    research=research_artifact,
                    allowed_url_prefixes=tuple(
                        prefix for prefix in (
                            os.environ.get("NB_WIX_SITE_BASE_URL", ""),
                        ) if prefix
                    ),
                )
            except SourceTransparencyError as exc:
                print(f"  ERROR: source transparency blocked publication: {exc}")
                state.ended(TerminalStage.EDITORIAL, TerminalDisposition.BLOCKED,
                            f"source transparency: {type(exc).__name__}")
                return 1
            print("  ✓  source transparency: attribution verified against run sources")

        print(f"  ✓  blog:      {len(blog_body)} chars")
        print(f"  ✓  linkedin:  {len(linkedin_text)} chars")
        print(f"  ✓  threads:   {len(threads_seq)} posts")
        print(f"\n  LinkedIn preview (first 400 chars):")
        print(f"  {linkedin_text[:400].replace(chr(10), chr(10)+'  ')}")

        # ── 4. Validate ───────────────────────────────────────────────────────
        _require_run_id(run_ctx.run_id, "validation")
        print(f"\n[4/6] Validating generated content…")
        validation_results: list[ValidationResult] = []
        for _platform, _text in [("blog", blog_body), ("linkedin", linkedin_text)]:
            try:
                validate_article_for_publish(_text, platform=_platform, run_id=run_ctx.run_id)
                _vr = ValidationResult(platform=_platform, run_id=run_ctx.run_id, passed=True)
                print(f"  ✓  {_platform} validation passed")
            except Exception as exc:
                _vr = ValidationResult(
                    platform=_platform, run_id=run_ctx.run_id,
                    passed=False, error_message=str(exc),
                )
                print(f"  ✗  {_platform} validation FAILED: {exc}")
            _assert_run_id_match(run_ctx.run_id, _vr.run_id, f"validation-result:{_platform}")
            validation_results.append(_vr)

        if any(not vr.passed for vr in validation_results):
            print(f"\n  ERROR: validation error(s) — not publishing")
            return 1

        # ── 5. Apply formatting + save ─────────────────────────────────────────
        source_name = signal.get("SOURCE_NAME", "")
        source_url  = signal.get("SOURCE_URL", "")
        blog_body      += formatting.source_line(source_name, source_url, "blog_markdown")
        linkedin_text   = formatting.append_hashtags(
            formatting.bold_signature_prefix(linkedin_text, "unicode") +
            formatting.source_line(source_name, source_url, "bare_url"),
            generate_hashtags(signal, "linkedin"),
        )
        facebook_text   = (
            formatting.bold_signature_prefix(facebook_text, "unicode") +
            formatting.source_line(source_name, source_url, "bare_url")
        )
        instagram_text  = formatting.append_hashtags(
            formatting.bold_signature_prefix(instagram_text, "unicode"),
            generate_hashtags(signal, "instagram"),
        )

        # ── LinkedIn composition acceptance (Issue #93 / Story #14) ──────────
        # The canonical Release 1 LinkedIn artifact (the composer `medium`
        # body, 120–220-word target) must be demonstrably channel-native and
        # traceable before it may continue toward packaging/publication. A
        # failed LinkedIn acceptance stops the run — never a fallback to
        # another platform body, never a revision loop.
        try:
            _li_record = accept_linkedin_composition(
                linkedin_body=linkedin_text,
                article_body=blog_body,
                # Truthful Story #13 seam: a revised article invalidates the
                # pre-revision LinkedIn composition (fail closed, new run).
                article_revised=_acceptance.revised,
                run_id=run_ctx.run_id,
                signal_id=signal_id,
                configuration_identity=strategy_execution.identity,
                strategy_id=strategy_id,
                strategy_version=strategy_version,
            )
            write_linkedin_composition_json(
                run_dir, _li_record.model_dump(mode="json")
            )
        except (LinkedInCompositionError, ArtifactCollisionError, OSError) as exc:
            print(f"  ERROR: LinkedIn composition blocked publication: {exc}")
            state.ended(TerminalStage.LINKEDIN_COMPOSITION,
                        TerminalDisposition.BLOCKED,
                        f"linkedin composition: {type(exc).__name__}")
            return 1
        state.reached(TerminalStage.LINKEDIN_COMPOSITION)
        print(
            f"  ✓  linkedin composition: ACCEPTED "
            f"({_li_record.word_count} words) "
            f"[{_li_record.composition_rules_version}] "
            f"({run_dir / 'linkedin_composition.json'})"
        )

        # ── Visual contract gate (Issue #96 / Story #15) ─────────────────────
        # Release 1 rule: the Wix visual is required (no valid Wix visual → no
        # Wix package/publication); a LinkedIn visual is optional, but an
        # attempted LinkedIn visual that failed or is invalid is never
        # silently converted into text-only success. The gate validates the
        # RESULTING derivatives (remote URL, dimensions, format, lineage,
        # design version) and persists the immutable visual passport.
        try:
            _visual_record = build_visual_assets_record(
                pimgs,
                run_id=run_ctx.run_id,
                signal_id=signal_id,
                article_body=blog_body,
                design_version=CURRENT_DESIGN_VERSION,
            )
            write_visual_assets_json(
                run_dir, json.loads(_visual_record.model_dump_json())
            )
        except (VisualGateError, ArtifactCollisionError, OSError) as exc:
            print(f"  ERROR: visual gate blocked publication: {exc}")
            state.ended(TerminalStage.VISUAL, TerminalDisposition.BLOCKED,
                        f"visual gate: {type(exc).__name__}")
            return 1
        print(
            f"  ✓  visuals: {_visual_record.status} "
            f"(wix required ok; linkedin {_visual_record.linkedin_visual.value}) "
            f"[{_visual_record.design_version}] "
            f"({run_dir / 'visual_assets.json'})"
        )

        _generated_at = datetime.now(timezone.utc).isoformat()
        _generated_data = {
            "run_id":              run_ctx.run_id,
            "signal_id":           signal_id,
            "headline":            headline,
            "generated_at":        _generated_at,
            "strategy_id":         strategy_id,
            "strategy_version":    strategy_version,
            "strategy_started_at": strategy_started_at,
            "configuration_identity": strategy_execution.identity.model_dump(),
            "blog_article":        blog_body,
            "linkedin_post":       linkedin_text,
            "facebook_post":       facebook_text,
            "instagram_caption":   instagram_text,
            "threads_sequence":    threads_seq,
            "telegram_text":       telegram_text,
        }
        try:
            write_generated_json(run_dir, _generated_data)
        except ArtifactCollisionError as exc:
            print(f"  ERROR: {exc}")
            return 1
        print(f"\n  ✓  Saved {run_dir / 'generated.json'}")
        print(f"       run_id={run_ctx.run_id}  strategy_id={strategy_id}  strategy_version={strategy_version}  generated_at={_generated_at[:19]}")

    if args.dry_run:
        state.ended(TerminalStage.DRY_RUN, TerminalDisposition.COMPLETED)
        report = R1RunReport(
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            execution_mode=run_ctx.execution_mode.value,
            completed=True,
            notes="dry-run — content generated and validated; not published",
        )
        _emit_run_report(report)
        print(f"\n{SEP}")
        if args.from_package:
            print("  DRY RUN — existing package loaded and validated; not published.")
        else:
            print("  DRY RUN — generated content validated; not published.")
        print(f"  run_id: {run_ctx.run_id}  [COMPLETE]")
        print(SEP)
        return 0

    # ── 6. Publish: Wix + LinkedIn ────────────────────────────────────────────
    print(f"\n[5/6] Publishing…")

    # Delete old Wix post if requested (e.g. when republishing with corrections)
    if args.delete_wix_post_id:
        print(f"  Deleting old Wix post {args.delete_wix_post_id}…")
        try:
            import requests
            wix_api_key  = os.getenv("NB_WIX_API_KEY", "")
            wix_site_id  = os.getenv("NB_WIX_SITE_ID", "")
            del_resp = requests.delete(
                f"https://www.wixapis.com/blog/v3/posts/{args.delete_wix_post_id}",
                headers={
                    "Authorization": wix_api_key,
                    "wix-site-id": wix_site_id,
                },
                timeout=15,
            )
            if del_resp.status_code in (200, 204):
                print(f"  ✓  Deleted Wix post {args.delete_wix_post_id}")
            else:
                print(f"  WARNING: Wix delete returned {del_resp.status_code} — continuing anyway")
        except Exception as exc:
            print(f"  WARNING: Wix delete failed ({exc}) — continuing anyway")

    _require_run_id(run_ctx.run_id, "publication")

    # ── Canonical publication packages (Issue #100 / Story #17) ──────────────
    # The strict frozen per-channel packages are the single source for
    # everything handed to the R1 publishers. They are composed only from the
    # run's accepted canonical artifacts plus explicit non-secret target
    # identity; credentials never enter a package (credential readiness is
    # Issue #101 preflight scope). Construction fails closed on any cross-run,
    # cross-signal, or configuration mismatch.
    _generated_source: dict = pkg if (args.from_package or args.legacy_package) else _generated_data
    _li_composition: dict | None = None
    _li_composition_failure: str | None = None
    if args.from_package or args.legacy_package:
        try:
            _li_composition = load_linkedin_composition_json(
                PACKAGES_DIR, signal_id, _source_run_id
            )
        except (FileNotFoundError, ValueError) as exc:
            # Channel-local: the LinkedIn channel has no accepted composition
            # to publish. Wix is unaffected and still reaches preflight.
            _li_composition_failure = f"{type(exc).__name__}: {exc}"
    else:
        _li_composition = _li_record.model_dump(mode="json")

    # Each channel is constructed independently (Issue #101): a channel-local
    # package or target failure becomes a typed channel BLOCK recorded in the
    # preserved verdict, never a whole-run stop that hides the decision.
    def _build_channel(channel: str) -> ChannelPackageOutcome:
        try:
            if channel == "wix":
                target = WixPublicationTarget(
                    site_id=os.getenv("NB_WIX_SITE_ID", ""),
                    owner_member_id=os.getenv("NB_WIX_POST_OWNER_ID", ""),
                    category_ids=tuple(
                        x.strip()
                        for x in [os.getenv("NB_WIX_BLOG_CATEGORY_ID", "")]
                        if x.strip()
                    ),
                    tag_ids=tuple(
                        x.strip()
                        for x in os.getenv("NB_WIX_BLOG_TAG_IDS", "").split(",")
                        if x.strip()
                    ),
                )
            else:
                target = LinkedInPublicationTarget(
                    account_id=os.getenv("NB_ZERNIO_LINKEDIN_ACCOUNT_ID", ""),
                )
        except PydanticValidationError as exc:
            return ChannelPackageOutcome.failed(
                channel,
                f"{type(exc).__name__}: {exc}",
                category=PackageFailureCategory.TARGET,
            )
        try:
            if channel == "wix":
                package = build_wix_publication_package(
                    run_id=run_ctx.run_id,
                    signal_id=signal_id,
                    configuration_identity=strategy_execution.identity,
                    generated=_generated_source,
                    visual_record=_visual_record,
                    target=target,
                )
            else:
                if _li_composition is None:
                    return ChannelPackageOutcome.failed(
                        channel,
                        _li_composition_failure or "no LinkedIn composition",
                        category=PackageFailureCategory.CHANNEL_PACKAGE,
                    )
                package = build_linkedin_publication_package(
                    run_id=run_ctx.run_id,
                    signal_id=signal_id,
                    configuration_identity=strategy_execution.identity,
                    generated=_generated_source,
                    linkedin_composition=_li_composition,
                    visual_record=_visual_record,
                    target=target,
                )
        except PublicationPackageError as exc:
            # The builder classifies its own failure scope: a channel-local
            # payload problem isolates this channel, while configuration /
            # provenance / lineage corruption is shared run evidence and stops
            # every channel. Scope is never inferred from message text.
            return ChannelPackageOutcome.failed(
                channel, f"{type(exc).__name__}: {exc}", category=exc.category
            )
        except PydanticValidationError as exc:
            return ChannelPackageOutcome.failed(
                channel,
                f"{type(exc).__name__}: {exc}",
                category=PackageFailureCategory.CHANNEL_PACKAGE,
            )
        return ChannelPackageOutcome.valid(channel, package)

    _channel_outcomes = [_build_channel(name) for name in _R1_PUBLISHERS]
    for _outcome in _channel_outcomes:
        if _outcome.package is not None:
            print(f"  ✓  {_outcome.channel} package: {_outcome.package.package_digest()}")
        else:
            print(f"  ✗  {_outcome.channel} package: {_outcome.failure_reason}")

    # ── Publication preflight (Issue #101 / Story #17) ───────────────────────
    # The last gate before any external side effect: the exact frozen packages
    # built above are evaluated, the verdict is persisted BEFORE any allowed
    # call, and only ALLOWed channels reach a publisher. Run-level failures
    # block every channel; channel-scoped failures block only their channel.
    _freshness = FreshnessVerdict(
        verified=True,
        rules=(
            ("source_package_generated_at_not_before_strategy_start",
             "strategy_id_and_version_match_active",
             "configuration_identity_matches_source_snapshot")
            if (args.from_package or args.legacy_package)
            else ("configuration_identity_matches_active_strategy",)
        ),
    )
    try:
        preflight = evaluate_publication_preflight(
            packages_dir=PACKAGES_DIR,
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            configuration_identity=strategy_execution.identity,
            channel_outcomes=_channel_outcomes,
            override_attempted=_override_attempted,
            readiness=_readiness,
            freshness=_freshness,
        )
        write_preflight_result_json(
            run_dir, json.loads(preflight.model_dump_json())
        )
    except (ArtifactCollisionError, OSError, ValueError) as exc:
        print(f"\n  ERROR: publication preflight could not be committed: {exc}")
        return 1
    state.reached(TerminalStage.PREFLIGHT)
    print(f"\n  preflight: run={preflight.run_disposition.value} "
          f"({run_dir / 'preflight_result.json'})")
    for _verdict in preflight.channels:
        _detail = (
            ", ".join(reason.value for reason in _verdict.blocking_reasons)
            or _verdict.package_digest
        )
        print(f"    {_verdict.channel:<9} {_verdict.disposition.value:<5} {_detail}")
    if preflight.run_disposition is PreflightDisposition.BLOCK:
        print("  ERROR: publication preflight blocked this run — no channel published.")
        state.ended(
            TerminalStage.PREFLIGHT, TerminalDisposition.BLOCKED,
            *[reason.value for reason in preflight.run_blocking_reasons],
        )
        _emit_run_report(R1RunReport(
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            execution_mode=run_ctx.execution_mode.value,
            errors=[reason.value for reason in preflight.run_blocking_reasons],
            completed=False,
            notes="publication preflight blocked the run",
        ))
        return 1

    results: dict = {}
    wix_post_id: Optional[str] = None
    wix_url = ""
    # Issue #105: typed, sanitized note when prior publication evidence could
    # not be interpreted — it never suppresses publication, but the run says so.
    _unusable_prior_evidence: Optional[dict] = None

    _r1_cls = {"wix": WixPublisher, "linkedin": LinkedInPublisher}
    _r1_packages = {
        outcome.channel: outcome.package
        for outcome in _channel_outcomes
        if outcome.package is not None
    }
    for name in _R1_PUBLISHERS:
        _verdict = preflight.verdict_for(name)
        if _verdict is None or _verdict.disposition is PreflightDisposition.BLOCK:
            _reasons = (
                ", ".join(r.value for r in _verdict.blocking_reasons)
                if _verdict is not None else "no preflight verdict"
            )
            print(f"  ✗  {name:<12} BLOCKED by preflight ({_reasons}) — not published")
            results[name] = {
                "platform": name, "status": "BLOCKED",
                "error_message": f"publication preflight: {_reasons}",
                "external_id": None, "url": None, "run_id": run_ctx.run_id,
            }
            continue
        try:
            channel_view = (
                strategy_execution.wix
                if name == "wix"
                else strategy_execution.linkedin
            )
            require_configuration_identity(
                strategy_execution.identity,
                channel_view.identity,
                f"{name}-publication",
            )
            _package = _r1_packages[name]
            # The authorized object is the one that crosses the boundary: its
            # digest must still be exactly what the persisted verdict allowed.
            if _package.package_digest() != _verdict.package_digest:
                raise ValueError(
                    f"{name} package digest does not match the preflight verdict"
                )

            # ── Wix retry idempotency (Issue #105 / Story #18) ───────────────
            # Runs only after this channel received preflight ALLOW and only on
            # the exact authorized package, so it can suppress an authorized
            # call but never bypass any gate. A proven earlier PUBLISHED result
            # for the same (signal, accepted article, Wix site) means this run
            # creates no second post: no media import, no draft, no publish.
            _scan = None
            if name == "wix":
                _scan = find_prior_wix_publication(
                    PACKAGES_DIR,
                    WixPublicationIdentity.from_package(_package),
                    current_run_id=run_ctx.run_id,
                )
            elif name == "linkedin":
                # Issue #109: the same discipline for LinkedIn — the duplicate
                # identity is the accepted LinkedIn body, not the article, so a
                # different composition of the same article publishes normally.
                _scan = find_prior_linkedin_publication(
                    PACKAGES_DIR,
                    LinkedInPublicationIdentity.from_package(_package),
                    current_run_id=run_ctx.run_id,
                )
            if _scan is not None:
                _note = _scan.evidence_note()
                if _note is not None:
                    _unusable_prior_evidence = _note
                if _scan.match is not None:
                    print(
                        f"  ↺  {name:<12} REUSED — already published by run "
                        f"{_scan.match.run_id} (post {_scan.match.post_id}); "
                        "no duplicate created"
                    )
                    result = _normalize_publish_result(
                        PublishResult(
                            platform=name,
                            status=PublishStatus.REUSED,
                            external_id=_scan.match.post_id,
                            url=_scan.match.url or None,
                            url_provenance=_scan.match.url_provenance,
                            reused_from_run_id=_scan.match.run_id,
                        ),
                        run_ctx.run_id,
                        name,
                    )
                    results[name] = result.to_dict()
                    if name == "wix":
                        wix_post_id = result.external_id
                        wix_url = result.url or ""
                    continue

            result = _r1_cls[name]().publish(
                _package, "live", strategy_view=channel_view
            )
            result = _normalize_publish_result(result, run_ctx.run_id, name)
            results[name] = result.to_dict()
            if name == "wix" and result.ok():
                wix_post_id = result.external_id
                wix_url     = result.url or ""
        except Exception as exc:
            log.error("%s publish error: %s", name, exc)
            results[name] = {
                "platform": name, "status": "FAILED",
                "error_message": str(exc), "external_id": None, "url": None,
                "run_id": run_ctx.run_id,
            }

    print()
    for platform, res in results.items():
        status = res.get("status", "?")
        icon = "↺" if status == "REUSED" else ("✓" if status in _OK_STATUSES else "✗")
        print(f"  {icon}  {platform:<12} status={status}")
        print(f"           id={res.get('external_id') or '—'}")
        print(f"           url={(res.get('url') or '—')[:80]}")
        if res.get("error_message"):
            print(f"           error={res['error_message']}")
    print(f"  —  [skipped-not-r1] {', '.join(_NON_R1_PUBLISHERS)}")

    # ── Write publication_results.json (immutable, once per run) ─────────────
    published_at = datetime.now(timezone.utc)
    failed = [
        p for p, r in results.items()
        if r.get("status") not in _COMPLETED_STATUSES
    ]
    _run_errors = [
        results[p].get("error_message") or f"{p} failed"
        for p in failed
    ]
    _pub_results_data = {
        "run_id":             run_ctx.run_id,
        "signal_id":          signal_id,
        "source_run_id":      _source_run_id,
        "generation_run_id":  _generation_run_id,
        "execution_mode":     run_ctx.execution_mode.value,
        "configuration_identity": strategy_execution.identity.model_dump(),
        "published_at":       published_at.isoformat(),
        "results":            results,
        "completed":          not bool(failed),
        "errors":             _run_errors,
        "wix_url":            wix_url,
        "wix_post_id":        wix_post_id,
        # Issue #105 — smallest truthful reuse provenance for this run.
        "wix_reused_from_run_id": (
            results.get("wix", {}).get("reused_from_run_id")
        ),
        "unusable_prior_publication_evidence": _unusable_prior_evidence,
    }
    try:
        write_publication_results_json(run_dir, _pub_results_data)
    except (ArtifactCollisionError, OSError, TypeError, ValueError) as exc:
        # Publishing already happened, but the run is not complete unless its
        # immutable result artifact is committed.  Do not write history, run
        # analytics, or emit a success report for an unrecorded publication.
        print(f"\n  ERROR: publication results could not be committed: {exc}")
        state.ended(TerminalStage.PUBLICATION, TerminalDisposition.FAILED,
                    f"publication results not committed: {type(exc).__name__}")
        report = R1RunReport(
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            execution_mode=run_ctx.execution_mode.value,
            results={name: r for name, r in results.items()},
            errors=[*_run_errors, f"artifact commit failed: {exc}"],
            completed=False,
        )
        _emit_run_report(report)
        return 1

    # ── Write to History ──────────────────────────────────────────────────────
    publications: dict[str, PlatformPublication] = {}
    for pub_name, pub_dict in results.items():
        if pub_dict.get("status") in _OK_STATUSES:
            publications[pub_name] = PlatformPublication(
                platform=pub_name,
                external_id=pub_dict.get("external_id") or None,
                url=pub_dict.get("url") or "",
                published_at=published_at,
                status=pub_dict.get("status", "published").lower(),
            )

    _is_from_pkg_or_legacy = args.from_package or args.legacy_package
    entry = PublishedEntry(
        content_id=signal_id,
        strategy_id=strategy_id,
        published_at=published_at,
        platform="blog",
        url=wix_url,
        platform_content_id=wix_post_id,
        publications=publications,
        topic=headline,
        cta_mode=cta_mode,
        echo=echo_line or None,
        hook=structured.get("hook", "") if not _is_from_pkg_or_legacy else "",
    )
    try:
        append_published_entry(entry)
        print(f"\n  ✓  History entry written (strategy_id={strategy_id})")
    except Exception as exc:
        print(f"\n  WARNING: History write failed (non-fatal): {exc}")

    # ── Run analytics ─────────────────────────────────────────────────────────
    print(f"\n[6/6] Running analytics…")
    print("  (LinkedIn analytics may return 404 immediately after publish — expected)")
    print()
    analytics_result = run_analytics_pipeline([BlogCollector(), LinkedInCollector()])
    print(analytics_result.format_summary())

    # ── Final run report ──────────────────────────────────────────────────────
    report = R1RunReport(
        run_id=run_ctx.run_id,
        signal_id=signal_id,
        execution_mode=run_ctx.execution_mode.value,
        results={name: r for name, r in results.items()},
        errors=_run_errors,
        completed=not bool(failed),
    )
    _emit_run_report(report)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    state.ended(
        TerminalStage.PUBLICATION,
        TerminalDisposition.FAILED if failed else TerminalDisposition.COMPLETED,
        *_run_errors,
    )
    if failed:
        print(f"  PARTIAL — failed R1 channels: {failed}")
        print(f"  run_id: {run_ctx.run_id}  [FAILED]")
        print(SEP)
        return 1
    print("  DONE — Release 1 channels published (Wix + LinkedIn).")
    print(f"  Wix:     {wix_url or wix_post_id or '—'}")
    print(f"  strategy_id: {strategy_id}")
    print(f"  run_id:      {run_ctx.run_id}  [COMPLETE]")
    print(SEP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
