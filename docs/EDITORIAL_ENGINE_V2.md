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
Decision Lens
      ↓
Narrative Spine          ← establishes what the article is actually about
      ↓
Editorial Engine (6 modules)
      ↓
Article
```

The Editorial Engine receives `investigation_evidence_report`, Decision Lens output, and the Narrative Spine. It does not re-investigate. It does not add conclusions. It takes what the investigation found and builds a path for a reader through it — toward the Spine.

See: [NARRATIVE_SPINE.md](NARRATIVE_SPINE.md)

---

## 2. What the Editorial Engine Receives

From `narrative_spine` (NARRATIVE_SPINE.md — run before any module):

- `core_decision` — the underlying decision the article investigates
- `narrative_spine` — the one sentence the article is built to earn
- `target_feeling` — the emotional register the last line must produce
- `company_as_evidence_of` — what the company proves, not what it did

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

**Question:** Does the reader know what this company fundamentally does — and does the Hook work without knowing?

Reader Context is **mandatory** unless the company is universally recognizable.

Universally recognizable means: Apple, Microsoft, Google, Amazon, Meta, Tesla, Toyota, Samsung — companies where any adult in any country would immediately understand the business without explanation. Everything else requires Reader Context.

**Placement — this is determined by the Hook, not by the company:**

**Hook-first** (default): The Hook works without knowing the company. Reader Context follows immediately after.
```
Hook
↓
Reader Context
↓
Discovery
```
> *Getty filed one of the biggest copyright suits in AI history. Then it partnered with the defendant.*
> *Getty Images licenses photographs and video to media companies and advertisers worldwide.*

The hook lands on its own. Context arrives to make the next paragraph make sense.

**Context-first**: The Hook is impossible to understand without knowing what the company does.
```
Reader Context
↓
Hook
↓
Discovery
```
> *Polymarket operates a prediction market where users trade on real-world event outcomes.*
> *For three years, it blocked US users. Then it quietly reopened. The press couldn't explain why now.*

Without the first sentence, "Polymarket blocked US users" has no weight. The reader doesn't know why they should care.

The test: read only the Hook. If a reader unfamiliar with the company would understand why it matters — Hook-first. If not — Context-first.

**Rules:**
- One sentence. Maximum 10–20 words.
- Describe only what the company fundamentally does.
- Never include analysis, opinion, or anything about the current story.
- Never summarize what happened.

**Format:**
```
[Company] [does what] [for whom / in what context].
```

**Examples:**

> Polymarket operates a prediction market where users trade on real-world event outcomes.

> Getty Images licenses photographs and video to media companies and advertisers worldwide.

> Lucid Motors builds premium electric vehicles focused on maximum driving range.

> Stability AI develops open-source generative AI models for image and text creation.

One sentence. What the company does. Nothing else.

---

### Module 3 — Discovery Builder

**Question:** How does the reader experience the moment of discovery — not the conclusion?

The Discovery Builder constructs the investigation experience for the reader. Its job is not to deliver the surviving explanation — it is to make the reader arrive at it themselves, one step ahead of the article confirming it.

The difference from Story Builder is the voice:

- Story Builder: *Here is the correct interpretation.*
- Discovery Builder: *Here is why I stopped believing the first interpretation.*

The reader is not a student receiving analysis. They are a co-investigator watching the obvious explanation break.

**The four beats:**

**Beat 1 — The First Wrong Explanation**

Name the interpretation everyone held, including the narrator, before the investigation.

Not a straw man. Not "critics said." The actual obvious conclusion.

> *I thought Getty had blinked.*

This is the starting position. The reader holds it too.

**Beat 2 — The Puzzle**

One specific fact that does not fit the first explanation. Not a "crack" — a contradiction.

A crack invites qualification. A contradiction forces a new explanation.

> *Except the lawsuit wasn't dropped. It's still active. A company that ran out of options doesn't keep the case open.*

The reader stops. The first explanation no longer holds. They don't yet have a replacement.

**Beat 3 — Investigation Reveal**

Walk through the evidence in the order it narrowed the space. Not conclusion-first. Sequence-first.

Each piece of evidence eliminates one possible explanation. The reader watches the field narrow.

> *So I went back to the timeline.*  
> *Getty banned AI-generated images from its own platform — September 2022.*  
> *The lawsuit came after.*  
> *The deal came after the lawsuit.*  
> *That's not the sequence of a company reacting. It's the sequence of a company setting terms.*

The surviving explanation is not stated here. The reader can see it forming.

**Beat 4 — The Aha**

The moment the reader's model flips. The article does not announce it. The article presents the last piece of evidence, and the reader arrives one sentence ahead of the text.

> *Here's what the CEO said when the deal closed:*  
> *"We want to be part of the solution, not just the opposition."*  
> *Companies that run out of options don't frame themselves as having previously been the opposition.*

The article does not then say "therefore Getty planned this." The reader already knows.

**Rules:**

The first explanation must be one the reader genuinely held — not a weak position set up to be knocked down.

The puzzle must be a single fact, not a list of concerns. One contradiction is stronger than five doubts.

The investigation reveal must show sequence, not summary. "The timeline shows X" is summary. "First this happened. Then this. Then this." is sequence.

The Aha must arrive before the article states the conclusion. If the article has to explain the Aha, the Aha didn't land.

**What Discovery Builder receives:**

- `hook` — from Hook Engine
- `hypothesis_history` — which explanations were contradicted and why
- `narrative_spine` — the conclusion the reader is being built toward
- `contradicted_hypotheses` — the first wrong explanation and the specific fact that broke it
- `safe_conclusions` — the evidence sequence

**What Discovery Builder returns:**

- `first_wrong_explanation` — the obvious interpretation, stated directly
- `puzzle` — the single fact that breaks it
- `investigation_sequence` — ordered evidence beats (3–5 items)
- `aha_setup` — the last piece of evidence before the reader flips, without stating the conclusion

---

### Module 4 — Story Builder

**Question:** In what order should the full article be assembled?

The Story Builder receives Discovery Builder output and assembles the complete article sequence. Its job is to place the discovery experience within the full arc — what comes before it, and what comes after.

**Full article sequence:**

```
1. Hook
2. Context (0–2 sentences, or skip)
3. Discovery Builder output
   a. First wrong explanation
   b. Puzzle
   c. Investigation reveal
   d. Aha setup
