# Curiosity Engine — Specification

_formerly "Business Investigation Layer"_

**Version:** 0.2 (architecture only — no implementation)
**Status:** Draft
**Branch:** feature/business-investigation-layer

---

## Purpose

> **Never Blank teaches AI to be curious before it becomes confident.**

The Curiosity Engine is the first active layer in the Never Blank pipeline.
It sits between signal discovery and content generation.

Its only responsibility: determine what must be understood before a conclusion is
even possible — and produce a structured investigation plan based on questions,
not on available APIs.

It does not write articles. It does not produce opinions. It does not start from
what sources are accessible. It starts from what must be known.

> **Core principle:** Never Blank does not rush to explain events.
> First, it investigates what decisions, constraints, alternatives, and consequences
> stand behind the event. Only then does it have the right to draw a conclusion.

**The governing question of this layer:**
> *"What must be investigated before we have the right to draw a conclusion?"*

**The critical ordering principle:**
The engine moves from questions to sources — never the reverse.

```
Question
    ↓
Evidence Needed
    ↓
Possible Sources
    ↓
Evidence Collected
    ↓
Decision Lens
```

Starting from "what sources do we have access to?" is an engineering shortcut
that produces source-constrained thinking. Starting from "what do we need to know?"
produces investigation-driven thinking. The difference determines output quality.

---

## Where this layer fits

```
Business Signal (RSS / manual)
        ↓
  [ Stage 1–9 ]   Current pipeline (discovery → score → enrich → angles)
        ↓
  [ Stage 10 ]    CURIOSITY ENGINE            ← this document
                  "What should we investigate?"
        ↓
  [ Stage 10b ]   EVIDENCE COLLECTOR
                  "What can we actually verify?"
        ↓
  [ Stage 11 ]    DECISION LENS
                  "What does it mean?"
        ↓
  [ Stage 12 ]    EDITORIAL ENGINE
                  "How do we explain it?"
        ↓
  [ Stage 13 ]    Platform Adaptation (LinkedIn, Instagram, Threads, Telegram, Wix)
```

Note: the Curiosity Engine (Stage 10) and Evidence Collector (Stage 10b) are two
distinct responsibilities. This document covers Stage 10 — the question-generation
and investigation-planning step. The Evidence Collector will be specified separately.

The current pipeline is preserved in full. Stages 1–9 continue to operate as-is.
This layer receives their output and enriches it before passing to content generation.

---

## Inputs

The layer receives the enriched signal record produced by Stages 1–9.

**Required fields:**
```json
{
  "SIGNAL_ID": "string",
  "HEADLINE": "string",
  "SOURCE_URL": "string",
  "SOURCE_NAME": "string",
  "SOURCE_DATE": "YYYY-MM-DD",
  "CORE_FACT": "string",
  "SIGNAL_TYPE": "layoffs | pricing | fundraising | acquisition | regulation | ai_adoption | hiring | retention | product | strategy | macro",
  "REAL_COMPANY_EXAMPLE": "string | null",
  "CORE_TENSION": "string",
  "BUSINESS_LESSON": "string",
  "ARTICLE_READINESS_SCORE": "integer 0–10"
}
```

**Optional fields passed through if present:**
`RESPONSE_TAKEN`, `OUTCOME_IF_KNOWN`, `PROBLEM_FACED`, `BUSINESS_RESPONSES_OBSERVED`,
`COUNTER_EXAMPLE`, `POSSIBLE_SIGNATURE_LINE`, `NEVER_BLANK_ANGLE`

---

## Investigation workflow

```
1. Classify signal type
        ↓
2. Select investigation template for that type
        ↓
3. Generate investigation plan (list of required + optional questions)
        ↓
4. Attempt to answer each question via available sources
        ↓
5. Score evidence completeness
        ↓
6. Decide: proceed / flag insufficient / halt
        ↓
7. Return investigation record to Decision Lens
```

---

## Investigation templates by signal type

Each template defines:
- **Required questions** — must be answered before proceeding
- **Contextual questions** — attempted; partial answers acceptable
- **Evidence threshold** — minimum required/contextual coverage to proceed

---

### LAYOFFS

**Required questions:**
1. Why now — what changed in the last 90 days that made this the moment?
2. Is this cost reduction or strategic repositioning? (What did they stop doing?)
3. Which teams/functions were cut? Which were protected or grew?
4. What did leadership say publicly vs. what did employees report?

