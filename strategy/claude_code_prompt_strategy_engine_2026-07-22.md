# Never Blank — Strategy Engine: Automated Monthly Cycle

## Objective

Build an automated monthly cycle that runs end-to-end **without human
approval before publishing**: market research → pattern extraction →
strategy selection → content plan → article generation → publish →
analytics collection → strategy history logging.

This is a new orchestration layer on top of the editorial system already
built (`57e4c9c`, `54d7694`, plus whatever local commits followed the
"editorial strategy amendment"). Read `strategy/decision_log.md` in full
before starting — it is the canonical record of every editorial and
business decision this task must respect, especially Часть 4 (post
structure, Echo, cta_mode), Часть 5 (article philosophy — company as
evidence, not hero), Часть 6 (target audience, GTM), and Часть 7 (this
task's explicit scope and the risk being accepted). Also read
`strategy/worldview.md` and `strategy/never_blank_campaign_1.xlsx` — the
spreadsheet is a hand-built reference example of the target quality bar
and `cta_mode` distribution, not a process to replicate manually.

## The monthly cycle

```
Market Intelligence / Research
        ↓
Pattern Extraction
        ↓
Strategy Selection
        ↓
Content Plan (topics + hooks)
        ↓
Article Generation
        ↓
Quality Gate (automatic, no human review)
        ↓
Publish
        ↓
Analytics Collection (after a window)
        ↓
Strategy History entry
```

### 1. Market Intelligence / Research

Reuse and extend `scripts/research/discover.py`, which already has a
visibility-relevance gate scoped to Never Blank's territory. Point research
at the target audience defined in decision 34: small B2B service
businesses with a single decision-maker — agencies (digital/web/dev/
creative), consultants, MSPs. Look for: active pains, seasonal/behavioral
shifts, competitive visibility patterns, anything that maps to the
visibility/presence/recognition/customer-memory territory (decision 13) —
not general small-business news.

### 2. Pattern Extraction

This is the open architectural item from Часть 4 (`strategy/decision_log.md`,
"Pattern Extractor"). Implement it now, sitting between Research and
Strategy Selection. For each candidate signal, it must answer: what
mechanism was found; what typical business-owner situation maps to that
mechanism; whether this signal fits Never Blank's territory at all (reject
if not — this is a hard gate, not a soft preference); what the commercial
consequence of the mechanism is; and, if a named company appears in the
signal, why it is evidence rather than the subject of the article (decision
24, 28 — the article must survive if the company name is removed).

### 3. Strategy Selection

Decide the month's main theme and 1–2 secondary themes, based on which
patterns are strongest and which pains are currently active for the target
segment. Decide the `cta_mode` distribution for the month's posts (mix of
`none` / `reflection` / `diagnostic` / `example_request` /
`direct_conversation` per decision 18/31 — do not default to all-diagnostic
or all-none). This stage's output is the "current strategy" record — see
the two-representation requirement below.

### 4. Content Plan

Structured list of the month's topics: for each, the theme it serves, the
hook, the `cta_mode`, and the specific pain/mechanism it addresses. Output
format is your call (JSON is probably the natural fit given the rest of
the pipeline) — Val does not care whether it's JSON or spreadsheet, only
that it exists and articles come out of it.

### 5. Article Generation

Reuse `config/prompts/linkedin_post.yaml` and `src/content/generator.py`.
Every article must follow: Recognition before Explanation (decision 16);
research stays backstage, no "I researched/analyzed" narration except when
an article is explicitly about the research itself (decision 17); CTA
comes from `cta_mode`, never model discretion (decision 18); Reframe must
break the obvious explanation, not just recommend "do more" (decision 29);
business translation is concrete and commercial, not emotional (decision
30).

**Echo — read this carefully, it changed today.** Decision 19 originally
set a soft target of roughly half of posts carrying an earned Echo. That
target is now raised significantly (decision 38): Echo should be present
in the large majority of articles — treat "no strong Echo emerged" as a
rare exception, not a routine outcome. Still generate multiple candidates
internally and still refuse to insert a generic/unearned Echo — the bar on
quality does not drop, only the acceptable rate of skipping it does. If
you find candidate generation is producing weak Echoes often, that's a
signal the generation prompt needs work, not a reason to lower the bar.

Named concepts: Presence Debt is the one flagship term being tested this
phase (decision 21) — working definition and validation criteria are in
`decision_log.md`. Do not force it into every article. Hashtags: 3–5,
article-specific, no generic tags (decision 23).

### 6. Quality Gate — the only checkpoint before publish

Decision 39: publishing is **fully autonomous, no human review**. The only
gate is the existing automatic Quality Gate (`src/quality/gate.py`:
voice/factuality/duplication checks). If an article fails the gate, follow
the existing rewrite path (`src/quality/rewrite.py`) once; if it still
fails, **do not publish it** — log the skip explicitly (which topic, which
check failed, why) so it's visible in the strategy history / analytics,
rather than silently dropping it or force-publishing a failing article.

