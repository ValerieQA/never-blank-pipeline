"""
Never Blank image generation pipeline.

Flow:
  1. Read image_prompt.txt + hook_sentence from draft
  2. Call DALL-E 3 to generate base image
  3. Composite: dark gradient overlay + hook text + Never Blank logo
  4. Save to data/images/latest/image.png
  5. Upload to Cloudinary (never-blank/posts/{slug}/)
  6. Write URL to data/drafts/latest/image_url.txt

Public API:
  run_image_pipeline(draft_dir) -> str   # full pipeline, returns Cloudinary URL
  composite_image(base_bytes, hook_text) -> PIL.Image
"""
import json
import os
import time
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# ── Paths & constants ──────────────────────────────────────────────────────────

REPO_ROOT  = Path(__file__).parent.parent.parent
LOGO_PATH  = REPO_ROOT / "assets" / "logo" / "never-blank-logo.png"
IMAGES_DIR = REPO_ROOT / "data" / "images" / "latest"

IMAGE_SIZE  = (1080, 1080)   # square — works on IG, FB, LinkedIn
BG_COLOR    = (0, 0, 0)
TEXT_COLOR  = (255, 255, 255)
SHADOW_COLOR = (0, 0, 0, 180)

HOOK_MAX_CHARS = 80           # from brand.yaml image.hook_max_chars


# ── Font loader ────────────────────────────────────────────────────────────────

