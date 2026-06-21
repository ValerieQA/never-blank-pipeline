"""
Never Blank Pipeline — Image Generation (Phase 5C)

Usage:
    python scripts/generate_image.py --dry-run   # validate setup, no API calls
    python scripts/generate_image.py --upload    # generate + upload + write image_url.txt

--dry-run validates:
  - draft exists in data/drafts/latest/
  - logo exists at assets/logo/never-blank-logo.png
  - Pillow installed + font available
  - NB_OPENAI_API_KEY present
  - Cloudinary env vars present

--upload runs the full pipeline (DALL-E + composite + Cloudinary).
Output:
  data/images/latest/image.png
  data/drafts/latest/image_url.txt
"""
import sys
import os
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.publishing.image_pipeline import (
    LOGO_PATH, IMAGES_DIR, REPO_ROOT, HOOK_MAX_CHARS, REGISTRY_PATH,
    _find_font, composite_image, run_image_pipeline, load_registry,
    choose_visual_family,
)

DRAFT_BASE = REPO_ROOT / "data" / "drafts" / "latest"
SEP = "─" * 60


def dry_run() -> int:
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║    Never Blank — Image Pipeline Dry-Run                  ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    errors: list[str] = []

    # ── 1. Draft ────────────────────────────────────────────────────
    print(f"{SEP}")
    print("  Draft")
    print(SEP)
    draft_dir = DRAFT_BASE / "final" if (DRAFT_BASE / "final" / "metadata.json").exists() else DRAFT_BASE
    if (draft_dir / "metadata.json").exists():
        import json
        meta = json.loads((draft_dir / "metadata.json").read_text())
        bm   = json.loads((draft_dir / "blog_meta.json").read_text())
        print(f"  ✓  Draft found:  {draft_dir}")
        print(f"  ✓  Title:        {meta.get('title', '?')!r}")
        print(f"  ✓  Hook:         {bm.get('hook_sentence', '?')[:60]!r}…")
        print(f"  ✓  Slug:         {meta.get('wix_slug', '?')!r}")
        prompt_file = draft_dir / "image_prompt.txt"
        if prompt_file.exists():
            print(f"  ✓  image_prompt.txt: {len(prompt_file.read_text())} chars")
        else:
            print(f"  ○  image_prompt.txt: not found — will derive from title")
    else:
        print(f"  ✗  No draft at {DRAFT_BASE}")
        print(f"       Run: python scripts/generate.py  OR  python scripts/create_fixture.py")
        errors.append("draft missing")

    # ── 2. Logo ─────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Logo")
    print(SEP)
    if LOGO_PATH.exists():
        from PIL import Image as PILImage
        logo = PILImage.open(LOGO_PATH)
        print(f"  ✓  {LOGO_PATH.relative_to(REPO_ROOT)}  ({logo.size[0]}×{logo.size[1]}px, {logo.mode})")
    else:
        print(f"  ✗  Logo not found: {LOGO_PATH}")
        errors.append("logo missing")

    # ── 3. Pillow + font ─────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Pillow + font")
    print(SEP)
    try:
        from PIL import Image as PILImage, ImageDraw, __version__ as pil_ver
        print(f"  ✓  Pillow {pil_ver}")
        font = _find_font(72)
        font_name = getattr(font, "path", "PIL default bitmap")
        print(f"  ✓  Font: {font_name}")
    except Exception as exc:
        print(f"  ✗  Pillow error: {exc}")
        errors.append("pillow")

    # ── 4. Visual system ──────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Visual system")
    print(SEP)
    from src.publishing.image_pipeline import VISUAL_SYSTEM, IMG_GEN_PROMPT
    if VISUAL_SYSTEM.exists():
        print(f"  ✓  config/visual_system.yaml")
    else:
        print(f"  ✗  config/visual_system.yaml missing")
        errors.append("visual_system.yaml missing")
    if IMG_GEN_PROMPT.exists():
        print(f"  ✓  config/prompts/image_generation.yaml")
    else:
        print(f"  ✗  config/prompts/image_generation.yaml missing")
        errors.append("image_generation.yaml missing")
    if REGISTRY_PATH.exists():
        registry = load_registry()
        n_posts = len(registry.get("posts", []))
        print(f"  ✓  data/memory/visual_registry.json  ({n_posts} posts logged)")
    else:
        print(f"  ○  data/memory/visual_registry.json not yet created (will be initialized on first run)")

    # ── 5. OpenAI (optional — has programmatic fallback) ─────────────
    print(f"\n{SEP}")
    print("  OpenAI (gpt-image-1 / dall-e-3) — optional, has fallback")
    print(SEP)
    key = os.getenv("NB_OPENAI_API_KEY", "")
    if key:
        print(f"  ✓  NB_OPENAI_API_KEY present ({len(key)} chars)")
        print(f"  ○  If AI image generation unavailable → programmatic Pillow image used")
    else:
        print(f"  ○  NB_OPENAI_API_KEY not set — will use programmatic Pillow image")

    # ── 5. Cloudinary ─────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Cloudinary")
    print(SEP)
    for var in ("NB_CLOUDINARY_CLOUD_NAME", "NB_CLOUDINARY_API_KEY", "NB_CLOUDINARY_API_SECRET"):
        val = os.getenv(var, "")
        if val:
            print(f"  ✓  {var}  ({len(val)} chars)")
        else:
            print(f"  ✗  {var} missing")
            errors.append(var)

    # ── 6. Output dirs ────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  Output paths")
    print(SEP)
    print(f"  ○  Image output:    data/images/latest/image.png  (created on run)")
    print(f"  ○  URL output:      data/drafts/latest/image_url.txt  (written on run)")

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{SEP}")
    if errors:
        print(f"  ✗  {len(errors)} issue(s) — fix before running --upload:")
        for e in errors:
            print(f"       • {e}")
        return 1

    print("  ✓  All checks passed — ready to run --upload")
    return 0


