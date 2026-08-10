"""
Never Blank — Controlled End-to-End Run.

Orchestrates the full article generation pipeline with complete external-write
isolation. Protection is provided by an immutable ControlledRunPolicy object
that is EXPLICITLY created here and EXPLICITLY passed to every adapter boundary.

## Primary protection: ControlledRunPolicy (dependency injection)

The policy object is the PRIMARY gate. It is:
  1. Created with all writes forbidden (all flags False by default)
  2. Passed as `policy=policy` to every publisher (via template method in BasePublisher)
  3. Passed to upload_to_cloudinary and append_published_entry
  4. Passed to _build_visual_brief_for_run (for exclusion tags)
  5. Every check recorded to policy.audit_trail for evidence-based validation

## Secondary protection: NB_CONTROLLED_RUN=1 env-var

Defense-in-depth. Remains set for the duration of the run. Catches any legacy
callers that do not accept a policy parameter.

## Decision Lens recording (no mock.patch)

The DL recording wrapper is passed as `decision_lens_fn` to generate_article().
generate_article() calls it INSTEAD of the default generate_decision_lens.
No mock.patch, no namespace interception at runtime.

## Visual brief

build_visual_brief() from src/publishing/visual_brief.py is the shared production
implementation used by both the controlled run and the production publishing path.
Policy exclusions are passed via policy_exclusion_tags parameter (not hardcoded).

## Modes

full-e2e
  Calls the production Research Engine stages (run_discovery, score_candidates,
  enrich_candidates, add_angles) with isolated I/O.

existing-signal
  Loads an existing signal by --signal-id from signals files.

synthetic-signal
  Creates a minimal stub signal from --topic without invoking the Research Engine.
  NOT a proof of the research-to-editorial chain.

## Exit codes
  0  success
  1  validation error, preflight failure, or pipeline failure

## Protected operations
  publication          — ControlledRunPolicy.publication_allowed=False
  cloudinary_upload    — ControlledRunPolicy.permanent_storage_allowed=False
  history_write        — ControlledRunPolicy.history_writes_allowed=False
  image_reuse          — ControlledRunPolicy.image_reuse_allowed=False
  image_generation     — ControlledRunPolicy.image_generation_allowed (from --image-generation flag)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.lifecycle.signal_lifecycle import ResearchContext
from src.controlled_run.guard import ControlledRunGuard, ControlledRunViolation
from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation
from src.publishing.visual_brief import build_visual_brief, CR_POLICY_EXCLUSIONS
from src.utils.logger import get_logger

log = get_logger("controlled_run")


# ---------------------------------------------------------------------------
# Invocation ledger (orchestrator-level stage recording)
# ---------------------------------------------------------------------------

class InvocationLedger:
    """
    Records each ORCHESTRATION stage invocation, its outcome, and measurable evidence.
    The validation report is built from BOTH the ledger AND policy.audit_trail.
    No hardcoded True/False in the report.
    """
    OUTCOME_PASSED       = "passed"
    OUTCOME_FAILED       = "failed"
    OUTCOME_SKIPPED      = "skipped"
    OUTCOME_NOT_EXECUTED = "not_executed"

    def __init__(self):
        self._entries: list[dict] = []

    def record(self, stage: str, outcome: str, evidence: dict | None = None, note: str = "") -> None:
        self._entries.append({
            "stage":           stage,
            "outcome":         outcome,
            "evidence":        evidence or {},
            "note":            note,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        })

    def all_entries(self) -> list[dict]:
        return list(self._entries)

    def outcome_for(self, stage: str) -> str:
        for e in reversed(self._entries):
            if e["stage"] == stage:
                return e["outcome"]
        return self.OUTCOME_NOT_EXECUTED

    def build_validation_report(self, policy: ControlledRunPolicy) -> dict:
        checks = {e["stage"]: e["outcome"] for e in self._entries}
        # Non-mandatory stages: image_generation may be skipped; decision_lens
        # is an observability sub-stage inside article_generation.
        NON_MANDATORY = {"image_generation", "decision_lens"}
        all_mandatory_passed = all(
            v == self.OUTCOME_PASSED
            for k, v in checks.items()
            if k not in NON_MANDATORY
        )
        image_status = checks.get("image_generation", self.OUTCOME_NOT_EXECUTED)
        image_skipped = image_status == self.OUTCOME_SKIPPED

        if not all_mandatory_passed:
            status = "failed"
        elif image_skipped:
            status = "complete_without_image"
        else:
            status = "complete"

        # Policy audit summary — grounded in actual recorded checks
        policy_audit = policy.audit_summary()

        return {
            "all_mandatory_passed": all_mandatory_passed,
            "overall_status":       status,
            "checks":               checks,
            "ledger":               self.all_entries(),
            "image_generation":     image_status,
            "policy_audit":         policy_audit,
            "verification_source":  "InvocationLedger + ControlledRunPolicy.audit_trail",
            "note": (
                "complete_without_image: all editorial stages passed; "
                "image generation was explicitly skipped via --image-generation disabled"
                if image_skipped else ""
            ),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Never Blank — Controlled End-to-End Run (no external writes)"
    )
    parser.add_argument("--mode", required=True,
                        choices=["full-e2e", "existing-signal", "synthetic-signal"])
    parser.add_argument("--publication", required=True, choices=["disabled"])
    parser.add_argument("--external-writes", required=True, choices=["disabled"])
    parser.add_argument("--cache", default="disabled", choices=["disabled"])
    parser.add_argument("--image-reuse", default="disabled", choices=["disabled"])
    parser.add_argument("--image-generation", default="disabled",
                        choices=["disabled", "enabled"])
    parser.add_argument("--output-root", default="artifacts/controlled_runs")
    parser.add_argument("--topic", default="")
    parser.add_argument("--brand", default="Never Blank")
    parser.add_argument("--channels", default="linkedin,blog,instagram")
    parser.add_argument("--signal-id", default="")
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> list[str]:
    errors = []
    if args.publication != "disabled":
        errors.append("--publication must be 'disabled'")
    if args.external_writes != "disabled":
        errors.append("--external-writes must be 'disabled'")
    if args.mode in ("full-e2e", "synthetic-signal") and not args.topic.strip():
        errors.append("--topic is required when --mode is full-e2e or synthetic-signal")
    if args.mode == "existing-signal" and not args.signal_id.strip():
        errors.append("--signal-id is required when --mode=existing-signal")
    return errors


# ---------------------------------------------------------------------------
# Research Engine (full-e2e)
# ---------------------------------------------------------------------------

def _run_research_engine(topic_hint: str, run_dir: Path, ledger: InvocationLedger) -> dict:
    """
    Invoke the production Research Engine stages with isolated I/O.

    ## Side-effect audit (verified by reading each source file)

    run_discovery(seen_ids: set) -> list[dict]:
      - Reads: config/research_sources.yaml (read-only config)
      - Reads: RSS feeds via requests.get() (network read, no write)
      - Writes: NONE to filesystem
      - LLM: calls chat() for candidate filtering (_llm_filter_candidates)
      - Cache: NONE — seen_ids is caller-owned in-memory set; function never writes it back

    score_candidates(candidates: list[dict]) -> list[dict]:
      - Reads: config/scoring_weights.yaml (read-only config)
      - Writes: NONE to filesystem
      - LLM: calls chat() for scoring (_llm_score_batch)
      - Cache: NONE

    enrich_candidates(candidates: list[dict]) -> list[dict]:
      - Reads: prompt files via load_prompt() (read-only config)
      - Writes: NONE to filesystem
      - LLM: calls chat() per signal (enrich_signal)
      - Cache: NONE

    add_angles(signals: list[dict]) -> list[dict]:
      - Reads: prompt files via load_prompt() (read-only config)
      - Writes: NONE to filesystem
      - LLM: calls chat() per signal (generate_angles)
      - Cache: NONE

    UNCONTROLLED EXTERNAL PROPERTY:
      LLM provider-side prompt caching (Anthropic or OpenAI) cannot be disabled
      by the client. This is documented in run_manifest.json as
      "external_uncontrolled_properties": ["llm_provider_cache"].

    CONTROLLED ISOLATION:
      - seen_ids=set() prevents cross-run signal deduplication
      - Results saved to run_dir ONLY; signals_active.jsonl never written
      - run_daily_research.run() is NOT called (no registry/history updates)

    Raises ValueError if research produces no article-ready signal.
    """
    from scripts.research.discover import run_discovery
    from scripts.research.score import score_candidates
    from scripts.research.enrich import enrich_candidates
    from scripts.research.angles import add_angles
    from scripts.research.run_daily_research import SCHEMA_DEFAULTS

    # Stage R1: Discovery — seen_ids=empty set means no prior-signal filtering
    log.info("[R1] Discovery (production run_discovery, seen_ids=empty)")
    candidates = run_discovery(seen_ids=set())
    ledger.record("research_discovery", InvocationLedger.OUTCOME_PASSED, {
        "candidates_found": len(candidates),
        "entry_point":      "scripts.research.discover.run_discovery",
        "cache_state":      "none — function has no cache; seen_ids=set() (empty)",
        "filesystem_writes": "none",
        "provider":         "RSS feeds + LLM (chat)",
    })
    (run_dir / "research_candidates.json").write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if not candidates:
        for stage in ("research_score", "research_enrich", "research_angles",
                      "research_signal_selection"):
            ledger.record(stage, InvocationLedger.OUTCOME_SKIPPED,
                          note="No candidates from discovery")
        raise ValueError("Research Engine produced no candidates")

    # Stage R2: Score
    log.info("[R2] Scoring %d candidates", len(candidates))
    scored = score_candidates(candidates)
    ledger.record("research_score", InvocationLedger.OUTCOME_PASSED, {
        "scored_count":     len(scored),
        "entry_point":      "scripts.research.score.score_candidates",
        "cache_state":      "none",
        "filesystem_writes": "none",
        "provider":         "LLM (chat)",
    })
    (run_dir / "research_scored.json").write_text(
        json.dumps(scored, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Stage R3: Enrich
    log.info("[R3] Enriching %d candidates", len(scored))
    enriched = enrich_candidates(scored)
    ledger.record("research_enrich", InvocationLedger.OUTCOME_PASSED, {
        "enriched_count":   len(enriched),
        "entry_point":      "scripts.research.enrich.enrich_candidates",
        "cache_state":      "none",
        "filesystem_writes": "none",
        "provider":         "LLM (chat)",
    })
    (run_dir / "research_enriched.json").write_text(
        json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Stage R4: Angles
    log.info("[R4] Adding angles")
    with_angles = add_angles(enriched)
    ledger.record("research_angles", InvocationLedger.OUTCOME_PASSED, {
        "signals_with_angles": len(with_angles),
        "entry_point":         "scripts.research.angles.add_angles",
        "cache_state":         "none",
        "filesystem_writes":   "none",
        "provider":            "LLM (chat)",
    })
    (run_dir / "research_angles.json").write_text(
        json.dumps(with_angles, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Apply schema defaults
    final_signals = []
    for sig in with_angles:
        full = dict(SCHEMA_DEFAULTS)
        full.update(sig)
        final_signals.append(full)

    # Select first admitted signal
    selected = None
    for sig in final_signals:
        rc = ResearchContext.from_dict(sig)
        if rc.admission_status in ("admitted", "force_override"):
            selected = sig
            break

    if selected is None:
        ledger.record("research_signal_selection", InvocationLedger.OUTCOME_FAILED, {
            "candidates_evaluated":  len(final_signals),
            "article_ready_signals": 0,
        }, note="No signal passed admission gate")
        raise ValueError(
            f"Research Engine produced {len(final_signals)} signals but none passed "
            "the admission gate (article_ready=False for all)"
        )

    rc_selected = ResearchContext.from_dict(selected)
    source_urls = [selected.get("SOURCE_URL", ""), selected.get("SOURCE_FOR_CASE", "")]
    ledger.record("research_signal_selection", InvocationLedger.OUTCOME_PASSED, {
        "selected_signal_id":  selected["SIGNAL_ID"],
        "selected_headline":   selected.get("HEADLINE", "")[:80],
        "source_urls":         [u for u in source_urls if u],
        "article_ready":       rc_selected.article_ready,
        "admission_status":    rc_selected.admission_status,
    })
    (run_dir / "selected_signal.json").write_text(
        json.dumps(selected, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return selected


# ---------------------------------------------------------------------------
# Signal loaders
# ---------------------------------------------------------------------------

def _load_existing_signal(signal_id: str) -> dict:
    for path in [
        Path("data/research/signals_active.jsonl"),
        Path("data/research/selected_signals.jsonl"),
    ]:
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
    raise FileNotFoundError(f"Signal {signal_id!r} not found in research files")


def _create_synthetic_signal(topic: str) -> dict:
    """
    Stub signal for synthetic-signal mode. NOT from the Research Engine.
    Uses RECOMMENDED_FOR_ARTICLE alias (no ARTICLE_READY) to exercise normalization fix.
    """
    signal_id = f"synth-{uuid4().hex[:12]}"
    return {
        "SIGNAL_ID":               signal_id,
        "_synthetic":              True,
        "_synthetic_note":         "synthetic-signal mode: NOT from Research Engine",
        "HEADLINE":                topic,
        "SIGNAL_TYPE":             "business trust",
        "REGION":                  "US",
        "INDUSTRY":                "General",
        "SOURCE_NAME":             "synthetic-stub",
        "SOURCE_URL":              "",
        "SOURCE_DATE":             datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "DATE_FOUND":              datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "CORE_FACT":               f"Synthetic stub fact: {topic}",
        "CONFIDENCE":              "medium",
        "SOURCE_PREMISE_VERIFIED": "unknown",
        "SOURCE_FOR_CASE":         "synthetic://controlled-run-test",
        "OUTCOME_IF_KNOWN":        "unknown",
        "DID_IT_WORK":             "unknown",
        "EVIDENCE_OF_OUTCOME":     "",
        "SOURCE_QUALITY":          "",
        "NOTES":                   "Synthetic signal — not from Research Engine",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
        "ARTICLE_READINESS_SCORE": "7",
        "CHANNEL_FIT_SCORE":       "7",
        "SIGNAL_STRENGTH":         "medium",
        "DISCUSSION_POTENTIAL":    "medium",
        "score_reason":            "synthetic",
        "CORE_TENSION":            f"Tension for: {topic}",
        "BUSINESS_LESSON":         f"Lesson from: {topic}",
        "WHY_THIS_CASE_IS_INTERESTING": f"Interesting because: {topic}",
        "WHY_IT_MATTERS_TO_BUSINESS":   f"Business relevance: {topic}",
        "BUSINESS_RESPONSES_OBSERVED":  "",
        "PROBLEM_FACED":           f"Problem in: {topic}",
        "RESPONSE_TAKEN":          "unknown",
        "COUNTER_EXAMPLE":         "",
        "TIME_HORIZON":            "medium",
        "INTERESTING_QUESTION":    f"What does {topic} reveal?",
        "NEVER_BLANK_ANGLE":       f"The real signal in '{topic}' is not the event itself.",
        "POSSIBLE_SIGNATURE_LINE": "Never Blank: The signal is rarely the event itself.",
        "POTENTIAL_HOOK":          f"What {topic} reveals about presence.",
        "TARGET_AUDIENCE":         "founder",
        "PRIMARY_CHANNEL":         "linkedin",
        "LINKEDIN_ANGLE":          f"LinkedIn angle: {topic}",
        "BLOG_ANGLE":              f"Blog angle: {topic}",
        "THREADS_ANGLE":           f"Threads angle: {topic}",
        "STORY_ANGLE":             f"Story angle: {topic}",
        "raw_summary":             f"Synthetic summary for {topic}",
        "discovery_confidence":    "medium",
        "APPROVED_OVERRIDE":       "",
        "RECOMMENDED_FOR_ARTICLE": "true",  # no ARTICLE_READY — tests normalization
    }


# ---------------------------------------------------------------------------
# Decision Lens recording wrapper (NO mock.patch — uses DI via decision_lens_fn)
# ---------------------------------------------------------------------------

def _make_decision_lens_recorder(run_dir: Path, ledger: InvocationLedger) -> tuple[Callable, dict]:
    """
    Return (recording_wrapper, dl_record).

    The recording_wrapper is passed as decision_lens_fn to generate_article().
    generate_article() calls it INSTEAD of the default generate_decision_lens.
    No mock.patch, no runtime namespace interception.

    dl_record is mutated in-place by the wrapper when called.
    Artifacts are written after generate_article() returns.
    """
    from src.editorial.decision_lens_lite import generate_decision_lens as _real_dl

    dl_record: dict = {"called": False, "input": None, "output": None}

    def _recording_wrapper(signal: dict) -> dict:
        dl_record["called"] = True
        dl_record["input"]  = signal
        result = _real_dl(signal)
        dl_record["output"] = result
        return result

    return _recording_wrapper, dl_record


def _write_decision_lens_artifacts(
    run_dir: Path, ledger: InvocationLedger, dl_record: dict
) -> None:
    """Write DL artifacts and record to ledger. Called after generate_article() returns."""
    if dl_record["called"]:
        (run_dir / "decision_lens_input.json").write_text(
            json.dumps(dl_record["input"], indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        (run_dir / "decision_lens_output.json").write_text(
            json.dumps(dl_record["output"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        ledger.record("decision_lens", InvocationLedger.OUTCOME_PASSED, {
            "entry_point":               "src.editorial.decision_lens_lite.generate_decision_lens",
            "injection_method":          "decision_lens_fn parameter in generate_article()",
            "output_keys":               list((dl_record["output"] or {}).keys()),
            "never_blank_angle_in_input": bool((dl_record["input"] or {}).get("NEVER_BLANK_ANGLE")),
        })
    else:
        ledger.record("decision_lens", InvocationLedger.OUTCOME_NOT_EXECUTED,
                      note="generate_decision_lens was not called by generate_article — unexpected")


# ---------------------------------------------------------------------------
# Image generation (production provider, isolated output)
# ---------------------------------------------------------------------------

def _run_image_generation(
    signal: dict,
    visual_brief,
    run_dir: Path,
    ledger: InvocationLedger,
    policy: ControlledRunPolicy,
) -> dict:
    """
    Call production _generate_base_image(). Save to run_dir only.
    Policy checks image_generation permission before any provider call.
    Does NOT call upload_to_cloudinary. Does NOT read image_library.json.
    """
    from src.publishing.image_pipeline import (
        _generate_base_image,
        composite_for_platform,
        CARD_TYPES,
    )

    # Policy gate — before any provider call
    policy.check("image_generation", adapter="_generate_base_image")

    visual_family   = visual_brief.visual_family
    image_prompt    = visual_brief.image_prompt
    negative_prompt = visual_brief.negative_prompt
    is_card         = visual_family in CARD_TYPES

    if is_card:
        method     = "quote_card"
        base_bytes = None
    else:
        base_bytes, method = _generate_base_image(
            image_prompt, visual_family, negative_prompt, log=log.info
        )

    local_path = "(quote_card)"
    if base_bytes is not None:
        img_path = run_dir / "generated_image_blog.png"
        sized    = composite_for_platform(base_bytes, visual_brief.hook_text, "blog")
        sized.save(str(img_path), "PNG", optimize=True)
        local_path = str(img_path)

    record = {
        "generated":             True,
        "method":                method,
        "visual_family":         visual_family,
        "local_path":            local_path,
        "cloudinary_upload":     "blocked by policy (permanent_storage_allowed=False)",
        "image_library_updated": False,
        "image_reuse":           False,
    }
    (run_dir / "image_generation_result.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    ledger.record("image_generation", InvocationLedger.OUTCOME_PASSED, {
        "entry_point":   "src.publishing.image_pipeline._generate_base_image",
        "method":        method,
        "cloudinary":    "not_called (policy.check('cloudinary_upload') would raise PolicyViolation)",
        "image_library": "not_read",
        "local_path":    local_path,
    })
    return record


# ---------------------------------------------------------------------------
# Platform drafts
# ---------------------------------------------------------------------------

def _build_platform_drafts(article_result: dict, channels: list[str]) -> dict:
    platforms   = article_result.get("platforms", {})
    channel_map = {
        "blog":      ("long",      "body"),
        "linkedin":  ("medium",    "body"),
        "facebook":  ("reading",   "body"),
        "instagram": ("instagram", "body"),
    }
    drafts: dict = {}
    for ch in channels:
        if ch in channel_map:
            key, fld = channel_map[ch]
            data = platforms.get(key, {})
            body = data.get(fld, "") if isinstance(data, dict) else ""
            drafts[ch] = {"body": body, "channel": ch}
        else:
            drafts[ch] = {"body": "", "channel": ch, "note": "channel not in editorial output"}
    return drafts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_sha() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_controlled(args: argparse.Namespace) -> int:
    # Defense-in-depth env-var. Primary protection is ControlledRunPolicy (DI).
    os.environ["NB_CONTROLLED_RUN"] = "1"

    run_id     = uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)
    timestamp  = started_at.strftime("%Y%m%d_%H%M%S")
    channels   = [c.strip() for c in args.channels.split(",") if c.strip()]
    ledger     = InvocationLedger()

    # Create the immutable policy object — PRIMARY protection
    policy = ControlledRunPolicy(
        run_id                    = run_id,
        publication_allowed       = False,
        external_drafts_allowed   = False,
        permanent_storage_allowed = False,
        history_writes_allowed    = False,
        database_writes_allowed   = False,
        cache_reads_allowed       = False,
        cache_writes_allowed      = False,
        image_reuse_allowed       = False,
        image_generation_allowed  = (args.image_generation == "enabled"),
    )

    output_root = Path(args.output_root)
    run_dir     = output_root / f"{timestamp}_{run_id}"

    if run_dir.exists():
        log.error("Run directory already exists: %s", run_dir)
        return 1
    run_dir.mkdir(parents=True, exist_ok=False)

    is_synthetic = (args.mode == "synthetic-signal")

    manifest: dict = {
        "run_id":                   run_id,
        "started_at_utc":           started_at.isoformat(),
        "completed_at_utc":         None,
        "git_sha":                  _git_sha(),
        "entry_point":              "scripts/controlled_run.py",
        "mode":                     args.mode,
        "synthetic":                is_synthetic,
        "synthetic_note":           (
            "synthetic-signal mode: signal NOT from Research Engine. "
            "NOT a proof of the research-to-editorial chain."
            if is_synthetic else None
        ),
        "publication_disabled":     True,
        "external_writes_disabled": True,
        "cache_policy":             "disabled",
        "image_reuse":              False,
        "image_generation":         args.image_generation,
        "input_topic":              args.topic,
        "input_signal_id":          args.signal_id if args.mode == "existing-signal" else "",
        "brand":                    args.brand,
        "channels":                 channels,
        "nb_controlled_run_env":    os.environ.get("NB_CONTROLLED_RUN", ""),
        "models":                   {},
        "providers":                {},
        "source_identifiers":       [],
        "artifact_paths":           {},
        "status":                   "running",
        "failure_stage":            None,
        "external_uncontrolled_properties": [
            "llm_provider_cache — provider-side prompt caching cannot be disabled by client"
        ],
        "policy_enforcement": {
            "primary":   "ControlledRunPolicy (dependency injection, explicit pass-through)",
            "secondary": "NB_CONTROLLED_RUN=1 env-var (defense-in-depth, legacy callers)",
            "audit":     "policy.audit_trail records every check (both allowed and blocked)",
            "template_method": "BasePublisher.publish() non-abstract; _publish_impl() abstract",
            "limitation": "TelegramPublisher overrides publish() for wix_url kwarg; "
                          "explicitly calls _check_policy(). All other publishers protected "
                          "by template method automatically.",
        },
    }

    def _save_manifest():
        (run_dir / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    _save_manifest()
    failure_stage = None

    try:
        # Stage 1: Signal acquisition
        failure_stage = "signal_acquisition"
        if args.mode == "full-e2e":
            log.info("[1] full-e2e: invoking production Research Engine")
            signal = _run_research_engine(args.topic, run_dir, ledger)
            manifest["source_identifiers"] = [
                signal.get("SIGNAL_ID", ""),
                signal.get("SOURCE_URL", ""),
                signal.get("SOURCE_FOR_CASE", ""),
            ]
        elif args.mode == "existing-signal":
            signal = _load_existing_signal(args.signal_id)
            ledger.record("signal_acquisition", InvocationLedger.OUTCOME_PASSED, {
                "mode":      "existing-signal",
                "signal_id": signal.get("SIGNAL_ID"),
                "source":    "signals_active.jsonl / selected_signals.jsonl",
            })
            manifest["source_identifiers"] = [signal.get("SIGNAL_ID", "")]
        else:  # synthetic-signal
            signal = _create_synthetic_signal(args.topic)
            ledger.record("signal_acquisition", InvocationLedger.OUTCOME_PASSED, {
                "mode":      "synthetic-signal",
                "signal_id": signal["SIGNAL_ID"],
                "note":      "NOT from Research Engine — synthetic stub",
            })
            manifest["source_identifiers"] = [signal["SIGNAL_ID"]]

        # Stage 2: ResearchContext preflight
        failure_stage = "research_context"
        rc = ResearchContext.from_dict(signal)
        if not rc.article_ready and not rc.force_override:
            raise ValueError(
                f"Signal {signal.get('SIGNAL_ID')!r} blocked by preflight — "
                f"article_ready={rc.article_ready}, admission_status={rc.admission_status!r}"
            )
        ledger.record("research_context", InvocationLedger.OUTCOME_PASSED, {
            "signal_id":         rc.signal_id,
            "article_ready":     rc.article_ready,
            "admission_status":  rc.admission_status,
            "score_recommended": rc.score_recommended,
        })
        (run_dir / "research_context.json").write_text(
            json.dumps(rc.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        manifest["artifact_paths"]["research_context"] = str(run_dir / "research_context.json")

        # Stage 3: EditorialContext
        failure_stage = "editorial_context"
        editorial_package = {
            "SIGNAL_ID": signal.get("SIGNAL_ID"),
            "content":   {},
            "images":    {"platform_images": {}},
            "_note":     "controlled-run: no image library, no Cloudinary",
        }
        editorial_ctx = rc.to_editorial(editorial_package)
        ledger.record("editorial_context", InvocationLedger.OUTCOME_PASSED, {
            "signal_id":               editorial_ctx.signal_id,
            "admission_status":        editorial_ctx.admission_status,
            "never_blank_angle_present": bool(editorial_ctx.never_blank_angle),
        })
        ec_dict = editorial_ctx.to_legacy_dict()
        ec_dict["_editorial_metadata"] = {
            "factual_readiness":  editorial_ctx.factual_readiness,
            "admission_status":   editorial_ctx.admission_status,
            "never_blank_angle":  editorial_ctx.never_blank_angle,
            "potential_hook":     editorial_ctx.potential_hook,
            "target_audience":    editorial_ctx.target_audience,
        }
        (run_dir / "editorial_context.json").write_text(
            json.dumps(ec_dict, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        manifest["artifact_paths"]["editorial_context"] = str(run_dir / "editorial_context.json")

        # Stage 4: Article generation with DL recording via DI (no mock.patch)
        failure_stage = "article_generation"
        dl_input_signal = editorial_ctx.to_legacy_dict()

        from src.editorial.pipeline import generate_article, ArticleGenerationError

        dl_recording_fn, dl_record = _make_decision_lens_recorder(run_dir, ledger)

        try:
            article_result = generate_article(
                dl_input_signal,
                cta_mode="none",
                strategy_context=None,
                decision_lens_fn=dl_recording_fn,
            )
        except ArticleGenerationError as exc:
            raise ValueError(
                f"Article generation failed at stage {exc.stage!r}: {exc.original}"
            ) from exc

        # Write DL artifacts AFTER generate_article returns (no interception)
        _write_decision_lens_artifacts(run_dir, ledger, dl_record)

        ledger.record("article_generation", InvocationLedger.OUTCOME_PASSED, {
            "entry_point":        "src.editorial.pipeline.generate_article",
            "dl_injection":       "decision_lens_fn parameter (no mock.patch)",
            "platforms_produced": list(article_result.get("platforms", {}).keys()),
        })
        manifest["artifact_paths"]["decision_lens_input"]  = str(run_dir / "decision_lens_input.json")
        manifest["artifact_paths"]["decision_lens_output"] = str(run_dir / "decision_lens_output.json")
        (run_dir / "generated_article.json").write_text(
            json.dumps(article_result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        manifest["artifact_paths"]["generated_article"] = str(run_dir / "generated_article.json")

        # Stage 5: Platform drafts
        failure_stage = "platform_drafts"
        platform_drafts = _build_platform_drafts(article_result, channels)
        (run_dir / "platform_drafts.json").write_text(
            json.dumps(platform_drafts, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        ledger.record("platform_drafts", InvocationLedger.OUTCOME_PASSED, {
            "channels":        channels,
            "drafts_produced": list(platform_drafts.keys()),
        })
        manifest["artifact_paths"]["platform_drafts"] = str(run_dir / "platform_drafts.json")

        # Stage 6: Visual brief (shared production component)
        failure_stage = "visual_spec"
        from src.publishing.image_pipeline import load_registry

        registry = load_registry()
        visual_brief = build_visual_brief(
            signal               = signal,
            article_result       = article_result,
            brand_name           = args.brand,
            content_goal         = "challenge",
            registry             = registry,
            log                  = log.info,
            policy_exclusion_tags = CR_POLICY_EXCLUSIONS,
        )
        (run_dir / "visual_spec.json").write_text(
            json.dumps(visual_brief.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        ledger.record("visual_spec", InvocationLedger.OUTCOME_PASSED, {
            "entry_point":            "src.publishing.visual_brief.build_visual_brief",
            "visual_family":          visual_brief.visual_family,
            "palette":                visual_brief.dominant_palette,
            "image_prompt_present":   bool(visual_brief.image_prompt),
            "angle_source_present":   bool(visual_brief.angle_source),
            "policy_exclusions":      bool(visual_brief.policy_exclusions),
        })
        manifest["artifact_paths"]["visual_spec"] = str(run_dir / "visual_spec.json")

        # Stage 7: Image generation
        failure_stage = "image_generation"
        if args.image_generation == "enabled":
            _run_image_generation(signal, visual_brief, run_dir, ledger, policy)
            manifest["artifact_paths"]["image_generation_result"] = str(
                run_dir / "image_generation_result.json"
            )
        else:
            skip_record = {
                "skipped":               True,
                "reason":                "--image-generation disabled",
                "visual_spec_built":     True,
                "policy_check":          "policy.check('image_generation') would raise PolicyViolation "
                                         "(image_generation_allowed=False)",
            }
            (run_dir / "image_generation_skipped.json").write_text(
                json.dumps(skip_record, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            ledger.record("image_generation", InvocationLedger.OUTCOME_SKIPPED, {
                "reason":       "--image-generation disabled",
                "policy_check": "skipped (image_generation_allowed=False)",
            }, note="Status will be complete_without_image")
            manifest["artifact_paths"]["image_generation_skipped"] = str(
                run_dir / "image_generation_skipped.json"
            )

        # Stage 8: Validation report from ledger + policy audit
        failure_stage = "validation_report"
        validation_report = ledger.build_validation_report(policy)
        (run_dir / "validation_report.json").write_text(
            json.dumps(validation_report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        manifest["artifact_paths"]["validation_report"] = str(run_dir / "validation_report.json")

        if not validation_report["all_mandatory_passed"]:
            failed = [
                k for k, v in validation_report["checks"].items()
                if v not in (InvocationLedger.OUTCOME_PASSED, InvocationLedger.OUTCOME_SKIPPED)
            ]
            raise ValueError(f"Validation: mandatory stages not passed: {failed}")

    except (PolicyViolation, ControlledRunViolation) as exc:
        log.error("POLICY VIOLATION at stage %r: %s", failure_stage, exc)
        manifest["status"]           = "failed"
        manifest["failure_stage"]    = failure_stage
        manifest["failure_error"]    = str(exc)
        manifest["failure_type"]     = "PolicyViolation"
        manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        _save_manifest()
        return 1

    except Exception as exc:
        log.error("Controlled run FAILED at stage %r: %s", failure_stage, exc)
        manifest["status"]           = "failed"
        manifest["failure_stage"]    = failure_stage
        manifest["failure_error"]    = str(exc)
        manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        _save_manifest()
        return 1

    final_status = validation_report.get("overall_status", "failed")
    manifest["status"]           = final_status
    manifest["failure_stage"]    = None
    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    _save_manifest()
    log.info("Controlled run %s — run_id=%s", final_status, run_id)
    return 0


def main(argv=None) -> int:
    args   = _parse_args(argv)
    errors = _validate_args(args)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return run_controlled(args)


if __name__ == "__main__":
    sys.exit(main())
