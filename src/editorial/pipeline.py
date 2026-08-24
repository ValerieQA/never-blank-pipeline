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
from src.research.evidence import NormalizedResearchArtifact

from src.editorial.pattern_extractor import extract_pattern, SignalRejectedError
from src.editorial.decision_lens_lite import generate_decision_lens
from src.editorial.narrative_spine import build_narrative_spine
from src.editorial.hook_engine import generate_hook
from src.editorial.reader_context import build_reader_context
from src.editorial.discovery_builder import build_discovery
from src.editorial.story_assembly import assemble_story
from src.editorial.never_blank_voice import finalize_article
from src.run.call_budget import RunCallBudgetExceededError
from src.editorial.platform_composer import CompositionRejected, compose_platforms
from src.editorial.sources_of_record import source_citation_values
from src.strategy.execution_context import (
    AudienceSelection,
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


def _record_rejection(sink, stage_name: str, attempt: int, exc: Exception) -> None:
    """Capture a composition our own validator refused (#191).

    Only rejections that carry their generated body are recorded; ordinary
    stage failures have nothing to preserve. Never touches provider data.
    """
    if sink is None or not isinstance(exc, CompositionRejected):
        return
    sink.append({
        "stage": stage_name,
        "format": exc.format_key,
        "attempt": attempt,
        "validation_error": exc.validation_error,
        "body": exc.body,
    })


def _run_stage(stage_name: str, fn: Callable, *args, rejected_sink=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        _record_rejection(rejected_sink, stage_name, 1, exc)
        log.warning("Stage %r failed on first attempt (%s) — retrying once", stage_name, exc)
        try:
            return fn(*args, **kwargs)
        except ValueError as exc2:
            _record_rejection(rejected_sink, stage_name, 2, exc2)
            raise ArticleGenerationError(stage_name, exc2) from exc2


def generate_article(
    signal: dict,
    cta_mode: str = "none",
    strategy_context: DecisionLensEditorialStrategyView | Mapping[str, object] | None = None,
    *,
    wix_strategy: WixStrategyView | None = None,
    linkedin_strategy: LinkedInStrategyView | None = None,
    audience_selection: AudienceSelection | None = None,
    research_artifact: NormalizedResearchArtifact | None = None,
    editorial_role_rules: "str | dict[str, str] | None" = None,
    composer_formats: "tuple[str, ...] | None" = None,
    closing_contract: str | None = None,
    rejected_sink: "list | None" = None,
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
    enriched = {**signal, **pattern}
    typed_strategy = (
        strategy_context
        if isinstance(strategy_context, DecisionLensEditorialStrategyView)
        else None
    )
    if strategy_context is not None and typed_strategy is None:
        # Legacy/non-canonical callers retain their mapping adapter. Controlled
        # R1 never enters this branch and passes typed views directly.
        enriched["STRATEGY_PRIMARY_MESSAGE"] = strategy_context.get("primary_message", "")
        enriched["STRATEGY_SELECTED_PROBLEM"] = strategy_context.get("selected_problem", "")
        enriched["STRATEGY_DESIRED_REALIZATION"] = strategy_context.get("desired_reader_realization", "")
        enriched["STRATEGY_COMPOUND_ROLE"] = strategy_context.get("compound_presence_role", "")
        enriched["STRATEGY_ID"] = strategy_context.get("strategy_id", "")
    if typed_strategy is not None and audience_selection is None:
        raise ArticleGenerationError(
            "audience_selection", ValueError("typed strategy requires explicit audience selection")
        )
    selected_cta = typed_strategy.cta(cta_mode) if typed_strategy is not None else None

    if typed_strategy is None:
        decision_lens = _run_stage("decision_lens_lite", generate_decision_lens, enriched)
    else:
        decision_lens = _run_stage(
            "decision_lens_lite", generate_decision_lens,
            enriched, typed_strategy, audience_selection, research_artifact,
        )
    spine = _run_stage("narrative_spine", build_narrative_spine, decision_lens, enriched)
    hook = _run_stage("hook_engine", generate_hook, spine, decision_lens, enriched)
    reader_context = _run_stage("reader_context", build_reader_context, enriched)
    discovery = _run_stage("discovery_builder", build_discovery, hook, spine, decision_lens, enriched)
    story = _run_stage("story_assembly", assemble_story, discovery, spine, decision_lens, enriched)
    voice_args = (
        hook, reader_context, discovery, story, spine, decision_lens, enriched, cta_mode
    )
    if typed_strategy is None:
        structured_article = _run_stage("never_blank_voice", finalize_article, *voice_args)
    else:
        structured_article = _run_stage(
            "never_blank_voice", finalize_article, *voice_args,
            typed_strategy, audience_selection, selected_cta,
        )
    # #191/#193: the citable values of each source, grouped per record. A
    # Sources line must render one whole record — every value it has and
    # nothing else of substance. Grouped so a line mixing two sources
    # satisfies neither, and value-based so a citation written naturally
    # passes while the prompt's field labels stay optional.
    _identities: tuple[tuple[str, ...], ...] = (
        source_citation_values(research_artifact)
        if research_artifact is not None else ()
    )

    platforms = _run_stage(
        "platform_composer",
        compose_platforms,
        structured_article,
        cta_mode=cta_mode,
        wix_strategy=wix_strategy,
        linkedin_strategy=linkedin_strategy,
        editorial_role_rules=editorial_role_rules,
        formats=composer_formats,
        rejected_sink=rejected_sink,
        source_identities=_identities,
        **({} if closing_contract is None else {"closing_contract": closing_contract}),
    )

    log.info("Editorial Engine: generation complete for signal %s", sig_id)
    return {
        "pattern": pattern,
        "decision_lens": decision_lens,
        "narrative_spine": spine,
        "structured_article": structured_article,
        "platforms": platforms,
    }


def recompose_platform(
    structured_article: dict,
    format_key: str,
    *,
    canonical_body: str,
    cta_mode: str = "none",
    wix_strategy=None,
    linkedin_strategy=None,
    editorial_role_rules: "str | dict[str, str] | None" = None,
    closing_contract: "str | None" = None,
    research_artifact=None,
    rejected_sink: "list | None" = None,
) -> dict:
    """Re-compose ONE platform derivative from final accepted content (#197).

    The missing lifecycle operation behind the Story #13 stale-composition
    guard: when editorial review revises the long-form after the platform
    bodies were composed, the affected derivative must be produced again —
    this time FROM the content that actually survived review, carried in
    ``canonical_body`` as the authoritative source. Exactly one composition
    stage runs (one logical model call through the same budget-charged
    client); nothing else is regenerated — no research, no long-form, no
    title (the requested format's own contract still governs whether it may
    return one), and the Echo still arrives verbatim from
    ``structured_article`` under the same closing contract.

    Same machinery as first composition: the same channel lens, role rules,
    local validators and ``_run_stage`` retry-once semantics, so a
    re-composed body meets exactly the bar the original did. Failures
    surface as ``ArticleGenerationError`` (rejections preserved in
    ``rejected_sink``); the caller fails closed — never falling back to the
    stale body.
    """

    if not isinstance(canonical_body, str) or not canonical_body.strip():
        raise ArticleGenerationError(
            "platform_recomposer",
            ValueError("re-composition requires the final accepted content"),
        )
    _identities: tuple[tuple[str, ...], ...] = (
        source_citation_values(research_artifact)
        if research_artifact is not None else ()
    )
    try:
        platforms = _run_stage(
            "platform_recomposer",
            compose_platforms,
            structured_article,
            cta_mode=cta_mode,
            wix_strategy=wix_strategy,
            linkedin_strategy=linkedin_strategy,
            editorial_role_rules=editorial_role_rules,
            formats=(format_key,),
            rejected_sink=rejected_sink,
            source_identities=_identities,
            canonical_body=canonical_body,
            **({} if closing_contract is None else {"closing_contract": closing_contract}),
        )
    except ArticleGenerationError:
        raise
    except RunCallBudgetExceededError:
        # #171: an exhausted call budget is a run stop, never a stage error.
        raise
    except Exception as exc:  # noqa: BLE001 — provider/transport failures
        # ``_run_stage`` retries only ValueError-class rejections; a provider
        # failure surfaces here on the FIRST attempt (no retry, no second
        # charge). Wrapped so the caller has one typed fail-closed boundary.
        raise ArticleGenerationError("platform_recomposer", exc) from exc
    log.info("Editorial Engine: %s re-composed from final accepted content", format_key)
    return platforms[format_key]

