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
│   Intelligence Engine → Topic Generator → Topic Scoring          │
│                                │                                 │
│                          Strategy Layer                          │
│                                │                                 │
│              Memory ◄─────────►│◄──── Reports                   │
│                                │                                 │
│                       Content Generator                          │
│                       Quality Control                            │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                    EXTERNAL NEVER BLANK                          │
│                                                                  │
│   Wix Blog  │  LinkedIn  │  Facebook  │  Instagram  │  Threads  │
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

### 2. Topic Generator

Extracts publishable topic ideas from raw intelligence items.

This step answers: *what is the interesting thought here?*
Not: *what happened?* — but: *what does this reveal?*

- Each raw item is passed through a topic extraction prompt (`config/prompts/topic_extract.yaml`)
- The prompt looks for the observation, the pattern, the paradox, or the implication
- Output is a `TopicCandidate` object: `{idea, angle, source_category, source_ref, evergreen}`

Examples of what the Topic Generator should surface:
- From a statistic → the counterintuitive implication
- From a case study → the transferable lesson
- From a market shift → what it means for founders specifically
- From Never Blank's own history → a pattern worth naming

**Output:** `data/intelligence/YYYY-MM-DD/candidates_raw.json`

### 3. Topic Scoring

Ranks all topic candidates into a publication queue.

Scoring factors (weights defined in `config/intelligence.yaml`):
- **Relevance** — how closely this topic connects to Never Blank's positioning
- **Originality** — how different this is from recently published content (checked against memory)
- **Platform fit** — does this work as a long article, a short post, or both
- **Recency signal** — time-sensitive topics score higher when fresh
- **Source category weight** — per the priority table above

Topics that score below the minimum threshold are dropped.
The top N candidates are written to the publication queue.

**Output:** `data/intelligence/YYYY-MM-DD/publication_queue.json` (ordered list)

### 4. Strategy Layer

Applies Never Blank editorial logic to each topic candidate:
- Selects the right angle (not just what happened — what it means)
- Maps topic to platform format (long blog vs. short social)
- Sets tone guidance based on brand voice config
- Defines the content goal: educate / challenge / demonstrate / invite

All strategy rules live in `config/strategy.yaml` — no logic inside Python.

**Output:** approved `ContentBrief` object passed to Content Generator

### 5. Memory

Persistent store of everything the system has done:
- Published topics and their slugs
- Topic embeddings for semantic deduplication
- Per-platform performance notes (added manually or via future integrations)
- Brand voice examples (approved reference posts)

Stored in `data/memory/`:
- `published.json` — log of every published piece
- `topic_embeddings.json` — vector index for deduplication
- `voice_examples.json` — curated brand voice reference set

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

| Platform     | Format                  | Primary Purpose              |
|--------------|-------------------------|------------------------------|
| Wix Blog     | Long-form article       | SEO, depth, demonstration    |
| LinkedIn     | Professional post       | Thought leadership, reach    |
| Facebook     | Post + image            | Community, warmth            |
| Instagram    | Image + caption         | Visual identity, hook        |
| Threads      | Short text              | Conversation starter         |

Each platform has its own prompt template in `config/prompts/`.
Content is adapted — not copied — across platforms.

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

Every pipeline run and every content piece carries one of four statuses:

| Status     | Meaning                                              | Human action required? |
|------------|------------------------------------------------------|------------------------|
| **GREEN**  | Published successfully                               | No                     |
| **YELLOW** | Quality issue detected — system rewrote and resolved | No                     |
| **ORANGE** | Topic quarantined — skipped, pipeline continued      | No (optional review)   |
| **RED**    | System failure — broken API key, pipeline crash      | Yes                    |

Human intervention is required **only for RED**.
ORANGE items are visible in the Google Sheet for optional review — but the pipeline did not wait.

### QC Checks (in order)

| Check                   | Failure Type | System Response            |
|-------------------------|--------------|----------------------------|
| Duplication Detection   | Type 2       | Rewrite with new angle     |
| Brand Voice Validation  | Type 2       | Rewrite with voice anchoring |
| Consistency Check       | Type 2       | Regenerate platform variants |
| Factuality Check        | Type 3       | Quarantine topic            |
| Hallucination Detection | Type 3       | Quarantine topic            |
| Platform API health     | Type 1       | Retry with backoff          |
| Image rendering         | Type 1       | Retry, then skip image      |

QC config (thresholds, max retries, max rewrites, strictness) lives in `config/quality.yaml`.

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
- Every published piece
- Columns: `date`, `topic`, `platform`, `url`, `status`

**3. Pipeline Log**
- Every run logged automatically
- Columns: `run_date`, `trigger`, `topic_selected`, `qc_result`, `publish_result`, `errors`

**4. Failures & Retries**
- Failed runs with error reason
- Columns: `date`, `topic`, `stage`, `error`, `retry_count`, `resolved`

**5. Upcoming Topics**
- Auto-populated from topic candidates that passed prioritization
- For visibility — not for editing

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
└── prompts/
    ├── blog_post.yaml             # full Wix article prompt template
    ├── linkedin_post.yaml         # LinkedIn post prompt
    ├── facebook_post.yaml         # Facebook post prompt
    ├── instagram_caption.yaml
    ├── threads_post.yaml
    ├── topic_extract.yaml         # prompt for extracting idea from raw intelligence item
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
│   │   ├── topic_generator.py      # extracts topic ideas from raw intelligence
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
│   │   └── cloudinary_upload.py   # image hosting
│   │
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── reporter.py            # assembles run report
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
│   │       ├── raw/               # raw items per source category
│   │       ├── candidates_raw.json    # topic ideas before scoring
│   │       └── publication_queue.json # scored, ranked, ready for strategy

│   ├── drafts/
│   │   ├── pending/               # content awaiting publish
│   │   └── quarantine/            # factual risk — awaiting optional human review
│   ├── memory/
│   │   ├── published.json
│   │   ├── topic_embeddings.json
│   │   └── voice_examples.json
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
│   └── sync_sheets.py             # pull manual topics from Google Sheets
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
GOOGLE_SHEETS_CREDENTIALS_JSON=
GOOGLE_SHEET_ID=
```

---

## Design Principles

1. **Human Review is optional. Human Dependency is forbidden.** The system continues working when the human is unavailable. Valeria can review; the pipeline cannot wait for her.
2. **Failures have types, and types have responses.** Technical failures retry. Quality failures rewrite. Factual risks quarantine. Only system crashes require human action.
3. **Prompts live in config, not code.** Python loads templates; it never builds prompt strings.
4. **Content comes from ideas, not news.** News is one input among six. The most powerful content often comes from observations, paradoxes, and patterns — not headlines.
5. **Manual queue takes priority.** Automation serves when humans have nothing queued.
6. **Memory prevents repetition.** Every published topic is remembered semantically, not just by title.
7. **The system reports itself.** Every run is visible in Google Sheets without opening the code.
8. **Brand voice is a constraint, not an afterthought.** Voice validation runs before every publish. On failure, the system rewrites — it does not stop.
9. **Images are part of the content, not decoration.** Generated automatically, with hook and branding.
10. **One source of truth per concern.** Config owns rules. Memory owns history. Sheets owns visibility.