4. Surviving explanation (stated — reader already has it)
5. Remaining uncertainty (if would_change_conclusion_if_resolved = true)
6. Business meaning — what this decision reveals beyond this company
7. Never Blank line
```

**Story Builder decisions:**

- Whether to include Reader Context (Module 2) before or after the hook
- How much of `hypothesis_history` to surface explicitly vs. let inform framing
- Where to place `remaining_uncertainty` — before or after surviving explanation
- Length: which beats to compress and which to expand

**Rule:** The surviving explanation (step 4) arrives after the Aha setup. The reader has the answer. The article confirms it.

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

### Module 7 — Platform Composer

**Each platform has one job:**
- Blog — prove it.
- Telegram — tell it.
- LinkedIn / Facebook — explain it.
- Instagram — make them feel it.
- Threads — leave a thought that lives on its own.



**Question:** How does each platform's reading behavior change what the article needs to do?

The Platform Composer is not a text editor. It does not receive an article and cut sentences. It receives a structured JSON of named blocks from Never Blank Voice and produces five platform-specific versions — each optimized for how that audience actually reads, not just for length.

Word count is a consequence of reading behavior. It is not the target.

**The core principle:** Preserve every cognitive step. Compress only exposition. Optimize for reading behavior.

The invariant across all five formats:
- Narrative Spine — identical in every version
- Hook — present in every version
- Discovery moment — present in every version
- Aha moment — present in every version
- Never Blank signature — present in every version

Only investigation depth changes between formats. The business insight must remain identical.

**What the Platform Composer receives:**

Never Blank Voice outputs a structured article object — not a flat body string:

```json
{
  "signal_id": "string",
  "narrative_spine": "string",
  "hook": "string",
  "reader_context": "string | null",
  "discovery": {
    "first_wrong_explanation": "string",
    "puzzle": "string",
    "investigation_sequence": ["string"],
    "aha_setup": "string"
  },
  "surviving_explanation": "string",
  "remaining_uncertainty": "string | null",
  "business_translation": "string",
  "signature": "string"
}
```

**Format → platform mapping:**

| Format | Platforms | Words | Reading behavior |
|---|---|---|---|
| Long | Blog | 700–1000 | Reads at a desk. Wants full evidence, timeline, uncertainty. |
| Reading | Telegram | 350–600 | Reads the whole thing. Wants narrative and discovery, not evidence density. |
| Medium | LinkedIn, Facebook | 120–220 | Reads in a feed. Needs a complete standalone arc: Hook → Discovery → Aha → Lesson → Signature. |
| Instagram | Instagram | 80–150 | Reads on a phone, one screen at a time. Shorter paragraphs, stronger rhythm, one dominant insight. Not a shortened LinkedIn post. |
| Short | Threads | 40–80 | Reads one idea. Hook or Spine only. Does not summarize the investigation. |

**Per-block behavior by format:**

| Block | Long | Reading | Medium | Instagram | Short |
|---|---|---|---|---|---|
| `hook` | full | full | compressed | compressed | compressed |
| `reader_context` | full | skip | skip | skip | skip |
| `discovery.first_wrong_explanation` | full | full | compressed | compressed | skip |
| `discovery.puzzle` | full | full | compressed | compressed | skip |
| `discovery.investigation_sequence` | full | compressed | skip | skip | skip |
| `discovery.aha_setup` | full | full | compressed | compressed | skip |
| `surviving_explanation` | full | compressed | skip | skip | skip |
| `remaining_uncertainty` | full | skip | skip | skip | skip |
| `business_translation` | full | compressed | compressed | skip | skip |
| `signature` | full | full | full | full | full |

`skip` — block is omitted entirely.
`compressed` — block is present, reduced to its cognitive minimum. Never summarized, never merged.
`full` — block appears as written by Never Blank Voice.

**Format-specific constraints:**

*Reading (Telegram):* Preserve the narrative arc. Remove evidence citations and analytical qualifications that slow reading pace. A reader should feel the investigation without cataloguing the evidence. Target: readable in 2–4 minutes without stopping.

*Medium (LinkedIn, Facebook):* Must be a complete standalone text. A reader who has never heard of the company must reach the Aha and the Spine without needing the Long version. No dangling references to evidence not present in this version.

*Instagram:* Instagram is the most literary format in the system. Its job is not to explain the investigation — it is to make the reader feel the moment the first explanation broke.

No analysis. No qualifications. No stacked facts. Only the emotional sequence: something was true, then one thing changed, then nothing was the same.

Rules for Instagram:
- Keep the Hook — compressed to its sharpest form.
- Keep the moment the first explanation broke — not as analysis, as sensation.
- Keep the Aha — as implication, not as statement.
- Keep the Narrative Spine — the one sentence the post is built to earn.
- One idea per paragraph. Blank lines are part of the storytelling.
- Prefer movement and implication over fact and qualification.
- Never name a statistic unless it is the puzzle itself.
- Never write a sentence that could appear in a LinkedIn post.

The reader should finish thinking: *I just realized something* — not *I just read an analysis.*

The investigation is the source. It is not the content.

*Short (Threads):* One idea. Either the Hook that opens the gap, or the Spine that closes it. Does not attempt to compress the investigation into 60 words — that produces summaries, not insights.

**The rule for compressing a block:**

Remove sentences that explain what the previous sentence already showed. Do not remove sentences that move the reader to the next cognitive position.

Wrong compression of `discovery.investigation_sequence` for Reading:
> Getty's timeline shows a deliberate strategy: ban, then lawsuit, then partnership.

That is a summary. The sequence is gone.

Right compression:
> Ban first. Then lawsuit. Then partnership. That sequence only makes sense one way.

Same cognitive move. Half the words.

**Output format:**

```json
{
  "signal_id": "string",
  "narrative_spine": "string — identical across all formats",
  "long":      { "word_count": 0, "body": "string" },
  "reading":   { "word_count": 0, "body": "string" },
  "medium":    { "word_count": 0, "body": "string" },
  "instagram": { "word_count": 0, "body": "string" },
  "short":     { "word_count": 0, "body": "string" }
}
```

The Platform Composer does not rewrite the article. It selects blocks, applies format-specific constraints, and assembles. The investigation and the insight are the same in every version.

---

## 4. The Full Flow

```
investigation_evidence_report
          +
    Decision Lens output
          ↓
  ┌───────────────────┐
  │  Narrative Spine  │  → core_decision + spine sentence + target_feeling
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │   Hook Engine     │  → 5–7 candidates → select hook that earns the Spine
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │  Reader Context   │  → 0–2 sentences (or skip)
  └───────────────────┘
          ↓
  ┌───────────────────────────┐
  │    Discovery Builder      │  → first wrong explanation → puzzle →
  │                           │    investigation reveal → aha setup
  └───────────────────────────┘
          ↓
  ┌───────────────────┐
  │  Story Builder    │  → assembles full article sequence around discovery
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │  Evidence Reveal  │  → transform findings into texture
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │Business Translation│ → translates the Spine into universal terms
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │ Never Blank Voice │  → checks article earns the Spine by the last line
  └───────────────────┘
          ↓
  ┌───────────────────┐
  │Platform Composer │  → 5 formats, optimized by reading behavior
  └───────────────────┘
          ↓
  Long (blog) / Reading (Telegram) / Medium (LinkedIn+FB) / Instagram / Short (Threads)
