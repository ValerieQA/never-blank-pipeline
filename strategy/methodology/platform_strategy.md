# Never Blank — Platform Strategy

**Status:** Production  
**Last updated:** 2026-07-22  
**Decision:** 44 (platform principle: each platform gets independent composition)

---

## Core rule

One article brief → independent compositions per platform.  
Not one text with mechanical truncation.  
Not one text with hashtags added.

Each platform has a different reader context, consumption mode, and platform algorithm. The same idea must be recomposed, not resized.

---

## Website / Blog

**Reader context:** searching, comparing, evaluating. May arrive via search or direct.

**Requirements:**
- SEO: target keywords in headline, subheadings, first paragraph
- GEO (generative engine optimization): write to answer questions an AI assistant might be asked. Use natural-language question phrasing as subheadings where relevant
- Query coverage: semantic completeness — related concepts the reader might search for
- Structure: clear H2/H3 hierarchy, short paragraphs, internal links to related articles
- Sources: factual claims must be traceable. No invented statistics
- AI-search readability: the article must be quotable in a 1–2 sentence summary without losing meaning
- Length: enough for the argument, not padded. 600–1200 words typical range

**What to avoid:**
- Opening with a corporate news item
- Generic "it's important to" phrasing
- Walls of text without subheadings
- Claims without source traceability

---

## LinkedIn

**Reader context:** professional, B2B, feed-scanning. Wants recognition and analytical value.

**Requirements:**
- Strong opening sentence — the first line appears before "see more." It must create a reason to expand
- Dwell time: the text must hold attention. Recognition first, then mechanism
- No walls of text: short paragraphs, white space
- Saves and comments are the signal — aim for posts people save and send to a colleague
- B2B relevant: the reader is a professional who manages or owns a small service business
- 3–5 article-specific hashtags (not generic: #marketing, #smallbusiness)
- Source attribution: one bare URL at the end if article exists

**Format:** Medium length. Full arc: Hook → Recognition → Mechanism → Reframe → (Compound Presence, woven) → Echo → CTA if applicable.

---

## Instagram

**Reader context:** phone, visual consumption, scrolling. Saves and shares are the primary signal.

**Requirements:**
- Visual hook in the first line — not a topic statement, the point
- Emotional recognition before analytical explanation
- One idea per paragraph, blank lines as pacing
- Caption must work alongside the image (image carries hook visually; caption extends it)
- Save/share intent: the reader must feel "I want to come back to this" or "I need to send this to someone"
- 3–5 hashtags, article-specific
- No text that could appear unchanged on LinkedIn — different register entirely

**What to avoid:**
- Analytical opening (that is LinkedIn)
- Long sentences
- Content that is "compressed LinkedIn" — must feel cinematic, not analytical

---

## Facebook

**Reader context:** conversational, community-oriented. Shares and comments are primary.

**Requirements:**
- Self-contained: the post must make sense without the blog article
- Conversational register: slightly warmer than LinkedIn, more direct
- Human-first: less formal structure, more storytelling
- Not the same text as LinkedIn — different opening, different feel
- Longer than Instagram, shorter than blog

**Format:** Narrative, reading-length adaptation of the article angle.

---

## Threads

**Reader context:** fast-moving, idea-dense. Follows cognitive chains.

**Requirements:**
- 3–5 standalone posts that build as a sequence
- Arc: Hook → Recognition → Mechanism → Reframe → Echo
- Each post must stand alone — someone seeing only post 3 still gets value
- Each post adds something the previous did not say — never restate
- No hashtags
- No numbering (not "1/5")
- Echo post is the last position — an implication or uncomfortable truth, never advice

**What to avoid:**
- Summarizing the blog article
- Motivational closing ("bridges must be built," "you've got this")
- Any post that ends with a recommendation to do something

---

## Telegram

**Reader context:** signal channel. Readers want the observation itself, not a pointer to it.

**Format:** 3 lines maximum.

```
Line 1: One sharp observation — the pattern, not the topic
Line 2: One business implication — what this costs or changes
Line 3: [Optional] CTA if cta_mode ≠ none, or article link
```

**Hard constraints:**
- Maximum 3 non-empty lines
- Maximum 90 words
- No hashtags
- No "Read more," "New post out," "Check the link"
- No article summary or teaser
- Line 3 is absent when cta_mode = "none"

If the reader cannot get the insight from these 3 lines without clicking, the post failed.

---

## Cross-platform duplication check

Before publishing, `src/content/differentiation.py` runs pairwise Jaccard similarity across all platform outputs.

Threshold: 45% word-level Jaccard similarity flags a pair for review.

LinkedIn ↔ Facebook is the most common flag — they use similar vocabulary but must have different structure, register, and opening.
