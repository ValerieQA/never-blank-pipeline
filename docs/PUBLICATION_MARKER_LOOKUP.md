# NB-00b evidence map — every pre-publish check consults the authority

Issue #288 (SL-0), on top of NB-00a (#287,
`docs/PUBLICATION_MARKER_AUTHORITY.md`). Requires:
`docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md` §3.6 rules 2
and 6, `06_STEP5_MIGRATION_MAP.md` §1.1.

Each acceptance criterion below is exactly one of `SATISFIED` /
`DEFERRED-LIVE` / `NOT DELIVERED`.

**Nothing in this document is evidence of a real external publication.** Every
proof here is deterministic, with no credential and no network.

## What changed

NB-00a built the authority and wired it into the four publishing paths. It
could still only be reached through those paths' own `PublicationGuard`. The
two checks that decide *before* them answered from somewhere else:

| Check | Answered from, before | Answers from, now |
|---|---|---|
| `find_prior_wix_publication` / `find_prior_linkedin_publication` | `packages_dir/<signal_id>/runs/*/publication_results.json` only — nothing in a fresh CI checkout (§1.1) | the marker store first; this checkout's run directories only when the authority has proven nothing was published |
| `select_eligible_signal.py`, including an explicitly dispatched `--signal-id` | `data/research/published_signal_ids.txt` only — written only when a whole job succeeded | the same list **and** the marker store |

`src/publishing/idempotency.py` is now "has this publication already
happened?", with the authority in front of the evidence reader it used to be:

- `find_prior_publication(destination, *, source_signal_ids, client, store)` —
  the generic lookup, **usable for all six destinations**, keyed
  `(client, destination, sorted source signal IDs)` exactly as the store is.
  Three answers and no fourth: a match (`REUSED`), a `refusal` (`SKIP`), or
  never published.
- `find_prior_wix_publication` / `find_prior_linkedin_publication` — the two
  destination faces of it. They keep their `REUSED` behaviour, and the
  canonical URL is still re-established by asking the provider for the known
  post rather than trusting recorded evidence (#200, `_record_reuse`).
- `signal_publication_state(source_signal_ids)` — the same question at
  signal level, across all six destinations, for selection.

The marker key carries **no article digest** (Step 5 §1.1). Re-pointing the
Wix lookup onto it therefore makes it *stricter*: a rewritten article for the
same signal is the same publication and is not published again. That is the
accepted decision, not a side effect.

The run-directory scan is kept behind the authority, unchanged. It can still
recognise a sequential retry inside one working tree, and it can never
authorize a call — both sources funnel through one `_record_reuse`, so which
one answered cannot change what the run records.

## Acceptance evidence

**1. "Test: a dispatched signal that has a marker is refused."**
`SATISFIED`.
`tests/test_288_marker_lookup.py::test_a_dispatched_signal_that_has_a_marker_is_refused`
— the real canonical entrypoint, dispatched with `--signal-id` at a signal
both destinations already have a marker for, with the real authority and the
real lookups wired in. Neither publisher is reached at all; both channels are
`REUSED` carrying the external IDs the earlier run recorded.
`…::test_an_explicitly_dispatched_signal_with_a_marker_is_refused` proves the
same refusal one stage earlier, in the selector: exit `3`, audit outcome
`already_published`, and no eligibility judgment is even requested.

**2. "Test: unavailable authority → SKIP, no publish call."**
`SATISFIED`.
`tests/test_288_marker_lookup.py::test_an_authority_that_cannot_answer_skips_and_publishes_nothing`
— the store is not in this checkout, `wix` is `SKIPPED` with
`idempotency_authority_unavailable`, and no publisher is called.
`…::test_a_store_that_cannot_answer_is_a_refusal_never_a_clean_no` and
`…::test_a_publication_with_no_source_signal_cannot_be_proven_unpublished`
cover the lookup itself; `…::test_selection_selects_nothing_when_the_authority_cannot_answer`
covers selection, which exits `4` — an unanswerable authority is
infrastructure failure, never a clean "nothing to publish".

**3. "A written result of the LinkedIn digest-mismatch test."**
`SATISFIED` — see below.

**Tests over all six destinations.** `test_an_untouched_key_is_neither_a_match_nor_a_refusal`,
`test_a_marker_is_a_match_for_every_destination` and
`test_an_intent_without_a_marker_is_a_refusal_for_every_destination` are
parametrised over `DESTINATIONS`, which is composed from the release-scope
lists so it cannot drift.

## The LinkedIn digest mismatch: CONFIRMED

Step 5 §1.1 recorded this as `INFERRED from code order; **TO TEST**`:

> **LinkedIn scan probably never matches.** The identity digest is taken from
> the package after `bind_canonical_article_url` has added the link
> (`generate_and_publish.py:3459`, before the scan at `:3556`). The prior
> digest comes from `linkedin_composition.json` without the link
> (`idempotency.py:364-371`).

**Result: CONFIRMED.** Both halves hold, and they are now tested:

1. `test_the_entrypoint_binds_the_canonical_link_before_it_looks_for_a_prior`
   — in the entrypoint's publication section, `bind_canonical_article_url(`
   precedes `find_prior_linkedin_publication(`. The identity the lookup
   receives is therefore built from the enriched body.
2. `test_binding_the_canonical_link_moves_the_accepted_body_digest` — the link
   block is appended unconditionally, so the enriched body and the composed
   body never share a digest. The composition record cannot contain the link:
   the URL does not exist until Wix has published.

So `LinkedInPublicationIdentity.accepted_linkedin_body_digest` and the digest
`_prior_linkedin_body_digest` derives from `linkedin_composition.json` could
never be equal in a real run, and the run-directory LinkedIn scan could never
match. Every existing suite that showed it matching does so through the legacy
harness, which patches `bind_canonical_article_url` to the identity function
(`tests/test_generate_and_publish.py`) — which is exactly why code order alone
had never been caught.

**What it costs now: nothing.** The authority's key does not contain the body
digest, so the lookup matches whether the identity carries the composed body
or the enriched one:
`test_the_linkedin_lookup_matches_although_the_body_digest_moved` asserts both.
The mismatch survives only in the subordinate run-directory reader, where it
can no longer decide anything: that reader is reached only after the authority
has said nothing was published, and it can only ever suppress a call.

Fixing the composed-versus-enriched comparison inside that reader would be a
second, weaker idempotency rule for one destination. It is deliberately not
done here.

## Not delivered

**The research workflow's inline selector.** `NOT DELIVERED`.

`.github/workflows/research_generate_and_publish.yml` auto-selects a signal in
an inline Python heredoc (L62-85) that reads `published_signal_ids.txt` and
nothing else. Teaching it the marker store means editing that workflow file,
and #288 declares no orch-containment entry for it, so this attempt did not
touch it.

Nothing is unsafe as a result, and the gap is an optimization rather than a
hole: a signal that selector picks is checked against the authority at the
entrypoint before any external call (criterion 1 above), so an already
published signal is `REUSED`/`SKIP`ped rather than published twice. What is
missing is only that the workflow would pick that signal in the first place
instead of the next unpublished one. The fix is three lines against
`signal_publication_state`, in a follow-up that declares the workflow path.

## Production safety

Additive, and can only prevent publication. Every new answer is a recorded
`REUSED` or `SKIP` with a sanitized ARP reason; nothing waits for a human, and
no path gained the ability to publish anything it could not publish before.
Selection can now refuse where it used to select, and refuses visibly.
