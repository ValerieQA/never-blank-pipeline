"""
Content Package Preparation — research pipeline stage 10.
For each selected signal, generates platform content previews and selects/reuses images.
Does NOT publish to any platform.

Output per signal: data/research/content_packages/{SIGNAL_ID}.json
Image library:     data/research/image_library.json
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.utils.logger import get_logger
from src.utils.llm_client import chat

log = get_logger("research.prepare_content")

SELECTED_FILE    = Path("data/research/selected_signals.jsonl")
PACKAGES_DIR     = Path("data/research/content_packages")
IMAGE_LIBRARY    = Path("data/research/image_library.json")
PLATFORMS        = ["blog", "linkedin", "facebook", "instagram", "threads", "stories"]

CONTENT_SYSTEM = """You are a content strategist for Never Blank, a content practice for founders.

For a given business signal, generate platform-specific content previews.

Never Blank voice: sharp, observational, commercially aware. Not motivational. Not academic.
Forbidden: "in today's world", "let's dive in", "game-changer", "unlock", "leverage", "hustle"

Return JSON with this exact structure:
{
  "blog": {
    "headline": "...",
    "angle": "One sentence describing the article angle — Signal → Tension → Response → Lesson"
  },
  "linkedin": {
    "headline": "Opening line (hook)",
    "angle": "One-sentence format: Observation + Business implication"
  },
  "facebook": {
    "headline": "Opening line",
    "angle": "Signal + case + question format"
  },
  "instagram": {
    "headline": "Visual anchor phrase (5–8 words)",
    "angle": "One-sentence caption angle"
  },
  "threads": {
    "thread_hook": "Opening post — one punchy observation, no hashtags",
    "angle": "What the thread sequence reveals"
  },
  "stories": {
    "story_question": "A question or tension framed for a 5-second swipe-up",
    "angle": "The business tension this story explores"
  }
}"""


def _generate_content_package(signal: dict) -> dict:
    """Generate platform content previews for one signal via LLM."""
    user = f"""Generate content package for this signal:

