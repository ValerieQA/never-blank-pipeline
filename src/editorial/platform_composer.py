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
#
# 1.1 (#221): the instruction no longer tells the model to avoid the article's
# opening sentence. Sentence-level overlap between Never Blank surfaces — every
# surface, not only Wix and LinkedIn — is a product decision, so a shared hook,
# sentence or Echo is permitted rather than prohibited. That is a real change in
# what the composer is asked to produce, and therefore a new version on every
# record written from here on.
LINKEDIN_COMPOSITION_RULES_VERSION = "linkedin-medium-native/1.1"

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
        "Write conversationally for Facebook. Use a human owner scenario and one "
        "complete mechanism. Compose for this surface rather than trimming another "
        "channel's body; a shared opening line or Echo is allowed."
    ),
    "medium": (
        "Write a native LinkedIn post, not a shortened blog: compose it for the feed "
        "rather than trimming the article down to length. It MAY open with the "
        "article's own hook — a strong opening is worth repeating, and a reader who "
        "arrives at the article from this post is helped by recognising it. "
        "Use short paragraphs of one to three sentences. One corporate example "
        "maximum. Stay within the target length; LinkedIn readers scan."
    ),
    "instagram": (
        "Make the reader feel a specific owner situation before explaining it. No research diary, "
        "no stacked evidence, no company-led opening. One sentence per paragraph."
    ),
    "short": (
        "Express one native short-form thought. Do not summarize the article; "
        "this surface carries a single idea, not a digest of the whole piece. "
        "A line that also appears elsewhere is fine if it is the right line here."
    ),
}

_SYSTEM_PROMPT = """You are the Platform Composer for Never Blank.

The small-business owner is the central character. Write a fresh native body for the requested
format from structured semantic fields. Compose for the format rather than trimming another
platform's body down to size; individual lines — a strong hook, the Echo — may recur across
formats.

The article's structure is the client's, not the Composer's: when the editorial role carries
client lenses, they are the client's own rules for this article — follow them.
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

#: List markers a Sources entry may legitimately carry.
_LIST_MARKER = re.compile(r"^\s{0,3}(?:[-*\u2022]|\d+[.)])\s*")


#: Prompt vocabulary, not published contract: a citation may carry these
#: labels or omit them. Live run 32656064741 wrote the values without them.
_FIELD_LABELS = ("publisher:", "title:", "url:")

#: Anything that still reads as a word after a record's values are removed.
_WORD = re.compile(r"[^\W_]", re.UNICODE)


def _cites_one_source_record(line: str, record: "tuple[str, ...]") -> bool:
    """Does this line render exactly this one source record, and nothing more?

    Two halves, both required:

    - **presence** — every citable value of THIS record appears in the line;
    - **residue** — with those values (and the optional field labels) removed,
      nothing but separators and punctuation is left.

    Presence alone would bless "Never Blank uses AI to drive Growth." for a
    record whose publisher is "AI"; residue alone would bless a bare
    separator. Together they establish that the line *is* this citation
    rather than prose that mentions part of it — and because the values are
    grouped per record, a line mixing two sources satisfies neither.

    Rendering is free: "Publisher · Title · URL", "Publisher — Title (URL)"
    and the labelled prompt form all pass. Deterministic, case-insensitive,
    no judgment about meaning, no model call.
    """
    if not record:
        return False
    text = _LIST_MARKER.sub("", line)
    lowered = text.casefold()
    if not all(value.casefold() in lowered for value in record):
        return False
    # longest first, so a title containing the publisher cannot strand it
    for value in sorted(record, key=len, reverse=True):
        lowered = lowered.replace(value.casefold(), " ")
    for label in _FIELD_LABELS:
        lowered = lowered.replace(label, " ")
    return _WORD.search(lowered) is None


def _is_canonical_source_entry(
    line: str, records: "tuple[tuple[str, ...], ...]"
) -> bool:
    """Is this line a citation of one of the run's own sources?"""
    return any(_cites_one_source_record(line, record) for record in records)


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
    source_identities: "tuple[tuple[str, ...], ...]" = (),
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
        if not _is_canonical_source_entry(entry, source_identities):
            raise CompositionRejected(
                f"Platform Composer ({format_key}): every line after the "
                "Sources heading must cite one of this run's sources — all "
                "of that source's publisher, title and URL, and nothing "
                "else. The Never Blank Echo is the article's last editorial "
                "word",
                format_key=format_key, body=body,
            )


