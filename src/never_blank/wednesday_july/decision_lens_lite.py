"""
Decision Lens Lite
Spec: docs/LERA_OPERATING_SYSTEM.md, Section 12 (Decision Lens output schema)

TEMPORARY SUBSTITUTE: the real Decision Lens receives an investigation_evidence_report
from Curiosity Engine + Evidence Collector (Q1-Q6, hypothesis testing, source tiers).
That layer does not exist in code yet (no web search / evidence collection is wired in).
This module derives the same output schema directly from already-enriched signal fields
(CORE_FACT, CORE_TENSION, etc.) in a single LLM call, as a stand-in until the real
Investigation Layer is built. Downstream modules (Narrative Spine, Discovery Builder)
consume this module's output shape unchanged, so swapping in the real Decision Lens
later requires no interface change here.
"""
# ─────────────────────────────────────────────────────────────────────────────
# ISOLATED WEDNESDAY EDITORIAL MODULE — restored verbatim from c7d3a23 (#207).
#
# This is a literal port of the July 6 2026 editorial stage that produced the
# Versant / Full Swing specimen. It is deliberately NOT the shared
# src/editorial/ module of the same name: those have since evolved under
# Monday-driven work, and their current behaviour is what this restoration
# exists to bypass.
#
# Do not "reconcile" this file with src/editorial/. Do not refactor it into
# the generic engine. Divergence from the shared module is the point; if the
# shared module changes, this file must NOT follow.
#
# Only current TECHNICAL infrastructure is used — llm_client (provider,
# per-stage model routing, call budget, retry ceilings) and logging. No
# current business rule reaches this module.
# ─────────────────────────────────────────────────────────────────────────────

import json

from src.utils.llm_client import chat, model_enrich
from src.utils.logger import get_logger

log = get_logger("editorial.decision_lens_lite")

_VALID_CONFIDENCE = {"high", "medium", "low"}

_SYSTEM_PROMPT = """You are the Decision Lens for Never Blank.

Never Blank does not explain events. It reconstructs the decision behind the event —
and identifies the strategic_objective: what the organization was actually optimizing
for, not what it announced.

Given the fields below about a business signal, produce:

- core_decision: one sentence — the underlying decision the article should investigate.
  Not the event described in the headline. The decision that would have been made even
  if no one was watching.
- strategic_objective: what the organization was actually trying to preserve or capture.
  Not what they did — what objective function explains every move. Example framing:
  "Protect long-term manufacturing capability over short-term market approval."
- strategic_objective_evidence: 1-3 short strings, each a fact from the provided signal
  fields that supports the strategic_objective reading.
- strategic_objective_confidence: "high", "medium", or "low". Use "low" when the evidence
  supports the decision but leaves the objective ambiguous - when two different objectives
  could produce the same observed moves.
- business_lesson: what this decision reveals about organizational logic generally.
- never_blank_insight: the specific, non-obvious observation - not a restatement of
  business_lesson.

Rules:
- Do not invent facts not implied by the provided fields.
- strategic_objective must not just restate core_decision - it is the logic behind it.
- Return ONLY valid JSON. No text outside the JSON block.

{
  "core_decision": "string",
  "strategic_objective": "string",
  "strategic_objective_evidence": ["string"],
  "strategic_objective_confidence": "high|medium|low",
  "business_lesson": "string",
  "never_blank_insight": "string"
}"""


def _validate(data: dict) -> dict:
    required_strings = [
        "core_decision", "strategic_objective", "business_lesson", "never_blank_insight",
    ]
    for field in required_strings:
        value = data.get(field, "")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Decision Lens Lite: field {field!r} missing or empty in LLM output")

    confidence = data.get("strategic_objective_confidence", "")
    if confidence not in _VALID_CONFIDENCE:
        raise ValueError(
            f"Decision Lens Lite: invalid strategic_objective_confidence={confidence!r}, "
            f"must be one of {sorted(_VALID_CONFIDENCE)}"
        )

    evidence = data.get("strategic_objective_evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("Decision Lens Lite: strategic_objective_evidence must be a list")

    return {
        "core_decision": data["core_decision"].strip(),
        "strategic_objective": data["strategic_objective"].strip(),
        "strategic_objective_evidence": [str(e).strip() for e in evidence],
        "strategic_objective_confidence": confidence,
        "business_lesson": data["business_lesson"].strip(),
        "never_blank_insight": data["never_blank_insight"].strip(),
    }


def generate_decision_lens(signal: dict) -> dict:
    """
    Produce a Decision Lens output dict from enriched signal fields.

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
COUNTER_EXAMPLE: {signal.get('COUNTER_EXAMPLE', '')}
WHY_THIS_CASE_IS_INTERESTING: {signal.get('WHY_THIS_CASE_IS_INTERESTING', '')}

Produce the Decision Lens JSON for this signal."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_enrich())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Decision Lens Lite returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    result = _validate(data)
    log.info(
        "Decision Lens Lite: core_decision=%r confidence=%s",
        result["core_decision"][:80], result["strategic_objective_confidence"],
    )
    return result
