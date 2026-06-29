"""
Hypothesis Generator — Phase 1 MVP
Spec: docs/EVIDENCE_COLLECTOR_MVP.md, Sections 3, 3b

Generates a prioritized hypothesis space for each investigation question.
Priority (test_priority) is computed deterministically from two explicit
criteria — it is never assigned by the LLM.
"""

import json
from dataclasses import dataclass
from typing import Literal

from src.utils.llm_client import chat, model_enrich
from src.utils.logger import get_logger

log = get_logger("hypothesis_generator")

ImpactLevel = Literal[
    "destroys_main_narrative",
    "weakens_main_narrative",
    "orthogonal",
    "supports_main_narrative",
]
DistanceLevel = Literal["low", "medium", "high"]
OriginType = Literal["initial", "exhaustion_check"]

_VALID_IMPACTS: set[str] = {
    "destroys_main_narrative",
    "weakens_main_narrative",
    "orthogonal",
    "supports_main_narrative",
}
_VALID_DISTANCES: set[str] = {"low", "medium", "high"}
_DISTANCE_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass
class Hypothesis:
    hypothesis_id: str
    hypothesis: str
    origin_type: OriginType
    if_true_impact: ImpactLevel
    distance_from_signal: DistanceLevel
    test_priority: int
    priority_reason: str

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "hypothesis": self.hypothesis,
            "origin_type": self.origin_type,
            "if_true_impact": self.if_true_impact,
            "distance_from_signal": self.distance_from_signal,
            "test_priority": self.test_priority,
            "priority_reason": self.priority_reason,
        }


def _compute_priority(impact: str, distance: str) -> int:
    """
    Deterministic priority from EVIDENCE_COLLECTOR_MVP.md Section 3b.

    1  destroys_main_narrative           (test first — if true, conclusion is invalid)
    2  weakens_main_narrative            (test second — qualifies conclusion)
    3  orthogonal + distance low         (cheap to check, grounded in signal)
    4  orthogonal + distance medium/high (speculative, lower urgency)
    5  supports_main_narrative           (test last — only confirms what we hope is true)
    """
    if impact == "destroys_main_narrative":
        return 1
    if impact == "weakens_main_narrative":
        return 2
    if impact == "orthogonal":
        return 3 if distance == "low" else 4
    return 5  # supports_main_narrative


_SYSTEM_PROMPT = """You are part of the Never Blank investigation system.

Your task: generate a hypothesis space for one investigation question about a business signal.

RULES:
- Use only the HEADLINE and CORE_FACT provided. Do not rely on general knowledge alone.
- Do NOT use fields like CORE_TENSION, BUSINESS_LESSON, or NEVER_BLANK_ANGLE.
- Generate 5 to 10 distinct hypotheses. Cover the full range:
    * The most obvious explanation
    * Structural/systemic explanations (the organization had no real choice)
    * Contrarian explanations (the company misjudged and got lucky)
    * Uncomfortable explanations (financial pressure, internal failure, personal decisions)
    * Explanations that would, if true, make the outcome look non-strategic

For EACH hypothesis, assign:

  if_true_impact — what happens to the most plausible positive explanation if this is true:
    "destroys_main_narrative"  — the positive explanation is invalid; the outcome was forced, accidental, or a failure
    "weakens_main_narrative"   — the positive explanation survives but requires significant qualification
    "orthogonal"               — does not affect the positive explanation either way
    "supports_main_narrative"  — strengthens the positive explanation

  distance_from_signal — how directly this hypothesis can be derived from HEADLINE + CORE_FACT:
    "low"    — directly derivable, minimal inference required
    "medium" — requires one inference step beyond the signal
    "high"   — speculative; requires multiple inference steps or external knowledge

  priority_reason — one sentence explaining WHY this impact level was assigned.
    MUST reference if_true_impact or distance_from_signal explicitly.
    "Model judgment" or "this seems most likely" are NOT valid reasons.
    Valid example: "If true, this would mean the company had no agency in the decision,
    making destroys_main_narrative the correct impact level."

Return ONLY valid JSON. No text outside the JSON block.

{
  "hypotheses": [
    {
      "hypothesis": "string",
      "if_true_impact": "destroys_main_narrative|weakens_main_narrative|orthogonal|supports_main_narrative",
      "distance_from_signal": "low|medium|high",
      "priority_reason": "string"
    }
  ]
}"""


