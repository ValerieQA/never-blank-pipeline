"""
Never Blank Pipeline — Phase 3 Content Generator.

Generates a full content package for one topic and saves all outputs
to data/drafts/latest/ (and an archived copy in data/drafts/YYYY-MM-DD/).

Does NOT publish anything. No publisher APIs are called.

Usage:
    python scripts/generate.py
    python scripts/generate.py --topic-id 1     # force a specific manual topic
    python scripts/generate.py --dry             # validate setup without calling OpenAI
"""

import sys
import os
import json
import argparse
import dataclasses
from pathlib import Path
from datetime import date, datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.utils.logger import get_logger
from src.utils.env_validator import validate
from src.internal.topic_prioritizer import get_next_topic
from src.internal.strategy import build_content_brief
from src.internal.memory import is_duplicate, get_embedding, save_embedding
from src.content.generator import generate_content_package
from src.models import ContentBrief, ContentPackage

log = get_logger("generate")

DRAFTS_DIR   = Path(__file__).parent.parent / "data" / "drafts"
LATEST_DIR   = DRAFTS_DIR / "latest"
ARCHIVE_ROOT = DRAFTS_DIR / date.today().isoformat()


# ── Output helpers ─────────────────────────────────────────────────────────────

def _save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    log.debug("Saved: %s (%d chars)", path, len(content))


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if dataclasses.is_dataclass(data):
        data = _brief_to_dict(data) if isinstance(data, ContentBrief) else dataclasses.asdict(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.debug("Saved JSON: %s", path)


def _brief_to_dict(brief: ContentBrief) -> dict:
    return {
        "title":                brief.title,
        "angle":                brief.angle,
        "hook":                 brief.hook,
        "content_goal":         brief.content_goal.value,
        "observation_statement": brief.observation_statement,
        "observation_type":     brief.observation_type.value,
        "platforms":            brief.platforms,
        "tone_notes":           brief.tone_notes,
        "source_signals":       brief.source_signals,
        "wix_slug":             brief.wix_slug,
        "wix_category_id":      brief.wix_category_id,
        "wix_tags":             brief.wix_tags,
        "observation_id":       brief.observation_id,
        "manual_topic_id":      brief.manual_topic_id,
    }


def save_package(pkg: ContentPackage, output_dir: Path) -> dict[str, Path]:
    """Save all content package outputs to output_dir. Returns {label: path} map."""
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {}

    # ContentBrief JSON
    p = output_dir / "content_brief.json"
    _save_json(p, pkg.brief)
    files["content_brief"] = p

    # Blog post (Markdown)
    p = output_dir / "blog_post.md"
    blog_md = f"# {pkg.blog_title}\n\n{pkg.blog_body}"
    _save_text(p, blog_md)
    files["blog_post"] = p

    # Blog meta
    p = output_dir / "blog_meta.json"
    _save_json(p, {
        "title":             pkg.blog_title,
        "meta_description":  pkg.blog_meta_description,
        "hook_sentence":     pkg.blog_hook_sentence,
        "wix_slug":          pkg.brief.wix_slug,
        "wix_category_id":   pkg.brief.wix_category_id,
        "wix_tags":          pkg.brief.wix_tags,
    })
    files["blog_meta"] = p

    # LinkedIn
    p = output_dir / "linkedin.txt"
    _save_text(p, pkg.linkedin_text)
    files["linkedin"] = p

    # Instagram
    p = output_dir / "instagram.txt"
    hashtag_line = " ".join(f"#{h}" for h in pkg.instagram_hashtags)
    _save_text(p, pkg.instagram_caption + "\n\n" + hashtag_line)
    files["instagram"] = p

    # Facebook
    p = output_dir / "facebook.txt"
    _save_text(p, pkg.facebook_text)
    files["facebook"] = p

    # Threads (JSON sequence + readable text)
    p = output_dir / "threads.json"
    _save_json(p, {"sequence": pkg.threads_sequence})
    files["threads"] = p

    p = output_dir / "threads_readable.txt"
    readable = "\n\n---\n\n".join(
        f"[{i+1}/{len(pkg.threads_sequence)}]\n{post}"
        for i, post in enumerate(pkg.threads_sequence)
    )
    _save_text(p, readable)
    files["threads_readable"] = p

    # Telegram
    p = output_dir / "telegram.txt"
    _save_text(p, pkg.telegram_text)
    files["telegram"] = p

    # Image prompt
    p = output_dir / "image_prompt.txt"
    _save_text(p, pkg.image_prompt)
    files["image_prompt"] = p

    # Metadata
    p = output_dir / "metadata.json"
    _save_json(p, {
        "generated_at":     pkg.generated_at,
        "title":            pkg.blog_title,
        "wix_slug":         pkg.brief.wix_slug,
        "observation_type": pkg.brief.observation_type.value,
        "content_goal":     pkg.brief.content_goal.value,
        "platforms":        pkg.brief.platforms,
        "manual_topic_id":  pkg.brief.manual_topic_id,
    })
    files["metadata"] = p

    return files


# ── Main ───────────────────────────────────────────────────────────────────────

def run(topic_id: str | None = None, dry: bool = False) -> None:
    print("\n╔══════════════════════════════════════════════════╗")
    print("║       Never Blank Pipeline — Content Generator   ║")
    print("║       Phase 3                                    ║")
    print("╚══════════════════════════════════════════════════╝\n")

    # ── 1. Validate configuration ───────────────────────────────────────────────
    api_key_set = bool(os.environ.get("NB_OPENAI_API_KEY", "").strip())
    api_icon = "✓" if api_key_set else "✗"
    print(f"  {api_icon}  NB_OPENAI_API_KEY {'set' if api_key_set else 'NOT SET'}")
    print(f"  ✓  Model: {os.environ.get('NB_OPENAI_CHAT_MODEL', '(not set — default gpt-4o)')}")
    print(f"  ✓  Temperature: {os.environ.get('NB_OPENAI_TEMPERATURE', '0.7 (default)')}")
    print(f"  ✓  QC Temperature: {os.environ.get('NB_OPENAI_QC_TEMPERATURE', '0.2 (default)')}")

    if dry:
        topic = get_next_topic()
        if topic:
            brief = build_content_brief(topic)
            print(f"\n  [dry mode] Topic: {topic.title!r}")
            print(f"  [dry mode] Slug:  {brief.wix_slug}")
            print(f"  [dry mode] Tags:  {brief.wix_tags}")
        else:
            print("\n  [dry mode] No pending topic in manual queue")
        print("\n  [dry mode] Setup validated — no OpenAI calls made.")
        print(f"  [dry mode] Ready to generate: {'YES' if api_key_set else 'NO (API key missing)'}")
        return

    if not api_key_set:
        print("\n  ✗  NB_OPENAI_API_KEY is not set.")
        print("     Phase 3 requires OpenAI. Add it to your .env file:")
        print("       NB_OPENAI_API_KEY=sk-...")
        print()
        sys.exit(1)

    # ── 2. Get topic ────────────────────────────────────────────────────────────
    print("\n  Loading topic...")
    topic = get_next_topic()

    if topic is None:
        print("  ✗  No topic available. Add rows to topics_manual.csv with status=pending.")
        sys.exit(1)

    print(f"  ✓  Topic: {topic.title!r}")
    print(f"     Source: {topic.source} | Goal: {topic.content_goal.value}")
    print(f"     Observation: {topic.observation_statement[:80]}...")

    # ── 3. Build ContentBrief ───────────────────────────────────────────────────
    print("\n  Building ContentBrief...")
    brief = build_content_brief(topic)
    print(f"  ✓  Slug: {brief.wix_slug}")
    print(f"  ✓  Tags: {brief.wix_tags}")

    # ── 4. Deduplication check ──────────────────────────────────────────────────
    print("\n  Checking for semantic duplicates...")
    dedup_text = f"{brief.title} — {brief.angle}"
    is_dup, sim_score, matched_slug = is_duplicate(dedup_text)

    if is_dup:
        print(f"  ✗  Duplicate detected (similarity={sim_score:.4f}, matched={matched_slug!r})")
        print("     Add a different topic to topics_manual.csv or adjust the angle.")
        sys.exit(1)

    print(f"  ✓  Not a duplicate (highest similarity: {sim_score:.4f})")

    # ── 5. Generate content ─────────────────────────────────────────────────────
    print("\n  Generating content package (6 OpenAI calls)...")
    print("  This may take 20–40 seconds...")

    pkg = generate_content_package(brief)

    print(f"  ✓  Blog post:   {len(pkg.blog_body)} chars")
    print(f"  ✓  LinkedIn:    {len(pkg.linkedin_text)} chars")
    print(f"  ✓  Instagram:   {len(pkg.instagram_caption)} chars + {len(pkg.instagram_hashtags)} hashtags")
    print(f"  ✓  Facebook:    {len(pkg.facebook_text)} chars")
    print(f"  ✓  Threads:     {len(pkg.threads_sequence)} posts")
    print(f"  ✓  Telegram:    {len(pkg.telegram_text)} chars")
    print(f"  ✓  Image prompt: {len(pkg.image_prompt)} chars")

    # ── 6. Save outputs ─────────────────────────────────────────────────────────
    print("\n  Saving outputs...")

    # Save to data/drafts/latest/ (always overwritten)
    files = save_package(pkg, LATEST_DIR)

    # Save archived copy in data/drafts/YYYY-MM-DD/
    archive_dir = ARCHIVE_ROOT / brief.wix_slug
    save_package(pkg, archive_dir)

    # Save embedding to memory (for future dedup)
    vec = get_embedding(dedup_text)
    save_embedding(dedup_text, vec, slug=brief.wix_slug, source="title+angle")

    print(f"\n  ✓  Outputs saved to: data/drafts/latest/")
    print(f"  ✓  Archive saved to: data/drafts/{date.today().isoformat()}/{brief.wix_slug}/")
    print()
    print("  Files created:")
    for label, path in files.items():
        rel = path.relative_to(LATEST_DIR.parent.parent)
        print(f"    • {rel}")

    print(f"\n  Generated at: {pkg.generated_at}")
    print(f"  Topic: {pkg.blog_title!r}")
    print(f"  Slug: {brief.wix_slug}")
    print()
    print("  Next step: review drafts → then run scripts/publish.py (Phase 5)")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-id", help="Force a specific manual topic ID")
    parser.add_argument("--dry", action="store_true",
                        help="Validate setup without calling OpenAI")
    args = parser.parse_args()
    run(topic_id=args.topic_id, dry=args.dry)
