# Never Blank Signal Research Pipeline

## 1. Overview

The Never Blank Signal Research Pipeline is a daily automated system that finds, scores, enriches, and angles real business signals from news sources. It feeds a rolling library of content-ready signals to the content generation layer.

The pipeline does not summarize news. It identifies economic, operational, or behavioral shifts that businesses are responding to — the kind of signal that generates a genuine editorial angle for founders.

Runs daily at 08:00 UTC via GitHub Actions. Output is committed back to the repo as JSONL.

---

## 2. Architecture

```
Stage 1: Discovery
  └── Fetch RSS feeds → filter by signal categories via LLM
        ↓
Stage 2: Deduplication
  └── Check seen_index.json → skip already-processed signals
        ↓
Stage 3: Scoring
  └── LLM scores each candidate against 5 binary criteria (max 10 pts)
        ↓
Stage 4: Enrichment
  └── LLM fills full signal schema — NEVER invents facts, company names, or outcomes
        ↓
Stage 5: Angle Generation
  └── LLM generates channel-specific content angles (LinkedIn, Blog, Threads, Story)
        ↓
Stage 6: Save
  └── Append to data/research/signals_active.jsonl
      Update data/research/seen_index.json
      High-scoring signals → data/research/selected_signals.jsonl
        ↓
Stage 7: Google Sheets Sync (write)
  └── Pushes all active signals to Sheets tab for editorial review
      Failure is non-fatal — JSONL is source of truth
        ↓
Stage 8: Pull-back from Sheets (optional)
  └── Pulls only NOTES, APPROVED_OVERRIDE, and angle edits back to JSONL
        ↓
Stage 9: Archive
  └── Moves signals >60 days old (not selected, not approved) to archive/
```

---

## 3. Source of Truth

**GitHub JSONL is the source of truth. Always.**

- `data/research/signals_active.jsonl` — all active signals
- `data/research/selected_signals.jsonl` — signals selected for content generation
- `data/research/seen_index.json` — deduplication index

Google Sheets is a view and light edit layer only. The pull-back step (`sync_from_sheets.py`) only writes back a narrow allowlist of fields: `NOTES`, `APPROVED_OVERRIDE`, `LINKEDIN_ANGLE`, `BLOG_ANGLE`, `THREADS_ANGLE`, `STORY_ANGLE`. All other fields in Sheets are display-only and are overwritten on the next sync.

---

## 4. File Structure

```
config/
  research_sources.yaml          — RSS feeds, lookback window, signal/avoid categories
  scoring_weights.yaml           — Scoring criteria, weights, thresholds

scripts/research/
  __init__.py
  discover.py                    — Stage 1: RSS fetch + LLM filter
  score.py                       — Stage 3: LLM scoring
  enrich.py                      — Stage 4: LLM enrichment (no hallucination)
  angles.py                      — Stage 5: Content angle generation
  sync_to_sheets.py              — Stage 7: Write to Google Sheets
  sync_from_sheets.py            — Stage 8: Pull edits from Sheets
  archive.py                     — Stage 9: Move old signals to archive
  run_daily_research.py          — Orchestrator: runs all stages in order

data/research/
  signals_active.jsonl           — Active signal library (source of truth)
  selected_signals.jsonl         — Signals selected for content generation
  seen_index.json                — Deduplication index (signal_id → date + headline)
  archive/
    signals_YYYY_MM.jsonl        — Archived signals by month

.github/workflows/
  daily_signal_research.yml      — GitHub Actions: runs daily at 08:00 UTC

tests/
  test_research_pipeline.py      — Unit tests for pipeline logic

docs/
  NEVER_BLANK_RESEARCH_PIPELINE.md  — This file
  SYSTEM_MAP.md                     — Full system map
```

---

## 5. Full Signal Schema

Every signal in `signals_active.jsonl` contains the following fields:

