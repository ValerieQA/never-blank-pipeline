# Never Blank — Platform and Visual Strategy

This document defines each platform's role in the Never Blank content system.
It is the authoritative reference for what each platform does, what blocks it uses,
and how CTA and Echo behave on each channel.

---

## Blog

**Function:** Primary long-form format. The full research arc, structured for reading.

**Depth:** All blocks from structured_article.

**Blocks included:** hook, reader_context (if present), observation, recognition,
evidence_pattern, explanation, reframe, business_meaning, echo (if present), cta (if present)

**Blocks excluded:** none

**CTA behavior:** Follows article-level cta block directly. Campaign cta_mode governs
whether a CTA is present; the Blog always expresses it in full paragraph form.
CTA appears before Echo, never after.

**Echo behavior:** Verbatim. The Blog is where the Echo is authored — all other platforms
derive from it.

**Format:** 700–1000 words. Flowing prose. No bullet lists in the main body.
Paragraph spacing for phone readability.

**Relation to article:** Primary (is the article)

**Visual type:** Dark editorial photograph. High contrast. No text overlay.
visual_anchor from the article idea. No generic imagery.

**Success signals:** Reader finishes. Reader recognizes their situation.
Reader does not leave thinking they received advice.

---

## LinkedIn

**Function:** The most commercially visible format. One observation, recognition,
and specific business implication. Feed-optimized for professionals.

**Depth:** Medium — uses hook, recognition, explanation, reframe, echo, cta.

**Blocks included:** hook, recognition, explanation (compressed), reframe, echo, cta

**Blocks excluded:** reader_context, evidence_pattern, business_meaning (merged into reframe)

**CTA behavior:** Campaign cta_mode governs. When present, CTA is a paragraph-length
invitation specific to the article's pattern. Never generic. Appears before Echo.

**Echo behavior:** Verbatim. LinkedIn is the second venue (after Blog) where the Echo
is preserved exactly. Strong echo can carry the post without any CTA.

**Format:** 350–600 words. Short paragraphs. 3–5 niche hashtags.
No preamble. Opens on the hook.

**Relation to article:** Primary (derived from article, independently valuable)

**Visual type:** Same as Blog — editorial photograph, dark palette, visual_anchor driven.
Never a carousel of tips or motivational quotes.

**Success signals:** High saves and shares relative to impressions.
Comments that show recognition ("this is exactly what is happening in my business").

---

## Instagram Feed

**Function:** Literary/emotional format. The reader feels the pattern before they understand it.
Visual anchor carries half the meaning; caption completes it.

**Depth:** Shallow — hook, observation, recognition only. No evidence, no analysis.

**Blocks included:** hook (compressed), observation (compressed), recognition (compressed),
echo (adapted)

**Blocks excluded:** reader_context, evidence_pattern, explanation, reframe, business_meaning

**CTA behavior:** If cta_mode is "none" — no CTA in caption. If cta_mode is any other value,
add one short (1 sentence) platform-adapted CTA at the end of the caption (before echo).
Must feel natural in caption style — not a LinkedIn paragraph.
Example: "If you recognize this — DM me and I'll show you where the gap is."

**Echo behavior:** Adapted. The semantic content of the echo is preserved, but the wording
is adjusted to feel native to Instagram caption voice. Not copy-pasted verbatim.

**Format:** 80–200 words (not counting hashtags). One paragraph or very short sections.
5–10 niche hashtags. No generic hashtags.

**Relation to article:** Derived (emotional signal, not analysis)

**Visual type:** visual_anchor from article idea. Dark, high-contrast editorial style.
Never generic entrepreneur-with-laptop. No motivational quote overlays.

**Success signals:** Saves. "This is exactly it" comments. New follower quality.

---

## Facebook

**Function:** More human and conversational version of the same idea. Longer recognition
section. Direct questions to the audience allowed. Diagnostic CTA allowed.
More personal tone than LinkedIn.

**Depth:** Medium-full — similar to LinkedIn but warmer, with extended recognition.

**Blocks included:** hook, recognition (full, extended), explanation (compressed),
reframe, business_meaning (compressed), echo (adapted), cta

**Blocks excluded:** reader_context, evidence_pattern

