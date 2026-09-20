"""
Hook Engine — Editorial Engine V2 Module 1
Spec: docs/EDITORIAL_ENGINE_V2.md, Module 1

Generates 5-7 candidate hooks across distinct types for small business
patterns, then selects the one that makes a business owner stop and recognize
their own situation.

A single hook generated first is almost never the strongest one.
"""

import json

from src.editorial.editorial_plan import plan_block
from src.utils.llm_client import chat, model_article
from src.utils.logger import get_logger

log = get_logger("editorial.hook_engine")

_MIN_CANDIDATES = 5

_HOOK_TYPES = {
    "hidden_cost",
    "invisible_pattern",
    "false_comfort",
    "timing_contradiction",
    "recognition_gap",
    "accumulated_effect",
}

_SYSTEM_PROMPT = """You are the Hook Engine for Never Blank.

Never Blank is a research-driven observer of the patterns that shape how small
businesses actually work. The reader is a small-business owner who must recognize
their own situation in the first three lines.

Question: what observation would make a business owner stop scrolling and think
"this is about my business"? Not "how do I start elegantly" — but "what is the
specific tension in this evidence that this business owner has not yet named?"

Generate 5-7 candidate hooks, spanning as many of these types as make sense:

- hidden_cost: names the cost created by the supported mechanism
  Example: "The cheapest order can be the one that consumes the scarce hour."
- invisible_pattern: names something the reader does regularly without realizing its effect
  Example: "A full queue can conceal the constraint that price is rationing."
- false_comfort: states a belief the reader holds that the evidence contradicts
  Example: "More demand is not automatically useful when capacity cannot move."
- timing_contradiction: exposes that the pattern happens at exactly the wrong moment
  Example: "The compliance rule changes before the next contract is awarded."
- recognition_gap: names the gap between what the business does and what is visible outside
  Example: "Customers see the price; they do not see the bottleneck behind it."
- accumulated_effect: reveals that small repeated absences compound into a large problem
  Example: "Small scheduling compromises can become a permanent capacity ceiling."

Presence, visibility, recognition, memory, and consistency are possible subjects only
when the evidence and configured editorial role support them. Do not redirect another
mechanism into those concepts to fit the examples or the Never Blank name.

Selection rule: choose the hook that:
1. A business owner stops at because they recognize their own situation
2. Cannot be written without understanding this specific pattern (not a generic opener)
3. Creates a gap — something the reader feels is true but cannot yet explain
4. Does NOT summarize the article
5. Does NOT reveal the narrative_spine early — the reader earns the spine at the end

FORBIDDEN hook patterns:
- "In today's..." / "It's not about..." / "Many founders..."
- Opening with a question
- Stating the article's conclusion in the first line
- "Here's what research shows about..."

Return ONLY valid JSON:
{
  "hook_candidates": [
    {"type": "hidden_cost|invisible_pattern|false_comfort|timing_contradiction|recognition_gap|accumulated_effect", "text": "string"}
  ],
  "selected_hook": "string - must be the exact text of one of the hook_candidates"
}"""


def _validate(data: dict) -> dict:
    candidates = data.get("hook_candidates", [])
    if not isinstance(candidates, list) or len(candidates) < _MIN_CANDIDATES:
        raise ValueError(
            f"Hook Engine: expected >= {_MIN_CANDIDATES} hook_candidates, "
            f"got {len(candidates) if isinstance(candidates, list) else 'non-list'}"
        )

    clean_candidates = []
    for i, c in enumerate(candidates):
        htype = c.get("type", "")
        text = c.get("text", "")
        if htype not in _HOOK_TYPES:
            raise ValueError(f"Hook Engine: candidate {i} has invalid type={htype!r}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Hook Engine: candidate {i} has empty text")
        clean_candidates.append({"type": htype, "text": text.strip()})

    selected = data.get("selected_hook", "")
    if not isinstance(selected, str) or not selected.strip():
        raise ValueError("Hook Engine: selected_hook missing or empty")
    selected = selected.strip()

    if selected not in {c["text"] for c in clean_candidates}:
        raise ValueError(
            "Hook Engine: selected_hook does not match the exact text of any hook_candidate"
        )

    return {"hook_candidates": clean_candidates, "selected_hook": selected}


def generate_hook(spine: dict, decision_lens: dict, signal: dict) -> dict:
    """
    Produce hook candidates and a selection for a small business pattern.

    Raises ValueError if fewer than 5 candidates are returned, any candidate has an
    invalid type, or selected_hook does not exactly match a candidate's text.
    """
    user = f"""HEADLINE: {signal.get('HEADLINE', '')}
narrative_spine: {spine.get('narrative_spine', '')}
founder_scenario: {signal.get('founder_scenario', '')}
business_pattern (legacy field visibility_pattern): {signal.get('visibility_pattern', '')}
mechanism: {signal.get('mechanism', '')}
never_blank_insight: {decision_lens.get('never_blank_insight', '')}
owner_system_objective: {decision_lens.get('owner_system_objective', '')}
CORE_FACT: {signal.get('CORE_FACT', '')}
CORE_TENSION: {signal.get('CORE_TENSION', '')}

HARD REQUIREMENT: Hooks must create recognition for the owner, not summarize a corporate
event. A hook that requires knowing the company name to make sense has failed.{plan_block(signal)}

Produce the Hook Engine JSON."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_article())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Hook Engine returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    result = _validate(data)
    log.info("Hook Engine: %d candidates, selected=%r", len(result["hook_candidates"]), result["selected_hook"][:80])
    return result
