# Evidence Collector MVP
## Anti-Hallucination Filter for the Investigation Layer

**Version:** v0.2 — Specification Only  
**Branch:** feature/business-investigation-layer  
**Status:** Spec. No code yet.  
**Depends on:** LERA_OPERATING_SYSTEM.md (Evidence Gate, Section 9)

---

## 1. Purpose

The Evidence Collector is not a research engine.  
It is an anti-hallucination filter.

Its job is not to find everything.  
Its job is to try to destroy each hypothesis before allowing it to reach Decision Lens.

**Core philosophy:**

```
WRONG: Hypothesis → Find evidence that supports it
RIGHT: Hypothesis → Try to disprove it → If impossible, try to confirm it → If still impossible, leave Unknown
```

A hypothesis that survives a serious attempt to disprove it is fundamentally more reliable than a hypothesis that was simply confirmed. The system searches for disconfirmation first. Confirmation is the fallback.

**What it must do:**
- For each question: generate a hypothesis space (5–10 candidates), not a single hypothesis
- Rank candidates by plausibility, take the top 2–3
- Attempt to disprove each — strongest first
- If disproof fails, attempt confirmation
- If both fail, mark Unknown
- Preserve the full `hypothesis_history` — not just survivors
- Separate Evidence from Inference as distinct objects
- Block conclusions that have no source

**What it must not do:**
- Generate only 1–2 hypotheses and immediately seek confirmation
- Discard contradicted hypotheses from the record
- Treat model-generated inference as evidence
- Continue searching once the Evidence Gate already passes

The system is done when it knows enough — not when it has found everything.

---

## 2. Position in the Pipeline

```
Business Signal (HEADLINE + CORE_FACT)
      ↓
Curiosity Engine
(generates Q1–Q6 investigation questions)
      ↓
Hypothesis Generator  ← NEW MICRO-STAGE
(generates hypothesis space: 5–10 candidates per question)
      ↓
Evidence Collector  ← THIS DOCUMENT
(tries to disprove each hypothesis; preserves full history)
      ↓
Inference Layer  ← EXPLICIT SEPARATION
(labels what is concluded vs. what is evidenced)
      ↓
INVESTIGATION_EVIDENCE_GATE
(proceed / proceed_with_caveats / insufficient / blocked)
      ↓
Decision Lens
(receives hypothesis_history + surviving hypotheses + inference labels)
      ↓
Editorial Engine
```

Evidence Collector receives: `hypothesis_space` (from Hypothesis Generator)  
Evidence Collector returns: `investigation_evidence_report` with `hypothesis_history`  
Decision Lens receives: `investigation_evidence_report` only — it cannot request more research.

---

## 3. Hypothesis Generator (New Micro-Stage)

**Purpose:** Expand the hypothesis space before any evidence search begins.

The quality of the investigation is not determined by how well hypotheses are confirmed.  
It is determined by how many possible explanations were considered before the search started.

A narrow hypothesis space produces narrow conclusions — even with excellent evidence collection.

**Process:**

```
Step 1: Receive question (e.g., Q1: "Why now?")

Step 2: Generate hypothesis space
  → Generate 5–10 distinct possible explanations
  → Do not rank yet
  → Include obvious, contrarian, and structural explanations
  → Include explanations that would be uncomfortable for the company

Step 3: Cluster similar hypotheses
  → Group hypotheses that would be confirmed or denied by the same evidence
  → Merge duplicates

Step 4: Rank by prior plausibility
  → Most likely given available HEADLINE + CORE_FACT
  → Do not use NB pipeline fields (CORE_TENSION, BUSINESS_LESSON) at this stage

Step 5: Select top 2–3 for testing
  → Strongest plausibility first
  → Include at least one contrarian or uncomfortable hypothesis if present
```

**Toyota Q1 example — before (v0.1):**

```
initial_hypothesis: "BEV adoption slower than forecast"
second_hypothesis:  "Competitor EV production problems"
```

Two hypotheses, both generated in one pass, both moderately plausible.

**Toyota Q1 example — after (v0.2):**

```
Hypothesis space generated (unranked):
1. BEV adoption fell below 2021 forecasts (infrastructure gap)
2. Toyota lacked capital to fund full EV pivot
3. Competitor EV production failures let Toyota win by default
4. Toyota's manufacturing lock-in made pivot structurally impossible
5. Toyota CEO personally opposed BEV and imposed strategy top-down
6. Toyota was protecting supplier relationships (keiretsu)
7. Toyota's internal research predicted infrastructure gap years earlier
8. Toyota misjudged and got lucky — hybrid demand was not forecasted correctly
9. Toyota's deliberate multi-pathway strategy anticipated multiple consumer segments

Ranked by plausibility: 9 > 1 > 3 > 7 > 2 > 4 > 5 > 6 > 8

Selected for testing: 9, 1, 2 (includes one potentially embarrassing: 2 — "lacked capital")
```

