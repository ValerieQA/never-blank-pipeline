# Lera Operating System
## The Intellectual Architecture of Never Blank

**Version:** v0.1 — Specification Only  
**Branch:** feature/business-investigation-layer  
**Status:** Under development. Not merged to main.

---

## 1. Purpose

Never Blank does not explain business events.  
It reconstructs the sequence of decisions that made those events likely.

---

## 2. The Foundational Principle

Most systems ask: **What happened?**

Never Blank asks: **What sequence of decisions produced this outcome — and why were those decisions rational given the constraints that existed?**

This is not a stylistic preference. It is an architectural constraint.

A system that explains events produces analysis.  
A system that reconstructs decisions produces understanding.

Never Blank is the second kind.

---

## 3. What "Understanding" Means Here

An event is a data point.  
A decision is a choice made under constraint.  
A sequence of decisions is an organizational logic.

Never Blank is not interested in the event.  
It is interested in the organizational logic that made the event nearly inevitable.

**Example:**

> A company announces 14% layoffs.

Wrong question: *Why did they lay people off?*  
Right question: *What sequence of decisions — made 6 to 24 months earlier — made this outcome structurally unavoidable?*

The layoff is the last chapter. Never Blank wants to read the book.

---

## 4. Investigation Flow

Every signal must pass through this sequence before any interpretation is permitted.

```
Observed Outcome
      ↓
Reconstruct Timeline
(What decisions preceded this? How far back does the chain go?)
      ↓
Identify Decisions
(What was chosen? By whom? At what cost?)
      ↓
Identify Constraints
(What limitations shaped those choices? What was not negotiable?)
      ↓
Identify Rejected Alternatives
(What did they consciously not do? Why?)
      ↓
Identify Protected Priority
(What were they unwilling to sacrifice — even when under pressure?)
      ↓
Identify Who Pays
(Who absorbs the cost of this decision, and when will they know?)
      ↓
Evidence Completeness Check
(Does the investigation meet the minimum threshold? See Section 6.)
      ↓
Decision Lens
(Only now: what does this mean?)
```

**The flow is not optional.** A system that skips Reconstruct Timeline cannot reach a valid Decision Lens output. A system that skips Rejected Alternatives will always produce the most obvious interpretation, not the most accurate one.

---

## 5. Universal Investigation Questions

These questions operationalize the Investigation Flow. They are ordered: each question deepens what the previous one revealed.

**Q1 — Why now?**  
Why did this happen at this specific moment, and not six months earlier or later?  
*Purpose: surfaces timing logic, which almost always reveals constraint or opportunity.*

**Q2 — What changed?**  
What shifted in the preceding months or years that made this decision possible or necessary?  
*Purpose: finds the enabling condition. The event didn't emerge from nothing.*

**Q3 — What constraint did they see?**  
What limitation, risk, or asymmetric opportunity did the company perceive that most observers missed?  
*Purpose: this is where the actual insight lives. The insight is almost never in the decision itself — it is in what they saw that others didn't.*

**Q4 — What did they deliberately reject?**  
What alternative did they consciously not choose, and what does that rejection reveal?  
*Purpose: the rejected alternative often contains the real decision. The announcement tells you what they did. The rejection tells you what they believed.*

**Q5 — What were they protecting?**  
What was more important to them than the thing they sacrificed?  
Not revenue. Not market share. The specific thing they would not trade.  
*Purpose: reveals the organizational priority that made this choice rational. Without it, the decision looks arbitrary.*

**Q6 — Who ultimately pays?**  
Who absorbs the cost of this decision — and when will the consequences become visible?  
*Purpose: forces the investigation past the press release. Every decision transfers cost somewhere. Finding where is finding the truth.*

**Q7 — What should we see next?**  
If this decision is correct and the reasoning holds, what observable outcome should appear in 6 to 18 months?  
*Purpose: converts analysis into a testable hypothesis. Never Blank is not a commentator of the past — it is an observer of what logic implies about the future.*

---

### On Q1: the discipline of the second hypothesis

Q1 is not answered by finding a convenient explanation.

The first answer to "Why now?" is almost always the official narrative: the event, the catalyst, the press release.

The second answer is the real one.

**Required discipline:** After the first hypothesis, the system must ask: *Is this the cause, or is this the occasion? What else could explain why exactly now?*

An occasion gives permission. A cause provides necessity.  
Never Blank is looking for necessity, not permission.

---

### The question that surfaces organizational logic

After Q1–Q6, the system must ask one more question before passing to Decision Lens:

**Q0 — What does this decision reveal about how this organization makes decisions?**

This question is not about the event. It is about the system that produced the event.

It is the question that turns a news analysis into a Never Blank insight.

---

## 6. The Evidence Problem

Q1–Q6 are a question framework, not a research output.

A system that answers Q1–Q6 from internal model knowledge produces well-formatted guesses. That is not investigation. That is plausible confabulation with structure.

**The critical distinction:**

