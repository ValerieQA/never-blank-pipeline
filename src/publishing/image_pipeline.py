"""
Never Blank image generation pipeline — Visual System v2.

Flow:
  1. Load visual_system.yaml + image_generation.yaml
  2. Load visual_registry.json (rotation memory)
  3. Choose visual family based on topic + rotation rules
  4. Build image prompt via OpenAI (vision director call) or deterministic fallback
  5. Generate base image (AI or programmatic Pillow fallback)
  6. Composite: dark gradient overlay + hook text + official logo
  7. Save to data/images/latest/image.png
  8. Upload to Cloudinary (never-blank/posts/{slug}/)
  9. Write URL to data/drafts/latest/image_url.txt
  10. Update data/memory/visual_registry.json

Public API:
  run_image_pipeline(draft_dir) -> str          # full pipeline, returns Cloudinary URL
  composite_image(base_bytes, hook_text) -> PIL.Image
  choose_visual_family(title, observation, content_goal) -> dict  # visual spec
"""
import json
import math
import os
import time
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont
import yaml

# ── Paths ──────────────────────────────────────────────────────────────────────

REPO_ROOT      = Path(__file__).parent.parent.parent
LOGO_PATH      = REPO_ROOT / "assets" / "logo" / "never-blank-logo.png"
IMAGES_DIR     = REPO_ROOT / "data" / "images" / "latest"
REGISTRY_PATH  = REPO_ROOT / "data" / "memory" / "visual_registry.json"
VISUAL_SYSTEM  = REPO_ROOT / "config" / "visual_system.yaml"
IMG_GEN_PROMPT = REPO_ROOT / "config" / "prompts" / "image_generation.yaml"

IMAGE_SIZE   = (1080, 1080)
HOOK_MAX_CHARS = 80

# Electric Blue accent for compositing
ELECTRIC_BLUE = (66, 160, 255)
TEXT_COLOR    = (255, 255, 255)


# ── Config loaders ─────────────────────────────────────────────────────────────

def _load_visual_system() -> dict:
    with open(VISUAL_SYSTEM) as f:
        return yaml.safe_load(f)


def _load_img_gen_prompt() -> dict:
    with open(IMG_GEN_PROMPT) as f:
        return yaml.safe_load(f)


# ── Visual registry ────────────────────────────────────────────────────────────

def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    return {"_schema": "1.0", "posts": []}