| Field | Source | Description |
|---|---|---|
| SIGNAL_ID | discover.py | 16-char MD5 hash of normalized URL + headline |
| DATE_FOUND | discover.py | Date pipeline found the signal (YYYY-MM-DD) |
| SOURCE_DATE | discover.py | Publication date of the original article |
| SOURCE_NAME | discover.py | RSS feed name (e.g. "Reuters Business") |
| SOURCE_URL | discover.py | Normalized article URL |
| HEADLINE | discover.py | Article headline |
| REGION | discover.py | US / Global / EU / inferred |
| INDUSTRY | discover.py | Main industry of the signal |
| SIGNAL_TYPE | discover.py | One of the signal_categories from config |
| raw_summary | discover.py | 2-3 sentence factual summary from LLM |
| discovery_confidence | discover.py | high / medium / low |
| SIGNAL_STRENGTH | score.py | high / medium / low |
| DISCUSSION_POTENTIAL | score.py | high / medium / low |
| CHANNEL_FIT_SCORE | score.py | 1-10 integer |
| ARTICLE_READINESS_SCORE | score.py | 0-10 total score |
| score_reason | score.py | One sentence explaining the score |
| RECOMMENDED_FOR_ARTICLE | score.py | true / false |
| CORE_FACT | enrich.py | The central verifiable fact of the signal |
| WHY_IT_MATTERS_TO_BUSINESS | enrich.py | Business relevance explanation |
| BUSINESS_RESPONSES_OBSERVED | enrich.py | How businesses have responded |
| REAL_COMPANY_EXAMPLE | enrich.py | Named company (null if not identifiable) |
| PROBLEM_FACED | enrich.py | The business problem in the case |
| RESPONSE_TAKEN | enrich.py | What the company did |
| OUTCOME_IF_KNOWN | enrich.py | Result — "unknown" if not sourced |
| SOURCE_FOR_CASE | enrich.py | URL or publication for the case (null if unknown) |
| BUSINESS_LESSON | enrich.py | The transferable lesson |
| DID_IT_WORK | enrich.py | "yes" / "no" / "unknown" |
| EVIDENCE_OF_OUTCOME | enrich.py | Evidence for the outcome claim |
| TIME_HORIZON | enrich.py | How quickly the outcome materialized |
| COUNTER_EXAMPLE | enrich.py | A company that responded differently |
| WHY_THIS_CASE_IS_INTERESTING | enrich.py | Editorial note on what makes this worth writing |
| CORE_TENSION | enrich.py | The business tension (e.g. "Trust vs Margin") |
| CONFIDENCE | enrich.py | high / medium / low confidence in enrichment |
| NOTES | enrich.py / Sheets | Manual editorial notes |
| LINKEDIN_ANGLE | angles.py | Observation + business lesson format |
| BLOG_ANGLE | angles.py | Signal + case + outcome + lesson format |
| THREADS_ANGLE | angles.py | One-liner provocative observation |
| STORY_ANGLE | angles.py | Question or tension format |
| POTENTIAL_HOOK | angles.py | Opening sentence — concrete and uncomfortable |
| INTERESTING_QUESTION | angles.py | The question this raises for founders |
| NEVER_BLANK_ANGLE | angles.py | The Never Blank editorial observation |
| POSSIBLE_SIGNATURE_LINE | angles.py | "Never Blank: [short insight]" |
| TARGET_AUDIENCE | angles.py | founder / owner / consultant / etc. |
| PRIMARY_CHANNEL | angles.py | linkedin / blog / threads / story / instagram |
| SOURCE_QUALITY | run_daily | Inherited from RSS source quality config |
| APPROVED_OVERRIDE | Sheets | Manual override to keep in queue ("true" / "") |

---

## 6. Scoring Formula

Scoring is binary per criterion. Each criterion is either earned (full weight) or not (0).

| Criterion | Weight | Description |
|---|---|---|
| strong_business_signal | 2 | Clear business/economic signal, not opinion |
| numerical_fact | 2 | Contains measurable data or identifiable trend |
| real_company_available | 2 | Real company or business behavior identifiable |
| clear_tension | 2 | Clear business tension visible (Trust vs Margin, etc.) |
| channel_fit | 2 | Good fit for LinkedIn/Blog/Threads audience |
| **Total** | **10** | |

**Thresholds:**
- `enrich_minimum: 5` — minimum score to be sent to enrichment
- `select_minimum: 7` — minimum score to be added to selected_signals.jsonl
- `top_n_to_enrich: 10` — top N candidates sent to enrichment stage
- `top_n_to_select: 3` — top N signals added to selected queue per run

---

## 7. Archive Rules

Signals are automatically archived when ALL three conditions are true:
1. `DATE_FOUND` is more than 60 days ago
2. `APPROVED_OVERRIDE` is not "true", "yes", or "1"
3. `SIGNAL_ID` is not in `selected_signals.jsonl`

