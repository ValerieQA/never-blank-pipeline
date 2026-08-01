"""
Content Package Preparation — research pipeline stage 10.
For each selected signal:
  - generates platform content previews via LLM
  - generates one new image per signal using full image pipeline
  - exports platform-specific image sizes
  - does NOT publish

Image reuse rules (strict):
  - same SIGNAL_ID in this run's library → reuse across platforms
  - same SIGNAL_TYPE in library → only if semantically confirmed by LLM (not implemented here)
  - NO fallback to unrelated past images

Output per signal: reports/content_packages/{SIGNAL_ID}.json
Platform images:   reports/content_packages/images/{SIGNAL_ID}_{platform}.png
Cloudinary URL:    stored in image_library.json keyed by SIGNAL_ID
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.utils.logger import get_logger
from src.utils.llm_client import chat, model_social

log = get_logger("research.prepare_content")

SELECTED_FILE = Path("data/research/selected_signals.jsonl")
PACKAGES_DIR  = Path("reports/content_packages")
IMAGE_LIBRARY = Path("data/research/image_library.json")
PLATFORMS     = ["blog", "linkedin", "facebook", "instagram", "threads", "stories"]

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
        raw  = chat(CONTENT_SYSTEM, user, json_mode=True, model=model_social())
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
    Return a reusable image URL only if:
      - SIGNAL_ID matches, AND
      - design_version in library matches CURRENT_DESIGN_VERSION, AND
      - NB_FORCE_REGENERATE_RESEARCH_IMAGES != 'true'

    Old entries with missing or outdated design_version are ignored
    so that improved image designs are not blocked by stale library entries.
    """
    from src.publishing.image_pipeline import CURRENT_DESIGN_VERSION

    force = os.environ.get("NB_FORCE_REGENERATE_RESEARCH_IMAGES", "false").lower() == "true"
    if force:
        return None, "force_regenerate"

    sig_id = signal.get("SIGNAL_ID", "")
    if sig_id in library:
        entry = library[sig_id]
        if entry.get("design_version") == CURRENT_DESIGN_VERSION:
            return entry["url"], f"same_signal ({entry.get('headline', '')[:40]})"
        # Entry exists but design version is outdated — regenerate
        log.info(
            "Signal %s: image_library entry has design_version=%r, current=%s — regenerating",
            sig_id, entry.get("design_version"), CURRENT_DESIGN_VERSION,
        )
    return None, "none"


