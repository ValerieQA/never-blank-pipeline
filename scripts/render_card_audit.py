"""
Card composition audit — renders all 8 test cases before/after.

Usage:
    python3 scripts/render_card_audit.py

Output:
    reports/card_audit/
        quote_card_NNN_before.png
        quote_card_NNN_after.png
        photo_NNN_before.png
        photo_NNN_after.png
        grid_preview_before.png   — 3×3 mosaic @ grid crop (square center)
        grid_preview_after.png
        comparison_NNN.png        — before | after side by side
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from PIL import Image, ImageDraw, ImageFont
from src.publishing.image_pipeline import (
    _generate_programmatic_base,
    _COL_QUOTE,
    _COL_PHOTO,
    _COL_LEGACY,
    _SEP_RATIO,
    ELECTRIC_BLUE,
    PLATFORM_SIZES,
    _fit_text_dynamic,
    _find_font,
    _wrap_text,
    _hex_to_rgb,
    _load_visual_system,
    LOGO_PATH,
    CARD_BACKGROUNDS,
    compose_quote_card,
    composite_for_platform,
    resize_for_platform,
)
from io import BytesIO

OUT = REPO / "reports" / "card_audit"
OUT.mkdir(parents=True, exist_ok=True)

PLATFORM = "instagram"
W, H = PLATFORM_SIZES[PLATFORM]  # 1080 × 1350

TEST_CASES = [
    ("short",       "Presence matters."),
    ("medium",      "5 signals your brand is invisible to AI search."),
    ("long",        "A single croissant photo did what months of marketing couldn't: it filled every seat, every day, for four months."),
    ("very_long",   "How AI search decides who to recommend — and what it ignores. Myth: AI recommends whoever has the best website. Reality: AI surfaces whoever appears most consistently in context."),
    ("long_word",   "Antitrust concerns stall a $110 billion merger."),
    ("quote_card",  "The Compound Presence model: why consistent beats brilliant."),
    ("photo_ovrl",  "Controlling distribution to stabilize pricing and regain market share."),
    ("legacy_sq",   "Workforce cut signals challenges ahead."),
]

TEXTURE = "light_paths"   # neutral family — no center focal


# ── Before: reproduce pre-fix behaviour ────────────────────────────────────────

def _compose_quote_before(hook: str) -> Image.Image:
    """Reproduce quote card as it was before the column fix."""
    vs = _load_visual_system()
    bg_hex   = vs["palette"]["dark_core"]["colors"].get("deep_navy", "#050B16")
    bg_color = _hex_to_rgb(bg_hex)
    top_c    = _hex_to_rgb(vs["palette"]["dark_core"]["colors"].get("steel_blue", "#1D2E4A"))
    text_color   = (255, 255, 255)
    label_color  = (185, 200, 225)

    wash = Image.new("RGB", (W, H))
    wd = ImageDraw.Draw(wash)
    for y in range(H):
        t = y / H
        color = tuple(int(top_c[i] * (1 - t) + bg_color[i] * t) for i in range(3))
        wd.line([(0, y), (W, y)], fill=color)

    texture_bytes = _generate_programmatic_base(TEXTURE)
    texture_img   = Image.open(BytesIO(texture_bytes)).convert("RGB")
    textured      = resize_for_platform(texture_img, PLATFORM)
    canvas        = Image.blend(wash, textured, 0.6)

    text_zone_top    = int(H * 0.22)
    text_zone_bottom = int(H * 0.74)

    # OLD padding-derived max_tw (regression state)
    padding_old = max(64, int(W * 0.13))
    max_tw_old  = W - padding_old * 2   # 800px = 74%

    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd   = ImageDraw.Draw(band)
    fade_px = int(H * 0.08)
    for y in range(text_zone_top, text_zone_bottom):
        edge_dist = min(y - text_zone_top, text_zone_bottom - y)
        fade = min(edge_dist / fade_px, 1.0)
        bd.line([(0, y), (W, y)], fill=(*bg_color, int(150 * fade)))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), band).convert("RGB")
    draw   = ImageDraw.Draw(canvas)

    max_th     = int((text_zone_bottom - text_zone_top) * 0.82)
    font_start = max(28, int(W * 0.05))
    font, lines = _fit_text_dynamic(hook, max_tw_old, max_th, font_start=font_start, font_min=24, max_lines=5, weight=600)
    line_h  = int(font.size * 1.42)
    block_h = len(lines) * line_h
    zone_center = (text_zone_top + text_zone_bottom) // 2
    y_start     = zone_center - block_h // 2

    for i, line in enumerate(lines):
        bbox   = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x      = (W - line_w) // 2
        draw.text((x, y_start + i * line_h), line, font=font, fill=text_color)

    sep_y = y_start + block_h + max(28, int(H * 0.035))
    sep_w = min(int(W * 0.14), 140)   # OLD sep_w
    draw.line([(W//2 - sep_w//2, sep_y), (W//2 + sep_w//2, sep_y)], fill=ELECTRIC_BLUE, width=2)

    font_label = _find_font(max(18, int(W * 0.02)), weight=500)
    label = "NEVER BLANK"
    lb    = draw.textbbox((0, 0), label, font=font_label)
    lw    = lb[2] - lb[0]
    draw.text(((W - lw) // 2, sep_y + max(16, int(H * 0.018))), label, font=font_label, fill=label_color)

    return canvas


def _compose_photo_before(hook: str) -> Image.Image:
    """Photo overlay card before fix."""
    base_bytes = _generate_programmatic_base(TEXTURE)
    base = Image.open(BytesIO(base_bytes)).convert("RGBA")
    base = base.resize((W, H), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    canvas.paste(base, (0, 0))

    from PIL import ImageDraw as ID2
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd   = ID2.Draw(grad)
    for y in range(H):
        if y < H * 0.55:
            alpha = int(200 * (y / (H * 0.55)) ** 0.55)
        else:
            frac  = (y - H * 0.55) / (H * 0.45)
            alpha = int(110 + 110 * frac)
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    canvas = Image.alpha_composite(canvas, grad)
    draw   = ImageDraw.Draw(canvas)

    # OLD max_tw
    padding_old = max(40, int(W * 0.06))
    max_tw_old  = W - padding_old * 2  # 952px = 88%
    max_th      = int(H * 0.45)
    font_start  = max(28, int(W * 0.055))

    font, lines = _fit_text_dynamic(hook, max_tw_old, max_th, font_start=font_start)
    line_h  = int(font.size * 1.30)
    block_h = len(lines) * line_h
    y_start = int(H * 0.38) - block_h // 2

    for i, line in enumerate(lines):
        bbox   = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x      = (W - line_w) // 2
        y      = y_start + i * line_h
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

    sep_y = y_start + block_h + max(16, int(H * 0.022))
    sep_w = min(int(W * 0.22), 220)
    draw.line([(W//2 - sep_w//2, sep_y), (W//2 + sep_w//2, sep_y)], fill=ELECTRIC_BLUE + (160,), width=2)

    font_label = _find_font(max(18, int(W * 0.022)))
    label = "Never Blank"
    lb    = draw.textbbox((0, 0), label, font=font_label)
    lw    = lb[2] - lb[0]
    draw.text(((W - lw) // 2, sep_y + max(10, int(H * 0.012))), label, font=font_label, fill=(200, 210, 230, 200))

    return canvas.convert("RGB")


# ── Grid preview crop (Instagram: square center of 4:5) ────────────────────────

def _grid_crop(img: Image.Image) -> Image.Image:
    """Crop to the Instagram grid square (center square of a 4:5 card)."""
    w, h = img.size
    side  = w  # square = card width
    top   = (h - side) // 2
    return img.crop((0, top, side, top + side))


def _side_by_side(before: Image.Image, after: Image.Image, label: str) -> Image.Image:
    """Stitch before|after into a comparison image."""
    gap  = 12
    pad  = 48
    font = _find_font(32)
    total_w = before.width + after.width + gap + pad * 2
    total_h = max(before.height, after.height) + pad * 2 + 50
    comp = Image.new("RGB", (total_w, total_h), (18, 18, 18))
    comp.paste(before, (pad, pad + 50))
    comp.paste(after,  (pad + before.width + gap, pad + 50))
    draw = ImageDraw.Draw(comp)
    draw.text((pad, 12), f"BEFORE  |  AFTER   —  {label}", font=font, fill=(200, 200, 200))
    return comp


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    grid_before_crops = []
    grid_after_crops  = []

    for slug, hook in TEST_CASES:
        print(f"  Rendering: {slug}…")

        # Choose which render pair
        if slug in ("quote_card", "short", "medium", "long", "very_long", "long_word"):
            # quote card path
            before = _compose_quote_before(hook)
            after  = compose_quote_card(hook, PLATFORM, "dark_insight_card", TEXTURE)
        elif slug == "photo_ovrl":
            before_bytes = _generate_programmatic_base(TEXTURE)
            before = _compose_photo_before(hook)
            after  = composite_for_platform(before_bytes, hook, PLATFORM)
        else:
            # legacy square
            from src.publishing.image_pipeline import composite_image
            base_bytes = _generate_programmatic_base(TEXTURE)
            # "before" for legacy is same function — show as-is; column token already applied
            # We reconstruct before manually
            from PIL import Image as Img
            base_bytes2 = _generate_programmatic_base(TEXTURE)
            before = _compose_photo_before(hook)
            after  = composite_for_platform(base_bytes2, hook, "threads")  # 1:1

        before.save(OUT / f"{slug}_before.png")
        after.save(OUT / f"{slug}_after.png")

        comp = _side_by_side(before, after, slug)
        comp.save(OUT / f"{slug}_comparison.png")

        grid_before_crops.append(_grid_crop(before).resize((360, 360), Image.LANCZOS))
        grid_after_crops.append(_grid_crop(after).resize((360, 360), Image.LANCZOS))

    # Build 3×3 grid mosaics (use first 9, pad with blank if fewer)
    def _mosaic(crops: list, name: str):
        cols, rows = 3, 3
        gw, gh = 360, 360
        mosaic = Image.new("RGB", (cols * gw, rows * gh), (10, 10, 10))
        for idx, crop in enumerate(crops[:9]):
            r, c = divmod(idx, cols)
            mosaic.paste(crop, (c * gw, r * gh))
        mosaic.save(OUT / f"grid_preview_{name}.png")
        print(f"  Grid mosaic → reports/card_audit/grid_preview_{name}.png")

    _mosaic(grid_before_crops, "before")
    _mosaic(grid_after_crops,  "after")

    print(f"\n  Done. {len(TEST_CASES) * 3 + 2} files in reports/card_audit/")
    print("  Open comparison_*.png files for before|after view.")
    print("  Open grid_preview_before/after.png to check Instagram grid crop.")


if __name__ == "__main__":
    main()