### 7. Publish

Via the existing publishers (`src/publishing/linkedin.py`, Zernio-backed).
No new publishing logic needed unless the monthly cadence requires
scheduling changes to the existing GitHub Actions workflows — check
`daily_signal_research.yml` and the other workflows in `.github/workflows/`
and decide whether the monthly cycle needs its own scheduled workflow or
can be composed from the existing daily research cadence plus a
month-boundary trigger. Document whichever you choose.

### 8. Analytics Collection

After a defined window (30 days is the default assumption — confirm against
however the monthly cycle boundary is implemented), collect:

- **Automatic signals** (platform APIs where available): impressions,
  reactions, comments, reposts, clicks, profile views if exposed, website
  visits, replies.
- **Qualitative signals** (require human or LLM-assisted reading, not a
  platform metric): whether Recognition landed, whether the Echo worked,
  whether comments showed genuine self-recognition, whether a named
  concept got repeated back. Per decision 22, do not build or imply an
  automatic score for this half — provide a clear place for it to be
  filled in (by a person or by an LLM-assisted qualitative pass reading the
  actual post/comments), and label it as qualitative judgment, not a
  platform metric.
- **Outcome tracking**: leads, conversations started, clients — this is
  the actual success metric Val cares about most ("do we have clients or
  not"). If there's no automated way to capture this yet, the schema must
  still have an explicit field for it, even if populated manually for now.

### 9. Strategy History

New artifact, separate from `decision_log.md` (which stays for
architecture/system decisions). This one records the actual monthly
strategy cycles and what happened: period → which strategy was chosen and
based on which research/analytics → what happened in practice (worked /
partially worked / didn't, with concrete numbers — leads, reactions,
clients yes/no) → what's chosen next and why. Chronological, append-only,
one entry added at the end of each cycle, committed to git.

## Two representations of "current strategy" (decision 40)

1. **In code** — a structured record (JSON/YAML) that actually drives
   generation for the active cycle. This is the source of truth.
2. **Human-readable document** — e.g. `strategy/current_strategy.md`,
   regenerated or updated at the start of each cycle in plain language:
   main theme, secondary themes, why, target segment, `cta_mode`
   distribution, when the next cycle runs. Someone should be able to open
   this file and understand the active strategy without reading code or
   JSON.

Both must be updated together — they are not allowed to drift.

## Git / GitHub

Check `.gitignore` — `data/` is currently ignored. The strategy history
file and the current-strategy document are durable, decision-relevant
artifacts and must be tracked in git, not left in an ignored directory.
Published article records and the content plan for each cycle should also
be committed (or clearly justified if you decide otherwise).

## Constraints carried over from existing decisions (do not re-derive, just respect)

- Territory: visibility, presence, recognition, customer memory only — not
  general small-business consulting (decision 13). Target segment: small
  B2B service businesses, single decision-maker — agencies, consultants,
  MSPs (decision 34).
- Company appears only as evidence embedded mid-argument, never as the
  subject or hero (decisions 24, 28).
- No fabricated research volume, customer history, or statistics, ever
  (original anti-hallucination brief, decision 10).
- Reframe must genuinely contest the obvious explanation, not just suggest
  doing more of something (decision 29).

## Required implementation behavior

1. Audit current architecture first — identify what already exists
   (`discover.py`'s visibility gate, `CTAMode`, `ContentPackage`,
   `src/quality/gate.py`, existing workflows) vs. what's genuinely new for
   this task.
2. Build Pattern Extraction as a real module, not a doc — it's been an open
   item since Часть 4.
3. Build Strategy Selection + Content Plan generation.
4. Wire Echo's new priority level into the generation prompt/logic (not
   just documentation).
5. Build both strategy artifacts (code record + human-readable doc) and
   keep them in sync.
6. Build the strategy history file and log a first real entry once a cycle
   actually runs.
7. Decide and document the scheduling mechanism (new workflow vs. reuse of
   existing cadence).
8. Add tests for: the visibility-relevance gate, the quality-gate-fail →
   skip-and-log path (must not silently drop or force-publish), and the
   two-artifacts-stay-in-sync invariant.
9. Run the existing test suite — do not silently break what's there.
10. Do not build a human-approval step anywhere in this path — that was
    explicitly decided against (decision 39). If you think it's a mistake,
    say so in your deliverables report, but build what was asked.

## Deliverables

1. Short audit of what already existed vs. what you built.
2. List of changed/new files with what each does.
3. The first real monthly cycle output: content plan, generated articles,
   the current-strategy document, and the first strategy-history entry.
4. Test results.
5. Commit SHA.
6. Explicitly flag anything you had to guess or decide without enough
   product input — do not silently resolve ambiguity in a way that isn't
   visible in this report.
