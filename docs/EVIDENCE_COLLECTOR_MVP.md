# Evidence Collector MVP
## Anti-Hallucination Filter for the Investigation Layer

**Version:** v0.1 — Specification Only  
**Branch:** feature/business-investigation-layer  
**Status:** Spec. No code yet.  
**Depends on:** LERA_OPERATING_SYSTEM.md (Evidence Gate, Section 9)

---

## 1. Purpose

The Evidence Collector is not a research engine.  
It is an anti-hallucination filter.

Its job is not to find everything.  
Its job is to prevent the system from writing an article based on an unverified hypothesis.

**What it must do:**
- Generate search queries from Q1–Q6 hypotheses
- Find Tier 1–2 sources that confirm, contradict, or fail to support each hypothesis
- Return structured evidence status per question
- Block conclusions that have no source

**What it must not do:**
- Attempt exhaustive research
- Replace Q1–Q6 reasoning with raw search results
- Accept Tier 4 sources as confirmation
- Continue searching once the Evidence Gate already passes

The system is done when it knows enough — not when it has found everything.

---

## 2. Position in the Pipeline

```
Business Signal (HEADLINE + CORE_FACT)
      ↓
Curiosity Engine
(generates Q1–Q6 hypotheses + second hypotheses)
      ↓
Evidence Collector  ← THIS DOCUMENT
(tests hypotheses against sources)
      ↓
INVESTIGATION_EVIDENCE_GATE
(proceed / proceed_with_caveats / insufficient / blocked)
      ↓
Decision Lens
(interprets confirmed evidence only)
      ↓
Editorial Engine
```

Evidence Collector receives: `evidence_query_plan`  
Evidence Collector returns: `investigation_evidence_report`  
Decision Lens receives: `investigation_evidence_report` only — it cannot request more research.

---

## 3. Workflow

For each signal:

```
Step 1: Receive hypotheses
  ← Q1–Q6: initial_hypothesis + second_hypothesis (from Curiosity Engine)

Step 2: Generate search queries
  → 1–3 queries per hypothesis
  → Prioritize Tier 1–2 search targets first

Step 3: Execute searches
  → Search Tier 1 first (company filings, official statements)
  → If insufficient, search Tier 2 (major media)
  → If still unclear, search Tier 3 (analyst/trade)
  → Use Tier 4 only to refine hypothesis — never to confirm

Step 4: Evaluate each result
  → confirmed: source directly supports hypothesis
  → contradicted: source contradicts hypothesis — log to contradicted_hypotheses
  → unclear: source found but does not resolve the question
  → no_source: no relevant source found

Step 5: Run Evidence Gate
  → Check gate rules (see LERA_OPERATING_SYSTEM.md Section 9)
  → Assign: PROCEED / PROCEED_WITH_CAVEATS / INSUFFICIENT / BLOCKED

Step 6: Compile output
  → investigation_evidence_report (see Section 7)
  → safe_conclusions
  → blocked_conclusions
  → contradicted_hypotheses
```

**Stop condition:** Stop searching as soon as the Evidence Gate passes (`PROCEED`).  
Do not collect more sources after the gate condition is satisfied.

---

## 4. Query Generation Rules

For each Q1–Q6 hypothesis, generate 1–3 search queries.

**Query construction principles:**
- Query 1: most specific — company name + action + date range
- Query 2: broader context — industry + trend + relevant period
- Query 3 (optional): alternative framing — if first two return nothing relevant

**Query targets by tier:**

| Tier | Search approach |
|---|---|
| Tier 1 | `site:sec.gov`, `site:[company].com/investors`, earnings call transcripts, official press releases |
| Tier 2 | Standard news search — Bloomberg, Reuters, FT, WSJ, CNBC, TechCrunch |
| Tier 3 | Analyst report databases, trade publications, industry journals |
| Tier 4 | Reddit, Glassdoor, X/Twitter — only for hypothesis generation, not confirmation |

**Per-question query guidance:**

