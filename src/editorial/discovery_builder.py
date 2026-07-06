"""
Discovery Builder — Editorial Engine V2 Module 3
Spec: docs/EDITORIAL_ENGINE_V2.md, Module 3

Voice: "Here is why I stopped believing the first interpretation." The reader is a
co-investigator watching the obvious explanation break, not a student receiving
analysis.

LIMITATION (temporary): per spec, this module receives hypothesis_history and
contradicted_hypotheses from a real Evidence Collector. That layer does not exist
in code yet. This module instead constructs a plausible discovery arc directly from
enriched signal fields (CORE_TENSION as the puzzle source, RESPONSE_TAKEN /
OUTCOME_IF_KNOWN / COUNTER_EXAMPLE as the evidence beats). The arc is honest to the
provided facts but is not built from a tested hypothesis space. Replace this with a
real hypothesis_history-driven version once the Investigation Layer exists.
"""

import json

from src.utils.llm_client import chat, model_article
from src.utils.logger import get_logger

log = get_logger("editorial.discovery_builder")

_MIN_SEQUENCE = 3
_MAX_SEQUENCE = 5

_SYSTEM_PROMPT = """You are the Discovery Builder for Never Blank.

Your job is not to deliver the surviving explanation - it is to make the reader
arrive at it themselves, one step ahead of the article confirming it.

VOICE — HARD REQUIREMENT:
Every field is written in first person, as a narrator investigating in real
time and changing their mind on the page. Not "the compliance explanation
falls apart because..." (analyst voice) but "I assumed this was about
compliance. Then one fact didn't fit." (narrator voice). This is not optional
styling — a version of these fields with the "I" removed and stated as
settled analysis instead has failed the task, no matter how accurate the
content is. Required-voice reference examples:
- "I thought Getty had blinked."
- "Except the lawsuit wasn't dropped. It's still active."
- "So I went back to the timeline."
- "That's not the sequence of a company reacting. It's the sequence of a
  company setting terms."

Four beats, each in that first-person investigating voice:

1. first_wrong_explanation - what I assumed, going in - the interpretation
   everyone held, including the narrator, before the investigation. Not a
   straw man - the actual obvious conclusion a reader would reach from the
   headline alone. Phrase it as something the narrator believed ("I assumed
   X"), not as a description of a public misconception ("Many believe X").

2. puzzle - the one fact that made me stop believing it. ONE specific fact
   that does not fit the first explanation. Not a list of doubts - a single
   contradiction. A crack invites qualification; a contradiction forces a new
   explanation. This is the pivot of the whole piece - it must read as a
   genuine surprise the narrator ran into, not a thesis being asserted.

3. investigation_sequence - what I looked at next, in order, and what each
   step revealed. 3 to 5 ordered beats, sequence-first not summary-first, as
   things the narrator did or noticed ("So I checked X." "That's when Y
   surfaced." "Then Z.") rather than a report ("The timeline shows..."). Do
   not state the surviving explanation here - the reader should watch it form.

4. aha_setup - the last thing I found before it clicked. Present the
   evidence in the narrator's voice; do not state the conclusion
   ("therefore..."). The reader should arrive at the conclusion one sentence
   ahead of the text.

Rules:
- Every field must be in first person. A field with no "I" in it, or written
  as third-person analysis, fails the task regardless of factual accuracy.
- first_wrong_explanation must be a position a reader would genuinely hold, not a
  weak position set up to be knocked down.
- puzzle must be a single fact, not a list.
- investigation_sequence must show sequence ("First this. Then this. Then this."),
  not summary ("The timeline shows X").
- aha_setup must not state the conclusion - the article confirms it, the reader
  already has it.

Return ONLY valid JSON:
{
  "first_wrong_explanation": "string",
  "puzzle": "string",
  "investigation_sequence": ["string", "string", "string"],
  "aha_setup": "string"
}"""


def _validate(data: dict) -> dict:
    for field in ("first_wrong_explanation", "puzzle", "aha_setup"):
        value = data.get(field, "")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Discovery Builder: field {field!r} missing or empty in LLM output")

    sequence = data.get("investigation_sequence", [])
    if not isinstance(sequence, list) or not (_MIN_SEQUENCE <= len(sequence) <= _MAX_SEQUENCE):
        raise ValueError(
            f"Discovery Builder: investigation_sequence must have {_MIN_SEQUENCE}-{_MAX_SEQUENCE} "
            f"items, got {len(sequence) if isinstance(sequence, list) else 'non-list'}"
        )
    clean_sequence = []
    for i, item in enumerate(sequence):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"Discovery Builder: investigation_sequence item {i} is empty")
        clean_sequence.append(item.strip())

    return {
        "first_wrong_explanation": data["first_wrong_explanation"].strip(),
        "puzzle": data["puzzle"].strip(),
        "investigation_sequence": clean_sequence,
        "aha_setup": data["aha_setup"].strip(),
    }


def build_discovery(hook: dict, spine: dict, decision_lens: dict, signal: dict) -> dict:
    """
    Produce the Discovery Builder dict.

    Raises ValueError if any field is missing/empty, or investigation_sequence is
    outside the 3-5 item range.
    """
    user = f"""HEADLINE: {signal.get('HEADLINE', '')}
selected_hook: {hook.get('selected_hook', '')}
narrative_spine: {spine.get('narrative_spine', '')}
CORE_FACT: {signal.get('CORE_FACT', '')}
CORE_TENSION: {signal.get('CORE_TENSION', '')}
RESPONSE_TAKEN: {signal.get('RESPONSE_TAKEN', '')}
OUTCOME_IF_KNOWN: {signal.get('OUTCOME_IF_KNOWN', '')}
COUNTER_EXAMPLE: {signal.get('COUNTER_EXAMPLE', '')}
strategic_objective: {decision_lens.get('strategic_objective', '')}

Produce the Discovery Builder JSON. The reader is being built toward the
narrative_spine above - the aha_setup should leave them one sentence away from it."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_article())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Discovery Builder returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    result = _validate(data)
    log.info("Discovery Builder: puzzle=%r, sequence_len=%d", result["puzzle"][:80], len(result["investigation_sequence"]))
    return result
