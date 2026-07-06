"""
Platform Composer — Editorial Engine V2 Module 7
Spec: docs/EDITORIAL_ENGINE_V2.md, Module 7

Structural editor, not a text editor. Receives the structured_article object from
Never Blank Voice and produces five platform-specific bodies, each governed by a
fixed per-block full/compressed/skip table - not by word-count truncation. Word
count is a consequence of reading behavior, not the target.

Invariant across all five formats: narrative_spine, hook, discovery moment, aha
moment, and signature are present in every format (per-block table below - `full`
or `compressed`, never `skip`, for those). Only investigation depth changes.

One LLM call per format: Python decides which blocks are full/compressed/skip and
only passes the blocks that are not skipped into the prompt (skipped blocks are not
given to the LLM at all, so they cannot leak in). The LLM performs the compression
judgment itself - compression is a cognitive operation ("remove sentences that
explain what the previous sentence already showed"), not something Python can do
mechanically.
"""

import json

from src.utils.llm_client import chat, model_article, model_social
from src.utils.logger import get_logger

log = get_logger("editorial.platform_composer")

# block -> ("full" | "compressed" | "skip") per format, from EDITORIAL_ENGINE_V2.md
# "Per-block behavior by format" table.
_BLOCK_TABLE = {
    "long": {
        "hook": "full", "reader_context": "full", "first_wrong_explanation": "full",
        "puzzle": "full", "investigation_sequence": "full", "aha_setup": "full",
        "surviving_explanation": "full", "remaining_uncertainty": "full",
        "business_translation": "full", "signature": "full",
    },
    "reading": {
        "hook": "full", "reader_context": "skip", "first_wrong_explanation": "full",
        "puzzle": "full", "investigation_sequence": "compressed", "aha_setup": "full",
        "surviving_explanation": "compressed", "remaining_uncertainty": "skip",
        "business_translation": "compressed", "signature": "full",
    },
    "medium": {
        "hook": "compressed", "reader_context": "skip", "first_wrong_explanation": "compressed",
        "puzzle": "compressed", "investigation_sequence": "skip", "aha_setup": "compressed",
        "surviving_explanation": "skip", "remaining_uncertainty": "skip",
        "business_translation": "compressed", "signature": "full",
    },
    "instagram": {
        "hook": "compressed", "reader_context": "skip", "first_wrong_explanation": "compressed",
        "puzzle": "compressed", "investigation_sequence": "skip", "aha_setup": "compressed",
        "surviving_explanation": "skip", "remaining_uncertainty": "skip",
        "business_translation": "skip", "signature": "full",
    },
    "short": {
        "hook": "compressed", "reader_context": "skip", "first_wrong_explanation": "skip",
        "puzzle": "skip", "investigation_sequence": "skip", "aha_setup": "skip",
        "surviving_explanation": "skip", "remaining_uncertainty": "skip",
        "business_translation": "skip", "signature": "full",
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
    "long": "Reads at a desk. Wants full evidence, timeline, uncertainty.",
    "reading": "Reads the whole thing. Wants narrative and discovery, not evidence density.",
    "medium": "Reads in a feed. Needs a complete standalone arc: Hook -> Discovery -> Aha -> Lesson -> Signature.",
    "instagram": "Reads on a phone, one screen at a time. Shorter paragraphs, stronger rhythm, one dominant insight. Not a shortened LinkedIn post.",
    "short": "Reads one idea. Hook or Spine only. Does not summarize the investigation.",
}

_FORMAT_CONSTRAINTS = {
    "long": (
        "Full evidence, timeline, and uncertainty. Flowing prose, not a bulleted report."
    ),
    "reading": (
        "Preserve the narrative arc. Remove evidence citations and analytical qualifications "
        "that slow reading pace. A reader should feel the investigation without cataloguing "
        "the evidence. Target: readable in 2-4 minutes without stopping."
    ),
    "medium": (
        "Must be a complete standalone text. A reader who has never heard of the company must "
        "reach the Aha and the Spine without needing the Long version. No dangling references "
        "to evidence not present in this version."
    ),
    "instagram": (
        "The most literary format in the system. Its job is not to explain the investigation - "
        "it is to make the reader feel the moment the first explanation broke. No analysis. No "
        "qualifications. No stacked facts. Only the emotional sequence: something was true, then "
        "one thing changed, then nothing was the same. One idea per paragraph - blank lines are "
        "part of the storytelling. Never name a statistic unless it is the puzzle itself. Never "
        "write a sentence that could appear in a LinkedIn post. The reader should finish thinking "
        "'I just realized something' - not 'I just read an analysis.'"
    ),
    "short": (
        "One idea. Either the Hook that opens the gap, or the Spine that closes it. Does not "
        "attempt to compress the investigation into a summary - that produces a summary, not an "
        "insight."
    ),
}

_COMPRESSION_RULE = (
    "The rule for compressing a block: remove sentences that explain what the previous "
    "sentence already showed. Do not remove sentences that move the reader to the next "
    "cognitive position. Never summarize a block - compress it to its cognitive minimum."
)


def _block_content(structured_article: dict, block: str) -> str | None:
    discovery = structured_article.get("discovery", {})
    mapping = {
        "hook": structured_article.get("hook", ""),
        "reader_context": structured_article.get("reader_context"),
        "first_wrong_explanation": discovery.get("first_wrong_explanation", ""),
        "puzzle": discovery.get("puzzle", ""),
        "investigation_sequence": " ".join(discovery.get("investigation_sequence", [])),
        "aha_setup": discovery.get("aha_setup", ""),
        "surviving_explanation": structured_article.get("surviving_explanation", ""),
        "remaining_uncertainty": structured_article.get("remaining_uncertainty"),
        "business_translation": structured_article.get("business_translation", ""),
        "signature": structured_article.get("signature", ""),
    }
    return mapping.get(block)


def _build_user_prompt(structured_article: dict, format_key: str) -> str:
    table = _BLOCK_TABLE[format_key]
    lo, hi = _WORD_RANGE[format_key]

    lines = [
        f"narrative_spine (identical across all formats - do not alter its meaning): "
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
    lines.append("Assemble the final body text for this format now, in the order the blocks "
                  "are listed above (narrative_spine is context, not a block to include verbatim - "
                  "it must be earned by the piece, not stated).")

    return "\n".join(lines)


_SYSTEM_PROMPT = """You are the Platform Composer for Never Blank.

You are a structural editor, not a text editor: you do not receive an article and
cut sentences. You receive a fixed set of named blocks and assemble them into one
platform's body text, respecting exactly which blocks are full, compressed, or
omitted for this format (given in the user message). Preserve every cognitive step
of the blocks you are given. Compress only exposition.

VOICE — DO NOT FLATTEN INTO ANALYSIS:
The discovery blocks (first_wrong_explanation, puzzle, investigation_sequence,
aha_setup) are written in first person, as a narrator investigating in real time.
Your job is to assemble them, not to translate them into third-person analytical
prose. If a block reads "I assumed X. Then one fact didn't fit," it must still
read that way in the final body - not rewritten into "X initially appeared true,
however evidence suggests otherwise." A version of this piece that reads like an
analyst's memo instead of an investigator's account has failed, even if every
fact is preserved.

DO NOT RESOLVE TOO FAST:
The most common failure is stating the conclusion within the first few sentences
after the hook. surviving_explanation exists to confirm what the reader already
arrived at via aha_setup - it must not appear early, restated, or hedge-free as
if it were the obvious reading all along. If the piece would read the same with
surviving_explanation moved to paragraph two, the discovery arc did not survive
assembly - keep the full investigative distance between the puzzle and the
confirmation.

THE ENDING MUST ECHO THE SPINE, NOT JUST GESTURE AT IT:
narrative_spine is not background context to keep in mind - it is the sentence
the reader must recognize by the end. business_translation and the moment right
before signature should land on language that clearly rhymes with narrative_spine
(reusing its central image or claim, not just a related theme), so a reader who
reaches the end recognizes "that's the sentence this was building to." A
business_translation that is generic enough to paste under a different company's
headline unchanged is a failure - it must depend on the specific narrative_spine
and discovery above it.

Never invent evidence, facts, or claims not present in the blocks provided.
The signature block must appear verbatim (it is always `full`) at the very end.

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
    # Soft tolerance: 40% either side. LLM word counts are approximate; do not
    # hard-fail generation over a length miss, but log so drift is visible.
    if not (lo * 0.6 <= word_count <= hi * 1.4):
        log.warning(
            "Platform Composer (%s): word_count=%d outside expected %d-%d range",
            format_key, word_count, lo, hi,
        )

    signature = structured_article.get("signature", "")
    if signature and signature not in body:
        log.warning("Platform Composer (%s): signature missing from body, appending", format_key)
        body = f"{body}\n\n{signature}"
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
