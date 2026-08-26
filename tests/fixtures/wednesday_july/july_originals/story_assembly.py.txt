"""
Story Assembly — Editorial Engine V2 Modules 4-5
Spec: docs/EDITORIAL_ENGINE_V2.md, "Story Builder", "Evidence Reveal", "Business Translation"

These three modules are merged into one LLM call: they are sequential text-production
steps operating on the same discovery output with no independent-regeneration value
between them (unlike Hook Engine or Discovery Builder, which benefit from generating
candidates and selecting). Python still enforces the constraints the spec assigns to
each of them individually (see _validate).
"""

import json

from src.utils.llm_client import chat, model_article
from src.utils.logger import get_logger

log = get_logger("editorial.story_assembly")

_SYSTEM_PROMPT = """You are the Story Assembly module for Never Blank (Story Builder +
Evidence Reveal + Business Translation combined).

Given the Discovery Builder output (first_wrong_explanation, puzzle,
investigation_sequence, aha_setup) and the Narrative Spine, produce:

1. surviving_explanation - the explanation the reader now holds, stated directly.
   This arrives AFTER the aha_setup - the reader already has the answer; this
   confirms it. Do not re-explain the discovery sequence - state the conclusion in
   1-3 sentences, evidence-textured (reference what was shown, not "based on the
   above").

2. remaining_uncertainty - one sentence naming a genuine open question this
   investigation could not resolve, framed as an open question rather than a
   caveat that undercuts the piece. Return null (not a placeholder string) if there
   is nothing material left open given the provided facts - do not invent a fake
   uncertainty just to fill the field.

3. business_translation - what this decision means for a company with nothing to
   do with this one, facing the same TYPE of structural choice. Must be derived
   from strategic_objective/business_lesson provided below, not invented. It must
   be specific enough to be actionable, not generic enough to apply to everything -
   "companies should think long-term" is a platitude, not a lesson. It should fail
   for at least some companies; if it applies to every situation, it applies to
   none.

Rules:
- Every claim in surviving_explanation must be traceable to the discovery sequence
  or signal facts provided - do not add new facts.
- business_translation must not be generic advice.

Return ONLY valid JSON:
{
  "surviving_explanation": "string",
  "remaining_uncertainty": "string or null",
  "business_translation": "string"
}"""


def _validate(data: dict) -> dict:
    for field in ("surviving_explanation", "business_translation"):
        value = data.get(field, "")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Story Assembly: field {field!r} missing or empty in LLM output")

    uncertainty = data.get("remaining_uncertainty", None)
    if uncertainty is not None:
        if not isinstance(uncertainty, str):
            raise ValueError("Story Assembly: remaining_uncertainty must be a string or null")
        uncertainty = uncertainty.strip() or None

    return {
        "surviving_explanation": data["surviving_explanation"].strip(),
        "remaining_uncertainty": uncertainty,
        "business_translation": data["business_translation"].strip(),
    }


def assemble_story(discovery: dict, spine: dict, decision_lens: dict, signal: dict) -> dict:
    """
    Produce surviving_explanation, remaining_uncertainty, and business_translation.

    Raises ValueError if required fields are missing/empty, or remaining_uncertainty
    is present but not a string.
    """
    user = f"""narrative_spine: {spine.get('narrative_spine', '')}
first_wrong_explanation: {discovery.get('first_wrong_explanation', '')}
puzzle: {discovery.get('puzzle', '')}
investigation_sequence: {json.dumps(discovery.get('investigation_sequence', []))}
aha_setup: {discovery.get('aha_setup', '')}
strategic_objective: {decision_lens.get('strategic_objective', '')}
strategic_objective_confidence: {decision_lens.get('strategic_objective_confidence', '')}
business_lesson: {decision_lens.get('business_lesson', '')}
OUTCOME_IF_KNOWN: {signal.get('OUTCOME_IF_KNOWN', '')}

Produce the Story Assembly JSON."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_article())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Story Assembly returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    result = _validate(data)
    log.info("Story Assembly: surviving_explanation=%r", result["surviving_explanation"][:80])
    return result
