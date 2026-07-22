# Narrative Spine
## The Central Thought Before the Article Begins

**Version:** v0.2 — Updated for small-business visibility editorial identity  
**Status:** Live  
**Position in pipeline:** Between Decision Lens and Hook Engine.

---

## 1. What This Is

The Narrative Spine is one sentence.

It is not the hook. It is not the headline. It is not the business lesson.

It is the answer to the question: **what is this article actually about?**

Not the signal. Not the statistic. Not the platform.
The pattern. The mechanism. The invisible thing the research surfaced.

The signal is evidence. The Narrative Spine is what the evidence proves about
how small businesses maintain or lose commercial presence.

---

## 2. Why This Exists

Without a Narrative Spine, every module in the Editorial Engine answers "what is this
article about?" independently.

The Hook Engine guesses from the signal.
The Discovery Builder guesses from the hook.
The Story Assembly guesses from the discovery.

Each is working from a different starting point. The result is an article where
the hook points one direction, the middle goes another, and the Echo arrives from
somewhere else entirely. The reader feels it — even if they cannot name it.

The Narrative Spine is established once, before any editorial module runs.
Every module then builds toward it.

---

## 3. Three Questions

The Narrative Spine answers exactly three questions for visibility/presence patterns.

**Question 1 — What pattern does this article actually investigate?**

Not the signal that triggered the article. The underlying pattern.
The thing that would be happening even if no one was measuring it.

> Pattern: The moment presence stops being maintained is almost never the moment
> the owner decides to stop — it is the moment they get busy enough that it
> falls off the schedule.

> Pattern: Accumulated recognition degrades faster during silence than it was built
> during presence.

> Pattern: A business whose content output is tied to the owner's energy will
> be least visible precisely when it most needs to be visible.

**Question 2 — What one sentence expresses this thought?**

The Spine itself. The single sentence the entire article is built to earn.

It must:
- Work for any small business owner, not just the one whose signal triggered the article
- Be specific enough to be wrong for some situations
- Sound like something a reader would want to remember

> "If presence depends only on the owner's free time, silence eventually becomes
> part of the strategy — even when nobody chose it."

> "Customers rarely decide to forget a business. They simply stop encountering it."

> "The work gets done. The record of it doesn't. Those are not the same problem."

> "A business that goes quiet during its busiest period teaches its clients
> something it did not intend to teach."

It must not:
- Be generic ("businesses should be more consistent")
- Summarize a signal ("founder X reduced posting by 40%")
- Repeat the hook

**Question 3 — What feeling should remain after the last line?**

Not a summary. Not a lesson restated.
An emotional register. The thing the business owner carries.

| Feeling | When it fits | Example reader response |
|---|---|---|
| `recognition` | The reader has been in exactly this situation | "This is what happened to me last quarter." |
| `unease` | The reader suspects they are in this pattern right now | "I have not published anything in three weeks." |
| `reframe` | The reader now sees a familiar situation differently | "I thought I was being strategic. I was being absent." |
| `clarity` | Something previously vague now has a name | "I never had words for why this happens." |
| `anticipation` | The reader wants to understand what comes next | "Now I know what to watch for." |

The feeling is not stated. It is engineered through the Recognition step,
the Reframe, and the Echo.

---

## 4. Output Format

```json
{
  "signal_id": "string",
  "core_pattern": "string — the underlying visibility/presence pattern, one sentence",
  "narrative_spine": "string — the central thought the article earns",
  "target_feeling": "recognition | unease | reframe | clarity | anticipation",
  "pattern_as_evidence_of": "string — what this pattern proves about small business presence"
}
```

**Example:**

```json
{
  "signal_id": "sig_busy_silence_2026",
  "core_pattern": "Small business owners consistently reduce or stop content activity during their highest-revenue periods, creating the appearance of stagnation precisely when they are most successful.",
  "narrative_spine": "If presence depends only on the owner's free time, silence eventually becomes part of the strategy — even when nobody chose it.",
  "target_feeling": "recognition",
  "pattern_as_evidence_of": "What it costs when visibility is a task rather than a system"
}
```

**Example:**

```json
{
  "signal_id": "sig_recognition_decay_2026",
  "core_pattern": "Customer familiarity with a business degrades during periods of silence faster than it was built during periods of consistent presence.",
  "narrative_spine": "Customers rarely decide to forget a business. They simply stop encountering it.",
  "target_feeling": "unease",
  "pattern_as_evidence_of": "Why accumulated recognition is more fragile than it feels from the inside"
}
```

---

## 5. Rules

**The Spine must be established before any Editorial Engine module runs.**
Hook Engine, Discovery Builder, and Story Assembly all receive the Spine as input.
They do not derive it themselves.

**The Spine is not the hook.**
The hook creates a gap. The Spine closes it. The reader earns the Spine at the end
of the article — they do not receive it at the beginning.

**The Spine must work for the reader, not about a company.**
This is the key difference from large-company strategy analysis. The reader is not
studying what another company did. They are recognizing what is happening in their
own business. The Spine must work from that position.

If the Spine requires knowing what a specific company did — it is a description of
an event, not a pattern.

**The Spine comes from Decision Lens output, not from Investigation alone.**
Investigation finds what is true. Decision Lens identifies what it means.
Narrative Spine expresses what the article is for.

**One spine per article.**
An article with two spines has none. If two distinct patterns emerged from the
investigation, they become two articles.

---

## 6. What Changes Downstream

| Module | Before Narrative Spine | After Narrative Spine |
|---|---|---|
| Hook Engine | Generates hooks from signal | Generates hooks that create a gap the Spine fills |
| Discovery Builder | Constructs a pattern sequence | Constructs a path toward the Recognition moment |
| Story Assembly | Derives a lesson | Translates the Spine into commercial reality |
| Never Blank Voice | Checks that the article sounds like Never Blank | Checks that the Echo earns the Spine by the last line |

---

## 7. The Shortest Test

Read only the first sentence and the Echo of the finished article.

If they feel like they belong to the same thought — the Spine worked.
If they feel like two different articles — go back to the Spine.

---

*The Narrative Spine is the one thing the article is trying to say.
Everything else is how it gets there.*
