# Narrative Spine
## The Central Thought Before the Article Begins

**Version:** v0.1 — Specification Only  
**Status:** Spec. No code yet.  
**Position in pipeline:** Between Decision Lens and Hook Engine.

---

## 1. What This Is

The Narrative Spine is one sentence.

It is not the hook. It is not the headline. It is not the business lesson.

It is the answer to the question: **what is this article actually about?**

Not the event. Not the company. Not the news.  
The decision. The pattern. The idea.

The company is evidence. The Narrative Spine is what the evidence proves.

---

## 2. Why This Exists

Without a Narrative Spine, every module in the Editorial Engine answers "what is this article about?" independently.

The Hook Engine guesses from the investigation output.  
The Story Builder guesses from the hook.  
The Business Translation guesses from the story.

Each is working from a different starting point. The result is an article where the hook points one direction, the middle goes another, and the lesson arrives from somewhere else entirely. The reader feels it — even if they can't name it.

The Narrative Spine is established once, before any editorial module runs. Every module then builds toward it.

---

## 3. Three Questions

The Narrative Spine answers exactly three questions. Nothing more.

**Question 1 — What decision does this article actually investigate?**

Not the event the signal describes. The underlying decision.  
The thing that would have been decided even if no one was watching.

> Getty: The decision to change what you're trying to win — before you lose the thing you're currently fighting for.  
> Toyota: The decision to hold a conviction under pressure until the market catches up.  
> Polymarket: The decision of when to remove a barrier you created yourself.  
> UPS: The decision to own a bottleneck rather than rent it.

**Question 2 — What one sentence expresses this thought?**

The Spine itself. The single sentence the entire article is built to earn.

It must:
- Work without the company name
- Be specific enough to be wrong for some situations
- Sound like something a reader would want to remember

> Getty: "Winning the wrong war is still losing."  
> Toyota: "Long-term conviction is an organizational capability — not a strategic stance."  
> Polymarket: "Distribution windows close faster than product cycles."  
> UPS: "The bottleneck becomes the business."

It must not:
- Be generic ("companies should think long-term")
- Summarize what happened ("Getty partnered with OpenAI instead of suing")
- Repeat the hook

**Question 3 — What feeling should remain after the last line?**

Not a summary. Not a lesson restated.  
An emotional register. The thing the reader carries.

| Feeling | When it fits | Example |
|---|---|---|
| `reframe` | The reader now sees something familiar differently | "I've watched other companies do this wrong for years." |
| `recognition` | The reader has faced this decision or seen it | "This is the decision I never realized I was making." |
| `unease` | The reader suspects they're in a similar position | "What war am I currently winning that doesn't matter?" |
| `clarity` | Something previously vague has a name | "I never had words for this before." |
| `anticipation` | The reader wants to see what happens next | "Now I'll be watching for when this breaks." |

The feeling is not stated. It is engineered through the last paragraph and the signature line.

---

## 4. Output Format

```json
{
  "signal_id": "string",
  "core_decision": "string — the underlying decision, one sentence",
  "narrative_spine": "string — the central thought the article earns",
  "target_feeling": "reframe | recognition | unease | clarity | anticipation",
  "company_as_evidence_of": "string — what the company proves, not what it did"
}
```

**Getty example:**
```json
{
  "signal_id": "getty-openai-deal-2023",
  "core_decision": "Switching the definition of winning before the current definition becomes impossible to fulfill",
  "narrative_spine": "Winning the wrong war is still losing.",
  "target_feeling": "reframe",
  "company_as_evidence_of": "The moment to change what you're fighting for comes before you lose — not after"
}
```

**Toyota example:**
```json
{
  "signal_id": "toyota-hybrid-outsells-gm-2026",
  "core_decision": "Holding a multi-year conviction while the market actively punishes you for it",
  "narrative_spine": "Long-term conviction is an organizational capability — not a strategic stance.",
  "target_feeling": "recognition",
  "company_as_evidence_of": "What it actually costs to stay right before the market agrees with you"
}
```

---

## 5. Rules

**The Spine must be established before any Editorial Engine module runs.**  
Hook Engine, Story Builder, and Business Translation all receive the Spine as input. They do not derive it themselves.

**The Spine is not the hook.**  
The hook creates a gap. The Spine closes it. The reader earns the Spine at the end of the article — they do not receive it at the beginning.

**The Spine must survive without the company name.**  
If removing the company name makes the sentence meaningless, it is describing an event — not a decision pattern.

**The Spine comes from Decision Lens output, not from Investigation.**  
Investigation finds what is true. Decision Lens identifies what it means. Narrative Spine expresses what the article is for.

**One spine per article.**  
An article with two spines has none. If two distinct patterns emerged from the investigation, they become two articles.

---

## 6. What Changes Downstream

| Module | Before Narrative Spine | After Narrative Spine |
|---|---|---|
| Hook Engine | Guesses what the article is about from investigation output | Generates hooks that create a gap the Spine fills |
| Story Builder | Constructs a revelation sequence from evidence | Constructs a path toward the Spine |
| Business Translation | Derives a lesson from the surviving explanation | Translates the Spine into universally applicable terms |
| Never Blank Voice | Checks that the article sounds like Never Blank | Checks that the article earns the Spine by the last line |

---

## 7. The Shortest Test

Read only the first sentence and the last sentence of the finished article.

If they feel like they belong to the same thought — the Spine worked.  
If they feel like two different articles — go back to the Spine.

---

*The Narrative Spine is the one thing the article is trying to say.  
Everything else is how it gets there.*