**CTA behavior:** Campaign cta_mode governs. Diagnostic CTA is well-suited to Facebook —
conversational question format works here ("If this is happening in your business, I'm
interested in hearing where it starts"). Direct questions to audience are allowed.

**Echo behavior:** Adapted. Facebook voice is warmer and more personal than LinkedIn.
Echo wording adjusted to match — the thought is preserved, phrasing softened slightly.

**Format:** 300–500 words. Conversational tone. Can include a direct question to the reader.
No hashtags or 1–2 maximum. No corporate vocabulary.

**Relation to article:** Derived (human version of the same idea)

**Visual type:** Same visual family as Blog/LinkedIn. Can be slightly warmer in treatment
(less stark), but still editorial. No lifestyle imagery.

**Success signals:** Comments with personal experiences. Shares with context ("this happened
to me"). Diagnostic inquiry replies.

---

## Threads

**Function:** A 5-post cognitive arc. Builds tension across posts. Each post adds a new
step — not a restatement. No hashtags. No article summary.

**Depth:** Selective — each post covers one cognitive step from the arc.

**Blocks included (distributed across posts):**
- Post 1 (Hook): hook
- Post 2 (Recognition): recognition
- Post 3 (Mechanism): explanation
- Post 4 (Reframe): reframe
- Post 5 (Echo): echo (adapted)

**Blocks excluded:** reader_context, evidence_pattern, business_meaning, cta

**CTA behavior:** No CTA in Threads. The arc closes on Echo, not an invitation.

**Echo behavior:** Adapted. Post 5 carries the semantic content of the echo, but phrased
for Threads voice — blunt, short, punchy. Not the verbatim Blog/LinkedIn echo.

**Format:** 3–5 posts (target 5). Each post max 500 characters.
No hashtags. No numbering ("1/5" etc). Each post must stand alone.

**Relation to article:** Derived (thinking progression, not summary)

**Visual type:** No image required on Threads. If used, same editorial palette.

**Success signals:** Replies that engage with the mechanism or reframe.
Reposts of individual posts (especially Post 3 or Post 5).

---

## Stories

**Function:** Interactive channel. Not a summary of the article.
4-frame arc: recognition → hidden mechanism → reframe → interactive moment.

**Depth:** Shallow and experiential. One cognitive step per frame.

**Frames:**
- Frame 1 (Recognition): Reader sees themselves in the pattern
- Frame 2 (Mechanism): What is actually happening underneath
- Frame 3 (Reframe): It is not what they thought
- Frame 4 (Interaction): Poll, question box, or CTA depending on cta_mode

**CTA behavior:**
- cta_mode "none" → Frame 4 is a question box (no CTA)
- cta_mode "diagnostic" → Frame 4 is a direct CTA ("Show me how your presence is organized")
- cta_mode "reflection" → Frame 4 is a question box with a reflective prompt
- cta_mode "example_request" → Frame 4 is a CTA to reply for an example
- cta_mode "direct_conversation" → Frame 4 is a poll ("Does this happen in your business?")

**Echo behavior:** Not used in Stories. Frame 3 (Reframe) carries the insight.

**Format:** 4 frames. 1–2 sentences per frame. Written for a phone screen.
Second person throughout ("you", "your"). No hashtags. No article title.

**Relation to article:** Derived (interactive signal, not content delivery)

**Visual type:** Branded Stories design using Never Blank color palette.
Text-on-color or text-on-dark-image. No generic stock imagery. visual_anchor informs
the visual tone of frames 1–2.

**Success signals:** Frame 4 interaction rate (poll responses, question box replies).
Story completion rate (viewers who watch all 4 frames).

---

## Telegram

**Function:** Signal channel. One sharp observation + one business implication + optional link.
NOT an announcement. NOT a copy of LinkedIn. NOT a newsletter teaser.

**Depth:** Minimal — 3 lines maximum. The observation itself, not a pointer to it.

**Blocks included:** observation (compressed to one line), mechanism or cost_of_ignoring
(one implication), optional link

**Blocks excluded:** everything else

**CTA behavior:**
- cta_mode "none" → no CTA, no link. Two-line signal only.
- cta_mode "diagnostic" → "Reply if you recognize this." or similar (one short sentence)
- cta_mode "reflection" → one short reflective sentence
- cta_mode "example_request" → "Reply to see what this looks like in practice."
- cta_mode "direct_conversation" → "Reply if you want to look at where this is happening in your business."
- Any non-none cta_mode may also include the [link] placeholder as the third line.

**Echo behavior:** Not used. Telegram is too compressed for an echo.

**Format:** 3 lines maximum. No hashtags. No "Read more." No "Check the link."
No "New post out." The insight is the post.

**Relation to article:** Signal (independent observation, not article promotion)

**Visual type:** No image on Telegram. Text only.

**Success signals:** Replies that show recognition. Forwards. Direct message follow-ups.

---

## Content Cadence

2–3 research themes per week.

Each theme selects active platforms based on what the idea offers each platform.
Not every theme must go to every platform.

A platform is activated when the idea has something to give that platform — not because
the calendar says a post is due. An analytical mechanism that needs depth goes to Blog and
LinkedIn first. A sharp visual pattern may lead with Instagram and Stories. A signal that
reads cleanly in 3 lines belongs on Telegram even if LinkedIn is not ready.

The `active_platforms` field in each content brief controls which platforms are generated
for that campaign. If absent, defaults to `[blog, linkedin]`.

---

## Design Constraints (current)

- Use existing Never Blank color palette
- No generic entrepreneur-with-laptop AI imagery
- visual_anchor must be derived from the article's core idea, not from a generic
  "content strategy" visual library
- Carousel and Stories must be built from editorial blocks, not design templates
- Do not create a separate visual system for Presence Debt until the concept is validated
  (evaluate after Campaign 1 whether the term earns a distinct visual identity)
- Quote cards use Inter font, dual composition templates (as established)
