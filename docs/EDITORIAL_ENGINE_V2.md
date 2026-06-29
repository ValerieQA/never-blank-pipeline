# Editorial Engine V2
## The Layer That Turns Investigation Into Story

**Version:** v0.1 — Specification Only  
**Branch:** main  
**Status:** Spec. No code yet.  
**Depends on:** LERA_OPERATING_SYSTEM.md, EVIDENCE_COLLECTOR_MVP.md

---

## 1. The Problem This Solves

The Investigation Layer (Curiosity Engine + Evidence Collector + Decision Lens) produces an excellent internal document.

Nobody should ever read it.

It is dry by design. It names hypotheses, evidence statuses, unknown reasons, and surviving conclusions. It does not care if you finish reading it. Its job is to be correct.

The Editorial Engine has a different job: **make a person choose to read the next sentence.**

These are not the same job. They must never be the same module.

**What went wrong before V2:**

```
Investigation Output → Article
```

The system collapsed two distinct responsibilities into one output. The result was structurally correct analysis with no reason to read it. The investigation answered "what is true." The article never answered "why should I care right now."

**The fix:**

```
Investigation Output
      ↓
Editorial Engine (6 modules)
      ↓
Article
```

The Editorial Engine receives `investigation_evidence_report` and produces a publishable article. It does not re-investigate. It does not add conclusions. It takes what the investigation found and builds a path for a reader through it.

---

## 2. What the Editorial Engine Receives

From `investigation_evidence_report`:

- `safe_conclusions` — what can be stated with evidence
- `blocked_conclusions` — what cannot be stated as fact
- `hypothesis_history` — which explanations were tested and eliminated
- `inferences` — what was concluded from evidence, with motive_status labels
- `remaining_uncertainty` — what is still unknown, and whether it changes the conclusion
- `timeline` — reconstructed sequence of prior decisions

From Decision Lens (upstream):

- `decision` — the core business decision being examined
- `business_lesson` — what this decision reveals about organizational logic
- `never_blank_insight` — the specific observation that is non-obvious

**The Editorial Engine may not:**

- Add conclusions not present in `safe_conclusions`
- Upgrade an `inferred` finding to a stated fact
- Drop `remaining_uncertainty` items where `would_change_conclusion_if_resolved: true`
- Invent context about the company not present in the signal or investigation

---

## 3. The Six Modules

### Module 1 — Hook Engine

**Question:** Why would a person stop scrolling for this?

Not: "How do I start elegantly?"  
But: "What is the thing in this investigation that a reader would not expect?"

The Hook Engine generates **5–7 candidate hooks** before selecting one. A single hook generated first is almost never the strongest one.

**Hook types to generate across:**

| Type | What it does | Example frame |
|---|---|---|
| `contradiction` | States something that seems wrong but is true | "Getty wasn't losing. That's what makes the deal interesting." |
| `invisible_signal` | Names something everyone saw but nobody read correctly | "Everyone noticed the partnership. Almost nobody noticed what Getty stopped trying to win." |
| `surprising_question` | Opens with the question the investigation answered | "What does a copyright lawsuit cost when AI is rewriting the market faster than courts move?" |
| `wrong_consensus` | Names the incorrect interpretation the market held | "The press called it a retreat. The CEO's exact words suggest the opposite." |
| `hidden_decision` | Reveals that the visible event was not the actual decision | "The deal with OpenAI wasn't the decision. The decision was made in 2022, when Getty banned AI uploads from its own platform." |
| `false_narrative` | Dismantles the frame before establishing the real one | "Getty didn't stop suing because it lost. It stopped because winning the wrong war is still losing." |

**Selection rule:** Choose the hook that names something the reader would not have derived from the headline alone. If the hook could be written without reading the investigation, it is wrong.

**The hook must not summarize.** It must create a gap — something the reader does not yet know how to resolve.

---

### Module 2 — Reader Context

**Question:** What does the reader need to know in two sentences to make the next five paragraphs land?

Not a company history. Not a market overview.  
Two sentences, maximum. One is better.

**When context is required:**
- Company is not a household name
- Event happened in an industry the target audience doesn't follow
- The signal involves a regulatory or legal mechanism that needs a single-line definition

**When context is not required:**
- Company needs no introduction for the target audience
- The hook already establishes sufficient context
- Adding context would slow the opening

