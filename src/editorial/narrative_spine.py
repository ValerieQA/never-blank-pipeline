"""
Narrative Spine
Spec: docs/NARRATIVE_SPINE.md

The Spine is one sentence: the central thought the whole article is built to earn.
It is established once, from Decision Lens output, before any Editorial Engine
module runs. Every downstream module receives it as a fixed input.
"""

import json

from src.utils.llm_client import chat, model_enrich
from src.utils.logger import get_logger

log = get_logger("editorial.narrative_spine")

_VALID_FEELINGS = {"reframe", "recognition", "unease", "clarity", "anticipation"}

_SYSTEM_PROMPT = """You are the Narrative Spine module for Never Blank.

The Narrative Spine is one sentence: the answer to "what is this article actually
about?" Not the event. Not the company. The decision. The pattern. The idea.
The company is evidence. The Spine is what the evidence proves.

Answer exactly three questions:

1. core_decision - restate or refine the underlying decision (from strategic_objective
   and core_decision provided below) as one sentence.

2. narrative_spine - the single sentence the entire article is built to earn. It must:
   - work without the company name (if removing the company name makes it meaningless,
     it is describing an event, not a decision pattern)
   - be specific enough to be wrong for some situations
   - sound like something a reader would want to remember
   It must NOT be generic ("companies should think long-term"), summarize what happened,
   or repeat a headline-style hook.

3. target_feeling - exactly one of: reframe, recognition, unease, clarity, anticipation.

4. company_as_evidence_of - one sentence: what the company proves, not what it did.

strategic_objective is the primary input to narrative_spine - sometimes the Spine
restates it directly, more often it reframes it into a sentence that survives without
the company name.

Return ONLY valid JSON:
{
  "core_decision": "string",
  "narrative_spine": "string",
  "target_feeling": "reframe|recognition|unease|clarity|anticipation",
  "company_as_evidence_of": "string"
}"""


def _validate(data: dict) -> dict:
    for field in ("core_decision", "narrative_spine", "company_as_evidence_of"):
        value = data.get(field, "")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Narrative Spine: field {field!r} missing or empty in LLM output")

    feeling = data.get("target_feeling", "")
    if feeling not in _VALID_FEELINGS:
        raise ValueError(
            f"Narrative Spine: invalid target_feeling={feeling!r}, "
            f"must be one of {sorted(_VALID_FEELINGS)}"
        )

    return {
        "core_decision": data["core_decision"].strip(),
        "narrative_spine": data["narrative_spine"].strip(),
        "target_feeling": feeling,
        "company_as_evidence_of": data["company_as_evidence_of"].strip(),
    }


def build_narrative_spine(decision_lens: dict, signal: dict) -> dict:
    """
    Produce the Narrative Spine dict from Decision Lens output.

    Raises ValueError if the LLM output does not satisfy the schema, including an
    invalid target_feeling value.
    """
    user = f"""HEADLINE: {signal.get('HEADLINE', '')}
COMPANY: {signal.get('REAL_COMPANY_EXAMPLE', 'none')}

core_decision (from Decision Lens): {decision_lens.get('core_decision', '')}
strategic_objective (from Decision Lens): {decision_lens.get('strategic_objective', '')}
strategic_objective_confidence: {decision_lens.get('strategic_objective_confidence', '')}
business_lesson: {decision_lens.get('business_lesson', '')}
never_blank_insight: {decision_lens.get('never_blank_insight', '')}

Produce the Narrative Spine JSON."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_enrich())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Narrative Spine returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    result = _validate(data)
    log.info("Narrative Spine: %r (feeling=%s)", result["narrative_spine"][:80], result["target_feeling"])
    return result
