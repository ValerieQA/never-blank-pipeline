---
id: K-DST-FB-02
version: 1
status: approved-rule
tier: 1
evidence_class: PLAT
confidence: high
verified_on: 2026-09-21
review_by: 2026-12-20
approved_by: owner, 2026-09-28
---

# Engagement bait and unrelated hashtag captions are demoted and demonetized

## Statement
Meta's policy demotes and demonetizes posts that solicit engagement for its own
sake — asking for a like, a share, a tag or a comment as the point of the post —
and captions carrying long runs of hashtags unrelated to what the post is about.
Both are treated as attempts to buy distribution rather than to earn it.

## Applies when
destination is facebook

## Influences
- S-10 · `E-14.hashtags` — a caption's tags are about what the post is about.
- S-10 · `E-14.first_line_mechanics` — the opening states the point rather than
  asking for a reaction to it.

## Conflicts
None known. Where the client contract's hashtag policy and this record
disagree, this is tier 1 and wins: a contract may not require what a platform's
hard policy demotes. This record constrains what the tags may say; it states no
policy of its own, so it fixes nothing and competes with nothing.

## Source
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §8, row `K-DST-FB-02` (platform
documentation, platform rule, tier 1).

## Notes
It names `E-14.hashtags` without fixing a value, and that distinction is the
whole of how the two authorities compose: the client's tier-2 rule decides
whether Facebook carries hashtags at all, and this record decides what they may
be about. A record that carries no `[fixes: …]` clause states no value, so it
enters adaptation as a constraint rather than as a competing authority.

It admits a compliant variant — a caption whose tags are about the post
complies — so breaking it is replanned around rather than terminal (V-P04).

Transcribed from the accepted map rather than re-checked against the platform,
so `verified_on` is the day the map was accepted.

## Change log
- v1, 2026-09-29: created from the accepted map §8.6 as the tier-1 half of the
  Facebook pair the map's review split (#363).