| Question | Primary search target | Why |
|---|---|---|
| Q1 — Why now? | News around event date ±90 days; earnings calls in same period | Timing context is usually discussed publicly |
| Q2 — What changed? | Industry reports 6–24 months prior; company strategy statements | Background shifts are often documented |
| Q3 — Constraint they saw | Company filings, investor presentations, CEO statements | Constraints are sometimes disclosed; often inferable from actions |
| Q4 — Rejected alternative | M&A records, strategy announcements, analyst coverage | Rarely stated directly — usually inferred; must be labeled |
| Q5 — Protected priority | Long-term strategy docs, multi-year investment patterns | Capital allocation reveals priorities better than statements |
| Q6 — Who pays | Financial reporting, workforce data, market impact analysis | Consequences are usually measurable |
| Q7 — What next | Forward guidance, analyst forecasts, industry analyst calls | Observable predictions require forward-looking sources |

---

## 5. Evidence Evaluation Rules

**Rule 1: No source URL = no claim.**  
A finding without a source is a hypothesis. It must be labeled `unclear`, not `confirmed`.

**Rule 2: Contradiction must be preserved.**  
If a source contradicts the hypothesis, the contradiction goes into `contradicted_hypotheses`. It cannot be rewritten or discarded. It is append-only.

**Rule 3: Tier 4 cannot confirm.**  
A claim confirmed only by Tier 4 sources receives `evidence_status = unclear` and `motive_status = speculation`. It may inform a new hypothesis but cannot close one.

**Rule 4: Paywalled source handling.**  
If only the headline and snippet are accessible:
- The snippet may support `unclear` status
- It cannot support `confirmed` status
- Log as: `source_accessible: false`, `snippet_only: true`

**Rule 5: Stale source.**  
A source older than 36 months for rapidly evolving topics (AI, EV, regulatory) must be flagged with `source_age_warning: true`. It can be used for historical timeline reconstruction but not for current-state confirmation.

**Rule 6: Conflicting evidence.**  
If two Tier 1–2 sources directly contradict each other:
- Log both
- Set `evidence_status = contradicted`
- Set `confidence = low`
- Do not resolve — surface the conflict to Decision Lens

**Rule 7: Motive status is immutable.**  
Once assigned, motive status cannot be upgraded without a new Tier 1–2 source that directly addresses intent. `speculation` does not become `supported_inference` through repeated inference.

---

## 6. Failure Behavior

| Failure | Behavior |
|---|---|
| Search returns no results | `evidence_status = unclear`, `no_source = true`. Do not invent source. |
| Source is paywalled | Log URL + snippet. Flag `snippet_only: true`. Cannot confirm — only inform. |
| Two sources conflict | Log both. Set `evidence_status = contradicted`. Surface conflict to Decision Lens. |
| Source is Tier 4 only | Log as hypothesis support. Cannot set `confirmed`. |
| Source is stale (>36mo for fast-moving topics) | Flag `source_age_warning`. Use for timeline only. |
| Web search fails (timeout, API error) | Log `search_failed: true`. Do not retry more than once. Mark question `unclear`. |
| All searches return irrelevant results | Mark `evidence_status = unclear`. Do not force relevance. |
| Q3 returns no Tier 1–2 source | Gate cannot be `PROCEED`. Status: `PROCEED_WITH_CAVEATS` at best, `INSUFFICIENT` if confidence is low. |

---

## 7. JSON Schema

### 7a. evidence_query_plan

Generated by Curiosity Engine, consumed by Evidence Collector.

```json
{
  "signal_id": "string",
  "headline": "string",
  "core_fact": "string",
  "questions": [
    {
      "question_id": "Q1",
      "question": "Why now?",
      "initial_hypothesis": "string",
      "second_hypothesis": "string",
      "search_queries": [
        "string",
        "string"
      ],
      "tier_priority": ["tier_1", "tier_2", "tier_3"]
    }
  ]
}
```

### 7b. investigation_evidence_report

Generated by Evidence Collector, consumed by Decision Lens.

