"""Discovery Builder — Editorial Engine V2 Module 3.

Builds structured reasoning inputs, not publishable prose. The owner is the
protagonist; a company example may appear once as supporting evidence only.
"""

import json

from src.utils.llm_client import chat, model_article
from src.utils.logger import get_logger

log = get_logger("editorial.discovery_builder")
_MIN_SEQUENCE = 2
_MAX_SEQUENCE = 4

_SYSTEM_PROMPT = """You are the Discovery Builder for Never Blank.

Your output is STRUCTURED REASONING MATERIAL for downstream platform writers.
It is not finished prose, not a first-person investigation, and not a detective story.

The reader is a small-business owner. The owner situation is the protagonist.
A named company, publication, or corporate case may appear in at most ONE evidence
item and only as supporting evidence. The structure must remain coherent if every
company name is removed.

Build four fields:

1. first_wrong_explanation
   The natural explanation an owner gives themselves for the situation.
   Write it as a concise proposition, not "I assumed..." and not "many founders believe...".

2. puzzle
   The single observable contradiction that makes that explanation insufficient.
   It must be grounded in the provided inputs. No theatrical surprise language.

3. investigation_sequence
   Two to four concise evidence/mechanism beats. Each beat must do one distinct job:
   - identify a behavior or process;
   - show a consequence;
   - clarify the mechanism;
   - optionally use one company example as corroboration.
   Do not narrate research actions. Forbidden constructions include:
   "I figured", "I went looking", "I expected", "But then I found",
   "That's when I realized", "So I checked", "Then I saw".

4. aha_setup
   A concrete owner-recognition scene that leaves the reader ready for the reframe.
   Prefer second person or a direct small-business situation. Do not state the final thesis.

Hard rules:
- no first-person detective narration;
- no diary of research actions;
- no article-ready transitions;
- no invented facts;
- company evidence in at most one investigation_sequence item;
- the owner scenario and mechanism must dominate the output.

Return ONLY valid JSON:
{
  "first_wrong_explanation": "string",
  "puzzle": "string",
  "investigation_sequence": ["string", "string"],
  "aha_setup": "string"
}"""


def _contains_detective_template(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "i figured", "i went looking", "i expected", "but then i found",
        "that's when i realized", "that’s when i realized", "so i checked",
        "then i saw", "i thought maybe",
    )
    return any(marker in lowered for marker in markers)


def _validate(data: dict) -> dict:
    for field in ("first_wrong_explanation", "puzzle", "aha_setup"):
        value = data.get(field, "")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Discovery Builder: field {field!r} missing or empty")
        if _contains_detective_template(value):
            raise ValueError(f"Discovery Builder: field {field!r} uses detective-template narration")

    sequence = data.get("investigation_sequence", [])
    if not isinstance(sequence, list) or not (_MIN_SEQUENCE <= len(sequence) <= _MAX_SEQUENCE):
        raise ValueError(
            f"Discovery Builder: investigation_sequence must have {_MIN_SEQUENCE}-{_MAX_SEQUENCE} items"
        )

    clean_sequence = []
    for i, item in enumerate(sequence):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"Discovery Builder: investigation_sequence item {i} is empty")
        if _contains_detective_template(item):
            raise ValueError(f"Discovery Builder: investigation_sequence item {i} uses detective narration")
        clean_sequence.append(item.strip())

    return {
        "first_wrong_explanation": data["first_wrong_explanation"].strip(),
        "puzzle": data["puzzle"].strip(),
        "investigation_sequence": clean_sequence,
        "aha_setup": data["aha_setup"].strip(),
    }


def build_discovery(hook: dict, spine: dict, decision_lens: dict, signal: dict) -> dict:
    user = f"""selected_hook: {hook.get('selected_hook', '')}
narrative_spine: {spine.get('narrative_spine', '')}
visibility_pattern: {signal.get('visibility_pattern', '')}
founder_scenario: {signal.get('founder_scenario', '')}
mechanism: {signal.get('mechanism', '')}
business_consequence: {signal.get('business_consequence', '')}
company_as_evidence_of: {signal.get('company_as_evidence_of', '')}
evidence_limit: {signal.get('evidence_limit', '')}
CORE_FACT: {signal.get('CORE_FACT', '')}
CORE_TENSION: {signal.get('CORE_TENSION', '')}
RESPONSE_TAKEN: {signal.get('RESPONSE_TAKEN', '')}
OUTCOME_IF_KNOWN: {signal.get('OUTCOME_IF_KNOWN', '')}
COUNTER_EXAMPLE: {signal.get('COUNTER_EXAMPLE', '')}
owner_system_objective: {decision_lens.get('owner_system_objective', '')}
delivery_vs_presence_conflict: {decision_lens.get('delivery_vs_presence_conflict', '')}

Produce owner-centered structured discovery material. Do not write publishable prose.
The company is evidence, never protagonist."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_article())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Discovery Builder returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    result = _validate(data)
    log.info("Discovery Builder: puzzle=%r, sequence_len=%d", result["puzzle"][:80], len(result["investigation_sequence"]))
    return result