def _validate_item(i: int, item: dict) -> tuple[str, str, str]:
    """Validate one raw hypothesis dict. Returns (impact, distance, reason) or raises."""
    impact = item.get("if_true_impact", "").strip()
    distance = item.get("distance_from_signal", "").strip()
    reason = item.get("priority_reason", "").strip()

    if impact not in _VALID_IMPACTS:
        raise ValueError(
            f"Hypothesis {i+1}: invalid if_true_impact={repr(impact)}. "
            f"Must be one of {sorted(_VALID_IMPACTS)}."
        )
    if distance not in _VALID_DISTANCES:
        raise ValueError(
            f"Hypothesis {i+1}: invalid distance_from_signal={repr(distance)}. "
            f"Must be one of {sorted(_VALID_DISTANCES)}."
        )
    if not reason:
        raise ValueError(
            f"Hypothesis {i+1} has no priority_reason. "
            "Every hypothesis must explain why its impact level was assigned."
        )
    # Weak guard: reject obviously invalid reasons
    bad_phrases = ("model judgment", "model judged", "most likely", "seems likely")
    if any(phrase in reason.lower() for phrase in bad_phrases):
        raise ValueError(
            f"Hypothesis {i+1} priority_reason is invalid: {repr(reason)}. "
            "Must reference if_true_impact or distance_from_signal, not model confidence."
        )

    return impact, distance, reason


def generate_hypothesis_space(
    question_id: str,
    question: str,
    headline: str,
    core_fact: str,
    origin_type: OriginType = "initial",
) -> list[Hypothesis]:
    """
    Generate a prioritized hypothesis space for one investigation question.

    Args:
        question_id: e.g. "Q1", "Q3"
        question:    e.g. "Why now?"
        headline:    signal HEADLINE field
        core_fact:   signal CORE_FACT field
        origin_type: "initial" or "exhaustion_check"

    Returns:
        List of Hypothesis objects sorted by test_priority (ascending).
        test_priority is computed deterministically — never assigned by LLM.

    Raises:
        ValueError: if LLM returns invalid JSON, too few hypotheses,
                    missing priority_reason, or invalid field values.
    """
    user_msg = (
        f"HEADLINE: {headline}\n"
        f"CORE_FACT: {core_fact}\n\n"
        f"INVESTIGATION QUESTION ({question_id}): {question}\n\n"
        "Generate the hypothesis space."
    )

    raw = chat(system=_SYSTEM_PROMPT, user=user_msg, json_mode=True, model=model_enrich())
    log.debug("Hypothesis Generator raw response for %s: %s", question_id, raw[:200])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Hypothesis Generator returned invalid JSON for {question_id}: {exc}\n"
            f"Raw (first 300 chars): {raw[:300]}"
        ) from exc

    raw_list = data.get("hypotheses", [])
    if len(raw_list) < 3:
        raise ValueError(
            f"Hypothesis Generator returned only {len(raw_list)} hypotheses for {question_id}. "
            "Minimum is 3 to ensure contrarian coverage."
        )

    result: list[Hypothesis] = []
    for i, item in enumerate(raw_list):
        impact, distance, reason = _validate_item(i, item)
        priority = _compute_priority(impact, distance)
        result.append(
            Hypothesis(
                hypothesis_id=f"H-{question_id}-{i+1:02d}",
                hypothesis=item.get("hypothesis", "").strip(),
                origin_type=origin_type,
                if_true_impact=impact,
                distance_from_signal=distance,
                test_priority=priority,
                priority_reason=reason,
            )
        )

    result.sort(key=lambda h: (h.test_priority, _DISTANCE_RANK.get(h.distance_from_signal, 1)))
    log.info(
        "Hypothesis Generator: %d hypotheses for %s (top priority: %s)",
        len(result),
        question_id,
        result[0].if_true_impact if result else "none",
    )
    return result


def select_for_testing(hypotheses: list[Hypothesis], max_count: int = 3) -> list[Hypothesis]:
    """
    Select top hypotheses for Evidence Collector.

    Returns up to max_count hypotheses, highest-priority first.
    Always favours hypotheses that could destroy or weaken the main narrative.
    """
    return hypotheses[:max_count]


def build_hypothesis_space(
    questions: list[dict],
    headline: str,
    core_fact: str,
) -> dict:
    """
    Run Hypothesis Generator for a list of investigation questions.

    Args:
        questions: list of {"question_id": "Q1", "question": "Why now?"}
        headline:  signal HEADLINE
        core_fact: signal CORE_FACT

    Returns:
        evidence_query_plan-compatible dict with hypothesis_space per question.
    """
    output: dict = {
        "headline": headline,
        "core_fact": core_fact,
        "questions": [],
    }

    for q in questions:
        qid = q["question_id"]
        qtext = q["question"]
        log.info("Generating hypothesis space for %s", qid)

        hypotheses = generate_hypothesis_space(
            question_id=qid,
            question=qtext,
            headline=headline,
            core_fact=core_fact,
        )
        selected = select_for_testing(hypotheses)

        output["questions"].append({
            "question_id": qid,
            "question": qtext,
            "hypothesis_space": [h.to_dict() for h in hypotheses],
            "selected_for_testing": [h.hypothesis_id for h in selected],
        })

    return output
