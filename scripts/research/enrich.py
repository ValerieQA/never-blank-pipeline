"""
Stage 4 — Enrichment.
Fill full signal schema via LLM. Never invents case sources, outcomes, or company examples.
"""

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.utils.logger import get_logger
from src.utils.llm_client import chat, model_enrich
from src.utils.config_loader import load_prompt
from src.strategy.client_contract import ClientConfigurationError
from src.strategy.contract_fit import RISK_RULE_ID, TOPIC_RULE_ID, contract_fit_rules

log = get_logger("research.enrich")

_NULL_CASE = {
    "REAL_COMPANY_EXAMPLE":  None,
    "OUTCOME_IF_KNOWN":      "unknown",
    "DID_IT_WORK":           "unknown",
    "CONFIDENCE":            "low",
    "RECOMMENDED_FOR_ARTICLE": "false",
}

#: The two E-01 fields S-00's `ContractFitRules` read, spelled as the intake
#: record spells them (#365). Stage 4 is where a record acquires them: seam 1
#: passes the intake record through and may not synthesise a classification it
#: was never given.
DOMAIN_FIELD = "EDITORIAL_DOMAIN"
RISK_FIELD   = "EDITORIAL_RISK"

#: What became of each classification, recorded beside the value in a field no
#: `FitRule` reads. S-00 refuses `outside_admitted` and `cannot_answer` alike —
#: it cannot tell them apart and does not need to — but the record must: a
#: signal deliberately placed outside the client's vocabulary and a classifier
#: that failed are two different facts about the run.
DOMAIN_OUTCOME_FIELD = "EDITORIAL_DOMAIN_OUTCOME"
RISK_OUTCOME_FIELD   = "EDITORIAL_RISK_OUTCOME"

#: The three outcomes. Only ADMITTED comes with a value; for the other two the
#: value field is absent, and absence is never normalised into an admitted value.
ADMITTED         = "admitted"
OUTSIDE_ADMITTED = "outside_admitted"
CANNOT_ANSWER    = "cannot_answer"

#: The one answer other than a listed value, owner-approved 2026-09-29. The
#: classifier chooses among the configured values and is never asked to invent
#: a category of its own, so a deliberate "none of these" needs a way to be
#: said: this token, substituted into the rendered prompt from here and from
#: nowhere else. It is a protocol token and never a category — it is the only
#: answer recorded as OUTSIDE_ADMITTED, it is never written to a value field,
#: and it is never added to the Client Contract, which stays a pure allow-list.
OUTSIDE_ADMITTED_TOKEN = "none_of_these"

#: Which of the two evidence paths verified the premise. Both already satisfy
#: `SOURCE_PREMISE_VERIFIED`, and that boolean is the whole of what survives
#: today: `determine_article_readiness` computes the distinction, states it in
#: a reason string, and the record keeps no trace of it.
#:
#: The Golden Engine's Monday role is `never-blank-monday-documented-case`, and
#: a documented case is exactly path 1 — a named company with a source for the
#: case. Path 2 is legitimate Never Blank material and is not a case: it is
#: research or data standing on its own, explicitly "without a named company".
#: Recording which one verified the premise is therefore the difference between
#: a role being able to select its own material and a person guessing.
#:
#: This is a derivation, not a judgement: the booleans below are the ones the
#: readiness check already computes, and no model is asked anything new.
PREMISE_PATH_FIELD = "SOURCE_PREMISE_PATH"

#: The two paths, closed. Absence is a third state and is never a value: a
#: signal whose premise does not verify carries no path at all, exactly as an
#: unclassified signal carries no domain (#365).
COMPANY_CASE  = "company_case"
RESEARCH_DATA = "research_data"


def premise_path(signal: dict) -> Optional[str]:
    """Which evidence path verifies this signal's premise, or ``None``.

    Deterministic, no model call, no side effects — the same three fields
    :func:`determine_article_readiness` reads, in the same order of precedence
    it applies: a verified company case is path 1 even when the research path
    would also hold, because a named company with a source for the case is the
    stronger statement and is the one a documented-case role needs.

    ``None`` means the premise does not verify at all. It never means
    "research/data", and it is never written to the record as a value.
    """

    has_company = bool(signal.get("REAL_COMPANY_EXAMPLE"))
    has_source  = bool(signal.get("SOURCE_FOR_CASE"))
    confidence  = signal.get("CONFIDENCE", "low")

    if has_company and has_source:
        return COMPANY_CASE
    if has_source and confidence in ("high", "medium"):
        return RESEARCH_DATA
    return None