```
WRONG:  Q1–Q6 → answers
RIGHT:  Q1–Q6 → hypotheses → evidence search → confirmed / contradicted / unclear → conclusion
```

Every answer to Q1–Q6 must be backed by an external source or explicitly labeled as inference. If a hypothesis is contradicted by evidence, the contradiction must be preserved — not rewritten into a cleaner answer.

**Example of correct behavior:**

> Hypothesis: Toyota avoided full EV transition because it lacked capital.  
> Evidence found: Toyota was simultaneously investing billions into EV battery plants.  
> Status: **contradicted**  
> Correct conclusion: Lack of capital is not the explanation. Evidence points toward a deliberate multi-pathway strategy instead.

The contradiction is more valuable than a clean narrative. It eliminates a wrong answer and forces the investigation toward the real one.

---

## 7. Source Hierarchy

Not all sources are equal. The tier determines what a source can do.

| Tier | Source Types | What It Can Do |
|---|---|---|
| **Tier 1** | Company filings, earnings calls, official statements, investor presentations, regulatory filings | Confirm facts and stated company positions |
| **Tier 2** | Reuters, AP, Bloomberg, WSJ, Financial Times, CNBC, TechCrunch, industry-specific reputable media | Confirm reported facts; contextualize events |
| **Tier 3** | Analyst reports, expert commentary, trade publications | Support interpretation; cannot confirm primary facts alone |
| **Tier 4** | Glassdoor, Blind, Reddit, X/Twitter, employee reviews, founder interviews, podcasts | Generate hypotheses only; cannot confirm facts |

**Rule:** Tier 4 sources can raise a question. They cannot close one.

**Rule:** A claim confirmed only by Tier 3 or Tier 4 must be labeled as inferred, not stated.

---

## 8. Motive Classification

Every claim about why a company or person acted must be labeled with one of three epistemic statuses:

| Status | Definition | Example |
|---|---|---|
| **stated** | The company or a named representative explicitly said this | "Toyota CEO stated they believe hybrid is the right transition path" (earnings call) |
| **supported inference** | Multiple independent sources and the available evidence point in this direction | "Toyota's continued hybrid investment while competitors pivoted suggests deliberate multi-pathway strategy" |
| **speculation** | Plausible but not supported by available evidence | "Toyota may have wanted to preserve supplier relationships" |

**Rule:** Speculation cannot appear in the final article as fact.  
**Rule:** Supported inferences must be labeled as such in the investigation record, even if stated as conclusions in editorial output.  
**Rule:** Q4 (rejected alternatives) is almost always inferred. It must be labeled as such unless the company explicitly disclosed its alternatives.

---

## 9. INVESTIGATION_EVIDENCE_GATE

This gate sits between the Curiosity Engine and Decision Lens. Decision Lens cannot activate until the gate passes.

### Gate Rules

1. At least 4 of Q1–Q6 must have `evidence_status = confirmed` or `supported`.
2. Q3 ("constraint they saw") must have at least one Tier 1 or Tier 2 source.
3. Q4 ("rejected alternative") must be labeled `inferred` unless directly evidenced.
4. No motive claim with status `speculation` may pass to Decision Lens as a conclusion.
5. Contradicted hypotheses must be logged, not discarded.
6. If `evidence_status = contradicted` for Q3 or Q6, the investigation is BLOCKED until an alternative hypothesis is formed and tested.

### Gate Outcomes

| Outcome | Condition |
|---|---|
| **PROCEED** | ≥4 questions confirmed/supported; Q3 and Q6 have Tier 1–2 sources |
| **PROCEED_WITH_CAVEATS** | ≥4 questions confirmed/supported; Q3 or Q6 is inference-only (Tier 3–4) |
| **INSUFFICIENT** | 3 or fewer questions confirmed; investigation must continue |
| **BLOCKED** | Q3 or Q6 contradicted; or active speculation in core conclusions |

---

## 10. Output: Investigation Evidence Report

The Curiosity Engine delivers this object to Decision Lens. Decision Lens may not request modifications — it works with what it receives, including gaps and contradictions.

```json
{
  "signal_id": "...",
  "headline": "...",
  "investigation_status": "proceed | proceed_with_caveats | insufficient | blocked",

  "questions": [
    {
      "question_id": "Q1",
      "question": "Why now?",
      "initial_hypothesis": "...",
      "second_hypothesis": "...",
      "evidence_found": "...",
      "source_url": "...",
      "source_type": "tier_1 | tier_2 | tier_3 | tier_4",
      "evidence_status": "confirmed | contradicted | unclear | inferred",
      "motive_status": "stated | supported_inference | speculation | not_applicable",
      "confidence": "high | medium | low",
      "notes": "..."
    }
  ],

  "timeline": [...],

  "contradicted_hypotheses": [
    {
      "hypothesis": "...",
      "contradicting_evidence": "...",
      "source_url": "...",
      "implication": "..."
    }
  ],

  "unsupported_claims": ["..."],
  "safe_conclusions": ["..."],
  "blocked_conclusions": ["..."],

  "unknowns": ["..."],
  "proceed": "PROCEED | PROCEED_WITH_CAVEATS | INSUFFICIENT | BLOCKED"
}
```

