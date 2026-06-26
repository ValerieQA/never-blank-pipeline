# Investigation Question Library

**Version:** 0.1
**Status:** Draft
**Branch:** feature/business-investigation-layer

---

## What this document is

This is the intellectual core of the Curiosity Engine.

It defines the questions Never Blank must ask for each class of business signal —
before any source is consulted, before any conclusion is drawn, before any article
is written.

This document does not describe implementation.
It does not describe APIs, code, or prompts.
It describes *curiosity* — the specific type of curiosity Never Blank develops
in response to different categories of business events.

> **The principle behind this library:**
> Sources are a consequence of questions, not the starting point.
> A system that starts from "what sources are available?" produces
> source-constrained thinking.
> A system that starts from "what must we understand?" produces
> investigation-driven thinking.

---

## How to read each entry

Each signal type contains:

**Primary Questions** — must be answered before any conclusion is possible.
If none of these can be answered with Tier 1 or Tier 2 evidence, the investigation
returns `INSUFFICIENT`.

**Secondary Questions** — deepen the investigation. Partial coverage is acceptable.
These produce the texture that separates a Never Blank article from generic coverage.

**Evidence Needed** — the type of evidence that would satisfy each primary question.
Described in terms of what it is, not where to find it.

**Possible Sources** — where that evidence might live. Listed from most to least
reliable. The Evidence Collector consults this list; the Curiosity Engine only
defines it. Sources are a hypothesis, not a constraint.

---

## Signal types

