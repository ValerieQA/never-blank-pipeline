"""
Pattern Extractor — mandatory gate between research enrichment and editorial pipeline.

This module transforms a signal into an owner-centered business pattern, or rejects
the signal entirely. The pattern is whichever one the material most strongly supports;
the field name ``visibility_pattern`` is the established downstream contract and is
kept for that reason, not because the pattern must be about visibility. It runs before any editorial stage. If the signal
cannot credibly be reframed as a pattern a small business owner recognizes in their
own business, the signal is rejected and pipeline skips publishing.

Output feeds directly into Decision Lens (and all downstream stages) via the
`enriched` dict in pipeline.py.
"""

import json

from src.utils.llm_client import chat, model_enrich
from src.utils.logger import get_logger

log = get_logger("editorial.pattern_extractor")


class SignalRejectedError(Exception):
    """Raised when the Pattern Extractor determines the signal cannot produce
    an owner-centered article without forcing a connection."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Signal rejected: {reason}")


_SYSTEM_PROMPT = """You are the Pattern Extractor for Never Blank.

Never Blank produces articles for small business owners — not about corporations.
Your job is to extract the structural business pattern the owner recognizes in their
own business, or to reject the signal if no credible owner-facing pattern exists.

THE CENTRAL QUESTION IS:
"What happened here that a small business owner would recognize in their own business?"
NOT "What did the company do?" — that question is forbidden here.

The pattern is whichever one the material most strongly supports — pricing, capacity, supply, regulation, distribution, operations, customer behaviour, a founder decision, communication, presence, or another supported mechanism. Do not force the material into a presence or visibility frame it does not carry.

Produce exactly these fields:

1. visibility_pattern
   (Established field name; the content is the business pattern this material supports.)
   What happens in small businesses — the structural pattern the evidence actually
   shows, whichever mechanism that is. Must describe what happens in small businesses,
   not what happened to a specific company. The example may have triggered the signal,
   but it is not the pattern.

2. founder_scenario
   A concrete recognizable scene where the owner sees themselves — the moment they
   recognize their situation. ONE sentence. No company names, no brand names.
   The owner must be able to read this without knowing anything about the corporate
   example. If you cannot write this scene naturally and specifically, the signal
   must be rejected.

3. mechanism
   WHY this pattern happens structurally. Not what a company decided. Not what the
   owner should do differently. The underlying structural reason this pattern repeats.
   Examples of valid mechanism framing, deliberately spanning different mechanisms:
   — "price rations the constraint that is actually binding, not the one being measured"
   — "capacity added ahead of demand converts fixed cost into fragility"
   — "non-urgent visibility work is displaced by urgent delivery work"
   — "customer memory degrades in proportion to exposure frequency, not business performance"
   Do NOT describe what a company did.

4. business_consequence
   What happens to customer memory, trust, referral pipeline, or future revenue when
   this pattern plays out. One to two sentences. Specific to this mechanism.

5. company_as_evidence_of
   ONE sentence — no more. The corporate example proves this pattern exists at scale.
   Frame as: "[Company] demonstrates that [pattern claim]." The company is evidence,
   not the subject. If you need more than one sentence, the pattern has not been extracted.

6. evidence_limit
   What this corporate example cannot prove about the small business owner's situation.
   One sentence. Be honest about where the scale difference matters.

7. article_protagonist
   Always "owner". This is a hard assertion, not a choice. Never "company", never
   "brand", never the corporate example's name.

8. signal_fit
   "use" if a credible owner-recognition scenario exists without forcing a connection.
   "reject" if any of these conditions are true:
   — No credible founder-recognition scenario can be written naturally
   — The signal is only relevant to large-company strategy with no small-business mechanism
   — The corporate example cannot be removed without the pattern collapsing
   — The signal is generic AI/tech news with no owner-facing mechanism
   — The founder_scenario requires the reader to know the corporate example to make sense

9. rejection_reason
   Required (non-null string) when signal_fit = "reject".
   Null when signal_fit = "use".

Rules:
- article_protagonist must always be "owner" — no exceptions.
- founder_scenario must be writable WITHOUT any company name. If it is not, signal_fit = "reject".
- company_as_evidence_of must be exactly one sentence.
- mechanism must explain structural cause, not company behavior.
- When signal_fit = "reject", rejection_reason must clearly explain why no credible owner scenario exists.
- Return ONLY valid JSON. No text outside the JSON block.