Archived signals are written to `data/research/archive/signals_YYYY_MM.jsonl` grouped by the month they were found. They are removed from `signals_active.jsonl`.

Archive never deletes — it only moves.

---

## 8. How to Run Manually

```bash
# From the repo root:
python scripts/research/run_daily_research.py
```

Required environment variables (see Section 10) must be set before running.

To run only discovery (no LLM cost):
```bash
python scripts/research/discover.py
```

To sync to Sheets only:
```bash
python scripts/research/sync_to_sheets.py
```

To run archive only:
```bash
python scripts/research/archive.py
```

---

## 9. How to Troubleshoot

**No candidates found:**
- Check RSS feeds are reachable: `curl -I https://feeds.reuters.com/reuters/businessNews`
- Check `lookback_hours` in `config/research_sources.yaml` (default 72)
- Check LLM API key is set: `echo $NB_OPENAI_API_KEY`

**Signals not making it to selected:**
- Check `ARTICLE_READINESS_SCORE` in `signals_active.jsonl`
- Threshold is `select_minimum: 7` in `config/scoring_weights.yaml`
- Check `RECOMMENDED_FOR_ARTICLE` field

**Duplicate signals appearing:**
- Check `data/research/seen_index.json` — should contain SIGNAL_ID keys
- `make_signal_id` normalizes URLs (strips UTM params, lowercases)

**Sheets sync failing:**
- Check `NB_RESEARCH_SHEET_ID` is set correctly
- Check service account has Editor access to the sheet
- Pipeline continues even if sync fails — check logs for "Sheets sync failed (non-fatal)"

**JSONL corruption:**
- Each line is validated with `json.loads()` before write
- Read the file: `python3 -c "import json; [json.loads(l) for l in open('data/research/signals_active.jsonl')]"`

**Checking logs in GitHub Actions:**
- Go to Actions tab → Daily Signal Research → click the run → expand "Run research pipeline"
- Summary is written to the step summary at the bottom of each run

---

## 10. Required Secrets

Set these in GitHub repository Settings → Secrets and variables → Actions:

| Secret | Description |
|---|---|
| `NB_OPENAI_API_KEY` | OpenAI API key for LLM calls |
| `NB_OPENAI_CHAT_MODEL` | Model name (e.g. `gpt-4o`, `gpt-4o-mini`) |
| `NB_GOOGLE_SERVICE_ACCOUNT_JSON` | Google service account JSON (full JSON string) |
| `NB_RESEARCH_SHEET_ID` | Google Sheets spreadsheet ID |
| `NB_RESEARCH_SHEET_TAB` | Tab name in the sheet (default: "Signals") |
| `NB_RESEARCH_MAX_DAILY_COST_USD` | Budget cap per run in USD (default: "2.00") |

Optional:
| Secret | Description |
|---|---|
| `NB_GOOGLE_SHEETS_CREDENTIALS_JSON` | Fallback for service account JSON (same format) |
| `NB_OPENAI_TEMPERATURE` | LLM temperature (default: "0.3") |

---

## 11. What Happens on Sync Failure

Google Sheets sync failure is explicitly non-fatal.

If `sync_to_sheets.py` raises any exception:
- A warning is logged: "Sheets sync failed (non-fatal): {reason}"
- The function returns `False`
- The orchestrator records `"sheet_sync": "failed"` in the daily report
- `signals_active.jsonl` is NOT modified
- The pipeline continues to the archive stage

The JSONL files on disk are always complete and valid regardless of Sheets state.

---

## 12. Connection to Content Generation

`data/research/selected_signals.jsonl` is the handoff point between research and content generation.

Each run appends up to `top_n_to_select` (default 3) signals with `ARTICLE_READINESS_SCORE >= 7` to this file.

The content generation layer (future `scripts/generate.py`) reads from `selected_signals.jsonl` and uses the pre-generated angles (`LINKEDIN_ANGLE`, `BLOG_ANGLE`, `THREADS_ANGLE`, `STORY_ANGLE`, `POTENTIAL_HOOK`) as starting points for full article and post generation.

Signals in `selected_signals.jsonl` are protected from archiving — they stay in `signals_active.jsonl` until explicitly removed.
