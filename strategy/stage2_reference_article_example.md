# Stage 2 — reference example: what "wiring worked" actually means

Added 2026-08-07, source: Val's alignment-check conversation with GPT
about Stage 2 direction. Referenced from `decision_log.md`.

## The point this example exists to make

Stage 2 (`ResearchContext → EditorialContext → Editorial Engine`) fixes
*data plumbing* — the Editorial Engine gets the right research signal,
facts, source, strategy and context instead of a stale JSON or an
accidentally-admitted signal. That is necessary but **not sufficient**.

If, after wiring, the Editorial Engine still produces a generic,
"importance-of-consistent-content" article, the data pipe was fixed but
the Editorial Engine itself was not. **Acceptance test for Stage 2 is not
"does the typed object reach the engine" — it's "can the engine write an
article like the one below, using the context it now receives."** Passing
a clean typed object through and getting back the same shallow article,
converted from a stripped legacy dict, means the wiring is technically
done and the product has not moved forward at all.

## Input signal (hypothetical, for calibration)

- Small business owners increasingly use AI to generate content.
- The real problem is no longer "not enough content" — it's sameness,
  loss of brand voice, and no system behind the output.
- Signal confirmed by sources, `article_ready=True`, relevant to Never
  Blank's strategy, source/audience/business-angle/publication-reason all
  known.

## Reference article ("ideal output")

**Headline:** Вашему бизнесу не нужно больше контента. Ему нужна память
*(Your business doesn't need more content. It needs memory.)*

Core structure, in order:
1. **Open on the now-trivial mechanics of AI content** — open ChatGPT,
   ask for five ideas, publish, repeat next week. Surface problem solved;
   real problem introduced: every new post acts like nothing came before
   it. AI doesn't know what's already been said, what landed, that the
   last four posts repeat one idea in different words, or how a new
   industry signal connects to *this* business specifically. Content gets
   produced; brand presence doesn't get built.
2. **"Regularity without memory becomes noise"** — worked example: a
   small financial company posts about retirement savings in January,
   financial planning in February, retirement savings again in March
   under a different headline. Each piece is fine alone; together they
   don't show development of thought. This is the line between a
   "publication generator" and a "presence system." A generator answers
   *what do we publish today*. A system has to answer: what's already
   been said, what's changed since, why does this matter now, how does it
   connect to the product/experience, what should the reader understand
   after reading, what's the natural next step in the conversation.
3. **"Real AI value doesn't appear at generation time"** — value
   accumulates when the system remembers: positioning, products/services,
   real customer stories, already-published topics, preferred brand
   voice, audience reactions, industry shifts, past owner decisions. Over
   months the system doesn't just write faster — it gets more accurate
   about what the company should say and why. That's the advantage no
   single good prompt can produce.
4. **"Good content doesn't start from a blank document — it starts from a
   signal."** A shift in customer need, a new question, competitors
   repeating the same idea, an industry contradiction, old material
   becoming relevant again for new reasons. The system must then check
   the signal: enough confirmation? fits business strategy? a genuinely
   new angle, not a repeat? can it become something useful to the reader?
   does the company have standing to speak on it? Only then does writing
   start — otherwise AI produces filler, not a content system.
5. **"Continuous presence isn't daily publishing"** — a business doesn't
   need to post every day, but it shouldn't start from zero each time.
   Continuity means each new post accounts for what came before and
   sharpens the overall picture — turning scattered channel posts into
   one continuing story about what the company sees, understands,
   believes, can solve, and why it can be trusted.
6. **Close:** Never Blank's job isn't to make a business produce more
   content — it's to remove the owner's burden of constantly inventing
   what to say, while preserving meaning, recognizability, and connection
   to reality. Emptiness doesn't disappear when AI fills a page with
   words. It disappears when the business has something to say — and the
   system didn't lose it.

**Why this is judged a good result:** doesn't open with a "in today's
digital world" cliché; carries one clear thesis (the problem isn't
generation, it's missing memory); explains the product through the
problem without turning into a flyer; makes the Never Blank vs. generic
AI-generator distinction concrete; has a specific example; leads
logically to the product; reads as a company's position, not a
rewritten SEO article; can seed several social posts.

## Visual system for this article

Explicitly rejected: another robot/laptop/floating-social-icons stock
image — visually indistinguishable from a thousand other AI-content
pieces.

Single concept: **"content with memory."**

| Format | Visual | On-visual text |
|---|---|---|
| Article hero | Several scattered sheets turning into one connected storyline | "Your business doesn't need more content. It needs memory." |
| IG carousel, slide 1 | Clean background, one blank document among many identical ones | "More content won't fix a missing system." |
| Slide 2 | Three nearly identical post cards | "New post. Same idea. Different headline." |
| Slide 3 | Timeline: past posts → new market signal → next topic | "Content should remember what came before." |
| Slide 4 | Two columns: Generator / Presence System | "Generates words / Builds continuity" |
| Slide 5 | Connected dots: brand, history, audience, market signals | "Memory makes the system smarter over time." |
| Slide 6 | Minimal Never Blank brand screen | "Never start from a blank page again." |

Style direction: editorial, not tech-futuristic; warm cream or light-gray
background; graphite text; one bright brand accent color; sheets/cards
connected by a thin continuous line; no literal robot; format adapts
cleanly to Wix hero, LinkedIn, and Instagram.

## How to use this file

This is a calibration reference, not a template to copy structurally
every time — Editorial Engine variety still matters (decision 43: Echo
in the large majority, not literal 100%; territory/voice rules elsewhere
in `decision_log.md` still govern). Use it to judge, after Stage 2 wiring
lands, whether a generated article reaches this level of specificity and
argument — not whether it matches this article's exact six-section shape.