def _find_font(size: int) -> ImageFont.FreeTypeFont:
    """
    Find best available TTF font — tries project assets first,
    then common system paths (Ubuntu CI + macOS local), then PIL default.
    """
    from glob import glob
    candidates = [
        str(REPO_ROOT / "assets" / "fonts" / "*.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",          # Ubuntu (CI)
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",  # Ubuntu
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",                 # Ubuntu
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",                      # Arch
        "/System/Library/Fonts/Helvetica.ttc",                           # macOS
        "/Library/Fonts/Arial Bold.ttf",                                  # macOS
        "/Library/Fonts/Arial.ttf",                                       # macOS
    ]
    for candidate in candidates:
        if "*" in candidate:
            for match in sorted(glob(candidate)):
                try:
                    return ImageFont.truetype(match, size)
                except Exception:
                    continue
        elif os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ── Text wrapping ──────────────────────────────────────────────────────────────

def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Wrap text to fit max_w pixels wide."""
    tmp = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(tmp)

    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if (bbox[2] - bbox[0]) <= max_w:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines or [text]


# ── DALL-E image generation ───────────────────────────────────────────────────

def _generate_dalle_image(prompt: str) -> bytes:
    """
    Call DALL-E 3 with a brand-styled prompt, download result, return raw bytes.
    """
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["NB_OPENAI_API_KEY"])

    styled = (
        f"{prompt.rstrip('.')}\n\n"
        "Visual style: dark editorial, minimalist, cinematic. "
        "Very dark background (near-black). Strong negative space. "
        "No text, no typography, no logos in the image. "
        "High contrast. Professional photography quality. "
        "Suitable for a thought-leadership brand aimed at founders."
    )

    response = client.images.generate(
        model="dall-e-3",
        prompt=styled,
        size="1024x1024",
        quality="standard",
        n=1,
    )
    image_url = response.data[0].url
    with urllib.request.urlopen(image_url, timeout=30) as resp:
        return resp.read()


# ── Compositing ────────────────────────────────────────────────────────────────

def composite_image(base_bytes: bytes, hook_text: str) -> Image.Image:
    """
    Composite logo + hook text onto a base image.
    Returns a 1080×1080 RGB image.
    """
    W, H = IMAGE_SIZE
    hook = hook_text[:HOOK_MAX_CHARS].strip()

    # Base layer
    base = Image.open(BytesIO(base_bytes)).convert("RGBA").resize((W, H), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    canvas.paste(base, (0, 0))

    # Dark gradient overlay — heavier at top (text area) and bottom (logo area)
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad)
    for y in range(H):
        # Top half: 0 → 190 alpha (text legibility)
        if y < H * 0.55:
            alpha = int(190 * (y / (H * 0.55)) ** 0.6)
        else:
            # Bottom 45%: 100 → 210 alpha (logo area)
            frac = (y - H * 0.55) / (H * 0.45)
            alpha = int(100 + 110 * frac)
        grad_draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    canvas = Image.alpha_composite(canvas, grad)

    draw = ImageDraw.Draw(canvas)

    # ── Hook text ─────────────────────────────────────────────────────────────
    padding   = 72
    font_hook = _find_font(72)
    font_sub  = _find_font(34)
    max_text_w = W - padding * 2

    lines = _wrap_text(hook, font_hook, max_text_w)

    # Calculate total block height
    line_h = int(72 * 1.25)
    block_h = len(lines) * line_h
    y_center = int(H * 0.38)
    y_start  = y_center - block_h // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_hook)
        line_w = bbox[2] - bbox[0]
        x = (W - line_w) // 2
        y = y_start + i * line_h
        # Shadow
        draw.text((x + 3, y + 3), line, font=font_hook, fill=(0, 0, 0, 180))
        # Text
        draw.text((x, y), line, font=font_hook, fill=(255, 255, 255, 255))

    # Thin separator line below text
    sep_y = y_start + block_h + 28
    sep_w = min(200, W // 3)
    draw.line(
        [(W // 2 - sep_w // 2, sep_y), (W // 2 + sep_w // 2, sep_y)],
        fill=(255, 255, 255, 140),
        width=2,
    )

    # "Never Blank" small label below separator
    font_label = _find_font(26)
    label = "Never Blank"
    bbox = draw.textbbox((0, 0), label, font=font_label)
    lw = bbox[2] - bbox[0]
    draw.text(
        ((W - lw) // 2, sep_y + 14),
        label,
        font=font_label,
        fill=(200, 200, 200, 200),
    )

    # ── Logo — bottom right ───────────────────────────────────────────────────
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo_w = int(W * 0.22)
        logo_h = int(logo.height * (logo_w / logo.width))
        logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

        margin = 40
        paste_x = W - logo_w - margin
        paste_y = H - logo_h - margin
        canvas.paste(logo, (paste_x, paste_y), logo)

    return canvas.convert("RGB")


# ── Cloudinary upload ──────────────────────────────────────────────────────────

def upload_to_cloudinary(image_path: Path, slug: str) -> str:
    """Upload PNG to Cloudinary, return secure_url."""
    import cloudinary
    import cloudinary.uploader

    cloudinary.config(
        cloud_name = os.environ["NB_CLOUDINARY_CLOUD_NAME"],
        api_key    = os.environ["NB_CLOUDINARY_API_KEY"],
        api_secret = os.environ["NB_CLOUDINARY_API_SECRET"],
        secure     = True,
    )

    ts     = int(time.time())
    folder = f"never-blank/posts/{slug}"
    result = cloudinary.uploader.upload(
        str(image_path),
        folder        = folder,
        public_id     = str(ts),
        resource_type = "image",
        overwrite     = True,
    )
    return result["secure_url"]


# ── Full pipeline ──────────────────────────────────────────────────────────────

def run_image_pipeline(
    draft_dir: Path,
    images_dir: Path = IMAGES_DIR,
    log=print,
) -> str:
    """
    Full pipeline: DALL-E → composite → save locally → upload to Cloudinary.
    Writes image_url.txt to draft_dir.
    Returns the Cloudinary URL.
    """
    # Read draft metadata
    blog_meta = json.loads((draft_dir / "blog_meta.json").read_text(encoding="utf-8"))
    metadata  = json.loads((draft_dir / "metadata.json").read_text(encoding="utf-8"))

    hook = blog_meta.get("hook_sentence", metadata.get("title", ""))[:HOOK_MAX_CHARS]
    slug = metadata.get("wix_slug", "post")

    # Image prompt
    prompt_file = draft_dir / "image_prompt.txt"
    if prompt_file.exists():
        prompt = prompt_file.read_text(encoding="utf-8").strip()
    else:
        prompt = (
            f"Editorial photograph representing the idea: '{metadata.get('title', '')}'. "
            f"Abstract, conceptual, dark background."
        )

    # Generate base image
    log("  Calling DALL-E 3…")
    base_bytes = _generate_dalle_image(prompt)
    log(f"  Base image: {len(base_bytes) // 1024}KB received")

    # Composite branding
    log("  Compositing logo + hook text…")
    image = composite_image(base_bytes, hook)

    # Save locally
    images_dir.mkdir(parents=True, exist_ok=True)
    local_path = images_dir / "image.png"
    image.save(str(local_path), "PNG", optimize=True)
    log(f"  Saved locally: {local_path}  ({local_path.stat().st_size // 1024}KB)")

    # Upload to Cloudinary
    log("  Uploading to Cloudinary…")
    url = upload_to_cloudinary(local_path, slug)
    log(f"  Cloudinary URL: {url}")

    # Write image_url.txt so publishers can find it
    url_file = draft_dir / "image_url.txt"
    url_file.write_text(url, encoding="utf-8")
    log(f"  Written: {url_file}")

    return url
