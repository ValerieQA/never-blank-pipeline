# Editorial Engine V2
## The Layer That Turns Investigation Into Story

**Version:** v0.2 — Updated for small-business visibility editorial identity  
**Branch:** main  
**Status:** Live  
**Depends on:** NEVER_BLANK_EDITORIAL_WORLDVIEW.md, LERA_OPERATING_SYSTEM.md, EVIDENCE_COLLECTOR_MVP.md

---

## 1. The Problem This Solves

The Investigation Layer (Curiosity Engine + Evidence Collector + Decision Lens) produces
an excellent internal document. Nobody should ever read it.

It is dry by design. It names hypotheses, evidence statuses, unknown reasons, and surviving
conclusions. Its job is to be correct.

The Editorial Engine has a different job: **make a small business owner recognize their own
situation in the next sentence.**

These are not the same job. They must never be the same module.

**The fix:**

```
Investigation Output (visibility/presence pattern signals)
      ↓
Decision Lens
      ↓
Narrative Spine          ← establishes what the article is actually about
      ↓
Editorial Engine (7 modules)
      ↓
Article (9-step reader-facing arc)
```

The Editorial Engine receives `investigation_evidence_report`, Decision Lens output, and the
Narrative Spine. It does not re-investigate. It takes what the investigation found and builds
a path for a reader through it — toward the moment of recognition.

See: [NARRATIVE_SPINE.md](NARRATIVE_SPINE.md)

---

## 2. What the Editorial Engine Receives

From `narrative_spine` (NARRATIVE_SPINE.md — run before any module):

- `core_decision` — the underlying pattern the article investigates
- `narrative_spine` — the one sentence the article is built to earn
- `target_feeling` — the emotional register the last line must produce
- `pattern_as_evidence_of` — what the pattern proves, not merely what it describes

From `investigation_evidence_report`:

- `safe_conclusions` — what can be stated with evidence
- `blocked_conclusions` — what cannot be stated as fact
- `hypothesis_history` — which explanations were tested and eliminated
- `inferences` — what was concluded from evidence, with confidence labels
- `remaining_uncertainty` — what is still unknown, and whether it changes the conclusion

From Decision Lens (upstream):

- `decision` — the core pattern being examined
- `business_lesson` — what this pattern reveals about small business visibility
- `never_blank_insight` — the specific observation that is non-obvious

**The Editorial Engine may not:**

- Add conclusions not present in `safe_conclusions`
- Upgrade an `inferred` finding to a stated fact
- Drop `remaining_uncertainty` items where `would_change_conclusion_if_resolved: true`
- Invent statistics, customer histories, or private business data not present in research inputs

---

## 3. The Nine-Step Reader-Facing Arc

Every article moves through this arc. Steps may be compressed or implied, but none may be
inverted. The reader must arrive at recognition before they receive explanation, and they must
receive the Echo before a CTA (if one is used at all).

```
1. Hook
2. Observation
3. Recognition
4. Evidence / specific pattern
5. Explanation
6. Reframe
7. Business and sales meaning
8. Echo
9. Natural invitation (when appropriate — not every article)
```

### Step 1 — Hook

Expose a contradiction, hidden cost, invisible pattern, or uncomfortable truth.

The Hook must NOT merely summarize the article. It must create immediate tension.
The reader should feel it is true before they can argue with it.

**Forbidden openings:** "In today's...", "It's not about...", "Many founders...",
"It's a pattern...", "At the core of...", any wind-up phrase, any question.

**Target territory:**
- "The most expensive post may be the one that never appeared."
- "Good businesses rarely disappear in one day."
- "Your customers do not know that you are busy. They only know that you went silent."
- "A business can be successful and still be gradually forgotten."

If the first sentence could be removed without losing the core idea — it is the wrong sentence.

### Step 2 — Observation

Name the external business pattern being investigated.

Avoid leading with "I researched / I analyzed / I looked at." Prefer the finding over narration
about the act of researching. The observation must be something a reader can picture happening
in the world, not a methodological statement.

### Step 3 — Recognition

Connect the pattern to the lived reality of the reader. Show situations like:

- client work defeating content work in the same week
- publishing stopping during busy periods without a conscious decision to stop
- competitors remaining visible despite not being better
- clients going quiet between projects and then using someone else

The reader should feel seen, not lectured. The recognition step is where the reader thinks
"this is about my business."

### Step 4 — Evidence or specific pattern

Concrete research finding, contradiction, sequence, or sourced observation.

Never fabricate volume, customer history, or private data. Use permitted formulations:
- "this pattern appeared repeatedly in the businesses examined"
- "the available research points to the same recurring failure"
- "the evidence suggests"

