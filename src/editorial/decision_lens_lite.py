"""
Decision Lens Lite
Spec: docs/LERA_OPERATING_SYSTEM.md, Section 12 (Decision Lens output schema)

Updated for owner-centered editorial identity: questions now concern the owner's
presence system, not the corporate company's strategy. Receives pattern-extractor
fields (visibility_pattern, founder_scenario, mechanism, etc.) merged into the
signal dict by the pipeline.

TEMPORARY SUBSTITUTE: the real Decision Lens receives an investigation_evidence_report
from Curiosity Engine + Evidence Collector (Q1-Q6, hypothesis testing, source tiers).
That layer does not exist in code yet. This module derives the same output schema
directly from already-enriched signal fields in a single LLM call. Downstream modules
consume this module's output shape unchanged.
"""

import json

from src.strategy.execution_context import (
    AudienceSelection,
    DecisionLensEditorialStrategyView,
)
from src.research.evidence import NormalizedResearchArtifact

from src.utils.llm_client import chat, model_enrich
from src.utils.logger import get_logger

log = get_logger("editorial.decision_lens_lite")

_SYSTEM_PROMPT = """You are the Decision Lens for Never Blank.

Never Blank investigates patterns that make small businesses visible, recognizable,
remembered, and commercially present. The reader is the owner — not the corporate
company whose news triggered the signal.

The Pattern Extractor has already identified the owner-centered visibility pattern.
Your job is to analyze what is happening in the OWNER'S PRESENCE SYSTEM — not what
the company decided.

Four primary questions:

1. core_pattern
   The owner-level visibility/presence pattern, stated precisely. One sentence.
   Must describe what happens in small businesses, not what a company did.

2. owner_system_objective
   What the owner's process is ACTUALLY optimizing for — not what the owner intends,
   but what the system produces. When a founder goes quiet, the system is optimizing
   for immediate delivery throughput at the cost of future visibility. Name the actual
   optimization function, not the intention.
   Example: "optimizing for immediate client delivery at the cost of non-urgent
   presence maintenance"

3. delivery_vs_presence_conflict
   The specific tension between client work and visibility work in this pattern.
   Why do they compete? What makes visibility work lose? One to two sentences.

4. customer_memory_consequence
   What happens to customer memory specifically when this presence pattern plays out.
   Not what the owner feels — what the customer experiences over time.
   One to two sentences.

5. structural_cause
   Why this pattern is structural, not a discipline failure. What makes it repeat
   even in businesses that intend to maintain presence? One to two sentences.

6. never_blank_insight
   The specific non-obvious observation this pattern surfaces — the thing that is
   true and surprising and not yet named by the owner. Not a restatement of
   customer_memory_consequence or structural_cause.

Rules:
- All six fields must be about the owner's situation, not the company's situation.
- Do not name the corporate company in core_pattern, owner_system_objective,
  delivery_vs_presence_conflict, or customer_memory_consequence.
- never_blank_insight must be non-obvious — not a restatement of what is already
  in the other fields.
- NEVER_BLANK_ANGLE is an editorial hypothesis. Test and sharpen it against the
  verified facts; do not ignore it and do not repeat it uncritically.
- Prefer a concrete mechanism, contradiction, or worked consequence over generic
  advice about consistency or "creating more content".
- Return ONLY valid JSON. No text outside the JSON block.

{
  "core_pattern": "string",
  "owner_system_objective": "string",
  "delivery_vs_presence_conflict": "string",
  "customer_memory_consequence": "string",
  "structural_cause": "string",
  "never_blank_insight": "string"
}"""


def _validate(data: dict) -> dict:
    required_strings = [
        "core_pattern",
        "owner_system_objective",
        "delivery_vs_presence_conflict",
        "customer_memory_consequence",
        "structural_cause",
        "never_blank_insight",
    ]
    for field in required_strings:
        value = data.get(field, "")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Decision Lens Lite: field {field!r} missing or empty in LLM output")

    return {
        "core_pattern": data["core_pattern"].strip(),
        "owner_system_objective": data["owner_system_objective"].strip(),
        "delivery_vs_presence_conflict": data["delivery_vs_presence_conflict"].strip(),
        "customer_memory_consequence": data["customer_memory_consequence"].strip(),
        "structural_cause": data["structural_cause"].strip(),
        "never_blank_insight": data["never_blank_insight"].strip(),
    }