```json
{
  "signal_id": "string",
  "headline": "string",
  "investigation_status": "proceed | proceed_with_caveats | insufficient | blocked",

  "questions": [
    {
      "question_id": "Q1",
      "question": "Why now?",
      "initial_hypothesis": "string",
      "second_hypothesis": "string",
      "evidence_found": "string",
      "source_url": "string | null",
      "source_type": "tier_1 | tier_2 | tier_3 | tier_4 | none",
      "source_accessible": true,
      "snippet_only": false,
      "source_age_warning": false,
      "evidence_status": "confirmed | contradicted | unclear | inferred",
      "motive_status": "stated | supported_inference | speculation | not_applicable",
      "confidence": "high | medium | low",
      "search_failed": false,
      "notes": "string"
    }
  ],

  "timeline": ["string"],

  "contradicted_hypotheses": [
    {
      "question_id": "Q1",
      "hypothesis": "string",
      "contradicting_evidence": "string",
      "source_url": "string",
      "implication": "string"
    }
  ],

  "safe_conclusions": ["string"],
  "blocked_conclusions": ["string"],
  "unsupported_claims": ["string"],
  "unknowns": ["string"],

  "proceed": "PROCEED | PROCEED_WITH_CAVEATS | INSUFFICIENT | BLOCKED",
  "gate_notes": "string"
}
```

### 7c. safe_conclusions

A conclusion is safe if:
- It is derived from a `confirmed` or `supported_inference` finding
- Its source is Tier 1 or Tier 2
- Its motive status is `stated` or `supported_inference`

Format: plain string — one conclusion per entry. No hedges added by the system. Decision Lens adds appropriate framing.

### 7d. blocked_conclusions

A conclusion is blocked if:
- It is derived from an `unclear` or `contradicted` finding
- Its only source is Tier 4
- Its motive status is `speculation`
- Q3 is unanswered and this conclusion depends on the constraint

Blocked conclusions are logged and passed to Decision Lens as reference. They cannot appear in the final article as fact.

---

## 8. Cost Controls

**Max queries per signal:** 18 (3 queries × 6 questions)  
**Max sources evaluated per question:** 3  
**Early stop:** Stop searching when Evidence Gate condition `PROCEED` is met  
**Tier escalation:** Only escalate to next tier if current tier returns no relevant result  
**No redundant search:** If Q1 and Q2 share the same source URL, do not re-fetch  

**Token budget guidance (for implementation):**
- Query generation: low cost (structured output from hypothesis)
- Source retrieval and snippet extraction: variable
- Evidence evaluation per source: ~200–400 tokens
- Full report compilation: ~500 tokens
- Expected total per signal: 2,000–6,000 tokens depending on source availability

---

## 9. Implementation Plan (Smallest Path First)

### Phase 0 — Spec only (current)
This document. No code.

### Phase 1 — Offline MVP (no live web search)
**Goal:** Test the schema and gate logic with manually provided sources.

Implementation:
1. Curiosity Engine generates `evidence_query_plan` with hypotheses (no search yet)
2. Human or tool provides source URLs manually per signal
3. Evidence Collector evaluates provided sources against hypotheses
4. Returns `investigation_evidence_report`
5. Decision Lens operates on confirmed findings only

**What this proves:** The schema works. The gate blocks correctly. Speculation is separated from evidence.  
**What this does not prove:** That automated search finds the right sources.

### Phase 2 — Web search integration (one question at a time)
**Goal:** Automate evidence search for Q3 only (the highest-value question).

Implementation:
1. For Q3 hypothesis, generate 2 search queries
2. Execute search via available tool (WebSearch or similar)
3. Evaluate top 3 results
4. Return `evidence_status` for Q3
5. All other questions remain manual or hypothesis-only

**Why Q3 first:** Q3 is the gate-critical question. If Q3 evidence is missing, no article is possible. Automating Q3 alone already prevents the most common failure: publishing a constraint claim with no source.

### Phase 3 — Full Q1–Q6 automated search
**Goal:** Automate all six questions.

Implementation:
1. Run Phase 1–2 logic for all questions
2. Apply cost controls (max 18 queries, early stop)
3. Full `investigation_evidence_report` generated automatically

### Phase 4 — Decision Lens integration
**Goal:** Decision Lens reads `investigation_evidence_report` and generates interpretation from `safe_conclusions` only.

---

## 10. What This Is Not

The Evidence Collector MVP is not:
- A comprehensive research agent
- A replacement for human editorial judgment
- A guarantee that the article is factually complete
- A system that finds everything worth knowing

It is an anti-hallucination filter.

It guarantees one thing: **if a claim appears in the final article as fact, there is a source URL that supports it.**

That is the only guarantee. It is sufficient for now.

---

*Implementation begins after this spec is reviewed and approved.*