**Format:**
```
[Company] is [one-line description of what it does and why it matters in this context].
```

Getty example:
> Getty Images licenses photographs, illustrations, and video to media companies and advertisers worldwide — one of the last major platforms where every image comes with a documented legal history.

That last clause is not decorative. It is the reason the OpenAI deal matters. Reader context must earn its place by making the next paragraph easier to understand, not by providing background for its own sake.

---

### Module 3 — Story Builder

**Question:** In what order should the reader encounter the information?

The Story Builder decides the sequence of revelation. Its job is not to present conclusions — it is to create the experience of reaching them.

**The core principle:** The reader should arrive at the insight one step behind the investigation. Not five steps behind (confusing) and not simultaneously (no tension).

**Standard revelation sequence:**

```
1. Hook — the unexpected entry point
2. Context — what the reader needs to follow
3. The visible event — what everyone saw
4. The first obvious interpretation — what most people concluded
5. The crack in that interpretation — the evidence that doesn't fit
6. The real question — what the investigation actually asked
7. The surviving explanation — what the evidence supports
8. The remaining uncertainty — what is still open (if material)
9. The business lesson — what this means beyond this company
10. Never Blank line — the observation that doesn't expire
```

**Story Builder decisions:**

- How many steps to include (not all articles need all 10)
- Where to place the `remaining_uncertainty` (before or after the surviving explanation)
- Whether the `contradicted_hypotheses` should appear explicitly or only inform the framing
- Where tension is introduced and when it is released

**Rule:** The surviving explanation must not appear before step 5. If the reader gets the answer in paragraph two, there is no story — only a press release with a byline.

**Rule:** `blocked_conclusions` cannot appear as narrative beats. They can only shape what is *not* claimed.

---

### Module 4 — Evidence Reveal

**Question:** How does the reader experience the evidence without reading a research report?

The Evidence Reveal module takes `safe_conclusions` and `hypothesis_history` and transforms them into the texture of the story — not a footnote, not a citation, but the moment when the reader sees why the conclusion holds.

**Wrong approach (pre-V2):**
> Getty's CEO stated that the company wanted to be "part of the solution." This is consistent with a deliberate strategic pivot rather than a forced capitulation.

This is an analyst memo. It states the evidence and draws the conclusion in the same sentence.

**Right approach:**
> Here's what Getty's CEO actually said at the time:  
> *"We want to be part of the solution, not just the opposition."*  
> That's not the language of a company that ran out of options.

The evidence lands first. The reader draws the conclusion. Then the article confirms it.

**Techniques:**

| Technique | When to use |
|---|---|
| Direct quote with attribution | When `motive_status = stated` — the source said it explicitly |
| Behavioral evidence | When action reveals more than statement ("Getty banned AI uploads from its own platform") |
| Eliminated alternative | When a `contradicted_hypothesis` makes the surviving explanation stronger ("The lawsuit wasn't lost — the case was still active") |
| Explicit uncertainty | When `remaining_uncertainty.would_change_conclusion_if_resolved = true` — must surface, not omit |

**Rule:** Every piece of evidence in the article must trace back to a `safe_conclusion` or `inference` in the investigation report. The Editorial Engine does not generate evidence. It reveals what was already found.

---

### Module 5 — Business Translation

**Question:** What does this decision mean for a company that has nothing to do with Getty or AI?

This is the layer that gives Never Blank its universal value. The investigation is about one company. The business lesson must work for any company facing the same structural choice.

**The translation question:**
> "If I run a company in a different industry facing the same type of decision, what does this tell me?"

**Translation types:**

| Type | Frame |
|---|---|
| Resource allocation | When to own vs. partner vs. litigate vs. wait |
| Timing logic | When moving first loses and when waiting costs more than acting |
| Narrative vs. reality | When the public explanation and the strategic logic diverge |
| Protected priority | What a company was unwilling to trade, and what that reveals |
| Cost transfer | Who ends up paying for the decision, and why it was designed that way |

**Rules:**
- The lesson must be specific enough to be actionable, not generic enough to apply to everything
- "Companies should think long-term" is not a business lesson — it is a platitude
- The lesson must be derived from the `decision` field in Decision Lens output — not invented by the Editorial Engine
- The lesson should fail for at least some companies — if it applies to every situation, it applies to none

