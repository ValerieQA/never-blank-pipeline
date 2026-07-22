"""
Platform Composer — Editorial Engine V2 Module 7
Spec: docs/EDITORIAL_ENGINE_V2.md, Module 7

Structural editor, not a text editor. Receives the structured_article object from
Never Blank Voice and produces five platform-specific bodies, each governed by a
fixed per-block full/compressed/skip table.

Updated for the new 9-step visibility/presence arc:
- New blocks: reframe, echo (formerly signature), cta
- echo is optional (can be absent from article — not forced)
- cta is optional (varies by article — not in every post)
- reader_context is now rarely used (small business patterns don't need company context)

Block table from EDITORIAL_ENGINE_V2.md, Section 5:
  hook, reader_context, observation (first_wrong_explanation), recognition (aha_setup),
  evidence_pattern (puzzle+investigation_sequence), explanation (surviving_explanation),
  reframe, business_meaning (business_translation), echo (signature), cta

Invariant across all formats: narrative_spine, hook, recognition, echo (when present)
are present in every format (compressed or full, never skip for these core blocks).
"""

import json

from src.utils.llm_client import chat, model_article, model_social
from src.utils.logger import get_logger

log = get_logger("editorial.platform_composer")

# Maps structured_article field names to logical block names used in the table.
# Some blocks aggregate multiple source fields.
_BLOCK_TABLE = {
    "long": {
        "hook": "full",
        "reader_context": "full",
        "observation": "full",       # first_wrong_explanation repurposed as Observation
        "recognition": "full",       # aha_setup repurposed as Recognition
        "evidence_pattern": "full",  # puzzle + investigation_sequence
        "explanation": "full",       # surviving_explanation
        "reframe": "full",
        "business_meaning": "full",  # business_translation
        "echo": "full",              # signature/echo_line
        "cta": "full",
    },
    "reading": {
        "hook": "full",
        "reader_context": "skip",
        "observation": "full",
        "recognition": "full",
        "evidence_pattern": "compressed",
        "explanation": "full",
        "reframe": "compressed",
        "business_meaning": "compressed",
        "echo": "full",
        "cta": "full",
    },
    "medium": {
        "hook": "compressed",
        "reader_context": "skip",
        "observation": "compressed",
        "recognition": "compressed",
        "evidence_pattern": "compressed",
        "explanation": "compressed",
        "reframe": "compressed",
        "business_meaning": "compressed",
        "echo": "full",
        "cta": "compressed",
    },
    "instagram": {
        "hook": "compressed",
        "reader_context": "skip",
        "observation": "compressed",
        "recognition": "compressed",
        "evidence_pattern": "skip",
        "explanation": "skip",
        "reframe": "skip",
        "business_meaning": "skip",
        "echo": "full",
        "cta": "skip",
    },
    "short": {
        "hook": "compressed",
        "reader_context": "skip",
        "observation": "skip",
        "recognition": "skip",
        "evidence_pattern": "skip",
        "explanation": "skip",
        "reframe": "skip",
        "business_meaning": "skip",
        "echo": "full",
        "cta": "skip",
    },
}

_WORD_RANGE = {
    "long": (700, 1000),
    "reading": (350, 600),
    "medium": (120, 220),
    "instagram": (80, 150),
    "short": (40, 80),
}

_READING_BEHAVIOR = {
    "long": "Reads at a desk. Wants full evidence arc, mechanism, and reframe.",
    "reading": "Reads the whole thing. Wants narrative and recognition, not evidence density.",
    "medium": "Reads in a feed. Needs a complete standalone arc: Hook → Recognition → Explanation → Reframe → Echo.",
    "instagram": "Reads on a phone, one screen at a time. Make them feel the pattern before they understand it.",
    "short": "Reads one idea. Hook or Echo only. Does not attempt to summarize the pattern.",
}

