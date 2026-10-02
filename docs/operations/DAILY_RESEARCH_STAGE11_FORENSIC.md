# Daily Signal Research — Stage 11 and the canonical package contract

Issue #231. Anchored against `orch/231` at
`8d4e76fb6794fbca07207c4c8e6ec8c73a40457c`.

**This document changes nothing, and it does not choose between the two
resolutions the issue puts to the owner.** It is the forensic record the issue
asks for: what Stage 11 does today, which of it is checkable from this tree,
and what each resolution would have to touch. `docs/repository-audit/REPOSITORY_AUDIT.md`
closes by stating that "the unresolved product choice in #231 was not made
implicitly"; the same holds here.

## 1 · The finding in one line

Stage 11 of Daily Signal Research is authorized to publish to exactly two
channels, and it is structurally unable to call either of them: it hands the
legacy mutable `DraftPackage` to publishers that accept only the frozen
canonical package, and the adapter reads attributes that object does not have.

## 2 · Two contracts, one call site

| | Stage 11 | The R1 publishers |
|---|---|---|
| What it passes / expects | `DraftPackage`, built in-stage by `_build_draft` (`scripts/research/publish_packages.py:163-193`) | `WixPublicationPackage` (`src/publishing/wix.py:157-162`), `LinkedInPublicationPackage` (`src/publishing/linkedin.py:46-52`) |
| Title field | `blog_title` (`src/publishing/base.py:27`) | `package.title`, read at `src/publishing/base.py:67` |
| LinkedIn body field | `linkedin_text` (`src/publishing/base.py:30`) | `package.linkedin_body`, read at `src/publishing/base.py:96` |
| Authorization behind it | none — no preflight is constructed anywhere in the stage | `evaluate_publication_preflight`, the single publication-authorization boundary (`src/publishing/preflight.py:327-351`) |

`DraftPackage` is `src/publishing/base.py:25-54`; neither `title` nor
`linkedin_body` is among its fields.

The call is `publisher.publish(use_draft, mode)` at
`scripts/research/publish_packages.py:355`. Both publishers immediately derive
their internal representation from the argument —
`DraftPackage.from_wix_package` (`src/publishing/wix.py:171`) and
`from_linkedin_package` (`src/publishing/linkedin.py:59`) — and those
classmethods are total over the *frozen* package only. Given a `DraftPackage`
they raise `AttributeError` before any provider call.

Which two channels Stage 11 is authorized for is not a literal it maintains:
`_PUBLISHERS = restrict_to_release_scope(_ALL_PUBLISHERS)`
(`scripts/research/publish_packages.py:77`) resolves to `("wix", "linkedin")`
from `R1_PUBLISH_CHANNELS` (`src/publishing/release_scope.py:33`). So the set
the stage may drive and the set it cannot drive are the same set, and #227
narrowing the stage to Release 1's own channels is what made that visible
rather than what caused it.

The other four channels already get a stated non-result:
`PublishStatus.SKIPPED`, `"outside the Release 1 publishing scope (#227)"`
(`scripts/research/publish_packages.py:304-311`).

### In-tree evidence of the exact failure

The two Daily Signal Research runs the issue cites (34031888336, 34131034688)
are GitHub run records and are not in this tree. The identical failure shape
*is*, from the visibility publisher (Tue/Thu), which makes the same legacy call
— `publisher.publish(draft, "live")` at
`scripts/generate_and_publish_visibility.py:368` — in
`data/strategy/visibility_history.jsonl:5-6`:

```
"wix":      {"status": "FAILED", "error_message": "'DraftPackage' object has no attribute 'title'"}
"linkedin": {"status": "FAILED", "error_message": "'DraftPackage' object has no attribute 'linkedin_body'"}
```

Both entries (`vis_005`, 2026-08-18; `vis_006`, 2026-08-20) also record
non-R1 channels publishing in the same run — Facebook and Telegram in both,
Threads in `vis_005`: the pre-#227 shape in which the two R1 channels failed
while channels outside Release 1 succeeded.

