"""
Never Blank — Canonical Release 1 entry point.

This script is the single authorized controlled execution path for Release 1.

Canonical call flow
-------------------
  CLI --signal-id
  → load active strategy (required)
  → load JSONL signal
  → DEFAULT_INTAKE_ADAPTER.adapt() → ContentAssignment
  → RunContext.from_assignment()  → one RunContext per execution (run_id immutable)
  → _require_run_id()             → fail-closed guard at intake
  → _build_legacy_research_context()  → ResearchContext with run_id injected
  → _assert_run_id_match()        → identity check at research boundary
  → [fresh-gen] execute_and_persist_research() → run-scoped research.json
  → [fresh-gen] evaluate_and_persist_decision() → run-scoped decision.json
  → require_proceed()             → ONLY a reloaded PROCEED decision continues;
                                    every other disposition or evaluator failure
                                    stops the run before narrative/editorial/
                                    visual/package/publisher work (Issue #60)
  → [fresh-gen] rc.to_editorial() → EditorialContext with run_id propagated
  → [fresh-gen] _assert_run_id_match() → identity check at editorial boundary
  → [fresh-gen] run_editorial_acceptance() → explicit editorial verdict on the
                                    Wix article: ACCEPT continues; REVISE gets
                                    exactly one controlled revision + recheck;
                                    everything else stops before packaging and
                                    publication (Issue #89 / Story #13)
  → VisualArtifactRequest         → visual boundary typed adapter (blocked stub)
  → _require_run_id()             → guard at image-preparation
  → _require_run_id()             → guard at validation
  → validate_article_for_publish() → ValidationResult per platform
  → _assert_run_id_match()        → identity check on each ValidationResult
  → canonical packages            → frozen Wix/LinkedIn publication packages
  → evaluate_publication_preflight() → per-channel ALLOW/BLOCK verdict
  → write_preflight_result_json() → verdict persisted before any external call
  → _require_run_id()             → guard at publication
  → publisher.publish()           → PublishResult (run_id empty from publisher)
  → _normalize_publish_result()   → inject/verify run_id, fail closed on mismatch
  → R1RunReport                   → final run-report boundary
  → _emit_run_report()            → logs report (persistent storage: Issue #16)

Artifact layout (Task #28)
--------------------------
  reports/content_packages/<signal_id>/runs/<run_id>/research.json
  reports/content_packages/<signal_id>/runs/<run_id>/decision.json
  reports/content_packages/<signal_id>/runs/<run_id>/editorial_acceptance.json
  reports/content_packages/<signal_id>/runs/<run_id>/generated.json
  reports/content_packages/<signal_id>/runs/<run_id>/publication_results.json

  editorial_acceptance.json — editorial audit record written once for every
                         run that reaches editorial acceptance, accepted or
                         blocked (rubric identity, both reviews, disposition).
                         generated.json exists only for accepted articles.

  decision.json        — canonical Issue #58 Decision Lens artifact, written
                         exactly once after research, before any editorial work.
                         Immutable; create-once; reused runs revalidate it.

  generated.json       — written exactly once, immediately after content generation.
                         Immutable. Never overwritten by publication or re-publication.
  publication_results.json — written once after Wix/LinkedIn attempt.
                         Carries run_id, source_run_id, generation_run_id, results.
  Both are written atomically with create-once semantics and fail closed on collision.

--from-package lifecycle (Option B — publication is a new run)
--------------------------------------------------------------
  --from-package --source-run-id <generation_run_id>

  Reads <signal_id>/runs/<source_run_id>/generated.json exactly.
  Creates a new RunContext (pub run_id). Writes publication_results.json
  under the new pub run directory. The source generated.json is never modified.

  For fresh-gen runs: source_run_id == run_id == generation_run_id.
  For from-package:   source_run_id == original generation run_id (stable).

--legacy-package mode
---------------------
  --legacy-package reads the flat legacy artifact:
      reports/content_packages/{signal_id}_generated.json
  Requires explicit CLI flag; never falls back automatically.
  Never writes back to the legacy path.
  Writes publication_results.json to the current run's run-scoped directory.
  Legacy provenance is recorded explicitly in publication_results.json.

Release 1 publishing scope: Wix and LinkedIn.
Facebook, Instagram, Threads, and Telegram are excluded from this path
and reported as [skipped-not-r1].

Usage (local):
    NB_OPENAI_API_KEY=... python scripts/generate_and_publish.py --signal-id <id> [--dry-run]

Args:
    --signal-id      : SIGNAL_ID from data/research/selected_signals.jsonl or signals_active.jsonl
    --dry-run        : Generate and validate content, save generated.json, but do NOT publish
    --from-package   : Skip LLM generation — publish run-scoped generated.json (requires --source-run-id)
    --source-run-id  : run_id of the source generated.json to load (required with --from-package)
    --legacy-package : Read legacy flat artifact {signal_id}_generated.json (explicit adapter)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.intake import (
    ContentAssignment,
    IntakeAdapter,
    IntakeAdapterError,
    JsonlIntakeAdapter,
)
from src.intake.assignment_record import AssignmentRecord
from src.intake.audience_routing import audience_request
from src.run.code_identity import resolve_code_identity
from src.run.call_budget import (
    R1_MAX_CEILING,
    WEDNESDAY_MAX_CEILING,
    RunCallBudget,
    RunCallBudgetExceededError,
    activate_call_budget,
    configured_run_call_ceiling,
)
from src.run.decision_policy import (
    DecisionPolicyError,
    DecisionPolicyRecord,
    verify_decision_policy_record,
)
from src.lifecycle.signal_lifecycle import ResearchContext
from src.research.provider import (
    ResearchProvider,
    SourceDirectiveKind,
    SourcePriority,
)
from src.research.adapters.exa import ExaResearchAdapter
from src.research.adapters.direct_url import DirectUrlResearchProvider
from src.research.assessment import EvidenceAssessmentError, EvidenceJudgmentTransport
from src.research.lifecycle import (
    ResearchGateError,
    build_research_request,
    execute_and_persist_research,
    load_research_envelope,
    validate_research_envelope,
    MissingCredentialResearchProvider,
)
from src.run import ExecutionMode, RunContext
from src.analytics.blog import BlogCollector
from src.analytics.linkedin import LinkedInCollector
from src.analytics.orchestrator import run_analytics_pipeline
from src.editorial.platform_composer import CLOSING_BRANDED_ECHO_THEN_SOURCES
from src.editorial.editorial_role import (
    EditorialRoleError,
    render_editorial_role_rules,
    resolve_editorial_role,
)
from src.editorial.sources_of_record import (
    render_sources_of_record,
    source_records,
)
from src.editorial.source_transparency import (
    SocialLineageError,
    SourceTransparencyError,
    validate_social_lineage,
    validate_source_transparency,
)
from src.never_blank.wednesday_july import WednesdayGenerationError
from src.never_blank.wednesday_routing import (
    WEDNESDAY_ROLE_ID,
    generate_for_wednesday,
    is_wednesday_role,
)
from src.never_blank.wednesday_supply import (
    WEDNESDAY_SIGNALS_FILE,
    WednesdaySupplyError,
    published_signal_ids,
    supply_wednesday_signal,
)
from src.editorial.pipeline import (
    ArticleGenerationError,
    generate_article,
    recompose_platform,
)
from src.editorial.pattern_extractor import SignalRejectedError
from src.editorial.decision_lens_evaluator import (
    DecisionLensEvaluator,
    production_evaluator,
)
from src.editorial.decision_lifecycle import (
    RELEASE1_LENS_PROFILE,
    DecisionGateError,
    evaluate_and_persist_decision,
    load_decision_artifact,
    require_proceed,
)
from src.editorial.linkedin_composition import (
    LinkedInCompositionError,
    accept_linkedin_composition,
)
from src.visual.contract import (
    VisualGateError,
    build_visual_assets_record,
    reuse_visual_assets_record,
)
from src.editorial.editorial_acceptance import (
    ArticleRevisionTransport,
    EditorialAcceptanceError,
    EditorialAcceptanceRubric,
    EditorialReviewTransport,
    LlmChatArticleRevisionTransport,
    LlmChatEditorialReviewTransport,
    RevisionContext,
    run_editorial_acceptance,
)
from src.publishing import formatting
from src.strategy.client_contracts import ClientContractError, contracts_for_role
from src.publishing.formatting import ensure_source_line
from src.publishing.image_pipeline import CURRENT_DESIGN_VERSION
from src.publishing.hashtags import generate_hashtags
from src.publishing.facebook import FacebookPublisher
from src.publishing.instagram import InstagramPublisher
from src.publishing.linkedin import LinkedInPublisher
from pydantic import ValidationError as PydanticValidationError

from src.publishing.idempotency import (
    LinkedInPublicationIdentity,
    WixPublicationIdentity,
    find_prior_linkedin_publication,
    find_prior_wix_publication,
)
from src.publishing.preflight import (
    ChannelPackageOutcome,
    FreshnessVerdict,
    PreflightDisposition,
    ReadinessVerdict,
    evaluate_publication_preflight,
)
from src.publishing.package import (
    LinkedInPublicationTarget,
    PackageFailureCategory,
    PublicationPackageError,
    WixPublicationTarget,
    bind_canonical_article_url,
    build_linkedin_publication_package,
    build_wix_publication_package,
    canonical_slug,
)
from src.publishing.canonical_url import (
    CanonicalUrlVerdict,
    verify_canonical_url,
)
from src.publishing.result import PublishResult, PublishStatus
from src.publishing.release_scope import (
    NON_R1_PUBLISH_CHANNELS,
    R1_PUBLISH_CHANNELS,
)
from src.publishing.telegram import TelegramPublisher
from src.publishing.threads import ThreadsPublisher
from src.publishing.wix import ProviderUrlLookup, WixPublisher
from src.artifacts import (
    ArtifactCollisionError,
    write_generated_pre_acceptance_json,
    write_signal_snapshot_json,
    load_run_generated,
    load_business_strategy_snapshot,
    resolve_run_dir,
    load_linkedin_composition_json,
    load_assignment_json,
    load_visual_assets_json,
    append_rejected_composition,
    write_accepted_composition_json,
    write_assignment_json,
    write_editorial_acceptance_json,
    write_decision_policy_json,
    write_editorial_review_content_json,
    write_generated_json,
    write_linkedin_composition_json,
    write_linkedin_final_preflight_json,
    write_visual_assets_json,
    write_business_strategy_snapshot,
    write_preflight_result_json,
    write_publication_results_json,
    write_run_report_json,
)
from src.reporting import R1RunReport
from src.reporting.run_report import (
    RunReportError,
    TerminalDisposition,
    TerminalStage,
    build_run_report,
)
from src.strategy.history import append_published_entry
from src.strategy.business_config import (
    BusinessStrategyConfiguration,
    BusinessStrategyConfigurationError,
    load_business_strategy_configuration,
)
from src.strategy.execution_context import (
    StrategyExecutionContext,
    StrategyExecutionError,
    assert_campaign_reference,
    identity_from_mapping,
    require_configuration_identity,
)
# get_strategy_context remains imported for legacy test/caller patch surfaces;
# the canonical path no longer calls it.
from src.strategy.loader import get_cta_mode, get_strategy_context, load_active_strategy
from src.strategy.models import PlatformPublication, PublishedEntry
from src.strategy.validators import ValidationResult, validate_article_for_publish
from src.utils.logger import get_logger
from src.visual import VisualArtifactRequest

log = get_logger("generate_and_publish")

#: Where run records are written. The production default is the repository's
#: own reports/ output root, unchanged. ``NB_PACKAGES_DIR`` redirects it, so a
#: test — or a sandboxed run of this entrypoint — never writes run records into
#: the tracked tree. Until #233 F-02 this path was a fixed relative one, and any
#: test that drove the entrypoint without redirecting it committed its residue:
#: 7,796 tracked files, entering in bulk on unrelated commits.
DEFAULT_PACKAGES_DIR = Path("reports/content_packages")
PACKAGES_DIR   = Path(os.environ.get("NB_PACKAGES_DIR", "").strip() or DEFAULT_PACKAGES_DIR)
PACKAGES_DIR.mkdir(parents=True, exist_ok=True)

#: Exit code for "this signal is editorially unsuitable": the pre-generation
#: suitability gate (the Pattern Extractor) rejected the candidate before any
#: article was written. Not a failure of the run — a stream driver that walks
#: candidates in queue order (first valid signal wins, #240 D8) moves on to the
#: next one. The signal is never consumed; the rejection is recorded in the run.
EXIT_EDITORIALLY_UNSUITABLE = 6
SIGNALS_FILES  = [
    Path("data/research/selected_signals.jsonl"),
    Path("data/research/signals_active.jsonl"),
    # Wednesday's own store (#211). Present so a Wednesday signal can be
    # reloaded by identity on a --from-package retry. Nothing writes Monday
    # signals here and nothing writes Wednesday signals to the two above:
    # the supplies are separate in both directions.
    WEDNESDAY_SIGNALS_FILE,
]
HISTORY_FILE   = Path("strategy/published_content_index.jsonl")
SEP            = "─" * 64
_OK_STATUSES   = {"PUBLISHED", "DRAFT_CREATED", "published_url_unavailable"}
# Issue #105: a REUSED channel is not a failure — the article is live from the
# earlier publication — but it is deliberately NOT an OK status, so a retry can
# never be recorded as a second fresh publication in the history index.
#
# Issue #108: PROVIDER_DUPLICATE belongs to NEITHER set. A provider duplicate
# response proves a duplicate exists but never which post, so the channel is
# neither a successful publication nor a completed one.
_COMPLETED_STATUSES = _OK_STATUSES | {"REUSED"}
DEFAULT_INTAKE_ADAPTER: IntakeAdapter = JsonlIntakeAdapter()


def _source_of_record_attribution(signal: dict, research) -> Optional[tuple]:
    """The (name, url) Wednesday may cite, or None (#219).

    The URL must be one the run's research artifact actually recorded, because
    that artifact is exactly what the source-transparency gate validates
    against. Citing anything else would either fail that gate or, worse, put a
    link in the published article that no stage ever retrieved.

    The label is the signal's own ``SOURCE_NAME`` — the same value the
    formatting stage already uses — so the footer this produces is
    byte-identical to the one the run would have appended later anyway.
    Nothing here invents a field: a signal with no URL, or a URL the run did
    not retrieve, returns None and the gate stops the run on its own terms.
    """
    url = str(signal.get("SOURCE_URL") or "").strip()
    if not url:
        return None
    try:
        of_record = {
            item["url"] for item in source_records(research) if item.get("url")
        }
    except Exception:                      # a malformed artifact cites nothing
        return None
    if url not in of_record:
        return None
    return str(signal.get("SOURCE_NAME") or "").strip(), url


def _load_signal(signal_id: str) -> dict:
    for path in SIGNALS_FILES:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("SIGNAL_ID") == signal_id:
                    return obj
            except Exception:
                pass
    raise FileNotFoundError(
        f"Signal {signal_id!r} not found in:\n"
        + "\n".join(f"  {p}" for p in SIGNALS_FILES)
    )


def _load_package_images(signal_id: str) -> dict:
    path = PACKAGES_DIR / f"{signal_id}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data.get("images", {}).get("platform_images", {})
        except Exception:
            pass
    return {}


def _slugify(text: str) -> str:
    # Canonical implementation lives with the publication package contract.
    return canonical_slug(text)


_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"'”’)]*\s+")

#: A period after one of these does not end a sentence (#259 review: "We
#: consulted Dr." is not a sentence). Single capital initials ("J.") too.
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "no", "vs",
    "etc", "inc", "ltd", "co", "corp", "e.g", "i.e", "u.s", "u.k", "a.m",
    "p.m", "approx", "est", "fig", "jan", "feb", "mar", "apr", "jun", "jul",
    "aug", "sep", "sept", "oct", "nov", "dec",
    "min", "mins", "hr", "hrs", "sec", "secs", "mo", "mos", "yr", "yrs",
    "wk", "wks", "ft", "lb", "lbs", "oz", "pp", "dept", "govt", "misc",
})


def _ends_with_abbreviation(fragment: str) -> bool:
    """Might this period be an abbreviation rather than a sentence end?

    Conservative by design (#259 review): no finite list covers every
    abbreviation ("Assoc.", "Gov.", "Rep."…), so any short capitalized token,
    any token with an internal period, and any single letter is treated as
    one — and so is a period right after a digit ("steps: 1. Review…").
    A wrong guess only MERGES two real sentences into one longer unit —
    which the length budget may then skip — and never cuts one.
    """
    words = fragment.rstrip("\"'”’)").split()
    if not words:
        return False
    if words[-1].endswith(("!", "?")):
        # a brand or name such as "Yahoo!" — a short capitalized token
        raw = words[-1].rstrip("!?").lstrip("\"'“‘(")
        return bool(raw) and raw[:1].isupper() and len(raw) <= 6
    if not words[-1].endswith("."):
        return False
    raw = words[-1].rstrip(".").lstrip("\"'“‘(")
    token = raw.casefold()
    return (
        token in _ABBREVIATIONS
        or (len(token) == 1 and token.isalpha())
        or "." in raw
        or (raw[:1].isupper() and len(raw) <= 6)
        # a period straight after a digit may be a list marker ("1.") or an
        # ordinal/number — ambiguous, so merge (#259 review round 5)
        or raw[-1:].isdigit()
    )


def _inside_open_quote(fragment: str) -> bool:
    """Does ``fragment`` leave a quotation or bracket open?

    A "?" or "." inside quoted or bracketed speech does not end the outer
    sentence ("The team tested “Ready to buy? Compare …” against …" is one
    sentence, #259 review), so an open one always merges.

    Scanned in order, so a closing mark only ever closes a quotation that is
    actually open: an apostrophe ("don’t") or a possessive ("customers’")
    with nothing open is just an apostrophe and cancels nothing.
    """
    def is_letter(ch: str) -> bool:
        return ch.isalpha()

    double = single = straight_single = paren = 0
    straight_double = False
    text = fragment or ""
    for i, ch in enumerate(text):
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch == "“":
            double += 1
        elif ch == "”" and double:
            double -= 1
        elif ch == "‘":
            single += 1
        elif ch == "’":
            if is_letter(prev) and is_letter(nxt):
                continue                               # apostrophe: don’t
            if single:
                single -= 1                            # closes an open ‘
        elif ch == "'":
            if is_letter(prev) and is_letter(nxt):
                continue                               # apostrophe: don't
            if (not prev or prev.isspace() or prev in "(“[") and is_letter(nxt):
                straight_single += 1                   # opens: 'Ready
            elif straight_single and (not nxt or not is_letter(nxt)):
                straight_single -= 1                   # closes an open '
        elif ch == '"':
            straight_double = not straight_double
        elif ch == "(":
            paren += 1
        elif ch == ")" and paren:
            paren -= 1
    return bool(double or single or straight_single or paren or straight_double)


def _sentences(text: str) -> list[str]:
    """Whole sentences of one paragraph, markdown emphasis removed."""
    flat = re.sub(r"\s+", " ", (text or "").replace("*", "")).strip()
    sentences: list[str] = []
    for part in (piece.strip() for piece in _SENTENCE_END.split(flat)):
        if not part:
            continue
        # A sentence never begins in lowercase: "30 min. before …" is one
        # sentence, whatever the token before the period (#259 review).
        first_letter = next((ch for ch in part if ch.isalpha()), "")
        continues = bool(first_letter) and first_letter.islower()
        if sentences and (continues or _ends_with_abbreviation(sentences[-1])
                          or _inside_open_quote(sentences[-1])):
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)
    return sentences


def _whole_sentences(text: str, max_words: int) -> str:
    """The longest run of WHOLE opening sentences within ``max_words``.

    Never cuts a sentence: when even the first sentence is longer than the
    limit, the result is empty and the caller moves on. Controlled live run
    35383199073 published "…and follow through—making your." — a length
    limit must never end an output mid-sentence.
    """
    kept: list[str] = []
    used = 0
    for sentence in _sentences(text):
        words = len(sentence.split())
        if used + words > max_words:
            break
        kept.append(sentence)
        used += words
    # safety net: never hand back a unit that leaves a quotation or bracket
    # open — whatever the splitter concluded, that unit is unfinished
    while kept and _inside_open_quote(" ".join(kept)):
        kept.pop()
    return " ".join(kept)


def _article_paragraphs(article_body: str, echo: str = "") -> list[str]:
    """The accepted article's own prose paragraphs, in order.

    Stops at the Echo attribution line and at any Sources section; skips
    headings. Everything returned is text Editorial Acceptance approved.
    """
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", article_body or ""):
        text = block.strip()
        if not text:
            continue
        plain = text.replace("*", "").strip()
        if (echo and echo.strip() and echo.strip() in plain) or re.match(
            r"^(#+\s*)?sources?\s*:?\s*$", plain.splitlines()[0], re.IGNORECASE
        ):
            break
        if plain.startswith("#"):
            continue
        paragraphs.append(text)
    return paragraphs


def _accepted_echo(final_article: str, draft_echo: str = "") -> str:
    """The Echo as the FINAL ACCEPTED article carries it.

    The draft's Echo predates Editorial Acceptance: a revision may reword,
    negate or remove it (#259 review). Authoritative, in order:

    1. the accepted article's attributed paragraph ("Never Blank: <echo>"),
       taken whole even when it wraps across lines;
    2. the draft Echo only when it is, by itself, the accepted article's
       final prose paragraph — the closing an unattributed contract
       requires. Merely appearing inside a sentence proves nothing ("We
       cannot conclude that <echo>" contains it and rejects it);
    3. otherwise no Echo — never the draft's.
    """
    paragraphs = [
        re.sub(r"\s+", " ", block.replace("*", "")).strip()
        for block in re.split(r"\n\s*\n", final_article or "")
        if block.strip()
    ]
    for paragraph in paragraphs:
        match = re.match(r"^Never Blank\s*:\s*(.+)$", paragraph)
        if match:
            return match.group(1).strip()
    prose = [p for p in paragraphs
             if not re.match(r"^(#+\s*)?sources?\s*:?", p, re.IGNORECASE)]
    draft = re.sub(r"\s+", " ", (draft_echo or "").replace("*", "")).strip()
    if draft and prose and prose[-1] == draft:
        return draft
    return ""


def _build_threads(title: str | None, article_body: str, echo: str = "") -> list[str]:
    """Threads, derived from the FINAL ACCEPTED article only.

    The accepted title leads (Product Owner decision: one canonical headline
    on every surface), then the opening whole sentences of the article's
    paragraphs, then the Echo. Existing limits unchanged: at most 5 posts,
    at most 55 words each — but a post is never cut mid-sentence to fit.
    """
    candidates = [title or ""]
    for paragraph in _article_paragraphs(article_body, echo):
        lead = _whole_sentences(paragraph, 55)
        if lead:
            candidates.append(lead)
        if len([c for c in candidates if c]) >= 4:
            break
    candidates.append(echo or "")
    sequence: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        post = re.sub(r"\s+", " ", (value or "").strip())
        key = post.lower()
        if post and key not in seen:
            sequence.append(post)
            seen.add(key)
    # Never padded and never invented: an accepted article too short for the
    # 3–5 post target yields what it honestly supports. Threads is not a
    # Release 1 surface, so a short sequence is reported, never a run stop.
    if len(sequence) < 3:
        print(f"  ⚠  threads: the accepted article supports {len(sequence)} "
              "post(s), fewer than the 3–5 target")
    return sequence[:5]


def _lead_with_canonical_title(body: str, title: str | None) -> str:
    """Open a channel derivative with the article's accepted title.

    Product Owner decision (Monday preview readiness): every content surface
    carries the same accepted canonical headline — no composer invents its
    own. Deterministic, never a model call: the title the run accepted is set
    as the first line, unless the body already opens with it. Without an
    accepted title the body is returned unchanged; nothing is invented.
    """
    if not title or not body:
        return body
    first = next((line for line in body.splitlines() if line.strip()), "")
    # "Opens with it" means the opening line starts with the title — the
    # title may be the whole line or its first sentence (#259 review): a
    # second copy would trip the duplicate-sentence guard.
    if first.replace("*", "").strip().casefold().startswith(title.strip().casefold()):
        return body
    return f"{title.strip()}\n\n{body}"


def _build_telegram(title: str | None, article_body: str, echo: str = "",
                    wix_url: str = "") -> str:
    """Telegram, derived from the FINAL ACCEPTED article only.

    The existing contract is unchanged — one observation and one implication,
    each at most 34 words (the Telegram length itself awaits a Product Owner
    decision) — but both now come from accepted text: the observation is the
    opening whole sentences of the article, the implication is the article's
    own Echo. The accepted title leads. Never cut mid-sentence.
    """
    observation = next(
        (lead for lead in (_whole_sentences(p, 34)
                           for p in _article_paragraphs(article_body, echo)) if lead),
        "",
    )
    implication = _whole_sentences(echo, 34)
    lines = [title or "", observation, implication]
    if wix_url:
        lines.append(wix_url.strip())
    return "\n".join(line.strip() for line in lines if line and line.strip())


def _save_generated(
    path: Path,
    signal_id: str,
    headline: str,
    blog_body: str,
    linkedin: str,
    facebook: str,
    instagram: str,
    threads: list[str],
    telegram: str,
    wix_url: str,
    strategy_id: str,
    strategy_started_at: str,
    strategy_version: str,
    generated_at: str | None = None,
    run_id: str = "",
    generation_run_id: str = "",
) -> None:
    data: dict = {
        "run_id":              run_id,
        "signal_id":           signal_id,
        "headline":            headline,
        "generated_at":        generated_at or datetime.now(timezone.utc).isoformat(),
        "strategy_id":         strategy_id,
        "strategy_version":    strategy_version,
        "strategy_started_at": strategy_started_at,
        "wix_url":             wix_url,
        "blog_article":        blog_body,
        "linkedin_post":       linkedin,
        "facebook_post":       facebook,
        "instagram_caption":   instagram,
        "threads_sequence":    threads,
        "telegram_text":       telegram,
    }
    if generation_run_id:
        data["generation_run_id"] = generation_run_id
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# Release 1 publishing scope — only these two publishers are invoked.
# #227: the values are unchanged; they now come from the single authority in
# src/publishing/release_scope.py, because two older automatic paths carried
# their own copy of this list and silently published four channels Release 1
# does not publish.
_R1_PUBLISHERS = R1_PUBLISH_CHANNELS
_NON_R1_PUBLISHERS = NON_R1_PUBLISH_CHANNELS

# #175: the composer formats and image surfaces the active R1 publishers
# actually consume. Inactive surfaces execute nothing — no composition
# transport, no image composite/upload — while their package fields and the
# composer/image architecture remain for future configuration.
#: Composed BEFORE editorial acceptance: the canonical article only. Every
#: social derivative is composed afterwards, from the final accepted article
#: (see "Social derivatives from the final accepted article" in _run) — a
#: derivative composed beside the draft would carry the draft's claims past
#: Editorial Acceptance (controlled live run 35383199073).
_R1_COMPOSER_FORMATS = ("long",)

#: Recorded in generated.json by every run whose social bodies were derived
#: from the final accepted article. A package without it predates that
#: invariant, so --from-package / --legacy-package refuse it: republishing
#: it could put draft-derived social copy beside a corrected article.
SOCIAL_DERIVATION_LINEAGE = "final-accepted-article/1"
_R1_IMAGE_PLATFORMS = ["blog", "linkedin"]


def _persist_rejected_compositions(run_dir: Path, rejected: list) -> None:
    """Write refused compositions as diagnostic evidence (Issue #191).

    A deterministic contract failure must be diagnosable without paying for
    another live run. Never a publication input: the record declares itself
    unpublishable, is absent from the canonical artifact set, and no loader
    reads it — ``--from-package`` reads ``generated.json`` and only that.
    A failure to preserve evidence never rewrites the run's outcome.
    """
    if not rejected:
        return
    try:
        for entry in rejected:
            append_rejected_composition(run_dir, entry)
        print(f"  ℹ  rejected compositions preserved: {len(rejected)} "
              f"({run_dir / 'rejected_composition.json'})")
    except (OSError, ValueError) as exc:
        log.warning("rejected compositions could not be preserved (%s)",
                    type(exc).__name__)


def _stop_with_preflight(
    *,
    run_dir: Path,
    run_id: str,
    signal_id: str,
    configuration_identity,
    readiness: ReadinessVerdict,
    override_attempted: bool,
    freshness: Optional[FreshnessVerdict] = None,
) -> int:
    """Persist the authorization verdict for a stop that precedes packaging.

    Issue #101: a publication decision inside Story #17's authorization model
    is never taken outside the canonical preflight boundary. When no channel
    package can exist yet, every channel is recorded in the explicit
    fail-closed state "the canonical package could not be constructed".
    """

    outcomes = [
        ChannelPackageOutcome.failed(
            channel,
            "no canonical package was constructed: the run was blocked before "
            "publication packaging",
        )
        for channel in _R1_PUBLISHERS
    ]
    try:
        verdict = evaluate_publication_preflight(
            packages_dir=PACKAGES_DIR,
            run_id=run_id,
            signal_id=signal_id,
            configuration_identity=configuration_identity,
            channel_outcomes=outcomes,
            override_attempted=override_attempted,
            readiness=readiness,
            freshness=freshness or FreshnessVerdict(verified=True),
        )
        write_preflight_result_json(run_dir, json.loads(verdict.model_dump_json()))
        print(
            f"  preflight: run={verdict.run_disposition.value} "
            f"({run_dir / 'preflight_result.json'})"
        )
    except (ArtifactCollisionError, OSError, ValueError) as exc:
        print(f"  ERROR: publication preflight could not be committed: {exc}")
    return 1


def _require_run_id(run_id: str, stage: str) -> None:
    """
    Fail-closed guard: raise RuntimeError when run_id is missing or blank.

    Called at intake, validation, image-preparation, and publication to ensure
    run identity is always valid before any side effect is triggered.
    """
    if not run_id or not run_id.strip():
        raise RuntimeError(
            f"run_id is missing or blank at stage {stage!r}. "
            "RunContext must be created before any stage is entered."
        )


def _assert_run_id_match(expected: str, actual: str, boundary: str) -> None:
    """
    Fail-closed identity assertion: raise RuntimeError when actual != expected.

    Called at every named stage boundary to prevent silent run_id drift.
    The contract requires one immutable run_id from intake through all boundaries.
    """
    if actual != expected:
        raise RuntimeError(
            f"run_id identity mismatch at boundary {boundary!r}: "
            f"expected={expected!r} actual={actual!r}"
        )


def _normalize_publish_result(
    result: PublishResult,
    expected_run_id: str,
    platform: str,
) -> PublishResult:
    """
    Normalize publisher result run identity — called immediately after publish().

    Publishers do not set run_id (they operate without RunContext knowledge).
    This adapter:
      - Injects expected_run_id when result.run_id is empty (backward compat).
      - Fails closed when result.run_id is non-empty but does not match expected.

    Returns the result with run_id guaranteed to equal expected_run_id.
    """
    if not result.run_id:
        result.run_id = expected_run_id
    elif result.run_id != expected_run_id:
        raise RuntimeError(
            f"PublishResult run_id mismatch for {platform!r}: "
            f"result={result.run_id!r} expected={expected_run_id!r}"
        )
    return result


class _TerminalState:
    """What the run has proven so far, for the single terminalization seam.

    The business body advances this as it goes, so no return path has to
    build a report itself and none can be forgotten. A run that never
    receives a run identity — argument or configuration failures, before the
    run namespace exists — leaves the state empty and is not reportable:
    there is no run to account for.
    """

    __slots__ = ("run_id", "signal_id", "execution_mode", "packages_dir",
                 "stage", "disposition", "errors")

    def __init__(self) -> None:
        self.run_id: Optional[str] = None
        self.signal_id: Optional[str] = None
        self.execution_mode: str = "unknown"
        self.packages_dir: Optional[Path] = None
        self.stage: TerminalStage = TerminalStage.INTAKE
        self.disposition: TerminalDisposition = TerminalDisposition.FAILED
        self.errors: list = []

    def begin(self, *, run_id: str, signal_id: str, execution_mode: str,
              packages_dir: Path) -> None:
        self.run_id = run_id
        self.signal_id = signal_id
        self.execution_mode = execution_mode
        self.packages_dir = packages_dir

    def reached(self, stage: TerminalStage) -> None:
        """Record the last lifecycle stage the run actually reached."""
        self.stage = stage

    def ended(self, stage: TerminalStage, disposition: TerminalDisposition,
              *errors: str) -> None:
        self.stage = stage
        self.disposition = disposition
        self.errors.extend(str(item) for item in errors if item)

    @property
    def reportable(self) -> bool:
        return bool(self.run_id and self.signal_id and self.packages_dir)


def _emit_terminal_report(state: "_TerminalState", exit_code: int) -> None:
    """Persist the authoritative account of one terminal run (Issue #112).

    Called exactly once, after the business run has fully returned, so every
    canonical artifact it references is already committed. A failure here is
    logged and never rewrites the business outcome: a run that failed for a
    reason still fails for that reason, and a successful run is never turned
    into a failure because its account could not be written.
    """

    if not state.reportable:
        return                       # no run namespace — nothing to account for

    disposition = state.disposition
    if exit_code == 0 and disposition is TerminalDisposition.FAILED:
        disposition = TerminalDisposition.COMPLETED

    try:
        report = build_run_report(
            state.packages_dir,
            run_id=state.run_id,
            signal_id=state.signal_id,
            execution_mode=state.execution_mode,
            terminal_stage=state.stage,
            terminal_disposition=disposition,
            errors=tuple(state.errors),
        )
        write_run_report_json(
            resolve_run_dir(state.packages_dir, state.signal_id, state.run_id),
            json.loads(report.model_dump_json()),
        )
        log.info(
            "run_report: run_id=%s stage=%s disposition=%s completed=%s",
            report.run_id, report.terminal_stage.value,
            report.terminal_disposition.value, report.completed,
        )
    except ArtifactCollisionError:
        # An existing report is never overwritten and never silently updated.
        log.warning(
            "run_report already exists for run_id=%s — the existing report stands",
            state.run_id,
        )
    except (RunReportError, OSError, TypeError, ValueError) as exc:
        # Never let the account rewrite the outcome it describes.
        log.warning(
            "run_report could not be written for run_id=%s (%s) — "
            "the run outcome is unchanged",
            state.run_id, type(exc).__name__,
        )


def _emit_run_report(report: R1RunReport) -> None:
    """
    Emit the final run report.  Release 1: log only.
    Persistent storage, artifact naming, and evidence provenance: Issue #16.
    """
    log.info(
        "R1RunReport: run_id=%s signal_id=%s mode=%s completed=%s ok=%s errors=%r",
        report.run_id,
        report.signal_id,
        report.execution_mode,
        report.completed,
        report.ok(),
        report.errors,
    )


def _build_legacy_research_context(
    assignment: ContentAssignment,
    raw_signal: dict,
    run_ctx: "RunContext",
) -> ResearchContext:
    """
    Compatibility boundary — converts a ContentAssignment + raw JSONL signal dict
    into the legacy ResearchContext expected by downstream pipeline stages.
    Injects run_id from RunContext so ResearchContext carries run identity.

    The assignment_id must match the raw signal's SIGNAL_ID.  Mismatched identifiers
    are rejected to prevent stale or unrelated signal data from being injected.

    TODO Task #29: remove this boundary once downstream stages accept
    ContentAssignment directly.
    """
    raw_signal_id = raw_signal.get("SIGNAL_ID", "")
    if assignment.assignment_id != raw_signal_id:
        raise ValueError(
            f"assignment.assignment_id {assignment.assignment_id!r} does not match "
            f"raw_signal SIGNAL_ID {raw_signal_id!r}. "
            "Mismatched identifiers are not allowed at the compatibility boundary."
        )
    rc = ResearchContext.from_dict(raw_signal)
    rc.run_id = run_ctx.run_id
    return rc


def main(
    *,
    research_provider: ResearchProvider | None = None,
    evidence_judgment: "EvidenceJudgmentTransport | None" = None,
    decision_evaluator: DecisionLensEvaluator | None = None,
    editorial_reviewer: EditorialReviewTransport | None = None,
    article_revisor: ArticleRevisionTransport | None = None,
) -> int:
    """Run one signal end to end and account for it exactly once.

    Issue #112: the business run lives in ``_run``; this wrapper is the single
    terminalization seam that persists the authoritative ``run_report.json``
    after the run has fully finished — so the report is never written before
    the terminal evidence is stable, never written twice, and never able to
    rewrite the business outcome it describes.
    """

    state = _TerminalState()
    # #217: resolve only the declared role needed to choose the finite budget
    # before the full entrypoint parses and executes. Unknown arguments stay
    # untouched for the canonical parser below.
    budget_parser = argparse.ArgumentParser(add_help=False)
    budget_parser.add_argument("--editorial-role", default="")
    budget_args, _ = budget_parser.parse_known_args()
    # #171: one deterministic ceiling on paid text-model calls for the whole
    # run. The budget is constructed per run (reset = construction), charged
    # inside the shared client before each transport, and exhausted budgets
    # fail the run closed here — after the last reached stage is recorded,
    # before any further paid call, with the standard terminal accounting.
    budget_limit = configured_run_call_ceiling(budget_args.editorial_role or None)
    budget = RunCallBudget(
        limit=budget_limit,
        hard_max=(
            WEDNESDAY_MAX_CEILING
            if budget_args.editorial_role == WEDNESDAY_ROLE_ID
            else R1_MAX_CEILING
        ),
    )
    try:
        with activate_call_budget(budget):
            exit_code = _run(
                state,
                research_provider=research_provider,
                evidence_judgment=evidence_judgment,
                decision_evaluator=decision_evaluator,
                editorial_reviewer=editorial_reviewer,
                article_revisor=article_revisor,
            )
    except RunCallBudgetExceededError as exc:
        print(f"  ERROR: {exc}")
        state.ended(state.stage, TerminalDisposition.STOPPED,
                    f"call budget exhausted: {exc.used}/{exc.limit}")
        exit_code = 1
    print(
        f"  ℹ  text-model call budget: {budget.used} used / "
        f"{budget.limit} limit / {budget.remaining} remaining"
    )
    _emit_terminal_report(state, exit_code)
    return exit_code


def _run(
    state: "_TerminalState",
    *,
    research_provider: ResearchProvider | None = None,
    evidence_judgment: "EvidenceJudgmentTransport | None" = None,
    decision_evaluator: DecisionLensEvaluator | None = None,
    editorial_reviewer: EditorialReviewTransport | None = None,
    article_revisor: ArticleRevisionTransport | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Generate + publish one signal end-to-end")
    # #211: Wednesday's fresh-generation runs discover their own signal
    # through the restored July research path, so the id is a filter there
    # rather than an input. Every other path still requires it, enforced
    # below once the role is known.
    parser.add_argument("--signal-id", default="")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate and validate content, save generated.json, but do not publish")
    parser.add_argument("--preview-fresh-images", action="store_true",
                        help="With --dry-run only: an owner-controlled full-content preview "
                             "that generates and uploads a FRESH image (never reusing a "
                             "cached one) and runs the visual gate. Still publishes nothing "
                             "and consumes nothing.")
    parser.add_argument("--from-package", action="store_true",
                        help="Skip LLM generation — publish run-scoped generated.json (requires --source-run-id)")
    parser.add_argument("--source-run-id",
                        help="run_id of the source generated.json to load (required with --from-package)")
    parser.add_argument("--legacy-package", action="store_true",
                        help="Read legacy flat artifact {signal_id}_generated.json (explicit adapter; never auto-fallback)")
    parser.add_argument("--editorial-role", default="",
                        help="Editorial role id declared by the business configuration "
                             "(Issue #142); recorded on the run and applied to composition")
    parser.add_argument("--delete-wix-post-id",
                        help="Delete this Wix post ID before publishing (use when replacing an existing post)")
    args = parser.parse_args()
    signal_id = args.signal_id

    # Validate mutually exclusive modes and required co-arguments.
    if args.from_package and args.legacy_package:
        print("  ERROR: --from-package and --legacy-package are mutually exclusive")
        return 1
    if args.from_package and not args.source_run_id:
        print("  ERROR: --from-package requires --source-run-id <run_id>")
        return 1
    if args.source_run_id and not args.from_package:
        print("  ERROR: --source-run-id is only valid with --from-package")
        return 1
    if args.preview_fresh_images and (
        not args.dry_run or args.from_package or args.legacy_package
    ):
        print("  ERROR: --preview-fresh-images is a generating dry run only "
              "(requires --dry-run; not with --from-package/--legacy-package)")
        return 1

    mode = ("dry-run preview with fresh images (no publish)" if args.preview_fresh_images
            else "dry-run (no publish)" if args.dry_run
            else "from-package" if args.from_package
            else "legacy-package" if args.legacy_package
            else "live (LLM generate)")
    print(f"\n{SEP}")
    print("  Never Blank — Generate + Publish")
    # #211: a Wednesday run has no signal id yet — it discovers one below.
    print(f"  Signal: {signal_id or '(to be discovered)'}")
    print(f"  Mode:   {mode}")
    print(SEP)

    # ── 1. Load strict business configuration before any judgment ────────────
    print("\n[1/6] Loading business configuration and active campaign…")
    try:
        business_configuration = load_business_strategy_configuration()
        strategy_execution = StrategyExecutionContext.from_configuration(
            business_configuration
        )
        strategy_execution.assert_consistent()
    except (BusinessStrategyConfigurationError, StrategyExecutionError) as exc:
        print(f"  ERROR: {exc}")
        return 1

    # Issue #142: which editorial role this run produces. Requested explicitly
    # by the caller and resolved against the declared roles — never inferred
    # from the weekday, the cron, the source title, or the prompt. An unknown
    # role fails closed: a run with no rules to follow must not quietly
    # produce a default article under a role name it never honoured.
    _editorial_role_identity = None
    _editorial_role_rules = None
    _editorial_acceptance_path = None
    _editorial_acceptance_identity = None
    _role = None
    #: The client's contracts for this role (#240 D12), or None when the client
    #: supplies none — zero client documents is a valid state.
    _client_contracts = None
    if args.editorial_role:
        try:
            # One snapshot per run: the texts that shape it are the texts it records.
            _client_contracts = contracts_for_role(args.editorial_role.strip())
            _editorial_role_identity, _role = resolve_editorial_role(
                business_configuration, args.editorial_role, contracts=_client_contracts
            )
        except (EditorialRoleError, ClientContractError) as exc:
            print(f"  ERROR: {exc}")
            return 1
        _writing_lenses = (
            _client_contracts.for_stage("writing") if _client_contracts is not None else ()
        )
        # Per-format rendering: the role's surface-scoped rules reach exactly
        # the surface they are for. ``long`` is the Wix article and ``medium``
        # the LinkedIn artifact — the same mapping this entrypoint already
        # relies on when it publishes them. Client lenses routed to writing
        # reach both.
        _editorial_role_rules = {
            "long": render_editorial_role_rules(
                _role, surface="wix", lenses=_writing_lenses
            ),
            "medium": render_editorial_role_rules(
                _role, surface="linkedin", lenses=_writing_lenses
            ),
        }
        if _client_contracts is not None:
            _provenance = _client_contracts.provenance
            print(f"  ✓  client stream contract: {_provenance['stream']['identity']}"
                  + "".join(f", lens {lens['identity']} → {'/'.join(lens['stages'])}"
                            for lens in _provenance["lenses"]))
        _editorial_acceptance_path = _role.acceptance_rubric_path
        _editorial_acceptance_identity = _role.acceptance_rubric_identity
        print(f"  ✓  editorial role: {_editorial_role_identity.role_id}")

    active_strategy = load_active_strategy()
    if active_strategy is None:
        print("  ERROR: No active strategy found at strategy/current/strategy.json")
        print("  Cannot generate content without an active strategy.")
        return 1

    cta_mode            = get_cta_mode(active_strategy)
    # #191: a role may declare its own CTA mode. Monday declares "none": its
    # single branded editorial moment is the Never Blank Echo, and the Wix
    # reader is already on the site. The shared channel rules already say
    # "When CTA mode is none, do not add an invitation", so this switches the
    # existing contract off without editing configuration other streams read.
    if _role is not None and _role.cta_mode is not None:
        if _role.cta_mode != cta_mode:
            print(
                f"  ✓  cta_mode:      {_role.cta_mode} "
                f"(role {_role.role_id!r} overrides strategy {cta_mode!r})"
            )
        cta_mode = _role.cta_mode
    strategy_id         = active_strategy.strategy_id
    strategy_started_at = str(active_strategy.started_at) if active_strategy.started_at else ""
    strategy_version    = active_strategy.strategy_version

    try:
        assert_campaign_reference(
            business_configuration, campaign_version=strategy_version
        )
        strategy_execution.decision_lens_editorial.cta(cta_mode)
    except StrategyExecutionError as exc:
        print(f"  ERROR: {exc}")
        return 1

    print(
        "  ✓  business configuration: "
        f"{strategy_execution.identity.configuration_id}@"
        f"{strategy_execution.identity.configuration_version} "
        f"(schema {strategy_execution.identity.schema_version})"
    )
    print(f"  ✓  strategy_id:   {strategy_id}")
    print(f"  ✓  started_at:    {strategy_started_at}")
    print(f"  ✓  cta_mode:      {cta_mode}")

    # ── 2. Obtain the signal ───────────────────────────────────────────────────
    # Two supplies, chosen by role. Wednesday discovers its own signal through
    # the restored July research path (#211); every other run loads one the
    # shared research store already holds, exactly as before.
    _wednesday_supply = (
        is_wednesday_role(_editorial_role_identity)
        and not args.from_package
        and not args.legacy_package
    )
    if _wednesday_supply:
        print("\n[2/6] Wednesday supply — restored July research (RSS → "
              "select → enrich → score → angles)…")
        try:
            signal = supply_wednesday_signal(
                signal_id, seen_ids=published_signal_ids()
            )
        except WednesdaySupplyError as exc:
            # Before the run namespace exists there is no run to account for,
            # so this returns without a terminal report — the same contract
            # every other pre-intake failure follows.
            print(f"  ERROR: {exc}")
            return 1
        if signal is None:
            # July published nothing on a quiet day rather than lowering the
            # bar, and neither does this. An empty Wednesday is a clean stop,
            # never a fall-through to the shared store.
            print("  ✓  no unseen Wednesday candidate — publishing nothing")
            return 0
        # The run is dispatched under the identity July's own algorithm
        # produced, so every artifact this run writes is filed under the
        # historical signal id.
        signal_id = signal.get("SIGNAL_ID", "")
        if not signal_id:
            print("  ERROR: Wednesday research produced a signal with no SIGNAL_ID")
            return 1
        print(f"  ✓  Wednesday signal: {signal_id}")
        # Machine-readable marker for the workflow, which cannot know the id
        # in advance now that Wednesday discovers its own. Same convention as
        # the shared selector's `selected=` line.
        print(f"wednesday_signal_id={signal_id}")
    else:
        if not signal_id:
            print("  ERROR: --signal-id is required for this run "
                  "(only Wednesday fresh generation discovers its own signal)")
            return 1
        print(f"\n[2/6] Loading signal {signal_id}…")
        try:
            signal = _load_signal(signal_id)
        except FileNotFoundError as exc:
            print(f"  ERROR: {exc}")
            return 1

    headline = signal.get("HEADLINE", signal_id)
    print(f"  ✓  Headline: {headline[:70]}")

    # ── Normalized intake + run identity ──────────────────────────────────────
    execution_mode = ExecutionMode.DRY_RUN if args.dry_run else ExecutionMode.CONTROLLED_LIVE
    try:
        assignment = DEFAULT_INTAKE_ADAPTER.adapt(
            signal,
            strategy_ref=active_strategy.strategy_id,
            strategy_version=active_strategy.strategy_version,
            submitted_at=datetime.now(timezone.utc),
        )
    except IntakeAdapterError as exc:
        print(f"  ERROR: {exc}")
        return 1
    run_ctx = RunContext.from_assignment(
        assignment,
        execution_mode,
        configuration_identity=strategy_execution.identity,
    )
    _require_run_id(run_ctx.run_id, "intake")
    print(f"  ✓  run_id:        {run_ctx.run_id}")
    print(f"  ✓  assignment_id: {run_ctx.assignment_id}")
    print(f"  ✓  execution_mode:{run_ctx.execution_mode.value}")

    require_configuration_identity(
        strategy_execution.identity,
        run_ctx.configuration_identity,
        "run-context",
    )
    run_dir = resolve_run_dir(PACKAGES_DIR, signal_id, run_ctx.run_id)
    # From here the run has a namespace and is reportable (Issue #112).
    state.begin(
        run_id=run_ctx.run_id,
        signal_id=signal_id,
        execution_mode=run_ctx.execution_mode.value,
        packages_dir=PACKAGES_DIR,
    )
    try:
        write_business_strategy_snapshot(
            run_dir, business_configuration.model_dump(mode="json")
        )
        # The exact client texts this run executes (#240 D12): identity, path
        # and digest of the stream contract and of every routed lens.
        if _client_contracts is not None:
            (run_dir / "client_contracts.json").write_text(
                json.dumps(_client_contracts.provenance, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        # Canonical intake evidence (Issue #98 / Story #16): the immutable
        # record of what this run was asked to process — the anchor of the
        # run's provenance chain. Written for every run, both branches.
        # Which code is executing this run (Issue #114 / Story #21), read
        # from the local checkout before the run writes anything. Resolved
        # here rather than at report time because the report must describe the
        # code that ran, not whatever is checked out when the run ends.
        _assignment_record = AssignmentRecord(
            run_id=run_ctx.run_id,
            execution_mode=run_ctx.execution_mode.value,
            configuration_identity=strategy_execution.identity,
            assignment=assignment,
            code_identity=resolve_code_identity(),
            editorial_role=_editorial_role_identity,
        )
        write_assignment_json(
            run_dir, json.loads(_assignment_record.model_dump_json())
        )
    except ArtifactCollisionError as exc:
        print(f"  ERROR: {exc}")
        return 1

    try:
        # Issue #121: a coarse discovery label is source metadata, not a
        # request. When it names no configured audience the configured default
        # supplies identity and says so, so the case reaches Decision Lens —
        # which is what decides whether the evidence supports a bounded claim
        # for that audience. An explicit request is still strict and still
        # fails closed; a routing error is never rescued by a default.
        _requested_audience = audience_request(
            assignment, strategy_execution.decision_lens_editorial
        )
        audience_selection = strategy_execution.decision_lens_editorial.select_audience(
            _requested_audience
        )
        research_audience = strategy_execution.research.select_audience(
            _requested_audience
        )
        if audience_selection != research_audience:
            raise StrategyExecutionError("audience selection differs across strategy views")
    except StrategyExecutionError as exc:
        print(f"  ERROR: {exc}")
        return 1

    # ── Compatibility boundary: ContentAssignment → legacy ResearchContext ────
    # Injects run_id so ResearchContext carries run identity into the editorial
    # boundary.  TODO Task #29: remove once downstream stages accept
    # ContentAssignment directly.
    rc = _build_legacy_research_context(assignment, signal, run_ctx)
    rc.strategy_view = strategy_execution.research
    require_configuration_identity(
        strategy_execution.identity, rc.strategy_view.identity, "research-context"
    )
    _assert_run_id_match(run_ctx.run_id, rc.run_id, "research-context")

    # Readiness gate (Issue #101): Release 1 has no trustworthy authorization
    # identity, so a raw override boolean never bypasses a blocking condition.
    # The attempt is carried forward and recorded truthfully in the preserved
    # preflight verdict; it never becomes an authorization claim.
    # Readiness (Issue #101): the rule is unchanged, but its final publication
    # authorization decision belongs to the canonical preflight boundary, so a
    # readiness stop — and any override attempted against it — is preserved
    # evidence instead of an undocumented pre-preflight return.
    _override_attempted = bool(rc.force_override)
    if rc.article_ready:
        _readiness = ReadinessVerdict(verified=True)
    else:
        field_note = (
            "field absent (pre-dates readiness gate)"
            if not signal.get("ARTICLE_READY")
            else f"ARTICLE_READY={rc.article_ready!r}"
        )
        _readiness = ReadinessVerdict(
            verified=False,
            failure_reason=(
                f"{field_note}; SOURCE_PREMISE_VERIFIED="
                f"{rc.source_premise_verified}"
            ),
        )
        if _override_attempted:
            print(
                f"  NOTE: an override was attempted for {signal_id!r} "
                "(FORCE_PUBLISH_OVERRIDE / APPROVED_OVERRIDE). Release 1 has "
                "no trustworthy authorization identity, so an override never "
                "converts a blocking condition into permission to publish."
            )
        print(
            f"  ERROR: Signal {signal_id!r} blocked by readiness — {field_note} "
            f"(SOURCE_PREMISE_VERIFIED={rc.source_premise_verified}). "
            "This signal did not pass enrichment verification and cannot be published."
        )
        # No canonical package can exist for an unready signal: every channel
        # is recorded as an explicit fail-closed "package not constructed"
        # state, and the verdict is persisted before the run stops.
        state.ended(TerminalStage.READINESS, TerminalDisposition.BLOCKED, field_note)
        return _stop_with_preflight(
            run_dir=run_dir,
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            configuration_identity=strategy_execution.identity,
            readiness=_readiness,
            override_attempted=_override_attempted,
        )

    # Run-scoped artifact directory for this execution.
    echo_line = ""
    _generation_run_id: str = run_ctx.run_id   # fresh-gen default; overridden below
    _source_run_id: str     = run_ctx.run_id   # fresh-gen default; overridden below
    research_artifact = None

    if not args.from_package and not args.legacy_package:
        try:
            research_request = build_research_request(
                run_ctx, assignment, signal, strategy_execution.research,
                now=datetime.now(timezone.utc),
            )
            # #211: Wednesday is the historical control path, so its
            # evidence stage must not widen the supply the July research
            # chose. Retrieval fetches the exact SOURCE_URL that signal
            # already cites and nothing else — the adapter below cannot
            # discover — and this guard refuses the request before it is
            # ever made, so a directive that would mean "go looking" stops
            # the run rather than reaching any provider.
            if _wednesday_supply:
                # Two directive shapes mean "go looking": a DISCOVERY
                # directive, and anything that is not an exact URL. Both are
                # refused, so Wednesday's evidence can only ever be the exact
                # source its own July research cited.
                #
                # DirectUrlResearchProvider refuses these on its own — this is
                # deliberately the same rule stated twice. It stops the run
                # here, before a provider is constructed, and says so in terms
                # of Wednesday's supply rather than of a provider contract.
                # The two must agree; a test holds them to it.
                _searchable = tuple(
                    directive.directive_id
                    for directive in research_request.source_directives
                    if directive.priority is not SourcePriority.EXCLUDED
                    and (
                        directive.priority is SourcePriority.DISCOVERY
                        or directive.kind is not SourceDirectiveKind.URL
                    )
                )
                if _searchable or research_request.freshness.allow_open_discovery:
                    print(
                        "  ERROR: Wednesday research would reach provider-side "
                        f"search via {_searchable!r} — the restored July path "
                        "supplies Wednesday's sources, and retrieval may only "
                        "fetch the source that signal already cites"
                    )
                    state.ended(TerminalStage.RESEARCH, TerminalDisposition.FAILED,
                                "wednesday research: provider search requested")
                    return 1
            if research_provider is not None:
                provider = research_provider
            elif _wednesday_supply:
                # #211 product decision: Wednesday is the historical control
                # path, and a control that borrows a stage from the system
                # under test is not a control. July had no research provider
                # at all — its evidence was the article its own discovery
                # cited — so Wednesday retrieves exactly that URL directly.
                # ExaResearchAdapter is not constructed on this path, and
                # neither of its endpoints can be reached from here.
                #
                # This is fidelity, not distrust of the provider: Monday
                # keeps Exa, unchanged. Verification is re-sourced, never
                # removed — the fetch follows redirects, records the final
                # URL, checks the authority, fails closed when the source
                # cannot be read, and emits `not_assessed` evidence that the
                # shared assessment stage and the canonical research gate
                # judge to exactly the same READY standard as Monday's.
                provider = DirectUrlResearchProvider()
                print("  ✓  wednesday retrieval: direct-URL "
                      "(no provider search, no Exa)")
            else:
                try:
                    provider = ExaResearchAdapter()
                except EnvironmentError:
                    provider = MissingCredentialResearchProvider()
            research_artifact = execute_and_persist_research(
                provider, research_request, run_dir,
                identity=strategy_execution.identity,
                run_started_at=run_ctx.started_at,
                judgment_transport=evidence_judgment,
            )
        except EvidenceAssessmentError as exc:
            # Assessment failed — which is not retrieval failing, and must not
            # be reported as though the provider broke. Nothing is promoted.
            print(f"  ERROR: evidence assessment blocked generation: {exc}")
            state.ended(TerminalStage.RESEARCH, TerminalDisposition.FAILED,
                        f"evidence assessment: {type(exc).__name__}")
            return 1
        except (ResearchGateError, ArtifactCollisionError, OSError, ValueError, EnvironmentError) as exc:
            print(f"  ERROR: research gate blocked generation: {exc}")
            state.ended(TerminalStage.RESEARCH, TerminalDisposition.FAILED,
                        f"research gate: {type(exc).__name__}")
            return 1
        print(f"  ✓  research: READY ({run_dir / 'research.json'})")
        state.reached(TerminalStage.RESEARCH)

        # ── Decision policy (Issue #152) ─────────────────────────────────────
        # A role may declare which decision policy governs the run between
        # READY research and generation. "role_bounded_r1" is the explicit R1
        # product decision for two roles now:
        #
        #   Monday  — the Decision Lens's audience-transfer semantics predate
        #             the corrected Monday strategy (reconciliation is #151).
        #   Wednesday — the restored July path (#207/#209) IS Wednesday's
        #             business reasoning, and the canonical Lens is current
        #             shared reasoning that July never had. Leaving it in
        #             front would let it stop a Wednesday run before the
        #             restored path is reached at all — which is exactly what
        #             happened in live run 32769085831, where both criteria
        #             were satisfied and the Lens still returned "revise".
        #
        # This is auditable, not silent — the policy is persisted on
        # assignment.json's editorial_role and in decision_policy.json — and
        # it relaxes nothing downstream: acceptance, source transparency,
        # preflight and the publishers are exactly as strict as before. Every
        # other role, and every run with no role, takes the Lens unchanged.
        if (
            _editorial_role_identity is not None
            and _role.decision_policy == "role_bounded_r1"
        ):
            # The explicit chain link decision.json would otherwise be: a run
            # that skipped the lens with no record would read as corruption to
            # Story #16 provenance — and should. The record is an AUTHORITY,
            # so it is held to the canonical standard: strict typed construct
            # → create-once write → strict reload from disk → identity
            # verification against independently known values. Generation is
            # authorized by the verified on-disk record, never the in-memory
            # object alone.
            try:
                _policy_record = DecisionPolicyRecord(
                    run_id=run_ctx.run_id,
                    assignment_id=assignment.assignment_id,
                    signal_id=research_artifact.signal_id,
                    role_id=_editorial_role_identity.role_id,
                    configuration_version=(
                        _editorial_role_identity.configuration_version
                    ),
                    configuration_identity=strategy_execution.identity,
                    decision_policy="role_bounded_r1",
                    research_readiness=research_artifact.readiness.value,
                )
                write_decision_policy_json(
                    run_dir, json.loads(_policy_record.canonical_json())
                )
                _policy_reloaded = DecisionPolicyRecord.model_validate_json(
                    (run_dir / "decision_policy.json").read_bytes()
                )
                verify_decision_policy_record(
                    _policy_reloaded,
                    run_id=run_ctx.run_id,
                    assignment_id=assignment.assignment_id,
                    signal_id=research_artifact.signal_id,
                    role_id=_editorial_role_identity.role_id,
                    configuration_version=(
                        _editorial_role_identity.configuration_version
                    ),
                    configuration_identity=strategy_execution.identity,
                    research_readiness=research_artifact.readiness.value,
                )
            except (DecisionPolicyError, ArtifactCollisionError, OSError,
                    ValueError) as exc:
                print(f"  ERROR: decision policy authority is not valid: {exc}")
                state.ended(TerminalStage.DECISION, TerminalDisposition.STOPPED,
                            f"decision policy record: {type(exc).__name__}")
                return 1
            print(
                "  ✓  decision policy: role_bounded_r1 — READY research "
                f"authorizes generation for role {_editorial_role_identity.role_id!r} "
                f"({run_dir / 'decision_policy.json'}); the Decision Lens is not "
                "consulted on this run (R1 product decision; R2 reconciliation "
                "tracked in #151)"
            )
            state.reached(TerminalStage.DECISION)
        else:
          # ── Decision Lens gate (Issue #60) ────────────────────────────────
          # The Decision Lens verdict is the mandatory business gate between
          # research and all narrative/editorial/downstream work. The persisted
          # and strict-reloaded decision.json — not the in-memory result — is
          # the artifact that authorizes continuation, and only PROCEED passes.
          try:
              evaluator = (
                  decision_evaluator
                  if decision_evaluator is not None
                  else production_evaluator()
              )
              decision_artifact = evaluate_and_persist_decision(
                  evaluator,
                  research=research_artifact,
                  strategy_view=strategy_execution.decision_lens_editorial,
                  audience=audience_selection,
                  configuration_identity=strategy_execution.identity,
                  lens_profile=RELEASE1_LENS_PROFILE,
                  run_id=run_ctx.run_id,
                  assignment_id=assignment.assignment_id,
                  # The authoritative signal identity is the one carried by the
                  # validated current-run research artifact — never derived from
                  # the assignment identity. run/assignment/signal remain three
                  # independently correct identities in decision.json.
                  signal_id=research_artifact.signal_id,
                  run_dir=run_dir,
              )
              require_proceed(decision_artifact)
          except (DecisionGateError, ArtifactCollisionError, OSError, ValueError) as exc:
              print(f"  ERROR: decision gate blocked generation: {exc}")
              state.ended(TerminalStage.DECISION, TerminalDisposition.STOPPED,
                          f"decision gate: {type(exc).__name__}")
              return 1
          state.reached(TerminalStage.DECISION)
          print(
              f"  ✓  decision: PROCEED ({run_dir / 'decision.json'}) "
              f"[{decision_artifact.decision_lens_version}]"
          )
    elif args.legacy_package:
        print("  ERROR: legacy prepared packages have no canonical research lineage")
        return 1

    if args.from_package or args.legacy_package:
        # ── 3a. Load, verify, and validate existing package ──────────────────
        # All checks complete before any image-generation side effect.
        if args.from_package:
            print(f"\n[3/6] Loading run-scoped package (--from-package)…")
            _source_run_id = args.source_run_id
            try:
                pkg = load_run_generated(PACKAGES_DIR, signal_id, _source_run_id)
            except FileNotFoundError as exc:
                print(f"  ERROR: {exc}")
                return 1
            except ValueError as exc:
                print(f"  ERROR: Package could not be parsed: {exc}")
                return 1

            # Source-identity verification — loaded artifact must match requested address.
            _pkg_run_id = pkg.get("run_id", "")
            if _pkg_run_id != _source_run_id:
                print(
                    f"  ERROR: source identity mismatch: "
                    f"artifact run_id={_pkg_run_id!r} requested source_run_id={_source_run_id!r}"
                )
                return 1
        else:
            # --legacy-package: explicit adapter for flat legacy artifact.
            print(f"\n[3/6] Loading legacy package (--legacy-package)…")
            _legacy_path = PACKAGES_DIR / f"{signal_id}_generated.json"
            if not _legacy_path.exists():
                print(f"  ERROR: Legacy artifact {_legacy_path} not found — "
                      "run without --legacy-package to generate a run-scoped artifact")
                return 1
            try:
                pkg = json.loads(_legacy_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                print(f"  ERROR: Legacy artifact could not be read or parsed: {exc}")
                return 1
            _source_run_id = pkg.get("run_id") or "legacy-unknown"
            print(f"  ⚠  Legacy source (not a run-scoped artifact). source_run_id={_source_run_id!r}")

        # Shape check — must be a JSON object, not an array, scalar, or null.
        if not isinstance(pkg, dict):
            print(f"  ERROR: Package is not a JSON object (got {type(pkg).__name__})")
            return 1

        # Lineage check — the package's social bodies must be derivations of
        # its final accepted article (#259). A package from before that
        # invariant may pair a corrected article with draft-derived social
        # copy; it is refused before any side effect, never republished.
        if pkg.get("social_derivation") != SOCIAL_DERIVATION_LINEAGE:
            print(
                "  ERROR: package predates the social-derivation invariant "
                f"(social_derivation={pkg.get('social_derivation')!r}, required "
                f"{SOCIAL_DERIVATION_LINEAGE!r}) — its social copy may derive from "
                "the pre-review draft; generate a new run instead of reusing it"
            )
            return 1

        # Field-type checks — strategy_id, strategy_version, and generated_at
        # must be non-blank strings before any further processing.
        for _field in ("strategy_id", "strategy_version", "generated_at"):
            _val = pkg.get(_field)
            if not isinstance(_val, str) or not _val.strip():
                print(
                    f"  ERROR: Package field {_field!r} must be a non-blank string "
                    f"(got {type(_val).__name__ if _val is not None else 'missing'})"
                )
                return 1

        # signal_id identity check — must match CLI arg and ContentAssignment.
        _pkg_signal_id = pkg.get("signal_id")
        if not isinstance(_pkg_signal_id, str) or not _pkg_signal_id.strip():
            print(
                f"  ERROR: Package field 'signal_id' must be a non-blank string "
                f"(got {type(_pkg_signal_id).__name__ if _pkg_signal_id is not None else 'missing'})"
            )
            return 1
        if _pkg_signal_id != signal_id:
            print(
                f"  ERROR: signal_id mismatch: package={_pkg_signal_id!r} "
                f"requested={signal_id!r}"
            )
            return 1
        if _pkg_signal_id != assignment.assignment_id:
            print(
                f"  ERROR: signal_id mismatch: package={_pkg_signal_id!r} "
                f"assignment_id={assignment.assignment_id!r}"
            )
            return 1

        # Provenance / staleness check (fail-closed)
        pkg_strategy_id = pkg["strategy_id"]
        if pkg_strategy_id != strategy_id:
            print(f"  ERROR: strategy_id mismatch: package={pkg_strategy_id!r} active={strategy_id!r}")
            return 1
        pkg_strategy_version = pkg["strategy_version"]
        if pkg_strategy_version != strategy_version:
            print(
                f"  ERROR: strategy_version mismatch: "
                f"package={pkg_strategy_version!r} active={strategy_version!r}"
            )
            return 1
        try:
            package_configuration_identity = identity_from_mapping(
                pkg.get("configuration_identity"), boundary="generated-package"
            )
            require_configuration_identity(
                strategy_execution.identity,
                package_configuration_identity,
                "generated-package",
            )
            if args.from_package:
                snapshot_data = load_business_strategy_snapshot(
                    PACKAGES_DIR, signal_id, _source_run_id
                )
                try:
                    snapshot_configuration = BusinessStrategyConfiguration.model_validate(
                        snapshot_data
                    )
                except Exception as exc:
                    raise StrategyExecutionError(
                        "business strategy snapshot is invalid at source-run"
                    ) from exc
                snapshot_identity = strategy_execution.identity.from_configuration(
                    snapshot_configuration
                )
                require_configuration_identity(
                    package_configuration_identity,
                    snapshot_identity,
                    "source-run-snapshot",
                )
                require_configuration_identity(
                    strategy_execution.identity,
                    snapshot_identity,
                    "current-configuration/source-run-snapshot",
                )
                source_envelope = load_research_envelope(
                    PACKAGES_DIR, signal_id, _source_run_id
                )
                research_artifact = validate_research_envelope(
                    source_envelope,
                    run_id=_source_run_id,
                    assignment_id=assignment.assignment_id,
                    signal_id=signal_id,
                    identity=strategy_execution.identity,
                    run_started_at=source_envelope.request.freshness.retrieved_not_before,
                    now=datetime.now(timezone.utc),
                )
                # ── Decision reuse gate (Issue #60 / #174) ────────────────────
                # Reuse honours the source run's persisted decision authority
                # without ever re-running or rewriting it. The XOR contract
                # (#152) holds here exactly as at generation time: a run has
                # decision.json OR decision_policy.json — one authority,
                # never both, never neither.
                _source_run_dir = resolve_run_dir(
                    PACKAGES_DIR, signal_id, _source_run_id
                )
                # ── Source editorial-role binding (#174 correction) ───────
                # assignment.json is the immutable provenance anchor and
                # carries the role the content was actually produced under.
                # Reuse binds it to the dispatched role — never inferred
                # from weekday, package prose, decision artifact or
                # workflow name, and never rewritten here.
                try:
                    _source_assignment = AssignmentRecord.model_validate(
                        load_assignment_json(
                            PACKAGES_DIR, signal_id, _source_run_id
                        )
                    )
                except (FileNotFoundError, ValueError) as exc:
                    raise DecisionGateError(str(exc)) from exc
                except Exception as exc:
                    raise DecisionGateError(
                        f"source assignment.json is invalid: {exc}"
                    ) from exc
                if _source_assignment.run_id != _source_run_id:
                    raise DecisionGateError(
                        "source assignment identity mismatch: "
                        f"assignment run_id={_source_assignment.run_id!r} "
                        f"requested source_run_id={_source_run_id!r}"
                    )
                require_configuration_identity(
                    strategy_execution.identity,
                    _source_assignment.configuration_identity,
                    "source-assignment",
                )
                _source_role = _source_assignment.editorial_role
                if (_source_role is None) != (_editorial_role_identity is None):
                    raise DecisionGateError(
                        "editorial-role binding mismatch: source run was "
                        f"produced under role "
                        f"{None if _source_role is None else _source_role.role_id!r} "
                        "but this dispatch declares role "
                        f"{None if _editorial_role_identity is None else _editorial_role_identity.role_id!r} "
                        "— a package may only be republished under the "
                        "identity that produced it"
                    )
                if _source_role is not None and (
                    _source_role.role_id != _editorial_role_identity.role_id
                    or _source_role.configuration_version
                    != _editorial_role_identity.configuration_version
                ):
                    raise DecisionGateError(
                        "editorial-role binding mismatch: source role "
                        f"{_source_role.role_id!r} "
                        f"(configuration {_source_role.configuration_version!r}) "
                        f"vs dispatched role {_editorial_role_identity.role_id!r} "
                        f"(configuration "
                        f"{_editorial_role_identity.configuration_version!r})"
                    )
                _policy_path = _source_run_dir / "decision_policy.json"
                if (
                    _editorial_role_identity is not None
                    and _role.decision_policy == "role_bounded_r1"
                ):
                    if (_source_run_dir / "decision.json").exists():
                        raise DecisionGateError(
                            "source run carries both decision.json and "
                            "decision_policy.json — corrupt decision "
                            "authority; refusing reuse"
                        )
                    if not _policy_path.exists():
                        raise DecisionGateError(
                            f"No decision_policy.json at {_policy_path}. A "
                            "role_bounded_r1 source run must carry its "
                            "verified policy record."
                        )
                    try:
                        _source_policy = DecisionPolicyRecord.model_validate_json(
                            _policy_path.read_bytes()
                        )
                    except Exception as exc:
                        raise DecisionGateError(
                            f"source decision_policy.json is invalid: {exc}"
                        ) from exc
                    verify_decision_policy_record(
                        _source_policy,
                        run_id=_source_run_id,
                        assignment_id=_source_assignment.assignment.assignment_id,
                        signal_id=signal_id,
                        role_id=_editorial_role_identity.role_id,
                        configuration_version=(
                            _editorial_role_identity.configuration_version
                        ),
                        configuration_identity=strategy_execution.identity,
                        research_readiness=research_artifact.readiness.value,
                    )
                    print(
                        "  ✓  decision policy: role_bounded_r1 (reused from "
                        f"source run {_source_run_id}) — the Decision Lens "
                        "was not consulted at generation and is not "
                        "consulted for republication"
                    )
                else:
                    if _policy_path.exists():
                        raise DecisionGateError(
                            "source run carries decision_policy.json but the "
                            "dispatched role expects a Decision Lens "
                            "decision — identity mismatch; refusing reuse"
                        )
                    source_decision = load_decision_artifact(
                        PACKAGES_DIR,
                        signal_id,
                        _source_run_id,
                        research=research_artifact,
                        audience=audience_selection,
                        configuration_identity=strategy_execution.identity,
                        lens_profile=RELEASE1_LENS_PROFILE,
                    )
                    require_proceed(source_decision)
                    print(
                        f"  ✓  decision: PROCEED (reused from source run "
                        f"{_source_run_id}) [{source_decision.decision_lens_version}]"
                    )
        except DecisionPolicyError as exc:
            print(f"  ERROR: {exc}")
            return 1
        except (FileNotFoundError, ValueError, ResearchGateError, DecisionGateError) as exc:
            print(f"  ERROR: {exc}")
            return 1
        except StrategyExecutionError as exc:
            print(f"  ERROR: {exc}")
            return 1
        raw_gen_at = pkg["generated_at"]
        try:
            from datetime import date
            gen_dt = datetime.fromisoformat(raw_gen_at).date()
        except ValueError:
            print(f"  ERROR: generated_at {raw_gen_at!r} could not be parsed as ISO 8601")
            return 1
        strategy_start = active_strategy.started_at if active_strategy and active_strategy.started_at else None
        if strategy_start and isinstance(strategy_start, str):
            from datetime import date
            strategy_start = date.fromisoformat(strategy_start)
        if strategy_start and gen_dt < strategy_start:
            print(f"  ERROR: Package generated BEFORE active strategy started ({gen_dt} < {strategy_start})")
            return 1

        # generation_run_id: for run-scoped packages the source_run_id IS the
        # generation identity (generated.json belongs to the generation run).
        # For legacy packages, use source_run_id as best-effort provenance.
        _generation_run_id = _source_run_id

        # Preserve original generation timestamp.
        _generated_at = raw_gen_at

        headline       = pkg.get("headline", headline)
        blog_body      = pkg.get("blog_article", "")
        linkedin_text  = pkg.get("linkedin_post", "")
        facebook_text  = pkg.get("facebook_post", "")
        instagram_text = pkg.get("instagram_caption", "")
        threads_seq    = pkg.get("threads_sequence", [])
        telegram_text  = pkg.get("telegram_text", "")
        echo_line      = pkg.get("echo_line", "")

        # Content field type validation — before any slicing, len(), or replace() calls.
        _content_errors: list[str] = []
        for _fname, _fval in [
            ("headline",     headline),
            ("blog_article", blog_body),
            ("linkedin_post", linkedin_text),
        ]:
            if not isinstance(_fval, str) or not _fval.strip():
                _content_errors.append(
                    f"{_fname!r} must be a non-blank string "
                    f"(got {type(_fval).__name__ if not isinstance(_fval, str) else 'blank'})"
                )
        for _fname, _fval in [
            ("facebook_post",    facebook_text),
            ("instagram_caption", instagram_text),
            ("telegram_text",    telegram_text),
            ("echo_line",        echo_line),
        ]:
            if not isinstance(_fval, str):
                _content_errors.append(
                    f"{_fname!r} must be a string (got {type(_fval).__name__})"
                )
        if not isinstance(threads_seq, list) or not all(isinstance(t, str) for t in threads_seq):
            _content_errors.append("'threads_sequence' must be a list of strings")
        if _content_errors:
            for _err in _content_errors:
                print(f"  ERROR: {_err}")
            return 1

        print(f"  ✓  headline:            {headline[:70]}")
        print(f"  ✓  blog:                {len(blog_body)} chars")
        print(f"  ✓  linkedin:            {len(linkedin_text)} chars")
        print(f"  ✓  strategy_id:         {pkg_strategy_id}")
        print(f"  ✓  strategy_version:    {pkg_strategy_version}")
        print(f"  ✓  generated_at:        {raw_gen_at[:10]}")
        print(f"  ✓  generation_run_id:   {_generation_run_id}")
        print(f"  ✓  publication_run_id:  {run_ctx.run_id}")
        print(f"\n  LinkedIn preview (first 400 chars):")
        print(f"  {linkedin_text[:400].replace(chr(10), chr(10)+'  ')}")

        # ── Validate content (before any image side effect) ───────────────────
        _require_run_id(run_ctx.run_id, "validation")
        print(f"\n[4/6] Validating loaded package content…")
        validation_results: list[ValidationResult] = []
        for _platform, _text in [("blog", blog_body), ("linkedin", linkedin_text)]:
            try:
                validate_article_for_publish(_text, platform=_platform, run_id=run_ctx.run_id)
                _vr = ValidationResult(platform=_platform, run_id=run_ctx.run_id, passed=True)
                print(f"  ✓  {_platform} validation passed")
            except Exception as exc:
                _vr = ValidationResult(
                    platform=_platform, run_id=run_ctx.run_id,
                    passed=False, error_message=str(exc),
                )
                print(f"  ✗  {_platform} validation FAILED: {exc}")
            _assert_run_id_match(run_ctx.run_id, _vr.run_id, f"validation-result:{_platform}")
            validation_results.append(_vr)

        if any(not vr.passed for vr in validation_results):
            print(f"\n  ERROR: validation error(s) in loaded package — not publishing")
            return 1

        # ── Visual boundary — typed adapter ───────────────────────────────────
        # Full implementation deferred to Visual System story.
        # Adapter constructed here so visual boundary carries run_id.
        _require_run_id(run_ctx.run_id, "image-preparation")
        _vis_req = VisualArtifactRequest(
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            design_version=CURRENT_DESIGN_VERSION,
            strategy_view=strategy_execution.visual,
        )
        _vis_req.assert_identity(run_ctx.run_id)
        _vis_req.assert_configuration_identity(strategy_execution.identity)
        log.info(
            "visual-boundary: run_id=%s blocked=%s reason=%r",
            _vis_req.run_id, _vis_req.blocked, _vis_req.blocked_reason,
        )

        # ── Visual reuse gate — truthful provenance (Issue #96 / Story #15) ──
        # --from-package is a NEW publication run reusing artifacts produced
        # by the original generation run. The ONLY accepted provenance source
        # is that run's immutable visual passport: origin is never inferred
        # from signal_id or legacy signal-scoped image mappings, the current
        # publication run is never stamped as the visual origin, and the
        # publication uses exactly the derivatives that passport proves.
        # Sources without a trustworthy passport fail closed.
        try:
            _source_visual = load_visual_assets_json(
                PACKAGES_DIR, signal_id, _source_run_id
            )
            _visual_record = reuse_visual_assets_record(
                _source_visual,
                source_run_id=_source_run_id,
                publication_run_id=run_ctx.run_id,
                article_body=blog_body,
            )
            write_visual_assets_json(
                run_dir, json.loads(_visual_record.model_dump_json())
            )
        except (VisualGateError, FileNotFoundError, ValueError,
                ArtifactCollisionError, OSError) as exc:
            print(f"  ERROR: visual gate blocked publication: {exc}")
            state.ended(TerminalStage.VISUAL, TerminalDisposition.BLOCKED,
                        f"visual gate: {type(exc).__name__}")
            return 1
        print(
            f"  ✓  visuals: {_visual_record.status} reused "
            f"(origin run {_visual_record.origin_run_id}; "
            f"linkedin {_visual_record.linkedin_visual.value}) "
            f"({run_dir / 'visual_assets.json'})"
        )

        blog_image_url: Optional[str] = _visual_record.wix_url
        platform_image_urls = {
            p: url
            for p, url in (
                ("blog", _visual_record.wix_url),
                ("linkedin", _visual_record.linkedin_url),
            )
            if url
        }
        print(f"  ✓  Blog image: {blog_image_url[:60] if blog_image_url else '— (none)'}")
        print(f"  ✓  Platform images: {list(platform_image_urls.keys())}")

    else:
        # ── Visual boundary — typed adapter (fresh-gen path) ──────────────────
        _vis_req = VisualArtifactRequest(
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            design_version=CURRENT_DESIGN_VERSION,
            strategy_view=strategy_execution.visual,
        )
        _vis_req.assert_identity(run_ctx.run_id)
        _vis_req.assert_configuration_identity(strategy_execution.identity)
        log.info(
            "visual-boundary: run_id=%s blocked=%s reason=%r",
            _vis_req.run_id, _vis_req.blocked, _vis_req.blocked_reason,
        )

        # ── Image preparation deferred (#177) ────────────────────────────────
        # Paid image generation moves behind every text gate that can still
        # block publication: a run that editorial acceptance, source
        # transparency, validation or LinkedIn composition is going to
        # refuse must not already have paid for assets it cannot publish.
        # Until then the run carries no visuals — which is also what a
        # blocked run honestly preserves.
        #
        # PRODUCT DECISION (#177, authorized): the CONTENT_PACKAGE preview is
        # deliberately removed from the canonical R1 editorial input. It cost
        # one model call, was labelled non-authoritative ("never a source of
        # new facts"), sat outside the evidence chain, was invisible to
        # acceptance and source transparency — and appeared only when the
        # image cache happened to miss, so the steady state never had it.
        # Every fresh run now feeds generation this same canonical empty
        # shape regardless of image-cache state. R2 must not "restore" the
        # old cache-dependent preview as a bug fix; reintroducing it is a
        # product decision with a per-run cost.
        pimgs: dict = {}
        editorial_package: dict = {"images": {"platform_images": {}}}
        blog_image_url: Optional[str] = None
        platform_image_urls: dict = {}

        # #191: diagnostic sink for compositions rejected by local validation.
        _rejected_compositions: list = []

        # ── 3b. Generate content via LLM ─────────────────────────────────────
        print(f"\n[3/6] Generating content (LLM — Editorial Engine V2)…")
        print(f"  strategy context injected: strategy_id={strategy_id}")
        try:
            editorial = rc.to_editorial(editorial_package)
            _assert_run_id_match(run_ctx.run_id, editorial.run_id, "editorial-context")
            # #155: the role's rules demand attribution; only here — after
            # research is READY — can the run say WHAT to attribute. The
            # sources come from the persisted research artifact, never from
            # model memory or invented prompt text, and only roles that
            # require source transparency receive the block.
            if _role is not None and _role.require_source_transparency:
                _editorial_role_rules = {
                    "long": _editorial_role_rules["long"]
                    + render_sources_of_record(research_artifact, surface="wix"),
                    "medium": _editorial_role_rules["medium"]
                    + render_sources_of_record(research_artifact, surface="linkedin"),
                }
            # ── Wednesday runs the restored July path (#207/#209) ─────────
            # Wednesday's editorial intelligence was lost to changes made for
            # Monday — most decisively pattern_extractor, which asserts an
            # owner protagonist and rejects large-company-strategy signals,
            # and which did not exist in July. Rather than reconcile the two
            # products in one engine, Wednesday generates through its own
            # restored package. Everything after this branch — acceptance,
            # transparency, composition acceptance, packaging, preflight and
            # the whole publication lifecycle — is shared and unchanged.
            if is_wednesday_role(_editorial_role_identity):
                print("  ✓  editorial path: restored July Wednesday pipeline")
                article = generate_for_wednesday(editorial.to_legacy_dict())
            else:
                article    = generate_article(
                    editorial.to_legacy_dict(),
                    cta_mode=cta_mode,
                    strategy_context=strategy_execution.decision_lens_editorial,
                    wix_strategy=strategy_execution.wix,
                    linkedin_strategy=strategy_execution.linkedin,
                    audience_selection=audience_selection,
                    research_artifact=research_artifact,
                    editorial_role_rules=_editorial_role_rules,
                    composer_formats=_R1_COMPOSER_FORMATS,
                    # #191: how this role closes its long-form surface. Roles
                    # that declare nothing keep the existing contract.
                    closing_contract=(
                        _role.closing_contract if _role is not None else None
                    ),
                    # #191: compositions our own validator refuses are
                    # preserved for diagnosis instead of dying with the runner.
                    rejected_sink=_rejected_compositions,
                )
            platforms  = article["platforms"]
            structured = article["structured_article"]
        except (ArticleGenerationError, WednesdayGenerationError) as exc:
            _persist_rejected_compositions(run_dir, _rejected_compositions)
            if exc.stage == "pattern_extractor" and isinstance(exc.original, SignalRejectedError):
                # Editorially unsuitable, not broken: recorded, never consumed,
                # and distinguishable so the stream can try the next candidate.
                (run_dir / "editorial_rejection.json").write_text(
                    json.dumps({"signal_id": signal_id, "stage": exc.stage,
                                "reason": str(exc.original)}, indent=2,
                               ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                print(f"  —  signal {signal_id} is editorially unsuitable "
                      f"({exc.original}); not consumed")
                state.ended(TerminalStage.GENERATION, TerminalDisposition.STOPPED,
                            "editorially unsuitable at pattern_extractor")
                return EXIT_EDITORIALLY_UNSUITABLE
            print(f"  ERROR: Editorial Engine failed at stage {exc.stage!r}: {exc.original}")
            return 1

        blog_body      = platforms["long"]["body"]
        # composed after acceptance, from the final article (absent here
        # unless the generation path produced one — the Wednesday route)
        linkedin_text  = platforms.get("medium", {}).get("body", "")
        # The published title is the article's own hook when the composition
        # produced one. Before this, Wix received the source signal's headline —
        # the RSS feed's words on our page. An absent title keeps the previous
        # behaviour rather than inventing one.
        _composed_title = platforms["long"].get("title")
        if _composed_title:
            headline = _composed_title
            print(f"  ✓  article title: {headline[:70]}")
        # #175: inactive surfaces were not composed; their package fields
        # stay present and empty.
        # Every other surface is derived after acceptance, from the final
        # accepted article, never from this draft.
        facebook_text  = ""
        instagram_text = ""
        threads_seq: list[str] = []
        telegram_text  = ""
        echo_line      = structured.get("echo_line", "")

        # ── Pre-acceptance diagnostic evidence (Issue #215) ──────────────────
        # Generation is complete; nothing has judged it yet. The canonical
        # generated.json is written much later, only for a run that survives
        # acceptance — so live run 33283836847 produced a full article and
        # left nothing to inspect when acceptance blocked it. That is exactly
        # backwards: a blocked run is the one whose output you most need to
        # read.
        #
        # These two files are evidence, never product. They are stamped
        # canonical=false / publishable=false / stage=pre_acceptance, no
        # loader reads them, --from-package still requires generated.json, and
        # a blocked article stays blocked. The only thing that changes is that
        # it can be examined afterwards.
        #
        # Scoped to the Wednesday role, on the same predicate that routes
        # generation to the restored July path. This first wrote for every
        # role, on the reasoning that a recording seam decides nothing — but
        # two new files appearing in a Monday run *is* a change to Monday, and
        # these diagnostics exist to explain the restored Wednesday path in
        # particular. Monday and role-less runs are left exactly as they were.
        #
        # Written on a best-effort basis: failing to record diagnostics must
        # never be the reason a run stops, in either direction.
        if is_wednesday_role(_editorial_role_identity):
            try:
                write_signal_snapshot_json(run_dir, signal)
                write_generated_pre_acceptance_json(run_dir, {
                    "run_id": run_ctx.run_id,
                    "signal_id": signal_id,
                    "editorial_role": (
                        _editorial_role_identity.role_id
                        if _editorial_role_identity is not None else None
                    ),
                    # the composed title, or None when the composition produced
                    # none — never the source headline standing in for one
                    "title": _composed_title or None,
                    "structured_article": structured,
                    "platforms": platforms,
                    "echo_line": echo_line,
                    # Whatever the pipeline exposed of its own stages. The July
                    # path returns decision_lens/narrative_spine beside the
                    # article; anything else it publishes at this seam is captured
                    # by name rather than by an assumed schema, so a stage that
                    # starts reporting more is preserved without another change
                    # here — and none of it is required to exist.
                    "stages": {
                        name: article[name]
                        for name in (
                            "decision_lens", "narrative_spine", "hook",
                            "reader_context", "discovery", "story_assembly",
                            "never_blank_voice", "pattern",
                        )
                        if name in article
                    },
                })
                print("  ℹ  pre-acceptance diagnostics written "
                      f"({run_dir / 'generated_pre_acceptance.json'})")
            except (ArtifactCollisionError, OSError, TypeError, ValueError) as exc:
                print(f"  ⚠  pre-acceptance diagnostics not written ({exc}) — "
                      "the run continues; this is evidence, not product")

        # ── Editorial acceptance gate (Issue #89 / Story #13) ────────────────
        # A technically valid article is not automatically publishable. One
        # explicit editorial decision on the canonical Wix article: ACCEPT
        # continues, REVISE triggers exactly one controlled revision followed
        # by one recheck, everything else stops before packaging/publication.
        # Revision touches the Wix article body only — no other channel is
        # regenerated.
        try:
            _acceptance_rubric = (
                EditorialAcceptanceRubric.load(Path(_editorial_acceptance_path))
                if _editorial_acceptance_path
                else EditorialAcceptanceRubric.load()
            )
            if (
                _editorial_acceptance_identity is not None
                and _acceptance_rubric.identity != _editorial_acceptance_identity
            ):
                raise EditorialAcceptanceError(
                    "configured editorial-role rubric identity mismatch: "
                    f"expected {_editorial_acceptance_identity!r}, "
                    f"loaded {_acceptance_rubric.identity!r}"
                )
            _acceptance = run_editorial_acceptance(
                article_body=blog_body,
                research=research_artifact,
                run_id=run_ctx.run_id,
                # #155: the reviser sees the run's real sources, so a fix for
                # one criterion cannot quietly remove the attribution the
                # publication gate requires — and cannot invent a new one.
                sources_of_record=(
                    render_sources_of_record(research_artifact, surface="wix")
                    if _role is not None and _role.require_source_transparency
                    else None
                ),
                rubric=_acceptance_rubric,
                # #254 D10 (temporary, until #253): the reviser inherits the
                # role and the configured voice, so a revision cannot flatten
                # either. Wednesday is paused and keeps its own acceptance.
                revision_context=(
                    RevisionContext(
                        role_rules=render_editorial_role_rules(_role, surface="wix"),
                        voice=strategy_execution.decision_lens_editorial.brand_editorial.voice,
                        lenses=(
                            _client_contracts.for_stage("revision")
                            if _client_contracts is not None else ()
                        ),
                    )
                    if _role is not None
                    and not is_wednesday_role(_editorial_role_identity)
                    else None
                ),
                reviewer=(
                    editorial_reviewer
                    if editorial_reviewer is not None
                    else LlmChatEditorialReviewTransport()
                ),
                revisor=(
                    article_revisor
                    if article_revisor is not None
                    else LlmChatArticleRevisionTransport()
                ),
            )
        except (EditorialAcceptanceError, ValueError, OSError) as exc:
            print(f"  ERROR: editorial acceptance blocked publication: {exc}")
            state.ended(TerminalStage.EDITORIAL, TerminalDisposition.BLOCKED,
                        f"editorial acceptance: {type(exc).__name__}")
            return 1
        # The editorial verdict is persisted for every run that reaches
        # acceptance — accepted or blocked — so the decision history stays
        # auditable. Persisting the audit is NOT permission to continue: the
        # accepted check below still stops every non-ACCEPT outcome before
        # any packaging or publication effect.
        try:
            write_editorial_acceptance_json(
                run_dir,
                {
                    "run_id": run_ctx.run_id,
                    "signal_id": signal_id,
                    **_acceptance.audit,
                },
            )
        except (ArtifactCollisionError, OSError) as exc:
            print(f"  ERROR: editorial acceptance audit could not be persisted: {exc}")
            return 1
        print(f"  ✓  editorial audit: {run_dir / 'editorial_acceptance.json'}")
        if not _acceptance.accepted:
            _final = _acceptance.final_review or _acceptance.initial_review
            # Issue #134: preserve what this run produced so a human can read
            # the article the reviewer refused. Review-only, never a
            # publication input, and never a reason to continue: the block
            # below is unchanged and still ends the run.
            try:
                write_editorial_review_content_json(
                    run_dir,
                    {
                        "run_id": run_ctx.run_id,
                        "signal_id": signal_id,
                        "assignment_id": assignment.assignment_id,
                        "editorial": {
                            "rubric": _acceptance_rubric.identity,
                            "final_disposition": _final.disposition.value,
                            "failed_criterion_ids": list(_final.failed_criterion_ids),
                            "revised": _acceptance.revised,
                        },
                        "content": {
                            "article_as_generated": blog_body,
                            "article_after_revision": (
                                _acceptance.final_article_body
                                if _acceptance.revised
                                else None
                            ),
                            "linkedin_body": linkedin_text,
                        },
                        "visuals": dict(platform_image_urls),
                    },
                )
                print(
                    "  ✓  produced content preserved for review: "
                    f"{run_dir / 'editorial_review_content.json'} (not publishable)"
                )
            except (ArtifactCollisionError, OSError) as exc:
                # Losing the review copy must not change the verdict or hide
                # the real reason the run stopped.
                print(f"  ⚠  produced content could not be preserved: {exc}")
            state.ended(TerminalStage.EDITORIAL, TerminalDisposition.BLOCKED,
                        f"editorial disposition={_final.disposition.value}")
            print(
                "  ERROR: editorial acceptance blocked publication: "
                f"disposition={_final.disposition.value!r} "
                f"failed_criteria={list(_final.failed_criterion_ids)} "
                f"[{_acceptance_rubric.identity}] — the article does not "
                "continue toward packaging or publication"
            )
            return 1
        state.reached(TerminalStage.EDITORIAL)
        blog_body = _acceptance.final_article_body
        # Everything downstream derives from the accepted article — its Echo
        # included. ``structured_final`` is the only outline a derivation may
        # see: the draft's narrative fields are withheld by the composer, and
        # its Echo is replaced here by the accepted one (#259 review).
        echo_line = _accepted_echo(blog_body, echo_line)
        structured_final = {**structured, "echo_line": echo_line or None,
                            "signature": None, "cta_line": None}
        print(
            f"  ✓  editorial acceptance: ACCEPT "
            f"({'after one revision' if _acceptance.revised else 'original article'}) "
            f"[{_acceptance_rubric.identity}]"
        )

        # #196/#197: one record of the accepted compositions and how the
        # social derivative relates to the revision, filled in below.
        _accepted_record = {
            "run_id": run_ctx.run_id,
            "signal_id": signal_id,
            "assignment_id": assignment.assignment_id,
            "editorial": {
                "rubric": _acceptance_rubric.identity,
                "revised": _acceptance.revised,
            },
        }
        _social_recomposed = False

        # ── Social re-composition after revision (Issue #197) ────────────────
        # The canonical content model: final canonical article → channel lens
        # → social derivative. When acceptance revised the article, the
        # social body composed alongside the ORIGINAL article no longer
        # derives from the content that survived review — live run
        # 32725156081 proved the Story #13 guard then (correctly) kills the
        # whole run. The missing operation is re-composition: one composition
        # stage, same channel lens and validators, with the FINAL accepted
        # article as the authoritative source. Nothing else is regenerated —
        # not research, not the article, not the title, not the Echo (it
        # still arrives verbatim from the structured article) — and the
        # stale body is preserved as evidence, never published, never a
        # fallback.
        #
        # Invariant (Monday preview readiness): every social derivative is
        # composed from the FINAL ACCEPTED article — never from the draft,
        # its outline or narrative spine, or a composition made before
        # acceptance. The canonical route composes no social body before
        # acceptance; any route that did (the restored July Wednesday path)
        # has that body discarded here. Every run derives it here, revised
        # or not.
        _stale_social_body = linkedin_text or None
        _accepted_record["social_recomposition"] = {
            "performed": False,
            "reason": (
                "every social derivative is composed from the final "
                "accepted article, after editorial acceptance; any "
                "composition made before acceptance was discarded"
            ),
            "stale_composition_discarded": _stale_social_body,
        }
        try:
            _recomposed = recompose_platform(
                structured_final,
                "medium",
                canonical_body=blog_body,
                cta_mode=cta_mode,
                linkedin_strategy=strategy_execution.linkedin,
                editorial_role_rules=_editorial_role_rules,
                closing_contract=(
                    _role.closing_contract if _role is not None else None
                ),
                research_artifact=research_artifact,
                rejected_sink=_rejected_compositions,
            )
            linkedin_text = _recomposed["body"]
            _social_recomposed = True
            _accepted_record["social_recomposition"]["performed"] = True
            print(
                f"  ✓  social derivative re-composed from the final "
                f"accepted article ({_recomposed['word_count']} words)"
            )
        except ArticleGenerationError as exc:
            # Fail closed before any later gate or side effect: the run
            # has a final accepted article and no valid social
            # derivative. Preserve both facts honestly — Article B with
            # NO social body (the stale one is evidence, not content) —
            # and every rejected attempt for diagnosis.
            print(
                "  ERROR: social re-composition failed after revision: "
                f"{exc.original} — the stale pre-revision composition is "
                "never a fallback; the run stops"
            )
            _persist_rejected_compositions(run_dir, _rejected_compositions)
            _accepted_record["social_recomposition"]["error"] = (
                f"{type(exc.original).__name__}: {exc.original}"
            )
            _accepted_record["content"] = {
                "title": headline,
                "echo": echo_line,
                "article_body": blog_body,
                "linkedin_body": None,
            }
            try:
                write_accepted_composition_json(run_dir, _accepted_record)
                print(
                    "  ✓  accepted article preserved without a social "
                    f"derivative: {run_dir / 'accepted_composition.json'}"
                )
            except (ArtifactCollisionError, OSError) as exc2:
                print(f"  ⚠  accepted article could not be preserved: {exc2}")
            state.ended(
                TerminalStage.LINKEDIN_COMPOSITION,
                TerminalDisposition.BLOCKED,
                f"social recomposition: {type(exc.original).__name__}",
            )
            return 1

        # ── Full-content preview surfaces (owner-controlled, dry run) ────────
        # Facebook and Instagram are not part of Release 1, so a normal run
        # does not pay to compose them (#175). The owner-controlled preview
        # composes them — from the final accepted article, through the same
        # composer, channel lenses and validators — so every intended surface
        # can be inspected before any of them is enabled.
        if args.dry_run and args.preview_fresh_images:
            for _format_key, _rules_key in (("reading", "long"), ("instagram", "medium")):
                try:
                    _derived = recompose_platform(
                        structured_final,
                        _format_key,
                        canonical_body=blog_body,
                        cta_mode=cta_mode,
                        wix_strategy=strategy_execution.wix,
                        linkedin_strategy=strategy_execution.linkedin,
                        # a mapping keyed by THIS format: the composer forwards
                        # a plain string only to long/medium (#259 review)
                        editorial_role_rules={_format_key: (
                            _editorial_role_rules.get(_rules_key)
                            if isinstance(_editorial_role_rules, dict)
                            else _editorial_role_rules
                        )},
                        closing_contract=(
                            _role.closing_contract if _role is not None else None
                        ),
                        research_artifact=research_artifact,
                        rejected_sink=_rejected_compositions,
                    )
                except ArticleGenerationError as exc:
                    print(f"  ERROR: preview {_format_key} composition failed: {exc.original}")
                    _persist_rejected_compositions(run_dir, _rejected_compositions)
                    state.ended(TerminalStage.GENERATION, TerminalDisposition.BLOCKED,
                                f"preview composition {_format_key}: "
                                f"{type(exc.original).__name__}")
                    return 1
                if _format_key == "reading":
                    facebook_text = _derived["body"]
                    # The Facebook surface carries the article's facts, so
                    # the same source-transparency gate the Wix article
                    # passed applies — a preview must show a post that
                    # could honestly be published.
                    if _role is not None and _role.require_source_transparency:
                        try:
                            validate_source_transparency(
                                article_body=facebook_text,
                                research=research_artifact,
                                allowed_destinations=tuple(
                                    d for d in (os.environ.get("NB_WIX_SITE_BASE_URL", ""),) if d
                                ),
                            )
                        except SourceTransparencyError as exc:
                            print(f"  ERROR: preview facebook source transparency: {exc}")
                            state.ended(TerminalStage.EDITORIAL, TerminalDisposition.BLOCKED,
                                        f"preview facebook transparency: {type(exc).__name__}")
                            return 1
                else:
                    instagram_text = _derived["body"]
                print(f"  ✓  preview {_format_key} composed from the final accepted "
                      f"article ({_derived['word_count']} words)")

        # Threads and Telegram: deterministic derivations of the final
        # accepted article — accepted text only, whole sentences only.
        threads_seq   = _build_threads(_composed_title, blog_body, echo_line)
        telegram_text = _build_telegram(_composed_title, blog_body, echo_line)

        # Issue #196: preserve the accepted compositions NOW, before the
        # remaining gates. A run blocked downstream (transparency, images,
        # visuals, preflight) used to lose its accepted article with the
        # runner — live run 32666861632 cost a full regeneration to learn
        # what it had written. Diagnostic evidence only: publishable=false,
        # not canonical, and nothing (including --from-package) loads it, so
        # preservation can never become a route past a gate. #197: written
        # after re-composition, so the record holds the final internally
        # consistent pair — never the revised article beside a stale social
        # body presented as accepted.
        try:
            write_accepted_composition_json(
                run_dir,
                {
                    **_accepted_record,
                    "content": {
                        "title": headline,
                        "echo": echo_line,
                        "article_body": blog_body,
                        "linkedin_body": linkedin_text,
                    },
                },
            )
            print(
                "  ✓  accepted compositions preserved: "
                f"{run_dir / 'accepted_composition.json'} (not publishable)"
            )
        except (ArtifactCollisionError, OSError) as exc:
            # Losing the diagnostic copy never changes the run's verdict —
            # but the run says so honestly instead of silently.
            print(f"  ⚠  accepted compositions could not be preserved: {exc}")

        # ── Wednesday deterministic attribution (Issue #219) ────────────────
        # The restored July composer writes no attribution: July had no
        # transparency gate, and Wednesday's role rules are deliberately inert
        # during generation (#209/#210), so the block that tells Monday's
        # model to cite never reaches it. Live run 33884765429 produced a
        # complete, ACCEPTED article and was stopped here, correctly.
        #
        # The footer is not new: the formatting stage below already appends
        # exactly this line to every stream. It simply appended it *after* this
        # gate, so the body being validated was never the body being published.
        # Applying it here for Wednesday closes both problems at once — the
        # article gains real attribution, and validated body == published body.
        #
        # Deterministic and derived, never generated: no model call, no prompt
        # change, and the URL must be one the research artifact recorded.
        # Placed after social recomposition so the LinkedIn derivation is
        # untouched — the post carries the canonical article link, never the
        # original source URL (#196).
        _attribution_applied = False
        if is_wednesday_role(_editorial_role_identity):
            _attribution = _source_of_record_attribution(signal, research_artifact)
            if _attribution is not None:
                blog_body = ensure_source_line(
                    blog_body, _attribution[0], _attribution[1], "blog_markdown"
                )
                _attribution_applied = True
                print(f"  ✓  wednesday attribution: {_attribution[0] or _attribution[1]}")
            else:
                # Fail open here would be fail open at the gate. Say nothing
                # was added and let source transparency stop the run.
                print("  ⚠  wednesday attribution: no source-of-record URL to cite")

        # Issue #142 review round 2: a role may require source transparency
        # as a fail-closed publication condition. The prompt asked for
        # attribution; here the accepted CANONICAL ARTICLE is verified against
        # the run's ACTUAL sources — a model that ignored the instruction, or
        # invented a link, stops the run before any publisher is called.
        # Roles without the requirement (every other stream, and every run
        # with no role) are never checked.
        #
        # #196 split: this gate owns the canonical article ↔ original sources
        # half of the provenance chain, undiminished. The social half —
        # LinkedIn ↔ the published canonical article URL — cannot be judged
        # here because that URL does not exist until Wix publishes; it is
        # validated by validate_social_lineage in the publication loop. (The
        # old combined check also judged the LinkedIn body 49 lines before
        # its attribution line was appended — the run 32666861632 defect.)
        if _editorial_role_identity is not None and _role.require_source_transparency:
            try:
                validate_source_transparency(
                    article_body=blog_body,
                    research=research_artifact,
                    allowed_destinations=tuple(
                        destination for destination in (
                            os.environ.get("NB_WIX_SITE_BASE_URL", ""),
                        ) if destination
                    ),
                )
            except SourceTransparencyError as exc:
                print(f"  ERROR: source transparency blocked publication: {exc}")
                state.ended(TerminalStage.EDITORIAL, TerminalDisposition.BLOCKED,
                            f"source transparency: {type(exc).__name__}")
                return 1
            print("  ✓  source transparency: attribution verified against run sources")

        print(f"  ✓  blog:      {len(blog_body)} chars")
        print(f"  ✓  linkedin:  {len(linkedin_text)} chars")
        print(f"  ✓  threads:   {len(threads_seq)} posts")
        print(f"\n  LinkedIn preview (first 400 chars):")
        print(f"  {linkedin_text[:400].replace(chr(10), chr(10)+'  ')}")

        # ── 4. Validate ───────────────────────────────────────────────────────
        _require_run_id(run_ctx.run_id, "validation")
        print(f"\n[4/6] Validating generated content…")
        validation_results: list[ValidationResult] = []
        for _platform, _text in [("blog", blog_body), ("linkedin", linkedin_text)]:
            try:
                validate_article_for_publish(_text, platform=_platform, run_id=run_ctx.run_id)
                _vr = ValidationResult(platform=_platform, run_id=run_ctx.run_id, passed=True)
                print(f"  ✓  {_platform} validation passed")
            except Exception as exc:
                _vr = ValidationResult(
                    platform=_platform, run_id=run_ctx.run_id,
                    passed=False, error_message=str(exc),
                )
                print(f"  ✗  {_platform} validation FAILED: {exc}")
            _assert_run_id_match(run_ctx.run_id, _vr.run_id, f"validation-result:{_platform}")
            validation_results.append(_vr)

        if any(not vr.passed for vr in validation_results):
            print(f"\n  ERROR: validation error(s) — not publishing")
            return 1

        # ── 5. Apply formatting + save ─────────────────────────────────────────
        source_name = signal.get("SOURCE_NAME", "")
        source_url  = signal.get("SOURCE_URL", "")
        # #219: Wednesday already applied this exact footer before the
        # transparency gate, so validated body == published body. Skipped
        # rather than made idempotent here so this line stays byte-identical
        # for every other stream.
        #
        # A body closed under the branded-echo-then-sources contract already
        # ends in its one canonical Sources section — composed from the run's
        # own source records (#258) and verified by source transparency. The
        # signal-derived footer would add a second section naming the
        # signal's SOURCE_NAME, a publisher the source record may not hold
        # (controlled live run 35383199073: "## Source [HubSpot Marketing
        # Blog](…)" beside a publisher-less canonical citation).
        _canonical_sources_section = (
            _role is not None
            and _role.closing_contract == CLOSING_BRANDED_ECHO_THEN_SOURCES
        )
        if not _attribution_applied and not _canonical_sources_section:
            blog_body += formatting.source_line(
                source_name, source_url, "blog_markdown"
            )
        # #196: the LinkedIn post no longer carries the original source's URL
        # — the canonical Never Blank article owns the external-source links,
        # and the post's destination is the published article itself. That
        # link cannot be appended here because it does not exist yet; it is
        # bound deterministically after Wix publication succeeds.
        linkedin_text   = formatting.append_hashtags(
            _lead_with_canonical_title(
                formatting.bold_signature_prefix(linkedin_text, "unicode"),
                _composed_title,
            ),
            # Hashtags read the canonical accepted article, never free-text
            # fragments of it (controlled live run 35383199073).
            generate_hashtags(signal, "linkedin", article_text=blog_body),
        )
        if facebook_text:
            facebook_text = _lead_with_canonical_title(
                formatting.bold_signature_prefix(facebook_text, "unicode"),
                _composed_title,
            ) + (
                "" if _canonical_sources_section
                else formatting.source_line(source_name, source_url, "bare_url")
            )
        if instagram_text:
            instagram_text = formatting.append_hashtags(
                _lead_with_canonical_title(
                    formatting.bold_signature_prefix(instagram_text, "unicode"),
                    _composed_title,
                ),
                generate_hashtags(signal, "instagram", article_text=blog_body),
            )

        # ── LinkedIn composition acceptance (Issue #93 / Story #14) ──────────
        # The canonical Release 1 LinkedIn artifact (the composer `medium`
        # body, 120–220-word target) must be demonstrably channel-native and
        # traceable before it may continue toward packaging/publication. A
        # failed LinkedIn acceptance stops the run — never a fallback to
        # another platform body, never a revision loop.
        try:
            _li_record = accept_linkedin_composition(
                linkedin_body=linkedin_text,
                article_body=blog_body,
                # Truthful Story #13 seam: a revised article invalidates the
                # pre-revision LinkedIn composition (fail closed, new run).
                # #197: staleness means "the article was revised AFTER this
                # body was composed". A re-composed body derives from the
                # final accepted article, so it is not stale; the guard
                # itself is untouched and still kills any path that would
                # hand it a pre-revision body.
                article_revised=_acceptance.revised and not _social_recomposed,
                run_id=run_ctx.run_id,
                signal_id=signal_id,
                configuration_identity=strategy_execution.identity,
                strategy_id=strategy_id,
                strategy_version=strategy_version,
            )
            write_linkedin_composition_json(
                run_dir, _li_record.model_dump(mode="json")
            )
        except (LinkedInCompositionError, ArtifactCollisionError, OSError) as exc:
            print(f"  ERROR: LinkedIn composition blocked publication: {exc}")
            state.ended(TerminalStage.LINKEDIN_COMPOSITION,
                        TerminalDisposition.BLOCKED,
                        f"linkedin composition: {type(exc).__name__}")
            return 1
        state.reached(TerminalStage.LINKEDIN_COMPOSITION)
        print(
            f"  ✓  linkedin composition: ACCEPTED "
            f"({_li_record.word_count} words) "
            f"[{_li_record.composition_rules_version}] "
            f"({run_dir / 'linkedin_composition.json'})"
        )

        # ── Image preparation (fresh-gen path, after all text gates — #177) ──
        # Reading the package's images is a local file read — no model call,
        # no upload.
        #
        # The owner-controlled fresh-image preview ignores any cached image
        # and generates a new one for every image surface, so the preview
        # shows the visual pipeline as it actually runs today, end to end.
        fresh_image_preview = bool(args.dry_run and args.preview_fresh_images)
        pimgs = {} if fresh_image_preview else _load_package_images(signal_id)
        pkg_design_version = pimgs.get("_design_version") if pimgs else None
        needs_regen = fresh_image_preview or (
            not pimgs.get("blog", {}).get("url")
            or pkg_design_version != CURRENT_DESIGN_VERSION
        )
        # A dry run never generates or uploads an image (pre-live repair): no
        # image model call, no Cloudinary upload. When the package has no
        # current image the dry run is text-only — it has no visual to gate,
        # and it publishes nothing, so nothing downstream depends on one.
        text_only_dry_run = bool(args.dry_run and needs_regen and not fresh_image_preview)
        if text_only_dry_run:
            pimgs = {}
            needs_regen = False
            print("  —  dry run: text-only — no image generation, no upload")
        if needs_regen:
            reason = "no pre-generated image" if not pimgs else f"stale design v{pkg_design_version} (current: v{CURRENT_DESIGN_VERSION})"
            print(f"  — {reason} — generating images for the active platforms…")
            try:
                from scripts.research.prepare_content import prepare_content_packages
                pkgs = prepare_content_packages(
                    [signal], strategy_execution.research, research_audience,
                    # the preview shows every image surface; a publishing run
                    # composes only the surfaces it publishes (#175)
                    platforms=None if fresh_image_preview else _R1_IMAGE_PLATFORMS,
                    # #177 product decision: no preview generation here either
                    content_package=False,
                    force_regenerate=fresh_image_preview,
                )
                if pkgs:
                    pimgs = pkgs[0].get("images", {}).get("platform_images", {})
                    blog_url = pimgs.get("blog", {}).get("url") or ""
                    print(f"  ✓  Images generated: {blog_url[:60] if blog_url else '(none)'}")
                else:
                    print(f"  ⚠  Image generation returned no packages — visual platforms will skip")
            except RunCallBudgetExceededError:
                # #171: an exhausted call budget is a run stop, never a
                # silent fall-through to "publish without images".
                raise
            except Exception as exc:
                print(f"  ⚠  Image generation failed ({exc}) — visual platforms will skip")

        blog_image_url = pimgs.get("blog", {}).get("url") or None
        platform_image_urls = {
            p: (pimgs.get(p, {}).get("url") or None)
            for p in ("blog", "linkedin", "facebook", "instagram", "threads", "stories")
            if pimgs.get(p, {}).get("url")
        }
        print(f"  ✓  Blog image: {blog_image_url[:60] if blog_image_url else '— (none)'}")
        print(f"  ✓  Platform images: {list(platform_image_urls.keys())}")

        # ── Visual contract gate (Issue #96 / Story #15) ─────────────────────
        # Release 1 rule: the Wix visual is required (no valid Wix visual → no
        # Wix package/publication); a LinkedIn visual is optional, but an
        # attempted LinkedIn visual that failed or is invalid is never
        # silently converted into text-only success. The gate validates the
        # RESULTING derivatives (remote URL, dimensions, format, lineage,
        # design version) and persists the immutable visual passport.
        # A text-only dry run has no image to judge, and the gate guards a
        # publication that a dry run never makes.
        if text_only_dry_run:
            print("  —  visuals: not gated on a text-only dry run")
        else:
            try:
                _visual_record = build_visual_assets_record(
                    pimgs,
                    run_id=run_ctx.run_id,
                    signal_id=signal_id,
                    article_body=blog_body,
                    design_version=CURRENT_DESIGN_VERSION,
                )
                write_visual_assets_json(
                    run_dir, json.loads(_visual_record.model_dump_json())
                )
            except (VisualGateError, ArtifactCollisionError, OSError) as exc:
                print(f"  ERROR: visual gate blocked publication: {exc}")
                state.ended(TerminalStage.VISUAL, TerminalDisposition.BLOCKED,
                            f"visual gate: {type(exc).__name__}")
                return 1
            print(
                f"  ✓  visuals: {_visual_record.status} "
                f"(wix required ok; linkedin {_visual_record.linkedin_visual.value}) "
                f"[{_visual_record.design_version}] "
                f"({run_dir / 'visual_assets.json'})"
            )

        _generated_at = datetime.now(timezone.utc).isoformat()
        _generated_data = {
            "run_id":              run_ctx.run_id,
            "signal_id":           signal_id,
            "headline":            headline,
            # The accepted article title, and only that: None when the
            # composer produced none (``headline`` then falls back to the
            # signal's own headline). The canonical hook every channel
            # derivative leads with.
            "title":               _composed_title or None,
            "social_derivation":   SOCIAL_DERIVATION_LINEAGE,
            "generated_at":        _generated_at,
            "strategy_id":         strategy_id,
            "strategy_version":    strategy_version,
            "strategy_started_at": strategy_started_at,
            "configuration_identity": strategy_execution.identity.model_dump(),
            "blog_article":        blog_body,
            "linkedin_post":       linkedin_text,
            "facebook_post":       facebook_text,
            "instagram_caption":   instagram_text,
            "threads_sequence":    threads_seq,
            "telegram_text":       telegram_text,
        }
        try:
            write_generated_json(run_dir, _generated_data)
        except ArtifactCollisionError as exc:
            print(f"  ERROR: {exc}")
            return 1
        print(f"\n  ✓  Saved {run_dir / 'generated.json'}")
        print(f"       run_id={run_ctx.run_id}  strategy_id={strategy_id}  strategy_version={strategy_version}  generated_at={_generated_at[:19]}")

    if args.dry_run:
        state.ended(TerminalStage.DRY_RUN, TerminalDisposition.COMPLETED)
        report = R1RunReport(
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            execution_mode=run_ctx.execution_mode.value,
            completed=True,
            notes="dry-run — content generated and validated; not published",
        )
        _emit_run_report(report)
        print(f"\n{SEP}")
        if args.from_package:
            print("  DRY RUN — existing package loaded and validated; not published.")
        else:
            print("  DRY RUN — generated content validated; not published.")
        print(f"  run_id: {run_ctx.run_id}  [COMPLETE]")
        print(SEP)
        return 0

    # ── 6. Publish: Wix + LinkedIn ────────────────────────────────────────────
    print(f"\n[5/6] Publishing…")

    # Delete old Wix post if requested (e.g. when republishing with corrections)
    if args.delete_wix_post_id:
        print(f"  Deleting old Wix post {args.delete_wix_post_id}…")
        try:
            import requests
            wix_api_key  = os.getenv("NB_WIX_API_KEY", "")
            wix_site_id  = os.getenv("NB_WIX_SITE_ID", "")
            del_resp = requests.delete(
                f"https://www.wixapis.com/blog/v3/posts/{args.delete_wix_post_id}",
                headers={
                    "Authorization": wix_api_key,
                    "wix-site-id": wix_site_id,
                },
                timeout=15,
            )
            if del_resp.status_code in (200, 204):
                print(f"  ✓  Deleted Wix post {args.delete_wix_post_id}")
            else:
                print(f"  WARNING: Wix delete returned {del_resp.status_code} — continuing anyway")
        except Exception as exc:
            print(f"  WARNING: Wix delete failed ({exc}) — continuing anyway")

    _require_run_id(run_ctx.run_id, "publication")

    # ── Canonical publication packages (Issue #100 / Story #17) ──────────────
    # The strict frozen per-channel packages are the single source for
    # everything handed to the R1 publishers. They are composed only from the
    # run's accepted canonical artifacts plus explicit non-secret target
    # identity; credentials never enter a package (credential readiness is
    # Issue #101 preflight scope). Construction fails closed on any cross-run,
    # cross-signal, or configuration mismatch.
    _generated_source: dict = pkg if (args.from_package or args.legacy_package) else _generated_data
    _li_composition: dict | None = None
    _li_composition_failure: str | None = None
    if args.from_package or args.legacy_package:
        try:
            _li_composition = load_linkedin_composition_json(
                PACKAGES_DIR, signal_id, _source_run_id
            )
        except (FileNotFoundError, ValueError) as exc:
            # Channel-local: the LinkedIn channel has no accepted composition
            # to publish. Wix is unaffected and still reaches preflight.
            _li_composition_failure = f"{type(exc).__name__}: {exc}"
    else:
        _li_composition = _li_record.model_dump(mode="json")

    # Each channel is constructed independently (Issue #101): a channel-local
    # package or target failure becomes a typed channel BLOCK recorded in the
    # preserved verdict, never a whole-run stop that hides the decision.
    def _build_channel(channel: str) -> ChannelPackageOutcome:
        try:
            if channel == "wix":
                target = WixPublicationTarget(
                    site_id=os.getenv("NB_WIX_SITE_ID", ""),
                    owner_member_id=os.getenv("NB_WIX_POST_OWNER_ID", ""),
                    category_ids=tuple(
                        x.strip()
                        for x in [os.getenv("NB_WIX_BLOG_CATEGORY_ID", "")]
                        if x.strip()
                    ),
                    tag_ids=tuple(
                        x.strip()
                        for x in os.getenv("NB_WIX_BLOG_TAG_IDS", "").split(",")
                        if x.strip()
                    ),
                )
            else:
                target = LinkedInPublicationTarget(
                    account_id=os.getenv("NB_ZERNIO_LINKEDIN_ACCOUNT_ID", ""),
                )
        except PydanticValidationError as exc:
            return ChannelPackageOutcome.failed(
                channel,
                f"{type(exc).__name__}: {exc}",
                category=PackageFailureCategory.TARGET,
            )
        try:
            if channel == "wix":
                package = build_wix_publication_package(
                    run_id=run_ctx.run_id,
                    signal_id=signal_id,
                    configuration_identity=strategy_execution.identity,
                    generated=_generated_source,
                    visual_record=_visual_record,
                    target=target,
                )
            else:
                if _li_composition is None:
                    return ChannelPackageOutcome.failed(
                        channel,
                        _li_composition_failure or "no LinkedIn composition",
                        category=PackageFailureCategory.CHANNEL_PACKAGE,
                    )
                package = build_linkedin_publication_package(
                    run_id=run_ctx.run_id,
                    signal_id=signal_id,
                    configuration_identity=strategy_execution.identity,
                    generated=_generated_source,
                    linkedin_composition=_li_composition,
                    visual_record=_visual_record,
                    target=target,
                )
        except PublicationPackageError as exc:
            # The builder classifies its own failure scope: a channel-local
            # payload problem isolates this channel, while configuration /
            # provenance / lineage corruption is shared run evidence and stops
            # every channel. Scope is never inferred from message text.
            return ChannelPackageOutcome.failed(
                channel, f"{type(exc).__name__}: {exc}", category=exc.category
            )
        except PydanticValidationError as exc:
            return ChannelPackageOutcome.failed(
                channel,
                f"{type(exc).__name__}: {exc}",
                category=PackageFailureCategory.CHANNEL_PACKAGE,
            )
        return ChannelPackageOutcome.valid(channel, package)

    _channel_outcomes = [_build_channel(name) for name in _R1_PUBLISHERS]
    for _outcome in _channel_outcomes:
        if _outcome.package is not None:
            print(f"  ✓  {_outcome.channel} package: {_outcome.package.package_digest()}")
        else:
            print(f"  ✗  {_outcome.channel} package: {_outcome.failure_reason}")

    # ── Publication preflight (Issue #101 / Story #17) ───────────────────────
    # The last gate before any external side effect: the exact frozen packages
    # built above are evaluated, the verdict is persisted BEFORE any allowed
    # call, and only ALLOWed channels reach a publisher. Run-level failures
    # block every channel; channel-scoped failures block only their channel.
    _freshness = FreshnessVerdict(
        verified=True,
        rules=(
            ("source_package_generated_at_not_before_strategy_start",
             "strategy_id_and_version_match_active",
             "configuration_identity_matches_source_snapshot")
            if (args.from_package or args.legacy_package)
            else ("configuration_identity_matches_active_strategy",)
        ),
    )
    try:
        preflight = evaluate_publication_preflight(
            packages_dir=PACKAGES_DIR,
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            configuration_identity=strategy_execution.identity,
            channel_outcomes=_channel_outcomes,
            override_attempted=_override_attempted,
            readiness=_readiness,
            freshness=_freshness,
        )
        write_preflight_result_json(
            run_dir, json.loads(preflight.model_dump_json())
        )
    except (ArtifactCollisionError, OSError, ValueError) as exc:
        print(f"\n  ERROR: publication preflight could not be committed: {exc}")
        return 1
    state.reached(TerminalStage.PREFLIGHT)
    print(f"\n  preflight: run={preflight.run_disposition.value} "
          f"({run_dir / 'preflight_result.json'})")
    for _verdict in preflight.channels:
        _detail = (
            ", ".join(reason.value for reason in _verdict.blocking_reasons)
            or _verdict.package_digest
        )
        print(f"    {_verdict.channel:<9} {_verdict.disposition.value:<5} {_detail}")
    if preflight.run_disposition is PreflightDisposition.BLOCK:
        print("  ERROR: publication preflight blocked this run — no channel published.")
        state.ended(
            TerminalStage.PREFLIGHT, TerminalDisposition.BLOCKED,
            *[reason.value for reason in preflight.run_blocking_reasons],
        )
        _emit_run_report(R1RunReport(
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            execution_mode=run_ctx.execution_mode.value,
            errors=[reason.value for reason in preflight.run_blocking_reasons],
            completed=False,
            notes="publication preflight blocked the run",
        ))
        return 1

    results: dict = {}
    wix_post_id: Optional[str] = None
    wix_url = ""
    # #200: the canonical URL is what social will point readers at, so it is
    # only usable once the PROVIDER produced it and it actually resolves to
    # this post. The verdict is evidence either way.
    _canonical_verdict = None
    # #200: the provider-object identity chain, recorded so a human can read
    # "we published post X, we asked for post X, the provider returned this
    # PageUrl for post X" directly out of the run's evidence.
    _provider_lookup_audit = None

    def _verify_canonical(result) -> "CanonicalUrlVerdict":
        """Reachability of the URL the provider attached to this post (#200).

        Identity is already settled by the time we get here: the publisher
        established the URL from the published object itself (retrieve that
        exact post ID, use the PageUrl the provider returns for it) and
        leaves ``url`` empty when it could not. So an empty or
        non-provider-sourced URL means the identity chain did not complete,
        and this refuses it without asking the network anything.
        """
        verdict = verify_canonical_url(
            url=result.url or "",
            provenance=result.url_provenance,
            expected_host=os.environ.get("NB_WIX_SITE_BASE_URL", ""),
        )
        if verdict.verified:
            _moved = (
                f" → {verdict.final_resolved_url[:50]}"
                if verdict.final_resolved_url else ""
            )
            print(
                f"  ✓  canonical article URL verified "
                f"[{verdict.provenance.value}, HTTP {verdict.http_status}]: "
                f"{verdict.url[:70]}{_moved}"
            )
        else:
            print(
                f"  ✗  canonical article URL NOT verified "
                f"({verdict.failure_reason}) — social publication will not "
                "be attempted; the Wix article stays published"
            )
        return verdict

    def _canonical_verdict_ok(verdict) -> bool:
        return verdict is not None and verdict.verified

    # #196: lineage evidence for the LinkedIn attempt — set only once the
    # enriched package exists and holds a persisted final ALLOW.
    _li_evidence: Optional[dict] = None
    # Issue #105: typed, sanitized note when prior publication evidence could
    # not be interpreted — it never suppresses publication, but the run says so.
    _unusable_prior_evidence: Optional[dict] = None

    _r1_cls = {"wix": WixPublisher, "linkedin": LinkedInPublisher}
    _r1_packages = {
        outcome.channel: outcome.package
        for outcome in _channel_outcomes
        if outcome.package is not None
    }
    for name in _R1_PUBLISHERS:
        _verdict = preflight.verdict_for(name)
        if _verdict is None or _verdict.disposition is PreflightDisposition.BLOCK:
            _reasons = (
                ", ".join(r.value for r in _verdict.blocking_reasons)
                if _verdict is not None else "no preflight verdict"
            )
            print(f"  ✗  {name:<12} BLOCKED by preflight ({_reasons}) — not published")
            results[name] = {
                "platform": name, "status": "BLOCKED",
                "error_message": f"publication preflight: {_reasons}",
                "external_id": None, "url": None, "run_id": run_ctx.run_id,
            }
            continue
        # ── Wix gates social publication (Issue #196) ────────────────────
        # The LinkedIn post distributes the published canonical article; its
        # destination is that article's real URL. No canonical URL — Wix
        # blocked, failed, or published without returning one — means there
        # is nothing to distribute, so LinkedIn is NOT attempted. The
        # channels are no longer independent publication siblings.
        # #200: and it must be a URL the PROVIDER produced and that actually
        # resolves. A locally constructed route is a guess about site
        # configuration: run 32740322282 published a social post pointing at
        # exactly such a guess, and it returned 404. No verified canonical
        # URL — no social publication.
        if name == "linkedin" and not _canonical_verdict_ok(_canonical_verdict):
            _wix_status = results.get("wix", {}).get("status", "not attempted")
            _why = (
                _canonical_verdict.failure_reason
                if _canonical_verdict is not None else "wix_not_published"
            )
            print(
                f"  ✗  {name:<12} NOT ATTEMPTED — no verified canonical "
                f"article URL ({_why}; wix: {_wix_status}); social "
                "distributes the published article, so there is nothing to "
                "publish behind"
            )
            results[name] = {
                "platform": name, "status": "BLOCKED",
                "error_message": (
                    f"no verified canonical article URL ({_why}) — "
                    f"wix status: {_wix_status}"
                ),
                "external_id": None, "url": None, "run_id": run_ctx.run_id,
            }
            continue
        try:
            channel_view = (
                strategy_execution.wix
                if name == "wix"
                else strategy_execution.linkedin
            )
            require_configuration_identity(
                strategy_execution.identity,
                channel_view.identity,
                f"{name}-publication",
            )
            _package = _r1_packages[name]
            # The authorized object is the one that crosses the boundary: its
            # digest must still be exactly what the persisted verdict allowed.
            if _package.package_digest() != _verdict.package_digest:
                raise ValueError(
                    f"{name} package digest does not match the preflight verdict"
                )

            # ── Canonical article link enrichment + lineage gate (#196) ──────
            # Runs AFTER the digest check, so what is proven against the
            # run preflight verdict is exactly the authorized package. The
            # enrichment derives a new frozen package whose only difference is
            # the deterministic link block (zero model calls — the URL comes
            # from the Wix publisher's result and nowhere else), and the
            # lineage gate then proves the assembled body points at exactly
            # that URL and at nothing else. Placed BEFORE the idempotency scan
            # so duplicate identity is computed over the body actually
            # published — a recovery run assembles the same body and is
            # recognised.
            if name == "linkedin":
                _derived_from_digest = _package.package_digest()
                # #200: bind the VERIFIED canonical URL — the same string the
                # verdict above proved reachable and post-identifying.
                _canonical_url = _canonical_verdict.url
                _package = bind_canonical_article_url(_package, _canonical_url)
                validate_social_lineage(
                    social_body=_package.linkedin_body,
                    canonical_url=_canonical_url,
                )
                print(
                    f"  ✓  linkedin lineage: post → canonical article "
                    f"({_canonical_url[:60]})"
                )

                # ── Final exact-package authorization (#196 review) ──────────
                # The trust contract is: exact frozen package → exact-package
                # ALLOW → external side effect. The enriched package is a
                # DIFFERENT frozen package from the one the run preflight
                # authorized, so it receives its own verdict from the same
                # preflight machinery — evaluated against its own digest and
                # persisted BEFORE the publisher can be called. Deterministic
                # evidence and rules only; zero model calls.
                _final_preflight = evaluate_publication_preflight(
                    packages_dir=PACKAGES_DIR,
                    run_id=run_ctx.run_id,
                    signal_id=signal_id,
                    configuration_identity=strategy_execution.identity,
                    channel_outcomes=[
                        ChannelPackageOutcome.valid("linkedin", _package)
                    ],
                    override_attempted=_override_attempted,
                    readiness=_readiness,
                    freshness=_freshness,
                )
                write_linkedin_final_preflight_json(
                    run_dir, json.loads(_final_preflight.model_dump_json())
                )
                _final_verdict = _final_preflight.verdict_for("linkedin")
                if (
                    _final_preflight.run_disposition is PreflightDisposition.BLOCK
                    or _final_verdict is None
                    or _final_verdict.disposition is PreflightDisposition.BLOCK
                ):
                    _final_reasons = ", ".join(
                        reason.value
                        for reason in (
                            *_final_preflight.run_blocking_reasons,
                            *(
                                _final_verdict.blocking_reasons
                                if _final_verdict is not None else ()
                            ),
                        )
                    ) or "no final preflight verdict"
                    print(
                        f"  ✗  {name:<12} BLOCKED by final exact-package "
                        f"preflight ({_final_reasons}) — not published"
                    )
                    results[name] = {
                        "platform": name, "status": "BLOCKED",
                        "error_message": (
                            f"final exact-package preflight: {_final_reasons}"
                        ),
                        "external_id": None, "url": None,
                        "run_id": run_ctx.run_id,
                    }
                    continue
                # The critical invariant: the digest of the package handed to
                # the publisher IS the digest the persisted final ALLOW names.
                if _package.package_digest() != _final_verdict.package_digest:
                    raise ValueError(
                        "linkedin enriched package digest does not match the "
                        "persisted final preflight verdict"
                    )
                print(
                    f"  ✓  linkedin final ALLOW bound to "
                    f"{_final_verdict.package_digest[:16]}… "
                    f"({run_dir / 'linkedin_final_preflight.json'})"
                )
                _li_evidence = {
                    "published_package_digest": _package.package_digest(),
                    "derived_from_digest": _derived_from_digest,
                    "canonical_article_url": _canonical_url,
                }

            # ── Wix retry idempotency (Issue #105 / Story #18) ───────────────
            # Runs only after this channel received preflight ALLOW and only on
            # the exact authorized package, so it can suppress an authorized
            # call but never bypass any gate. A proven earlier PUBLISHED result
            # for the same (signal, accepted article, Wix site) means this run
            # creates no second post: no media import, no draft, no publish.
            _scan = None
            if name == "wix":
                _scan = find_prior_wix_publication(
                    PACKAGES_DIR,
                    WixPublicationIdentity.from_package(_package),
                    current_run_id=run_ctx.run_id,
                )
            elif name == "linkedin":
                # Issue #109: the same discipline for LinkedIn — the duplicate
                # identity is the accepted LinkedIn body, not the article, so a
                # different composition of the same article publishes normally.
                _scan = find_prior_linkedin_publication(
                    PACKAGES_DIR,
                    LinkedInPublicationIdentity.from_package(_package),
                    current_run_id=run_ctx.run_id,
                )
            if _scan is not None:
                _note = _scan.evidence_note()
                if _note is not None:
                    _unusable_prior_evidence = _note
                if _scan.match is not None:
                    print(
                        f"  ↺  {name:<12} REUSED — already published by run "
                        f"{_scan.match.run_id} (post {_scan.match.post_id}); "
                        "no duplicate created"
                    )
                    result = _normalize_publish_result(
                        PublishResult(
                            platform=name,
                            status=PublishStatus.REUSED,
                            external_id=_scan.match.post_id,
                            url=_scan.match.url or None,
                            url_provenance=_scan.match.url_provenance,
                            reused_from_run_id=_scan.match.run_id,
                        ),
                        run_ctx.run_id,
                        name,
                    )
                    results[name] = result.to_dict()
                    if name == "wix":
                        wix_post_id = result.external_id
                        # #200: do NOT reuse the URL the earlier run
                        # recorded — evidence written before this fix can
                        # carry a locally constructed route. Re-establish
                        # the identity chain by asking the provider for
                        # this post again (one HTTP call, no publication).
                        _reuse_lookup = WixPublisher().lookup_canonical_url(
                            wix_post_id or "", site_id=_package.target.site_id
                        )
                        _canonical_verdict = _verify_canonical(
                            _reuse_lookup.as_result_view()
                        )
                        wix_url = _canonical_verdict.url
                        _provider_lookup_audit = _reuse_lookup.as_audit_dict()
                    continue

            result = _r1_cls[name]().publish(
                _package, "live", strategy_view=channel_view
            )
            result = _normalize_publish_result(result, run_ctx.run_id, name)
            results[name] = result.to_dict()
            if name == "wix" and result.ok():
                wix_post_id = result.external_id
                wix_url     = result.url or ""
                _canonical_verdict = _verify_canonical(result)
                _lookup = getattr(result, "provider_lookup", None)
                if isinstance(_lookup, ProviderUrlLookup):
                    _provider_lookup_audit = _lookup.as_audit_dict()
        except Exception as exc:
            log.error("%s publish error: %s", name, exc)
            results[name] = {
                "platform": name, "status": "FAILED",
                "error_message": str(exc), "external_id": None, "url": None,
                "run_id": run_ctx.run_id,
            }

    # #196: the lineage/audit fields ride on the LinkedIn result they
    # describe — published, reused, or a failed attempt of the authorized
    # enriched package. A LinkedIn entry blocked before enrichment carries
    # none, honestly.
    if _li_evidence is not None and "linkedin" in results:
        results["linkedin"].update(_li_evidence)

    print()
    for platform, res in results.items():
        status = res.get("status", "?")
        icon = "↺" if status == "REUSED" else ("✓" if status in _OK_STATUSES else "✗")
        print(f"  {icon}  {platform:<12} status={status}")
        print(f"           id={res.get('external_id') or '—'}")
        print(f"           url={(res.get('url') or '—')[:80]}")
        if res.get("error_message"):
            print(f"           error={res['error_message']}")
    print(f"  —  [skipped-not-r1] {', '.join(_NON_R1_PUBLISHERS)}")

    # ── Write publication_results.json (immutable, once per run) ─────────────
    published_at = datetime.now(timezone.utc)
    failed = [
        p for p, r in results.items()
        if r.get("status") not in _COMPLETED_STATUSES
    ]
    _run_errors = [
        results[p].get("error_message") or f"{p} failed"
        for p in failed
    ]
    _pub_results_data = {
        "run_id":             run_ctx.run_id,
        "signal_id":          signal_id,
        "source_run_id":      _source_run_id,
        "generation_run_id":  _generation_run_id,
        "execution_mode":     run_ctx.execution_mode.value,
        "configuration_identity": strategy_execution.identity.model_dump(),
        "published_at":       published_at.isoformat(),
        "results":            results,
        "completed":          not bool(failed),
        "errors":             _run_errors,
        "wix_url":            wix_url,
        "wix_post_id":        wix_post_id,
        # Issue #105 — smallest truthful reuse provenance for this run.
        "wix_reused_from_run_id": (
            results.get("wix", {}).get("reused_from_run_id")
        ),
        "unusable_prior_publication_evidence": _unusable_prior_evidence,
        # #200: how the canonical article URL was established, and why it
        # was refused when it was. A refused candidate is preserved here
        # with its provenance so the failure is diagnosable without
        # republishing anything.
        "canonical_url_verification": (
            _canonical_verdict.as_audit_dict()
            if _canonical_verdict is not None else None
        ),
        "canonical_url_provider_lookup": _provider_lookup_audit,
    }
    try:
        write_publication_results_json(run_dir, _pub_results_data)
    except (ArtifactCollisionError, OSError, TypeError, ValueError) as exc:
        # Publishing already happened, but the run is not complete unless its
        # immutable result artifact is committed.  Do not write history, run
        # analytics, or emit a success report for an unrecorded publication.
        print(f"\n  ERROR: publication results could not be committed: {exc}")
        state.ended(TerminalStage.PUBLICATION, TerminalDisposition.FAILED,
                    f"publication results not committed: {type(exc).__name__}")
        report = R1RunReport(
            run_id=run_ctx.run_id,
            signal_id=signal_id,
            execution_mode=run_ctx.execution_mode.value,
            results={name: r for name, r in results.items()},
            errors=[*_run_errors, f"artifact commit failed: {exc}"],
            completed=False,
        )
        _emit_run_report(report)
        return 1

    # ── Write to History ──────────────────────────────────────────────────────
    publications: dict[str, PlatformPublication] = {}
    for pub_name, pub_dict in results.items():
        if pub_dict.get("status") in _OK_STATUSES:
            publications[pub_name] = PlatformPublication(
                platform=pub_name,
                external_id=pub_dict.get("external_id") or None,
                url=pub_dict.get("url") or "",
                published_at=published_at,
                status=pub_dict.get("status", "published").lower(),
            )

    _is_from_pkg_or_legacy = args.from_package or args.legacy_package
    entry = PublishedEntry(
        content_id=signal_id,
        strategy_id=strategy_id,
        published_at=published_at,
        platform="blog",
        url=wix_url,
        platform_content_id=wix_post_id,
        publications=publications,
        topic=headline,
        cta_mode=cta_mode,
        echo=echo_line or None,
        hook=structured.get("hook", "") if not _is_from_pkg_or_legacy else "",
    )
    try:
        append_published_entry(entry)
        print(f"\n  ✓  History entry written (strategy_id={strategy_id})")
    except Exception as exc:
        print(f"\n  WARNING: History write failed (non-fatal): {exc}")

    # ── Run analytics ─────────────────────────────────────────────────────────
    print(f"\n[6/6] Running analytics…")
    print("  (LinkedIn analytics may return 404 immediately after publish — expected)")
    print()
    analytics_result = run_analytics_pipeline([BlogCollector(), LinkedInCollector()])
    print(analytics_result.format_summary())

    # ── Final run report ──────────────────────────────────────────────────────
    report = R1RunReport(
        run_id=run_ctx.run_id,
        signal_id=signal_id,
        execution_mode=run_ctx.execution_mode.value,
        results={name: r for name, r in results.items()},
        errors=_run_errors,
        completed=not bool(failed),
    )
    _emit_run_report(report)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    state.ended(
        TerminalStage.PUBLICATION,
        TerminalDisposition.FAILED if failed else TerminalDisposition.COMPLETED,
        *_run_errors,
    )
    if failed:
        print(f"  PARTIAL — failed R1 channels: {failed}")
        print(f"  run_id: {run_ctx.run_id}  [FAILED]")
        print(SEP)
        return 1
    print("  DONE — Release 1 channels published (Wix + LinkedIn).")
    print(f"  Wix:     {wix_url or wix_post_id or '—'}")
    print(f"  strategy_id: {strategy_id}")
    print(f"  run_id:      {run_ctx.run_id}  [COMPLETE]")
    print(SEP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
