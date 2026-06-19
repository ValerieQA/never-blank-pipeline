"""
Dry-run runner for Phase 0 and Phase 1.

Validates the foundation without making any API calls or publishing anything.
Optionally tests the OpenAI client if NB_OPENAI_API_KEY is present.

Usage:
    python scripts/dry_run.py              # structure + config only
    python scripts/dry_run.py --test-llm  # also tests OpenAI connection
"""
import sys
import os
import json
import argparse
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.utils.logger import get_logger
from src.utils.env_validator import validate
from src.utils.config_loader import (
    load_brand, load_strategy, load_quality, load_platforms,
    load_intelligence, load_prompt,
)
from src.internal.memory import (
    load_published, load_observations, load_portfolio, load_voice_examples,
)
from src.internal.topic_prioritizer import get_next_topic

log = get_logger("dry_run")

SEP = "─" * 60


def section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def check(label: str, ok: bool, detail: str = "") -> None:
    icon = "✓" if ok else "✗"
    line = f"  {icon}  {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)


def run(test_llm: bool = False) -> None:
    print("\n╔══════════════════════════════════════════════════╗")
    print("║       Never Blank Pipeline — Dry Run             ║")
    print("║       Phase 0 + Phase 1                          ║")
    print("╚══════════════════════════════════════════════════╝")

    # ── 1. Environment ─────────────────────────────────────────────────────────
    section("1. Environment Variables")
    result = validate(phase="phase0", strict=False)
    for var in result["present"]:
        check(var, True, "set")
    for var in result["missing"]:
        check(var, False, "MISSING")

    phase0_ok = result["ok"]
    check("Phase 0 env complete", phase0_ok)

    # ── 2. Config files ────────────────────────────────────────────────────────
    section("2. Config Files")
    configs = {
        "brand.yaml": load_brand,
        "strategy.yaml": load_strategy,
        "quality.yaml": load_quality,
        "platforms.yaml": load_platforms,
        "intelligence.yaml": load_intelligence,
    }
    config_ok = True
    for name, loader in configs.items():
        try:
            data = loader()
            check(name, True, f"{len(data)} keys")
        except Exception as exc:
            check(name, False, str(exc))
            config_ok = False

    # ── 3. Prompt contracts ────────────────────────────────────────────────────
    section("3. Prompt Contracts")
    prompt_names = [
        "observation_discovery", "observation_score", "topic_extract",
        "blog_post", "linkedin_post", "facebook_post", "instagram_caption",
        "threads_post", "telegram_post", "qc_factuality", "qc_voice",
        "rewrite_with_feedback",
    ]
    not_needed = ["image_hook", "topic_score", "strategy_brief"]
    prompts_ok = True
    for name in prompt_names:
        try:
            p = load_prompt(name)
            status = p.get("status", "unknown")
            has_contract = bool(p.get("input_schema") and p.get("output_schema"))
            check(name, has_contract, f"status={status}, contract={'yes' if has_contract else 'NO'}")
            if not has_contract:
                prompts_ok = False
        except Exception as exc:
            check(name, False, str(exc))
            prompts_ok = False
    for name in not_needed:
        try:
            load_prompt(name)
            check(name, False, "should raise ValueError for not_needed")
        except ValueError:
            check(name, True, "correctly marked not_needed — no LLM call")
        except Exception as exc:
            check(name, False, str(exc))

    # ── 4. Memory files ────────────────────────────────────────────────────────
    section("4. Memory Files")
    memory_files = {
        "published": load_published,
        "observations": load_observations,
        "portfolio": load_portfolio,
        "voice_examples": load_voice_examples,
    }
    for name, loader in memory_files.items():
        try:
            data = loader()
            check(f"memory/{name}.json", True, type(data).__name__)
        except Exception as exc:
            check(f"memory/{name}.json", False, str(exc))

    # ── 5. Topic queue ─────────────────────────────────────────────────────────
    section("5. Manual Topic Queue")
    try:
        topic = get_next_topic()
        if topic:
            check("topics_manual.csv readable", True, f"{topic.title[:50]!r}")
            check("TopicCandidate built", True,
                  f"source={topic.source}, goal={topic.content_goal}")
        else:
            check("topics_manual.csv readable", True, "file exists, queue empty")
    except Exception as exc:
        check("topics_manual.csv", False, str(exc))

    # ── 6. Optional: LLM connection ────────────────────────────────────────────
    if test_llm:
        section("6. OpenAI Connection Test")
        if not os.environ.get("NB_OPENAI_API_KEY"):
            check("OpenAI ping", False, "NB_OPENAI_API_KEY not set — skipped")
        else:
            try:
                from src.utils.llm_client import chat
                response = chat(
                    system="You are a test assistant.",
                    user="Reply with exactly: OK",
                )
                check("chat() response", "OK" in response, response.strip()[:40])
            except Exception as exc:
                check("chat() response", False, str(exc))

            try:
                from src.utils.llm_client import embed
                vector = embed("Never Blank test embedding")
                check("embed() response", len(vector) > 0, f"dim={len(vector)}")
            except Exception as exc:
                check("embed() response", False, str(exc))
    else:
        section("6. OpenAI Connection Test")
        print("  (skipped — run with --test-llm to include)")

    # ── Summary ────────────────────────────────────────────────────────────────
    section("Summary")
    print("  Files created:")
    created = [
        "src/models.py", "src/utils/logger.py", "src/utils/env_validator.py",
        "src/utils/config_loader.py", "src/utils/llm_client.py",
        "src/utils/google_sheets.py (stub)",
        "src/internal/memory.py", "src/internal/topic_prioritizer.py",
        "config/brand.yaml", "config/strategy.yaml", "config/quality.yaml",
        "config/platforms.yaml", "config/intelligence.yaml",
        "config/prompts/ (12 contracts + 3 not_needed stubs)",
        "data/memory/ (5 JSON files)",
        "topics_manual.csv (1 example row)",
    ]
    for f in created:
        print(f"    • {f}")

    print("\n  Stubbed (not implemented yet):")
    stubbed = [
        "src/utils/google_sheets.py — Phase 8",
        "src/internal/intelligence_engine.py — Phase 7",
        "src/internal/observation_layer.py — Phase 7",
        "src/internal/topic_scorer.py — Phase 7",
        "src/internal/strategy.py — Phase 3",
        "src/content/generator.py — Phase 3",
        "src/quality/ — Phase 4",
        "src/publishing/ — Phase 5",
        "src/reporting/ — Phase 8",
    ]
    for f in stubbed:
        print(f"    • {f}")

    print("\n  Env vars required for this stage (Phase 0):")
    for v in ["NB_OPENAI_API_KEY", "NB_OPENAI_MODEL", "NB_OPENAI_EMBEDDING_MODEL"]:
        status = "✓ set" if os.environ.get(v) else "✗ missing"
        print(f"    • {v} — {status}")

    print(f"\n  Phase 0/1 foundation: {'READY' if config_ok and prompts_ok else 'NEEDS ATTENTION'}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-llm", action="store_true",
                        help="Test OpenAI connection (requires NB_OPENAI_API_KEY)")
    args = parser.parse_args()
    run(test_llm=args.test_llm)