### Step 5 — Explanation

Explain the mechanism. Not just "consistency matters." Examples of strong explanation:

- non-urgent visibility work is repeatedly displaced by urgent operational work
- repeated exposure creates recognition, not the other way around
- recognition lowers the cognitive cost of trust
- silence breaks accumulated familiarity faster than presence builds it

### Step 6 — Reframe

Challenge the obvious explanation. This is the intellectual move that distinguishes
Never Blank from advice columns.

Not a discipline problem — a system-design problem.
Not a lack-of-ideas problem — a continuity problem.
Not a marketing problem — a structural presence problem.

Do not repeat the same reframe every article. The reframe must be earned by the specific
pattern being investigated.

### Step 7 — Business and sales meaning

Connect visibility to commercial reality: trust, recognition, future buying decisions,
referrals, pipeline, sales conversations.

Not a product pitch. Not generic advice. The commercial consequence of the specific
pattern described in this article.

### Step 8 — Echo

A distinct final thought designed to remain in the reader's mind.

The Echo is the core Never Blank editorial device. It is NOT:
- a summary of the article
- a slogan pasted onto every article
- a generic motivational quote
- always a CTA
- always the phrase "Never Blank"

**Generate 3–5 candidate Echoes internally. Select the one that is:**
- specific to this article's pattern and argument
- earned by the logic that preceded it
- emotionally restrained (not inspirational, not instructional)
- memorable and works out of context
- not generic enough to paste under a different article unchanged

**Quality references (do NOT hardcode — treat as examples of register):**
- "The most expensive publication is not the one that received few views. It is the one
  that never appeared."
- "If presence depends only on the owner's free time, silence eventually becomes part of
  the strategy — even when nobody chose it."
- "Customers rarely decide to forget a business. They simply stop encountering it."

Every second article should normally contain a strong Echo. More often when naturally earned,
but never formulaic. An Echo can be omitted when no strong candidate emerged.

### Step 9 — Natural invitation (optional)

Not every article needs a direct CTA. When used:

- Place before the Echo or integrate before it — do not destroy a strong Echo with generic
  sales text appended after it
- Vary the type across articles
- Never use: "book a call", "learn more", "buy now", "let us handle your content",
  "transform your social media"

**CTA types to rotate:**
- invitation to a visibility audit
- invitation to show the current content or presence system
- invitation to identify where the system breaks
- invitation to request an example
- invitation to discuss whether Never Blank fits the business

---

## 4. The Seven Modules

### Module 1 — Hook Engine

Generates 5–7 candidate hooks across distinct types, then selects the one that names
something a reader would not have derived from the signal alone.

Hook types for visibility/presence patterns:

| Type | What it does |
|---|---|
| `hidden_cost` | Names what the silence or absence is actually costing, in commercial terms |
| `invisible_pattern` | Names something the reader does regularly without realizing its effect |
| `false_comfort` | States a belief the reader holds that the evidence contradicts |
| `timing_contradiction` | Exposes that the pattern happens at exactly the wrong moment |
| `recognition_gap` | Names the gap between what the business does and what is visible outside |
| `accumulated_effect` | Reveals that small repeated absences compound into a large problem |

Selection rule: choose the hook that makes a business owner stop and feel recognized.
If the hook could have been written by a generic content marketer — it is wrong.

### Module 2 — Reader Context

In the new editorial identity, Reader Context is used sparingly. Small business visibility
patterns do not require explaining what a company does — the reader IS the company.

Use Reader Context only when the article draws on a specific research source, named business
sector, or documented precedent that requires 1–2 sentences of grounding before the pattern
can land.

When used: one sentence maximum. Describe the research context, not the company.

### Module 3 — Discovery Builder

Constructs the reader's experience of encountering the pattern.

The four beats (adapted for visibility/presence patterns):

**Beat 1 — The Observation**
Name the pattern externally. Not as advice. Not as analysis. As something observable.

**Beat 2 — The Recognition Moment**
One specific situation that the reader will recognize from their own experience.
Not a generalization. A specific moment: "the Monday after a project closes."

**Beat 3 — Evidence Sequence**
The research or observation sequence that confirms the pattern is not random.
Show the mechanism forming, not the conclusion.

**Beat 4 — The Explanation Lands**
The moment the mechanism becomes clear. The reader understands why this happens,
not just that it happens.

### Module 4 — Story Assembly (Story Builder + Evidence Reveal + Business Translation)

Assembles the full article sequence from discovery output.

Produces:
- `surviving_explanation` — the mechanism stated clearly after the reader has already arrived at it
- `reframe` — the specific intellectual move that reframes the obvious explanation
- `remaining_uncertainty` — genuine open question, or null
- `business_translation` — commercial reality connection: what this pattern means for pipeline,
  trust, future sales conversations

