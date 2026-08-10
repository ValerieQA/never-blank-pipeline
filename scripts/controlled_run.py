"""
Never Blank — Controlled End-to-End Run.

Primary protection: ControlledRunPolicy (dependency injection).
Secondary: NB_CONTROLLED_RUN=1 env-var (defense-in-depth, legacy callers).

## 9 protected capabilities (all checked via policy.check())

  publication       — BasePublisher.publish() template method
  external_drafts   — preflight audit
  permanent_storage — preflight audit (separate from image_generation)
  history_write     — append_published_entry()
  database_write    — preflight audit
  cache_read        — preflight audit
  cache_write       — preflight audit
  image_reuse       — preflight audit + ImageReuseStore boundary
  cloudinary_upload — upload_to_cloudinary()
  image_generation  — _generate_base_image() (allowed by --image-generation flag)

Note: permanent_storage ≠ image_generation.
  image_generation = LLM / programmatic bytes production.
  permanent_storage = writing those bytes to Cloudinary or the image library.
Both are separately gated.

## Provider injection (no mock.patch in integration tests)

  run_controlled(args, llm_provider=..., feed_provider=..., image_provider=...)
  Integration tests pass FakeLLMProvider, FakeFeedProvider, FakeImageProvider.
  Production uses None (defaults to real implementations).

## Decision Lens (no mock.patch at runtime)

  _make_decision_lens_recorder() → (wrapper_fn, dl_record)
  wrapper_fn passed as decision_lens_fn to generate_article().
  No mock.patch, no namespace interception.

## Lifecycle (Option A)

  RECOMMENDED_FOR_ARTICLE alias removed from _resolve_article_ready().
  Synthetic signals use ARTICLE_READY=true explicitly.
  See LIFECYCLE_ALIAS_PROPOSAL.md.

## Modes
  full-e2e         — production Research Engine + provider injection
  existing-signal  — load from signals_active.jsonl
  synthetic-signal — stub signal from --topic (no Research Engine)

## Exit codes: 0 = success, 1 = failure
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
from src.controlled_run.policy import ControlledRunPolicy, PolicyViolation, PolicyRequiredError
from src.publishing.visual_brief import build_visual_brief, CR_POLICY_EXCLUSIONS
from src.utils.logger import get_logger

log = get_logger("controlled_run")


# ---------------------------------------------------------------------------
# Invocation ledger
# ---------------------------------------------------------------------------

class InvocationLedger:
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
        NON_MANDATORY = {"image_generation", "decision_lens"}
        all_mandatory_passed = all(
            v == self.OUTCOME_PASSED
            for k, v in checks.items()
            if k not in NON_MANDATORY
        )
        image_status  = checks.get("image_generation", self.OUTCOME_NOT_EXECUTED)
        image_skipped = image_status == self.OUTCOME_SKIPPED

        if not all_mandatory_passed:
            status = "failed"
        elif image_skipped:
            status = "complete_without_image"
        else:
            status = "complete"

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
                "image generation explicitly skipped via --image-generation disabled"
                if image_skipped else ""
            ),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Never Blank — Controlled E2E Run")
    p.add_argument("--mode", required=True,
                   choices=["full-e2e", "existing-signal", "synthetic-signal"])
    p.add_argument("--publication", required=True, choices=["disabled"])
    p.add_argument("--external-writes", required=True, choices=["disabled"])
    p.add_argument("--cache", default="disabled", choices=["disabled"])
    p.add_argument("--image-reuse", default="disabled", choices=["disabled"])
    p.add_argument("--image-generation", default="disabled",
                   choices=["disabled", "enabled"])
    p.add_argument("--output-root", default="artifacts/controlled_runs")
    p.add_argument("--topic", default="")
    p.add_argument("--brand", default="Never Blank")
    p.add_argument("--channels", default="linkedin,blog,instagram")
    p.add_argument("--signal-id", default="")
    return p.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> list[str]:
    errors = []
    if args.publication != "disabled":
        errors.append("--publication must be 'disabled'")
    if args.external_writes != "disabled":
        errors.append("--external-writes must be 'disabled'")
    if args.mode in ("full-e2e", "synthetic-signal") and not args.topic.strip():
        errors.append("--topic required for full-e2e / synthetic-signal")
    if args.mode == "existing-signal" and not args.signal_id.strip():
        errors.append("--signal-id required for existing-signal")
    return errors


# ---------------------------------------------------------------------------
# Preflight: call policy.check() for ALL 9 blocked capabilities
# ---------------------------------------------------------------------------

def _run_preflight_capability_audit(policy: ControlledRunPolicy, ledger: InvocationLedger) -> None:
    """
    Call policy.check() for every blocked capability BEFORE any I/O.

    Each blocked operation produces AuditEntry(blocked_before_network=True)
    in policy.audit_trail. This ensures the validation report has complete
    evidence for all 9 capabilities, not just those encountered at runtime.

    Note: image_generation and publication are NOT audited here — they are
    checked at their operation boundaries (image generation boundary and
    BasePublisher.publish() template method respectively).

    permanent_storage and cloudinary_upload are SEPARATE checks:
    - permanent_storage: writing bytes to any permanent location (disk library)
    - cloudinary_upload: specifically the Cloudinary CDN upload
    Both are blocked; both produce AuditEntry objects.
    """
    _PREFLIGHT_OPS: list[tuple[str, str]] = [
        ("external_drafts",   "any external draft creation boundary"),
        ("permanent_storage", "permanent storage writes (image library / disk cache)"),
        ("history_write",     "append_published_entry"),
        ("database_write",    "any database mutation"),
        ("cache_read",        "cache file reads"),
        ("cache_write",       "cache file writes"),
        ("image_reuse",       "ImageReuseStore.get() / .put()"),
        ("cloudinary_upload", "upload_to_cloudinary"),
    ]

    blocked_count = 0
    for operation, adapter in _PREFLIGHT_OPS:
        try:
            policy.check(operation, adapter=adapter)
        except PolicyViolation:
            blocked_count += 1  # expected; records AuditEntry(blocked_before_network=True)

    ledger.record("preflight_capability_audit", InvocationLedger.OUTCOME_PASSED, {
        "operations_checked":  len(_PREFLIGHT_OPS),
        "operations_blocked":  blocked_count,
        "operations_allowed":  len(_PREFLIGHT_OPS) - blocked_count,
        "audit_trail_entries": len(policy.audit_trail),
        "note": (
            "image_generation checked at operation site; "
            "publication checked in BasePublisher.publish() template method"
        ),
    })


# ---------------------------------------------------------------------------
# Research Engine
# ---------------------------------------------------------------------------

def _run_research_engine(
    topic_hint: str,
    run_dir: Path,
    ledger: InvocationLedger,
    llm_provider=None,
    feed_provider=None,
) -> dict:
    """
    Production Research Engine stages with provider injection.

    ## Side-effect audit

    run_discovery(seen_ids=set(), llm_provider, feed_provider):
      Filesystem writes: NONE. Cache: NONE. Network: feed_provider.fetch() only.

    score_candidates(candidates, llm_provider):
      Filesystem writes: NONE. Cache: NONE.

    enrich_candidates(candidates, llm_provider):
      Filesystem writes: NONE. Cache: NONE.

    add_angles(signals, llm_provider):
      Filesystem writes: NONE. Cache: NONE.

    UNCONTROLLED EXTERNAL PROPERTY:
      Provider-side LLM caching cannot be disabled by the client.
      Documented as external_uncontrolled_properties in run_manifest.json.

    Artifacts saved to run_dir ONLY. signals_active.jsonl never written.
    """
    from scripts.research.discover import run_discovery
    from scripts.research.score import score_candidates
    from scripts.research.enrich import enrich_candidates
    from scripts.research.angles import add_angles
    from scripts.research.run_daily_research import SCHEMA_DEFAULTS

    log.info("[R1] Discovery (seen_ids=empty, provider_injected=%s)", llm_provider is not None)
    candidates = run_discovery(set(), llm_provider=llm_provider, feed_provider=feed_provider)
    ledger.record("research_discovery", InvocationLedger.OUTCOME_PASSED, {
        "candidates_found":  len(candidates),
        "llm_injected":      llm_provider is not None,
        "feed_injected":     feed_provider is not None,
        "filesystem_writes": "none",
        "cache":             "none",
    })
    (run_dir / "research_candidates.json").write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if not candidates:
        for s in ("research_score", "research_enrich", "research_angles", "research_signal_selection"):
            ledger.record(s, InvocationLedger.OUTCOME_SKIPPED, note="No candidates")
        raise ValueError("Research Engine produced no candidates")

    log.info("[R2] Scoring %d candidates", len(candidates))
    scored = score_candidates(candidates, llm_provider=llm_provider)
    ledger.record("research_score", InvocationLedger.OUTCOME_PASSED, {
        "scored_count": len(scored), "filesystem_writes": "none",
    })
    (run_dir / "research_scored.json").write_text(
        json.dumps(scored, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    log.info("[R3] Enriching %d candidates", len(scored))
    enriched = enrich_candidates(scored, llm_provider=llm_provider)
    ledger.record("research_enrich", InvocationLedger.OUTCOME_PASSED, {
        "enriched_count": len(enriched), "filesystem_writes": "none",
    })
    (run_dir / "research_enriched.json").write_text(
        json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    log.info("[R4] Adding angles")
    with_angles = add_angles(enriched, llm_provider=llm_provider)
    ledger.record("research_angles", InvocationLedger.OUTCOME_PASSED, {
        "count": len(with_angles), "filesystem_writes": "none",
    })
    (run_dir / "research_angles.json").write_text(
        json.dumps(with_angles, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Apply schema defaults and select first admitted signal
    final_signals = [dict(SCHEMA_DEFAULTS, **sig) for sig in with_angles]
    selected = next(
        (s for s in final_signals
         if ResearchContext.from_dict(s).admission_status in ("admitted", "force_override")),
        None,
    )
    if selected is None:
        ledger.record("research_signal_selection", InvocationLedger.OUTCOME_FAILED,
                      {"candidates": len(final_signals), "admitted": 0})
        raise ValueError("No signal passed admission gate")

    rc = ResearchContext.from_dict(selected)
    ledger.record("research_signal_selection", InvocationLedger.OUTCOME_PASSED, {
        "signal_id":      selected["SIGNAL_ID"],
        "article_ready":  rc.article_ready,
        "admission":      rc.admission_status,
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
    raise FileNotFoundError(f"Signal {signal_id!r} not found")


def _create_synthetic_signal(topic: str) -> dict:
    """Stub signal. Uses ARTICLE_READY=true explicitly (Option A lifecycle)."""
    return {
        "SIGNAL_ID":               f"synth-{uuid4().hex[:12]}",
        "_synthetic":              True,
        "_synthetic_note":         "NOT from Research Engine",
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
        "NOTES":                   "Synthetic signal",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
        "ARTICLE_READINESS_SCORE": "7",
        "CHANNEL_FIT_SCORE":       "7",
        "SIGNAL_STRENGTH":         "medium",
        "DISCUSSION_POTENTIAL":    "medium",
        "score_reason":            "synthetic",
        "CORE_TENSION":            f"Tension for: {topic}",
        "BUSINESS_LESSON":         f"Lesson from: {topic}",
        "WHY_THIS_CASE_IS_INTERESTING": f"Interesting: {topic}",
        "WHY_IT_MATTERS_TO_BUSINESS":   f"Matters: {topic}",
        "BUSINESS_RESPONSES_OBSERVED":  "",
        "PROBLEM_FACED":           f"Problem: {topic}",
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
        "ARTICLE_READY":           "true",  # canonical; no alias needed (Option A)
    }


# ---------------------------------------------------------------------------
# Decision Lens recording (no mock.patch)
# ---------------------------------------------------------------------------

def _make_decision_lens_recorder(run_dir: Path, ledger: InvocationLedger) -> tuple[Callable, dict]:
    from src.editorial.decision_lens_lite import generate_decision_lens as _real_dl

    dl_record: dict = {"called": False, "input": None, "output": None}

    def _recording_wrapper(signal: dict) -> dict:
        dl_record["called"] = True
        dl_record["input"]  = signal
        result = _real_dl(signal)
        dl_record["output"] = result
        return result

    return _recording_wrapper, dl_record


def _write_decision_lens_artifacts(run_dir: Path, ledger: InvocationLedger, dl_record: dict) -> None:
    if dl_record["called"]:
        (run_dir / "decision_lens_input.json").write_text(
            json.dumps(dl_record["input"], indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        (run_dir / "decision_lens_output.json").write_text(
            json.dumps(dl_record["output"], indent=2, ensure_ascii=False), encoding="utf-8",
        )
        ledger.record("decision_lens", InvocationLedger.OUTCOME_PASSED, {
            "injection_method": "decision_lens_fn parameter in generate_article()",
            "output_keys":      list((dl_record["output"] or {}).keys()),
        })
    else:
        ledger.record("decision_lens", InvocationLedger.OUTCOME_NOT_EXECUTED,
                      note="generate_decision_lens not called by generate_article")


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

def _run_image_generation(
    signal: dict,
    visual_brief,
    run_dir: Path,
    ledger: InvocationLedger,
    policy: ControlledRunPolicy,
    image_provider=None,
) -> dict:
    """
    Call _generate_base_image() (or injected image_provider).

    policy.check("image_generation") fires BEFORE any provider call.
    This is SEPARATE from:
    - permanent_storage (Cloudinary/image-library write — always blocked)
    - cloudinary_upload (Cloudinary CDN — always blocked)
    Both permanent_storage and cloudinary_upload were checked in preflight.
    """
    from src.publishing.image_pipeline import (
        _generate_base_image, composite_for_platform, CARD_TYPES,
    )

    # image_generation policy check — before any provider call
    policy.check("image_generation", adapter="_generate_base_image")

    visual_family   = visual_brief.visual_family
    image_prompt    = visual_brief.image_prompt
    negative_prompt = visual_brief.negative_prompt
    is_card         = visual_family in CARD_TYPES

    if is_card:
        method, base_bytes = "quote_card", None
    else:
        base_bytes, method = _generate_base_image(
            image_prompt, visual_family, negative_prompt,
            log=log.info,
            image_provider=image_provider,
        )

    local_path = "(quote_card)"
    if base_bytes is not None:
        img_path = run_dir / "generated_image_blog.png"
        sized    = composite_for_platform(base_bytes, visual_brief.hook_text, "blog")
        sized.save(str(img_path), "PNG", optimize=True)
        local_path = str(img_path)

    record = {
        "generated":              True,
        "method":                 method,
        "visual_family":          visual_family,
        "local_path":             local_path,
        "provider":               type(image_provider).__name__ if image_provider else "default",
        "prompt_used":            image_prompt[:200],
        "cloudinary_upload":      "blocked — permanent_storage_allowed=False (preflight check)",
        "image_library_updated":  False,
        "image_reuse":            False,
    }
    (run_dir / "image_generation_result.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    ledger.record("image_generation", InvocationLedger.OUTCOME_PASSED, {
        "method":          method,
        "provider":        record["provider"],
        "prompt_present":  bool(image_prompt),
        "cloudinary":      "not_called (blocked in preflight)",
        "image_library":   "not_read (image_reuse blocked in preflight)",
        "local_path":      local_path,
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
    return {
        ch: {"body": (platforms.get(channel_map[ch][0], {}).get(channel_map[ch][1], "")
                      if ch in channel_map and isinstance(platforms.get(channel_map[ch][0]), dict)
                      else ""), "channel": ch}
        for ch in channels
    }


def _git_sha() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_controlled(
    args: argparse.Namespace,
    *,
    llm_provider=None,
    feed_provider=None,
    image_provider=None,
) -> int:
    """
    Orchestrate the controlled run.

    Args:
        args:           Parsed CLI arguments.
        llm_provider:   Optional LLMProvider (None = DefaultLLMProvider in research scripts).
        feed_provider:  Optional FeedProvider (None = DefaultFeedProvider).
        image_provider: Optional ImageProvider (None = _generate_base_image default logic).
    """
    # Defense-in-depth (set here, not module-level, to avoid pytest pollution)
    os.environ["NB_CONTROLLED_RUN"] = "1"

    run_id     = uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)
    timestamp  = started_at.strftime("%Y%m%d_%H%M%S")
    channels   = [c.strip() for c in args.channels.split(",") if c.strip()]
    ledger     = InvocationLedger()

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
        "mode":                     args.mode,
        "synthetic":                is_synthetic,
        "synthetic_note": (
            "synthetic-signal mode: NOT from Research Engine. "
            "NOT a proof of the research-to-editorial chain."
            if is_synthetic else None
        ),
        "publication_disabled":     True,
        "external_writes_disabled": True,
        "image_generation":         args.image_generation,
        "input_topic":              args.topic,
        "brand":                    args.brand,
        "channels":                 channels,
        "nb_controlled_run_env":    os.environ.get("NB_CONTROLLED_RUN", ""),
        "providers": {
            "llm":   type(llm_provider).__name__ if llm_provider else "DefaultLLMProvider",
            "feed":  type(feed_provider).__name__ if feed_provider else "DefaultFeedProvider",
            "image": type(image_provider).__name__ if image_provider else "default",
        },
        "source_identifiers":  [],
        "artifact_paths":      {},
        "status":              "running",
        "failure_stage":       None,
        "external_uncontrolled_properties": [
            "llm_provider_cache — provider-side prompt caching cannot be disabled by client"
        ],
        "policy_enforcement": {
            "primary":        "ControlledRunPolicy (DI, 9 operations checked)",
            "secondary":      "NB_CONTROLLED_RUN=1 env-var (defense-in-depth)",
            "template_method":"BasePublisher.publish() non-abstract, **kwargs",
            "preflight_audit":"8 blocked capabilities checked before any I/O → AuditEntry",
            "lifecycle":      "Option A: ARTICLE_READY canonical only (no alias)",
        },
    }

    def _save_manifest():
        (run_dir / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    _save_manifest()
    failure_stage = None

    try:
        # Stage 0: Preflight — 8 blocked ops → AuditEntry
        failure_stage = "preflight_capability_audit"
        _run_preflight_capability_audit(policy, ledger)

        # Stage 1: Signal acquisition
        failure_stage = "signal_acquisition"
        if args.mode == "full-e2e":
            signal = _run_research_engine(args.topic, run_dir, ledger,
                                          llm_provider=llm_provider,
                                          feed_provider=feed_provider)
            manifest["source_identifiers"] = [
                signal.get("SIGNAL_ID", ""),
                signal.get("SOURCE_URL", ""),
            ]
        elif args.mode == "existing-signal":
            signal = _load_existing_signal(args.signal_id)
            ledger.record("signal_acquisition", InvocationLedger.OUTCOME_PASSED,
                          {"mode": "existing-signal", "signal_id": signal.get("SIGNAL_ID")})
            manifest["source_identifiers"] = [signal.get("SIGNAL_ID", "")]
        else:
            signal = _create_synthetic_signal(args.topic)
            ledger.record("signal_acquisition", InvocationLedger.OUTCOME_PASSED,
                          {"mode": "synthetic-signal", "signal_id": signal["SIGNAL_ID"],
                           "article_ready_explicit": True})
            manifest["source_identifiers"] = [signal["SIGNAL_ID"]]

        # Stage 2: ResearchContext preflight
        failure_stage = "research_context"
        rc = ResearchContext.from_dict(signal)
        if not rc.article_ready and not rc.force_override:
            raise ValueError(
                f"Signal {signal.get('SIGNAL_ID')!r} blocked — "
                f"article_ready={rc.article_ready}"
            )
        ledger.record("research_context", InvocationLedger.OUTCOME_PASSED, {
            "signal_id":       rc.signal_id,
            "article_ready":   rc.article_ready,
            "admission_status": rc.admission_status,
        })
        (run_dir / "research_context.json").write_text(
            json.dumps(rc.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Stage 3: EditorialContext
        failure_stage = "editorial_context"
        editorial_package = {
            "SIGNAL_ID": signal.get("SIGNAL_ID"),
            "content":   {},
            "images":    {"platform_images": {}},
        }
        editorial_ctx = rc.to_editorial(editorial_package)
        ledger.record("editorial_context", InvocationLedger.OUTCOME_PASSED, {
            "signal_id":       editorial_ctx.signal_id,
            "admission_status": editorial_ctx.admission_status,
        })
        (run_dir / "editorial_context.json").write_text(
            json.dumps(editorial_ctx.to_legacy_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Stage 4: Article generation + DL recording via DI
        failure_stage = "article_generation"
        from src.editorial.pipeline import generate_article, ArticleGenerationError

        dl_recording_fn, dl_record = _make_decision_lens_recorder(run_dir, ledger)
        try:
            article_result = generate_article(
                editorial_ctx.to_legacy_dict(),
                cta_mode="none",
                strategy_context=None,
                decision_lens_fn=dl_recording_fn,
            )
        except ArticleGenerationError as exc:
            raise ValueError(f"Article generation failed at {exc.stage!r}: {exc.original}") from exc

        _write_decision_lens_artifacts(run_dir, ledger, dl_record)
        ledger.record("article_generation", InvocationLedger.OUTCOME_PASSED, {
            "dl_injection":       "decision_lens_fn parameter (no mock.patch)",
            "platforms_produced": list(article_result.get("platforms", {}).keys()),
        })
        (run_dir / "generated_article.json").write_text(
            json.dumps(article_result, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Stage 5: Platform drafts
        failure_stage = "platform_drafts"
        platform_drafts = _build_platform_drafts(article_result, channels)
        (run_dir / "platform_drafts.json").write_text(
            json.dumps(platform_drafts, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        ledger.record("platform_drafts", InvocationLedger.OUTCOME_PASSED,
                      {"channels": channels, "produced": list(platform_drafts.keys())})

        # Stage 6: Visual brief (channel-aware, shared production component)
        failure_stage = "visual_spec"
        from src.publishing.image_pipeline import load_registry
        registry = load_registry()
        visual_brief = build_visual_brief(
            signal                = signal,
            article_result        = article_result,
            brand_name            = args.brand,
            content_goal          = "challenge",
            registry              = registry,
            log                   = log.info,
            policy_exclusion_tags = CR_POLICY_EXCLUSIONS,
            channels              = channels,
        )
        (run_dir / "visual_spec.json").write_text(
            json.dumps(visual_brief.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        ledger.record("visual_spec", InvocationLedger.OUTCOME_PASSED, {
            "visual_family":  visual_brief.visual_family,
            "channel_specs":  list(visual_brief.channel_specs.keys()),
            "policy_exclusions_set": bool(visual_brief.policy_exclusions),
        })

        # Stage 7: Image generation (or skip)
        failure_stage = "image_generation"
        if args.image_generation == "enabled":
            _run_image_generation(signal, visual_brief, run_dir, ledger, policy,
                                  image_provider=image_provider)
        else:
            (run_dir / "image_generation_skipped.json").write_text(
                json.dumps({"skipped": True, "reason": "--image-generation disabled"},
                           indent=2), encoding="utf-8",
            )
            ledger.record("image_generation", InvocationLedger.OUTCOME_SKIPPED,
                          {"reason": "--image-generation disabled"})

        # Stage 8: Validation report
        failure_stage = "validation_report"
        validation_report = ledger.build_validation_report(policy)
        (run_dir / "validation_report.json").write_text(
            json.dumps(validation_report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if not validation_report["all_mandatory_passed"]:
            failed = [k for k, v in validation_report["checks"].items()
                      if v not in (InvocationLedger.OUTCOME_PASSED,
                                   InvocationLedger.OUTCOME_SKIPPED)]
            raise ValueError(f"Mandatory stages not passed: {failed}")

    except (PolicyViolation, PolicyRequiredError) as exc:
        log.error("POLICY VIOLATION at stage %r: %s", failure_stage, exc)
        manifest.update(status="failed", failure_stage=failure_stage,
                        failure_error=str(exc), failure_type=type(exc).__name__,
                        completed_at_utc=datetime.now(timezone.utc).isoformat())
        _save_manifest()
        return 1

    except Exception as exc:
        log.error("Controlled run FAILED at stage %r: %s", failure_stage, exc)
        manifest.update(status="failed", failure_stage=failure_stage,
                        failure_error=str(exc),
                        completed_at_utc=datetime.now(timezone.utc).isoformat())
        _save_manifest()
        return 1

    final_status = validation_report.get("overall_status", "failed")
    manifest.update(status=final_status, failure_stage=None,
                    completed_at_utc=datetime.now(timezone.utc).isoformat())
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
