"""
Never Blank Voice — Editorial Engine V2 Module 6
Spec: docs/EDITORIAL_ENGINE_V2.md, Module 6

Final pass for small business visibility articles.
Generates the Echo (article-specific final thought, sometimes absent) and an optional
CTA (natural invitation, varies by article). Runs a checklist self-assessment.

Key changes from V1:
- "signature" is now the Echo: article-specific, generated from multiple candidates,
  can be null if no strong candidate emerged (not forced into every article).
- CTA is new: optional natural invitation, varies by article, must precede Echo if used.
- Checklist updated for the 9-step visibility/presence arc.

checklist_pass=False is logged as a warning, not raised as a hard failure.
"""

import json

from src.utils.llm_client import chat, model_article
from src.utils.logger import get_logger

log = get_logger("editorial.never_blank_voice")

_SYSTEM_PROMPT = """You are the Never Blank Voice module - the final quality pass.

Never Blank investigates patterns that make small businesses visible, recognizable,
remembered, and commercially present. The reader is the central character.

You do not add analysis. Your job:

1. Generate the ECHO: 3-5 candidate Echo lines, then select the strongest one.

   The Echo is a distinct final thought designed to remain in the reader's mind.
   It is NOT:
   - a summary of the article
   - a slogan pasted onto every article
   - a generic motivational line
   - always "Never Blank" as a tagline

   It IS:
   - specific to THIS article's pattern and argument
   - earned by the logic that preceded it
   - emotionally restrained (not inspiring, not instructional)
   - memorable out of context
   - able to work as a standalone sentence

   Quality register examples (do NOT copy — generate article-specific):
   "The most expensive publication is not the one that received few views. It is the one that never appeared."
   "If presence depends only on the owner's free time, silence eventually becomes part of the strategy — even when nobody chose it."
   "Customers rarely decide to forget a business. They simply stop encountering it."

   Return null for echo_line if no candidate passed the quality bar for this article.
   Do not force an Echo. An absent Echo is better than a generic one.

2. Generate the CTA — governed by cta_mode (received in the user message):

   cta_mode MUST be followed exactly. Do NOT decide on your own whether to include a CTA.
   - cta_mode = none: set cta_line to null. No CTA under any circumstances.
   - cta_mode = reflection: write a soft reflective invitation tied to the reader
     recognizing their situation. Example: "If you recognize your business in this
     pattern, let's look at where your presence starts depending entirely on your
     time and energy."
   - cta_mode = diagnostic: write an invitation to a visibility audit or to identify
     where the system breaks.
   - cta_mode = example_request: write an invitation to request an example.
   - cta_mode = direct_conversation: write a direct, natural invitation to discuss fit.

   When CTA is included:
   - Must precede the Echo in the article
   - Must be natural and tied to this specific article's pattern
   - Forbidden: "book a call", "learn more", "buy now", "let us handle your content",
     "transform your social media", "schedule your free consultation"

3. Self-check the assembled piece against this checklist (all must be true):
   - hook creates a gap in the first 1-3 sentences
   - hook does not require knowing the company name to make sense — if the hook only
     lands for someone familiar with the corporate example, it has failed
   - the first third of the article speaks to the owner's situation, not to the
     company's situation
   - there is a Recognition moment where the reader sees their own situation specifically
   - evidence is traceable — no invented facts about specific businesses
   - corporate evidence does not occupy more than 20-25% of the article — the article
     must remain coherent if the company example is removed
   - reframe challenges the obvious explanation with something specific to this pattern
   - business meaning connects to commercial reality (trust, pipeline, future sales)
   - echo (if present) is specific to this article and not generic
   - cta (if present) precedes the echo and uses none of the forbidden phrases

Return ONLY valid JSON:
{
  "echo_candidates": ["string", "string", "string"],
  "echo_line": "string or null - the selected Echo, or null if none passed quality bar",
  "cta_line": "string or null - the natural invitation, or null if not appropriate",
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
    cta_mode: str = "none",
) -> dict:
    """
    Generate the Echo, optional CTA, run the Voice checklist, and assemble the
    structured_article dict consumed by Platform Composer.

    Echo (echo_line) can be None — not every article earns a strong Echo.
    CTA (cta_line) can be None — not every article includes a natural invitation.

    Raises ValueError if the signature is empty when the LLM returned a non-null
    echo_line that is not a valid string.
    """
    user = f"""HEADLINE: {signal.get('HEADLINE', '')}
cta_mode: {cta_mode}
selected_hook: {hook.get('selected_hook', '')}
narrative_spine: {spine.get('narrative_spine', '')}
first_wrong_explanation: {discovery.get('first_wrong_explanation', '')}
puzzle: {discovery.get('puzzle', '')}
aha_setup: {discovery.get('aha_setup', '')}
surviving_explanation: {story.get('surviving_explanation', '')}
reframe: {story.get('reframe', '')}
business_translation: {story.get('business_translation', '')}

Produce the Never Blank Voice JSON. Follow cta_mode exactly."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_article())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Never Blank Voice returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    # Echo is optional — null means no strong candidate for this article
    echo_raw = data.get("echo_line")
    echo_line: str | None = None
    if echo_raw is not None:
        if not isinstance(echo_raw, str):
            raise ValueError("Never Blank Voice: echo_line must be a string or null")
        echo_line = echo_raw.strip() or None

    # CTA is optional
    cta_raw = data.get("cta_line")
    cta_line: str | None = None
    if cta_raw is not None:
        if not isinstance(cta_raw, str):
            raise ValueError("Never Blank Voice: cta_line must be a string or null")
        cta_line = cta_raw.strip() or None

    checklist_pass = bool(data.get("checklist_pass", False))
    checklist_notes = str(data.get("checklist_notes", "")).strip()
    if not checklist_pass:
        log.warning(
            "Never Blank Voice: checklist FAILED for signal %s - %s",
            signal.get("SIGNAL_ID", "unknown"), checklist_notes or "(no notes)",
        )

    # Build backward-compatible signature field: Echo if present, else empty string
    # Platform Composer uses "signature" block; when echo is null we skip that block.
    signature = echo_line or ""

    structured_article = {
        "signal_id": signal.get("SIGNAL_ID", ""),
        "cta_mode": cta_mode,
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
        "reframe": story.get("reframe", ""),
        "remaining_uncertainty": story.get("remaining_uncertainty"),
        "business_translation": story.get("business_translation", ""),
        # Echo fields
        "echo_line": echo_line,
        "cta_line": cta_line,
        # Backward-compat: signature = echo when present, empty string when absent
        "signature": signature,
        "checklist_pass": checklist_pass,
        "checklist_notes": checklist_notes,
        "echo_candidates": data.get("echo_candidates", []),
    }

    log.info(
        "Never Blank Voice: cta_mode=%s echo=%r cta=%s checklist_pass=%s",
        cta_mode, (echo_line or "")[:80], bool(cta_line), checklist_pass,
    )
    return structured_article
