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

    lines = [
        "",
        "SOURCES OF RECORD — the only sources this run may cite. Quote these "
        "exactly; never invent, guess, complete, or substitute a publisher, "
        "title or URL that does not appear here.",
        "",
    ]
    for item in citable:
        parts = []
        if item.get("publisher"):
            parts.append(f"publisher: {item['publisher']}")
        if item.get("title"):
            parts.append(f"title: {item['title']}")
        if item.get("url"):
            parts.append(f"url: {item['url']}")
        lines.append("- " + " · ".join(parts))
    lines.append("")
    if surface == "wix":
        lines.append(
            "Required: attribute the facts you take from these sources in the "
            "body, and close the article with a short Sources section listing "
            "them. The article is not publishable without it."
        )
    else:
        lines.append(
            "Required: name the source case compactly — one clear reference to "
            "the publisher or title above — without turning the post into "
            "citation-heavy prose."
        )
    lines.append("")
    return "\n".join(lines)
