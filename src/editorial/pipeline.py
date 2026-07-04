"""
Editorial Engine V2 — orchestrator
Spec: docs/NARRATIVE_SPINE.md, docs/EDITORIAL_ENGINE_V2.md

Single entry point: generate_article(signal) runs Decision Lens Lite -> Narrative
Spine -> Hook Engine -> Reader Context -> Discovery Builder -> Story Assembly ->
Never Blank Voice -> Platform Composer, in that order, and returns the finished
structured_article plus all five platform bodies.

Each stage is retried once on a schema-validation failure (ValueError raised by the
stage module). A second failure raises ArticleGenerationError - this pipeline does
not degrade to worse content on failure. Per the specs' own principle: a failed
generation should skip publishing that signal, not publish a generic article to
fill the gap.
"""

from typing import Callable

from src.editorial.decision_lens_lite import generate_decision_lens
from src.editorial.narrative_spine import build_narrative_spine
from src.editorial.hook_engine import generate_hook
from src.editorial.reader_context import build_reader_context
from src.editorial.discovery_builder import build_discovery
from src.editorial.story_assembly import assemble_story
from src.editorial.never_blank_voice import finalize_article
from src.editorial.platform_composer import compose_platforms
from src.utils.logger import get_logger

log = get_logger("editorial.pipeline")


class ArticleGenerationError(Exception):
    """Raised when a pipeline stage fails schema validation twice in a row."""

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


def generate_article(signal: dict) -> dict:
    """
    Run the full Editorial Engine V2 pipeline for one enriched signal.

    Returns:
        {
          "decision_lens": {...},
          "narrative_spine": {...},
          "structured_article": {...},   # Never Blank Voice output
          "platforms": {                 # Platform Composer output
            "long": {"word_count": int, "body": str},
            "reading": {...}, "medium": {...}, "instagram": {...}, "short": {...},
          },
        }

    Raises ArticleGenerationError if any stage fails schema validation twice.
    """
    sig_id = signal.get("SIGNAL_ID", "unknown")
    log.info("Editorial Engine: starting generation for signal %s", sig_id)

    decision_lens = _run_stage("decision_lens_lite", generate_decision_lens, signal)
    spine = _run_stage("narrative_spine", build_narrative_spine, decision_lens, signal)
    hook = _run_stage("hook_engine", generate_hook, spine, decision_lens, signal)
    reader_context = _run_stage("reader_context", build_reader_context, signal)
    discovery = _run_stage("discovery_builder", build_discovery, hook, spine, decision_lens, signal)
    story = _run_stage("story_assembly", assemble_story, discovery, spine, decision_lens, signal)
    structured_article = _run_stage(
        "never_blank_voice", finalize_article,
        hook, reader_context, discovery, story, spine, decision_lens, signal,
    )
    platforms = _run_stage("platform_composer", compose_platforms, structured_article)

    log.info("Editorial Engine: generation complete for signal %s", sig_id)
    return {
        "decision_lens": decision_lens,
        "narrative_spine": spine,
        "structured_article": structured_article,
        "platforms": platforms,
    }
