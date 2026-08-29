"""
Hook Engine — Editorial Engine V2 Module 1
Spec: docs/EDITORIAL_ENGINE_V2.md, Module 1

Generates 5-7 candidate hooks across distinct types, then selects the one that
names something a reader would not have derived from the headline alone.
A single hook generated first is almost never the strongest one.
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

from src.utils.llm_client import chat, model_article
from src.utils.logger import get_logger

log = get_logger("editorial.hook_engine")

_MIN_CANDIDATES = 5

_HOOK_TYPES = {
    "contradiction", "invisible_signal", "surprising_question",
    "wrong_consensus", "hidden_decision", "false_narrative",
}

_SYSTEM_PROMPT = """You are the Hook Engine for Never Blank.

Question: why would a person stop scrolling for this? Not "how do I start elegantly"
but "what is the thing in this investigation a reader would not expect?"

Generate 5-7 candidate hooks, spanning as many of these types as make sense for this
signal:

- contradiction: states something that seems wrong but is true
- invisible_signal: names something everyone saw but nobody read correctly
- surprising_question: opens with the question the investigation answered
- wrong_consensus: names the incorrect interpretation the market held
- hidden_decision: reveals the visible event was not the actual decision
- false_narrative: dismantles the frame before establishing the real one

Selection rule: choose the hook that names something the reader would not have
derived from the headline alone. If the hook could be written without reading the
investigation, it is wrong. The hook must not summarize - it must create a gap the
reader does not yet know how to resolve. It must not reveal the narrative_spine
early - the reader earns the spine at the end of the article.

Return ONLY valid JSON:
{
  "hook_candidates": [
    {"type": "contradiction|invisible_signal|surprising_question|wrong_consensus|hidden_decision|false_narrative", "text": "string"}
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
    Produce hook candidates and a selection.

    Raises ValueError if fewer than 5 candidates are returned, any candidate has an
    invalid type, or selected_hook does not exactly match a candidate's text.
    """
    user = f"""HEADLINE: {signal.get('HEADLINE', '')}
narrative_spine: {spine.get('narrative_spine', '')}
never_blank_insight: {decision_lens.get('never_blank_insight', '')}
strategic_objective: {decision_lens.get('strategic_objective', '')}
CORE_FACT: {signal.get('CORE_FACT', '')}
CORE_TENSION: {signal.get('CORE_TENSION', '')}

Produce the Hook Engine JSON."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_article())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Hook Engine returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    result = _validate(data)
    log.info("Hook Engine: %d candidates, selected=%r", len(result["hook_candidates"]), result["selected_hook"][:80])
    return result