**Contextual questions:**
5. What were the last two years of headcount trajectory?
6. What did competitors do over the same period?
7. What do Glassdoor / Blind / LinkedIn data suggest about culture before the cut?
8. What happened to companies that made similar cuts 12–24 months ago?
9. What investor or board pressure preceded the decision?
10. What did they announce as priorities *after* the cut?

**Evidence threshold:** 3 of 4 required + at least 3 contextual

---

### PRICING

**Required questions:**
1. What specifically became more expensive, and by how much?
2. What alternatives did the company have? Why were they rejected?
3. Who absorbs the cost — the business or the end customer?
4. What triggered this now (cost pressure, competitive move, or margin expansion)?

**Contextual questions:**
5. What did competitors charge before and after?
6. Who chose a different path, and what happened to them?
7. What do power users say about willingness to pay?
8. Is there a free tier or workaround still available?
9. What happened to churn after the last pricing change?
10. What does this signal about their unit economics?

**Evidence threshold:** 3 of 4 required + at least 3 contextual

---

### FUNDRAISING

**Required questions:**
1. Why raise now — what does the timing reveal about their position?
2. Who led the round, and what does that investor's portfolio say about thesis?
3. What will the capital actually be used for (stated vs. inferred)?
4. What does the valuation imply about growth expectations?

**Contextual questions:**
5. What were the previous rounds, and how long did each runway last?
6. What alternatives existed — strategic partnership, profitability, acquisition?
7. What did the founding team say about funding strategy 12+ months ago?
8. What is the competitive landscape that made investors believe now?
9. Who passed on the round (if known)?
10. What are the dilution and governance implications?

**Evidence threshold:** 3 of 4 required + at least 2 contextual

---

### ACQUISITION

**Required questions:**
1. What did the acquirer actually buy — technology, team, customers, or distribution?
2. What problem does this solve that organic growth could not?
3. What did the target company struggle with before the acquisition?
4. What will the acquirer likely kill, keep, and integrate?

**Contextual questions:**
5. What did the target's founders and team say publicly about the deal?
6. What competing bids or alternatives were reported?
7. What happened to previous acquisitions by this buyer?
8. What do customers of the acquired company face now?
9. How does this change competitive dynamics in the category?
10. What does the price imply about market sizing?

**Evidence threshold:** 3 of 4 required + at least 3 contextual

---

### REGULATION

**Required questions:**
1. What specifically does the regulation require or prohibit?
2. Who lobbied for it and who lobbied against it? What does that reveal?
3. What enforcement mechanism exists — is it real or symbolic?
4. Who is most exposed, and who benefits from compliance costs?

**Contextual questions:**
5. What did the industry do in anticipation of this?
6. What happened in jurisdictions where similar rules already exist?
7. What is the timeline — when does compliance actually begin?
8. What workarounds exist and how long will they be tolerated?
9. What does this regulation signal about where the next one will land?
10. What do founders and operators say vs. what do lawyers say?

**Evidence threshold:** 4 of 4 required + at least 3 contextual

---

### AI ADOPTION

**Required questions:**
1. What specific workflow or role is being replaced or augmented?
2. What were the actual measured outcomes — not the press release?
3. Who made the adoption decision and what was their incentive?
4. What did the people affected say — public record only, no speculation?

**Contextual questions:**
5. What did similar companies do and what happened to their results?
6. What did the vendor claim vs. what was independently verified?
7. What broke or failed that was not announced?
8. What is the true cost of adoption (not just licensing)?
9. What skills or roles are now more valuable as a result?
10. What does the adoption pattern suggest about industry-wide timing?

**Evidence threshold:** 3 of 4 required + at least 3 contextual

---

## Source hierarchy

Sources are a consequence of questions, not the starting point.
Once the Curiosity Engine produces an investigation plan, the Evidence Collector
attempts to answer each question by consulting sources in reliability order.

The hierarchy below is used by the Evidence Collector (Stage 10b).
It is listed here because it shapes how the Curiosity Engine marks
evidence requirements — a question that can only be answered by Tier 3 sources
is flagged as lower-confidence from the start.

**Tier 1 — Primary evidence (strongly preferred):**
- Earnings call transcripts (verbatim)
- SEC / regulatory filings
- Official company announcements
- CEO / executive letters and interviews
- Court documents, regulatory decisions

**Tier 2 — Structured secondary evidence:**
- Verified journalist investigations (long-form, named sources)
- Glassdoor / Blind aggregates (directional only, not individual posts)
- LinkedIn headcount data
- Job posting changes (tracked via API)
- Patent filings, trademark registrations

**Tier 3 — Community signal (contextual only, never primary):**
- Reddit / HackerNews discussion
- Twitter / X threads from practitioners
- Industry newsletter coverage
- Analyst commentary