## 3 · What a live run does, in order

Per authorized channel, with `NB_PUBLISH_MODE=live` (set by
`.github/workflows/daily_signal_research.yml:63`):

1. `PublicationGuard(source_signal_ids=[sig_id], run_id=draft.run_id)`
   (`scripts/research/publish_packages.py:323-327`). `_build_draft` sets no
   `run_id`, so it is `""` (`src/publishing/base.py:53`).
2. `guard.check(name)` (`:334`) — the authority has no marker and no intent for
   this key, so it proceeds (`src/publishing/publication_markers.py:745-758`).
3. `guard.record_intent(name, content_digest=digest)`
   (`scripts/research/publish_packages.py:336`) — **a durable publication
   intent is written.** In the workflow's checkout the arbiter is a
   `GitSharedClaim` (`src/publishing/shared_claim.py:155-164`), so the intent
   file is committed and pushed before the call, by design
   (`src/publishing/publication_markers.py:599-612`).
4. `publisher.publish(use_draft, mode)` raises `AttributeError`.
5. The `except Exception` at `scripts/research/publish_packages.py:373-377`
   records `PublishStatus.FAILED` and the loop continues to the next channel,
   which does the same thing.
6. `_publishing_failures` collects both (`scripts/research/run_daily_research.py:91-97`),
   the summary artifact and discovery data are still written and committed —
   deliberately, per `run_daily_research.py:207-216` and the workflow's
   `if: always()` commit step — and the process exits 1
   (`scripts/research/run_daily_research.py:270-276`). The run is red.

## 4 · The cost is not only the colour of the run

Step 3 happens and step 4 fails. The intent survives; no marker is ever
written. The next lookup for that key therefore returns
`AuthorityState.POSSIBLY_PUBLISHED` — "an intent with no usable marker: at most
once means this is a skip" (`src/publishing/publication_markers.py:482-483`) —
and `may_publish` is true only for `NO_PUBLICATION`
(`src/publishing/publication_markers.py:496-498`).

The key is `client + destination + sorted(source_signal_ids)` and contains no
article digest, by explicit design: "one publication per signal set per
destination" (`src/publishing/publication_markers.py:331-341`). The canonical
entrypoint forms its key the same way, from the same signal ID
(`scripts/generate_and_publish.py:3412`).

So each red run spends the at-most-once budget of a publication that never
happened, for `wix` and for `linkedin`, keyed to that signal. Any later run
that forms the same identity is refused as a skip — including a canonical
Mon/Wed/Fri run for that signal. Two details worth recording:

- The intent carries `run_id: ""`, so it cannot be attributed to the run that
  wrote it, and the `existing.run_id == run_id` reclaim path
  (`src/publishing/publication_markers.py:617-623`) cannot distinguish it from
  any other empty-`run_id` writer.
- The workflow persists markers in their own `if: always()` step
  (`.github/workflows/daily_signal_research.yml:100-104`), precisely so a
  partial failure cannot lose them. That is correct for a real partial
  publication and it is what makes this intent durable too.

**Not provable from this tree:** whether any signal ID that Stage 11 intent-marked
has since reached, or will reach, the canonical entrypoint. The key space is
shared by construction, which is what makes the exposure real; whether it has
been hit is a question for the publication-marker store's history and the
content plans, not for this file. `data/editorial/publication_markers/never_blank/`
currently holds one wix and one linkedin key, each with both an intent **and** a
marker — a completed canonical publication, not a Stage 11 remnant.

## 5 · Why the crash is not the gate

Stage 11 constructs no preflight. Letting it reach Wix or LinkedIn would
therefore bypass the whole authorization boundary the canonical entrypoint
runs — provenance, readiness, configuration identity, freshness, per-channel
ALLOW/BLOCK (`src/publishing/preflight.py:339-351`) — which is the hole #229
closed for Telegram, Facebook and Instagram. The `AttributeError` is currently
the only thing preventing that, which makes the package contract an accidental
second authorization boundary.

