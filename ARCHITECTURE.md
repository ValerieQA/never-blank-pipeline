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
│   Signal Monitor → Market Analysis → Topic Prioritization        │
│                           │                                      │
│                     Strategy Layer                               │
│                           │                                      │
│              Memory ◄────►│◄──── Reports                        │
│                           │                                      │
│                    Content Generator                             │
│                    Quality Control                               │
└──────────────────────────────┬───────────────────────────────────┘
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

## Topic Priority System

**Manual topics always take priority over automated signals.**

```
┌─────────────────────────────────────┐
│         TOPIC QUEUE LOGIC           │
│                                     │
│  1. Read Google Sheet / CSV         │
│     ↓                               │
│  2. Manual topics exist?            │
│     YES → publish manual topic      │
│     NO  → run signal pipeline       │
│            ↓                        │
│         Market signals + news       │
│         → topic candidate           │
│         → strategy filter           │
│         → approved topic            │
└─────────────────────────────────────┘
```

Manual topics live in `topics_manual.csv` and are synced from Google Sheets.
Each manual topic row includes: title, angle, platform targets, priority order, notes.

---

## Internal Never Blank — Detailed Design

### 1. Signal Monitor

Watches external sources for relevant signals:
- Industry news (RSS feeds, defined in config)
- LinkedIn trending topics in the coaching / consulting space
- Google Trends (keyword clusters defined in config)
- Competitor content (defined list in config)

**Output:** raw signal objects saved to `data/signals/YYYY-MM-DD.json`

### 2. Market Analysis

Processes raw signals into structured insights:
- Clusters signals by theme
- Scores relevance to Never Blank positioning
- Flags urgency (time-sensitive news vs. evergreen angles)
- Eliminates noise below relevance threshold

**Output:** `data/analysis/YYYY-MM-DD.json`

### 3. Topic Prioritization

Ranks analyzed signals into publishable topic candidates:
- Checks against memory (no duplicate topics within configurable window)
- Scores by: relevance, timeliness, platform fit, audience value
- Returns an ordered list of candidates

**Output:** `data/topic_candidates/YYYY-MM-DD.json`

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

## Quality Control Layer

Every piece of content passes through QC before publishing.
QC is a sequential gate — any failure stops publication and logs the reason.

### QC Checks (in order)

| Check                   | Description                                                          |
|-------------------------|----------------------------------------------------------------------|
| Duplication Detection   | Semantic similarity against `memory/topic_embeddings.json`. Blocks if score > threshold. |
| Factuality Check        | Claude re-reads the content and flags any claims that are unverifiable or that contradict the brief. |
| Hallucination Prevention| Checks for invented statistics, named people, or specific dates not present in the source signals. |
| Consistency Check       | Verifies that all platform variants carry the same core message and angle. |
| Brand Voice Validation  | Compares output against `memory/voice_examples.json`. Flags tonal drift. |

QC config (thresholds, enabled checks, strictness) lives in `config/quality.yaml`.

All QC failures are logged to the report with the specific reason.
Failed content is saved to `data/drafts/failed/` for manual review.

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
├── signals.yaml          # RSS feeds, keyword clusters, competitor list
└── prompts/
    ├── blog_post.yaml        # full Wix article prompt template
    ├── linkedin_post.yaml    # LinkedIn post prompt
    ├── facebook_post.yaml    # Facebook post prompt
    ├── instagram_caption.yaml
    ├── threads_post.yaml
    ├── topic_analysis.yaml   # prompt for market analysis step
    ├── strategy_brief.yaml   # prompt for strategy layer
    ├── qc_factuality.yaml    # prompt for factuality check
    ├── qc_voice.yaml         # prompt for brand voice validation
    └── image_hook.yaml       # prompt for extracting hook sentence for image
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
│   │   ├── signal_monitor.py      # fetches raw signals from RSS, trends
│   │   ├── market_analysis.py     # clusters and scores signals
│   │   ├── topic_prioritizer.py   # ranks topic candidates
│   │   ├── strategy.py            # applies editorial logic, builds ContentBrief
│   │   └── memory.py              # reads/writes memory store
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
│   ├── signals/                   # raw signal JSON files by date
│   ├── analysis/                  # scored analysis JSON files by date
│   ├── topic_candidates/          # ranked topic lists by date
│   ├── drafts/
│   │   ├── pending/               # content awaiting QC
│   │   └── failed/                # content that failed QC
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
│   ├── run_publish_only.py        # publish pre-approved draft manually
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

1. **Prompts live in config, not code.** Python loads templates; it never builds prompt strings.
2. **Manual queue takes priority.** Automation serves when humans have nothing queued.
3. **Memory prevents repetition.** Every published topic is remembered semantically, not just by title.
4. **QC is a hard gate.** Failed content does not publish — it waits for human review.
5. **The system reports itself.** Every run is visible in Google Sheets without opening the code.
6. **Brand voice is a constraint, not an afterthought.** Voice validation runs before every publish.
7. **Images are part of the content, not decoration.** Generated automatically, with hook and branding.
8. **One source of truth per concern.** Config owns rules. Memory owns history. Sheets owns visibility.
