"""The run's actual sources, rendered for the stages that must cite them (#155).

A role can require a Sources section and still produce an article with none —
because the requirement reaches the prompt before the research does. The rules
say *cite your sources*; nothing ever says *these are your sources*. Live run
32416078767 accepted a good article that named no source at all and was
stopped, correctly, by the source-transparency gate.

This module closes that gap the only honest way: by reading the run's
persisted research artifact and rendering exactly what it contains — title,
publisher, URL, per source — as prompt text the writing and revision stages
can quote. Nothing here invents, guesses, or completes a missing field, so a
model that follows the block cannot fabricate a citation, and a model that
ignores it still meets the same validator as before.

Generic by construction: it knows a research artifact and produces text. The
requirement to *use* it belongs to the role configuration, and roles that do
not require attribution never receive it.
"""

from __future__ import annotations

from src.research.evidence import NormalizedResearchArtifact


def source_records(research: NormalizedResearchArtifact) -> tuple[dict, ...]:
    """The citable identity of each source, exactly as the run recorded it."""

    records = []
    for source in research.sources:
        locator = getattr(source.locator, "value", "") or ""
        record = {"source_id": source.source_id}
        title = (source.title or "").strip()
        publisher = (source.publisher or "").strip()
        if title:
            record["title"] = title
        if publisher:
            record["publisher"] = publisher
        if locator.startswith("http"):
            record["url"] = locator
        records.append(record)
    return tuple(records)


def source_citation_values(
    research: NormalizedResearchArtifact,
) -> tuple[tuple[str, ...], ...]:
    """The citable values of each source, one tuple per record (#193).

    This is what a published citation must carry: the record's publisher,
    title and URL as they exist. The *labels* around them are prompt
    vocabulary, not part of the published contract — live run 32656064741
    proved that requiring them rejects a correct citation.

    Grouped per record so a line combining values from two different sources
    satisfies neither.
    """

    groups = []
    for item in source_records(research):
        values = tuple(
            item[key] for key in ("publisher", "title", "url") if item.get(key)
        )
        if values:
            groups.append(values)
    return tuple(groups)


def canonical_source_entries(
    research: NormalizedResearchArtifact,
) -> tuple[str, ...]:
    """The exact citation text for each citable source, one string each.

    This is the single definition of what a Sources entry *is*: the prompt
    renders these (prefixed with "- ") and instructs the model to quote them
    exactly, and the composer validates the article's Sources section against
    the same strings. Deriving both from one function is what keeps the
    instruction and the check from drifting apart — the #191 defect was two
    rules that could not both be satisfied.

    Each entry is the finished citation line, not a description of one: the
    record's own values joined by " · " in a fixed order — ``publisher · title
    · URL`` when the record has a publisher, ``title · URL`` when it does not.
    Every component is conditional, because ``source_records`` treats a
    source as citable when it carries a URL OR a publisher OR a title, and
    nothing is ever filled in: a record without a publisher yields a line
    without one. Live run 35375812835 showed why the model must be handed the
    line rather than asked to build it — given a publisher-less record and a
    "Publisher · Title · URL" example, it supplied the publisher itself.
    """

    entries = []
    for item in source_records(research):
        parts = [item[key] for key in ("publisher", "title", "url") if item.get(key)]
        if parts:
            entries.append(" · ".join(parts))
    return tuple(entries)


def render_sources_of_record(
    research: NormalizedResearchArtifact, *, surface: str
) -> str:
    """Render the run's sources as deterministic, surface-appropriate text.

    Returns an empty string when the run carries no citable source identity —
    an article cannot be asked to cite what does not exist, and the
    source-transparency gate will stop that run on its own terms rather than
    on invented text.
    """

    records = source_records(research)
    citable = [item for item in records if item.get("url") or item.get("publisher")
               or item.get("title")]
    if not citable:
        return ""

    if surface == "wix":
        lines = [
            "",
            "SOURCES OF RECORD — the only sources this run may cite. Each "
            "line below is the exact citation of one source, built from the "
            "run's own source record. In the Sources section, copy each line "
            "character for character, one line per source; never invent, "
            "guess, complete, or substitute anything in a citation — in "
            "particular never add a publisher, brand or site name the line "
            "does not already contain, whether from the URL, the story or "
            "your own knowledge. A line without a publisher is complete as "
            "it is.",
            "",
        ]
        for entry in canonical_source_entries(research):
            lines.append("- " + entry)
        lines += [
            "",
            "Required: attribute the facts you take from these sources in the "
            "body, and close the article with a short Sources section listing "
            "them. The article is not publishable without it.",
            "",
        ]
        return "\n".join(lines)

    # Social surface (#196): the post distributes the published Never Blank
    # article, and the article owns the external-source links. The post may
    # name the source naturally, but never carries a URL — the canonical
    # article link is appended by the system after publication, and any URL
    # the model wrote would fail the social-lineage gate as a competing
    # destination. Records with no nameable identity (URL only) are omitted:
    # there is nothing they could contribute except the forbidden link.
    nameable = []
    for item in citable:
        parts = [item[key] for key in ("publisher", "title") if item.get(key)]
        if parts:
            nameable.append(" · ".join(parts))
    if not nameable:
        return ""
    lines = [
        "",
        "SOURCES BEHIND THE ARTICLE — the documented sources this story comes "
        "from. You may name the publisher or title naturally in the body when "
        "it helps the reader (for example, 'Entrepreneur profiled a founder "
        "who…'); never invent or substitute one, and never cite anything "
        "else.",
        "",
    ]
    for entry in nameable:
        lines.append("- " + entry)
    lines += [
        "",
        "Never write any URL in the post — not the source's, not the site's. "
        # brand-neutral: this Engine text reaches every client's social
        # surfaces, including the Engine adapters (#259 review)
        "The link to the published canonical article is appended by the "
        "system after publication.",
        "",
    ]
    return "\n".join(lines)
