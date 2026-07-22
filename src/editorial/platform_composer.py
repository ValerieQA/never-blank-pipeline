"""Platform Composer — converts one structured article into native platform bodies.

It receives structured fields, not a finished article to trim. Blog/LinkedIn preserve the
approved Echo verbatim. Other formats may adapt its meaning, and the composer never appends
an original Echo behind an adapted one.
"""

import json

from src.content.output_guard import validate_platform_output
from src.utils.llm_client import chat, model_article, model_social
from src.utils.logger import get_logger

log = get_logger("editorial.platform_composer")

_BLOCK_TABLE = {
    "long": {
        "hook": "full", "reader_context": "full", "observation": "full",
        "recognition": "full", "evidence_pattern": "full", "explanation": "full",
        "reframe": "full", "business_meaning": "full", "cta": "full", "echo": "full",
    },
    "reading": {
        "hook": "full", "reader_context": "skip", "observation": "full",
        "recognition": "full", "evidence_pattern": "compressed", "explanation": "full",
        "reframe": "compressed", "business_meaning": "compressed", "cta": "full", "echo": "full",
    },
    "medium": {
        "hook": "compressed", "reader_context": "skip", "observation": "compressed",
        "recognition": "compressed", "evidence_pattern": "skip", "explanation": "compressed",
        "reframe": "compressed", "business_meaning": "compressed", "cta": "compressed", "echo": "adapt",
    },
    "instagram": {
        "hook": "compressed", "reader_context": "skip", "observation": "compressed",
        "recognition": "full", "evidence_pattern": "skip", "explanation": "skip",
        "reframe": "compressed", "business_meaning": "skip", "cta": "compressed", "echo": "adapt",
    },
    "short": {
        "hook": "compressed", "reader_context": "skip", "observation": "skip",
        "recognition": "skip", "evidence_pattern": "skip", "explanation": "skip",
        "reframe": "skip", "business_meaning": "skip", "cta": "skip", "echo": "adapt",
    },
}

_WORD_RANGE = {
    "long": (700, 1000), "reading": (350, 600), "medium": (120, 220),
    "instagram": (80, 150), "short": (20, 80),
}

_PLATFORM_NAMES = {
    "long": "blog", "reading": "linkedin", "medium": "facebook",
    "instagram": "instagram", "short": "short",
}

_FORMAT_CONSTRAINTS = {
    "long": (
        "Develop the full owner-centered argument. Corporate evidence, if present, may occupy at most "
        "20 percent of the body. The article must remain coherent without the company example."
    ),
    "reading": (
        "Write a native LinkedIn post, not a shortened blog. Begin with the owner's recognizable "
        "situation. Use short paragraphs. One corporate example maximum."
    ),
    "medium": (
        "Write conversationally for Facebook. Use a human owner scenario and one complete mechanism. "
        "Do not reuse the Blog or LinkedIn opening sentence."
    ),
    "instagram": (
        "Make the reader feel a specific owner situation before explaining it. No research diary, "
        "no stacked evidence, no company-led opening. One sentence per paragraph."
    ),
    "short": (
        "Express one native short-form thought. Do not summarize the article and do not reproduce "
        "a paragraph from another platform."
    ),
}

_SYSTEM_PROMPT = """You are the Platform Composer for Never Blank.

The small-business owner is the central character. Write a fresh native body for the requested
format from structured semantic fields. Do not trim or paraphrase another platform's prose.

Article arc (production): Hook → Recognition → Tension → Market Observation → Investigation →
Mechanism → Business Consequence → Reframe → Compound Presence Connection → Echo → Soft CTA.
The Compound Presence Connection links the mechanism to the cumulative effect of consistent
presence. It may be woven into Reframe or the transition to Echo — it is not a required
standalone paragraph, but it must be semantically present.

Never use the recurring detective template: "I figured", "I went looking", "I expected",
"But then I found", "That's when I realized", "So I checked". Do not narrate research actions.

Corporate cases are supporting evidence only. Never begin with a company, news headline, source,
or dictionary-style description of what a business is.

CTA and Echo:
- CTA appears only when a CTA field is provided and must come before Echo.
- For verbatim Echo mode, place the supplied Echo exactly once at the very end.
- For adapted Echo mode, write one platform-native closing line preserving the core meaning.
  Do not also include the original wording.
- If no Echo is provided, do not invent one.

Return ONLY valid JSON:
{"body": "string", "echo_included": true|false}
"""