def save_registry(registry: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


def _recent_families(registry: dict, window: int = 6) -> list[str]:
    posts = registry.get("posts", [])
    return [p["visual_family"] for p in posts[-window:]]


def _last_family(registry: dict) -> Optional[str]:
    posts = registry.get("posts", [])
    return posts[-1]["visual_family"] if posts else None


def register_post(
    registry: dict,
    *,
    content_slug: str,
    visual_family: str,
    dominant_palette: str,
    hook_text: str,
    image_url: str,
    source_topic: str,
) -> dict:
    entry = {
        "published_date":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "content_slug":    content_slug,
        "visual_family":   visual_family,
        "dominant_palette": dominant_palette,
        "hook_text":       hook_text,
        "image_url":       image_url,
        "source_topic":    source_topic,
        "reuse_count":     1,
    }
    registry.setdefault("posts", []).append(entry)
    return registry


# ── Visual family selection ────────────────────────────────────────────────────

FAMILY_IDS = [
    "mountains_depth_layers",
    "light_paths",
    "contrast_waves",
    "particle_flow",
    "constellation_networks",
    "focus_rings",
]

# Maps content_goal / observation keywords to preferred family
_TOPIC_AFFINITY: dict[str, list[str]] = {
    "momentum":    ["light_paths", "particle_flow"],
    "pattern":     ["constellation_networks", "particle_flow"],
    "system":      ["constellation_networks", "particle_flow"],
    "signal":      ["contrast_waves", "focus_rings"],
    "rate":        ["light_paths", "contrast_waves"],
    "clarity":     ["mountains_depth_layers", "focus_rings"],
    "perspective": ["mountains_depth_layers"],
    "compound":    ["light_paths", "particle_flow"],
    "hidden":      ["mountains_depth_layers", "constellation_networks"],
    "measurement": ["focus_rings", "contrast_waves"],
    "network":     ["constellation_networks"],
    "direction":   ["light_paths"],
    "depth":       ["mountains_depth_layers"],
    "flow":        ["particle_flow", "light_paths"],
    "tension":     ["contrast_waves"],
    "attention":   ["focus_rings"],
}


def _pick_family_deterministic(
    title: str,
    observation: str,
    recent: list[str],
    last: Optional[str],
    vs: dict,
) -> str:
    """Choose a visual family without an LLM call, using keyword affinity + rotation."""
    text = (title + " " + observation).lower()
    rotation_rules = vs.get("rotation_rules", {})
    window_size    = rotation_rules.get("window", 6)
    max_in_window  = rotation_rules.get("max_same_family_in_window", 2)
    mtn_max        = rotation_rules.get("mountains_max_in_last_9", 3)

    # Score by keyword affinity
    scores: dict[str, int] = {fid: 0 for fid in FAMILY_IDS}
    for keyword, families in _TOPIC_AFFINITY.items():
        if keyword in text:
            for fid in families:
                scores[fid] += 2

    # mountains_depth_layers is the core family — small baseline boost
    scores["mountains_depth_layers"] += 1

    # Apply rotation constraints: penalise overused families
    recent_window = recent[-window_size:]
    for fid in FAMILY_IDS:
        count = recent_window.count(fid)
        if fid == last:
            scores[fid] -= 10   # heavy penalty for consecutive repeat
        if fid == "mountains_depth_layers":
            if recent[-9:].count(fid) >= mtn_max:
                scores[fid] -= 8
        elif count >= max_in_window:
            scores[fid] -= 6

    best = max(scores, key=lambda k: (scores[k], FAMILY_IDS.index(k) * -1))
    return best


def _build_image_prompt(
    visual_family: str,
    title: str,
    observation: str,
    dominant_palette: str,
    vs: dict,
    img_gen: dict,
) -> tuple[str, str]:
    """
    Build (image_prompt, negative_prompt) from config + visual family.
    Returns strings ready to pass to the image model.
    """
    family_cfg = vs["visual_families"][visual_family]
    visuals    = ", ".join(family_cfg["visuals"])
    avoid      = ", ".join(family_cfg.get("avoid", []))
    palette_hex = vs["palette"]["dark_core"]["colors"].get(dominant_palette, "#050B16")
    style_suffix = img_gen.get("image_generation_style_suffix", "").strip()
    neg_base     = img_gen.get("negative_prompt_base", "").strip()

    prompt = (
        f"Dark editorial photograph visualizing the concept: '{observation}'. "
        f"Visual metaphor: {family_cfg['label']} — {', '.join(family_cfg['meaning'])}. "
        f"Composition elements: {visuals}. "
        f"Dominant color: {dominant_palette.replace('_', ' ')} ({palette_hex}). "
        f"Atmosphere: intelligent, calm, signal-before-noise, premium. "
        f"{style_suffix}"
    )

    neg = neg_base
    if avoid:
        neg += f", {avoid}"

    return prompt.strip(), neg.strip()


def _ai_choose_visual_spec(
    title: str,
    observation: str,
    content_goal: str,
    recent_families: list[str],
    img_gen: dict,
    log=print,
) -> Optional[dict]:
    """
    Use OpenAI chat to pick visual family and build full spec.
    Returns parsed dict or None on failure.
    """
    api_key = os.getenv("NB_OPENAI_API_KEY", "")
    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        selection_prompt = img_gen["selection_prompt"].format(
            title=title,
            observation=observation,
            content_goal=content_goal,
            recent_families=", ".join(recent_families) if recent_families else "none",
        )

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": selection_prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        raw = resp.choices[0].message.content
        spec = json.loads(raw)

        # Validate required fields
        required = ["visual_family", "dominant_palette", "image_prompt", "hook_text",
                    "negative_prompt", "logo_placement", "rationale"]
        for key in required:
            if key not in spec:
                log(f"  ○ AI spec missing field '{key}' — falling back to deterministic")
                return None

        # Validate family is allowed
        if spec["visual_family"] not in FAMILY_IDS:
            log(f"  ○ AI chose unknown family '{spec['visual_family']}' — falling back")
            return None

        return spec
    except Exception as exc:
        log(f"  ○ AI visual selection failed ({exc.__class__.__name__}) — using deterministic")
        return None


def choose_visual_family(
    title: str,
    observation: str,
    content_goal: str,
    registry: dict,
    log=print,
) -> dict:
    """
    Choose visual family and build full image spec.
    Tries AI selection first; falls back to deterministic keyword + rotation logic.
    Returns a spec dict with all fields needed by the pipeline.
    """
    vs      = _load_visual_system()
    img_gen = _load_img_gen_prompt()
    recent  = _recent_families(registry)
    last    = _last_family(registry)

    # Try AI-based selection
    spec = _ai_choose_visual_spec(
        title, observation, content_goal, recent, img_gen, log=log
    )

    if spec:
        log(f"  Visual family (AI): {spec['visual_family']} — {spec.get('rationale', '')}")
        # Append style suffix to AI-generated prompt if not already comprehensive
        suffix = img_gen.get("image_generation_style_suffix", "").strip()
        if suffix and suffix[:30] not in spec["image_prompt"]:
            spec["image_prompt"] = spec["image_prompt"].rstrip() + " " + suffix
        return spec

    # Deterministic fallback
    family          = _pick_family_deterministic(title, observation, recent, last, vs)
    dominant_palette = "midnight"   # safe dark core default
    image_prompt, neg_prompt = _build_image_prompt(
        family, title, observation, dominant_palette, vs, img_gen
    )

    # Hook: use observation truncated cleanly
    hook = observation.strip()
    # Trim to word boundary at max chars
    if len(hook) > HOOK_MAX_CHARS:
        hook = hook[:HOOK_MAX_CHARS].rsplit(" ", 1)[0]

    log(f"  Visual family (deterministic): {family}")
    return {
        "visual_family":   family,
        "dominant_palette": dominant_palette,
        "image_prompt":    image_prompt,
        "hook_text":       hook,
        "negative_prompt": neg_prompt,
        "logo_placement":  "bottom_right",
        "rationale":       f"Deterministic: keyword affinity + rotation rules selected {family}",
    }


# ── Font loader ────────────────────────────────────────────────────────────────

def _find_font(size: int) -> ImageFont.FreeTypeFont:
    from glob import glob
    candidates = [
        str(REPO_ROOT / "assets" / "fonts" / "*.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
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
    tmp  = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(tmp)
    words: list[str] = text.split()
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


# ── Programmatic base image (Pillow only) ──────────────────────────────────────

def _generate_programmatic_base(visual_family: str = "mountains_depth_layers") -> bytes:
    """
    Create a dark branded background using Pillow only.
    Adapts texture slightly per visual family but always stays within brand palette.
    """
    W, H = 1024, 1024
    canvas = Image.new("RGB", (W, H), (5, 11, 22))   # Deep Navy #050B16
    draw   = ImageDraw.Draw(canvas)
    cx, cy = W // 2, H // 2

    if visual_family in ("mountains_depth_layers", "light_paths"):
        # Layered horizontal bands — depth / distance feeling
        for i, shade_base in enumerate(range(4, 28, 3)):
            y_pct = 0.3 + i * 0.08
            y0, y1 = int(H * y_pct), int(H * (y_pct + 0.09))
            shade = shade_base
            draw.rectangle([0, y0, W, y1], fill=(shade, shade + 2, int(shade * 1.6)))
        # Subtle radial glow near horizon
        for r in range(180, 0, -6):
            frac  = r / 180
            alpha = int(frac * 18)
            draw.ellipse(
                [cx - r * 2, cy - r, cx + r * 2, cy + r],
                fill=(alpha, alpha + 2, int(alpha * 2.2)),
            )
        if visual_family == "light_paths":
            # Single golden-white streak along bottom third
            for thickness in range(3, 0, -1):
                alpha = 45 - thickness * 12
                draw.line(
                    [(int(W * 0.1), int(H * 0.72)), (int(W * 0.9), int(H * 0.65))],
                    fill=(alpha + 60, alpha + 50, alpha),
                    width=thickness,
                )

    elif visual_family == "contrast_waves":
        # High-contrast sine wave fields
        for row in range(0, H, 6):
            amplitude = 18 + (row / H) * 24
            for x in range(0, W, 2):
                y_off = int(math.sin(x / 60 + row / 40) * amplitude)
                y_px  = row + y_off
                if 0 <= y_px < H:
                    frac  = abs(math.sin(x / 80)) * 0.15
                    shade = int(frac * 200)
                    draw.point((x, y_px), fill=(shade, shade + 4, int(shade * 1.8)))

    elif visual_family == "particle_flow":
        # Structured particle cluster — not random
        import random
        rng = random.Random(42)
        for _ in range(380):
            x = int(rng.gauss(cx, W * 0.22))
            y = int(rng.gauss(cy + H * 0.08, H * 0.22))
            x = max(0, min(W - 1, x))
            y = max(0, min(H - 1, y))
            r = rng.randint(1, 3)
            brightness = rng.randint(18, 80)
            draw.ellipse([x - r, y - r, x + r, y + r],
                         fill=(brightness, brightness + 4, int(brightness * 2.2)))

    elif visual_family == "constellation_networks":
        # Minimal node network
        import random
        rng = random.Random(7)
        nodes = [(rng.randint(100, W - 100), rng.randint(100, H - 100)) for _ in range(14)]
        for i, (x1, y1) in enumerate(nodes):
            for x2, y2 in nodes[i + 1:]:
                dist = math.hypot(x2 - x1, y2 - y1)
                if dist < 260:
                    draw.line([(x1, y1), (x2, y2)], fill=(18, 28, 52), width=1)
        for x, y in nodes:
            r = 4
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(30, 55, 110))
            draw.ellipse([x - 1, y - 1, x + 1, y + 1], fill=(66, 160, 255))

    elif visual_family == "focus_rings":
        # Concentric rings from center
        for r_step, opacity in zip(range(60, 380, 55), [35, 28, 22, 18, 12, 8]):
            draw.ellipse(
                [cx - r_step, cy - r_step, cx + r_step, cy + r_step],
                outline=(opacity, opacity + 4, int(opacity * 2.8)),
                width=1,
            )
        # Center dot in Electric Blue
        draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=(66, 160, 255))

    else:
        # Default: radial gradient on deep navy
        for r in range(min(W, H) // 2, 0, -4):
            frac  = r / (min(W, H) / 2)
            shade = int(frac * 22)
            draw.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                fill=(shade, shade, int(shade * 1.1)),
            )

    # Shared: thin diagonal lines across all families
    for i in range(-6, 14):
        offset = i * 120
        draw.line([(offset, 0), (offset + H, H)], fill=(10, 14, 22), width=1)

    canvas = canvas.filter(ImageFilter.GaussianBlur(radius=2))
    buf = BytesIO()
    canvas.save(buf, "PNG")
    return buf.getvalue()


# ── AI image generation ────────────────────────────────────────────────────────

def _generate_ai_image(prompt: str, negative_prompt: str = "", log=print) -> tuple[bytes, str]:
    """
    Try OpenAI image generation (gpt-image-1, then dall-e-3).
    Returns (bytes, method_used) or raises RuntimeError.
    """
    import base64
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["NB_OPENAI_API_KEY"])

    errors: dict = {}
    for model, fmt in [("gpt-image-1", "b64_json"), ("dall-e-3", "url")]:
        try:
            kwargs: dict = dict(model=model, prompt=prompt, size="1024x1024", n=1)
            if fmt == "b64_json":
                kwargs["response_format"] = "b64_json"
            response = client.images.generate(**kwargs)
            item = response.data[0]
            if fmt == "b64_json":
                return base64.b64decode(item.b64_json), model
            else:
                with urllib.request.urlopen(item.url, timeout=30) as r:
                    return r.read(), model
        except Exception as exc:
            errors[model] = str(exc)[:120]

    raise RuntimeError(
        f"OpenAI image generation unavailable. "
        f"gpt-image-1: {errors.get('gpt-image-1', '?')} | "
        f"dall-e-3: {errors.get('dall-e-3', '?')}"
    )


