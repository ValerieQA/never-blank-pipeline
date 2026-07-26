# Never Blank — Editorial Strategy Task: Amendment

This is a follow-up to the task already in progress ("Update the Never Blank
editorial strategy and article-generation architecture"). Everything in the
original brief still stands. The points below refine six specific parts of
it, decided after the original brief was written. Where these conflict with
the original wording, this amendment takes precedence. Full decision record:
`strategy/decision_log.md`, Часть 4 (2026-07-21).

If you have already implemented parts of the original brief, reconcile the
existing implementation with the refinements below rather than starting over.

## 1. CTA is governed by an explicit `cta_mode`, not left to model judgment

The original brief said CTA presence should follow "campaign purpose, not
randomly." Make this concrete: the campaign/content-matrix layer must set an
explicit field, e.g. `cta_mode`, with these values:

- `none` — no CTA, article's job is reach/recognition/concept-building only
- `reflection` — soft, reflective invitation (e.g. "if you recognize your
  business in this pattern...")
- `diagnostic` — invitation to a visibility audit / identify where the
  system breaks
- `example_request` — invitation to request an example
- `direct_conversation` — invitation to discuss fit directly

The model generating the article must not decide on its own whether to
include a CTA or which type — it receives `cta_mode` as input and writes the
CTA (or omits it) accordingly. This exists because leaving the choice to the
model at generation time systematically biases toward the safe option (no
sale), which defeats the "immediate client acquisition" goal in the original
brief.

## 2. Echo: candidate-generation model, not a per-article quota

Keep the Echo as a distinct structural device (see original brief, section
8) with one refinement to how "how often" is expressed: Echo is not a fixed
rule like "every second article." Instead:

- For every article, generate multiple Echo candidates internally.
- Include the strongest one only when it is genuinely earned by that
  article's specific argument.
- As a soft target for the first campaign only (not a hard rule going
  forward): a strong, earned Echo should show up in roughly half of the
  posts. Short-form or directly sales-oriented posts may skip it entirely —
  that's expected, not a failure.
- Valid ending combinations, all acceptable: Echo with no CTA / CTA before
  Echo / an invitation that itself functions as the Echo / a direct CTA with
  no philosophical closing line (for explicitly sales-purposed posts).

## 3. Named concepts: designate one flagship term as a tested hypothesis

The original brief lists Compound Presence, Never Silent, customer memory,
accumulated recognition, and continuity of presence as concepts to preserve
and develop. Refinement: designate **Presence Debt** as the first flagship
term to introduce and test in the first campaign, with this working
definition:

> Presence Debt is the accumulated cost of the periods when a business
> disappears from customers' view and has to rebuild recognition,
> familiarity, and trust again.

Treat it explicitly as a hypothesis, not a locked brand term. After the
first campaign, evaluate it against: do people repeat the phrase in
comments; do they recognize their own situation in it; does it prompt
questions; does it help move toward a diagnostic conversation; does it
require too much explanation to land. If it doesn't stick, drop it — the
system is not obligated to defend a term just because it shipped once. The
other named concepts stay in reserve and get introduced later, organically,
not all in the same launch.

## 4. Architecture staging: insert a live campaign between Editorial and Distribution work

The original brief scopes this task as editorial-strategy-and-article-
generation, and separately references SEO/GEO/discoverability work. Make the
sequencing explicit so future work (yours or a later task) doesn't jump
ahead of real evidence:

```
1. Implement Editorial Strategy (this task)
2. Generate and review the first campaign
3. Publish the campaign
4. Collect real qualitative and quantitative signals
5. Build/extend Distribution Engine (SEO, LinkedIn discoverability, etc.)
   using actual evidence from step 4
```

Nothing in steps 2-5 blocks this task from being completed and merged. This
is guidance for what comes after, so a future contributor doesn't design
analytics or distribution tooling around an untested hypothesis.

## 5. Analytics: separate automatic platform signals from human/qualitative judgment

The original brief's signal list (comments showing self-recognition, direct
questions, profile visits, website visits, diagnostic requests, example
requests, replies, leads, conversations, purchases) is correct but mixes two
different kinds of signal. Keep them distinct in whatever you build or
document:

- **Automatic signals** (pulled from platform APIs where available):
  impressions, reactions, comments, reposts, clicks, profile views, website
  visits, replies, leads, conversations.
- **Qualitative signals** (require a human — or an Experiment Analyst role —
  reading the actual post/comments/messages): whether Recognition landed,
  whether the Echo worked, whether a CTA felt forced, whether readers
  repeated a named concept back, whether comments showed genuine
  self-recognition.

Do not build or imply an automatic dashboard for the second category —
platforms don't expose "did Recognition land" as a metric. If you're
documenting this for future implementation rather than building it now
(per the original brief's "document them for future implementation"
allowance), make this split explicit in the doc so nobody later tries to
automate the qualitative half.

## 6. Hashtags and SEO/GEO — added specificity

In addition to the original brief's SEO/GEO section:

- Hashtags stay in the publishing layer, not the Editorial Engine (already
  stated in the original brief — no change here).
- Target roughly 3-5 relevant hashtags per LinkedIn post, chosen per
  article/industry/audience — not one fixed set reused everywhere.
- No generic/junk tags (`#success`, `#motivation`, `#business` and similar).
- A Named Concept (e.g. Presence Debt) may be used as a hashtag only after
  it has been explained in the content itself a few times — not as the
  first-ever appearance of the term.

## Deliverables for this amendment

When you report back on the original task's deliverables, note specifically:
whether `cta_mode` (or equivalent) is now an explicit input rather than a
model decision; how Echo frequency is actually behaving across the three
sample articles; whether Presence Debt appears in any sample article and how
it reads; and confirm the automatic-vs-qualitative signal split is reflected
in whatever analytics/signal documentation you touch.