The difference: hypothesis 2 ("lacked capital") and 4 ("manufacturing lock-in") were explicitly generated and then tested — and both were contradicted by evidence. This made the surviving hypothesis (9 + 1) demonstrably stronger.

---

## 4. Evidence Collection Workflow

For each signal, after Hypothesis Generator has produced the ranked hypothesis space:

```
Step 1: Attempt to DISPROVE strongest hypothesis
  → Generate 1–2 disconfirmation queries specifically
  → Search Tier 1–2 for evidence that would make the hypothesis false
  → If found: hypothesis is contradicted — log to hypothesis_history, move to next

Step 2: If disproof fails, attempt to CONFIRM
  → Generate 1–2 confirmation queries
  → Search Tier 1–2 for supporting evidence
  → If found: hypothesis is confirmed — log to hypothesis_history as "survived"

Step 3: If both fail
  → Mark hypothesis as "unclear"
  → Do not promote to safe_conclusions
  → Log to hypothesis_history as "unresolved"

Step 4: Repeat for hypotheses #2 and #3

Step 5: Construct Inference (see Section 5)
  → From confirmed/survived hypotheses, derive what can be concluded
  → Label every conclusion: Evidence vs. Inference
  → Evidence = directly stated in source
  → Inference = concluded from evidence + reasoning

Step 6: Run Evidence Gate
  → Check rules (see LERA_OPERATING_SYSTEM.md Section 9)
  → Assign: PROCEED / PROCEED_WITH_CAVEATS / INSUFFICIENT / BLOCKED

Step 7: Compile investigation_evidence_report
```

**Search escalation:**
- Search Tier 1 first
- Only escalate to Tier 2 if Tier 1 returns nothing relevant
- Only use Tier 3 for historical context or supporting inference
- Tier 4: generates new hypotheses only, never confirms

**Stop condition:** Stop as soon as Evidence Gate reaches `PROCEED`.  
Do not collect additional sources after gate is satisfied.

---

## 5. Evidence vs. Inference — Explicit Separation

This is one of the most important distinctions in the entire architecture.

**Evidence** is what a source directly states.  
**Inference** is what the system concludes from evidence plus reasoning.

They are not the same. They must never be merged silently.

```
Evidence:
  Akio Toyoda, Japan Automobile Manufacturers Association, Dec 2021:
  "If we are asked whether BEVs alone can achieve carbon neutrality, I believe the answer is no."
  Source: Reuters, Tier 2.

Inference derived from this evidence:
  Toyota's leadership had publicly committed to a multi-pathway strategy before most competitors.
  Motive status: supported_inference (evidence does not state "we chose multi-pathway"; it states a belief)
```

**Rules:**

1. Every `safe_conclusion` must state whether it is Evidence or Inference
2. Evidence requires a source URL — always
3. Inference requires the evidence it was derived from — always
4. An inference cannot be upgraded to evidence by restating it more confidently
5. An inference cannot be derived from another inference (no inference chains)
6. If the only support for an inference is Tier 4, it is `speculation`

**The Inference object:**

```json
{
  "inference_id": "I-Q3-01",
  "derived_from_evidence": ["E-Q3-01", "E-Q3-02"],
  "inference_text": "Toyota's leadership viewed BEV-only transition as premature given infrastructure constraints",
  "motive_status": "supported_inference",
  "confidence": "high",
  "alternative_inference": "Toyota maintained hybrid because internal manufacturing economics made pivot unattractive",
  "alternative_status": "contradicted",
  "alternative_contradicted_by": "E-Q3-03"
}
```

Decision Lens receives both the evidence objects and the inference objects, labeled distinctly. It knows what was said versus what was concluded.

---

## 6. Query Generation Rules

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

### 7a. hypothesis_space

Generated by Hypothesis Generator, consumed by Evidence Collector.