HEADLINE: {signal.get('HEADLINE', '')}
CORE_TENSION: {signal.get('CORE_TENSION', '')}
BUSINESS_LESSON: {signal.get('BUSINESS_LESSON', '')}
CORE_FACT: {signal.get('CORE_FACT', '')}
REAL_COMPANY_EXAMPLE: {signal.get('REAL_COMPANY_EXAMPLE', 'none')}
NEVER_BLANK_ANGLE: {signal.get('NEVER_BLANK_ANGLE', '')}
POSSIBLE_SIGNATURE_LINE: {signal.get('POSSIBLE_SIGNATURE_LINE', '')}
POTENTIAL_HOOK: {signal.get('POTENTIAL_HOOK', '')}
TARGET_AUDIENCE: {signal.get('TARGET_AUDIENCE', 'founder')}"""

    try:
        raw  = chat(CONTENT_SYSTEM, user, json_mode=True)
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log.error("Content generation failed for %s: %s", signal.get("SIGNAL_ID"), exc)
        return {}


def _load_image_library() -> dict:
    if IMAGE_LIBRARY.exists():
        return json.loads(IMAGE_LIBRARY.read_text())
    return {}


def _save_image_library(lib: dict) -> None:
    IMAGE_LIBRARY.parent.mkdir(parents=True, exist_ok=True)
    IMAGE_LIBRARY.write_text(json.dumps(lib, indent=2, ensure_ascii=False))


def _find_existing_image(signal: dict, library: dict) -> tuple[str | None, str]:
    """
    Try to find a reusable image. Returns (url_or_path, reuse_source).
    Priority:
      1. Same SIGNAL_ID in library
      2. Same SIGNAL_TYPE in library (same topic category)
      3. Most recent generic Never Blank image in library
    """
    sig_id      = signal.get("SIGNAL_ID", "")
    signal_type = signal.get("SIGNAL_TYPE", "")

    if sig_id in library:
        entry = library[sig_id]
        return entry["url"], f"same_signal ({entry.get('headline','')[:40]})"

    type_matches = [
        (k, v) for k, v in library.items()
        if v.get("signal_type") == signal_type and v.get("url")
    ]
    if type_matches:
        # Most recent
        type_matches.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
        key, entry = type_matches[0]
        return entry["url"], f"same_type:{signal_type}"

    # Fall back to most recent image of any kind
    if library:
        all_entries = sorted(library.items(), key=lambda x: x[1].get("created_at", ""), reverse=True)
        key, entry = all_entries[0]
        if entry.get("url"):
            return entry["url"], "most_recent_never_blank"

    return None, "none"


def _generate_programmatic_image(signal: dict) -> tuple[str, str]:
    """
    Generate a programmatic Never Blank branded image for this signal.
    Uses the existing image pipeline's programmatic fallback (no DALL-E cost).
    Returns (cloudinary_url_or_local_path, method).
    """
    try:
        from src.publishing.image_pipeline import (
            _generate_programmatic_base,
            composite_image,
            upload_to_cloudinary,
            choose_visual_family,
            load_registry,
        )

        hook_text = (signal.get("POTENTIAL_HOOK") or signal.get("HEADLINE", ""))[:80]
        title     = signal.get("HEADLINE", "")
        sig_id    = signal.get("SIGNAL_ID", "unknown")

        registry = load_registry()
        spec     = choose_visual_family(
            title=title,
            observation=signal.get("CORE_FACT", title),
            content_goal="challenge",
            registry=registry,
        )
        visual_family = spec.get("visual_family", "contrast_waves")

        base_bytes = _generate_programmatic_base(visual_family)
        image      = composite_image(base_bytes, hook_text)

        out_dir  = Path("data/research/images")
        out_dir.mkdir(parents=True, exist_ok=True)
        img_path = out_dir / f"{sig_id}.png"
        image.save(str(img_path), "PNG", optimize=True)

        # Try Cloudinary upload — gracefully skip if creds missing
        try:
            url = upload_to_cloudinary(img_path, slug=f"research/{sig_id}")
            return url, f"generated:programmatic:{visual_family}"
        except Exception as cld_exc:
            log.warning("Cloudinary upload failed — using local path: %s", cld_exc)
            return str(img_path), f"generated:local:{visual_family}"

    except Exception as exc:
        log.error("Image generation failed for %s: %s", signal.get("SIGNAL_ID"), exc)
        return "", "generation_failed"


def _build_image_plan(signal: dict, library: dict) -> dict:
    """
    Determine image for this signal: reuse or generate.
    Returns image plan dict and updated library.
    """
    existing_url, reuse_source = _find_existing_image(signal, library)

    if existing_url:
        image_url    = existing_url
        image_method = "reused"
        visual_path  = existing_url
        log.info("Image reused from %s for %s", reuse_source, signal.get("SIGNAL_ID"))
    else:
        log.info("No reusable image — generating for %s", signal.get("SIGNAL_ID"))
        image_url, image_method = _generate_programmatic_image(signal)
        visual_path = image_url

        if image_url:
            library[signal["SIGNAL_ID"]] = {
                "url":          image_url,
                "signal_type":  signal.get("SIGNAL_TYPE", ""),
                "headline":     signal.get("HEADLINE", ""),
                "created_at":   datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "method":       image_method,
            }

    # Single image shared across blog, linkedin, facebook, instagram
    # Stories gets a simple text variant (same image, noted separately)
    reused = image_method == "reused"
    platform_images = {
        "blog":      {"url": image_url, "path": visual_path, "reused": reused},
        "linkedin":  {"url": image_url, "path": visual_path, "reused": reused},
        "facebook":  {"url": image_url, "path": visual_path, "reused": reused},
        "instagram": {"url": image_url, "path": visual_path, "reused": reused},
        "threads":   {"url": image_url, "path": visual_path, "reused": reused},
        "stories":   {"url": image_url, "path": visual_path, "reused": reused},
    }
    new_images    = 0 if reused else (1 if image_url else 0)
    reused_images = 6 if reused else 0

    return {
        "platform_images": platform_images,
        "new_images":      new_images,
        "reused_images":   reused_images,
        "reuse_rate":      f"{int(reused_images / 6 * 100)}%",
        "image_method":    image_method,
        "reuse_source":    reuse_source if reused else "n/a",
    }


def prepare_content_packages(signals: list[dict]) -> list[dict]:
    """
    Main entry point. For each signal: generate content + select image.
    Returns list of content package dicts.
    """
    if not signals:
        return []

    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    library  = _load_image_library()
    packages = []

    for signal in signals:
        sig_id   = signal.get("SIGNAL_ID", "unknown")
        headline = signal.get("HEADLINE", "")
        log.info("Preparing content package: %s", headline[:60])

        # Generate platform content
        content = _generate_content_package(signal)

        # Image plan
        image_plan = _build_image_plan(signal, library)

        # Assemble package
        package = {
            "SIGNAL_ID":  sig_id,
            "HEADLINE":   headline,
            "prepared_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "content":    content,
            "images":     image_plan,
        }
        packages.append(package)

        # Save per-signal package
        pkg_path = PACKAGES_DIR / f"{sig_id}.json"
        pkg_path.write_text(json.dumps(package, indent=2, ensure_ascii=False))
        log.info("Saved content package: %s", pkg_path)

    _save_image_library(library)
    return packages


def format_package_preview(packages: list[dict]) -> str:
    """Return markdown summary of content packages for the daily report."""
    if not packages:
        return "No content packages prepared."

    lines = ["\n## Content Package Preview\n"]
    for i, pkg in enumerate(packages, 1):
        headline    = pkg.get("HEADLINE", "")
        content     = pkg.get("content", {})
        images      = pkg.get("images", {})
        platform_imgs = images.get("platform_images", {})

        lines.append(f"### Signal #{i}: {headline[:70]}")
        lines.append("")

        for platform in PLATFORMS:
            c = content.get(platform, {})
            img = platform_imgs.get(platform, {})
            img_path  = img.get("path", "—")
            reused    = "yes" if img.get("reused") else "no"

            if platform == "blog":
                lines.append(f"**Blog**")
                lines.append(f"- Headline: {c.get('headline', '—')}")
                lines.append(f"- Angle: {c.get('angle', '—')}")
            elif platform == "linkedin":
                lines.append(f"**LinkedIn**")
                lines.append(f"- Headline: {c.get('headline', '—')}")
                lines.append(f"- Angle: {c.get('angle', '—')}")
            elif platform == "facebook":
                lines.append(f"**Facebook**")
                lines.append(f"- Headline: {c.get('headline', '—')}")
                lines.append(f"- Angle: {c.get('angle', '—')}")
            elif platform == "instagram":
                lines.append(f"**Instagram**")
                lines.append(f"- Headline: {c.get('headline', '—')}")
                lines.append(f"- Angle: {c.get('angle', '—')}")
            elif platform == "threads":
                lines.append(f"**Threads**")
                lines.append(f"- Thread hook: {c.get('thread_hook', '—')}")
                lines.append(f"- Angle: {c.get('angle', '—')}")
            elif platform == "stories":
                lines.append(f"**Stories**")
                lines.append(f"- Story question: {c.get('story_question', '—')}")
                lines.append(f"- Angle: {c.get('angle', '—')}")

            lines.append(f"- Image asset: {img_path[:80] if img_path else '—'}")
            lines.append(f"- Image reused: {reused}")
            lines.append("")

        lines.append(f"**Image summary**")
        lines.append(f"- Reuse rate: {images.get('reuse_rate', '—')}")
        lines.append(f"- New images generated: {images.get('new_images', 0)}")
        lines.append(f"- Images reused: {images.get('reused_images', 0)}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    if not SELECTED_FILE.exists():
        print("No selected_signals.jsonl found")
        sys.exit(0)

    signals = [json.loads(l) for l in SELECTED_FILE.read_text().splitlines() if l.strip()]
    packages = prepare_content_packages(signals)
    print(format_package_preview(packages))
