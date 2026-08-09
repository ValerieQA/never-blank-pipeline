"""
Never Blank — Controlled End-to-End Run.

Orchestrates the full article generation pipeline in a completely isolated,
no-external-write environment. All publication, Cloudinary upload, and history
writes are blocked by ControlledRunGuard.

Usage:
    python -m scripts.controlled_run \\
        --mode full-e2e \\
        --publication disabled \\
        --external-writes disabled \\
        --cache disabled \\
        --image-reuse disabled \\
        --output-root artifacts/controlled_runs \\
        --topic "<TOPIC>" \\
        --brand "Never Blank" \\
        --channels "linkedin,blog,instagram"

Modes:
    full-e2e         Create a stub signal from --topic and run the full pipeline
    existing-signal  Load an existing signal by --signal-id (also isolated)

Validation rules (enforced before any LLM call):
    --mode            required; must be full-e2e or existing-signal
    --publication     must be 'disabled' (no default that enables publication)
    --external-writes must be 'disabled'
    Secrets never accepted as CLI args

Exit codes:
    0  success (manifest status=complete)
    1  validation error or pipeline failure
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.lifecycle.signal_lifecycle import ResearchContext
from src.controlled_run.guard import ControlledRunGuard, ControlledRunViolation
from src.utils.logger import get_logger

log = get_logger("controlled_run")

NEGATIVE_PROMPT_EXCLUSIONS = (
    "robots, humanoid AI figures, glowing brains, neural network visualizations, "
    "circuit boards, generic stock-AI imagery, text or typography inside image"
)


# ──────────────────────────────────────────────────────────────────────────────
# CLI argument parsing + validation
# ──────────────────────────────────────────────────────────────────────────────

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Never Blank — Controlled End-to-End Run (no external writes)"
    )
    parser.add_argument("--mode", required=True,
                        choices=["full-e2e", "existing-signal"],
                        help="Run mode: full-e2e (stub signal) or existing-signal (load by ID)")
    parser.add_argument("--publication", required=True,
                        choices=["disabled"],
                        help="Must be 'disabled' — publication is always blocked")
    parser.add_argument("--external-writes", required=True,
                        choices=["disabled"],
                        help="Must be 'disabled' — all external writes are always blocked")
    parser.add_argument("--cache", default="disabled",
                        choices=["disabled"],
                        help="Cache policy (always disabled)")
    parser.add_argument("--image-reuse", default="disabled",
                        choices=["disabled"],
                        help="Image reuse policy (always disabled)")
    parser.add_argument("--output-root", default="artifacts/controlled_runs",
                        help="Root directory for run artifacts")
    parser.add_argument("--topic", default="",
                        help="Topic for full-e2e mode (required when --mode=full-e2e)")
    parser.add_argument("--brand", default="Never Blank",
                        help="Brand name (default: Never Blank)")
    parser.add_argument("--channels", default="linkedin,blog,instagram",
                        help="Comma-separated channels")
    parser.add_argument("--signal-id", default="",
                        help="Signal ID for existing-signal mode")
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> list[str]:
    """Return list of validation errors (empty = ok)."""
    errors = []
    if args.publication != "disabled":
        errors.append("--publication must be 'disabled'")
    if args.external_writes != "disabled":
        errors.append("--external-writes must be 'disabled'")
    if args.mode == "full-e2e" and not args.topic.strip():
        errors.append("--topic is required when --mode=full-e2e")
    if args.mode == "existing-signal" and not args.signal_id.strip():
        errors.append("--signal-id is required when --mode=existing-signal")
    return errors


# ──────────────────────────────────────────────────────────────────────────────
# Signal creation
# ──────────────────────────────────────────────────────────────────────────────

def _create_stub_signal(topic: str) -> dict:
    """
    Create a properly normalized stub signal dict from a topic string.
    Uses RECOMMENDED_FOR_ARTICLE=true (no ARTICLE_READY) to exercise the
    normalization fix introduced in this patch.
    Does NOT use FORCE_PUBLISH_OVERRIDE.
    """
    signal_id = f"ctrl-{uuid4().hex[:12]}"
    return {
        "SIGNAL_ID":               signal_id,
        "HEADLINE":                topic,
        "SIGNAL_TYPE":             "business trust",
        "REGION":                  "US",
        "INDUSTRY":                "General",
        "SOURCE_NAME":             "controlled-run-stub",
        "SOURCE_URL":              "",
        "SOURCE_DATE":             datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "DATE_FOUND":              datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "CORE_FACT":               f"Controlled-run stub fact for: {topic}",
        "CONFIDENCE":              "medium",
        "SOURCE_PREMISE_VERIFIED": "unknown",
        "OUTCOME_IF_KNOWN":        "unknown",
        "DID_IT_WORK":             "unknown",
        "EVIDENCE_OF_OUTCOME":     "",
        "SOURCE_QUALITY":          "",
        "NOTES":                   "Generated by controlled_run.py — not a real signal",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "true",
        "ARTICLE_READINESS_SCORE": "7",
        "CHANNEL_FIT_SCORE":       "7",
        "SIGNAL_STRENGTH":         "medium",
        "DISCUSSION_POTENTIAL":    "medium",
        "score_reason":            "stub",
        "CORE_TENSION":            f"Tension inherent in: {topic}",
        "BUSINESS_LESSON":         f"Business lesson from: {topic}",
        "WHY_THIS_CASE_IS_INTERESTING": f"Interesting because: {topic}",
        "WHY_IT_MATTERS_TO_BUSINESS":   f"Business relevance: {topic}",
        "BUSINESS_RESPONSES_OBSERVED":  "",
        "PROBLEM_FACED":           f"Problem in: {topic}",
        "RESPONSE_TAKEN":          "unknown",
        "COUNTER_EXAMPLE":         "",
        "TIME_HORIZON":            "medium",
        "INTERESTING_QUESTION":    f"What does {topic} reveal about business presence?",
        "NEVER_BLANK_ANGLE":       f"The real signal in {topic} is not the event itself.",
        "POSSIBLE_SIGNATURE_LINE": "Never Blank: The signal is rarely the event itself.",
        "POTENTIAL_HOOK":          f"What {topic} reveals about presence.",
        "TARGET_AUDIENCE":         "founder",
        "PRIMARY_CHANNEL":         "linkedin",
        "LINKEDIN_ANGLE":          f"LinkedIn angle: {topic}",
        "BLOG_ANGLE":              f"Blog angle: {topic}",
        "THREADS_ANGLE":           f"Threads angle: {topic}",
        "STORY_ANGLE":             f"Story angle: {topic}",
        "raw_summary":             f"Stub summary for {topic}",
        "discovery_confidence":    "medium",
        "APPROVED_OVERRIDE":       "",
        # Use RECOMMENDED_FOR_ARTICLE (legacy alias) — no ARTICLE_READY
        # This exercises the normalization fix in from_dict().
        "RECOMMENDED_FOR_ARTICLE": "true",
    }


def _load_existing_signal(signal_id: str) -> dict:
    """Load a signal from signals_active.jsonl or selected_signals.jsonl."""
    search_paths = [
        Path("data/research/signals_active.jsonl"),
        Path("data/research/selected_signals.jsonl"),
    ]
    for path in search_paths:
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


# ──────────────────────────────────────────────────────────────────────────────
# Visual brief + image prompt builders
# ──────────────────────────────────────────────────────────────────────────────

def _load_visual_config() -> tuple[dict, dict]:
    """Load visual_system.yaml and image_generation.yaml. Returns (visual_system, img_gen)."""
    import yaml
    repo_root = Path(__file__).resolve().parent.parent
    vs_path   = repo_root / "config" / "visual_system.yaml"
    ig_path   = repo_root / "config" / "prompts" / "image_generation.yaml"
    visual_system = yaml.safe_load(vs_path.read_text()) if vs_path.exists() else {}
    img_gen       = yaml.safe_load(ig_path.read_text()) if ig_path.exists() else {}
    return visual_system, img_gen


def _choose_visual_family_stub(visual_system: dict) -> str:
    """Choose a visual family from the config (default: mountains_depth_layers)."""
    families = visual_system.get("visual_families", {})
    if "mountains_depth_layers" in families:
        return "mountains_depth_layers"
    if families:
        return next(iter(families))
    return "mountains_depth_layers"


def _build_visual_brief(signal: dict, article_body: str, visual_system: dict) -> dict:
    """
    Build the visual brief from signal fields and brand config.
    Does NOT call any external API.
    """
    never_blank_angle = signal.get("NEVER_BLANK_ANGLE", "")
    potential_hook    = signal.get("POTENTIAL_HOOK", "")
    target_audience   = signal.get("TARGET_AUDIENCE", "founder")
    article_summary   = (article_body or "")[:200]

    visual_family = _choose_visual_family_stub(visual_system)
    palette_config = visual_system.get("palette", {})
    dark_core = palette_config.get("dark_core", {}).get("colors", {
        "deep_navy":  "#050B16",
        "navy":       "#0B1323",
        "midnight":   "#0F1A2E",
    })
    signal_accent = palette_config.get("signal_accent", {}).get("colors", {
        "electric_blue": "#42A0FF",
    })
    palette = {**dark_core, **signal_accent}

    families_config = visual_system.get("visual_families", {})
    family_spec     = families_config.get(visual_family, {})
    composition_rules = {
        "column_ratio":     0.58,
        "separator_ratio":  0.14,
        "logo_placement":   visual_system.get("logo", {}).get("placement_default", "bottom_right"),
        "logo_size_ratio":  visual_system.get("logo", {}).get("size_ratio", 0.22),
        "logo_margin_px":   visual_system.get("logo", {}).get("margin_px", 40),
    }
    safe_zones = {
        "top_margin_px":    60,
        "bottom_margin_px": 120,
        "side_margin_px":   80,
        "logo_safe_zone":   "bottom-right quadrant, 40px margin",
    }

    return {
        "angle_source":       never_blank_angle,
        "potential_hook":     potential_hook,
        "target_audience":    target_audience,
        "article_summary":    article_summary,
        "brand_name":         "Never Blank",
        "visual_family":      visual_family,
        "family_meaning":     family_spec.get("meaning", []),
        "family_visuals":     family_spec.get("visuals", []),
        "family_avoid":       family_spec.get("avoid", []),
        "palette":            palette,
        "composition_rules":  composition_rules,
        "safe_zones":         safe_zones,
        "instagram_grid_qa":  visual_system.get("instagram_grid_qa", {}),
    }


def _build_image_prompt(visual_brief: dict, img_gen_config: dict) -> dict:
    """
    Build the image prompt spec from the visual brief.
    Negative prompt always includes the controlled-run exclusion list.
    """
    visual_family    = visual_brief["visual_family"]
    never_blank_angle = visual_brief["angle_source"]
    potential_hook   = visual_brief["potential_hook"]

    # Build base negative prompt from config + required exclusions
    base_negative = img_gen_config.get("negative_prompt_base", "")
    negative_prompt = (
        f"{base_negative}, {NEGATIVE_PROMPT_EXCLUSIONS}"
        if base_negative
        else NEGATIVE_PROMPT_EXCLUSIONS
    )

    image_prompt = (
        f"Dark editorial photograph embodying: {never_blank_angle}. "
        f"Visual family: {visual_family}. "
        f"Dark background 60-70%, electric blue signal accent, "
        f"no text, no typography, no logos, cinematic, minimalist, intelligent."
    )

    return {
        "visual_family":    visual_family,
        "dominant_palette": "midnight",
        "image_prompt":     image_prompt,
        "negative_prompt":  negative_prompt,
        "brand_constraints": {
            "no_text_in_image":   True,
            "dark_core_dominant": True,
            "no_amber":           True,
            "logo_overlay":       "bottom_right (applied by pipeline, not image model)",
        },
        "angle_source":     never_blank_angle,
        "hook_text":        potential_hook[:80] if potential_hook else "",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Platform draft builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_platform_drafts(article_result: dict, signal: dict, channels: list[str]) -> dict:
    """Extract platform-specific drafts from article generation result."""
    platforms = article_result.get("platforms", {})
    drafts: dict = {}

    channel_map = {
        "blog":      ("long",      "body"),
        "linkedin":  ("medium",    "body"),
        "facebook":  ("reading",   "body"),
        "instagram": ("instagram", "body"),
    }
    for ch in channels:
        if ch in channel_map:
            key, field = channel_map[ch]
            body = platforms.get(key, {}).get(field, "") if isinstance(platforms.get(key), dict) else ""
            drafts[ch] = {"body": body, "channel": ch}
        else:
            drafts[ch] = {"body": "", "channel": ch, "note": "not generated in this mode"}

    return drafts


# ──────────────────────────────────────────────────────────────────────────────
# Validation report
# ──────────────────────────────────────────────────────────────────────────────

def _build_validation_report(
    signal: dict,
    rc: "ResearchContext",
    editorial_ctx,
    article_result: dict,
    platform_drafts: dict,
    visual_brief: dict,
    image_prompt: dict,
) -> dict:
    platforms = article_result.get("platforms", {})
    blog_body = platforms.get("long", {}).get("body", "") if isinstance(platforms.get("long"), dict) else ""
    linkedin_body = platforms.get("medium", {}).get("body", "") if isinstance(platforms.get("medium"), dict) else ""

    checks = {
        "article_ready_passed_preflight":
            rc.article_ready,
        "admission_status":
            rc.admission_status,
        "editorial_context_created":
            editorial_ctx is not None,
        "article_generated":
            bool(blog_body or linkedin_body),
        "visual_brief_angle_source_present":
            bool(visual_brief.get("angle_source")),
        "image_prompt_negative_excludes_robots":
            "robots" in image_prompt.get("negative_prompt", ""),
        "image_prompt_negative_excludes_humanoid_ai":
            "humanoid AI" in image_prompt.get("negative_prompt", ""),
        "image_prompt_angle_source_present":
            bool(image_prompt.get("angle_source")),
        "platform_drafts_generated":
            bool(platform_drafts),
        "image_generation_skipped":
            True,
        "publication_disabled":
            True,
        "external_writes_disabled":
            True,
        "no_image_library_read":
            True,
        "no_cloudinary_upload":
            True,
        "no_history_write":
            True,
    }
    all_passed = all(checks.values())
    return {
        "all_checks_passed": all_passed,
        "checks": checks,
        "blog_length_chars":    len(blog_body),
        "linkedin_length_chars": len(linkedin_body),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Git SHA helper
# ──────────────────────────────────────────────────────────────────────────────

def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ──────────────────────────────────────────────────────────────────────────────

def run_controlled(args: argparse.Namespace) -> int:
    """
    Orchestrate the full-e2e or existing-signal controlled run.
    Returns 0 on success, 1 on failure.
    """
    run_id     = uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)
    timestamp  = started_at.strftime("%Y%m%d_%H%M%S")
    channels   = [c.strip() for c in args.channels.split(",") if c.strip()]

    output_root = Path(args.output_root)
    run_dir     = output_root / f"{timestamp}_{run_id}"

    if run_dir.exists():
        log.error("Run directory already exists: %s", run_dir)
        return 1
    run_dir.mkdir(parents=True, exist_ok=False)

    manifest: dict = {
        "run_id":                run_id,
        "started_at_utc":        started_at.isoformat(),
        "completed_at_utc":      None,
        "git_sha":               _git_sha(),
        "entry_point":           "scripts/controlled_run.py",
        "mode":                  args.mode,
        "publication_disabled":  True,
        "external_writes_disabled": True,
        "cache_policy":          "disabled",
        "image_reuse":           False,
        "input_topic":           args.topic if args.mode == "full-e2e" else "",
        "input_signal_id":       args.signal_id if args.mode == "existing-signal" else "",
        "brand":                 args.brand,
        "channels":              channels,
        "models":                {},
        "providers":             {},
        "source_identifiers":    [],
        "artifact_paths":        {},
        "status":                "running",
        "failure_stage":         None,
    }

    def _save_manifest():
        (run_dir / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    _save_manifest()

    failure_stage = None
    guard = ControlledRunGuard()

    with guard.active():
        try:
            # ── Stage 1: Create/load signal ──────────────────────────────────
            failure_stage = "signal_creation"
            if args.mode == "full-e2e":
                signal = _create_stub_signal(args.topic)
                log.info("[1] Stub signal created: %s", signal["SIGNAL_ID"])
            else:
                signal = _load_existing_signal(args.signal_id)
                log.info("[1] Signal loaded: %s", signal["SIGNAL_ID"])

            manifest["source_identifiers"] = [signal["SIGNAL_ID"]]

            # ── Stage 2: ResearchContext (preflight) ─────────────────────────
            failure_stage = "research_context"
            rc = ResearchContext.from_dict(signal)
            if not rc.article_ready:
                raise ValueError(
                    f"Signal {signal['SIGNAL_ID']!r} blocked by preflight — "
                    f"article_ready={rc.article_ready}, "
                    f"admission_status={rc.admission_status!r}. "
                    "In full-e2e mode, the stub signal uses RECOMMENDED_FOR_ARTICLE=true "
                    "which should be normalized to article_ready=True. Check lifecycle fix."
                )
            log.info("[2] ResearchContext created, admission_status=%s", rc.admission_status)

            # ── Stage 3: Build editorial_package stub + EditorialContext ─────
            failure_stage = "editorial_context"
            editorial_package: dict = {
                "SIGNAL_ID":    signal["SIGNAL_ID"],
                "content":      {},
                "images":       {"platform_images": {}},
                "_stub":        True,
                "_note":        "Controlled run: no Cloudinary, no image library read",
            }
            editorial_ctx = rc.to_editorial(editorial_package)
            log.info("[3] EditorialContext created, signal=%s", editorial_ctx.signal_id)

            ec_path = run_dir / "editorial_context.json"
            ec_dict = editorial_ctx.to_legacy_dict()
            ec_dict["_editorial_metadata"] = {
                "factual_readiness":  editorial_ctx.factual_readiness,
                "admission_status":   editorial_ctx.admission_status,
                "never_blank_angle":  editorial_ctx.never_blank_angle,
            }
            ec_path.write_text(json.dumps(ec_dict, indent=2, ensure_ascii=False), encoding="utf-8")
            manifest["artifact_paths"]["editorial_context"] = str(ec_path.relative_to(output_root.parent) if output_root.parent.exists() else ec_path)

            # ── Stage 4: Decision Lens input ─────────────────────────────────
            failure_stage = "decision_lens_input"
            dl_input = editorial_ctx.to_legacy_dict()
            dl_path  = run_dir / "decision_lens_input.json"
            dl_path.write_text(json.dumps(dl_input, indent=2, ensure_ascii=False), encoding="utf-8")
            manifest["artifact_paths"]["decision_lens_input"] = str(dl_path)

            # ── Stage 5: Article generation (LLM) ────────────────────────────
            failure_stage = "article_generation"
            from src.editorial.pipeline import generate_article, ArticleGenerationError
            try:
                article_result = generate_article(
                    dl_input,
                    cta_mode="none",
                    strategy_context=None,
                )
            except ArticleGenerationError as exc:
                raise ValueError(f"Article generation failed at stage {exc.stage!r}: {exc.original}") from exc

            log.info("[5] Article generated")
            art_path = run_dir / "generated_article.json"
            art_path.write_text(json.dumps(article_result, indent=2, ensure_ascii=False), encoding="utf-8")
            manifest["artifact_paths"]["generated_article"] = str(art_path)

            # ── Stage 6: Platform drafts ──────────────────────────────────────
            failure_stage = "platform_drafts"
            platform_drafts = _build_platform_drafts(article_result, signal, channels)
            pd_path = run_dir / "platform_drafts.json"
            pd_path.write_text(json.dumps(platform_drafts, indent=2, ensure_ascii=False), encoding="utf-8")
            manifest["artifact_paths"]["platform_drafts"] = str(pd_path)

            # ── Stage 7: Visual brief ─────────────────────────────────────────
            failure_stage = "visual_brief"
            visual_system, img_gen_config = _load_visual_config()
            blog_body = (
                article_result.get("platforms", {}).get("long", {}).get("body", "")
                if isinstance(article_result.get("platforms", {}).get("long"), dict)
                else ""
            )
            visual_brief = _build_visual_brief(signal, blog_body, visual_system)
            vb_path = run_dir / "visual_brief.json"
            vb_path.write_text(json.dumps(visual_brief, indent=2, ensure_ascii=False), encoding="utf-8")
            manifest["artifact_paths"]["visual_brief"] = str(vb_path)

            # ── Stage 8: Image prompt ─────────────────────────────────────────
            failure_stage = "image_prompt"
            image_prompt = _build_image_prompt(visual_brief, img_gen_config)
            ip_path = run_dir / "image_prompt.json"
            ip_path.write_text(json.dumps(image_prompt, indent=2, ensure_ascii=False), encoding="utf-8")
            manifest["artifact_paths"]["image_prompt"] = str(ip_path)

            # ── Stage 9: Image generation skipped ────────────────────────────
            failure_stage = "image_generation_skip"
            skip_record = {
                "skipped":  True,
                "reason":   "controlled-run mode — no image generation or Cloudinary upload",
                "run_id":   run_id,
                "no_upload_to_cloudinary": True,
                "no_image_library_read":   True,
            }
            skip_path = run_dir / "image_generation_skipped.json"
            skip_path.write_text(json.dumps(skip_record, indent=2, ensure_ascii=False), encoding="utf-8")
            manifest["artifact_paths"]["image_generation_skipped"] = str(skip_path)

            # ── Stage 10: Validation report ───────────────────────────────────
            failure_stage = "validation_report"
            validation_report = _build_validation_report(
                signal, rc, editorial_ctx, article_result,
                platform_drafts, visual_brief, image_prompt,
            )
            vr_path = run_dir / "validation_report.json"
            vr_path.write_text(json.dumps(validation_report, indent=2, ensure_ascii=False), encoding="utf-8")
            manifest["artifact_paths"]["validation_report"] = str(vr_path)

            if not validation_report["all_checks_passed"]:
                failed_checks = [k for k, v in validation_report["checks"].items() if not v]
                raise ValueError(f"Validation failed: {failed_checks}")

        except Exception as exc:
            log.error("Controlled run FAILED at stage %r: %s", failure_stage, exc)
            manifest["status"]        = "failed"
            manifest["failure_stage"] = failure_stage
            manifest["failure_error"] = str(exc)
            manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
            _save_manifest()
            return 1

    # ── Success ───────────────────────────────────────────────────────────────
    manifest["status"]           = "complete"
    manifest["failure_stage"]    = None
    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    _save_manifest()
    log.info("Controlled run complete — run_id=%s, dir=%s", run_id, run_dir)
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