```json
{
  "signal_id": "string",
  "headline": "string",
  "core_fact": "string",
  "questions": [
    {
      "question_id": "Q1",
      "question": "Why now?",
      "hypothesis_space": [
        {
          "hypothesis_id": "H-Q1-01",
          "hypothesis": "string",
          "plausibility_rank": 1,
          "type": "structural | behavioral | circumstantial | contrarian"
        }
      ],
      "selected_for_testing": ["H-Q1-01", "H-Q1-02", "H-Q1-03"],
      "disconfirmation_queries": ["string", "string"],
      "confirmation_queries": ["string", "string"],
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
      "surviving_hypothesis": "string | null",
      "surviving_hypothesis_id": "H-Q1-03",
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

  "hypothesis_history": [
    {
      "question_id": "Q1",
      "hypothesis_id": "H-Q1-01",
      "hypothesis": "string",
      "test_type": "disconfirmation_first",
      "status": "contradicted | survived | unresolved",
      "evidence": "string",
      "source_url": "string | null",
      "implication": "string — what this contradiction or survival means for the investigation"
    }
  ],

  "inferences": [
    {
      "inference_id": "I-Q3-01",
      "question_id": "Q3",
      "derived_from_evidence": ["E-Q3-01"],
      "inference_text": "string",
      "motive_status": "stated | supported_inference | speculation",
      "confidence": "high | medium | low",
      "alternative_inference": "string | null",
      "alternative_status": "contradicted | unresolved | null"
    }
  ],

  "timeline": ["string"],

  "safe_conclusions": [
    {
      "conclusion": "string",
      "type": "evidence | inference",
      "source_url": "string | null",
      "inference_id": "string | null"
    }
  ],

  "blocked_conclusions": ["string"],
  "unsupported_claims": ["string"],
  "unknowns": ["string"],

  "proceed": "PROCEED | PROCEED_WITH_CAVEATS | INSUFFICIENT | BLOCKED",
  "gate_notes": "string"
}
```

### 7c. safe_conclusions

A conclusion is safe if:
- `type: evidence` — has a source URL, Tier 1 or Tier 2
- `type: inference` — derived from confirmed evidence, motive_status is `stated` or `supported_inference`, no inference chains

Decision Lens adds appropriate framing and hedging. The system does not add hedges — it labels.

### 7d. blocked_conclusions

A conclusion is blocked if:
- Derived from an `unresolved` or `contradicted` hypothesis
- Its only source is Tier 4
- Its motive status is `speculation`
- Q3 is unanswered and this conclusion depends on the constraint

Blocked conclusions are logged and passed to Decision Lens as reference. They cannot appear in the final article as stated fact.

### 7e. hypothesis_history

`hypothesis_history` is append-only and includes every hypothesis that was tested — contradicted, survived, and unresolved.

Decision Lens receives the full history. It sees not just what the system concluded, but which explanations were considered and eliminated. This makes surviving hypotheses demonstrably stronger — they are not simply plausible, they are what remains after alternatives were actively rejected.

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

### Phase 1 — Offline MVP: hypothesis space + manual sources
**Goal:** Test the full schema including `hypothesis_history` with manually provided sources. No live search.

Implementation:
1. Curiosity Engine generates Q1–Q6 questions
2. Hypothesis Generator produces `hypothesis_space` (5–10 per question, ranked, top 3 selected)
3. Human provides source URLs manually per signal
4. Evidence Collector evaluates provided sources — attempts disconfirmation first, then confirmation
5. Returns `investigation_evidence_report` with full `hypothesis_history`
6. Inferences are labeled explicitly, separated from Evidence
7. Evidence Gate runs
8. Decision Lens operates on `safe_conclusions` only

**What this proves:**
- Hypothesis space generation works and produces non-obvious candidates
- `hypothesis_history` correctly captures contradicted hypotheses
- Evidence/Inference separation is enforced
- Gate blocks correctly

**What this does not prove:** That automated search finds the right sources.

**Toyota validation test:**
Run Toyota through Phase 1. Verify that hypotheses "lacked capital" and "manufacturing lock-in" are generated in hypothesis space, tested, contradicted, and logged — before "deliberate multi-pathway strategy" is promoted as the surviving hypothesis.

### Phase 2 — Web search for Q3 only
**Goal:** Automate evidence search for Q3 (gate-critical question).

Implementation:
1. For each Q3 hypothesis (top 2): generate 1 disconfirmation query + 1 confirmation query
2. Execute search (WebSearch or equivalent)
3. Evaluate top 3 results per query
4. Return `evidence_status` for Q3
5. All other questions: Phase 1 manual flow

**Why Q3 first:** Q3 is the gate-critical question. If Q3 evidence is missing, the gate cannot pass. Automating Q3 alone blocks the most common failure: writing a constraint claim with no source.

### Phase 3 — Full Q1–Q6 automated search with disconfirmation-first
**Goal:** Automate all six questions with the "try to disprove first" search strategy.

Implementation:
1. Hypothesis Generator runs for all questions
2. For each selected hypothesis: disconfirmation queries run first
3. If disconfirmation fails: confirmation queries run
4. Cost controls applied (max 18 queries total, early stop at PROCEED)
5. Full `investigation_evidence_report` + `hypothesis_history` generated automatically

### Phase 4 — Decision Lens integration
**Goal:** Decision Lens reads `investigation_evidence_report`, receives full `hypothesis_history`, generates interpretation from `safe_conclusions` + labeled `inferences` only.

Decision Lens knows what was considered and eliminated — not just what survived. This allows it to reference why certain explanations were rejected, which often strengthens the surviving interpretation.

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