1. [Layoffs](#layoffs)
2. [Pricing](#pricing)
3. [Fundraising](#fundraising)
4. [Acquisition](#acquisition)
5. [Regulation](#regulation)
6. [AI Adoption](#ai-adoption)
7. [Hiring / Headcount Growth](#hiring--headcount-growth)
8. [Leadership Change](#leadership-change)
9. [Product Launch / Kill](#product-launch--kill)
10. [Market Exit / Retreat](#market-exit--retreat)

---

## Layoffs

> The question is never "how many people were cut."
> The question is always "what decision was actually made, and why now?"

### Primary Questions

1. **Why now?**
   What changed in the last 90 days that made this the moment — not three months
   ago, not six months from now?

2. **What did the company actually decide?**
   Is this cost reduction, strategic repositioning, or both?
   What did they stop doing? What did they protect?

3. **Which parts of the company were cut, and which were spared?**
   The topology of the cut reveals the actual strategy more reliably than any
   press release.

4. **What did the people inside say vs. what did leadership say publicly?**
   The gap between internal experience and external messaging is often where
   the real story lives.

### Secondary Questions

5. What was the headcount trajectory over the previous two years?
6. What were the company's last public commitments to employees or investors?
7. What did competitors do over the same period?
8. What do Glassdoor or employee communities suggest about culture before the cut?
9. What happened to companies that made comparable cuts 12–24 months ago?
10. What board or investor pressure preceded the decision?
11. What did they announce as priorities immediately after the cut?
12. What role or function grew after the layoff?
13. Was this the first cut, or part of a pattern?
14. What happened to customers or products that depended on the cut teams?

### Evidence Needed

| Question | Evidence type |
|---|---|
| Why now | Earnings call transcript, CEO interview, investor letter, board minutes if public |
| What was decided | Official announcement, org chart changes, job posting changes |
| Who was cut / spared | Headcount data, department-level reports, LinkedIn changes |
| Internal vs. external narrative | Employee letters, internal memos if leaked, Glassdoor posts (directional) |

### Possible Sources

- Earnings call transcripts (Seeking Alpha, company IR page)
- CEO letters and public interviews (company blog, press, podcast appearances)
- SEC filings (8-K for material changes)
- LinkedIn headcount data (third-party tracking tools)
- Glassdoor / Blind (directional only — aggregate sentiment, not individual posts)
- Reddit / HackerNews layoffs threads (community corroboration)
- Layoffs.fyi (scale and timing comparison)
- Historical coverage of same company

---

## Pricing

> A price increase is rarely about money.
> It is almost always about who the company decided it no longer needs to serve.

### Primary Questions

1. **What specifically changed, and by how much?**
   Exact price, tier, feature access, or bundle. Vague answers produce vague articles.

2. **Who absorbs the cost — the business or the end customer?**
   B2B pricing changes often get passed downstream. Understanding the chain matters.

3. **What alternatives did the company have, and why were they rejected?**
   Every pricing decision is a choice among options. The rejected options reveal
   the real constraint.

4. **What triggered this now?**
   Cost pressure, competitive reposition, margin expansion, or investor demand?
   These have different implications for durability and customer response.

### Secondary Questions

5. What did competitors charge before and after this change?
6. Who chose a different path, and what happened to their metrics?
7. What do power users or heavy customers say about willingness to pay?
8. Is a free tier, legacy pricing, or workaround still available?
9. What happened to churn after the last pricing change at this company?
10. What does this price signal about their cost structure or unit economics?
11. What customer segment does this implicitly abandon?
12. Was there an advance notice period, and how was it communicated?

### Evidence Needed

| Question | Evidence type |
|---|---|
| What changed | Official pricing page, changelog, customer email, press release |
| Who absorbs cost | Terms of service, customer forum posts, analyst commentary |
| Alternatives rejected | CEO / CFO comments in earnings or interviews |
| What triggered it | Earnings transcript, investor presentation, macro context |

### Possible Sources

- Company pricing page (current + Wayback Machine for before/after comparison)
- Customer email announcements
- Earnings call transcript (CFO commentary on margin)
- CEO / product interviews
- Product forums and community (Reddit, HackerNews, Product Hunt)
- Competitor pricing pages
- SaaS metrics trackers (Baremetrics, ChartMogul if publicly shared)

---

## Fundraising

> The round itself is not the story.
> The story is what the timing, the investor, and the terms reveal about
> where the company actually stands.

### Primary Questions

1. **Why raise now?**
   What does the timing reveal — strength from a position of leverage,
   or urgency from a position of pressure?

2. **Who led the round, and what does that investor's portfolio and thesis say?**
   Lead investors pattern-match. What pattern does this fit?

3. **What will the capital actually be used for — stated vs. inferred?**
   Press releases say "growth." The inferred answer comes from what the company
   has been unable to do without this capital.

4. **What does the valuation imply about expectations?**
   The multiple on revenue or users sets a bar. How realistic is it?

### Secondary Questions

5. How long did the previous runway last, and what burn rate does this imply?
6. What alternatives existed — strategic partnership, profitability, acquisition?
7. What did the founders say about fundraising strategy 12+ months ago?
8. What competitive landscape made investors believe the timing was right?
9. Who passed on the round, if known?
10. What are the dilution and governance implications for the founding team?
11. What has this lead investor done to other portfolio companies at this stage?
12. What does the cap table now look like in terms of control?

### Evidence Needed

| Question | Evidence type |
|---|---|
| Why now | Founder interviews, pitch narrative, competitive context |
| Investor thesis | Lead investor website, portfolio pattern, prior public statements |
| Capital use | Press release + inferred from job postings, product roadmap signals |
| Valuation expectations | Comparable round multiples, revenue if disclosed, analyst estimates |

### Possible Sources

- TechCrunch, The Information, Bloomberg (round announcement with details)
- Lead investor firm website and portfolio
- Founder interviews (podcast, press, conference talks)
- Crunchbase / PitchBook (cap table history)
- Job postings (what roles they plan to hire reveals use of capital)
- Previous founder statements about fundraising philosophy

---

## Acquisition

> Acquisitions are rarely about what the press release says.
> They are about what the acquirer could not build, could not buy time for,
> or could not afford to let a competitor have.

### Primary Questions

1. **What did the acquirer actually buy — technology, team, customers, or distribution?**
   These have different integration strategies and very different failure modes.

2. **What problem does this solve that organic growth could not?**
   The answer to this question reveals the acquirer's actual strategic constraint.

3. **What did the target company struggle with before the deal?**
   Acquisitions often rescue companies that were not going to make it independently.
   That context shapes what the acquirer is inheriting.

4. **What will likely be killed, kept, and integrated?**
   Based on the acquirer's previous M&A history and the stated rationale.

### Secondary Questions

5. What did the target's founders and employees say publicly about the deal?
6. What competing bids or alternative outcomes were reported?
7. What happened to previous acquisitions by this buyer?
8. What do the target's customers face now?
9. How does this change competitive dynamics in the category?
10. What does the price imply about market sizing and growth expectations?
11. What is the retention structure — earnouts, vesting cliffs, key-person dependencies?
12. What does the acquirer's existing product line look like alongside the target?

### Evidence Needed

| Question | Evidence type |
|---|---|
| What was bought | Acquirer announcement, product overlap analysis, team LinkedIn |
| Why not organic | CEO comments on build vs. buy, product gap analysis |
| Target's struggles | Target's funding history, growth signals, employee attrition before deal |
| Kill/keep/integrate | Acquirer's M&A playbook from previous deals |

### Possible Sources

- Official acquisition announcement (both companies' press releases)
- SEC filings (8-K, proxy if material)
- Acquirer's previous M&A outcomes (Crunchbase history)
- Target company employee LinkedIn activity (retention signals)
- Customer community reactions (forums, Reddit, Product Hunt)
- Analyst reports on category dynamics

---

## Regulation

> New rules don't change industries.
> The anticipation of new rules — and who prepared for them — changes industries.

### Primary Questions

1. **What specifically does the rule require or prohibit?**
   Regulatory language is often deliberately vague. What does implementation
   actually mean for a typical business in this sector?

2. **Who lobbied for it and who lobbied against it?**
   The political economy of a regulation reveals who benefits from compliance costs
   and who is threatened by them.

3. **What enforcement mechanism exists — is this real or symbolic?**
   A rule with no enforcement body and no penalty structure is a different thing
   from one with active agency oversight.

4. **Who is most exposed, and who benefits from the new compliance burden?**
   Compliance costs favor incumbents with legal infrastructure. Who specifically
   gains competitive advantage from this rule?

### Secondary Questions

5. What did industry do in anticipation — before the rule was final?
6. What happened in jurisdictions where similar rules already exist?
7. What is the timeline — when does compliance actually begin?
8. What workarounds exist, and how long will they be tolerated?
9. What does this signal about where the next rule will land?
10. What do founders and operators say vs. what do lawyers and lobbyists say?
11. What enforcement actions have already been taken under related rules?
12. What does non-compliance actually cost in practice?

### Evidence Needed

| Question | Evidence type |
|---|---|
| What it requires | Regulatory text, agency FAQ, legal commentary |
| Lobbying map | FEC filings, public comment records, lobbying disclosures |
| Enforcement reality | Agency budget, enforcement history, penalty record |
| Who benefits | Compliance cost analysis, incumbent vs. startup exposure |

### Possible Sources

- Federal Register / equivalent regulatory body text
- Public comment record (often reveals industry positions clearly)
- Lobbying disclosure databases
- Law firm client alerts (often the clearest plain-English summaries)
- Enforcement action history from same agency
- Comparison jurisdictions (EU, UK, other US states)
- Trade association statements

---

## AI Adoption

> The press release says "we deployed AI."
> The real story is: what actually changed for the people doing the work,
> and what happened to the things that didn't work?

### Primary Questions

1. **What specific workflow or role is being replaced or augmented?**
   "AI adoption" without a specific function is not a signal — it's marketing.

2. **What were the actual measured outcomes — not the announcement?**
   Productivity claims require denominators. What was the baseline,
   what changed, and who measured it?

3. **Who made the adoption decision, and what was their incentive?**
   The CTO optimizing for cost and the CEO optimizing for a press cycle
   make the same announcement for different reasons with different durability.

4. **What do the people affected say — from public record only, no speculation?**
   Not what they should feel, not what's logical — what did they actually say?

### Secondary Questions

5. What did comparable companies do, and what happened to their results?
6. What did the vendor claim vs. what was independently verified?
7. What broke or failed that was not announced?
8. What is the true cost of adoption — not just licensing, but integration, retraining, mistakes?
9. What skills or roles became more valuable as a result?
10. What does the adoption pattern suggest about industry-wide timing?
11. What happened to the people whose roles were eliminated or changed?
12. What is the failure mode if the AI system makes an error in this context?

### Evidence Needed

| Question | Evidence type |
|---|---|
| What workflow changed | Job posting changes, product documentation, employee statements |
| Actual outcomes | Company-published metrics, independent benchmarks, press investigation |
| Decision incentive | CEO/CTO interviews, earnings commentary on cost structure |
| Affected people | Employee forums, LinkedIn posts, union statements if applicable |

### Possible Sources

- Company blog / technical blog (most credible outcome claims)
- Earnings call (CFO comments on cost savings)
- CEO / CTO interviews on adoption rationale
- Independent researcher benchmarks
- Employee community posts (Glassdoor, Reddit, Blind)
- Trade press covering the specific function (not general tech press)
- Vendor case study (useful for stated claims, requires independent verification)

---

## Hiring / Headcount Growth

> Hiring announcements are about aspiration.
> The actual hires — who, at what level, from where — are about strategy.

### Primary Questions

1. **What functions are growing fastest, and what does that reveal about priority?**
   Headcount allocation is resource allocation made visible.

2. **Who are they hiring from, and what does that signal about direction?**
   Poaching patterns reveal competitive intent before any announcement.

3. **What is the implied cost structure of this headcount plan?**
   Hiring 200 engineers in San Francisco is a different bet than 200 in Warsaw.

4. **What does the hiring freeze or slowdown in other areas say?**
   Growth is never uniform. What is being deprioritized?

### Secondary Questions

5. What is the total headcount trajectory over 24 months?
6. What do the job descriptions actually require — not the title, the specifics?
7. What is the attrition rate alongside the hiring push?
8. What compensation signals does the hiring reveal (equity bands, remote policy)?
9. What competitors are they pulling from most aggressively?
10. What functions have they given up trying to hire for internally?

### Evidence Needed

| Question | Evidence type |
|---|---|
| What's growing | LinkedIn headcount data, job posting volume by function |
| Hiring from where | LinkedIn profile analysis of recent hires |
| Cost structure | Compensation databases, location distribution, benefits signals |
| What's deprioritized | Job posting absences, recent attrition patterns |

### Possible Sources

- LinkedIn (headcount trends, recent hire profiles)
- Job board analysis (Indeed, Greenhouse, Lever, company careers page)
- Levels.fyi (compensation benchmarks)
- Glassdoor (interview process signals, offer details)
- Twitter / X (founder hiring announcements, sourcing threads)

---

## Leadership Change

> The official reason for a leadership change is almost never the real reason.
> The board letter and the press release exist to protect the transition,
> not to explain it.

### Primary Questions

1. **Was this planned or forced?**
   Timing, vesting schedules, and external circumstances usually reveal which.

2. **What was the board's stated reason vs. what the record suggests?**
   What were the last 12 months of public statements from the departing leader?
   Do they align with the stated rationale?

3. **Who chose the successor, and what does that choice signal?**
   An insider succession signals continuity. An outside hire signals rupture.
   A search firm signals the board is not sure what it wants.

4. **What does the company look like at the moment of transition?**
   Growth, decline, fundraising pressure, regulatory scrutiny — the context
   defines what the new leader is actually walking into.

### Secondary Questions

5. What did the departing leader say in their last public appearances?
6. What is the successor's track record in comparable situations?
7. What did employees say about the departing leader before the announcement?
8. What happened to companies with comparable leadership transitions?
9. What investor or board dynamics preceded the change?
10. What is the new leader's first stated priority, and what does that reveal?

### Evidence Needed

| Question | Evidence type |
|---|---|
| Planned vs. forced | Timing vs. vesting cliff, SEC filing language, context |
| Board rationale | Official announcement + departing leader's recent public record |
| Successor signal | New leader's background, who recruited them, press framing |
| Company condition | Financial metrics, product state, competitive position at transition |

### Possible Sources

- SEC filing (Form 8-K for material executive changes)
- Official announcement (both the statement and what it omits)
- Departing leader's recent interviews, tweets, conference talks
- Incoming leader's prior company outcomes
- Board member backgrounds and investor relationships
- Glassdoor / employee community sentiment about the departing leader

---

## Product Launch / Kill

> Every product death is a resource allocation decision.
> Every product launch is a claim about what the market will bear.
> Neither is ever as simple as the announcement suggests.

### Primary Questions

1. **What specific problem did this product solve, or fail to solve?**
   The product's definition of the problem it addresses is more revealing than
   any feature list.

2. **Why now — what changed that made this the right moment to launch or kill?**
   Market timing for a launch and the decision to stop investing are both active choices.

3. **Who used it (or was supposed to use it), and what did they say?**
   For launches: what evidence of demand existed before launch?
   For kills: what did users who relied on it say?

4. **What does this decision reveal about the company's actual resource allocation?**
   What was built instead of this? What will be built now that this is gone?

### Secondary Questions

5. How long was this in development, and what was the investment?
6. What competing products already exist, and how do they differ?
7. What did the team behind this product do next?
8. What customer contracts or commitments are affected?
9. What did the market analyst community say before and after?
10. What failed in beta or testing that wasn't publicly disclosed?

### Evidence Needed

| Question | Evidence type |
|---|---|
| Problem definition | Product documentation, launch post, CEO framing |
| Timing reason | Market context, competitive event, internal roadmap signals |
| User response | App reviews, community posts, customer statements |
| Resource signal | Hiring/firing in product team, related roadmap changes |

### Possible Sources

- Company blog / product announcement
- App store reviews (for consumer products)
- Product Hunt launch reception
- Customer community (Slack groups, Reddit, Discord)
- Job postings (what the team is hiring for next reveals priority)
- Wayback Machine (product page history)

---

## Market Exit / Retreat

> A market exit is a hypothesis being abandoned.
> The most important question is not where the company is going.
> It is what they learned that they will not say out loud.

### Primary Questions

1. **What specifically did the company stop doing, and in which geography or segment?**
   "Restructuring" and "exit" mean different things. Precision matters.

2. **What was the gap between the original thesis and reality?**
   Every market entry had a bet. What did reality disprove?

3. **What happens to the customers, employees, and partners left behind?**
   The exit terms and the transition plan reveal how confident the company is
   that they are not coming back.

4. **Who won the market they left, and what did that competitor do differently?**
   Market exits create competitive visibility. Who filled the gap?

### Secondary Questions

5. How long did they try before exiting?
6. What was the total investment — capital, headcount, time?
7. What did they say when they entered vs. what they say now?
8. What did customers say when the exit was announced?
9. What regulatory or operational obstacle proved insurmountable?
10. What does this reveal about the original market sizing assumptions?

### Evidence Needed

| Question | Evidence type |
|---|---|
| What stopped | Official announcement, service termination notices |
| Thesis vs. reality | Original entry announcement + metrics at exit |
| Customer / partner impact | Customer statements, partner communications |
| Who filled the gap | Competitor announcements, customer migration patterns |

### Possible Sources

- Company announcement (what's said and what's omitted)
- Original market entry announcement (for comparison)
- Customer community reaction
- Competitor announcements about market position
- Trade press covering the specific geography or vertical
- Employee LinkedIn activity around the exit period

---

## Fallback template — Unknown signal type

When a signal does not match any of the above types, apply the following
universal investigation framework before attempting content generation.

### Universal Primary Questions

1. **What specifically happened — as a factual statement, not an interpretation?**
2. **Who made this decision, and what was their stated reason?**
3. **What changed that made this possible or necessary now?**
4. **Who is materially affected, and what do they say?**

### Universal Secondary Questions

5. What was the situation 12 months ago?
6. What did similar organizations do in comparable situations?
7. What alternatives existed?
8. What does this reveal about a broader trend or constraint?

### Universal Evidence Needed

Documented statements from decision-makers + one independent corroborating source.

If neither exists, return `INSUFFICIENT`.

---

## What this library does not contain

- Prompts. Questions are not prompts. Prompts instruct a model how to behave.
  Questions define what must be understood. These are separate concerns.
- Source API specifications. Where evidence is sought is the Evidence Collector's
  responsibility, not the Curiosity Engine's.
- Scoring weights. Completeness thresholds are defined in the Curiosity Engine spec
  (`BUSINESS_INVESTIGATION_LAYER.md`).
- Editorial guidance. Tone, voice, structure, and platform adaptation belong to
  the Editorial Engine.

---

## How this library evolves

This is a living document. New signal types are added when:

1. A recurring signal type appears in the pipeline that does not fit existing categories
2. An existing category produces consistently shallow articles (signal that questions are wrong)
3. A new class of business event emerges that requires different investigation instincts

Questions within each type are refined when:

- A published article is later found to have missed a material fact that a better
  question would have surfaced
- A new investigation produces an insight that reveals a question worth asking systematically

The library is Never Blank's institutional memory of how to be curious.

---

_This document contains no code and no prompts.
It is a question library — the intellectual foundation of the Curiosity Engine._
