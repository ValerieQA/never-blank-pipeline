"""
Dry-run runner for Phase 0, Phase 1, and Phase 2.

Validates the foundation and memory layer without making API calls or publishing.
Optionally tests the OpenAI client if NB_OPENAI_API_KEY is present.

Usage:
    python scripts/dry_run.py              # structure + config + memory only
    python scripts/dry_run.py --test-llm  # also tests OpenAI connection
"""
import sys
import os
import json
import argparse
from pathlib import Path

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
    load_published, load_observation_registry, load_portfolio,
    load_voice_examples, load_embeddings, load_theme_registry,
    get_embedding, cosine_similarity, is_duplicate,
    save_embedding, save_published, update_portfolio,
    get_diversity_adjustment, is_voice_drifting, get_theme_saturation,
    register_theme, _is_mock_mode,
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
    print("║       Phase 0 + Phase 1 + Phase 2                ║")
    print("╚══════════════════════════════════════════════════╝")

    mode = "MOCK (no API key)" if _is_mock_mode() else "LIVE (OpenAI)"
    print(f"\n  Embedding mode: {mode}")

    # ── 1. Environment ──────────────────────────────────────────────────────────
    section("1. Environment Variables")
    result = validate(phase="phase0", strict=False)
    for var in result["present"]:
        check(var, True, "set")
    for var in result["missing"]:
        check(var, False, "MISSING (expected at this stage)")
    check("Phase 0 env complete", result["ok"])

    # ── 2. Config files ─────────────────────────────────────────────────────────
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
            check(name, True, f"{len(data)} top-level keys")
        except Exception as exc:
            check(name, False, str(exc))
            config_ok = False

    # ── 3. Prompt contracts ─────────────────────────────────────────────────────
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
            has_contract = bool(p.get("input_schema") and p.get("output_schema"))
            check(name, has_contract,
                  f"status={p.get('status','?')}, contract={'yes' if has_contract else 'NO'}")
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
            check(name, True, "correctly marked not_needed")
        except Exception as exc:
            check(name, False, str(exc))

    # ── 4. Memory files ─────────────────────────────────────────────────────────
    section("4. Memory Files — Schemas")
    memory_checks = [
        ("published.json",            load_published,            list),
        ("observation_registry.json", load_observation_registry, list),
        ("portfolio.json",            load_portfolio,            dict),
        ("voice_examples.json",       load_voice_examples,       list),
        ("embeddings.json",           load_embeddings,           list),
        ("theme_registry.json",       load_theme_registry,       list),
    ]
    for name, loader, expected_type in memory_checks:
        try:
            data = loader()
            ok = isinstance(data, expected_type)
            check(f"memory/{name}", ok, f"{expected_type.__name__}, len={len(data) if hasattr(data,'__len__') else 'n/a'}")
        except Exception as exc:
            check(f"memory/{name}", False, str(exc))

    # ── 5. Topic queue ──────────────────────────────────────────────────────────
    section("5. Manual Topic Queue")
    topic = None
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

    # ── 6. Semantic Deduplication ───────────────────────────────────────────────
    section("6. Semantic Deduplication (mock embeddings)")

    text_a = "Why the busiest businesses look closed — The visibility gap that costs clients"
    text_b = "How founders accidentally hide their expertise from the market"
    text_c = "Why the busiest businesses look closed — The visibility gap that costs clients"  # exact copy

    vec_a = get_embedding(text_a)
    check("get_embedding() returns vector", len(vec_a) > 0, f"dim={len(vec_a)}")
    check("vector is normalized", abs(sum(v*v for v in vec_a) - 1.0) < 0.01, "unit length ✓")

    sim_ab = cosine_similarity(vec_a, get_embedding(text_b))
    sim_ac = cosine_similarity(vec_a, get_embedding(text_c))
    check("different texts → low similarity", sim_ab < 0.95, f"sim={sim_ab:.4f}")
    check("identical texts → high similarity", sim_ac > 0.99, f"sim={sim_ac:.4f}")

    # save text_a to embeddings store, then check text_c is flagged as duplicate
    save_embedding(text_a, vec_a, slug="why-busiest-businesses-look-closed")
    is_dup_c, score_c, match_c = is_duplicate(text_c)
    check("identical text detected as duplicate", is_dup_c,
          f"sim={score_c:.4f}, matched={match_c!r}")

    is_dup_b, score_b, _ = is_duplicate(text_b)
    check("different text NOT flagged as duplicate", not is_dup_b,
          f"sim={score_b:.4f} (threshold=0.85)")

    # ── 7. Portfolio Update ─────────────────────────────────────────────────────
    section("7. Portfolio Update (simulated publication)")

    p_before = load_portfolio()
    total_before = p_before.get("total_published", 0)

    update_portfolio(
        observation_type="pattern",
        content_goal="challenge",
        tags=["visibility", "founder"],
        source_category="manual",
        voice_score=0.84,
        published_date="2026-06-19",
    )

    p_after = load_portfolio()
    total_after = p_after.get("total_published", 0)
    check("total_published incremented", total_after == total_before + 1,
          f"{total_before} → {total_after}")
    check("observation_type_counts updated",
          p_after["observation_type_counts"].get("pattern", 0) > 0,
          str(p_after["observation_type_counts"]))
    check("voice_scores_rolling updated",
          len(p_after["voice_scores_rolling"]) > 0,
          str(p_after["voice_scores_rolling"]))
    check("last_published_date set",
          p_after.get("last_published_date") == "2026-06-19",
          p_after.get("last_published_date", ""))

    # ── 8. Diversity Scoring ────────────────────────────────────────────────────
    section("8. Diversity Scoring")

    adj_pattern_challenge = get_diversity_adjustment("pattern", "challenge")
    adj_gap_educate       = get_diversity_adjustment("gap", "educate")
    check("diversity_adjustment returns float", isinstance(adj_pattern_challenge, float),
          f"pattern/challenge={adj_pattern_challenge:+.4f}")
    check("underrepresented type gets positive boost",
          adj_gap_educate >= 0,
          f"gap/educate={adj_gap_educate:+.4f} (not yet used)")

    drifting, avg_score = is_voice_drifting()
    check("voice drift check runs", True,
          f"drifting={drifting}, avg={avg_score}")

    # ── 9. Theme Registry ───────────────────────────────────────────────────────
    section("9. Theme Registry")

    theme_id = register_theme(
        text="Why the busiest businesses look closed",
        slug="why-busiest-businesses-look-closed",
        published_date="2026-06-19",
    )
    check("theme registered", bool(theme_id), f"theme_id={theme_id[:8]}...")

    saturation = get_theme_saturation("Why busy founders seem invisible to clients")
    check("theme saturation score returned", isinstance(saturation, float),
          f"saturation={saturation:.4f} (mock embeddings → not semantically meaningful)")

    new_sat = get_theme_saturation("Pricing strategy for B2B SaaS companies")
    check("different theme → lower saturation", new_sat < saturation,
          f"saturation={new_sat:.4f} (different topic)")

    registry = load_theme_registry()
    check("theme_registry.json has entry", len(registry) > 0,
          f"{len(registry)} cluster(s)")

    # ── 10. Optional: LLM connection ────────────────────────────────────────────
    if test_llm:
        section("10. OpenAI Connection Test")
        if _is_mock_mode():
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
                from src.utils.llm_client import embed as oai_embed
                vector = oai_embed("Never Blank test embedding")
                check("embed() response", len(vector) > 0, f"dim={len(vector)}")
            except Exception as exc:
                check("embed() response", False, str(exc))
    else:
        section("10. OpenAI Connection Test")
        print("  (skipped — run with --test-llm to include)")

    # ── Summary ─────────────────────────────────────────────────────────────────
    section("Summary")

    print("  Phase 2 — Memory files created/confirmed:")
    created = [
        "data/memory/published.json          — run records with per-channel results",
        "data/memory/embeddings.json         — text + vector + slug + model metadata",
        "data/memory/observation_registry.json — observations with cooldown tracking",
        "data/memory/portfolio.json          — running distribution counters",
        "data/memory/theme_registry.json     — semantic clusters with centroids",
        "data/memory/voice_examples.json     — voice reference samples",
    ]
    for f in created:
        print(f"    • {f}")

    print("\n  Phase 2 — Modules updated/created:")
    modules = [
        "src/internal/memory.py  — full rewrite: schemas, dedup, portfolio,",
        "                           theme registry, diversity scoring, mock embeddings",
    ]
    for m in modules:
        print(f"    • {m}")

    print("\n  Phase 3 — Implemented:")
    stubbed = [
        "src/internal/strategy.py       — ContentBrief builder ✓",
        "src/content/generator.py       — 6-platform content generation ✓",
        "config/prompts/ (9 prompts)    — real content, status=ready ✓",
        "scripts/generate.py            — full content package runner ✓",
        "data/drafts/                   — output folder ✓",
    ]
    for f in stubbed:
        print(f"    • {f}")

    print("\n  Still stubbed (Phase 4+):")
    stubbed = [
        "src/quality/                   — QC gate, voice, factuality (Phase 4)",
        "src/publishing/                — all 6 channel publishers (Phase 5)",
        "src/reporting/                 — Google Sheets reporter (Phase 8)",
        "src/internal/intelligence_engine.py — signal collection (Phase 7)",
    ]
    for s in stubbed:
        print(f"    • {s}")

    print("\n  Env vars required for this stage:")
    for v, note in [
        ("NB_OPENAI_API_KEY",        "optional for Phase 2 — mock used if absent"),
        ("NB_OPENAI_CHAT_MODEL",     "required for Phase 3+"),
        ("NB_OPENAI_EMBEDDING_MODEL","required for Phase 3+"),
        ("NB_OPENAI_TEMPERATURE",    "required for Phase 3+"),
    ]:
        status = "✓ set" if os.environ.get(v) else "○ not set"
        print(f"    • {v} — {status}  ({note})")

    all_ok = config_ok and prompts_ok
    print(f"\n  Phase 0/1/2 foundation: {'READY' if all_ok else 'NEEDS ATTENTION'}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-llm", action="store_true",
                        help="Test OpenAI connection (requires NB_OPENAI_API_KEY)")
    args = parser.parse_args()
    run(test_llm=args.test_llm)