**Tier 4 — Historical precedent:**
- What happened to comparable companies in comparable situations
- Past coverage of the same company
- Category-level outcome studies

**Rule:** No conclusion in the investigation record should rest solely on Tier 3 sources.
If Tier 3 is the only available evidence for a required question, that question is marked `unresolved`.

---

## Evidence completeness scoring

After attempting all questions, the layer scores completeness:

```
required_answered   = count of required questions with Tier 1 or 2 evidence
contextual_answered = count of contextual questions with any tier evidence
total_required      = count of required questions for this signal type
total_contextual    = count of contextual questions for this signal type

required_coverage   = required_answered / total_required
contextual_coverage = contextual_answered / total_contextual

investigation_score = (required_coverage * 0.7) + (contextual_coverage * 0.3)
```

**Decision thresholds:**

| Score | Decision | Action |
|---|---|---|
| ≥ 0.75 | `PROCEED` | Pass to Decision Lens |
| 0.50–0.74 | `PROCEED_WITH_CAVEATS` | Pass with `evidence_gaps` flagged |
| 0.30–0.49 | `INSUFFICIENT` | Hold signal; flag for manual review |
| < 0.30 | `BLOCKED` | Do not proceed; log reason |

---

## When to declare "insufficient evidence"

The layer must halt and return `status: INSUFFICIENT` when:

1. **All required questions are unanswered** — there is no primary or secondary evidence for any of the 4 required questions.

2. **The only source is the original signal** — no additional context was found beyond the triggering news item itself.

3. **Critical contradiction detected** — available evidence directly contradicts the premise of the signal and no resolution is possible without human judgment.

4. **Speculation dependency** — answering the required questions requires the layer to speculate rather than report. If the layer cannot distinguish between "what was documented" and "what seems likely," it must stop.

5. **Single-source critical claim** — a required question can only be answered by a single Tier 3 source with no corroboration.

`INSUFFICIENT` is not a failure. It is the correct output when evidence does not yet support a trustworthy conclusion. It prevents generic AI content from filling the gap with plausible-sounding fabrication.

---

## How this layer reduces hallucination and generic content

Generic AI content emerges when a model is given a thin signal and asked to produce a rich output. The gap between input richness and output richness is filled with the model's priors — statistically likely but factually unverified.

This layer closes that gap before content generation begins:

| Without this layer | With this layer |
|---|---|
| Model invents "what typically happens" when data is missing | Model only draws on verified evidence; gaps are explicit |
| Conclusions are plausible but not grounded | Conclusions cite specific sources, dates, outcomes |
| All layoff articles sound similar | Each article is shaped by the specific investigation findings |
| Hallucinations appear as confident assertions | Unresolved questions surface as honest unknowns |
| Decision Lens works on thin signal | Decision Lens works on documented evidence base |

The layer enforces a separation between **what was documented** and **what was inferred**. Every field in the output JSON is tagged with its evidence tier. The Editorial Engine is permitted to use documented evidence directly; inferences must be framed explicitly as interpretation.

---

## Output JSON schema

Returned to Decision Lens upon successful investigation.

```json
{
  "SIGNAL_ID": "string",
  "investigation_status": "PROCEED | PROCEED_WITH_CAVEATS | INSUFFICIENT | BLOCKED",
  "investigation_score": 0.0,
  "signal_type": "string",
  "investigated_at": "ISO-8601 datetime",

  "required_questions": [
    {
      "question": "string",
      "answer": "string | null",
      "evidence_tier": "1 | 2 | 3 | 4 | null",
      "source": "string | null",
      "resolved": true
    }
  ],

  "contextual_questions": [
    {
      "question": "string",
      "answer": "string | null",
      "evidence_tier": "1 | 2 | 3 | 4 | null",
      "source": "string | null",
      "resolved": false
    }
  ],

  "evidence_gaps": [
    "string — description of what was attempted but not found"
  ],

  "key_findings": [
    "string — one sentence per finding, source-backed"
  ],

  "contradictions": [
    "string — documented conflicts between sources"
  ],

  "historical_precedents": [
    {
      "company": "string",
      "situation": "string",
      "outcome": "string",
      "relevance": "string"
    }
  ],

  "investigation_narrative": "string — 200–400 word factual summary of what was found. No opinions. No conclusions. Only documented findings.",

  "recommended_angle_constraints": [
    "string — what the Editorial Engine must NOT claim without direct evidence"
  ],

  "pass_through_signal": { }
}
```