def determine_article_readiness(signal: dict) -> tuple[bool, str]:
    """
    Deterministic, no-LLM, no-side-effects check for factual article readiness.

    Scoring recommendation != factual article readiness.
    A signal becomes article-ready only after deterministic enrichment verification.

    Two valid evidence paths (either satisfies SOURCE_PREMISE_VERIFIED):
      1. Verified company case: REAL_COMPANY_EXAMPLE + SOURCE_FOR_CASE
      2. Verified research/data: SOURCE_FOR_CASE alone with CONFIDENCE >= medium
         (covers research on customer memory, trust, visibility without a named company)

    Returns (ready: bool, reason: str).
    """
    has_company  = bool(signal.get("REAL_COMPANY_EXAMPLE"))
    has_source   = bool(signal.get("SOURCE_FOR_CASE"))
    has_fact     = bool(signal.get("CORE_FACT", "").strip())
    confidence   = signal.get("CONFIDENCE", "low")
    signal_strength_ok = confidence in ("high", "medium")

    # Path 1: verified company case
    company_case_verified = has_company and has_source
    # Path 2: verified research/data — source present + sufficient confidence
    research_verified = has_source and signal_strength_ok

    premise_verified = company_case_verified or research_verified

    if not premise_verified:
        if not has_source:
            return False, "SOURCE_PREMISE_VERIFIED=false: missing SOURCE_FOR_CASE"
        return False, (
            "SOURCE_PREMISE_VERIFIED=false: SOURCE_FOR_CASE present but "
            f"CONFIDENCE={confidence!r} is insufficient for research path "
            "(need medium or high, or provide REAL_COMPANY_EXAMPLE)"
        )
    if not has_fact:
        return False, "missing CORE_FACT"

    # Explicit disclaimer in CORE_FACT overrides confidence-based paths.
    # Prevents research path from accepting a signal the LLM itself flagged as unverified.
    _UNVERIFIED_MARKERS = ("not verified", "unverified", "unverifiable", "unsupported", "cannot be confirmed")
    fact_lower = signal.get("CORE_FACT", "").lower()
    for marker in _UNVERIFIED_MARKERS:
        if marker in fact_lower:
            return False, f"CORE_FACT contains explicit disclaimer ({marker!r}) — claim is not verifiable"

    return True, "evidence verified" + (" (company case)" if company_case_verified else " (research/data)")