def _generate_signal_image(signal: dict) -> dict:
    """
    Generate a full Never Blank branded image for this signal.
    Uses the proven image_pipeline: visual family → base image → composite → platform sizes → Cloudinary.
    Returns image_result dict with per-platform Cloudinary URLs and metadata.
    """
    from src.publishing.image_pipeline import (
        choose_visual_family,
        load_registry,
        _generate_base_image,
        composite_for_platform,
        compose_quote_card,
        CARD_TYPES,
        upload_to_cloudinary,
        prepare_photo_overlay_hook,
        PLATFORM_SIZES,
        CURRENT_DESIGN_VERSION,
    )

    sig_id   = signal.get("SIGNAL_ID", "unknown")
    headline = signal.get("HEADLINE", "")
    hook_raw = signal.get("POTENTIAL_HOOK") or signal.get("POSSIBLE_SIGNATURE_LINE") or headline

    registry = load_registry()

    spec = choose_visual_family(
        title        = headline,
        observation  = signal.get("CORE_FACT", headline),
        content_goal = "challenge",
        registry     = registry,
        log          = log.info,
        company      = signal.get("REAL_COMPANY_EXAMPLE", ""),
    )

    visual_family    = spec["visual_family"]
    dominant_palette = spec["dominant_palette"]
    image_prompt     = spec["image_prompt"]
    negative_prompt  = spec.get("negative_prompt", "")
    ai_hook          = spec.get("hook_text", "")
    is_card          = visual_family in CARD_TYPES

    if is_card:
        # Quote cards hold full sentences - the text IS the visual. Do NOT
        hook_text = ai_hook or hook_raw
    else:
        hook_text = prepare_photo_overlay_hook(ai_hook if ai_hook else hook_raw)

    log.info("Signal %s: visual_family=%s hook=%r", sig_id, visual_family, hook_text)

    if is_card:
        # Quote card: no AI image call at all (also sidesteps the image-
        # safety-policy risk of AI-generated photos). Dark cards still get an
        # atmospheric backdrop — see compose_quote_card / card_texture_family.
        method = "quote_card"
        base_bytes = None
        card_texture_family = spec.get("card_texture_family", "mountains_depth_layers")
    else:
        # Generate base image (AI → programmatic fallback)
        base_bytes, method = _generate_base_image(
            image_prompt, visual_family, negative_prompt, log=log.info
        )

    # ── Per-platform composition: base → resize → overlay (correct order) ──────
    # Each platform gets its own composite with text/logo sized for that canvas.
    out_dir = PACKAGES_DIR / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    platform_images: dict[str, dict] = {}
    master_url: str = ""

    prepared_hook = prepare_photo_overlay_hook(hook_text)
    for platform in PLATFORMS:
        if is_card:
            sized_img = compose_quote_card(hook_text, platform, visual_family, card_texture_family)
        else:
            sized_img = composite_for_platform(base_bytes, prepared_hook, platform)
        w, h      = PLATFORM_SIZES.get(platform, (1080, 1080))
        img_path  = out_dir / f"{sig_id}_{platform}.png"
        sized_img.save(str(img_path), "PNG", optimize=True)

        try:
            url = upload_to_cloudinary(img_path, slug=f"research/{sig_id}/{platform}")
        except Exception as cld_exc:
            log.warning("Cloudinary upload failed for %s/%s: %s", sig_id, platform, cld_exc)
            url = str(img_path)

        platform_images[platform] = {
            "url":    url,
            "path":   str(img_path),
            "size":   f"{w}x{h}",
            "reused": False,
        }
        if platform == "blog":
            master_url = url

    # Update image library with blog URL + design_version
    if master_url:
        registry_lib_entry = {
            "url":            master_url,
            "signal_type":    signal.get("SIGNAL_TYPE", ""),
            "headline":       headline,
            "created_at":     datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "method":         method,
            "visual_family":  visual_family,
            "design_version": CURRENT_DESIGN_VERSION,
            "hook_text":      hook_text,
        }
        platform_images["_design_version"] = CURRENT_DESIGN_VERSION
        return {
            "platform_images": platform_images,
            "new_images":      1,
            "reused_images":   0,
            "reuse_rate":      "0%",
            "image_method":    method,
            "reuse_source":    "n/a",
            "visual_family":   visual_family,
            "hook_text":       hook_text,
            "_library_entry":  registry_lib_entry,
            "_registry_update": {
                "content_slug":    f"research/{sig_id}",
                "visual_family":   visual_family,
                "dominant_palette": dominant_palette,
                "hook_text":       hook_text,
                "image_url":       master_url,
                "source_topic":    headline,
            },
        }

    # Fallback: no Cloudinary URL at all (local paths only)
    platform_images["_design_version"] = CURRENT_DESIGN_VERSION
    return {
        "platform_images": platform_images,
        "new_images":      1,
        "reused_images":   0,
        "reuse_rate":      "0%",
        "image_method":    f"{method}:local_only",
        "reuse_source":    "n/a",
        "visual_family":   visual_family,
        "hook_text":       hook_text,
    }


def _build_image_plan(signal: dict, library: dict) -> tuple[dict, dict | None]:
    """
    Determine image for this signal: reuse (same signal only) or generate fresh.
    Returns (image_plan, library_entry_or_None).
    Library entry is only returned when a new image was generated.
    """
    existing_url, reuse_source = _find_existing_image(signal, library)

    if existing_url:
        log.info("Image reused (same signal, same design_version) for %s", signal.get("SIGNAL_ID"))
        from src.publishing.image_pipeline import PLATFORM_SIZES, CURRENT_DESIGN_VERSION
        lib_entry = library.get(signal.get("SIGNAL_ID", ""), {})
        platform_images = {
            p: {
                "url":    existing_url,
                "path":   existing_url,
                "size":   "%dx%d" % PLATFORM_SIZES.get(p, (1080, 1080)),
                "reused": True,
            }
            for p in PLATFORMS
        }
        return {
            "platform_images": platform_images,
            "new_images":      0,
            "reused_images":   len(PLATFORMS),
            "reuse_rate":      "100%",
            "image_method":    "reused",
            "reuse_source":    reuse_source,
            "visual_family":   lib_entry.get("visual_family", ""),
            "hook_text":       lib_entry.get("hook_text", ""),
            "design_version":  lib_entry.get("design_version", ""),
        }, None

    log.info("Generating new image for signal %s", signal.get("SIGNAL_ID"))
    try:
        result = _generate_signal_image(signal)
    except Exception as exc:
        log.error("Image generation failed for %s: %s", signal.get("SIGNAL_ID"), exc)
        # Return empty image plan — publishing will proceed without images
        empty = {p: {"url": "", "path": "", "size": "", "reused": False} for p in PLATFORMS}
        return {
            "platform_images": empty,
            "new_images":      0,
            "reused_images":   0,
            "reuse_rate":      "0%",
            "image_method":    "failed",
            "reuse_source":    "n/a",
            "visual_family":   "",
            "hook_text":       "",
            "error":           str(exc),
        }, None

    library_entry   = result.pop("_library_entry", None)
    registry_update = result.pop("_registry_update", None)
    if registry_update:
        # Persist so the instagram_rhythm.cycle / family rotation actually
        # advances between posts — previously computed and thrown away here,
        # so the rhythm cycle would have picked the same slot every run.
        from src.publishing.image_pipeline import load_registry, register_post, save_registry
        registry = register_post(load_registry(), **registry_update)
        save_registry(registry)

    return result, library_entry


