"""Platform Composer — converts one structured article into native platform bodies.

It receives structured fields, not a finished article to trim. Blog/LinkedIn preserve the
approved Echo verbatim. Other formats may adapt its meaning, and the composer never appends
an original Echo behind an adapted one.
"""

import json
import re
from typing import TYPE_CHECKING

from src.content.output_guard import validate_platform_output
from src.utils.llm_client import chat, model_article, model_social
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.strategy.execution_context import LinkedInStrategyView, WixStrategyView

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

# Release 1 product decision: the website article is one idea, not an anthology.
# 400-600 keeps it within roughly 2x the LinkedIn artifact, so the two read as
# the same thought at two lengths instead of two different products.
_WORD_RANGE = {
    "long": (400, 600), "reading": (350, 600), "medium": (120, 220),
    "instagram": (80, 150), "short": (20, 80),
}

# Platform identities for output validation. Canonical Release 1 (Issue #93):
# ``medium`` is the LinkedIn artifact the orchestrator publishes; ``reading``
# is the non-R1 Facebook long-form.
_PLATFORM_NAMES = {
    "long": "blog", "reading": "facebook", "medium": "linkedin",
    "instagram": "instagram", "short": "short",
}

# Version of the LinkedIn-native composition instruction and rule wiring for
# the canonical ``medium`` artifact. Recorded in every LinkedIn composition
# record; bump in a reviewed commit when composition semantics change.
LINKEDIN_COMPOSITION_RULES_VERSION = "linkedin-medium-native/1.0"

