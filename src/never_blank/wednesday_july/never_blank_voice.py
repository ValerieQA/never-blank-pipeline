"""
Never Blank Voice — Editorial Engine V2 Module 6
Spec: docs/EDITORIAL_ENGINE_V2.md, Module 6

Final pass. Does not add content beyond the signature line - it generates the
signature and self-checks the assembled piece against the Never Blank Voice
checklist, then returns the structured_article object that Platform Composer
consumes (spec Section 3, "What the Platform Composer receives").

checklist_pass=False is logged as a warning, not raised as a hard failure: the spec
calls for routing back to "the relevant stage," which this linear pipeline does not
yet support per-stage. Treat repeated checklist failures on the same signal as a
signal that Discovery Builder or Hook Engine need attention.
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

log = get_logger("editorial.never_blank_voice")

_SYSTEM_PROMPT = """You are the Never Blank Voice module - the final quality pass.

You do not add analysis. Your job:

1. Write the signature line: "Never Blank: [one observation that reframes the
   signal]". Must not repeat the headline or the hook verbatim. It should work out
   of context, as a standalone observation, not a summary.

2. Self-check the assembled piece against this checklist (all must be true):
   - hook creates a gap in the first 1-3 sentences
   - there is at least one moment where the reader encounters something unexpected
   - there is a point where tension is introduced and a point where it resolves
   - the business lesson is specific enough to be wrong for some companies
   - the signature line does not repeat the headline
   - the ending (business_translation + signature) is stronger than the opening (hook)

Return ONLY valid JSON:
{
  "signature": "string - format: Never Blank: [observation]",
  "checklist_pass": true,
  "checklist_notes": "string - brief note on any item that failed, empty if all passed"
}"""


def finalize_article(
    hook: dict,
    reader_context: str | None,
    discovery: dict,
    story: dict,
    spine: dict,
    decision_lens: dict,
    signal: dict,
) -> dict:
    """
    Generate the signature line, run the Voice checklist, and assemble the
    structured_article dict consumed by Platform Composer.

    Raises ValueError if the signature is missing/empty.
    """
    user = f"""HEADLINE: {signal.get('HEADLINE', '')}
selected_hook: {hook.get('selected_hook', '')}
narrative_spine: {spine.get('narrative_spine', '')}
first_wrong_explanation: {discovery.get('first_wrong_explanation', '')}
puzzle: {discovery.get('puzzle', '')}
aha_setup: {discovery.get('aha_setup', '')}
surviving_explanation: {story.get('surviving_explanation', '')}
business_translation: {story.get('business_translation', '')}

Produce the Never Blank Voice JSON."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_article())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Never Blank Voice returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    signature = data.get("signature", "")
    if not isinstance(signature, str) or not signature.strip():
        raise ValueError("Never Blank Voice: signature missing or empty")
    signature = signature.strip()

    checklist_pass = bool(data.get("checklist_pass", False))
    checklist_notes = str(data.get("checklist_notes", "")).strip()
    if not checklist_pass:
        log.warning(
            "Never Blank Voice: checklist FAILED for signal %s - %s",
            signal.get("SIGNAL_ID", "unknown"), checklist_notes or "(no notes)",
        )

    structured_article = {
        "signal_id": signal.get("SIGNAL_ID", ""),
        "narrative_spine": spine.get("narrative_spine", ""),
        "hook": hook.get("selected_hook", ""),
        "reader_context": reader_context,
        "discovery": {
            "first_wrong_explanation": discovery.get("first_wrong_explanation", ""),
            "puzzle": discovery.get("puzzle", ""),
            "investigation_sequence": discovery.get("investigation_sequence", []),
            "aha_setup": discovery.get("aha_setup", ""),
        },
        "surviving_explanation": story.get("surviving_explanation", ""),
        "remaining_uncertainty": story.get("remaining_uncertainty"),
        "business_translation": story.get("business_translation", ""),
        "signature": signature,
        "checklist_pass": checklist_pass,
    }

    log.info("Never Blank Voice: signature=%r checklist_pass=%s", signature[:80], checklist_pass)
    return structured_article
