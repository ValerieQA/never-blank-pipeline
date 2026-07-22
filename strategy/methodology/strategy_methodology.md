# Never Blank — Strategy Methodology

**Status:** Production  
**Last updated:** 2026-07-22  
**Decisions:** 34, 39, 41, 42, 43, 44, 45

---

## Product context

Never Blank is not a content generator. It is a system that continuously analyzes the market, identifies the most promising sales and presence strategy for small businesses, and executes it through Compound Presence.

**Compound Presence** — the cumulative effect of consistent business visibility at relevant contact points. Sequential publications, articles, market observations, and repeated semantic signals strengthen recognition, trust, and the likelihood of client contact over time.

Content is the execution mechanism of the strategy, not the product itself.

---

## Target segment (decision 34, 45)

Small B2B service businesses with a single decision-maker:
- Digital/web/dev/creative agencies
- Independent consultants and advisors
- Managed service providers (MSPs)

Territory: visibility, presence, recognition, customer memory, consistent communication, owner dependency (decision 13). Not general small-business consulting.

---

## Strategy cycle

```
Market Research
→ Market Analysis
→ Sales Strategy selection
→ Monthly Content Strategy
→ Editorial Plan (content plan)
→ Content Generation
→ Platform Adaptation
→ Distribution
→ Weekly Performance Review
→ Monthly Strategy Review
→ CONTINUE / ADJUST / REPLACE
```

### Strategy continuation rule (decision 42, implicit in 44)

A strategy does **not** automatically change at the end of a month.  
A new month means a mandatory re-evaluation, not a replacement.  
A working strategy — one producing leads or confirmed positive momentum — continues for as long as it works. This can be 2, 3, or more months.

---

## Primary KPI: leads (decision 45)

The strategy is commercially successful when it generates leads or shows sustained movement toward them.

**Leads include:**
- Inbound messages (LinkedIn DMs, Instagram messages, Telegram inquiries)
- Consultation or demo requests
- Form submissions
- Email inquiries
- Any measurable commercial contact initiated by a prospect

**Early signals** (diagnostic, not conclusive):
- Follower growth
- Website sessions and CTA clicks
- Saves and shares
- Substantive comments (genuine self-recognition, not generic)
- Reach and impressions
- Engagement growth vs. prior period
- Posts significantly above baseline
- Repeated reactions to the same problem or theme

Likes alone are not evidence of strategic success.

---

## Weekly evaluation (first month of any new strategy)

During the first month of a new strategy, the system runs a weekly review.

Output: one of three decisions.

### CONTINUE
Criteria:
- At least one lead, or
- Stable growth in early signals across multiple posts, or
- Audience responding to the chosen problem, or
- Strategy hypothesis being confirmed

### ADJUST_EXECUTION
Strategy direction is sound, but execution needs change. Adjust one or more of:
- Article topics or angles
- Hooks
- CTA mode or phrasing
- Platform format (carousel, thread length, etc.)
- Publishing frequency or timing
- Content mix (more recognition vs. more mechanism articles)

Changing execution is not the same as changing strategy.

### REVIEW_STRATEGY
Criteria (any of the following, especially if sustained):
- No leads
- No growth in early signals
- Posts consistently below baseline
- Chosen problem not producing recognition in comments/saves
- CTA not producing action
- Market hypothesis not being confirmed
- Negative trend over multiple weeks

---

## Monthly strategy review

At the end of each month, the system produces a full Strategy Review answering:

1. What strategy was active?
2. Why was it chosen?
3. What market signals informed it?
4. What small business problem was targeted?
5. What sales mechanism was applied?
6. What topics were published?
7. Which hooks performed best?
8. Which Echoes performed best?
9. Which CTAs generated action?
10. Which platforms performed best?
11. How many leads were generated?
12. Which posts were outliers (positive)?
13. Is there a positive trend?
14. Is the strategy confirmed?
15. Continue, adjust, or replace?

### Monthly decision options

- **CONTINUE_STRATEGY** — results confirm hypothesis, leads or strong early signals
- **CONTINUE_WITH_ADJUSTMENTS** — direction confirmed, refine execution
- **REPLACE_STRATEGY** — hypothesis not confirmed, no leads, no positive trend
- **INSUFFICIENT_DATA** — not enough data to decide; continue and collect more

---

## Strategy artifacts (two representations, always in sync)

**1. Machine-readable:** `strategy/current/strategy.json`  
The source of truth. Used by generation pipeline.

**2. Human-readable:** `strategy/current/strategy.md`  
Regenerated or updated at start of each cycle. Plain language.  
Anyone opening GitHub must understand the active strategy without reading code.

Both are updated together. Drift is not allowed.

---

## Strategy history

`strategy/history/` — append-only, version-controlled, never overwritten.

Each strategy gets its own subdirectory:
```
strategy/history/{year}-{month}-{strategy-id}/
  strategy.json
  strategy.md
  research_snapshot.json
  content_plan.json
  content_plan.csv
  weekly_review_01.json
  weekly_review_01.md
  weekly_review_02.json
  weekly_review_02.md
  weekly_review_03.json
  weekly_review_03.md
  weekly_review_04.json
  weekly_review_04.md
  monthly_review.json
  monthly_review.md
  lessons.json
```

Preserves: original strategy, rationale, research snapshot, all changes, all reviews, outcome metrics, decision, lessons learned.

---

## Quality gate (decision 39)

Publishing is fully autonomous. No human review step anywhere in the pipeline.

The only gate before publish is the automated Quality Gate (`src/quality/gate.py` + `src/content/output_guard.py`).

If an article fails the gate:
1. Rewrite once via `src/quality/rewrite.py`
2. If still failing: do not publish. Log explicitly: which topic, which check failed, why.
3. Logged skip is visible in strategy history and analytics — not silently dropped.
4. Never force-publish a failing article.

**Accepted risk** (recorded in decision_log.md): without human review, the first articles from a new strategy publish to real audience before anyone checks them. Quality Gate is the only protection. This was explicitly accepted.
