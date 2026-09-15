# Monday selection — head-of-line blocking at the 15-candidate bound

Forensic record for Issue #237. Monday 2026-09-14 (run `34868092082`) ended at
exit 5 — an incomplete eligibility search — and the same thing will happen every
Monday until an owner decision is taken. This document exists so the diagnosis
does not have to be re-derived from a run artifact each week.

**Nothing here changes product logic, and nothing here is a decision.** No live
run and no provider call was made to produce it. The three options at the end
are recorded as *not taken*; this document neither takes nor recommends one.

Each finding below is exactly one of:

- `VERIFIED-IN-REPO` — re-derivable from tracked files at `58afe47`, with no
  model call and no run.
- `RUN-EVIDENCE` — established only by run `34868092082` and its
  `monday-selection-audit` artifact (`reports/stream_selection/monday_selection.json`,
  uploaded by the workflow, not committed).

## 1. The bound is intentional, and the stop was not premature

`VERIFIED-IN-REPO`. `scripts/streams/select_eligible_signal.py:63` and `:69` set
`DEFAULT_MAX_CANDIDATES = 15` and `MAX_CANDIDATES_CEILING = 15`. The ceiling is a
hard Release 1 cost bound from #171 (`ae96c07`): each candidate costs one model
call, the selector is the largest pre-run call multiplier, and a larger
`--max-candidates` is refused before the queue is read rather than clamped.
Exit 5 (`SEARCH_TRUNCATED`) is the documented response to "no eligible candidate
in the evaluated window", deliberately distinct from exit 3's "no eligible
candidate in the queue".

`RUN-EVIDENCE`. The audit records `evaluated 15`, `outcome search_truncated`,
and no `judgment_failed` or `provider_unavailable` disposition. Every judgment
completed. This was not a provider outage wearing the wrong exit code.

## 2. The structural defect: the window never advances

`VERIFIED-IN-REPO`. Three properties combine into a standstill.

**Queue order is append order, oldest first.** `_load_candidates` walks
`data/research/signals_active.jsonl` in file order and keeps every signal whose
`SIGNAL_ID` is absent from `data/research/published_signal_ids.txt`. Daily
research appends, so `DATE_FOUND` is non-decreasing down the file: line 1 is
`2026-06-22`, line 105 is `2026-09-15`.

**Rejections are never recorded.** A rejected candidate is only *skipped* — the
module docstring states it, and consumption stays where it has always been,
after a successful publication. No file remembers that a candidate was judged
ineligible.

**So the same prefix is re-judged every week.** Of the 105 signals in the active
file, 5 appear in the published-ids list (lines 1–4 and 6), leaving **100 unused
candidates**. Positions 0–14 — the exact window one Monday can afford — are file
lines 5 and 7–20, spanning `DATE_FOUND` `2026-08-18` … `2026-08-27`. Position 15
is line 21 (`2026-08-28`). The **73 September signals occupy positions 27–99**,
and no Monday can reach them. Dropping the four `2026-09-15` signals added after
the run (lines 102–105) leaves **96 candidates**, matching the run's "15 of 96".

Every Monday therefore re-spends 15 model calls on the same ineligible head and
ends at exit 5, unless the head itself changes.

`RUN-EVIDENCE`. Monday 2026-09-07 and 2026-08-31 were stale-skipped before
selection ran, which is why 09-14 was the first Monday to reach this state.

## 3. Why all 15 were rejected

`RUN-EVIDENCE` for the dispositions, `VERIFIED-IN-REPO` for the criteria they
map onto — `strategy/current/business_strategy.json`, role
`never-blank-monday-documented-case`:

- **12 of 15 — no specific company.** General trend and advertiser pieces
  ("brands", "advertisers", "ecommerce retailers", LLC formation trends, Meta's
  small-business tools). These hit *"any case whose business scale, stage, or
  ownership the available material does not establish. Unknown is ineligible"*.
- **3 of 15 — currently large companies.** Invisalign, Wendy's, and HubSpot at a
  later stage, at unused-queue positions 0, 10 and 14 (file lines 5, 16 and 20)
  — all three inside the 15-wide window, which is why they were reached at all.
  These hit *"Ineligible: current large-company or public-company/major-corporate
  behaviour"*.

Read against the criteria as written, the judgments are consistent. This is a
judgment call about supply, not a re-run.

## 4. Eligibility logic did not regress

`VERIFIED-IN-REPO`. Three independent checks, all negative:

- The two rules that produced all 15 rejections are **byte-identical** to their
  text at `3fc0eff` (#142, 2026-08-20) and have not changed since.
- Monday published successfully on 2026-08-24 under those same criteria — signal
  `9edc711177c0fc6b`, the home bagel business, file line 6.
- The July failure pattern recorded in #206/#205 (the `a557855` signal filter,
  "protagonist always owner" in `pattern_extractor`) is not in this path.
  `select_eligible_signal.py` calls `judge_source_eligibility` and nothing else.

## 5. The mismatch is supply versus role (#202)

`VERIFIED-IN-REPO`. `config/prompts/research/signal_selector.yaml` admits
mechanism, trend and data signals without requiring a documented specific small
or owner-led business. **82 of the 100 unused signals carry
`"REAL_COMPANY_EXAMPLE": null`**, and the 18 that name a company name mostly
large ones — Amazon, Adobe, Microsoft, Stripe, Booking.com, Bain, Gong, Ramp,
Wikipedia, WhatsApp.

That field is a weak proxy and must not be read as an eligibility count: the
2026-08-24 winner is itself one of the 82. It is *plausible* that very few
eligible Monday candidates exist anywhere in the queue, and that cannot be
established without model calls.

## 6. Owner decisions — not taken

Recorded for continuity. None of these is implemented, and this document does
not choose between them.

- **A. Change selection order.** Walk newest first, or persist per-role
  rejections so the bound advances down the queue. This changes selection
  semantics and relaxes the "rejections are only skipped" contract; on its own it
  probably moves the failure from exit 5 to exit 3 or to a selection, depending
  on supply.
- **B. Operator unblock for one Monday.** Dispatch an explicit `signal_id`. This
  is a live run and needs explicit authorization.
- **C. Role-aware supply (#202).** Have research deliberately source documented
  small or owner-led cases for Monday. This addresses *why* the head is
  ineligible rather than how far the selector reaches past it.

Until one is taken, Section 2 is the expected weekly outcome, not an incident.