def _block_content(structured_article: dict, block: str):
    discovery = structured_article.get("discovery", {})
    evidence = [discovery.get("puzzle", "")] + list(discovery.get("investigation_sequence", []) or [])
    evidence = " ".join(item for item in evidence if item).strip()
    mapping = {
        "hook": structured_article.get("hook", ""),
        "reader_context": structured_article.get("reader_context"),
        "observation": discovery.get("first_wrong_explanation", ""),
        "recognition": discovery.get("aha_setup", ""),
        "evidence_pattern": evidence or None,
        "explanation": structured_article.get("surviving_explanation", ""),
        "reframe": structured_article.get("reframe", ""),
        "business_meaning": structured_article.get("business_translation", ""),
        "cta": structured_article.get("cta_line"),
        "echo": structured_article.get("echo_line") or structured_article.get("signature") or None,
    }
    return mapping.get(block)


def _build_user_prompt(structured_article: dict, format_key: str, cta_mode: str) -> str:
    lo, hi = _WORD_RANGE[format_key]
    lines = [
        f"FORMAT: {format_key}",
        f"TARGET LENGTH: {lo}-{hi} words",
        f"NARRATIVE SPINE (context, do not quote automatically): {structured_article.get('narrative_spine', '')}",
        f"FORMAT RULES: {_FORMAT_CONSTRAINTS[format_key]}",
        f"CTA MODE: {cta_mode}",
        "",
        "STRUCTURED FIELDS:",
    ]
    for block, mode in _BLOCK_TABLE[format_key].items():
        content = _block_content(structured_article, block)
        if mode == "skip" or not content:
            continue
        if block == "cta" and (not cta_mode or cta_mode == "none"):
            continue
        lines.append(f"- {block} [{mode}]: {content}")

    echo_mode = _BLOCK_TABLE[format_key].get("echo")
    if _block_content(structured_article, "echo"):
        if echo_mode == "full":
            lines.append("ECHO MODE: verbatim; include the supplied echo exactly once at the end.")
        elif echo_mode == "adapt":
            lines.append("ECHO MODE: adapt semantically; include one adapted closing line only.")
    else:
        lines.append("ECHO MODE: none; do not invent an echo.")

    lines.append("Write the native platform body now. Do not copy sentences from another format.")
    return "\n".join(lines)


def _compose_one(structured_article: dict, format_key: str, cta_mode: str = "none") -> dict:
    model = model_article() if format_key in ("long", "reading") else model_social()
    raw = chat(
        system=_SYSTEM_PROMPT,
        user=_build_user_prompt(structured_article, format_key, cta_mode),
        json_mode=True,
        model=model,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Platform Composer ({format_key}) returned invalid JSON: {exc}") from exc

    body = data.get("body", "")
    if not isinstance(body, str) or not body.strip():
        raise ValueError(f"Platform Composer ({format_key}): body missing or empty")
    body = body.strip()

    echo = _block_content(structured_article, "echo")
    echo_mode = _BLOCK_TABLE[format_key].get("echo")
    echo_included = bool(data.get("echo_included"))
    if echo and echo_mode == "full":
        if body.count(echo) != 1 or not body.endswith(echo):
            raise ValueError(f"Platform Composer ({format_key}): verbatim Echo must appear exactly once at end")
    elif echo and echo_mode == "adapt" and not echo_included:
        raise ValueError(f"Platform Composer ({format_key}): adapted Echo missing")

    validate_platform_output(_PLATFORM_NAMES[format_key], body)
    word_count = len(body.split())
    lo, hi = _WORD_RANGE[format_key]
    if not (lo * 0.6 <= word_count <= hi * 1.4):
        log.warning("Platform Composer (%s): word_count=%d outside %d-%d", format_key, word_count, lo, hi)
    return {"word_count": word_count, "body": body, "echo_included": echo_included}


def compose_platforms(structured_article: dict, cta_mode: str = "none") -> dict:
    result = {}
    for format_key in ("long", "reading", "medium", "instagram", "short"):
        result[format_key] = _compose_one(structured_article, format_key, cta_mode=cta_mode)
        log.info("Platform Composer: %s -> %d words", format_key, result[format_key]["word_count"])
    return result
