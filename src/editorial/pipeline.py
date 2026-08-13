"""
Editorial Engine V2 — orchestrator
Spec: docs/NARRATIVE_SPINE.md, docs/EDITORIAL_ENGINE_V2.md

Single entry point: generate_article(signal) runs:
  Pattern Extractor (mandatory gate) ->
  Decision Lens Lite -> Narrative Spine -> Hook Engine -> Reader Context ->
  Discovery Builder -> Story Assembly -> Never Blank Voice -> Platform Composer,
  in that order, and returns the finished structured_article plus all five platform
  bodies plus the pattern dict.

Each stage (except Pattern Extractor) is retried once on a schema-validation failure
(ValueError raised by the stage module). A second failure raises ArticleGenerationError.
Pattern Extractor rejection raises ArticleGenerationError immediately (no retry useful).

Per the specs' own principle: a failed generation should skip publishing that signal,
not publish a generic article to fill the gap.
"""

from typing import Callable, Mapping

from src.editorial.pattern_extractor import extract_pattern, SignalRejectedError
from src.editorial.decision_lens_lite import generate_decision_lens
from src.editorial.narrative_spine import build_narrative_spine
from src.editorial.hook_engine import generate_hook
from src.editorial.reader_context import build_reader_context
from src.editorial.discovery_builder import build_discovery
from src.editorial.story_assembly import assemble_story
from src.editorial.never_blank_voice import finalize_article
from src.editorial.platform_composer import compose_platforms
from src.strategy.execution_context import (
    DecisionLensEditorialStrategyView,
    LinkedInStrategyView,
    WixStrategyView,
)
from src.utils.logger import get_logger

log = get_logger("editorial.pipeline")


class ArticleGenerationError(Exception):
    """Raised when a pipeline stage fails schema validation twice in a row,
    or when the Pattern Extractor rejects the signal."""

    def __init__(self, stage: str, original: Exception):
        self.stage = stage
        self.original = original
        super().__init__(f"stage {stage!r} failed after retry: {original}")


def _run_stage(stage_name: str, fn: Callable, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        log.warning("Stage %r failed on first attempt (%s) — retrying once", stage_name, exc)
        try:
            return fn(*args, **kwargs)
        except ValueError as exc2:
            raise ArticleGenerationError(stage_name, exc2) from exc2


def generate_article(
    signal: dict,
    cta_mode: str = "none",
    strategy_context: DecisionLensEditorialStrategyView | Mapping[str, object] | None = None,
    *,
    wix_strategy: WixStrategyView | None = None,
    linkedin_strategy: LinkedInStrategyView | None = None,
) -> dict:
    """
    Run the full Editorial Engine V2 pipeline for one enriched signal.

    Args:
        signal: Enriched signal dict from the Investigation Layer.
        cta_mode: Explicit campaign directive for CTA. One of:
            none | reflection | diagnostic | example_request | direct_conversation.
            Defaults to "none". The model does NOT decide this — it is passed in.
        strategy_context: Typed strategy view on the canonical Release 1 path.
            A mapping remains accepted only for legacy/non-canonical callers.
        wix_strategy: Declared Wix composition view for controlled R1.
        linkedin_strategy: Declared LinkedIn composition view for controlled R1.

    Returns:
        {
          "pattern": {...},              # Pattern Extractor output
          "decision_lens": {...},
          "narrative_spine": {...},
          "structured_article": {...},   # Never Blank Voice output
          "platforms": {                 # Platform Composer output
            "long": {"word_count": int, "body": str},
            "reading": {...}, "medium": {...}, "instagram": {...}, "short": {...},
          },
        }

    Raises ArticleGenerationError if:
    - Pattern Extractor rejects the signal (stage = "pattern_extractor")
    - Any downstream stage fails schema validation twice
    """
    sig_id = signal.get("SIGNAL_ID", "unknown")
    log.info("Editorial Engine: starting generation for signal %s", sig_id)

    # Stage 0: Pattern Extractor — mandatory gate
    try:
        pattern = _run_stage("pattern_extractor", extract_pattern, signal)
    except SignalRejectedError as exc:
        raise ArticleGenerationError("pattern_extractor", exc) from exc

    # Merge pattern fields into signal so downstream stages receive owner-centered fields.
    # Pattern fields override same-named signal fields.
    # Strategy context is injected last as STRATEGY_* keys (no collision with signal/pattern keys).
    enriched = {**signal, **pattern}
    if strategy_context:
        if isinstance(strategy_context, DecisionLensEditorialStrategyView):
            prompt_values = strategy_context.legacy_prompt_values()
        else:
            prompt_values = strategy_context
        enriched["STRATEGY_PRIMARY_MESSAGE"]    = prompt_values.get("primary_message", "")
        enriched["STRATEGY_SELECTED_PROBLEM"]   = prompt_values.get("selected_problem", "")
        enriched["STRATEGY_DESIRED_REALIZATION"] = prompt_values.get("desired_reader_realization", "")
        enriched["STRATEGY_COMPOUND_ROLE"]      = prompt_values.get("compound_presence_role", "")
        enriched["STRATEGY_ID"]                 = prompt_values.get("strategy_id", "")
        log.debug("Strategy context injected into enriched signal: strategy_id=%s",
                  prompt_values.get("strategy_id", "none"))

    decision_lens = _run_stage("decision_lens_lite", generate_decision_lens, enriched)
    spine = _run_stage("narrative_spine", build_narrative_spine, decision_lens, enriched)
    hook = _run_stage("hook_engine", generate_hook, spine, decision_lens, enriched)
    reader_context = _run_stage("reader_context", build_reader_context, enriched)
    discovery = _run_stage("discovery_builder", build_discovery, hook, spine, decision_lens, enriched)
    story = _run_stage("story_assembly", assemble_story, discovery, spine, decision_lens, enriched)
    structured_article = _run_stage(
        "never_blank_voice", finalize_article,
        hook, reader_context, discovery, story, spine, decision_lens, enriched, cta_mode,
    )
    platforms = _run_stage(
        "platform_composer",
        compose_platforms,
        structured_article,
        cta_mode=cta_mode,
        wix_strategy=wix_strategy,
        linkedin_strategy=linkedin_strategy,
    )

    log.info("Editorial Engine: generation complete for signal %s", sig_id)
    return {
        "pattern": pattern,
        "decision_lens": decision_lens,
        "narrative_spine": spine,
        "structured_article": structured_article,
        "platforms": platforms,
    }