_FORMAT_CONSTRAINTS = {
    "long": (
        "Develop ONE central owner-centered idea with ONE primary mechanism or reframe. If the "
        "material suggests several arguments, choose the strongest and leave the rest for other "
        "articles. Never write a list of lessons, takeaways, or tips. Corporate evidence, if "
        "present, may occupy at most 20 percent of the body, and the article must remain coherent "
        "without the company example. Open with an H1 that gives a real reason to read — tension, "
        "contradiction, or business consequence — without manufactured drama."
    ),
    # Canonical Release 1 mapping (Issue #93): ``medium`` IS the LinkedIn
    # artifact consumed by the orchestrator; ``reading`` is the non-R1
    # Facebook long-form. Format keys stay stable; only channel semantics
    # were realigned to the authoritative consumer.
    "reading": (
        "Write conversationally for Facebook. Use a human owner scenario and one complete "
        "mechanism. Do not reuse the Blog or LinkedIn opening sentence."
    ),
    "medium": (
        "Write a native LinkedIn post, not a shortened blog. Begin with the owner's "
        "recognizable situation, never with the Blog opening sentence. Use short paragraphs "
        "of one to three sentences. One corporate example maximum. Stay within the target "
        "length; LinkedIn readers scan."
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
Mechanism → Business Consequence → Reframe → Echo → Soft CTA.
The mechanism is whichever one the evidence for this run most strongly supports —
pricing, capacity, supply, regulation, distribution, operations, customer behaviour, a
founder decision, communication, presence, or another supported mechanism. Do not
substitute a house thesis for what the material actually shows; the configured editorial
role decides what this article argues.

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

For the blog format, also return "title": the article's own H1 — the hook, not a
description of the subject, and not the source headline you were given as context.
Other formats return "title": null.

Return ONLY valid JSON:
{"body": "string", "echo_included": true|false, "title": "string or null"}
"""


#: Every format the composer knows how to write. Future channels re-enable
#: by passing their formats to compose_platforms — the tables stay complete.
ALL_FORMATS = ("long", "reading", "medium", "instagram", "short")

#: How a role's long-form surface closes (#191). "invitation_last" is every
#: role's existing contract: the verbatim Echo ends the body. A role may
#: instead declare "branded_echo_then_sources": the Echo IS the publisher's
#: perspective, rendered as an attributed block, with the required Sources
#: section after it. Role-scoped, so no other role's validated shape moves.
class CompositionRejected(ValueError):
    """A composition our own validator refused, carrying what was written.

    A ValueError so the existing single-retry seam still treats it as a
    retryable stage failure (#170/#171 semantics unchanged); the attached
    body exists so the rejection can be diagnosed without paying for another
    run (#191). Contains generated text only — never provider transport data.
    """

    def __init__(self, message: str, *, format_key: str, body: str) -> None:
        super().__init__(message)
        self.format_key = format_key
        self.body = body
        self.validation_error = message


CLOSING_INVITATION_LAST = "invitation_last"
CLOSING_BRANDED_ECHO_THEN_SOURCES = "branded_echo_then_sources"

#: The visible brand attribution. Matches formatting._SIGNATURE_PREFIX so the
#: publisher-layer bolding finds the same line on every surface.
BRAND_ATTRIBUTION = "Never Blank"

#: A Sources section is the only thing permitted after the branded Echo.
_SOURCES_HEADING = re.compile(r"^\s{0,3}(#{1,6}\s*)?sources\b\s*:?\s*$",
                              re.IGNORECASE)

def _cites_a_known_source(line: str, identities: "tuple[str, ...]") -> bool:
    """Does this line actually name one of the run's own sources?

    Identity match, not grammar: a bullet proves nothing, because
    "- Visit us today!" is as well-formed a list item as a citation. The run
    already knows its citable identities — each source's URL, publisher and
    title — and the prompt instructs the model to quote them exactly, so a
    real Sources entry contains one and a call to action contains none.

    Deterministic and case-insensitive. No judgment about what prose means,
    and no model call.
    """
    haystack = line.casefold()
    return any(identity.casefold() in haystack for identity in identities if identity)


def _attributed_echo_line(body: str, echo: str) -> "int | None":
    """Index of the line carrying '[**]Never Blank[**]: <echo>', or None.

    Bold markers are optional so the same contract holds for the markdown
    (Wix) and plain-text (social) renderings.
    """
    target = echo.strip()
    for index, line in enumerate(body.splitlines()):
        stripped = line.strip()
        if not stripped.endswith(target):
            continue
        prefix = stripped[: len(stripped) - len(target)]
        normalized = prefix.replace("*", "").strip()
        if normalized.rstrip(":").strip().casefold() == BRAND_ATTRIBUTION.casefold():
            return index
    return None


def _validate_branded_echo_then_sources(
    body: str, echo: str, format_key: str,
    source_identities: "tuple[str, ...]" = (),
) -> None:
    """Prove the branded-echo closing shape deterministically (#191).

    Four obligations, each a separate failure so the evidence names the
    cause: the Echo appears exactly once; it sits inside the publisher's
    attribution block; any Sources section comes after it, never before;
    and only a Sources section may follow it — which is
    also what proves no second perspective, invitation or call to action was
    appended after the branded moment. The engine stays generic: it never
    names a destination, only the shape.
    """
    if body.count(echo) != 1:
        raise CompositionRejected(
            f"Platform Composer ({format_key}): Echo must appear exactly once",
            format_key=format_key, body=body,
        )
    index = _attributed_echo_line(body, echo)
    if index is None:
        raise CompositionRejected(
            f"Platform Composer ({format_key}): Echo must be the Never Blank "
            f"attribution block — a line reading '{BRAND_ATTRIBUTION}: <echo>'",
            format_key=format_key, body=body,
        )
    lines = body.splitlines()
    for earlier in lines[:index]:
        if _SOURCES_HEADING.match(earlier.strip()):
            raise CompositionRejected(
                f"Platform Composer ({format_key}): the Sources section must "
                "follow the Echo, not precede it",
                format_key=format_key, body=body,
            )
    trailing = [ln.strip() for ln in lines[index + 1:] if ln.strip()]
    if not trailing:
        # Nothing after the Echo is a structurally valid ending. Whether the
        # article carries the attribution its role requires is not this
        # validator's question: validate_source_transparency owns it, sees
        # the run's real sources, and fails the run closed before any
        # publisher. Duplicating it here would be a second, weaker authority.
        return
    if not _SOURCES_HEADING.match(trailing[0]):
        raise CompositionRejected(
            f"Platform Composer ({format_key}): only a Sources section may "
            "follow the Never Blank Echo",
            format_key=format_key, body=body,
        )
    for entry in trailing[1:]:
        if not _cites_a_known_source(entry, source_identities):
            raise CompositionRejected(
                f"Platform Composer ({format_key}): every line after the "
                "Sources heading must name one of this run's sources — the "
                "Never Blank Echo is the article's last editorial word",
                format_key=format_key, body=body,
            )


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


def _build_user_prompt(
    structured_article: dict,
    format_key: str,
    cta_mode: str,
    strategy_rules: tuple[str, ...] = (),
    editorial_role_rules: str | None = None,
    closing_contract: str = CLOSING_INVITATION_LAST,
) -> str:
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
    if strategy_rules:
        lines.extend(
            ["", "CONFIGURED CHANNEL RULES:"]
            + [f"- {rule}" for rule in strategy_rules]
            + [""]
        )
    for block, mode in _BLOCK_TABLE[format_key].items():
        content = _block_content(structured_article, block)
        if mode == "skip" or not content:
            continue
        if block == "cta" and (not cta_mode or cta_mode == "none"):
            continue
        lines.append(f"- {block} [{mode}]: {content}")

    echo_mode = _BLOCK_TABLE[format_key].get("echo")
    if _block_content(structured_article, "echo"):
        if echo_mode == "full" and closing_contract == CLOSING_BRANDED_ECHO_THEN_SOURCES:
            lines.append(
                "ECHO MODE: verbatim, as the Never Blank perspective. Put the "
                f"supplied echo exactly once, on its own line, as "
                f"'**{BRAND_ATTRIBUTION}:** <echo>'. It is the last editorial "
                "word: no commentary, no invitation and no call to action after "
                "it. Only the required Sources section may follow."
            )
        elif echo_mode == "full":
            lines.append("ECHO MODE: verbatim; include the supplied echo exactly once at the end.")
        elif echo_mode == "adapt":
            lines.append("ECHO MODE: adapt semantically; include one adapted closing line only.")
    else:
        lines.append("ECHO MODE: none; do not invent an echo.")

    lines.append("Write the native platform body now. Do not copy sentences from another format.")
    if editorial_role_rules:
        # Issue #142: which editorial role this run is producing. The rules are
        # configured by the business, never inferred here from a weekday.
        lines.append(editorial_role_rules)
    return "\n".join(lines)


def _compose_one(
    structured_article: dict,
    format_key: str,
    cta_mode: str = "none",
    strategy_rules: tuple[str, ...] = (),
    editorial_role_rules: str | None = None,
    closing_contract: str = CLOSING_INVITATION_LAST,
    source_identities: "tuple[str, ...]" = (),
) -> dict:
    model = model_article() if format_key in ("long", "reading") else model_social()
    raw = chat(
        system=_SYSTEM_PROMPT,
        user=_build_user_prompt(
            structured_article, format_key, cta_mode, strategy_rules,
            editorial_role_rules=editorial_role_rules,
            closing_contract=closing_contract,
        ),
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
        if closing_contract == CLOSING_BRANDED_ECHO_THEN_SOURCES:
            # #191: for this contract the Echo is the publisher's perspective
            # and the required Sources section follows it. Proven structurally
            # rather than by "the echo is the last characters of the body",
            # which cannot coexist with a mandatory Sources section.
            _validate_branded_echo_then_sources(
                body, echo, format_key, source_identities
            )
        elif body.count(echo) != 1 or not body.endswith(echo):
            raise CompositionRejected(
                f"Platform Composer ({format_key}): verbatim Echo must appear exactly once at end",
                format_key=format_key, body=body,
            )
    elif echo and echo_mode == "adapt" and not echo_included:
        raise ValueError(f"Platform Composer ({format_key}): adapted Echo missing")

    validate_platform_output(_PLATFORM_NAMES[format_key], body)
    word_count = len(body.split())
    lo, hi = _WORD_RANGE[format_key]
    if not (lo * 0.6 <= word_count <= hi * 1.4):
        log.warning("Platform Composer (%s): word_count=%d outside %d-%d", format_key, word_count, lo, hi)
    # The blog article names itself. Publishing the source headline as the title
    # ships the RSS feed's words instead of the article's own hook; an absent or
    # unusable title falls back to prior behaviour rather than inventing one.
    title = data.get("title")
    title = title.strip() if isinstance(title, str) and title.strip() else None
    return {
        "word_count": word_count, "body": body,
        "echo_included": echo_included, "title": title,
    }


def _wix_rules(view: "WixStrategyView | None") -> tuple[str, ...]:
    if view is None:
        return ()
    rules = view.rules
    return (
        *rules.article_rules,
        *rules.metadata_rules,
        *rules.link_rules,
        *rules.cta_rules,
    )


def _linkedin_rules(view: "LinkedInStrategyView | None") -> tuple[str, ...]:
    if view is None:
        return ()
    rules = view.rules
    return (
        *rules.opening_rules,
        *rules.length_rules,
        *rules.formatting_rules,
        *rules.link_rules,
        *rules.cta_rules,
    )


def compose_platforms(
    structured_article: dict,
    cta_mode: str = "none",
    *,
    wix_strategy: "WixStrategyView | None" = None,
    linkedin_strategy: "LinkedInStrategyView | None" = None,
    editorial_role_rules: "str | dict[str, str] | None" = None,
    formats: "tuple[str, ...] | None" = None,
    closing_contract: str = CLOSING_INVITATION_LAST,
    source_identities: "tuple[str, ...]" = (),
) -> dict:
    """Compose one native body per requested format.

    ``formats=None`` keeps the historical all-formats behaviour for legacy
    callers. The canonical Release 1 entrypoint passes only the formats its
    active surfaces consume (#175): a format that is not requested makes no
    model call and produces no output — execution scope is reduced, the
    format architecture is not.
    """
    result = {}
    for format_key in (ALL_FORMATS if formats is None else formats):
        if format_key not in ALL_FORMATS:
            raise ValueError(f"unknown composer format: {format_key!r}")
        strategy_rules = (
            _wix_rules(wix_strategy)
            if format_key == "long"
            # The canonical R1 orchestrator currently consumes ``medium`` as
            # its LinkedIn artifact. Renaming format keys is outside Task #41.
            else _linkedin_rules(linkedin_strategy)
            if format_key == "medium"
            else ()
        )
        result[format_key] = _compose_one(
            structured_article,
            format_key,
            cta_mode=cta_mode,
            strategy_rules=strategy_rules,
            # The Release 1 published surfaces: the Wix article and the
            # LinkedIn artifact. Other formats keep their prior prompts. A
            # mapping carries per-surface renderings; a plain string applies
            # to both published surfaces unchanged.
            editorial_role_rules=(
                editorial_role_rules.get(format_key)
                if isinstance(editorial_role_rules, dict)
                else (
                    editorial_role_rules if format_key in ("long", "medium") else None
                )
            ),
            closing_contract=closing_contract,
            source_identities=source_identities,
        )
        log.info("Platform Composer: %s -> %d words", format_key, result[format_key]["word_count"])
    return result