def _generate_base_image(
    prompt: str,
    visual_family: str,
    negative_prompt: str = "",
    log=print,
) -> tuple[bytes, str]:
    """
    Generate base image: try OpenAI first, fall back to visual-family-aware programmatic.
    Returns (bytes, method_used).
    """
    if os.getenv("NB_OPENAI_API_KEY", ""):
        try:
            data, method = _generate_ai_image(prompt, negative_prompt, log=log)
            log(f"  Base image: AI ({method})")
            return data, method
        except Exception as exc:
            log(f"  OpenAI image unavailable ({exc.__class__.__name__}: {str(exc)[:80]})")
            log("  Falling back to programmatic base image…")

    data = _generate_programmatic_base(visual_family)
    log(f"  Base image: programmatic (Pillow, family={visual_family})")
    return data, "programmatic"


# ── Compositing ────────────────────────────────────────────────────────────────

def composite_image(base_bytes: bytes, hook_text: str) -> Image.Image:
    """
    Composite official logo + hook text onto a base image.
    Returns a 1080×1080 RGB image.
    Logo is overlaid from LOGO_PATH — never drawn by the image model.
    """
    W, H = IMAGE_SIZE
    hook = hook_text[:HOOK_MAX_CHARS].strip()

    base   = Image.open(BytesIO(base_bytes)).convert("RGBA").resize((W, H), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    canvas.paste(base, (0, 0))

    # Dark gradient overlay — heavier at top (text area) and bottom (logo area)
    grad      = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad)
    for y in range(H):
        if y < H * 0.55:
            alpha = int(190 * (y / (H * 0.55)) ** 0.6)
        else:
            frac  = (y - H * 0.55) / (H * 0.45)
            alpha = int(100 + 110 * frac)
        grad_draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    canvas = Image.alpha_composite(canvas, grad)

    draw = ImageDraw.Draw(canvas)

    # ── Hook text ─────────────────────────────────────────────────────────────
    padding    = 72
    font_hook  = _find_font(72)
    font_label = _find_font(26)
    max_text_w = W - padding * 2

    lines  = _wrap_text(hook, font_hook, max_text_w)
    line_h = int(72 * 1.25)
    block_h = len(lines) * line_h
    y_start = int(H * 0.38) - block_h // 2

    for i, line in enumerate(lines):
        bbox   = draw.textbbox((0, 0), line, font=font_hook)
        line_w = bbox[2] - bbox[0]
        x      = (W - line_w) // 2
        y      = y_start + i * line_h
        draw.text((x + 3, y + 3), line, font=font_hook, fill=(0, 0, 0, 180))
        draw.text((x, y), line, font=font_hook, fill=TEXT_COLOR + (255,))

    # Thin Electric Blue separator line
    sep_y = y_start + block_h + 28
    sep_w = min(200, W // 3)
    draw.line(
        [(W // 2 - sep_w // 2, sep_y), (W // 2 + sep_w // 2, sep_y)],
        fill=ELECTRIC_BLUE + (160,),
        width=2,
    )

    # "Never Blank" small label
    label = "Never Blank"
    bbox  = draw.textbbox((0, 0), label, font=font_label)
    lw    = bbox[2] - bbox[0]
    draw.text(
        ((W - lw) // 2, sep_y + 14),
        label,
        font=font_label,
        fill=(200, 210, 230, 200),
    )

    # ── Official logo — bottom right ───────────────────────────────────────────
    if LOGO_PATH.exists():
        vs       = _load_visual_system()
        size_ratio = vs.get("logo", {}).get("size_ratio", 0.22)
        margin     = vs.get("logo", {}).get("margin_px", 40)
        logo       = Image.open(LOGO_PATH).convert("RGBA")
        logo_w     = int(W * size_ratio)
        logo_h     = int(logo.height * (logo_w / logo.width))
        logo       = logo.resize((logo_w, logo_h), Image.LANCZOS)
        paste_x    = W - logo_w - margin
        paste_y    = H - logo_h - margin
        canvas.paste(logo, (paste_x, paste_y), logo)

    return canvas.convert("RGB")


# ── Cloudinary upload ──────────────────────────────────────────────────────────

def upload_to_cloudinary(image_path: Path, slug: str) -> str:
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
    Full pipeline: visual selection → base image → composite → Cloudinary.
    Writes image_url.txt and updates visual_registry.json.
    Returns the Cloudinary URL.
    """
    # Read draft
    blog_meta = json.loads((draft_dir / "blog_meta.json").read_text(encoding="utf-8"))
    metadata  = json.loads((draft_dir / "metadata.json").read_text(encoding="utf-8"))

    title       = metadata.get("title", "")
    observation = blog_meta.get("hook_sentence", title)
    content_goal = metadata.get("content_goal", "challenge")
    slug         = metadata.get("wix_slug", "post")

    # Load registry
    registry = load_registry()

    # Choose visual family + build image spec
    log("  Selecting visual family…")
    spec = choose_visual_family(title, observation, content_goal, registry, log=log)

    visual_family    = spec["visual_family"]
    dominant_palette = spec["dominant_palette"]
    image_prompt     = spec["image_prompt"]
    hook_text        = spec.get("hook_text", observation[:HOOK_MAX_CHARS])
    negative_prompt  = spec.get("negative_prompt", "")

    log(f"  Visual family: {visual_family}")
    log(f"  Hook text: {hook_text!r}")
    log(f"  Rationale: {spec.get('rationale', '')}")

    # Generate base image
    base_bytes, method = _generate_base_image(
        image_prompt, visual_family, negative_prompt, log=log
    )
    log(f"  Base image: {len(base_bytes) // 1024}KB [{method}]")

    # Composite
    log("  Compositing logo + hook text…")
    image = composite_image(base_bytes, hook_text)

    # Save locally
    images_dir.mkdir(parents=True, exist_ok=True)
    local_path = images_dir / "image.png"
    image.save(str(local_path), "PNG", optimize=True)
    log(f"  Saved: {local_path}  ({local_path.stat().st_size // 1024}KB)")

    # Upload to Cloudinary
    log("  Uploading to Cloudinary…")
    url = upload_to_cloudinary(local_path, slug)
    log(f"  Cloudinary URL: {url}")

    # Write image_url.txt (single URL reused across all platform publishers)
    url_file = draft_dir / "image_url.txt"
    url_file.write_text(url, encoding="utf-8")
    log(f"  Written: {url_file}")

    # Update visual registry
    registry = register_post(
        registry,
        content_slug    = slug,
        visual_family   = visual_family,
        dominant_palette = dominant_palette,
        hook_text        = hook_text,
        image_url        = url,
        source_topic     = title,
    )
    save_registry(registry)
    log(f"  Registry updated: {REGISTRY_PATH}")

    return url
