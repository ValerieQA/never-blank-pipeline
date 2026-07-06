"""
Reader Context — Editorial Engine V2 Module 2
Spec: docs/EDITORIAL_ENGINE_V2.md, Module 2

Mandatory one-sentence "what does this company do" line, unless the company is
universally recognizable. The household-name check is deterministic Python - it
does not need an LLM call, and skipping it entirely for household names saves a
call on a meaningful fraction of signals.
"""

import json

from src.utils.llm_client import chat, model_enrich
from src.utils.logger import get_logger

log = get_logger("editorial.reader_context")

# Per spec: "any adult in any country would immediately understand the business
# without explanation." Deliberately short and literal - do not extend casually.
_HOUSEHOLD_NAMES = {
    "apple", "microsoft", "google", "amazon", "meta", "tesla", "toyota", "samsung",
}

_MAX_WORDS = 25

_SYSTEM_PROMPT = """You are the Reader Context module for Never Blank.

First, identify the SUBJECT company: the one whose decision or action the
HEADLINE and CORE_FACT are actually about. Other companies may appear in
CORE_FACT as comparisons or precedents (e.g. "...as Varo and SoFi did before
it") — ignore those. Describe only the subject company.

Write exactly one sentence, 10-20 words, describing only what the subject
company fundamentally does. Format: "[Company] [does what] [for whom / in
what context]."

Rules:
- One sentence. Maximum 20 words.
- Never include analysis, opinion, or anything about the current story.
- Never summarize what happened.
- Never describe a comparison/precedent company instead of the subject.

Examples:
"Polymarket operates a prediction market where users trade on real-world event outcomes."
"Getty Images licenses photographs and video to media companies and advertisers worldwide."
"Lucid Motors builds premium electric vehicles focused on maximum driving range."

Return ONLY valid JSON:
{"context_line": "string"}"""


def _is_household_name(headline: str) -> bool:
    haystack = headline.lower()
    return any(name in haystack for name in _HOUSEHOLD_NAMES)


def build_reader_context(signal: dict) -> str | None:
    """
    Return a one-sentence reader-context line, or None if the company is a
    household name (Reader Context is mandatory otherwise).

    Raises ValueError if the LLM returns something that is not a single short
    sentence.

    Note: the subject company is identified by the LLM from HEADLINE +
    CORE_FACT, not read from REAL_COMPANY_EXAMPLE — that field frequently
    holds a comparison/precedent company (e.g. a signal about Klarna citing
    Varo Money as the first fintech to get a bank charter), not the subject
    of this article. Passing it as "the company" caused Reader Context to
    describe the wrong company in production (2026-07-06 Klarna signal).
    """
    headline = signal.get("HEADLINE", "") or ""

    if _is_household_name(headline):
        log.info("Reader Context: skipped (household name) for %r", headline[:60])
        return None

    user = f"""HEADLINE: {headline}
CORE_FACT: {signal.get('CORE_FACT', '')}

Identify the subject company from the fields above (ignore any comparison or
precedent companies mentioned in CORE_FACT) and produce the Reader Context
JSON."""

    raw = chat(system=_SYSTEM_PROMPT, user=user, json_mode=True, model=model_enrich())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Reader Context returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    context_line = data.get("context_line", "")
    if not isinstance(context_line, str) or not context_line.strip():
        raise ValueError("Reader Context: context_line missing or empty")
    context_line = context_line.strip()

    if "\n" in context_line:
        raise ValueError(f"Reader Context: expected a single sentence, got multiple lines: {context_line!r}")

    word_count = len(context_line.split())
    if word_count > _MAX_WORDS:
        raise ValueError(
            f"Reader Context: line has {word_count} words, expected <= {_MAX_WORDS}: {context_line!r}"
        )

    log.info("Reader Context: %r", context_line)
    return context_line