{
  "visibility_pattern": "string",
  "founder_scenario": "string",
  "mechanism": "string",
  "business_consequence": "string",
  "company_as_evidence_of": "string",
  "evidence_limit": "string",
  "article_protagonist": "owner",
  "signal_fit": "use|reject",
  "rejection_reason": "string or null"
}"""

_REQUIRED_FIELDS = [
    "visibility_pattern",
    "founder_scenario",
    "mechanism",
    "business_consequence",
    "company_as_evidence_of",
    "evidence_limit",
    "article_protagonist",
    "signal_fit",
    "rejection_reason",
]


def _validate(data: dict) -> dict:
    for field in _REQUIRED_FIELDS:
        if field not in data:
            raise ValueError(f"Pattern Extractor: required field {field!r} missing from LLM output")

    for field in ["visibility_pattern", "founder_scenario", "mechanism",
                  "business_consequence", "company_as_evidence_of", "evidence_limit"]:
        value = data.get(field, "")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Pattern Extractor: field {field!r} is empty or not a string")

    if data.get("article_protagonist") != "owner":
        raise ValueError(
            f"Pattern Extractor: article_protagonist must be 'owner', "
            f"got {data.get('article_protagonist')!r}"
        )

    signal_fit = data.get("signal_fit", "")
    if signal_fit not in ("use", "reject"):
        raise ValueError(
            f"Pattern Extractor: signal_fit must be 'use' or 'reject', got {signal_fit!r}"
        )

    rejection_reason = data.get("rejection_reason")
    if signal_fit == "reject" and (rejection_reason is None or not str(rejection_reason).strip()):
        raise ValueError(
            "Pattern Extractor: rejection_reason must be a non-null string when signal_fit = 'reject'"
        )
    if signal_fit == "use" and rejection_reason is not None:
        # Normalize: if LLM returned a string for use, coerce to null
        data = {**data, "rejection_reason": None}

    return {
        "visibility_pattern": data["visibility_pattern"].strip(),
        "founder_scenario": data["founder_scenario"].strip(),
        "mechanism": data["mechanism"].strip(),
        "business_consequence": data["business_consequence"].strip(),
        "company_as_evidence_of": data["company_as_evidence_of"].strip(),
        "evidence_limit": data["evidence_limit"].strip(),
        "article_protagonist": "owner",
        "signal_fit": signal_fit,
        "rejection_reason": str(rejection_reason).strip() if rejection_reason else None,
    }


def extract_pattern(signal: dict) -> dict:
    """
    Transform an enriched signal into an owner-centered business pattern dict.

    Returns the pattern dict when signal_fit = "use".
    Raises SignalRejectedError when signal_fit = "reject".
    Raises ValueError if the LLM output does not satisfy the schema.
    """
    user = f"""HEADLINE: {signal.get('HEADLINE', '')}
CORE_FACT: {signal.get('CORE_FACT', '')}
CORE_TENSION: {signal.get('CORE_TENSION', '')}
REAL_COMPANY_EXAMPLE: {signal.get('REAL_COMPANY_EXAMPLE', 'none')}
PROBLEM_FACED: {signal.get('PROBLEM_FACED', '')}
RESPONSE_TAKEN: {signal.get('RESPONSE_TAKEN', '')}
OUTCOME_IF_KNOWN: {signal.get('OUTCOME_IF_KNOWN', '')}
BUSINESS_LESSON: {signal.get('BUSINESS_LESSON', '')}
WHY_THIS_CASE_IS_INTERESTING: {signal.get('WHY_THIS_CASE_IS_INTERESTING', '')}
NEVER_BLANK_ANGLE (editorial hypothesis; validate it against the facts): {signal.get('NEVER_BLANK_ANGLE', '')}
POTENTIAL_HOOK (candidate, not a required opening): {signal.get('POTENTIAL_HOOK', '')}
TARGET_AUDIENCE: {signal.get('TARGET_AUDIENCE', 'founder')}

Extract the owner-centered business pattern from this signal."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_enrich())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Pattern Extractor returned invalid JSON: {exc}\nRaw: {raw[:300]}"
        ) from exc

    result = _validate(data)

    if result["signal_fit"] == "reject":
        log.warning(
            "Pattern Extractor: signal REJECTED — %s", result["rejection_reason"]
        )
        raise SignalRejectedError(result["rejection_reason"])

    log.info(
        "Pattern Extractor: pattern extracted — %r",
        result["visibility_pattern"][:80],
    )
    return result
