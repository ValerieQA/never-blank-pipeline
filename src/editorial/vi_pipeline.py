"""
Never Blank — Visibility Intelligence Generation Pipeline.

Architectural principle — Partial Regeneration:
    Recognition content is generated as a narrative chain where each stage
    depends on the previous one. Partial regeneration is therefore unsafe.

    Visibility Intelligence content is generated as a structured object.
    Individual platform outputs are independent of each other. A failed
    field may be regenerated individually without regenerating the entire
    package. This is an intentional property of the VI design, not a detail.

Flow:
    VisibilityQueueItem
    → _build_prompt()        — assemble system + user from YAML + variables
    → chat_parsed()          — single LLM call → VIGeneratedOutput (strict schema)
    → _check_constraints()   → list[RepairRequest]
    → _repair_field()        — targeted repair call per failed field
    → to_generated_package() — anti-corruption mapper → _generated.json format
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from src.strategy.models import (
    BrandConcept,
    ProductCategory,
    RepairRequest,
    StrategicTopic,
    VIGeneratedOutput,
    VisibilityQueueItem,
)
from src.utils.config_loader import load_prompt, load_yaml
from src.utils.llm_client import chat_parsed, model_article
from src.utils.logger import get_logger

log = get_logger("editorial.vi_pipeline")

_MAX_REPAIRS = 2          # max targeted repair attempts per field
_THREADS_MAX_CHARS = 280
_LINKEDIN_MAX_WORDS = 220
_INSTAGRAM_MAX_WORDS = 150
_TELEGRAM_MAX_WORDS = 200
_BLOG_MIN_WORDS = 300
_BLOG_MAX_WORDS = 700


# ── Prompt assembly ────────────────────────────────────────────────────────────

def _format_key_points(points: list[str]) -> str:
    if not points:
        return "(no specific key points provided — use your editorial judgment)"
    return "\n".join(f"- {p}" for p in points)


def _brand_concept_label(bc: Optional[BrandConcept]) -> str:
    if bc is None:
        return "(none — use general Never Blank presence principles)"
    return bc.value.replace("_", " ").title()


def _load_format_modifier(content_format: str) -> str:
    try:
        data = load_yaml("prompts/visibility/_format_modifiers.yaml")
        return data.get("modifiers", {}).get(content_format, "")
    except Exception as exc:
        log.warning("Could not load format modifier for '%s': %s", content_format, exc)
        return ""


def _build_prompt(
    queue_item: VisibilityQueueItem,
    strategy_context: dict,
    cta_mode: str,
) -> tuple[str, str]:
    """Return (system, user) strings for the LLM call."""
    category_key = f"visibility/{queue_item.product_category.value}"
    format_modifier = _load_format_modifier(queue_item.content_format)

    prompt_data = load_prompt(category_key, variables={
        "title":                      queue_item.title,
        "strategic_topic":            queue_item.strategic_topic.value.replace("_", " "),
        "brand_concept":              _brand_concept_label(queue_item.brand_concept),
        "target_audience":            queue_item.target_audience or "small B2B service businesses",
        "key_points":                 _format_key_points(queue_item.key_points),
        "format_instructions":        format_modifier or "(no specific format — use the category default structure)",
        "strategy_primary_message":   strategy_context.get("primary_message", ""),
        "strategy_selected_problem":  strategy_context.get("selected_problem", ""),
        "strategy_desired_realization": strategy_context.get("desired_reader_realization", ""),
        "cta_mode":                   cta_mode,
    })
    return prompt_data["system"], prompt_data["user"]


# ── Constraint validation ──────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


def _check_constraints(output: VIGeneratedOutput) -> list[RepairRequest]:
    """Return repair requests for fields that violate content constraints.

    Schema validation (non-empty, threads min 3) is handled by VIGeneratedOutput
    validators at parse time. This function checks semantic/length constraints
    that require counting words or characters.
    """
    repairs: list[RepairRequest] = []

    blog_words = _word_count(output.blog_article)
    if blog_words < _BLOG_MIN_WORDS:
        repairs.append(RepairRequest(
            field_name="blog_article",
            current_value=output.blog_article,
            failed_constraints=[f"min_words={_BLOG_MIN_WORDS} (actual={blog_words})"],
        ))
    elif blog_words > _BLOG_MAX_WORDS:
        repairs.append(RepairRequest(
            field_name="blog_article",
            current_value=output.blog_article,
            failed_constraints=[f"max_words={_BLOG_MAX_WORDS} (actual={blog_words})"],
        ))

    li_words = _word_count(output.linkedin_post)
    if li_words > _LINKEDIN_MAX_WORDS:
        repairs.append(RepairRequest(
            field_name="linkedin_post",
            current_value=output.linkedin_post,
            failed_constraints=[f"max_words={_LINKEDIN_MAX_WORDS} (actual={li_words})"],
        ))

    ig_words = _word_count(output.instagram_caption)
    if ig_words > _INSTAGRAM_MAX_WORDS:
        repairs.append(RepairRequest(
            field_name="instagram_caption",
            current_value=output.instagram_caption,
            failed_constraints=[f"max_words={_INSTAGRAM_MAX_WORDS} (actual={ig_words})"],
        ))

    tg_words = _word_count(output.telegram_text)
    if tg_words > _TELEGRAM_MAX_WORDS:
        repairs.append(RepairRequest(
            field_name="telegram_text",
            current_value=output.telegram_text,
            failed_constraints=[f"max_words={_TELEGRAM_MAX_WORDS} (actual={tg_words})"],
        ))

    long_threads = [
        f"item[{i}]: {len(t)} chars"
        for i, t in enumerate(output.threads_sequence)
        if len(t) > _THREADS_MAX_CHARS
    ]
    if long_threads:
        repairs.append(RepairRequest(
            field_name="threads_sequence",
            current_value="\n---\n".join(output.threads_sequence),
            failed_constraints=[f"max_chars_per_item={_THREADS_MAX_CHARS}", *long_threads],
        ))

    return repairs


# ── Targeted repair ────────────────────────────────────────────────────────────

_REPAIR_SYSTEM = """You are a precise content editor for Never Blank.
You will receive one content field that failed a constraint check.
Your task: rewrite ONLY that field to satisfy all listed constraints.
Do not change the core message, insight, or brand voice.
Return ONLY the corrected field content — no explanation, no preamble."""


def _repair_field(
    req: RepairRequest,
    queue_item: VisibilityQueueItem,
    output: VIGeneratedOutput,
) -> str:
    """Make one targeted repair call for a single failed field.

    Returns the repaired field value. Does not mutate output.
    """
    constraints_block = "\n".join(f"- {c}" for c in req.failed_constraints)
    user = (
        f"Field: {req.field_name}\n\n"
        f"Failed constraints:\n{constraints_block}\n\n"
        f"Current value:\n{req.current_value}\n\n"
        f"Post title (for context): {queue_item.title}\n"
        f"Platform: {req.field_name.split('_')[0]}\n\n"
        f"Rewrite the field to satisfy all constraints. "
        f"Keep the Never Blank voice and the same core insight."
    )
    log.info("Repairing field '%s' — constraints: %s", req.field_name, req.failed_constraints)
    from src.utils.llm_client import chat
    return chat(_REPAIR_SYSTEM, user, model=model_article())


def _apply_repairs(
    output: VIGeneratedOutput,
    repairs: list[RepairRequest],
    queue_item: VisibilityQueueItem,
) -> VIGeneratedOutput:
    """Apply targeted repairs and return a new VIGeneratedOutput instance."""
    data = output.model_dump()
    for req in repairs:
        for attempt in range(_MAX_REPAIRS):
            repaired_value = _repair_field(req, queue_item, output)
            # For threads_sequence, the repair returns items joined by "---"
            if req.field_name == "threads_sequence":
                items = [t.strip() for t in repaired_value.split("---") if t.strip()]
                data["threads_sequence"] = items
            else:
                data[req.field_name] = repaired_value

            # Re-check this specific constraint
            test_output = VIGeneratedOutput(**data)
            remaining = [r for r in _check_constraints(test_output) if r.field_name == req.field_name]
            if not remaining:
                log.info("Repair succeeded for '%s' on attempt %d", req.field_name, attempt + 1)
                break
            log.warning(
                "Repair attempt %d/%d for '%s' still fails: %s",
                attempt + 1, _MAX_REPAIRS, req.field_name, remaining[0].failed_constraints,
            )

    return VIGeneratedOutput(**data)


# ── Anti-corruption mapper ─────────────────────────────────────────────────────

def to_generated_package(
    vi_output: VIGeneratedOutput,
    queue_item: VisibilityQueueItem,
    strategy_context: dict,
) -> dict:
    """Map VIGeneratedOutput (domain model) to _generated.json transport format.

    This is the only place that knows about both layers. Adding a new field to
    _generated.json or changing the LLM schema does not require touching the other.
    """
    return {
        "queue_item_id":       queue_item.id,
        "headline":            vi_output.headline,
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "strategy_id":         strategy_context.get("strategy_id", ""),
        "strategy_started_at": strategy_context.get("started_at", ""),
        "wix_url":             "",          # populated after Wix publish
        "blog_article":        vi_output.blog_article,
        "linkedin_post":       vi_output.linkedin_post,
        "facebook_post":       vi_output.facebook_post,
        "instagram_caption":   vi_output.instagram_caption,
        "threads_sequence":    vi_output.threads_sequence,
        "telegram_text":       vi_output.telegram_text,
        "vi_metadata": {
            "product_category": queue_item.product_category.value,
            "content_format":   queue_item.content_format,
            "strategic_topic":  queue_item.strategic_topic.value,
            "brand_concept":    queue_item.brand_concept.value if queue_item.brand_concept else None,
        },
    }


# ── Main entry point ───────────────────────────────────────────────────────────

def generate_vi_post(
    queue_item: VisibilityQueueItem,
    strategy_context: dict,
    cta_mode: str = "none",
) -> dict:
    """Generate a Visibility Intelligence post and return the generated package.

    Args:
        queue_item:       Typed queue entry from visibility_queue.jsonl.
        strategy_context: Dict from get_strategy_context() — same contract as
                          recognition pipeline. Injected into prompts for brand
                          alignment but does not change generation structure.
        cta_mode:         CTA directive. Passed through to prompts; the LLM does
                          not decide whether to include a CTA.

    Returns:
        dict in _generated.json format, compatible with existing publisher code.
        Includes a "vi_metadata" key with visibility-specific fields (unknown to
        the recognition publisher — safely ignored).

    Raises:
        ValueError: if the LLM returns content that fails schema validation after
                    all repair attempts. This should be treated as a generation
                    failure and the run should be retried or skipped.
    """
    log.info(
        "VI generation: id=%s category=%s format=%s",
        queue_item.id, queue_item.product_category.value, queue_item.content_format,
    )

    system, user = _build_prompt(queue_item, strategy_context, cta_mode)

    log.info("VI: calling LLM (structured output)…")
    output: VIGeneratedOutput = chat_parsed(
        system=system,
        user=user,
        response_model=VIGeneratedOutput,
        model=model_article(),
    )
    log.info("VI: LLM call complete — headline: %s", output.headline[:60])

    repairs = _check_constraints(output)
    if repairs:
        log.warning(
            "VI: %d field(s) need repair: %s",
            len(repairs), [r.field_name for r in repairs],
        )
        output = _apply_repairs(output, repairs, queue_item)
        remaining = _check_constraints(output)
        if remaining:
            log.warning(
                "VI: %d field(s) still failing after repair (publishing anyway): %s",
                len(remaining), [(r.field_name, r.failed_constraints) for r in remaining],
            )
    else:
        log.info("VI: all constraints passed — no repairs needed")

    package = to_generated_package(output, queue_item, strategy_context)
    log.info("VI: generation complete — queue_item_id=%s", queue_item.id)
    return package
