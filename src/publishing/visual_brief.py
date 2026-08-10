"""
src/publishing/visual_brief.py
Production boundary: editorial result → VisualBrief → image prompt.

Used by:
  - scripts/controlled_run.py (controlled end-to-end run)
  - scripts/generate_and_publish.py (production publishing path, TBD integration)

Both paths use the SAME implementation so the controlled run produces
an identical brief to what production would generate.

## VisualBrief

Typed output from build_visual_brief(). Contains all fields needed to:
  1. Call an image-generation API (_generate_base_image)
  2. Render overlay text (hook_text)
  3. Apply brand-safe negative prompting
  4. Record the provenance of the prompt in validation artifacts

## Negative prompt assembly

brand_exclusions:    read from visual_spec returned by choose_visual_family()
policy_exclusions:   passed via `policy_exclusion_tags` argument (controlled run supplies
                     AI-imagery exclusions; production supplies nothing extra)
Final negative_prompt = brand_exclusions + ", " + policy_exclusions (if any)

Neither the brand rules NOR the policy exclusions are hardcoded in this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.controlled_run.policy import ControlledRunPolicy


@dataclass
class VisualBrief:
    """
    Typed visual specification produced by build_visual_brief().

    All fields that influence the image-generation API call are present here.
    This object is the single source of truth for the image prompt — no other
    code should derive an image prompt from signal fields directly.
    """
    # From choose_visual_family
    visual_family:    str
    dominant_palette: str
    image_prompt:     str
    hook_text:        str
    negative_prompt:  str   # combined brand + policy exclusions
    logo_placement:   str
    rationale:        str

    # Provenance — recorded in validation artifacts
    angle_source:        str   # NEVER_BLANK_ANGLE from signal
    potential_hook:      str   # POTENTIAL_HOOK from signal
    target_audience:     str   # TARGET_AUDIENCE from signal
    article_summary:     str   # first 200 chars of blog body
    brand_name:          str
    policy_exclusions:   str   # exclusions added by policy (empty in production)

    # Channel-aware specs: per-channel dimensions and safe zones.
    # Populated from PLATFORM_SIZES in image_pipeline.py.
    # The primary channel's spec influences the image prompt (aspect ratio).
    channel_specs: dict = field(default_factory=dict)

    # Extra fields from choose_visual_family (card rhythm etc.)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "visual_family":    self.visual_family,
            "dominant_palette": self.dominant_palette,
            "image_prompt":     self.image_prompt,
            "hook_text":        self.hook_text,
            "negative_prompt":  self.negative_prompt,
            "logo_placement":   self.logo_placement,
            "rationale":        self.rationale,
            "_angle_source":    self.angle_source,
            "_never_blank_angle": self.angle_source,
            "_potential_hook":  self.potential_hook,
            "_target_audience": self.target_audience,
            "_article_summary": self.article_summary,
            "_brand_name":      self.brand_name,
            "_policy_exclusions": self.policy_exclusions,
            "channel_specs":    self.channel_specs,
        }
        d.update(self.extra)
        return d


# Controlled-run specific AI-imagery exclusions.
# These are NOT brand rules — they are safety exclusions specific to
# controlled-run visual validation (no humanoid AI imagery in test artifacts).
# Passed via policy_exclusion_tags; NOT hardcoded in the function body.
CR_POLICY_EXCLUSIONS = (
    "robots, humanoid AI figures, glowing brains, neural network visualizations, "
    "circuit boards, generic stock-AI imagery, text or typography inside image"
)


def build_visual_brief(
    *,
    signal: dict,
    article_result: dict,
    brand_name: str = "Never Blank",
    content_goal: str = "challenge",
    registry: dict,
    log=print,
    policy_exclusion_tags: str = "",
    channels: list | None = None,
) -> VisualBrief:
    """
    Build a VisualBrief from a signal and article result using production
    choose_visual_family().

    This is the SINGLE production implementation of the editorial → visual brief
    boundary. Both the controlled runner and the production publishing path must
    call this function.

    Args:
        signal:               Enriched signal dict.
        article_result:       Output of generate_article().
        brand_name:           Brand name for provenance annotation.
        content_goal:         Passed to choose_visual_family (e.g. "challenge").
        registry:             Image registry dict from load_registry().
        log:                  Logger callable (default: print).
        policy_exclusion_tags: Extra negative-prompt tags from policy/config.
                              Production passes "" (nothing extra).
                              Controlled run passes CR_POLICY_EXCLUSIONS.
                              Never hardcoded in this function.
        channels:             List of target channels (e.g. ["linkedin", "blog"]).
                              Used to build channel_specs with per-channel
                              dimensions and safe zones. The PRIMARY channel
                              (first in list or PRIMARY_CHANNEL from signal)
                              influences the image prompt aspect ratio.

    Returns:
        VisualBrief with all fields required for image generation, including
        channel_specs: {channel: {width, height, aspect_ratio, safe_zone_pct}}
    """
    from src.publishing.image_pipeline import choose_visual_family, PLATFORM_SIZES

    title       = signal.get("HEADLINE", "")
    observation = signal.get("NEVER_BLANK_ANGLE") or signal.get("CORE_FACT") or title
    company     = signal.get("REAL_COMPANY_EXAMPLE", "")

    platforms   = article_result.get("platforms", {})
    blog_data   = platforms.get("long", {})
    blog_body   = blog_data.get("body", "") if isinstance(blog_data, dict) else ""

    # Determine primary channel for image sizing
    effective_channels = channels or [signal.get("PRIMARY_CHANNEL", "linkedin"), "blog"]
    primary_channel    = effective_channels[0] if effective_channels else "linkedin"

    # Build channel_specs from PLATFORM_SIZES
    channel_specs: dict = {}
    for ch in effective_channels:
        size = PLATFORM_SIZES.get(ch)
        if size:
            w, h = size
            ratio = round(w / h, 4)
            channel_specs[ch] = {
                "width":         w,
                "height":        h,
                "aspect_ratio":  ratio,
                "aspect_label":  f"{w}×{h}",
                # Safe zone: content-safe inset as percentage of dimensions
                # Instagram 4:5 has tighter safe zones than LinkedIn 1.91:1.
                "safe_zone_pct": 0.10 if ch == "instagram" else 0.08,
            }

    # Primary channel's aspect ratio annotated in the image prompt
    primary_spec  = channel_specs.get(primary_channel, {})
    aspect_label  = primary_spec.get("aspect_label", "1080×1080")
    aspect_ratio  = primary_spec.get("aspect_ratio", 1.0)

    # Aspect-ratio hint appended to prompt so the image model knows the crop
    # (DALL-E 3: square, landscape 1792×1024, portrait 1024×1792)
    if aspect_ratio > 1.5:
        dalle_size = "landscape (1792×1024)"
    elif aspect_ratio < 0.8:
        dalle_size = "portrait (1024×1792)"
    else:
        dalle_size = "square (1024×1024)"

    spec = choose_visual_family(
        title        = title,
        observation  = observation,
        content_goal = content_goal,
        registry     = registry,
        log          = log,
        company      = company,
    )

    # Assemble negative prompt: brand rules (from spec) + policy exclusions
    brand_neg  = spec.get("negative_prompt", "")
    if policy_exclusion_tags:
        if brand_neg:
            combined_neg = f"{brand_neg}, {policy_exclusion_tags}"
        else:
            combined_neg = policy_exclusion_tags
    else:
        combined_neg = brand_neg

    # Annotate image_prompt with primary-channel aspect ratio context
    base_prompt   = spec.get("image_prompt", "")
    channel_hint  = f" [Primary channel: {primary_channel}, target {aspect_label}, {dalle_size}]"
    image_prompt  = f"{base_prompt}{channel_hint}" if base_prompt else base_prompt

    # Carry through any extra fields from choose_visual_family (card texture etc.)
    known_keys = {"visual_family", "dominant_palette", "image_prompt", "hook_text",
                  "negative_prompt", "logo_placement", "rationale"}
    extra = {k: v for k, v in spec.items() if k not in known_keys}

    return VisualBrief(
        visual_family    = spec.get("visual_family", ""),
        dominant_palette = spec.get("dominant_palette", ""),
        image_prompt     = image_prompt,
        hook_text        = spec.get("hook_text", ""),
        negative_prompt  = combined_neg,
        logo_placement   = spec.get("logo_placement", "bottom_right"),
        rationale        = spec.get("rationale", ""),
        angle_source     = observation,
        potential_hook   = signal.get("POTENTIAL_HOOK", ""),
        target_audience  = signal.get("TARGET_AUDIENCE", "founder"),
        article_summary  = blog_body[:200],
        brand_name       = brand_name,
        policy_exclusions = policy_exclusion_tags,
        channel_specs    = channel_specs,
        extra            = extra,
    )
