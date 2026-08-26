"""Wednesday editorial pipeline — the July 6 2026 path, restored (#207).

A literal port of ``src/editorial/pipeline.py`` at ``c7d3a23`` — the commit
that produced the Versant / Full Swing specimen. Single entry point:
``generate_wednesday_article(signal)`` runs

    Decision Lens Lite → Narrative Spine → Hook Engine → Reader Context
    → Discovery Builder → Story Assembly → Never Blank Voice
    → Platform Composer

in that order, over the enriched 46-field signal, and returns the finished
structured article plus the platform bodies.

**What is deliberately absent, and why it matters.** The current shared
pipeline opens with ``pattern_extractor``, which did not exist in July. That
stage asserts ``article_protagonist = "owner"`` as "a hard assertion, not a
choice" and rejects any signal "only relevant to large-company strategy"
whose founder scenario cannot be written without naming a company. The
Versant specimen is a media conglomerate redefining what "media" means — its
protagonist *is* the company — so that stage would reject it or flatten it
into an owner scenario. July had no such constraint, and this pipeline
restores that: **Wednesday does not run pattern_extractor.**

Also absent: the canonical Decision Lens gate. July used Decision Lens *Lite*
as a generative stage inside the pipeline, not as a blocking gate ahead of
it. The Lite stage is what shapes the article's spine; it never had the power
to stop the run.

Each stage retries once on schema validation failure, exactly as July did. A
second failure raises ``WednesdayGenerationError`` — this pipeline does not
degrade to worse content, and it does not fall back to the shared engine.

Only current *technical* infrastructure is used: ``llm_client`` supplies the
provider client, per-stage model routing, the run call budget and the retry
ceiling; ``logger`` supplies logging. No current *business* rule reaches this
path.
"""

from typing import Callable

# reader_context is byte-identical July-vs-today, so the shared module IS the
# July behaviour — reused deliberately rather than duplicated (#207).
from src.editorial.reader_context import build_reader_context
from src.never_blank.wednesday_july.decision_lens_lite import generate_decision_lens
from src.never_blank.wednesday_july.discovery_builder import build_discovery
from src.never_blank.wednesday_july.hook_engine import generate_hook
from src.never_blank.wednesday_july.narrative_spine import build_narrative_spine
from src.never_blank.wednesday_july.never_blank_voice import finalize_article
from src.never_blank.wednesday_july.platform_composer import compose_platforms
from src.never_blank.wednesday_july.story_assembly import assemble_story
from src.utils.logger import get_logger

log = get_logger("never_blank.wednesday_july.pipeline")

#: The stage order as it existed on 2026-07-06. Exposed so a regression can
#: assert the shape of the restored path without executing it.
JULY_STAGE_ORDER = (
    "decision_lens_lite",
    "narrative_spine",
    "hook_engine",
    "reader_context",
    "discovery_builder",
    "story_assembly",
    "never_blank_voice",
    "platform_composer",
)

#: Stages present in the current shared pipeline that July did not have and
#: this path deliberately does not run. Named explicitly so the omission is a
#: recorded decision rather than something a future reader might "restore".
DELIBERATELY_ABSENT_STAGES = ("pattern_extractor",)


class WednesdayGenerationError(Exception):
    """A restored Wednesday stage failed schema validation twice."""

    def __init__(self, stage: str, original: Exception):
        self.stage = stage
        self.original = original
        super().__init__(f"stage {stage!r} failed after retry: {original}")


def _run_stage(stage_name: str, fn: Callable, *args, **kwargs):
    """July retry semantics: one retry on a schema failure, then stop."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        log.warning(
            "Wednesday stage %r failed on first attempt (%s) — retrying once",
            stage_name, exc,
        )
        try:
            return fn(*args, **kwargs)
        except ValueError as exc2:
            raise WednesdayGenerationError(stage_name, exc2) from exc2


def generate_wednesday_article(signal: dict) -> dict:
    """Run the restored July editorial path over one enriched signal.

    ``signal`` is the enriched 46-field research record — the same object the
    July pipeline received, carrying CORE_FACT, CORE_TENSION, BUSINESS_LESSON,
    WHY_THIS_CASE_IS_INTERESTING and the Angle Engine's output
    (POTENTIAL_HOOK, NEVER_BLANK_ANGLE, BLOG_ANGLE, LINKEDIN_ANGLE …). Those
    fields are what make this path produce a second-order reading rather than
    a summary, so they are passed through to every stage exactly as July did.

    Returns ``{"decision_lens", "narrative_spine", "structured_article",
    "platforms"}``. Raises ``WednesdayGenerationError`` on a twice-failed
    stage.
    """

    sig_id = signal.get("SIGNAL_ID", "unknown")
    log.info("Wednesday (July path): starting generation for signal %s", sig_id)

    decision_lens = _run_stage("decision_lens_lite", generate_decision_lens, signal)
    spine = _run_stage("narrative_spine", build_narrative_spine, decision_lens, signal)
    hook = _run_stage("hook_engine", generate_hook, spine, decision_lens, signal)
    reader_context = _run_stage("reader_context", build_reader_context, signal)
    discovery = _run_stage(
        "discovery_builder", build_discovery, hook, spine, decision_lens, signal
    )
    story = _run_stage(
        "story_assembly", assemble_story, discovery, spine, decision_lens, signal
    )
    structured_article = _run_stage(
        "never_blank_voice", finalize_article,
        hook, reader_context, discovery, story, spine, decision_lens, signal,
    )
    platforms = _run_stage("platform_composer", compose_platforms, structured_article)

    log.info("Wednesday (July path): generation complete for signal %s", sig_id)
    return {
        "decision_lens": decision_lens,
        "narrative_spine": spine,
        "structured_article": structured_article,
        "platforms": platforms,
    }
