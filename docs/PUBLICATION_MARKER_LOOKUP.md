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
checks that decide *before* them answered from somewhere else:

| Check | Answered from, before | Answers from, now |
|---|---|---|
| `find_prior_wix_publication` / `find_prior_linkedin_publication` | `packages_dir/<signal_id>/runs/*/publication_results.json` only — nothing in a fresh CI checkout (§1.1) | the marker store first; this checkout's run directories only when the authority has proven nothing was published |
| `select_eligible_signal.py`, including an explicitly dispatched `--signal-id` | `data/research/published_signal_ids.txt` only — written only when a whole job succeeded | the same list **and** the marker store |
| the research workflow's signal selection, including an explicitly dispatched `signal_id` | an inline heredoc over `data/research/published_signal_ids.txt` only | `scripts/streams/resolve_research_signal.py` — the same list **and** the marker store |

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

## The research workflow's selector

`SATISFIED`.

`.github/workflows/research_generate_and_publish.yml` used to auto-select a
signal in an inline Python heredoc that read `published_signal_ids.txt` and
nothing else. That file is written only when a whole job succeeded, so a run
that published Wix and then failed LinkedIn left it untouched and the signal
still looked unused — the partial-success hole this issue exists to close.

`scripts/streams/resolve_research_signal.py` replaces the heredoc. It reads
the legacy file **and** asks `signal_publication_state`, so a marker at any
destination — or an intent without one, a call that may have reached the
platform — passes the candidate over. An explicitly dispatched `--signal-id`
takes the same check: naming a signal says which one to consider, not that the
authority may be ignored.

It is deliberately not `select_eligible_signal.py`. Monday's selector runs an
editorial eligibility judgement and spends model calls; the research stream
has always taken the first unused signal, and the only thing that changes here
is which signals count as unused.

**Three outcomes, and the exit code says which.** `0` is a signal the
authority has not spent. `3` is a completed search that found none:
publishing nothing is correct and the run stays green. `4` is the authority
failing to answer, and it fails the run — never read as "nothing was
published", and never converted into a quiet "nothing to publish" either.
That is the same separation `select_eligible_signal.py` makes between
`NO_ELIGIBLE` and `ELIGIBILITY_FAILURE`, and the same contract
`monday_publish.yml` states for its own selector.

**The Generate + Publish step is guarded.** It had no condition on an empty
selection and would have run with `--signal-id ""`. It now requires a resolved
signal, so a refusal publishes nothing rather than reaching the publisher with
an empty argument.

Proven in `tests/test_288_research_selection.py`:

| What | Test |
|---|---|
| a signal the legacy file calls unused is refused when a marker exists | `test_a_signal_the_file_calls_unused_is_refused_when_a_marker_exists` |
| an intent without a marker is passed over too | `test_a_signal_with_an_intent_and_no_marker_is_also_passed_over` |
| a marker at any destination refuses the signal | `test_a_marker_at_any_destination_refuses_the_signal` |
| a dispatched signal does not bypass the authority | `test_a_dispatched_signal_is_still_checked` |
| an unavailable authority fails the run instead of going quiet | `test_an_unavailable_authority_fails_the_run_instead_of_going_quiet` |
| an unavailable authority refuses a dispatched signal too | `test_an_unavailable_authority_refuses_a_dispatched_signal_too` |
| nothing left is a completed search, not a failure | `test_nothing_left_is_a_completed_search_not_a_failure` |
| the workflow resolves through the resolver, not the published file | `test_the_workflow_resolves_through_the_marker_aware_resolver`, `test_the_workflow_no_longer_selects_on_the_published_file_alone` |
| only a completed search keeps the run green | `test_only_a_completed_search_keeps_the_run_green` |
| an empty selection never reaches the publisher | `test_nothing_is_published_when_the_resolver_selected_nothing` |

## Production safety

Additive, and can only prevent publication. Every new answer is a recorded
`REUSED` or `SKIP` with a sanitized ARP reason; nothing waits for a human, and
no path gained the ability to publish anything it could not publish before.
Selection can now refuse where it used to select, and refuses visibly.
