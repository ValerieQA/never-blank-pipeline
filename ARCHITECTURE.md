# Never Blank Pipeline — Architecture

> **Never Blank is not a content machine. Never Blank demonstrates intelligence through content.**
>
> Every piece of content is a proof of concept. The product produces content. The content demonstrates the product. The demonstration sells the product.

---

## Core Loop

```
┌─────────────────────────────────────────────────────────────┐
│                     NEVER BLANK CORE LOOP                   │
│                                                             │
│   Product  ──►  Content  ──►  Demonstration  ──►  Sale      │
│      ▲                                            │         │
│      └────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

Content is not marketing. Content is evidence.
The system exists to produce evidence — consistently, at quality, without drift.

---

## System Overview

The pipeline has two distinct layers:

```
┌──────────────────────────────────────────────────────────────────┐
│                    INTERNAL NEVER BLANK                          │
│                                                                  │
│   Intelligence Engine                                            │
│          │                                                       │
│          ▼                                                       │
│   Observation Layer        ◄──── Memory (past observations)     │
│   (discover before creating)                                     │
│          │                                                       │
│          ▼                                                       │
│   Topic Generator → Topic Scoring                                │
│                          │                                       │
│                    Strategy Layer                                │
│                          │                                       │
│          Memory ◄────────►│◄──── Reports                        │
│                          │                                       │
│                  Content Generator                               │
│                  Quality Control                                 │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    EXTERNAL NEVER BLANK                          │
│                                                                  │
│   Wix Blog  │  LinkedIn  │  Facebook  │  Instagram  │  Threads  │
│                                                                  │
│                         Telegram                                 │
│                                                                  │
│                      Visual Assets Layer                         │
└──────────────────────────────────────────────────────────────────┘
```

---

## Topic Pipeline

Content does not come from news. Content comes from interesting ideas.
An idea can emerge from a market shift, a research finding, a business paradox, a behavioral pattern, or the system's own analysis. News is one source among many.

```
┌──────────────────────────────────────────────────────────────────┐
│                      TOPIC PIPELINE                              │
│                                                                  │
│  1. Manual Queue (Google Sheet / CSV)                            │
│     │                                                            │
│     ├── topics exist? → YES → take from queue → Strategy Layer  │
│     │                                                            │
│     └── queue empty? → Intelligence Engine                       │
│                             │                                    │
│                     [collect from all sources]                   │
│                             │                                    │
│                       Topic Generator                            │
│                    (extract idea from source)                    │
│                             │                                    │
│                        Topic Scoring                             │
│                  (relevance + originality +                      │
│                   platform fit + recency check)                  │
│                             │                                    │
│                      Publication Queue                           │
│                    (ordered list of candidates)                  │
│                             │                                    │
│                       Strategy Layer                             │
└──────────────────────────────────────────────────────────────────┘
```

Manual topics live in `topics_manual.csv` and are synced from Google Sheets.
Each manual topic row includes: title, angle, platform targets, priority order, notes.

---

## Internal Never Blank — Detailed Design

### 1. Intelligence Engine

Never Blank does not rely on news. It draws from multiple source categories,
each with its own collection method and priority weight.

**Source categories (defined in `config/intelligence.yaml`):**

| # | Category                  | Examples                                                                 | Priority |
|---|---------------------------|--------------------------------------------------------------------------|----------|
| 1 | Market Signals            | industry changes, regulations, platform updates, AI developments         | High     |
| 2 | Business Observations     | recurring patterns, customer behavior, founder behavior, operational gaps | High     |
| 3 | Research Insights         | public studies, surveys, market reports, industry statistics             | Medium   |
| 4 | Business Facts            | surprising statistics, historical decisions, unusual cases               | Medium   |
| 5 | Never Blank Analysis      | patterns discovered by the system, comparisons, signal synthesis         | High     |
| 6 | Manual Topics             | Google Sheet queue, founder-provided topics                              | Highest  |

Categories 1–4 are collected from external sources (RSS, APIs, configured URLs).
Category 5 is generated internally — the system synthesizes patterns from what it has already collected and published.
Category 6 always takes priority over all others.

**Collection behavior:**
- Sources are defined in `config/intelligence.yaml` — no source URLs inside Python
- Each source entry has: `type`, `url`, `category`, `fetch_interval`, `relevance_filter`
- Raw items are saved to `data/intelligence/YYYY-MM-DD/raw/`

**Output:** structured intelligence items in `data/intelligence/YYYY-MM-DD/raw/*.json`

### 2. Observation Layer

> **Never Blank discovers observations before it creates content.**
> **The goal is not to publish information. The goal is to publish insights.**

The Observation Layer is where raw intelligence becomes something worth saying.

It does not ask: *what happened?*
It asks: *what is true here that most people have not named yet?*

An observation is not a topic. It is not a headline. It is a noticed pattern — something that
makes a reader stop and think: "Hm. That's actually true."

The layer looks across collected intelligence items and searches for:

| Observation Type    | Description                                                                 | Example                                                             |
|---------------------|-----------------------------------------------------------------------------|---------------------------------------------------------------------|
| **Pattern**         | Something that repeats across unrelated contexts                            | Founders who post least often tend to have the strongest positioning |
| **Paradox**         | Two things that are both true but seem to contradict each other             | The busiest businesses look like they're closed                      |
| **Reversal**        | Conventional wisdom that operates backwards in practice                     | Being less visible sometimes increases credibility                   |
| **Gap**             | Something important that the industry is not talking about                  | Everyone discusses content strategy; nobody discusses content silence |
| **Behavior delta**  | The difference between what people say and what they actually do            | Founders say they want clarity; they keep adding complexity          |
| **Signal cluster**  | Multiple unrelated signals that point to the same underlying shift           | Three separate trends all indicating the same change in buyer trust  |
| **Implication**     | A known fact whose consequence has not been widely acknowledged             | If attention is scarce, silence is a positioning decision            |

**The Observation Layer is not a summarizer.** It does not compress information.
It elevates the one thing that is genuinely worth saying.

**Process:**

```
Raw intelligence items
        ↓
Observation Discovery prompt
(config/prompts/observation_discovery.yaml)
        ↓
Candidate observations scored by:
  - non-obviousness (is this already widely said?)
  - specificity (is this concrete enough to be useful?)
  - relevance to Never Blank's audience
  - novelty vs. memory (not already published)
        ↓
Validated observations saved to data/observations/YYYY-MM-DD.json
        ↓
Passed to Topic Generator
```

**Observations are reusable.** A strong observation may generate multiple content pieces
over time — different angles, different platforms, different contexts. Observations are stored
in memory and can be referenced again when they become relevant.

**Output:** `data/observations/YYYY-MM-DD.json`
Each observation: `{statement, type, source_refs[], score, evergreen, used_in[]}`

### 3. Topic Generator

Converts validated observations into publishable topic briefs.

The observation is the asset. The topic is how it gets packaged for a specific audience moment.

- One observation → may generate multiple topic angles
- Topic Generator selects the angle that best fits the current moment and platform context
- Output is a `TopicCandidate`: `{observation_id, angle, platform_fit, content_goal, evergreen}`

The Topic Generator does not invent new ideas. It serves the observations the Observation Layer discovered.

**Output:** `data/intelligence/YYYY-MM-DD/candidates_raw.json`

### 3. Topic Scoring

Ranks all topic candidates into a publication queue.

**Base scoring factors** (weights defined in `config/intelligence.yaml`):
- **Relevance** — how closely this topic connects to Never Blank's positioning
- **Originality** — semantic distance from published content (embedding comparison, not string match)
- **Platform fit** — does this work as a long article, a short post, or both
- **Recency signal** — time-sensitive topics score higher when fresh
- **Source category weight** — per the priority table above

**Diversity adjustment** (reads from `memory/portfolio.json`):

The scoring system applies bonuses and penalties to enforce long-term content diversity.
These adjustments prevent the system from drifting toward one type of content.

| Condition                                                          | Adjustment              |
|--------------------------------------------------------------------|-------------------------|
| Observation type matches the last 3 published types               | −20% score penalty      |
| Observation type not used in the last 30 days                     | +15% score bonus        |
| Source category not used in the last 14 days                      | +10% score bonus        |
| Content goal same as last 3 published goals                       | −15% score penalty      |
| Content goal not used in last 20 published pieces                 | +20% score bonus        |

Thresholds and weights are configured in `config/intelligence.yaml` under `diversity_weights`.
The diversity adjustment is additive to the base score — it does not override it.

Topics that score below the minimum threshold after adjustment are dropped.
The top N candidates are written to the publication queue.

**Output:** `data/intelligence/YYYY-MM-DD/publication_queue.json` (ordered list with scores and diversity_adjustment breakdown)

### 4. Strategy Layer

Applies Never Blank editorial logic to each topic candidate:
- Selects the right angle (not just what happened — what it means)
- Maps topic to platform format (long blog vs. short social)
- Sets tone guidance based on brand voice config
- Defines the content goal: educate / challenge / demonstrate / invite
- **Assigns Wix tags automatically** based on content goal and observation type
- **Generates the URL slug** from the article title (no manual entry)

All strategy rules live in `config/strategy.yaml` — no logic inside Python.

Tag assignment is defined in `config/strategy.yaml` as a mapping:

```yaml
tag_assignment:
  observation_type:
    pattern:     ["observations", "business"]
    paradox:     ["observations", "strategy"]
    reversal:    ["visibility", "strategy"]
    gap:         ["visibility", "content"]
    behavior_delta: ["founder", "business"]
    signal_cluster: ["business", "strategy"]
    implication: ["observations", "founder"]
  content_goal:
    educate:     ["content"]
    challenge:   ["observations"]
    demonstrate: ["visibility"]
    invite:      ["founder"]
```

Each article receives 2–3 tags automatically. No human tag selection. No manual slug entry.

**Output:** approved `ContentBrief` object passed to Content Generator.
`ContentBrief` includes: `title`, `angle`, `goal`, `platforms`, `tone_notes`, `source_signals`,
`wix_tags: list[str]`, `wix_slug: str`, `wix_category_id: str`

### 5. Memory

Memory is not an archive. It is an active constraint on future decisions.
Every layer of the pipeline reads from memory before making choices.

**What memory stores:**

`data/memory/published.json`
- Full log of every published piece with per-channel results
- Used by: deduplication, portfolio tracking, observation staleness checks

`data/memory/observations.json`
- All discovered observations with: statement, type, score, source_refs, `used_in[]`, `use_count`, `last_used_date`
- An observation is never permanently retired — but it enters a cooldown after `max_uses` (configured in `quality.yaml`)
- Used by: Observation Layer (checks before adding a new candidate), Topic Generator

`data/memory/embeddings.json`
- Semantic vector index of every published topic summary and observation statement
- **String similarity is not sufficient.** Embeddings are required from day one.
- Used by: deduplication check in QC; observation novelty check in Observation Layer
- Two pieces are considered duplicates if cosine similarity > threshold (configured in `quality.yaml`)

`data/memory/voice_examples.json`
- Curated brand voice reference posts
- **This file must be updated periodically** as the brand matures — not set once and frozen
- A voice drift alert is triggered if the rolling voice score drops below threshold over 10 consecutive posts (see Brand Voice Drift Detection)
- Used by: QC voice check; rewrite prompts

`data/memory/portfolio.json`
- Running distribution of content across all dimensions
- Updated after every successful publish
- Structure:
  ```json
  {
    "observation_type_counts": {"paradox": 12, "reversal": 4, "gap": 2, ...},
    "content_goal_counts": {"educate": 10, "challenge": 6, "demonstrate": 8, "invite": 4},
    "source_category_counts": {"market_signals": 15, "business_observations": 8, ...},
    "tag_counts": {"business": 14, "visibility": 9, "observations": 11, ...},
    "voice_scores_rolling": [0.87, 0.85, 0.82, ...],
    "last_used_observation_types": ["paradox", "paradox", "reversal", "paradox", ...]
  }
  ```
- Used by: Topic Scoring (diversity adjustment), Portfolio Health Report

### 6. Reports

After each pipeline run, a report is written to:
- `data/reports/YYYY-MM-DD.json` (machine-readable)
- Google Sheet dashboard (human-readable)

Report covers:
- Run timestamp and trigger type (manual / automated)
- Topic selected and why
- Quality checks performed and results
- Publication outcomes per platform
- Any failures or retries

---

## External Never Blank — Detailed Design

### Platform Map

| Platform     | Format                         | Primary Purpose                       |
|--------------|--------------------------------|---------------------------------------|
| Wix Blog     | Long-form article              | SEO, depth, demonstration             |
| LinkedIn     | Professional post              | Thought leadership, reach             |
| Facebook     | Post + image                   | Community, warmth                     |
| Instagram    | Image + caption                | Visual identity, hook                 |
| Threads      | Short text                     | Conversation starter                  |
| Telegram     | Short insight + optional link  | Fast broadcast, sharp observations    |

Each platform has its own prompt template in `config/prompts/`.
Content is adapted — not copied — across platforms.

### Wix Publishing — Automatic Metadata

Every Wix post is published with full metadata set automatically. No manual steps.

| Field         | Source                                              |
|---------------|-----------------------------------------------------|
| Category      | Always `Never Blank` — hardcoded category ID in config |
| Tags          | Assigned by Strategy Layer from `strategy.yaml` mapping |
| Slug          | Auto-generated from article title (slugified, deduplicated vs memory) |
| Language      | `en` (set in config)                               |

The Wix category ID (`35920a76-8a41-4645-aeb1-322ae240a57a`) is stored in `config/platforms.yaml`.
Available tag IDs are stored in `config/platforms.yaml` as a label→ID map and kept in sync on startup.

### Telegram Role

Telegram is not an article platform. It is a fast broadcast channel.

A Telegram post contains:
- One sharp hook (the observation stated plainly)
- One business insight (why it matters)
- Link to the full Wix article when one exists for this topic
- Optional visual card if a branded image was generated

Telegram publishes the same day as the full article, not as a teaser before it.
The goal is to deliver value instantly to subscribers, with a path to depth for those who want it.

Telegram content is generated from `config/prompts/telegram_post.yaml`.
It is short by design — not a compressed version of the article, but a self-contained insight.

### Visual Assets Layer

Images are generated automatically per post using the following rules:

**Brand requirements (defined in `config/brand.yaml`):**
- Never Blank logo included
- Approved color palette only (hex values in config)
- Approved font families only
- Strong hook text on the image (pulled from content)
- Consistent layout templates per platform size

**Image generation pipeline:**
1. Content Generator extracts hook sentence
2. Image Builder selects template from `assets/templates/`
3. Renders image with hook text + logo + palette
4. Saves to `data/visuals/YYYY-MM-DD-{slug}/`
5. Uploads to Cloudinary (URL stored in report)

---

## Autonomy Principle

> **Human Review is optional. Human Dependency is forbidden.**

The system must be able to continue working when the human is unavailable.
A pipeline that stops and waits for approval on every uncertain post breaks its own promise.

Never Blank exists to produce evidence of intelligence without requiring constant supervision.
If the system needs Valeria to check every article before it publishes, the system has failed.

The human can review. The human cannot be a required step.

---

## Quality Control Layer

Every piece of content passes through QC before publishing.
QC failures do not stop the pipeline — they trigger the appropriate autonomous response.

### Failure Types and System Responses

Failures are not equal. The system's response depends on what broke.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     QC FAILURE HANDLING                             │
│                                                                     │
│  TYPE 1 — Technical Failure                                         │
│  API down, image failed to render, network timeout                  │
│  Response: retry (up to N times from config)                        │
│            → if still failing: RED status, alert                    │
│                                                                     │
│  TYPE 2 — Quality Failure                                           │
│  Duplicate topic, voice drift, inconsistency across platforms       │
│  Response: rewrite (up to N times from config)                      │
│            → if still failing: ORANGE status, skip topic, continue  │
│                                                                     │
│  TYPE 3 — Factual Risk                                              │
│  Claim cannot be verified against source signals                    │
│  Invented statistic, person, date, or event                         │
│  Response: quarantine topic, log reason, continue to next topic     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Status System

Status is tracked at two levels: per-platform and per-run.

**Per-platform status** — every channel is tracked independently.
A failed Telegram post does not block LinkedIn. A failed Instagram does not block Wix.

| Status      | Meaning                                                         | Human action required? |
|-------------|-----------------------------------------------------------------|------------------------|
| **GREEN**   | Published successfully                                          | No                     |
| **YELLOW**  | Quality issue detected — system rewrote and resolved            | No                     |
| **ORANGE**  | Topic quarantined — skipped, pipeline continued                 | No (optional review)   |
| **SKIPPED** | Platform intentionally excluded for this topic (with reason)    | No                     |
| **FAILED**  | Platform publish failed after all retries                       | No (logged, continued) |
| **RED**     | System-level failure — pipeline cannot continue at all          | Yes                    |

**Per-run overall status** — the final status of a complete pipeline run:

- **GREEN** — all required channels are either `GREEN`, `YELLOW`, or `SKIPPED` with reason
- **PARTIAL** — at least one required channel is `FAILED`, others succeeded
- **ORANGE** — topic was quarantined; pipeline moved to next topic
- **RED** — system-level failure; pipeline stopped

A run is not GREEN unless every required channel is either published or intentionally skipped with a recorded reason.
`FAILED` on a single channel does not stop other channels — it logs and continues.
`FAILED` on all channels escalates to RED.

Human intervention is required **only for RED**.

### QC Checks (in order)

| Check                        | Failure Type | System Response            |
|------------------------------|--------------|----------------------------|
| Semantic Duplication         | Type 2       | Rewrite with new angle     |
| Brand Voice Validation       | Type 2       | Rewrite with voice anchoring |
| Consistency Check            | Type 2       | Regenerate platform variants |
| Factuality Check             | Type 3       | Quarantine topic            |
| Hallucination Detection      | Type 3       | Quarantine topic            |
| Per-platform API health      | Type 1       | Retry with backoff per channel; failure logged, pipeline continues to next channel |
| Image rendering              | Type 1       | Retry, then publish without image |

QC config (thresholds, max retries, max rewrites, strictness) lives in `config/quality.yaml`.

### Brand Voice Drift Detection

Single-post QC validates each article in isolation. But brand voice can drift slowly across
200 posts without any single post failing its voice check. Drift is invisible at the post level.

The system runs a **rolling voice drift check** after every publish:
- Reads the last N voice scores from `memory/portfolio.json` (`voice_scores_rolling`)
- If the 10-post rolling average drops below `voice_drift_threshold` in `quality.yaml` → **ORANGE alert**
- The alert is logged to the Pipeline Log and the Failures tab in Google Sheet
- The pipeline does not stop — but the alert is visible and prompts optional review
- Recommended response: update `voice_examples.json` with recent approved posts

This is not a per-post failure. It is a **longitudinal signal** that the brand voice is shifting.

```
After each successful publish:
  → record voice score in portfolio.json
  → compute rolling average of last 10 scores
  → if average < threshold: log ORANGE drift alert to Google Sheet
  → continue pipeline
```

### Rewrite Loop

```
Generate
  ↓
QC check
  ↓ fail (Type 2)
Rewrite with failure reason injected into prompt
  ↓
QC check
  ↓ fail again
Rewrite attempt 2
  ↓
QC check
  ↓ still failing after N attempts
ORANGE → quarantine → log → next topic
```

The failure reason from QC is passed back into the generation prompt on rewrite.
The system does not rewrite blindly — it rewrites with context.

---

## Reporting Layer — Google Sheet Dashboard

The Google Sheet serves as the human control panel.

### Tabs

**1. Topic Queue**
- Manual topics awaiting publication (source of truth for manual queue)
- Columns: `title`, `angle`, `target_platforms`, `priority`, `notes`, `status`

**2. Published**
- Every published piece — one row per run (not per platform)
- Columns: `date`, `topic`, `overall_status`, `wix_url`, `wix_status`, `linkedin_status`, `facebook_status`, `instagram_status`, `threads_status`, `telegram_status`, `telegram_url`
- Status per channel: `green` / `yellow` / `skipped` / `failed`
- Allows instant visibility into which channels succeeded and which did not

**3. Pipeline Log**
- Every run logged automatically
- Columns: `run_date`, `trigger`, `topic_selected`, `qc_result`, `overall_status`, `failed_channels`, `errors`

**4. Failures & Retries**
- Per-channel failures with error reason
- Columns: `date`, `topic`, `channel`, `stage`, `error`, `retry_count`, `resolved`
- A Telegram failure appears here but does not mark the full run as RED

**5. Upcoming Topics**
- Auto-populated from topic candidates that passed prioritization
- For visibility — not for editing

**6. Portfolio Health** *(updated monthly, auto-generated)*
- Distribution of observation types published (count per type, last 30 / 90 / all-time)
- Distribution of content goals (educate / challenge / demonstrate / invite)
- Distribution of source categories used
- Distribution of Wix tags
- Rolling brand voice score (10-post average, trend)
- Observations used 3+ times (flagged for cooldown review)
- Intelligence sources not used in 30+ days (flagged as potentially stale)
- Columns: `metric`, `last_30_days`, `last_90_days`, `all_time`, `flag`

This tab is the 12-month health check. It answers: is the content portfolio balanced, or has the system drifted into a single mode?

---

## Configuration Architecture

**All prompts live in config files. No prompt text inside Python code.**

```
config/
├── brand.yaml            # logo path, color palette, fonts, tone descriptors
├── strategy.yaml         # editorial rules, content goals, angle patterns
├── quality.yaml          # QC thresholds, enabled checks, failure behavior
├── platforms.yaml        # per-platform specs (character limits, image sizes)
├── intelligence.yaml     # source categories, URLs, fetch intervals, scoring weights
# platforms.yaml includes:
#   wix.category_id, wix.tags (label→id map), wix.language
#   per-platform character limits, image dimensions
└── prompts/
    ├── blog_post.yaml             # full Wix article prompt template
    ├── linkedin_post.yaml         # LinkedIn post prompt
    ├── facebook_post.yaml         # Facebook post prompt
    ├── instagram_caption.yaml
    ├── threads_post.yaml
    ├── telegram_post.yaml         # short insight + optional article link
    ├── observation_discovery.yaml  # prompt for discovering observations from intelligence
    ├── observation_score.yaml     # prompt for scoring observation non-obviousness
    ├── topic_extract.yaml         # prompt for converting observation into topic angle
    ├── topic_score.yaml           # prompt for scoring and ranking topic candidates
    ├── strategy_brief.yaml        # prompt for strategy layer
    ├── qc_factuality.yaml         # prompt for factuality check
    ├── qc_voice.yaml              # prompt for brand voice validation
    ├── rewrite_with_feedback.yaml # rewrite prompt that includes QC failure reason
    └── image_hook.yaml            # prompt for extracting hook sentence for image
```

Prompt templates use `{variable}` placeholders filled at runtime.
No string concatenation of prompts in Python — always load from file.

---

## Repository Structure

```
Never-Blank-pipeline/
│
├── ARCHITECTURE.md
├── IMPLEMENTATION_PLAN.md
├── README.md
├── .env.example             # template — never commit .env
├── .gitignore
├── requirements.txt
│
├── config/
│   ├── brand.yaml
│   ├── strategy.yaml
│   ├── quality.yaml
│   ├── platforms.yaml
│   ├── signals.yaml
│   └── prompts/
│       ├── blog_post.yaml
│       ├── linkedin_post.yaml
│       ├── facebook_post.yaml
│       ├── instagram_caption.yaml
│       ├── threads_post.yaml
│       ├── topic_analysis.yaml
│       ├── strategy_brief.yaml
│       ├── qc_factuality.yaml
│       ├── qc_voice.yaml
│       └── image_hook.yaml
│
├── src/
│   ├── __init__.py
│   │
│   ├── internal/
│   │   ├── __init__.py
│   │   ├── intelligence_engine.py  # collects raw items from all source categories
│   │   ├── observation_layer.py    # discovers observations from raw intelligence
│   │   ├── topic_generator.py      # converts observations into topic angles
│   │   ├── topic_scorer.py         # scores and ranks candidates into publication queue
│   │   ├── strategy.py             # applies editorial logic, builds ContentBrief
│   │   └── memory.py               # reads/writes memory store
│   │
│   ├── content/
│   │   ├── __init__.py
│   │   ├── generator.py           # calls Claude API with loaded prompt + brief
│   │   ├── adapters.py            # adapts long-form to per-platform variants
│   │   └── image_builder.py       # renders visual assets
│   │
│   ├── quality/
│   │   ├── __init__.py
│   │   ├── gate.py                # runs all QC checks in sequence
│   │   ├── deduplication.py       # semantic similarity check
│   │   ├── factuality.py          # Claude-based factuality check
│   │   └── voice.py               # brand voice validation
│   │
│   ├── publishing/
│   │   ├── __init__.py
│   │   ├── wix.py                 # Wix blog publisher
│   │   ├── linkedin.py            # LinkedIn publisher
│   │   ├── facebook.py            # Facebook Graph API publisher
│   │   ├── instagram.py           # Instagram publisher
│   │   ├── threads.py             # Threads publisher
│   │   ├── telegram.py            # Telegram Bot API publisher
│   │   └── cloudinary_upload.py   # image hosting
│   │
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── reporter.py            # assembles run report
│   │   ├── portfolio_reporter.py  # computes portfolio health metrics from memory
│   │   └── sheets.py              # writes to Google Sheet dashboard
│   │
│   └── utils/
│       ├── __init__.py
│       ├── config_loader.py       # loads YAML configs and prompt templates
│       ├── google_sheets.py       # Google Sheets read/write client
│       └── logger.py              # structured logging
│
├── data/
│   ├── intelligence/
│   │   └── YYYY-MM-DD/
│   │       ├── raw/                   # raw items per source category
│   │       ├── candidates_raw.json    # topic angles before scoring
│   │       └── publication_queue.json # scored, ranked, ready for strategy
│   ├── observations/
│   │   └── YYYY-MM-DD.json            # validated observations (reusable across content pieces)

│   ├── drafts/
│   │   ├── pending/               # content awaiting publish
│   │   └── quarantine/            # factual risk — awaiting optional human review
│   ├── memory/
│   │   ├── published.json          # full publish log with per-channel results
│   │   ├── observations.json       # all observations with use_count, last_used_date, cooldown flag
│   │   ├── embeddings.json         # semantic vectors for all published topics and observations
│   │   ├── portfolio.json          # running distribution across all content dimensions
│   │   └── voice_examples.json     # brand voice reference set (updated periodically)
│   ├── visuals/                   # generated images by date-slug
│   └── reports/                   # run reports by date
│
├── assets/
│   ├── templates/                 # image layout templates (per platform)
│   ├── logo/                      # Never Blank logo files
│   └── fonts/                     # approved fonts
│
├── topics_manual.csv              # manual topic queue (synced from Google Sheets)
│
├── scripts/
│   ├── run_pipeline.py            # main entry point: full pipeline run
│   ├── run_intelligence.py        # run only the intelligence engine (collect + score)
│   ├── run_publish_only.py        # publish a quarantined draft after manual decision
│   ├── sync_sheets.py             # pull manual topics from Google Sheets
│   ├── sync_wix_tags.py           # sync tag label→ID map from Wix into platforms.yaml
│   └── generate_health_report.py  # compute and write Portfolio Health tab to Google Sheet
│
└── tests/
    ├── test_quality/
    ├── test_publishing/
    └── test_content/
```

---

## Secrets and Credentials

All secrets live in `.env` — never committed to the repository.

`.env.example` documents every required variable with a description.

Required secrets:
```
ANTHROPIC_API_KEY=
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
WIX_API_KEY=
WIX_SITE_ID=
LINKEDIN_ACCESS_TOKEN=
META_USER_TOKEN=
META_IG_USER_ID=
META_FB_PAGE_ID=
META_FB_PAGE_TOKEN=
THREADS_ACCESS_TOKEN=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=
GOOGLE_SHEETS_CREDENTIALS_JSON=
GOOGLE_SHEET_ID=
```

---

## Design Principles

1. **Human Review is optional. Human Dependency is forbidden.** The system continues working when the human is unavailable. Valeria can review; the pipeline cannot wait for her.
2. **Failures have types, and types have responses.** Technical failures retry. Quality failures rewrite. Factual risks quarantine. Only system crashes require human action.
3. **Prompts live in config, not code.** Python loads templates; it never builds prompt strings.
4. **The system discovers before it creates.** Raw intelligence is collected first. Then the Observation Layer finds what is actually worth saying. Only then does content generation begin.
5. **The goal is insights, not information.** An observation is not a summary of what happened. It is a named pattern that most people have not articulated yet.
6. **Content comes from ideas, not news.** News is one input among six. The most powerful content often comes from observations, paradoxes, and patterns — not headlines.
7. **Manual queue takes priority.** Automation serves when humans have nothing queued.
8. **Observations are reusable assets — but not indefinitely.** A single observation may fuel multiple content pieces. Observations enter cooldown after `max_uses` to prevent the same insight from becoming a crutch.
9. **Memory prevents repetition semantically, not lexically.** Deduplication uses embeddings. String matching is not sufficient — two different phrasings of the same idea must be detected as duplicates.
10. **Diversity is enforced, not assumed.** Topic Scoring applies explicit bonuses and penalties based on portfolio distribution. The system does not drift into a single observation type by accident.
11. **Brand voice drift is a longitudinal risk.** Single-post QC catches today's failure. Rolling voice score tracking catches the slow drift that kills a brand over 6 months.
12. **The system reports itself — including its own health.** Every run is visible in Google Sheets. Portfolio health is visible monthly. The system can report when it is becoming repetitive before a human notices.
13. **Brand voice examples are living references, not frozen artifacts.** `voice_examples.json` must be updated as the brand matures. A voice example from month 1 may no longer represent month 9.
14. **Images are part of the content, not decoration.** Generated automatically, with hook and branding.
15. **One source of truth per concern.** Config owns rules. Memory owns history. Sheets owns visibility.
