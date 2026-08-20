"""
Narrative Spine
Spec: docs/NARRATIVE_SPINE.md

The Spine is one sentence: the central thought the whole article is built to earn.
It is established once, from Decision Lens output, before any Editorial Engine
module runs. Every downstream module receives it as a fixed input.

For Never Blank, the Spine is always about a pattern in small business visibility,
presence, customer memory, or recognition — not about a single company's strategy.
"""

import json

from src.utils.llm_client import chat, model_enrich
from src.utils.logger import get_logger

log = get_logger("editorial.narrative_spine")

_VALID_FEELINGS = {"recognition", "unease", "reframe", "clarity", "anticipation"}

_SYSTEM_PROMPT = """You are the Narrative Spine module for Never Blank.

Never Blank is a research-driven observer of the patterns that make small businesses
visible, recognizable, remembered, and commercially present. The reader is a small
business owner who must recognize their own situation — not study someone else's company.

The Narrative Spine is one sentence: the answer to "what is this article actually about?"
Not the signal. Not the statistic. Not the platform.
The pattern. The mechanism. The invisible thing the research surfaced.

Answer exactly four questions:

1. core_pattern - restate or refine the underlying visibility/presence pattern as one sentence.
   This must describe what is happening in small businesses, not what a specific company did.

2. narrative_spine - the single sentence the entire article is built to earn. It must:
   - work for any small business owner recognizing their own situation
   - be specific enough to be wrong for some situations
   - sound like something a reader would want to remember
   - NOT be generic ("businesses should be more consistent")
   - NOT summarize a signal ("X reduced posting by 40%")
   - NOT repeat a headline-style hook

   Quality examples (register only — do not copy):
   "If presence depends only on the owner's free time, silence eventually becomes
   part of the strategy — even when nobody chose it."
   "Customers rarely decide to forget a business. They simply stop encountering it."
   "A business can be successful and still be gradually forgotten."

3. target_feeling - exactly one of: recognition, unease, reframe, clarity, anticipation.
   - recognition: reader has been in exactly this situation
   - unease: reader suspects they are in this pattern right now
   - reframe: reader now sees a familiar situation differently
   - clarity: something previously vague now has a name
   - anticipation: reader wants to understand what comes next

4. pattern_as_evidence_of - one sentence: what this visibility pattern proves about
   small business presence. Not what a company did — what the pattern reveals.

Return ONLY valid JSON:
{
  "core_pattern": "string",
  "narrative_spine": "string",
  "target_feeling": "recognition|unease|reframe|clarity|anticipation",
  "pattern_as_evidence_of": "string"
}"""


def _validate(data: dict) -> dict:
    for field in ("core_pattern", "narrative_spine", "pattern_as_evidence_of"):
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
        "core_pattern": data["core_pattern"].strip(),
        "narrative_spine": data["narrative_spine"].strip(),
        "target_feeling": feeling,
        "pattern_as_evidence_of": data["pattern_as_evidence_of"].strip(),
        # Backward-compat alias used by some downstream modules
        "core_decision": data.get("core_pattern", "").strip(),
        "company_as_evidence_of": data.get("pattern_as_evidence_of", "").strip(),
    }


def build_narrative_spine(
    decision_lens: dict, signal: dict, claim_boundary: str | None = None
) -> dict:
    """
    Produce the Narrative Spine dict from Decision Lens output.

    The spine is about a small business visibility/presence pattern, not a company strategy.

    Raises ValueError if the LLM output does not satisfy the schema, including an
    invalid target_feeling value.
    """
    strategy_section = ""
    if signal.get("STRATEGY_PRIMARY_MESSAGE"):
        strategy_section = f"""
Active campaign context — the Spine must align to this framing:
strategy_primary_message: {signal.get("STRATEGY_PRIMARY_MESSAGE", "")}
strategy_desired_reader_realization: {signal.get("STRATEGY_DESIRED_REALIZATION", "")}
strategy_compound_presence_role: {signal.get("STRATEGY_COMPOUND_ROLE", "")}
"""

    user = f"""HEADLINE: {signal.get('HEADLINE', '')}

visibility_pattern: {signal.get('visibility_pattern', '')}
founder_scenario: {signal.get('founder_scenario', '')}
mechanism: {signal.get('mechanism', '')}
business_consequence: {signal.get('business_consequence', '')}
owner_system_objective (from Decision Lens): {decision_lens.get('owner_system_objective', '')}
delivery_vs_presence_conflict (from Decision Lens): {decision_lens.get('delivery_vs_presence_conflict', '')}
customer_memory_consequence (from Decision Lens): {decision_lens.get('customer_memory_consequence', '')}
structural_cause (from Decision Lens): {decision_lens.get('structural_cause', '')}
never_blank_insight: {decision_lens.get('never_blank_insight', '')}{strategy_section}
Produce the Narrative Spine JSON for this small business visibility pattern."""

    if claim_boundary:
        user = f"{user}\n{claim_boundary}"

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_enrich())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Narrative Spine returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    result = _validate(data)
    log.info("Narrative Spine: %r (feeling=%s)", result["narrative_spine"][:80], result["target_feeling"])
    return result