_FORMAT_CONSTRAINTS = {
    "long": (
        "Full nine-step arc. Hook → Observation → Recognition → Evidence → Explanation "
        "→ Reframe → Business Meaning → Echo (if present) → CTA (if present). "
        "Flowing prose, not a bulleted report."
    ),
    "reading": (
        "Preserve the narrative arc. Remove evidence citations that slow reading pace. "
        "A reader should feel the pattern without cataloguing the evidence. "
        "Target: readable in 2-4 minutes without stopping."
    ),
    "medium": (
        "Must be a complete standalone text. A reader who does not know the research context "
        "must reach the Recognition and the Reframe without needing the Long version. "
        "No dangling references to evidence not present in this version."
    ),
    "instagram": (
        "The most literary format. Make the reader feel the visibility pattern before they "
        "understand it analytically. No analysis. No qualifications. No stacked facts. "
        "Only the emotional sequence: something was assumed, then one moment changed it. "
        "One idea per paragraph — blank lines are part of the storytelling. "
        "The reader should finish thinking 'I just recognized something' — not "
        "'I just read an analysis.'"
    ),
    "short": (
        "One idea. Either the Hook that opens the gap, or the Echo that closes it. "
        "Does not attempt to compress the pattern into a summary — that produces summaries, "
        "not insights."
    ),
}

_COMPRESSION_RULE = (
    "The rule for compressing a block: remove sentences that explain what the previous "
    "sentence already showed. Do not remove sentences that move the reader to the next "
    "cognitive position. Never summarize a block — compress it to its cognitive minimum."
)


def _block_content(structured_article: dict, block: str) -> str | None:
    """Map logical block names to structured_article fields."""
    discovery = structured_article.get("discovery", {})

    # Aggregate evidence_pattern from puzzle + investigation_sequence
    puzzle = discovery.get("puzzle", "")
    investigation_seq = discovery.get("investigation_sequence", [])
    evidence_combined = puzzle
    if investigation_seq:
        evidence_combined = puzzle + " " + " ".join(investigation_seq) if puzzle else " ".join(investigation_seq)

    mapping = {
        "hook": structured_article.get("hook", ""),
        "reader_context": structured_article.get("reader_context"),
        # Observation = first_wrong_explanation repurposed as "the named pattern"
        "observation": discovery.get("first_wrong_explanation", ""),
        # Recognition = aha_setup repurposed as "reader recognizes their situation"
        "recognition": discovery.get("aha_setup", ""),
        # Evidence = puzzle + investigation_sequence
        "evidence_pattern": evidence_combined or None,
        # Explanation = surviving_explanation (the mechanism)
        "explanation": structured_article.get("surviving_explanation", ""),
        "reframe": structured_article.get("reframe", ""),
        # Business meaning = business_translation
        "business_meaning": structured_article.get("business_translation", ""),
        # Echo = echo_line (optional) — falls back to signature for backward compat
        "echo": structured_article.get("echo_line") or structured_article.get("signature") or None,
        "cta": structured_article.get("cta_line"),
    }
    return mapping.get(block)


def _build_user_prompt(structured_article: dict, format_key: str) -> str:
    table = _BLOCK_TABLE[format_key]
    lo, hi = _WORD_RANGE[format_key]

    lines = [
        f"narrative_spine (do not state verbatim — the article must earn it): "
        f"{structured_article.get('narrative_spine', '')}",
        f"Target length: {lo}-{hi} words.",
        f"Reading behavior: {_READING_BEHAVIOR[format_key]}",
        "",
        "Blocks for this format (only non-skipped blocks are provided):",
    ]
    for block, mode in table.items():
        if mode == "skip":
            continue
        content = _block_content(structured_article, block)
        if content is None:
            continue
        lines.append(f"- {block} [{mode}]: {content}")

    lines.append("")
    lines.append(f"Format-specific constraints: {_FORMAT_CONSTRAINTS[format_key]}")
    lines.append(_COMPRESSION_RULE)
    lines.append("")
    lines.append(
        "Assemble the final body text for this format now, in the order the blocks "
        "are listed above. The narrative_spine is context — it must be EARNED by the "
        "piece, not stated. "
        "If the 'cta' block is present, it must appear BEFORE the 'echo' block in the "
        "assembled text. "
        "If the 'echo' block is absent, do not invent one."
    )

    return "\n".join(lines)