That the publishers refuse a mutable stand-in is itself a deliberate, tested
contract, not an accident: `tests/test_publication_preflight.py:384-393`
(`test_publisher_rejects_a_mutable_stand_in_for_the_package`) hands
`WixPublisher.publish` a `SimpleNamespace` carrying two of the package's
fields, asserts `AttributeError`, and asserts `_fetch` was never called. That
object fails on the next field `from_wix_package` reads; Stage 11's
`DraftPackage` fails on the first. The refusal is
correct and must survive either resolution. What is accidental is that Stage 11
is the caller being refused, and that its only signal of the refusal is a
stack trace.

`src/publishing/release_scope.py:1-26` already makes the argument against
relying on that: an incidental guard is not channel authorization, and the
module exists because #222 removed one and the accident it had been covering
became visible the next day. The same reasoning applies to this crash. It is
also why a permanently red daily workflow is its own cost: the colour has to
keep meaning something on the day a real failure happens.

## 6 · The schedule today

`daily_signal_research.yml` is cron `0 8 * * *`
(`.github/workflows/daily_signal_research.yml:5`) and is **owner-disabled in
the Actions UI**, per `docs/operations/GITHUB_ACTIONS_AUDIT.md:98-103`. That
audit carries it as DISABLE and states it cannot be deleted while #231 is
open, because resolution B would reuse the workflow.

So the daily red run is stopped today by a UI switch, not by anything in this
repository. A checkout of this commit, scheduled, still does everything in §3.
The stage also self-identifies as non-canonical in its own output
(`scripts/research/run_daily_research.py:101-103, 230`), and on Wednesdays the
workflow already forces `NB_RESEARCH_PUBLISH_ENABLED=false` so it cannot be a
second Wednesday publisher (`.github/workflows/daily_signal_research.yml:82-83`).
On every other day Stage 11 runs if that secret is `true`
(`scripts/research/run_daily_research.py:198-201`).

## 7 · The open decision, and what each resolution touches

The issue puts two coherent resolutions to the owner. They differ in what
Tue/Thu/Sat mean for the product, which is why neither is made here.

| | A — generate and package, publish nothing | B — Stage 11 becomes a canonical caller |
|---|---|---|
| Stage 11's publish loop | every channel gets the stated `SKIPPED` non-result the withheld four already get (`publish_packages.py:304-311`), with a reason naming the absent canonical preflight | builds frozen packages and runs `evaluate_publication_preflight` |
| Publishers | unchanged | unchanged |
| R1 publication | stays exclusively Mon/Wed/Fri through `scripts/generate_and_publish.py` | daily articles publish again — a Release decision, and one that contradicts `src/publishing/release_scope.py` as written |
| Intent markers (§4) | none written, because no channel is called | written and resolved by the real transaction |
| `daily_signal_research.yml` | disposition becomes decidable (audit §4) | retained and re-enabled |
| Regression test | that Stage 11 invokes no publisher | the full preflight path |

A third option the issue does not raise, and this record does not recommend:
leave it as is. That keeps the authorization hole closed by accident, keeps
spending the at-most-once budget per run, and depends on the Actions UI switch
staying off.

## 8 · What this record does not establish

- It does not establish that resolution A is right. The issue recommends it;
  the owner has not ruled, and §4 is new information that bears on the choice
  rather than settling it.
- It does not query GitHub. Every run-level claim is either quoted from the
  issue and labelled as such (§2), or anchored in this tree.
- It proves nothing about the *content* Stage 11 generates. Generation,
  validation and packaging complete; only publication fails.
- It does not decide #236, which owns `visibility_publish.yml` and
  `research_generate_and_publish.yml` (audit §4). The visibility path makes the
  same legacy call and its history is quoted above, but #236's stated failure is
  a provider 400 and it carries its own three resolutions.

---

*Read-only forensic record. No production code or configuration was modified,
no test was added or changed, nothing was published, no provider call was made,
and the product choice in #231 was left open.*