def upload() -> int:
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║    Never Blank — Image Pipeline (DALL-E + Cloudinary)    ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    draft_dir = DRAFT_BASE / "final" if (DRAFT_BASE / "final" / "metadata.json").exists() else DRAFT_BASE
    if not (draft_dir / "metadata.json").exists():
        print(f"  ✗  No draft found at {draft_dir}")
        print(f"       Run: python scripts/create_fixture.py  OR  python scripts/generate.py")
        return 1

    try:
        url = run_image_pipeline(draft_dir, IMAGES_DIR, log=lambda msg: print(msg))

        # Load registry to report what was selected
        registry = load_registry()
        last_post = registry.get("posts", [{}])[-1] if registry.get("posts") else {}

        print(f"\n  ✓  Image pipeline complete")
        print(f"  ✓  Visual family:  {last_post.get('visual_family', '?')}")
        print(f"  ✓  Hook text:      {last_post.get('hook_text', '?')!r}")
        print(f"  ✓  Palette:        {last_post.get('dominant_palette', '?')}")
        print(f"  ✓  Local:          data/images/latest/image.png")
        print(f"  ✓  Cloudinary URL: {url}")
        print(f"  ✓  image_url.txt:  data/drafts/latest/image_url.txt  ✓ written")
        print(f"  ✓  Registry:       data/memory/visual_registry.json  ✓ updated")
        print(f"\n  Next: python scripts/publish.py --dry-run")
        return 0
    except Exception as exc:
        print(f"\n  ✗  Pipeline failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Never Blank image generation pipeline",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Validate setup, no API calls")
    group.add_argument("--upload",  action="store_true", help="Generate + composite + upload")
    args = parser.parse_args()

    if args.dry_run:
        sys.exit(dry_run())
    else:
        sys.exit(upload())


if __name__ == "__main__":
    main()