_SYSTEM_PROMPT = """You are the Platform Composer for Never Blank.

Never Blank writes for small business owners who must recognize their own situation
in the content — not study someone else's company. The reader is the central character.

You are a structural editor, not a text editor: you do not receive an article and
cut sentences. You receive a fixed set of named blocks and assemble them into one
platform's body text, respecting exactly which blocks are full, compressed, or
omitted for this format (given in the user message). Preserve every cognitive step
of the blocks you are given. Compress only exposition.

NINE-STEP ARC — preserve the arc structure:
The article moves: Hook → Observation → Recognition → Evidence → Explanation →
Reframe → Business Meaning → (CTA if present, always before Echo) → Echo (if present).
Do not reorder these steps. Reframe must come after Explanation. CTA must come before Echo.

VOICE — READER IS THE CENTRAL CHARACTER:
The observation and recognition blocks are written from the perspective of someone
watching a pattern in the reader's own business. Your job is to assemble them, not
to translate them into third-person analytical prose. If a block reads in second
person ("Your clients see silence, not busy"), it must stay in second person — not
be rewritten into "businesses that do not communicate are perceived negatively."

DO NOT RESOLVE TOO FAST:
The most common failure is stating the business meaning within the first few sentences
after the hook. Business_meaning and reframe arrive late in the arc — they must not
appear early, restated, or hedge-free before the reader has been through the
recognition and explanation steps.

THE ECHO MUST EARN ITS PLACE:
If an echo block is provided, it must appear verbatim at the very end of the body.
Do not paraphrase it. Do not add text after it.
If no echo block is provided, do not invent one.

CTA PLACEMENT:
If a cta block is provided, it must appear BEFORE the echo block, not after it.
Do not add a CTA if none is provided.

FORMATTING — PARAGRAPH SPACING:
Put a blank line between paragraphs. Keep paragraphs short enough to read on a
phone — roughly 2-4 sentences for long, reading, and medium formats. For instagram,
one sentence per paragraph with explicit blank lines. For short, a single unbroken block.

Never invent evidence, statistics, or business facts not present in the blocks provided.

Return ONLY valid JSON:
{"body": "string - the assembled body text for this format"}"""


def _compose_one(structured_article: dict, format_key: str) -> dict:
    model = model_article() if format_key in ("long", "reading") else model_social()
    user = _build_user_prompt(structured_article, format_key)

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Platform Composer ({format_key}) returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    body = data.get("body", "")
    if not isinstance(body, str) or not body.strip():
        raise ValueError(f"Platform Composer ({format_key}): body missing or empty")
    body = body.strip()

    word_count = len(body.split())
    lo, hi = _WORD_RANGE[format_key]
    # Soft tolerance: 40% either side. LLM word counts are approximate.
    if not (lo * 0.6 <= word_count <= hi * 1.4):
        log.warning(
            "Platform Composer (%s): word_count=%d outside expected %d-%d range",
            format_key, word_count, lo, hi,
        )

    # Echo safety-net: if an echo was produced and is missing from the body, append it.
    echo = (
        structured_article.get("echo_line")
        or structured_article.get("signature")
        or ""
    )
    if echo and echo not in body:
        log.warning("Platform Composer (%s): echo missing from body, appending", format_key)
        body = f"{body}\n\n{echo}"
        word_count = len(body.split())

    return {"word_count": word_count, "body": body}


def compose_platforms(structured_article: dict) -> dict:
    """
    Produce all five platform formats from one structured_article.

    Raises ValueError if any single format's LLM call returns an empty body.
    """
    result = {}
    for format_key in ("long", "reading", "medium", "instagram", "short"):
        result[format_key] = _compose_one(structured_article, format_key)
        log.info(
            "Platform Composer: %s -> %d words", format_key, result[format_key]["word_count"],
        )
    return result