### Module 5 — Evidence Reveal

Transforms research findings into the texture of the article.
Not a citation. Not a footnote. The moment the reader encounters why the pattern is real.

Every claim must trace back to a `safe_conclusion` or `inference` in the investigation report.
The Editorial Engine does not generate evidence. It reveals what was already found.

### Module 6 — Never Blank Voice (Echo + CTA generation)

Final pass. Generates:

1. **Echo** — 3–5 candidates, selects the one most specific to this article's argument.
   Can return null if no strong candidate emerged (do not force an Echo into every article).

2. **CTA** — optional natural invitation. Null if this article does not warrant one.
   When non-null, must be specific to the pattern in this article, not a generic sales line.

3. **Checklist self-assessment** — all items must pass before the article is final.

Checklist items:
- [ ] Hook creates gap in first 1–3 sentences
- [ ] Article contains a Recognition moment where reader sees their own situation
- [ ] Evidence is traceable — no invented facts
- [ ] Reframe challenges the obvious explanation with a specific alternative
- [ ] Business meaning connects to commercial reality, not to abstract visibility concepts
- [ ] Echo (if present) is specific to this article and not generic
- [ ] CTA (if present) matches one of the permitted types and does not follow the Echo

### Module 7 — Platform Composer

Each platform has one job:
- Blog — prove the pattern with full evidence arc
- Telegram — tell the pattern as a narrative
- LinkedIn / Facebook — create the recognition moment in a feed
- Instagram — make the reader feel the pattern before they understand it
- Threads — leave one thought that lives on its own

See the per-block table in Section 5 for format-specific behavior.

---

## 5. Block Table (Platform Composer)

Blocks in the structured article object, with behavior per format:

| Block | Long | Reading | Medium | Instagram | Short |
|---|---|---|---|---|---|
| `hook` | full | full | compressed | compressed | compressed |
| `reader_context` | full | skip | skip | skip | skip |
| `observation` | full | full | compressed | compressed | skip |
| `recognition` | full | full | compressed | compressed | skip |
| `evidence_pattern` | full | compressed | compressed | skip | skip |
| `explanation` | full | full | compressed | skip | skip |
| `reframe` | full | compressed | compressed | skip | skip |
| `business_meaning` | full | compressed | compressed | skip | skip |
| `echo` | full | full | full | full | full |
| `cta` | full | full | compressed | skip | skip |

`skip` — block is omitted entirely.
`compressed` — block is present, reduced to its cognitive minimum. Never summarized.
`full` — block appears as written by Never Blank Voice.

---

## 6. What Each Module Receives and Returns

| Module | Receives | Returns |
|---|---|---|
| Narrative Spine | Decision Lens output | narrative_spine, target_feeling, pattern_as_evidence_of |
| Hook Engine | safe_conclusions, narrative_spine, never_blank_insight | hook_candidates[], selected_hook |
| Reader Context | signal type, research domain | context_line (string or null) |
| Discovery Builder | hook, hypothesis_history, safe_conclusions, narrative_spine | observation, recognition, evidence_sequence[], explanation_setup |
| Story Assembly | discovery output, spine, decision_lens, signal | surviving_explanation, reframe, remaining_uncertainty, business_translation |
| Never Blank Voice | complete article blocks, spine | echo (string or null), cta (string or null), checklist_pass, structured_article |
| Platform Composer | structured_article JSON | long / reading / medium / instagram / short |

---

## 7. Quality Gates

The Editorial Engine may not produce a final article if:

1. Hook Engine selected a hook that could have been written without reading the investigation
2. Discovery Builder Recognition moment is generic rather than a specific, recognizable situation
3. Evidence Reveal contains a claim not traceable to `safe_conclusions`
4. Story Assembly Reframe is not specific to this pattern (applies to any business article)
5. Never Blank Voice Echo (if present) is generic enough to appear in a different article
6. CTA (if present) uses any of the forbidden phrases
7. Checklist has any item marked false

If any gate fails, the module returns to the relevant stage — not to the beginning.

---

## 8. Relationship to Investigation Layer

The Editorial Engine is downstream. It cannot:
- Send signals back to the Investigation Layer
- Request additional research
- Override evidence status in the investigation report
- Omit material uncertainty to produce a cleaner narrative

It can:
- Choose which `safe_conclusions` to foreground
- Shape the Recognition moment to match the reader's likely experience
- Frame `remaining_uncertainty` as an open question rather than a caveat

The investigation determines what is true about the pattern.
The Editorial Engine determines how the reader encounters it.

---

*The reader is the central character. The article succeeds when they recognize themselves.*
