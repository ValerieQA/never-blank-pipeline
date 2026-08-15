# LinkedIn composition: canonical mapping, traceability, and acceptance

Issue #93 / Story #14. `src.editorial.linkedin_composition` plus the Platform
Composer mapping correction.

## Canonical Release 1 LinkedIn artifact (product-owner decision)

The canonical LinkedIn artifact is the Platform Composer **`medium`** body
with the **120–220-word** target. The orchestrator consumes
`platforms["medium"]` as `linkedin_text`; Release 1 does not use
`platforms["reading"]` for LinkedIn and does not expand the LinkedIn length.
Format keys are unchanged.

## Mapping correction

Inspection (recorded on Issue #92/#93) established that stale semantic layers
disagreed with the canonical consumer: `_PLATFORM_NAMES` labeled `medium` as
`facebook` (and `reading` as `linkedin`), and `_FORMAT_CONSTRAINTS["medium"]`
instructed the model to write for Facebook — so the actually published
LinkedIn body was prompted as a Facebook post. Corrected:

- `_PLATFORM_NAMES`: `medium → "linkedin"`, `reading → "facebook"` — platform
  output validation now runs under the correct `linkedin` identity for the
  published artifact;
- `_FORMAT_CONSTRAINTS["medium"]`: LinkedIn-native instructions (owner-first
  opening never copied from the Blog, short scannable paragraphs, one
  corporate example maximum, target-length discipline);
- `_FORMAT_CONSTRAINTS["reading"]`: the non-R1 Facebook long-form semantics;
- LinkedIn strategy-rule wiring stays on `medium` (unchanged);
- `LINKEDIN_COMPOSITION_RULES_VERSION = "linkedin-medium-native/1.0"` names
  this composition contract and is recorded in every composition record.

## Deterministic channel acceptance

`accept_linkedin_composition()` runs in the canonical entrypoint after
formatting, before `generated.json` and any packaging/publication effect. It
proves, without any model call:

- non-empty composition and non-empty accepted source article;
- not the Wix article verbatim, not its opening, and no shared
  sentence-length prose (`repeated_cross_platform_phrases`);
- word count within the accepted tolerance of the 120–220 target
  (72–308, the Platform Composer's long-standing 0.6×/1.4× envelope);
- platform output validation under the `linkedin` identity.

Failure raises `LinkedInCompositionError`: the run stops before packaging —
no LinkedIn publisher effects, no fallback to `reading` or any other platform
body, no revision loop (Story #13 owns article editorial quality; this
boundary only proves LinkedIn-specific composition of already accepted
content).

## Story #13 seam: truthful lineage across article revision

The LinkedIn `medium` body is composed in the same generation pass as the
original article. When Story #13 editorial acceptance **revises** the article,
the pre-revision LinkedIn body no longer truthfully derives from the final
accepted article — content removed or materially changed by the revision may
survive in it. Release 1 fails closed (`article_revised=True`): a stale
pre-revision LinkedIn body can never become `ACCEPTED` or publishable, and no
record is written whose `source_article_digest` would claim a composition
relationship that did not exist. The run's Story #13 editorial history stays
honestly preserved in `editorial_acceptance.json`; the remedy follows
existing new-run semantics — a fresh run composes every channel from one
accepted content state. Consequence: in Release 1, a run whose article needed
revision publishes nothing until re-run; digests in accepted records always
identify the article state that actually supported the composition.

## Traceability record

On acceptance, one immutable run-scoped `linkedin_composition.json`
(create-once, standard atomic protocol) records: schema version, `run_id`,
`signal_id`, `source_article_digest` (SHA-256 of the accepted article body —
the smallest stable current-run source identity; there is no separate article
artifact ID in Release 1), full `ConfigurationIdentity`, `strategy_id` and
`strategy_version`, `composition_rules_version`, the canonical LinkedIn body,
its word count, and the acceptance status.
`verify_linkedin_composition_record()` fails closed on cross-run,
configuration, or source-article drift.

## Deferred live verification

The Story #14 criterion requiring a current live LinkedIn artifact is
**deferred live verification**: it is collected during the existing
production/live-run work (Story #19 / Story #21) and is not faked here.