def admitted_vocabularies() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The client's admitted editorial domains and risk levels, in its spelling.

    Read through S-00's own producer rather than restated here: what the
    classifier is offered is exactly what the fit rules will admit, and the
    vocabulary lives in the Client Contract and in no second place. Editing
    `## Editorial domain` there changes what this stage offers.
    """
    rules = contract_fit_rules(domain_field=DOMAIN_FIELD, risk_field=RISK_FIELD)
    admits = {rule.rule_id: rule.admits for rule in rules.rules}
    return admits[TOPIC_RULE_ID], admits[RISK_RULE_ID]


def classify_against(
    stated: object, admits: tuple[str, ...], *, failed: bool
) -> tuple[str | None, str]:
    """One classification as the record will carry it: (value, outcome).

    A value comes back only with ADMITTED, and only for an answer that is
    exactly one of the configured values — the record states one configured
    value, in the contract's own spelling, or it states nothing at all. A
    respelling is not a configured value: admitting one would be this stage
    deciding what the contract meant, and the contract admits what it lists.

    Three inputs, three outcomes, and the distinction that must survive:
      - exactly a listed value                  → ADMITTED, value present
      - exactly OUTSIDE_ADMITTED_TOKEN          → OUTSIDE_ADMITTED, absent
      - anything else: no field, a non-string,
        an empty one, a respelling, an invented
        category, a failure, no vocabulary to
        classify against                        → CANNOT_ANSWER, absent

    Only the sanctioned token is a deliberate "outside the vocabulary". An
    unusable answer is not a judgment that the signal sits outside it, and
    recording one as the other would launder a failure into a decision.
    """
    if failed or not admits:
        return None, CANNOT_ANSWER
    if not isinstance(stated, str):
        return None, CANNOT_ANSWER
    if stated == OUTSIDE_ADMITTED_TOKEN:
        return None, OUTSIDE_ADMITTED
    if stated not in admits:
        # The answer carried no usable classification. Nothing was deliberately
        # placed outside the vocabulary; nothing was decided at all.
        return None, CANNOT_ANSWER
    return stated, ADMITTED


def enrich_signal(signal: dict) -> dict:
    try:
        domains, risks = admitted_vocabularies()
    except ClientConfigurationError as exc:
        # No vocabulary to classify against is a failure to classify, not a
        # classification: both outcomes become CANNOT_ANSWER below and neither
        # value field is written. The rest of the enrichment still runs.
        log.error("Editorial classification vocabulary unavailable: %s", exc)
        domains, risks = (), ()

    prompt = load_prompt("research/enrich", {
        "headline":    signal.get("HEADLINE", ""),
        "source_name": signal.get("SOURCE_NAME", ""),
        "source_url":  signal.get("SOURCE_URL", ""),
        "source_date": signal.get("SOURCE_DATE", ""),
        "raw_summary": signal.get("raw_summary", ""),
        "signal_type": signal.get("SIGNAL_TYPE", ""),
        "region":      signal.get("REGION", ""),
        "industry":    signal.get("INDUSTRY", ""),
        "editorial_domains":     ", ".join(domains),
        "editorial_risk_levels": ", ".join(risks),
        "outside_admitted_token": OUTSIDE_ADMITTED_TOKEN,
    })

    # A provider or schema failure is recorded, not inferred from silence: an
    # answer that simply carried no classification and a call that never
    # produced one are indistinguishable once both are an empty dict.
    classification_failed = False
    try:
        raw = chat(prompt["system"], prompt["user"], json_mode=True, model=model_enrich())
        enriched = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(enriched, dict):
            enriched = {}
            classification_failed = True
    except Exception as exc:
        log.error("Enrichment failed for %s: %s", signal.get("SIGNAL_ID"), exc)
        enriched = {}
        classification_failed = True

    merged = dict(signal)
    merged.update(enriched)

    # The two classifications are this stage's to write and never the answer's
    # to state: each value field is removed from whatever was merged and put
    # back only when the model named a value the contract admits. That is the
    # invariant — ADMITTED iff the value field is present — held structurally
    # rather than asserted.
    for value_field, outcome_field, admits in (
        (DOMAIN_FIELD, DOMAIN_OUTCOME_FIELD, domains),
        (RISK_FIELD,   RISK_OUTCOME_FIELD,   risks),
    ):
        value, outcome = classify_against(
            enriched.get(value_field), admits, failed=classification_failed
        )
        merged.pop(value_field, None)
        merged[outcome_field] = outcome
        if value is not None:
            merged[value_field] = value
        else:
            log.info(
                "Signal %s: %s not classified (%s)",
                signal.get("SIGNAL_ID"), value_field, outcome,
            )

    # _NULL_CASE resets to safe defaults when no evidence source exists.
    # SOURCE_FOR_CASE is required by both evidence paths; if absent, neither
    # path can succeed. A signal without source is not article-ready.
    # Note: signals with source but no company remain eligible via research path.
    has_source_now = bool(merged.get("SOURCE_FOR_CASE"))
    if not has_source_now:
        merged.update(_NULL_CASE)
        log.info("Signal %s: no case source — marked not article-ready", signal.get("SIGNAL_ID"))

    # Deterministic readiness fields — set after all evidence is merged.
    article_ready, reason = determine_article_readiness(merged)
    # SOURCE_PREMISE_VERIFIED is true if either evidence path is satisfied:
    # path 1 — company case: REAL_COMPANY_EXAMPLE + SOURCE_FOR_CASE
    # path 2 — research/data: SOURCE_FOR_CASE + confidence >= medium
    # Derived from `premise_path` rather than restated, so the boolean and the
    # path can never disagree about the same record — this expression was a
    # third copy of the readiness check's own logic.
    path = premise_path(merged)
    premise_verified = path is not None
    merged["SOURCE_PREMISE_VERIFIED"] = str(premise_verified).lower()
    # Written only when a path verified it. A signal whose premise does not
    # verify carries no path, and the field is absent rather than empty: the
    # same posture #365 holds for an unclassified domain.
    if path is not None:
        merged[PREMISE_PATH_FIELD] = path
    merged["ARTICLE_READY"]           = str(article_ready).lower()
    # Keep legacy field in sync so sheet consumers remain unaffected.
    merged["RECOMMENDED_FOR_ARTICLE"] = str(article_ready).lower()

    if not article_ready:
        log.info("Signal %s: ARTICLE_READY=false — %s", signal.get("SIGNAL_ID"), reason)

    return merged


def enrich_candidates(candidates: list[dict]) -> list[dict]:
    result = []
    for c in candidates:
        log.info("Enriching: %s", c.get("HEADLINE", "")[:60])
        result.append(enrich_signal(c))
    return result