def prepare_content_packages(signals: list[dict]) -> list[dict]:
    """
    Main entry point. For each signal: generate content + image (one per signal).
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

        content    = _generate_content_package(signal)
        image_plan, library_entry = _build_image_plan(signal, library)

        if library_entry:
            library[sig_id] = library_entry

        package = {
            "SIGNAL_ID":   sig_id,
            "HEADLINE":    headline,
            "prepared_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "content":     content,
            "images":      image_plan,
        }
        packages.append(package)

        pkg_path = PACKAGES_DIR / f"{sig_id}.json"
        pkg_path.write_text(json.dumps(package, indent=2, ensure_ascii=False))
        log.info("Saved content package: %s", pkg_path)

    _save_image_library(library)
    return packages


def format_package_preview(packages: list[dict]) -> str:
    if not packages:
        return "No content packages prepared."

    lines = ["\n## Content Package Preview\n"]
    for i, pkg in enumerate(packages, 1):
        headline = pkg.get("HEADLINE", "")
        content  = pkg.get("content", {})
        images   = pkg.get("images", {})
        pimgs    = images.get("platform_images", {})

        lines.append(f"### Signal #{i}: {headline[:70]}")
        lines.append(f"- Visual family: {images.get('visual_family', '—')}")
        lines.append(f"- Hook text: {images.get('hook_text', '—')}")
        lines.append(f"- Image method: {images.get('image_method', '—')}")
        lines.append(f"- Reuse source: {images.get('reuse_source', '—')}")
        lines.append("")

        for platform in PLATFORMS:
            c   = content.get(platform, {})
            img = pimgs.get(platform, {})
            reused = "yes" if img.get("reused") else "no"
            size   = img.get("size", "—")
            url    = img.get("url", "—")

            if platform == "blog":
                lines.append(f"**Blog** ({size})")
                lines.append(f"- Headline: {c.get('headline', '—')}")
                lines.append(f"- Angle: {c.get('angle', '—')}")
            elif platform == "linkedin":
                lines.append(f"**LinkedIn** ({size})")
                lines.append(f"- Headline: {c.get('headline', '—')}")
                lines.append(f"- Angle: {c.get('angle', '—')}")
            elif platform == "facebook":
                lines.append(f"**Facebook** ({size})")
                lines.append(f"- Headline: {c.get('headline', '—')}")
            elif platform == "instagram":
                lines.append(f"**Instagram** ({size})")
                lines.append(f"- Headline: {c.get('headline', '—')}")
            elif platform == "threads":
                lines.append(f"**Threads** ({size})")
                lines.append(f"- Thread hook: {c.get('thread_hook', '—')}")
            elif platform == "stories":
                lines.append(f"**Stories** ({size})")
                lines.append(f"- Story question: {c.get('story_question', '—')}")

            lines.append(f"- Image: {url[:80] if url else '—'}")
            lines.append(f"- Reused: {reused}")
            lines.append("")

        lines.append(f"**Image summary** — new: {images.get('new_images', 0)}, reused: {images.get('reused_images', 0)}, rate: {images.get('reuse_rate', '—')}")
        if images.get("error"):
            lines.append(f"- ⚠️ Image error: {images['error']}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    if not SELECTED_FILE.exists():
        print("No selected_signals.jsonl found")
        sys.exit(0)

    signals  = [json.loads(l) for l in SELECTED_FILE.read_text().splitlines() if l.strip()]
    packages = prepare_content_packages(signals)
    print(format_package_preview(packages))