def generate_decision_lens(
    signal: dict,
    strategy_view: DecisionLensEditorialStrategyView | None = None,
    audience: AudienceSelection | None = None,
    research_artifact: NormalizedResearchArtifact | None = None,
) -> dict:
    """
    Produce a Decision Lens output dict focused on the owner's presence system.

    Receives the enriched signal dict which includes pattern_extractor output fields
    (visibility_pattern, founder_scenario, mechanism, etc.) merged in by the pipeline.

    Raises ValueError if the LLM output does not satisfy the schema.
    """
    strategy_section = ""
    if strategy_view is not None:
        if audience is None:
            raise ValueError("Decision Lens requires an explicit audience selection")
        editorial = strategy_view.brand_editorial
        evidence_boundary = [
            {"evidence_id": item.evidence_id, "claim": item.claim,
             "source_ids": item.source_ids, "disposition": item.disposition.value}
            for item in research_artifact.evidence
        ] if research_artifact is not None else []
        strategy_section = f"""
Configured business strategy (treat every list as a boundary, not source material):
business_positioning: {strategy_view.positioning.statement}
selected_audience_id: {audience.audience_id}
selected_audience_name: {audience.audience_name}
selected_audience_problem: {audience.selected_problem}
proof_points_available_as_evidence_boundaries_only: {json.dumps(strategy_view.positioning.proof_points, ensure_ascii=False)}
IMPORTANT: proof points bound what may be supported; they are not permission to invent outcomes, customers, metrics, or facts.
preferred_claims: {json.dumps(editorial.preferred_claims, ensure_ascii=False)}
prohibited_claims: {json.dumps(editorial.prohibited_claims, ensure_ascii=False)}
factual_legal_reputational_restrictions: {json.dumps(editorial.legal_factual_reputational_restrictions, ensure_ascii=False)}
content_objectives: {json.dumps(strategy_view.content.objectives, ensure_ascii=False)}
content_territories: {json.dumps(strategy_view.content.territories, ensure_ascii=False)}
validated_normalized_research_evidence: {json.dumps(evidence_boundary, ensure_ascii=False)}
Use only this normalized evidence boundary for factual support. Do not invent provider data or unsupported outcomes.
"""

    user = f"""HEADLINE: {signal.get('HEADLINE', '')}
CORE_FACT: {signal.get('CORE_FACT', '')}
CORE_TENSION: {signal.get('CORE_TENSION', '')}
BUSINESS_LESSON: {signal.get('BUSINESS_LESSON', '')}
WHY_THIS_CASE_IS_INTERESTING: {signal.get('WHY_THIS_CASE_IS_INTERESTING', '')}
NEVER_BLANK_ANGLE: {signal.get('NEVER_BLANK_ANGLE', '')}
POTENTIAL_HOOK: {signal.get('POTENTIAL_HOOK', '')}
TARGET_AUDIENCE: {signal.get('TARGET_AUDIENCE', 'founder')}
BLOG_ANGLE: {signal.get('BLOG_ANGLE', '')}
STORY_ANGLE: {signal.get('STORY_ANGLE', '')}
CONTENT_PACKAGE (supporting preview, never a source of new facts): {json.dumps(signal.get('CONTENT_PACKAGE', {}), ensure_ascii=False)}

Pattern Extractor output (owner-centered framing already extracted):
visibility_pattern: {signal.get('visibility_pattern', '')}
founder_scenario: {signal.get('founder_scenario', '')}
mechanism: {signal.get('mechanism', '')}
business_consequence: {signal.get('business_consequence', '')}{strategy_section}
Produce the Decision Lens JSON — focused on the owner's presence system."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_enrich())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Decision Lens Lite returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    result = _validate(data)
    log.info(
        "Decision Lens Lite: core_pattern=%r",
        result["core_pattern"][:80],
    )
    return result