```

---

## 5. What Each Module Receives and Returns

| Module | Receives | Returns |
|---|---|---|
| Narrative Spine | Decision Lens output (core_decision + strategic_objective) | narrative_spine, target_feeling, company_as_evidence_of |
| Hook Engine | safe_conclusions, narrative_spine, never_blank_insight | hook_candidates[], selected_hook |
| Reader Context | headline, company name, signal type | context_line (string or null) |
| Discovery Builder | hook, hypothesis_history, contradicted_hypotheses, safe_conclusions, narrative_spine | first_wrong_explanation, puzzle, investigation_sequence[], aha_setup |
| Story Builder | discovery_builder output, remaining_uncertainty, business_lesson, narrative_spine | full_article_sequence[] |
| Evidence Reveal | full_article_sequence, safe_conclusions, inferences, hypothesis_history | article_body (draft) |
| Business Translation | narrative_spine, business_lesson, article_body | article_body + lesson_paragraph |
| Never Blank Voice | article_body (complete), narrative_spine, target_feeling | structured_article (hook, discovery, aha, business_translation, signature, …), checklist_pass (bool) |
| Platform Composer | structured_article JSON | long / reading / medium / instagram / short |

---

## 6. Quality Gates

The Editorial Engine may not produce a final article if:

1. `Hook Engine` selected a hook that could have been written from the headline alone
2. `Discovery Builder` first_wrong_explanation is a straw man — an interpretation nobody actually held
3. `Discovery Builder` puzzle is a list of doubts rather than a single contradiction
4. `Discovery Builder` Aha is stated by the article rather than arrived at by the reader
5. `Evidence Reveal` contains a claim not traceable to `safe_conclusions`
6. `Business Translation` lesson applies to all companies without qualification
7. `Never Blank Voice` checklist has any item marked false
8. `remaining_uncertainty` item with `would_change_conclusion_if_resolved: true` was omitted from the article
9. `Platform Composer` Medium or Short removed the puzzle or the Aha setup

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