**`investigation_narrative`** is the primary input to the Decision Lens.
It replaces the thin `CORE_FACT` + `CORE_TENSION` that currently drives content generation.

**`recommended_angle_constraints`** is a guardrail list.
If an article draft contains any claim that appears on this list without a cited source,
the Editorial Engine must revise or remove it.

---

## Integration with the existing pipeline

**What changes:**
- Stages 1–9 output is passed through this layer before reaching Stage 11 (publish_packages.py)
- The `investigation_narrative` replaces raw signal fields as the primary content input
- `evidence_gaps` are surfaced in the workflow step summary
- `investigation_status` gates publishing: `BLOCKED` signals are not published

**What does not change:**
- All existing enrichment fields remain in the signal record
- The Editorial Engine (hook, voice, Never Blank signature) is unchanged
- Platform adaptation logic is unchanged
- Publishing guards (`NB_RESEARCH_PUBLISH_ENABLED`, etc.) are unchanged

**New gate in publish flow:**
```python
if investigation["investigation_status"] == "BLOCKED":
    log.warning("Signal %s blocked by investigation layer", signal_id)
    continue  # skip publishing

if investigation["investigation_status"] == "INSUFFICIENT":
    log.warning("Signal %s: insufficient evidence — flagging for review", signal_id)
    # write to flagged_signals.jsonl for manual review
    continue
```

---

## What this layer does NOT do

- It does not write articles or drafts
- It does not produce opinions or editorial judgments
- It does not score signal quality (that is Stage 4 / score.py)
- It does not replace the Decision Lens — it feeds it
- It does not hallucinate answers to unanswered questions; it marks them `unresolved`
- It does not guarantee publication — it only determines whether evidence is sufficient

---

## Open questions (to be resolved before implementation)

1. **Source access strategy** — the Curiosity Engine defines *what* must be found; the Evidence Collector defines *how*. The open question is not "which APIs are available" but "what is the minimum viable evidence set that can realistically be collected at runtime?" This must be resolved during Evidence Collector specification, not here. The Curiosity Engine should never downgrade its questions based on source availability.

2. **Real-time vs. cached investigation** — should the layer attempt live web queries per run, or should a pre-fetch step cache evidence before the investigation runs? Live queries add latency and failure modes; cached evidence may be stale.

3. **`investigation_narrative` length** — 200–400 words is the current spec. The Decision Lens needs enough to reason about tensions and alternatives; too long increases token cost. Should there be a tiered length by signal type?

4. **Template extensibility** — the current six signal types cover most Never Blank content. What is the fallback template for signals that don't match any type? A generic "unknown" template risks being too shallow.

5. **Human review workflow for INSUFFICIENT signals** — when a signal is flagged `INSUFFICIENT`, where does it go? Currently there is no manual review queue in the pipeline. Does this require a new Sheets tab or a separate JSONL file?

6. **`recommended_angle_constraints` enforcement** — the spec says the Editorial Engine "must revise or remove" constrained claims. This implies a QC pass after draft generation. Is that a separate LLM call, or a post-generation regex/embedding check?

7. **Historical precedents source** — finding comparable company situations requires either a curated database or a web search step. Neither exists in the current pipeline. Should this be a static library built over time, or dynamic lookup?

---

## What comes next (recommended implementation order)

**Step 1 — Investigation planner**
Build the function that receives an enriched signal, classifies its type, and returns a structured investigation plan (list of required + contextual questions). This is pure logic, no external calls, testable immediately.

**Step 2 — Evidence fetcher**
Build the source-query layer: given a question and a signal, attempt to find evidence from available sources. Start with what's already reachable (original source URL, SOURCE_NAME, existing enrichment fields). Add web search as a second pass.

**Step 3 — Evidence scorer**
Implement the completeness scoring formula. Gate the investigation output on the threshold table. Write tests for each decision boundary.

**Step 4 — Output assembler**
Produce the full investigation JSON. Write `investigation_narrative` from resolved questions. Populate `evidence_gaps` from unresolved ones. Populate `recommended_angle_constraints`.

**Step 5 — Pipeline integration**
Insert the layer between Stage 9 (angles) and Stage 11 (publish_packages). Add `BLOCKED` / `INSUFFICIENT` gate. Surface `investigation_score` and `evidence_gaps` in the GitHub Actions step summary.

**Step 6 — Decision Lens update**
Update `publish_packages.py` blog generation to consume `investigation_narrative` as primary input instead of raw signal fields. This is the moment the quality difference becomes visible.

---

*This document is a specification only. No code, no prompts, no implementation details.
Implementation begins after this spec is reviewed and approved.*
