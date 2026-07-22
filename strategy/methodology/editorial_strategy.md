# Never Blank — Editorial Strategy

**Status:** Production  
**Last updated:** 2026-07-22  
**Decisions:** 16–19, 24, 28–30, 38, 44, 45

---

## Article Arc (Production — 11 steps)

Implemented in `src/editorial/never_blank_voice.py` and `src/editorial/platform_composer.py`.

```
Hook
→ Recognition
→ Tension
→ Market Observation
→ Investigation
→ Mechanism
→ Business Consequence
→ Reframe
→ Compound Presence Connection  ← semantic requirement, not a required section
→ Echo
→ Soft CTA
```

### Step definitions

**Hook** — one sentence that opens a gap. The reader must feel tension immediately.  
Not an introduction. Not a topic statement. The point.

**Recognition** — the reader sees their own situation.  
Specific enough that the reader thinks "that is me," not "founders generally."

**Tension** — the gap between what the reader assumed and what the article will reveal.  
Not a question. A held breath.

**Market Observation** — a real signal, data point, or observed pattern.  
Must be traceable to a source. No fabricated statistics or research volume.

**Investigation** — why the obvious explanation is insufficient.  
Cognitive steps, not detective narration. Never "I went looking" or "I figured."

**Mechanism** — the structural cause that produces the observed behavior.  
Not the symptom. The internal logic. Specific enough to be falsifiable.

**Business Consequence** — concrete commercial result of the mechanism.  
Not emotional. Not "this can affect your business." What actually changes — pipeline, referrals, recognition, revenue timing.

**Reframe** — the problem is different from how it appears.  
Must genuinely contest the obvious explanation, not add to it or recommend doing more of something.

**Compound Presence Connection** — semantic outcome, not a required paragraph.  
The article must establish why the revealed mechanism connects to the cumulative effect of consistent presence. Acceptable forms:
- A standalone paragraph
- Part of the Reframe
- The transition from Business Consequence to Echo
- Meaning distributed across multiple sentences

The validator checks for semantic content, not a section header.  
See `src/strategy/validators.py: validate_compound_presence_semantic()`.

**Echo** — the thought that stays.  
Generated from 3–5 internal candidates. Selected only when earned.  
Must be specific to this article, not transferable to another.  
Null is allowed when no candidate passes quality — but should be rare (decision 38).  
Never a motivational close. Never advice. An implication or uncomfortable truth.

**Soft CTA** — governed by `cta_mode` from the monthly strategy.  
Never model discretion. If `cta_mode=none`, no CTA. (Decision 18.)

---

## Article Arc (Kept — 9 steps, not production)

Implemented in original editorial prompts. **Not deleted.** Marked here for future testing and comparison.

```
Hook → Observation → Recognition → Evidence → Explanation → Reframe → Business Meaning → CTA → Echo
```

This arc is in `config/prompts/` and `src/editorial/platform_composer.py` as the pre-existing format keys (`long`, `reading`, `medium`, `instagram`, `short`). It has produced published content and should be evaluated against the 11-step arc when sufficient data exists. Do not remove it until that comparison is complete.

---

## Core article principles

**Company as evidence, not protagonist** (decisions 24, 28)  
A named company may appear only as evidence that a mechanism exists. The article must survive if the company name is removed. The small business owner is always the protagonist and central character.

**No fabricated research** (decision 10)  
No invented statistics, customer histories, or false research volume. Ever.

**Reframe must break the obvious** (decision 29)  
Not "do more of this." Not "here is a tip." The obvious explanation must be genuinely wrong or incomplete.

**Research stays backstage** (decision 17)  
No "I analyzed / I researched / I investigated" narration unless the article is explicitly about the research process itself.

**Compound Presence Connection is mandatory semantic content** (decision 44)  
Every article must connect its mechanism to the cumulative effect of consistent, systematic presence. How a reader recognizes the gap between one-time attention and a presence system.

---

## Echo rules (decision 38, 43)

- Generate 3–5 candidates internally
- Select only when a candidate genuinely earns it
- Null is acceptable — rare exception, not routine
- Quality bar does not drop to reach 100% Echo coverage
- Never the same Echo across articles
- Validator flags if the same formula repeats across recent articles

---

## Compound Presence Connection — validator criteria

`validate_compound_presence_semantic()` in `src/strategy/validators.py` checks:

1. Does the text explain why one-time attention ≠ systematic presence?
2. Is there a connection to repeated visibility, trust, audience memory, or contact accumulation?
3. Does this conclusion flow from the article's mechanism, not inserted artificially?
4. Is the same formula not repeated across recent articles?

Validator uses LLM-assisted semantic check, not keyword matching.  
Hard fail only when the connection is absent entirely — not when it is implicit or brief.

---

## What the article sells

Never Blank through quality of thinking, not through direct pitch.

Desired reader realization sequence:
1. "That is happening to us."
2. "This is why it happens."
3. "The cost is real — pipeline, recognition, trust."
4. "Consistent presence is not optional — it is the mechanism."
5. [Optional, `cta_mode`-dependent] "I want to look at how this applies to us."
