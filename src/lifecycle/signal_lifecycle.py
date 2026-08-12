"""
Stage 1.5 — Typed Signal Lifecycle Contracts.

Two typed objects gate the research→editorial boundary:

  ResearchContext  — created at selection gate (run_daily_research.py) and
                     publish preflight (generate_and_publish.py) after
                     enrich + angles; replaces raw dict for lifecycle
                     decisions only.

  EditorialContext — boundary contract defined in Stage 1.5 and wired into
                     both production generation paths in Stage 2:
                       ec = rc.to_editorial(pkg)
                       generate_article(ec.to_legacy_dict(), …)

                     The editorial boundary preserves publish semantics:
                     article_ready or force_override admits the signal; the
                     recommendation score remains a selection-time concern.

JSONL files remain append-only. from_dict() reads old records;
to_dict() writes new ones. No read-then-write path exists in the pipeline.
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Derivation functions — single source of truth; used by @property and tests
# ---------------------------------------------------------------------------

def derive_factual_readiness(article_ready: bool) -> str:
    """Return 'ready' or 'insufficient' from factual enrichment result."""
    return "ready" if article_ready else "insufficient"


def derive_admission_status(
    article_ready: bool,
    score_recommended: bool,
    force_override: bool,
) -> str:
    """
    Three possible outcomes (all 8 boolean combinations covered):

      force_override=True               → 'force_override'
      article_ready AND score_recommended → 'admitted'
      anything else                     → 'rejected'

    article_ready=True AND score_recommended=False → 'rejected':
    structurally impossible in current pipeline (enrichment runs only on
    top-N scored candidates) but explicitly defined for correctness.
    """
    if force_override:
        return "force_override"
    if article_ready and score_recommended:
        return "admitted"
    return "rejected"


# ---------------------------------------------------------------------------
# Known JSONL keys — verified against union of all 242 signals_active records
# ---------------------------------------------------------------------------

_KNOWN_JSONL_KEYS: frozenset = frozenset({
    # Present in every record (verified):
    "SIGNAL_ID", "HEADLINE", "SIGNAL_TYPE", "REGION", "INDUSTRY",
    "SOURCE_NAME", "SOURCE_URL", "SOURCE_DATE", "DATE_FOUND",
    "CORE_FACT", "CONFIDENCE", "SOURCE_FOR_CASE", "REAL_COMPANY_EXAMPLE",
    "OUTCOME_IF_KNOWN", "DID_IT_WORK", "EVIDENCE_OF_OUTCOME",
    "SOURCE_QUALITY", "NOTES",
    "ARTICLE_READINESS_SCORE", "SIGNAL_STRENGTH", "CHANNEL_FIT_SCORE",
    "DISCUSSION_POTENTIAL", "score_reason",
    "CORE_TENSION", "BUSINESS_LESSON", "WHY_THIS_CASE_IS_INTERESTING",
    "WHY_IT_MATTERS_TO_BUSINESS", "BUSINESS_RESPONSES_OBSERVED",
    "PROBLEM_FACED", "RESPONSE_TAKEN", "COUNTER_EXAMPLE", "TIME_HORIZON",
    "INTERESTING_QUESTION", "NEVER_BLANK_ANGLE", "POSSIBLE_SIGNATURE_LINE",
    "POTENTIAL_HOOK", "TARGET_AUDIENCE", "PRIMARY_CHANNEL",
    "LINKEDIN_ANGLE", "BLOG_ANGLE", "THREADS_ANGLE", "STORY_ANGLE",
    "raw_summary", "discovery_confidence",
    # Legacy override / alias fields:
    "APPROVED_OVERRIDE",       # always str "" in all 242 records
    "RECOMMENDED_FOR_ARTICLE", # verified alias of ARTICLE_READY (0 mismatches)
    # Stage 1A fields (absent in pre-1A records → handled by from_dict):
    "ARTICLE_READY", "SOURCE_PREMISE_VERIFIED",
    "SCORE_RECOMMENDED_FOR_ARTICLE", "FORCE_PUBLISH_OVERRIDE",
    # Stage 1.5 fields (written going forward):
    "FACTUAL_READINESS", "ADMISSION_STATUS",
    # NOT in known keys → passthrough:
    #   WHY_IT_MATTERS_TO_BUSINESSES (typo variant in some records)
    #   ARTICLE_STATUS, READINESS_REASON (ghost fields from ТЗ drafts)
})


# ---------------------------------------------------------------------------
# ResearchContext
# ---------------------------------------------------------------------------

@dataclass
class ResearchContext:
    """
    Typed wrapper for a research signal after enrich + angles, used from
    selection gate through editorial admission.

    factual_readiness and admission_status are @property: mutation of
    source fields (article_ready, score_recommended, force_override)
    automatically reflects in derived state — stale state is impossible.
    """

    # Identity
    signal_id: str
    headline: str
    signal_type: str
    region: str
    industry: str
    source_name: str
    source_url: str
    source_date: str
    date_found: str

    # Factual evidence (from enrich.py)
    article_ready: bool
    source_premise_verified: str   # "true" | "false" | "unknown"
    core_fact: str
    confidence: str                # "high" | "medium" | "low"
    source_for_case: str | None
    real_company_example: str | None
    outcome_if_known: str
    did_it_work: str
    evidence_of_outcome: str
    source_quality: str
    notes: str

    # Score layer (from score.py)
    score_recommended: bool
    article_readiness_score: int
    signal_strength: str
    channel_fit_score: int
    discussion_potential: str
    score_reason: str

    # Content fields (from enrich.py + angles.py)
    core_tension: str
    business_lesson: str
    why_this_case_is_interesting: str
    why_it_matters_to_business: str
    business_responses_observed: str  # normalized to str (list→json.dumps)
    problem_faced: str
    response_taken: str
    counter_example: str
    time_horizon: str
    interesting_question: str
    never_blank_angle: str
    possible_signature_line: str
    potential_hook: str
    target_audience: str
    primary_channel: str
    linkedin_angle: str
    blog_angle: str
    threads_angle: str
    story_angle: str

    # Override
    force_override: bool
    approved_override_raw: str     # preserves APPROVED_OVERRIDE value as-is

    # Discovery metadata
    raw_summary: str
    discovery_confidence: str

    # Run identity — set by the canonical entry point via _build_legacy_research_context.
    # Default "" preserves backward compat for from_dict() on pre-Task-#27 JSONL records
    # and for the discovery-only path (run_daily_research.py) which has no RunContext.
    run_id: str = field(default="")

    # Unknown legacy keys: preserved for JSONL output, never used for decisions
    _passthrough: dict = field(default_factory=dict, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Derived state as @property — always consistent with source fields
    # ------------------------------------------------------------------

    @property
    def factual_readiness(self) -> str:
        return derive_factual_readiness(self.article_ready)

    @property
    def admission_status(self) -> str:
        return derive_admission_status(
            self.article_ready, self.score_recommended, self.force_override
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        if self.confidence not in {"high", "medium", "low"}:
            raise ValueError(f"Invalid confidence: {self.confidence!r}")
        if self.source_premise_verified not in {"true", "false", "unknown"}:
            raise ValueError(
                f"Invalid source_premise_verified: {self.source_premise_verified!r}"
            )

    # ------------------------------------------------------------------
    # Adapters
    # ------------------------------------------------------------------

    def to_research_dict(self) -> dict:
        """
        For prepare_content_packages() — keys verified against
        scripts/research/prepare_content.py signal.get() calls.
        """
        return {
            "SIGNAL_ID":             self.signal_id,
            "HEADLINE":              self.headline,
            "SIGNAL_TYPE":           self.signal_type,
            "CORE_TENSION":          self.core_tension,
            "BUSINESS_LESSON":       self.business_lesson,
            "CORE_FACT":             self.core_fact,
            "REAL_COMPANY_EXAMPLE":  self.real_company_example,
            "NEVER_BLANK_ANGLE":     self.never_blank_angle,
            "POSSIBLE_SIGNATURE_LINE": self.possible_signature_line,
            "POTENTIAL_HOOK":        self.potential_hook,
            "TARGET_AUDIENCE":       self.target_audience,
        }

    def to_legacy_dict(self) -> dict:
        """
        For generate_article() and post-processing steps in generate_and_publish.py.

        Keys verified against execution path grep (src/editorial/*, hashtags.py,
        generate_and_publish.py lines 230–392).

        ARTICLE_READY = factual readiness only.
        force_override does NOT rewrite ARTICLE_READY — it stays false when
        evidence is insufficient, even when the signal is admitted via override.

        STRATEGY_* keys NOT included: injected by pipeline.py from strategy_context.
        Pattern_extractor output keys NOT included: merged by pipeline.py from pattern.
        """
        return {
            # Preflight keys (generate_and_publish.py lines 237-257)
            "ARTICLE_READY":           "true" if self.article_ready else "false",
            "FORCE_PUBLISH_OVERRIDE":  "true" if self.force_override else "false",
            "APPROVED_OVERRIDE":       self.approved_override_raw,
            "SOURCE_PREMISE_VERIFIED": self.source_premise_verified,
            # pattern_extractor input (pattern_extractor.py lines 181-189)
            "SIGNAL_ID":               self.signal_id,
            "HEADLINE":                self.headline,
            "CORE_FACT":               self.core_fact,
            "CORE_TENSION":            self.core_tension,
            "REAL_COMPANY_EXAMPLE":    self.real_company_example,
            "PROBLEM_FACED":           self.problem_faced,
            "RESPONSE_TAKEN":          self.response_taken,
            "OUTCOME_IF_KNOWN":        self.outcome_if_known,
            "BUSINESS_LESSON":         self.business_lesson,
            "WHY_THIS_CASE_IS_INTERESTING": self.why_this_case_is_interesting,
            "COUNTER_EXAMPLE":         self.counter_example,
            # post-processing (lines 386-387, hashtags.py lines 50-53)
            "SOURCE_NAME":             self.source_name,
            "SOURCE_URL":              self.source_url,
            "INDUSTRY":                self.industry,
        }

    def to_dict(self) -> dict:
        """
        JSONL write path for NEW records created by Stage 1.5 forward.
        Not for rewriting existing records (JSONL is append-only).

        Adds FACTUAL_READINESS and ADMISSION_STATUS to new records.
        Old records without these fields are handled by from_dict()
        which derives them from existing boolean fields.

        RECOMMENDED_FOR_ARTICLE: verified alias of ARTICLE_READY
        (0 mismatches across 242 records; producer enrich.py always
        writes RECOMMENDED_FOR_ARTICLE = ARTICLE_READY).
        """
        typed = {
            "SIGNAL_ID":                     self.signal_id,
            "HEADLINE":                      self.headline,
            "SIGNAL_TYPE":                   self.signal_type,
            "REGION":                        self.region,
            "INDUSTRY":                      self.industry,
            "SOURCE_NAME":                   self.source_name,
            "SOURCE_URL":                    self.source_url,
            "SOURCE_DATE":                   self.source_date,
            "DATE_FOUND":                    self.date_found,
            "ARTICLE_READY":                 "true" if self.article_ready else "false",
            "SOURCE_PREMISE_VERIFIED":       self.source_premise_verified,
            "SCORE_RECOMMENDED_FOR_ARTICLE": "true" if self.score_recommended else "false",
            "RECOMMENDED_FOR_ARTICLE":       "true" if self.article_ready else "false",
            "APPROVED_OVERRIDE":             self.approved_override_raw,
            "FORCE_PUBLISH_OVERRIDE":        "true" if self.force_override else "false",
            "CORE_FACT":                     self.core_fact,
            "CONFIDENCE":                    self.confidence,
            "SOURCE_FOR_CASE":               self.source_for_case,
            "REAL_COMPANY_EXAMPLE":          self.real_company_example,
            "OUTCOME_IF_KNOWN":              self.outcome_if_known,
            "DID_IT_WORK":                   self.did_it_work,
            "EVIDENCE_OF_OUTCOME":           self.evidence_of_outcome,
            "SOURCE_QUALITY":                self.source_quality,
            "NOTES":                         self.notes,
            "ARTICLE_READINESS_SCORE":       str(self.article_readiness_score),
            "SIGNAL_STRENGTH":               self.signal_strength,
            "CHANNEL_FIT_SCORE":             str(self.channel_fit_score),
            "DISCUSSION_POTENTIAL":          self.discussion_potential,
            "score_reason":                  self.score_reason,
            "CORE_TENSION":                  self.core_tension,
            "BUSINESS_LESSON":               self.business_lesson,
            "WHY_THIS_CASE_IS_INTERESTING":  self.why_this_case_is_interesting,
            "WHY_IT_MATTERS_TO_BUSINESS":    self.why_it_matters_to_business,
            "BUSINESS_RESPONSES_OBSERVED":   self.business_responses_observed,
            "PROBLEM_FACED":                 self.problem_faced,
            "RESPONSE_TAKEN":                self.response_taken,
            "COUNTER_EXAMPLE":               self.counter_example,
            "TIME_HORIZON":                  self.time_horizon,
            "INTERESTING_QUESTION":          self.interesting_question,
            "NEVER_BLANK_ANGLE":             self.never_blank_angle,
            "POSSIBLE_SIGNATURE_LINE":       self.possible_signature_line,
            "POTENTIAL_HOOK":                self.potential_hook,
            "TARGET_AUDIENCE":               self.target_audience,
            "PRIMARY_CHANNEL":               self.primary_channel,
            "LINKEDIN_ANGLE":                self.linkedin_angle,
            "BLOG_ANGLE":                    self.blog_angle,
            "THREADS_ANGLE":                 self.threads_angle,
            "STORY_ANGLE":                   self.story_angle,
            "raw_summary":                   self.raw_summary,
            "discovery_confidence":          self.discovery_confidence,
            # Stage 1.5 new fields (absent in pre-1.5 records):
            "FACTUAL_READINESS":             self.factual_readiness,
            "ADMISSION_STATUS":              self.admission_status,
        }
        # Passthrough fields last; typed fields take precedence on collision
        return {**self._passthrough, **typed}

    def to_editorial(self, pkg: dict) -> "EditorialContext":
        """
        Factory: construct EditorialContext from self + content_package dict.
        Raises ValueError when the signal is neither factually ready nor
        explicitly force-overridden.
        """
        # Publishing has always admitted factually-ready signals regardless of the
        # earlier recommendation score.  Preserve that contract at the editorial
        # boundary: score controls selection, not a second publish-time veto.
        if not self.article_ready and not self.force_override:
            raise ValueError(
                f"Signal {self.signal_id!r}: not factually ready and no override "
                f"(factual_readiness={self.factual_readiness!r}); "
                "cannot construct EditorialContext"
            )
        editorial_admission = (
            "force_override" if self.force_override else "admitted"
        )
        return EditorialContext(
            run_id=self.run_id,
            signal_id=self.signal_id,
            headline=self.headline,
            factual_readiness=self.factual_readiness,
            admission_status=editorial_admission,
            force_override=self.force_override,
            article_ready=self.article_ready,
            source_premise_verified=self.source_premise_verified,
            approved_override_raw=self.approved_override_raw,
            core_fact=self.core_fact,
            core_tension=self.core_tension,
            business_lesson=self.business_lesson,
            real_company_example=self.real_company_example,
            outcome_if_known=self.outcome_if_known,
            problem_faced=self.problem_faced,
            response_taken=self.response_taken,
            why_this_case_is_interesting=self.why_this_case_is_interesting,
            counter_example=self.counter_example,
            never_blank_angle=self.never_blank_angle,
            possible_signature_line=self.possible_signature_line,
            potential_hook=self.potential_hook,
            target_audience=self.target_audience,
            linkedin_angle=self.linkedin_angle,
            blog_angle=self.blog_angle,
            threads_angle=self.threads_angle,
            story_angle=self.story_angle,
            source_name=self.source_name,
            source_url=self.source_url,
            industry=self.industry,
            pkg_raw=pkg,
        )

    # ------------------------------------------------------------------
    # Deserialization
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict) -> "ResearchContext":
        """
        Read path: deserialize from JSONL dict, including pre-Stage-1A records
        where ARTICLE_READY, SOURCE_PREMISE_VERIFIED, etc. are absent (None).

        Documented normalizations (not silent):
          ARTICLE_READY=None          → article_ready=False
          SCORE_RECOMMENDED=None      → score_recommended=False
          FORCE_PUBLISH_OVERRIDE=None → contributes False to force_override
          SOURCE_PREMISE_VERIFIED=None → "unknown"
          BUSINESS_RESPONSES_OBSERVED: list → json.dumps(list)
          ARTICLE_READINESS_SCORE: str|None → int (0 if absent/invalid)
          CHANNEL_FIT_SCORE: str|None       → int (0 if absent/invalid)
        """

        def _bool(v) -> bool:
            return str(v or "").lower() == "true"

        def _int(v, default: int = 0) -> int:
            try:
                return int(v or default)
            except (ValueError, TypeError):
                return default

        def _str(v, default: str = "") -> str:
            if v is None:
                return default
            return v if isinstance(v, str) else str(v)

        def _spv(v) -> str:
            if v is None:
                return "unknown"
            s = str(v).lower()
            return s if s in ("true", "false", "unknown") else "unknown"

        def _bro(v) -> str:
            if isinstance(v, list):
                return _json.dumps(v, ensure_ascii=False)
            return _str(v)

        force_override = (
            _bool(d.get("FORCE_PUBLISH_OVERRIDE"))
            or _bool(d.get("APPROVED_OVERRIDE"))
        )

        passthrough = {k: v for k, v in d.items() if k not in _KNOWN_JSONL_KEYS}

        return cls(
            signal_id=_str(d.get("SIGNAL_ID")),
            headline=_str(d.get("HEADLINE")),
            signal_type=_str(d.get("SIGNAL_TYPE")),
            region=_str(d.get("REGION")),
            industry=_str(d.get("INDUSTRY")),
            source_name=_str(d.get("SOURCE_NAME")),
            source_url=_str(d.get("SOURCE_URL")),
            source_date=_str(d.get("SOURCE_DATE")),
            date_found=_str(d.get("DATE_FOUND")),
            article_ready=_bool(d.get("ARTICLE_READY")),
            source_premise_verified=_spv(d.get("SOURCE_PREMISE_VERIFIED")),
            core_fact=_str(d.get("CORE_FACT")),
            confidence=_str(d.get("CONFIDENCE"), "low"),
            source_for_case=d.get("SOURCE_FOR_CASE"),
            real_company_example=d.get("REAL_COMPANY_EXAMPLE"),
            outcome_if_known=_str(d.get("OUTCOME_IF_KNOWN"), "unknown"),
            did_it_work=_str(d.get("DID_IT_WORK"), "unknown"),
            evidence_of_outcome=_str(d.get("EVIDENCE_OF_OUTCOME")),
            source_quality=_str(d.get("SOURCE_QUALITY")),
            notes=_str(d.get("NOTES")),
            score_recommended=_bool(d.get("SCORE_RECOMMENDED_FOR_ARTICLE")),
            article_readiness_score=_int(d.get("ARTICLE_READINESS_SCORE")),
            signal_strength=_str(d.get("SIGNAL_STRENGTH")),
            channel_fit_score=_int(d.get("CHANNEL_FIT_SCORE")),
            discussion_potential=_str(d.get("DISCUSSION_POTENTIAL")),
            score_reason=_str(d.get("score_reason")),
            core_tension=_str(d.get("CORE_TENSION")),
            business_lesson=_str(d.get("BUSINESS_LESSON")),
            why_this_case_is_interesting=_str(d.get("WHY_THIS_CASE_IS_INTERESTING")),
            why_it_matters_to_business=_str(d.get("WHY_IT_MATTERS_TO_BUSINESS")),
            business_responses_observed=_bro(d.get("BUSINESS_RESPONSES_OBSERVED")),
            problem_faced=_str(d.get("PROBLEM_FACED")),
            response_taken=_str(d.get("RESPONSE_TAKEN")),
            counter_example=_str(d.get("COUNTER_EXAMPLE")),
            time_horizon=_str(d.get("TIME_HORIZON")),
            interesting_question=_str(d.get("INTERESTING_QUESTION")),
            never_blank_angle=_str(d.get("NEVER_BLANK_ANGLE")),
            possible_signature_line=_str(d.get("POSSIBLE_SIGNATURE_LINE")),
            potential_hook=_str(d.get("POTENTIAL_HOOK")),
            target_audience=_str(d.get("TARGET_AUDIENCE"), "founder"),
            primary_channel=_str(d.get("PRIMARY_CHANNEL")),
            linkedin_angle=_str(d.get("LINKEDIN_ANGLE")),
            blog_angle=_str(d.get("BLOG_ANGLE")),
            threads_angle=_str(d.get("THREADS_ANGLE")),
            story_angle=_str(d.get("STORY_ANGLE")),
            raw_summary=_str(d.get("raw_summary")),
            discovery_confidence=_str(d.get("discovery_confidence")),
            force_override=force_override,
            approved_override_raw=_str(d.get("APPROVED_OVERRIDE")),
            run_id=_str(d.get("run_id")),
            _passthrough=passthrough,
        )


# ---------------------------------------------------------------------------
# EditorialContext
# ---------------------------------------------------------------------------

@dataclass
class EditorialContext:
    """
    Typed wrapper for a signal admitted to the Editorial Engine.
    Constructed via ResearchContext.to_editorial(pkg).

    admission_status must be 'admitted' or 'force_override'.
    'rejected' signals never reach here — to_editorial() raises ValueError.

    pkg_raw holds the content_package dict from prepare_content_packages()
    unchanged and exposes it to Editorial Engine prompts as supporting context.
    """

    # From ResearchContext
    signal_id: str
    headline: str
    factual_readiness: str
    admission_status: str        # "admitted" | "force_override" only
    force_override: bool
    article_ready: bool          # preserved for exact ARTICLE_READY in to_legacy_dict
    source_premise_verified: str
    approved_override_raw: str
    core_fact: str
    core_tension: str
    business_lesson: str
    real_company_example: str | None
    outcome_if_known: str
    problem_faced: str
    response_taken: str
    why_this_case_is_interesting: str
    counter_example: str
    never_blank_angle: str
    possible_signature_line: str
    potential_hook: str
    target_audience: str
    linkedin_angle: str
    blog_angle: str
    threads_angle: str
    story_angle: str
    source_name: str
    source_url: str
    industry: str

    # From content_package dict
    pkg_raw: dict = field(default_factory=dict, repr=False)

    # Run identity — propagated from RunContext via ResearchContext.
    # Default "" preserves backward compat with tests and non-canonical paths.
    run_id: str = field(default="")

    def __post_init__(self) -> None:
        if self.admission_status not in ("admitted", "force_override"):
            raise ValueError(
                f"EditorialContext requires admission_status 'admitted' or "
                f"'force_override', got {self.admission_status!r}"
            )

    def to_legacy_dict(self) -> dict:
        """
        Returns the dict consumed by generate_article() and post-processing.

        ARTICLE_READY = factual readiness only (not admission status).
        Does not include STRATEGY_* (injected by pipeline.py from strategy_context)
        or pattern_extractor output keys (merged by pipeline.py from pattern).
        """
        return {
            "ARTICLE_READY":                 "true" if self.article_ready else "false",
            "FORCE_PUBLISH_OVERRIDE":        "true" if self.force_override else "false",
            "APPROVED_OVERRIDE":             self.approved_override_raw,
            "SOURCE_PREMISE_VERIFIED":       self.source_premise_verified,
            "SIGNAL_ID":                     self.signal_id,
            "HEADLINE":                      self.headline,
            "CORE_FACT":                     self.core_fact,
            "CORE_TENSION":                  self.core_tension,
            "REAL_COMPANY_EXAMPLE":          self.real_company_example,
            "PROBLEM_FACED":                 self.problem_faced,
            "RESPONSE_TAKEN":                self.response_taken,
            "OUTCOME_IF_KNOWN":              self.outcome_if_known,
            "BUSINESS_LESSON":               self.business_lesson,
            "WHY_THIS_CASE_IS_INTERESTING":  self.why_this_case_is_interesting,
            "COUNTER_EXAMPLE":               self.counter_example,
            # Editorial direction must survive the typed boundary.  Stage 1.5's
            # narrower adapter dropped these fields and produced generic framing.
            "NEVER_BLANK_ANGLE":             self.never_blank_angle,
            "POSSIBLE_SIGNATURE_LINE":       self.possible_signature_line,
            "POTENTIAL_HOOK":                 self.potential_hook,
            "TARGET_AUDIENCE":                self.target_audience,
            "LINKEDIN_ANGLE":                 self.linkedin_angle,
            "BLOG_ANGLE":                     self.blog_angle,
            "THREADS_ANGLE":                  self.threads_angle,
            "STORY_ANGLE":                    self.story_angle,
            "SOURCE_NAME":                   self.source_name,
            "SOURCE_URL":                    self.source_url,
            "INDUSTRY":                      self.industry,
            # Keep the prepared package as supporting context, not as authority;
            # prompts still require claims to be grounded in the verified signal.
            "CONTENT_PACKAGE":                self.pkg_raw,
        }