**Getty example — wrong:**
> Businesses facing disruption should consider partnering with the disruptors.

**Getty example — right:**
> The moment a lawsuit stops being about winning and starts being about delaying, the deal was always going to happen. The only question is the price. Getty moved while the price was still high.

---

### Module 6 — Never Blank Voice

**Question:** Does this sound like Never Blank?

This is the final pass. It does not add content. It checks that the content that exists has the qualities that distinguish Never Blank from analytical content that happens to be well-written.

**Checklist — the article must have:**

- [ ] A hook that creates a gap in the first 1–3 sentences
- [ ] At least one moment where the reader encounters something they didn't expect
- [ ] A point where tension is introduced and a point where it resolves
- [ ] A business lesson specific enough to be wrong for some companies
- [ ] A Never Blank signature line that doesn't repeat the headline
- [ ] An ending stronger than the opening — the last sentence must earn its place

**Checklist — the article must not have:**

- [ ] Generic advice ("companies should be strategic about...")
- [ ] A conclusion in the first paragraph
- [ ] Evidence presented without the reader experiencing its weight
- [ ] A summary at the end that repeats what was already said
- [ ] The word "pivoted" used without irony
- [ ] A business lesson that could have been written without reading the investigation

**Never Blank Voice characteristics:**

*Precision over volume.* One specific observation is worth more than three general ones.

*Tension before resolution.* The reader should not know where the article is going until they're almost there.

*Evidence before conclusion.* Show the crack in the obvious interpretation before naming the real one.

*The non-obvious is the product.* If a reader could have written this paragraph from the headline alone, the paragraph should not exist.

*The signature line is not a summary.* It is an observation that lingers. It should work out of context.

**Signature line format:**
```
Never Blank — [one observation that reframes the signal]
```

Not: "Never Blank — the signal is rarely the event itself." (generic)  
But: "Never Blank — Getty didn't stop suing because it lost. It stopped because winning the wrong war is still losing." (specific, derived from this investigation)

---

## 4. The Full Flow

```
investigation_evidence_report
          +
    Decision Lens output
          ↓
  ┌───────────────────┐
  │   Hook Engine     │  → 5–7 candidates → select 1
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │  Reader Context   │  → 0–2 sentences (or skip)
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │  Story Builder    │  → sequence of revelation
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │  Evidence Reveal  │  → transform findings into texture
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │Business Translation│ → universal lesson from specific decision
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │ Never Blank Voice │  → final quality pass
  └───────────────────┘
          ↓
       Article
```

---

## 5. What Each Module Receives and Returns

| Module | Receives | Returns |
|---|---|---|
| Hook Engine | safe_conclusions, decision, never_blank_insight | hook_candidates[], selected_hook |
| Reader Context | headline, company name, signal type | context_line (string or null) |
| Story Builder | hook, context, safe_conclusions, hypothesis_history, remaining_uncertainty | revelation_sequence[] |
| Evidence Reveal | revelation_sequence, safe_conclusions, inferences, hypothesis_history | article_body (draft) |
| Business Translation | decision, business_lesson, article_body | article_body + lesson_paragraph |
| Never Blank Voice | article_body (complete) | final_article, signature_line, checklist_pass (bool) |

---

## 6. Quality Gates

The Editorial Engine may not produce a final article if:

1. `Hook Engine` selected a hook that could have been written from the headline alone
2. `Evidence Reveal` contains a claim not traceable to `safe_conclusions`
3. `Business Translation` lesson applies to all companies without qualification
4. `Never Blank Voice` checklist has any item marked false
5. `remaining_uncertainty` item with `would_change_conclusion_if_resolved: true` was omitted from the article

If any gate fails, the module returns to the relevant stage — not to the beginning.

---

## 7. Relationship to Investigation Layer

The Editorial Engine is downstream. It cannot:

- Send signals back to the Investigation Layer
- Request additional research
- Override evidence status in the investigation report
- Omit material uncertainty to produce a cleaner narrative

It can:

- Choose which `safe_conclusions` to foreground and which to leave implicit
- Select the strongest hook from multiple candidates
- Shape the order of revelation to maximize reader engagement
- Frame `remaining_uncertainty` as an open question rather than a caveat

The investigation determines what is true.  
The Editorial Engine determines how the reader encounters it.

These are different skills. Both are required.

---

*Implementation follows specification approval.*