def _effective_echo_mode(format_key: str, closing_contract: str) -> "str | None":
    """The echo mode this composition actually runs under (#196).

    The ``_BLOCK_TABLE`` value is the format's default. A role that declares
    the branded-echo closing contract has declared that its Echo IS the
    publisher's perspective — one canonical Echo that travels verbatim into
    every derivative it composes. Under that contract a format whose default
    is ``adapt`` is upgraded to ``verbatim_final``: the exact Echo, as the
    attributed block, as the literal end of the composed body.

    Deliberately contract-scoped, not table-scoped: roles that declare
    nothing keep every format's default, so no other stream moves.
    """
    mode = _BLOCK_TABLE[format_key].get("echo")
    if mode == "adapt" and closing_contract == CLOSING_BRANDED_ECHO_THEN_SOURCES:
        return "verbatim_final"
    return mode


def _validate_branded_echo_final(body: str, echo: str, format_key: str) -> None:
    """Prove a social derivative ends at the exact canonical Echo (#196).

    Three obligations: the Echo appears verbatim exactly once; it is rendered
    as the publisher's attribution block; and it is the literal last line of
    the composed body. Everything that follows it on the published surface —
    the canonical article link, hashtags — is appended deterministically by
    the system, never composed, which is what keeps the Echo the last
    *editorial* word while the assembled post still carries its link.
    """
    if body.count(echo) != 1:
        raise CompositionRejected(
            f"Platform Composer ({format_key}): the canonical Echo must "
            "appear verbatim exactly once",
            format_key=format_key, body=body,
        )
    index = _attributed_echo_line(body, echo)
    if index is None:
        raise CompositionRejected(
            f"Platform Composer ({format_key}): the Echo must be the Never "
            f"Blank attribution block — a line reading "
            f"'{BRAND_ATTRIBUTION}: <echo>'",
            format_key=format_key, body=body,
        )
    trailing = [ln for ln in body.splitlines()[index + 1:] if ln.strip()]
    if trailing:
        raise CompositionRejected(
            f"Platform Composer ({format_key}): nothing may follow the Never "
            "Blank Echo in the composed body — the link and hashtags are "
            "appended by the system, never composed",
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
    canonical_body: str | None = None,
) -> str:
    lo, hi = _WORD_RANGE[format_key]
    lines = [
        f"FORMAT: {format_key}",
        f"TARGET LENGTH: {lo}-{hi} words",
        *(() if canonical_body else (
            f"NARRATIVE SPINE (context, do not quote automatically): {structured_article.get('narrative_spine', '')}",
        )),
        f"FORMAT RULES: {_FORMAT_CONSTRAINTS[format_key]}",
        f"CTA MODE: {cta_mode}",
        "",
        "REQUIRED ELEMENTS:" if canonical_body else "STRUCTURED FIELDS:",
    ]
    if canonical_body:
        # #197: this composition is a DERIVATIVE of already-accepted
        # long-form content. The final content is the only source: the
        # pre-review outline is not supplied at all (see the block loop).
        lines[:0] = [
            "FINAL CANONICAL CONTENT — the accepted long-form this "
            "composition must derive from. Its facts, framing and single "
            "mechanism are authoritative: never introduce a claim that is "
            "not supported by it, and use nothing that is not in it. Write "
            "this format's "
            "prose as your own derivative of that content rather than "
            "reproducing the long-form wholesale — a body that is simply "
            "the article trimmed to length is rejected. Individual "
            "sentences MAY recur where they earn it: the hook and the Echo "
            "in particular are meant to travel between surfaces. "
            "This rule governs ORDINARY PROSE ONLY: any element an instruction below "
            "requires to appear verbatim (the ECHO MODE line, for example) "
            "must still be reproduced exactly as supplied, even when the "
            "same wording also appears in the content above. Those "
            "requirements are exceptions to this one, never conflicts with "
            "it.",
            "",
            canonical_body,
            "",
        ]
    if strategy_rules:
        lines.extend(
            ["", "CONFIGURED CHANNEL RULES:"]
            + [f"- {rule}" for rule in strategy_rules]
            + [""]
        )
    for block, mode in _BLOCK_TABLE[format_key].items():
        # A derivative of final accepted content sees NONE of the pre-review
        # outline: its narrative fields predate Editorial Acceptance, and a
        # claim the reviewer removed from the article must not reach a
        # social surface through them (controlled live run 35383199073: the
        # reviewer removed "total engagement numbers drop" from the article;
        # the pre-review Threads and Telegram texts still carried it).
        # Only the element a contract requires verbatim still travels — the
        # Echo, supplied by the caller from the ACCEPTED article. Not even the
        # draft's CTA line: a CTA the article carries after revision is in
        # the canonical content itself (#259 review).
        if canonical_body and block != "echo":
            continue
        content = _block_content(structured_article, block)
        if mode == "skip" or not content:
            continue
        if block == "cta" and (not cta_mode or cta_mode == "none"):
            continue
        if block == "echo":
            # the ECHO MODE instruction below is authoritative; the label
            # here must not contradict it (#196)
            mode = _effective_echo_mode(format_key, closing_contract)
        lines.append(f"- {block} [{mode}]: {content}")

    echo_mode = _effective_echo_mode(format_key, closing_contract)
    if _block_content(structured_article, "echo"):
        if echo_mode == "full" and closing_contract == CLOSING_BRANDED_ECHO_THEN_SOURCES:
            lines.append(
                "ECHO MODE: verbatim, as the Never Blank perspective. Put the "
                f"supplied echo exactly once, on its own line, as "
                f"'**{BRAND_ATTRIBUTION}:** <echo>'. It is the last editorial "
                "word: no commentary, no invitation and no call to action after "
                "it. Only the required Sources section may follow, and every "
                "line in it must be one of the supplied SOURCES OF RECORD "
                "lines, copied exactly as given — never add a publisher or "
                "any other value the supplied line does not contain."
            )
        elif echo_mode == "verbatim_final":
            # #196: a social derivative of the branded contract carries the
            # exact same Echo as the canonical article — the one canonical
            # Echo travels; the lens never rewrites it.
            lines.append(
                "ECHO MODE: verbatim, as the Never Blank perspective — the "
                "EXACT supplied echo, word for word, never adapted or "
                "rephrased. Put it exactly once, as the final line, rendered "
                f"'{BRAND_ATTRIBUTION}: <echo>'. It is the post's last word: "
                "write nothing after it — no sources section, no link, no "
                "invitation, no hashtags (the system appends what follows). "
                "Do not write any URL anywhere in the post."
            )
        elif echo_mode == "full":
            lines.append("ECHO MODE: verbatim; include the supplied echo exactly once at the end.")
        elif echo_mode == "adapt":
            lines.append("ECHO MODE: adapt semantically; include one adapted closing line only.")
    else:
        lines.append("ECHO MODE: none; do not invent an echo.")

    lines.append(
        "Write the native platform body now. Compose it for this format rather "
        "than pasting another format's body; a line that belongs on this surface "
        "— the hook, the Echo — may be the same line another format uses."
    )
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
    source_identities: "tuple[tuple[str, ...], ...]" = (),
    canonical_body: "str | None" = None,
) -> dict:
    model = model_article() if format_key in ("long", "reading") else model_social()
    raw = chat(
        system=_SYSTEM_PROMPT,
        user=_build_user_prompt(
            structured_article, format_key, cta_mode, strategy_rules,
            editorial_role_rules=editorial_role_rules,
            closing_contract=closing_contract,
            canonical_body=canonical_body,
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
    echo_mode = _effective_echo_mode(format_key, closing_contract)
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
    elif echo and echo_mode == "verbatim_final":
        # #196: the social derivative carries the article's exact Echo and
        # ends at it — proven structurally, never trusted to the prompt.
        _validate_branded_echo_final(body, echo, format_key)
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
    source_identities: "tuple[tuple[str, ...], ...]" = (),
    canonical_body: "str | None" = None,
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
            # #197: when set, this composition derives from already-accepted
            # final long-form content (post-revision re-composition) rather
            # than from the structured outline alone.
            canonical_body=canonical_body,
        )
        log.info("Platform Composer: %s -> %d words", format_key, result[format_key]["word_count"])
    return result
