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

## 6. Evidence Completeness

The system may not proceed to Decision Lens unless the following conditions are met.

**Minimum threshold:** The investigation has produced defensible answers to at least 4 of the 6 questions Q1–Q6.

**Required threshold:** Q3 (constraint) and Q6 (who pays) must always be answered. These two cannot be substituted or skipped. If either is unanswerable, the evidence is insufficient.

**Prohibited states:**

| State | Action |
|---|---|
| Fewer than 4 questions answered | Block. Return to evidence collection. |
| Q3 unanswered | Block. The insight cannot exist without it. |
| Q6 unanswered | Block. The analysis is incomplete without consequence. |
| Q4 answered with "no alternative existed" | Flag for human review. This is almost never true. |
| Q1 answered only with official narrative | Flag. Require second hypothesis before proceeding. |

---

## 7. What the System Is Prohibited From Doing

These are not style guidelines. They are hard constraints on the investigation layer.

**The system may not:**

1. **Explain an event without reconstructing the decision chain.**  
   Describing what happened is not analysis. It is summarization.

2. **Accept the first explanation of "Why now?"**  
   The first explanation is the press release. The investigation is not complete until a second hypothesis has been generated and tested.

3. **Invent motives for individuals.**  
   The investigation operates at the level of organizational logic, not personal intent. "The CEO wanted to" is not evidence. "The organization was constrained by X and chose Y over Z" is.

4. **Treat the absence of evidence as evidence of absence.**  
   If a question cannot be answered, the system must name what is unknown — not fill the gap with inference.

5. **Confuse the event with the decision.**  
   The layoff is not the decision. The layoff is the outcome. The decision was made months earlier, under different circumstances, by people who could not see this moment coming.

6. **Stop at the first coherent narrative.**  
   A narrative that explains everything is usually wrong. The investigation is complete only when it has found the constraint that explains why no other choice was available — not just why this choice was made.

---

## 8. The Contract With Decision Lens

The Investigation Layer (Curiosity Engine + Evidence Collector) delivers exactly one thing to Decision Lens:

**A structured investigation record containing:**

```
signal_id:          [identifier]
headline:           [as received]
core_fact:          [as received]

timeline:           [reconstructed sequence of prior decisions]
decisions:          [identified choices with dates if known]
constraints:        [what limited the option space]
rejected:           [alternatives not taken, with rationale]
protected:          [the priority they preserved]
cost_bearer:        [who pays, and when]
next_signal:        [observable prediction for 6–18 months]

q1_why_now:         [answer + second hypothesis]
q2_what_changed:    [answer]
q3_constraint:      [answer — REQUIRED]
q4_rejected:        [answer]
q5_protected:       [answer]
q6_who_pays:        [answer — REQUIRED]
q7_what_next:       [answer]

unknowns:           [what could not be determined]
confidence:         [0.0–1.0 per question]
evidence_complete:  [true/false]
proceed:            [PROCEED | PROCEED_WITH_CAVEATS | INSUFFICIENT | BLOCKED]
```

Decision Lens receives this record and **may not request additional research.** It works with what the investigation produced — including the unknowns. The unknowns are part of the output, not an error condition.

If `evidence_complete` is false or `proceed` is BLOCKED, Decision Lens returns the signal to the investigation layer with a specific gap description. It does not generate an interpretation.

---

## 9. What This Layer Does Not Do

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

## 10. Why This Matters

Most business content starts from the event and asks: *What does this mean?*

Never Blank starts from the event and asks: *What sequence of decisions produced this — and why were those decisions rational given what the organization knew and couldn't afford to lose?*

That is a different question.  
It produces a different kind of understanding.  
And it is the reason Never Blank content doesn't sound like news analysis.

It sounds like someone who read the organization, not the headline.

---

## Appendix: Failure Modes to Monitor

As this layer is implemented, watch for these failure patterns:

| Failure Mode | Symptom | Fix |
|---|---|---|
| Timeline collapse | Investigation skips directly to Q1 without reconstructing prior decisions | Enforce Reconstruct Timeline as a separate, logged step |
| First-hypothesis lock | Q1 is answered once and never questioned | Require explicit second hypothesis before Q1 is marked complete |
| Constraint invention | Q3 answer contains "they believed" without evidence | Q3 requires external evidence, not inference |
| Missing rejection | Q4 answered as "there were no alternatives" | Flag and require human review — this answer is almost always wrong |
| Cost displacement | Q6 answered as "costs are shared" | Force specificity: who, how much, when |
| Premature proceed | `evidence_complete: true` despite Q3 or Q6 being empty | Hard block in pipeline logic |

---

*This document describes the intellectual architecture, not the implementation. Code, prompts, and pipeline integration are defined separately and must conform to the contract specified here.*