**Decision Lens receives this and may not:**
- Request additional research
- Discard contradicted hypotheses
- Treat `speculation` as `supported_inference`
- Generate conclusions from `blocked_conclusions`

The unknowns, contradictions, and gaps are part of the output. They shape the editorial layer — honest caveats are a feature, not a failure.

---

## 11. What the System Is Prohibited From Doing

These are not style guidelines. They are hard constraints on the investigation layer.

**The system may not:**

1. **Answer Q1–Q6 from model intuition without evidence.**  
   A plausible answer without a source is a hypothesis. It must be labeled as such and tested before it can pass the Evidence Gate.

2. **Rewrite a contradicted hypothesis into a clean answer.**  
   If evidence contradicts the hypothesis, the contradiction is the finding. It goes into `contradicted_hypotheses`, not the trash.

3. **Explain an event without reconstructing the decision chain.**  
   Describing what happened is summarization. The system reconstructs decisions, not events.

4. **Accept the first explanation of "Why now?"**  
   Q1 requires a second hypothesis. The first answer is almost always the official narrative.

5. **Invent motives for individuals.**  
   The investigation works at organizational logic level. "The CEO wanted to" requires Tier 1 evidence or must be labeled speculation.

6. **Treat absence of evidence as evidence of absence.**  
   If a question cannot be answered, the system names what is unknown. It does not fill the gap.

7. **Confuse the event with the decision.**  
   The event is the outcome. The decisions that produced it were made earlier, under different information.

8. **Stop at the first coherent narrative.**  
   A narrative that explains everything is usually wrong. Investigation is complete only when it has identified the constraint that made other choices unavailable.

---

## 12. The Contract With Decision Lens

The Investigation Layer delivers exactly one thing: `investigation_evidence_report` (see Section 10).

Decision Lens receives this record and operates under the following constraints:

- **May use:** `safe_conclusions`, confirmed/supported Q-answers, timeline, unknowns
- **May not use as fact:** `blocked_conclusions`, speculation-labeled claims, contradicted hypotheses
- **Must acknowledge in output:** any `proceed_with_caveats` condition, any material unknown
- **Must log:** all `contradicted_hypotheses` for future signal pattern analysis

If `proceed = BLOCKED`, Decision Lens returns the signal to Curiosity Engine with a specific gap description. It does not generate interpretation from a blocked investigation.

---

## 13. What This Layer Does Not Do

The Investigation Layer:

- Does **not** write content
- Does **not** determine editorial angle
- Does **not** decide which platform to publish on
- Does **not** evaluate whether the signal is "interesting"
- Does **not** produce a Business Lesson
- Does **not** generate a Never Blank Angle

All of these are downstream responsibilities.

The Investigation Layer has one job: reconstruct what happened and why, with evidence, and name what remains unknown.

---

## 14. Why This Matters

Most business content starts from the event and asks: *What does this mean?*

Never Blank starts from the event and asks: *What sequence of decisions produced this — and why were those decisions rational given what the organization knew and couldn't afford to lose?*

That is a different question.  
It produces a different kind of understanding.  
And it is the reason Never Blank content doesn't sound like news analysis.

It sounds like someone who read the organization, not the headline.

The Evidence Gate is what enforces this. Without it, the system produces plausible-sounding analysis built on unverified assumptions. With it, the system either finds real evidence or names what it doesn't know.

Both are acceptable outputs.  
Confident analysis built on guesses is not.

---

## Appendix: Failure Modes to Monitor

As this layer is implemented, watch for these failure patterns:

| Failure Mode | Symptom | Fix |
|---|---|---|
| Timeline collapse | Investigation skips Reconstruct Timeline and goes directly to Q1 | Enforce Timeline Reconstruction as a separate, logged step |
| First-hypothesis lock | Q1 answered once, second hypothesis never generated | Require `second_hypothesis` field before Q1 marked complete |
| Constraint invention | Q3 answer asserts company belief without Tier 1–2 source | Q3 requires external evidence; inference must be labeled |
| Missing rejection | Q4 answered as "no alternatives existed" | Flag; this answer is almost never supported by evidence |
| Cost displacement | Q6 answered as "costs are shared broadly" | Force specificity: who, how much, when, which source |
| Premature proceed | Gate passes despite Q3 or Q6 empty | Hard block in pipeline; gate rules are not advisory |
| Speculation laundering | Speculation labeled as inference in successive passes | Motive status is immutable once assigned; cannot be upgraded without new Tier 1–2 evidence |
| Contradiction erasure | Contradicted hypothesis rewritten into coherent narrative | `contradicted_hypotheses` is append-only; items cannot be removed, only annotated |

---

*This document describes the intellectual architecture, not the implementation. Code, prompts, and pipeline integration are defined separately and must conform to the contract specified here.*
