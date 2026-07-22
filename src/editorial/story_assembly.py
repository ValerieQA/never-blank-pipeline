"""
Story Assembly — Editorial Engine V2 Modules 4-5
Spec: docs/EDITORIAL_ENGINE_V2.md, "Story Builder", "Evidence Reveal", "Business Translation"

These three modules are merged into one LLM call: they are sequential text-production
steps operating on the same discovery output with no independent-regeneration value
between them. Python still enforces the constraints the spec assigns to each individually.

For the new editorial identity (small business visibility patterns):
- surviving_explanation becomes Step 5 (Explanation — the mechanism named clearly)
- reframe is new: Step 6 (challenging the obvious interpretation)
- business_translation becomes Step 7 (Business and sales meaning — commercial reality)
- remaining_uncertainty is preserved as an open question or null
"""

import json

from src.utils.llm_client import chat, model_article
from src.utils.logger import get_logger

log = get_logger("editorial.story_assembly")

_SYSTEM_PROMPT = """You are the Story Assembly module for Never Blank (Story Builder +
Evidence Reveal + Business Translation combined).

Never Blank investigates patterns that make small businesses visible, recognizable,
remembered, and commercially present. The reader is a small business owner who must
recognize their own situation — not study someone else's company.

Given the Discovery Builder output and the Narrative Spine, produce four fields:

1. surviving_explanation - the MECHANISM stated clearly after the reader has already
   arrived at it through the discovery sequence. This is Step 5 (Explanation):
   - Name WHY this visibility pattern happens specifically
   - Not "consistency matters" — name the actual mechanism:
     "non-urgent visibility work is repeatedly displaced by urgent operational work,"
     "repeated exposure creates recognition before trust, not after,"
     "silence breaks accumulated familiarity faster than presence builds it"
   - 2-4 sentences. First-person investigative voice, not analytical summary.
   - Must be traceable to the discovery sequence provided — do not add new facts.

2. reframe - Step 6: a single specific intellectual move that challenges the obvious
   interpretation of the pattern.
   - Not a discipline problem — a system-design problem.
   - Not a lack-of-ideas problem — a continuity problem.
   - Must be specific to THIS pattern, not a generic reframe about content marketing.
   - 1-3 sentences. Does not repeat surviving_explanation.
   - If removed, the article loses something important. If it could appear in any
     article about content, it is too generic — rewrite.

3. remaining_uncertainty - one sentence naming a genuine open question this
   investigation could not resolve, framed as an open question rather than a caveat.
   Return null (not a placeholder string) if there is nothing material left open.
   Do not invent fake uncertainty just to fill the field.

4. business_translation - Step 7 (Business and sales meaning): what this visibility
   pattern means for the business owner's commercial reality.
   - Connect to: trust, recognition, future buying decisions, referrals, pipeline,
     sales conversations, future revenue.
   - NOT a product pitch. NOT generic advice. NOT "companies should..."
   - Must clearly rhyme with the narrative_spine — reuse its central image or claim.
   - 1-2 sentences. By this point the reader already understands the lesson;
     business_translation only makes the commercial consequence explicit.
   - HARD REQUIREMENT: read it with the pattern removed. If it would paste unchanged
     under a different article, it is too generic. Rewrite until it depends on this
     specific pattern and narrative_spine.
   - Banned pattern: "If your goal is X, then Y" / "Businesses facing Z should consider W"

Rules:
- Every claim in surviving_explanation must be traceable to the discovery sequence
  or signal facts provided — do not add new facts.
- reframe must be specific to this pattern — generic reframes fail.
- business_translation must not be generic advice; it must depend on the specific
  narrative_spine above it.

Return ONLY valid JSON:
{
  "surviving_explanation": "string",
  "reframe": "string",
  "remaining_uncertainty": "string or null",
  "business_translation": "string"
}"""


def _validate(data: dict) -> dict:
    for field in ("surviving_explanation", "reframe", "business_translation"):
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
        "reframe": data["reframe"].strip(),
        "remaining_uncertainty": uncertainty,
        "business_translation": data["business_translation"].strip(),
    }


def assemble_story(discovery: dict, spine: dict, decision_lens: dict, signal: dict) -> dict:
    """
    Produce surviving_explanation, reframe, remaining_uncertainty, and business_translation.

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
