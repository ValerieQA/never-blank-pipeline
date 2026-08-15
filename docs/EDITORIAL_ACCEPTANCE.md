# Editorial acceptance and one controlled revision

`src.editorial.editorial_acceptance` owns the Release 1 editorial acceptance
boundary (Issue #89 / Story #13). It answers one business question about the
generated Wix article: **is it good enough that the business should put its
name on it?** A technically valid article is not automatically publishable.

## Release 1 lifecycle

Wired into the canonical entrypoint immediately after article generation and
before any packaging/publication effect:

    generated article → editorial acceptance
    → ACCEPT: continue with the original article
    → REJECT: stop immediately (no automatic revision)
    → REVISE: exactly one controlled revision → one acceptance recheck
        → ACCEPT: continue with the revised article
        → REVISE / REJECT / malformed / failure: stop.

Maximum automatic revisions: **one**. There is no open-ended self-revision
loop, no generalized scoring platform, and no rubric registry.

Story #12 remains authoritative upstream: only a canonical `PROCEED` Decision
Lens run reaches article generation and Story #13 at all. Editorial
acceptance never re-runs or modifies the Decision Lens.

## Versioned rubric

One concise externalized rubric at
`config/prompts/editorial_acceptance/never_blank.yaml`
(`never-blank-editorial-acceptance/1.0`) with nine criteria: evidence-use,
defensible-angle, audience-recognition, insight, narrative-coherence, voice,
unsupported-claims, generic-filler, reader-value. The rubric identity is
recorded in every acceptance record; changing acceptance semantics requires a
version bump in a reviewed commit.

## Typed acceptance result

`EditorialReview` is strict and immutable: rubric ID/version, disposition
(`ACCEPT`/`REVISE`/`REJECT`), failed criterion IDs, bounded rationale, and
bounded revision guidance. Enforced invariants:

- `ACCEPT` cannot carry failed criteria — a reviewer that tries to accept an
  article while naming an unsupported-claims (or any other) failure is
  rejected, fail closed;
- a non-`ACCEPT` verdict must name the failed rubric criteria;
- reviewer output with unknown fields or criteria outside the rubric is
  rejected, not normalized.

`EditorialAcceptanceOutcome` preserves the initial review, the final review
(when a revision occurred), the final article body, and a compact audit
record.

## Evidence boundary

The reviewer judges quality only. The review request carries the accepted
current-run research evidence so grounding can be checked; the reviewer may
flag unsupported claims and require removal or correction, but it never
invents evidence and never manufactures support. The revisor is instructed to
remove or correct unsupported claims, never to pad them with invented
support.

## Controlled revision boundary

Revision is a narrow injectable transport that operates on the canonical Wix
article body **only**:

- receives the article plus explicit failed criteria and revision guidance;
- performs at most one revision;
- returns either a usable revised article or an explicit failure — a failed
  revision never silently continues with the original article;
- never regenerates LinkedIn, Instagram, Facebook, Threads, or Telegram
  content (channel bodies keep their originally generated values; article
  generation runs exactly once per run).

The legacy `src/quality/` subsystem (whose blog rewrite regenerates other
channels and can silently return the original text) is deliberately **not**
wired into the canonical path and is left untouched.

## Failure behavior

Fail closed (`EditorialAcceptanceError`, run stops, zero publication
effects): malformed reviewer output, reviewer transport failure/timeout,
malformed/empty revised article, revision transport failure, missing or
invalid rubric identity. Raw provider output and exception messages never
cross the boundary — failures carry evaluator-authored bounded detail only.

## Audit minimum

For every accepted run, `generated.json` carries an `editorial_acceptance`
record: rubric identity, whether a revision occurred, the full initial
review, and the full final review (null when no revision ran). Blocked runs
print the disposition and failed criteria and persist nothing new — retry
follows existing new-run semantics.

## Production transports and testing

Production uses `LlmChatEditorialReviewTransport` (JSON reviewer) and
`LlmChatArticleRevisionTransport` (article revisor) over the repository LLM
client. Deterministic tests (`tests/test_editorial_acceptance.py`) inject
fake transports through the real `main()` entrypoint via the
`editorial_reviewer`/`article_revisor` seams — the same injection pattern as
`research_provider` and `decision_evaluator`.
