# Never Blank Pipeline — Implementation Plan

> No production code is written yet. This document defines the build order, phase goals, and acceptance criteria for each phase.

---

## Build Philosophy

- Each phase produces a working, testable unit — not a partial skeleton.
- No phase moves forward until the previous phase is verified.
- Config files are written before any code that depends on them.
- Every phase ends with a manual test that a human can run without reading code.

---

## Phase 0 — Foundation (do this first, touch nothing else)

**Goal:** Repository is runnable, secrets are safe, config structure exists.

### Steps

1. Create `.gitignore`
   - Exclude: `.env`, `data/`, `assets/logo/`, `__pycache__`, `.venv`

2. Create `.env.example`
   - Document every required secret with description and example format

3. Create `requirements.txt`
   - `anthropic`, `python-dotenv`, `pyyaml`, `gspread`, `google-auth`, `cloudinary`, `requests`, `Pillow`, `feedparser`, `pytrends`, `numpy`

4. Create empty config stubs
   - `config/brand.yaml` — placeholder with color palette structure
   - `config/strategy.yaml` — placeholder with angle pattern structure
   - `config/quality.yaml` — QC thresholds with sensible defaults
   - `config/platforms.yaml` — character limits, image dimensions per platform
   - `config/signals.yaml` — RSS feed list, keyword clusters (empty lists for now)

5. Create all prompt template files in `config/prompts/`
   - Each file is a YAML with keys: `system`, `user`, `variables` (list of placeholders)
   - Content is placeholder text only — real prompts come in Phase 3

6. Create `src/utils/config_loader.py`
   - `load_yaml(path)` — loads any YAML config
   - `load_prompt(name, variables)` — loads prompt template, fills `{variable}` placeholders

7. Create `src/utils/logger.py`
   - Structured logging: timestamp, level, component, message

**Acceptance:** `python -c "from src.utils.config_loader import load_yaml; print('ok')"` runs without error.

---

## Phase 1 — Topic Queue (the human control layer)

**Goal:** System can read manual topics and knows whether to use them or fall through to signals.

### Steps

1. Define `topics_manual.csv` schema
   - Columns: `id`, `title`, `angle`, `target_platforms`, `priority`, `notes`, `status`
   - Status values: `pending`, `in_progress`, `published`, `skipped`

2. Create `src/utils/google_sheets.py`
   - `read_sheet(tab_name)` → list of dicts
   - `write_row(tab_name, row)` → appends a row
   - `update_cell(tab_name, row_id, col, value)` → updates one cell

3. Create `scripts/sync_sheets.py`
   - Pulls manual topic queue from Google Sheet "Topic Queue" tab
   - Writes to `topics_manual.csv`
   - Marks synced rows in the sheet

4. Create topic queue reader in `src/internal/memory.py`
   - `get_next_manual_topic()` → returns first `pending` row or `None`
   - `mark_topic_status(id, status)`

5. Create `src/internal/topic_prioritizer.py` (stub only)
   - `get_next_topic()` → checks manual queue first; if empty, returns `None` (signals not wired yet)

**Acceptance:** Add a row to `topics_manual.csv` with `status=pending`. Run `python -c "from src.internal.topic_prioritizer import get_next_topic; print(get_next_topic())"`. Should print the row.

---

## Phase 2 — Memory

**Goal:** System knows what has been published and can detect topic duplicates.

### Steps

1. Define `data/memory/published.json` schema
   ```json
   [
     {
       "id": "uuid",
       "date": "YYYY-MM-DD",
       "title": "...",
       "slug": "...",
       "platforms": ["wix", "linkedin"],
       "urls": {"wix": "...", "linkedin": "..."},
       "topic_summary": "one-sentence summary for dedup"
     }
   ]
   ```

2. Create `data/memory/voice_examples.json`
   - Manually curated: 5-10 example posts that represent the Never Blank voice
   - Each entry: `{"platform": "linkedin", "text": "...", "notes": "why this is a good example"}`

3. Implement `src/internal/memory.py`
   - `load_published()` → list of published items
   - `save_published(item)` → appends to published.json
   - `load_voice_examples()` → list of voice reference texts
   - `is_duplicate(topic_summary, threshold)` → basic string similarity for now (embeddings later)

**Acceptance:** Add a fake entry to `published.json`. Call `is_duplicate("same topic summary")` → should return `True`. Call with different text → `False`.

---

## Phase 3 — Content Generation

**Goal:** Given a topic and angle, system produces content for all platforms.

### Steps

1. Write real prompt templates in `config/prompts/`
   - `blog_post.yaml`: system prompt establishes Never Blank voice and purpose; user prompt includes `{title}`, `{angle}`, `{goal}`, `{brand_voice_examples}`
   - `linkedin_post.yaml`, `facebook_post.yaml`, `instagram_caption.yaml`, `threads_post.yaml`: adapted per platform constraints
   - All prompts must include voice anchoring via `{brand_voice_examples}`

2. Create `ContentBrief` dataclass in `src/internal/strategy.py`
   ```python
   @dataclass
   class ContentBrief:
       title: str
       angle: str
       goal: str          # educate / challenge / demonstrate / invite
       platforms: list[str]
       tone_notes: str
       source_signals: list[str]
   ```

3. Create `src/content/generator.py`
   - `generate_blog_post(brief)` → calls Claude API with blog_post prompt
   - `generate_platform_variant(brief, platform, blog_post)` → adapts blog post per platform
   - Never builds prompt strings — always calls `config_loader.load_prompt(name, variables)`

4. Create `src/content/adapters.py`
   - `adapt_for_platform(content, platform)` → enforces character limits from `platforms.yaml`

**Acceptance:** Create a test brief manually. Call `generate_blog_post(brief)`. Read the output and verify it sounds like Never Blank, not a generic AI post.

---

## Phase 4 — Quality Control

**Goal:** QC runs autonomously. It never stops the pipeline waiting for a human — it rewrites, quarantines, or retries depending on failure type.

### Steps

1. Write QC prompt templates
   - `config/prompts/qc_factuality.yaml`: instructs Claude to identify claims not verifiable from the provided source signals; returns structured JSON with `passed` and `flags`
   - `config/prompts/qc_voice.yaml`: instructs Claude to compare content against voice examples and flag drift; returns `passed` and `issues`
   - `config/prompts/rewrite_with_feedback.yaml`: rewrite prompt that receives the original brief + original content + QC failure reason

2. Implement `src/quality/deduplication.py`
   - `check_duplicate(topic_summary)` → `{"passed": bool, "score": float, "reason": str, "failure_type": "type2"}`

3. Implement `src/quality/factuality.py`
   - `check_factuality(content, source_signals)` → `{"passed": bool, "flags": list, "failure_type": "type3"}`

4. Implement `src/quality/voice.py`
   - `check_voice(content, voice_examples)` → `{"passed": bool, "issues": list, "failure_type": "type2"}`

5. Implement `src/quality/gate.py`
   - `run_qc(content, brief)` → runs all checks in sequence
   - Returns structured result: `{"passed": bool, "status": "green|yellow|orange", "failed_at": str, "failure_type": "type1|type2|type3", "reason": str}`
   - Does NOT raise exceptions — always returns a result object the runner can act on

6. Implement rewrite loop in `src/content/generator.py`
   - `rewrite_with_feedback(content, brief, qc_result)` → calls `rewrite_with_feedback.yaml` prompt
   - Max rewrite attempts configured in `quality.yaml` as `max_rewrites`

**Acceptance:**
- Generate content. Inject a fake factual claim. Run QC → result should be `failure_type: type3`, `status: orange`.
- Inject a voice drift issue. Run QC → result should be `failure_type: type2`. Call rewrite → verify new content is generated. Re-run QC → should pass → `status: yellow`.

---

## Phase 5 — Publishing

**Goal:** Approved content publishes to all target platforms.

### Steps

1. Implement `src/publishing/wix.py`
   - `publish_post(title, content, slug)` → Wix Headless CMS API → returns `{"url": "...", "post_id": "..."}`

2. Implement `src/publishing/linkedin.py`
   - `publish_post(text)` → LinkedIn Share API → returns `{"url": "...", "post_id": "..."}`

3. Implement `src/publishing/facebook.py`
   - `publish_post(message, image_url)` → Facebook Graph API → returns `{"post_id": "..."}`

4. Implement `src/publishing/instagram.py`
   - `publish_post(image_url, caption)` → two-step: create container → publish → returns `{"post_id": "..."}`

5. Implement `src/publishing/threads.py`
   - `publish_post(text)` → Threads API → returns `{"post_id": "..."}`

6. Each publisher:
   - Reads credentials from `.env` only (no hardcoded values)
   - Returns structured result object
   - Raises typed exceptions on failure (not raw requests errors)

**Acceptance:** Publish one test post to each platform. Verify the post appears. Verify no credentials appear in any source file.

---

## Phase 6 — Visual Assets

**Goal:** Every post has an automatically generated, on-brand image.

### Steps

1. Define image templates in `assets/templates/`
   - One template per platform (dimensions from `platforms.yaml`)
   - Template = background + logo position + text zones

2. Write `config/prompts/image_hook.yaml`
   - Extracts the strongest single sentence from content to use as image headline

3. Implement `src/content/image_builder.py`
   - `extract_hook(content)` → Claude API call → returns hook string
   - `render_image(hook, platform, template)` → Pillow rendering → saves to `data/visuals/`
   - `upload_image(path)` → Cloudinary upload → returns CDN URL

**Acceptance:** Generate an image for a test post. Verify it has the logo, correct palette, hook text, correct dimensions for the target platform.

---

## Phase 7 — Signal Pipeline (automated topic sourcing)

**Goal:** When no manual topics exist, the system finds its own topics.

### Steps

1. Implement `src/internal/signal_monitor.py`
   - `fetch_rss_signals()` → reads feeds from `signals.yaml` → returns list of raw items
   - `fetch_trends_signals()` → Google Trends for configured keywords

2. Implement `src/internal/market_analysis.py`
   - `analyze_signals(signals)` → Claude API call using `topic_analysis.yaml` prompt
   - Returns scored and clustered signal groups

3. Implement `src/internal/strategy.py` (full version)
   - `build_brief_from_signals(analysis)` → applies rules from `strategy.yaml` → returns `ContentBrief`

4. Wire into `src/internal/topic_prioritizer.py`
   - `get_next_topic()` now: check manual queue → if empty → run signal pipeline → return brief

**Acceptance:** Empty the manual topic queue. Run `get_next_topic()`. System should return a signal-derived `ContentBrief`.

---

## Phase 8 — Reporting

**Goal:** Every run is visible without opening the code.

### Steps

1. Implement `src/reporting/reporter.py`
   - `build_report(run_context)` → assembles structured run report dict
   - `save_report(report)` → writes to `data/reports/YYYY-MM-DD-HH-MM.json`

2. Implement `src/reporting/sheets.py`
   - `log_run(report)` → writes to "Pipeline Log" tab in Google Sheet
   - `log_published(item)` → writes to "Published" tab
   - `log_failure(error)` → writes to "Failures & Retries" tab
   - `update_topic_status(id, status)` → updates "Topic Queue" tab

**Acceptance:** Run a full pipeline cycle. Open Google Sheet. Verify all tabs updated correctly.

---

## Phase 9 — Main Pipeline Runner

**Goal:** One command runs the full pipeline end to end.

### Steps

1. Implement `scripts/run_pipeline.py` with full autonomous failure handling:
   ```
   1. sync manual topics from Google Sheets
   2. get next topic (manual or signal)
   3. generate content
   4. run QC gate
      → type2 fail: rewrite (up to max_rewrites)
         → still failing: ORANGE, quarantine topic, go to step 2 with next topic
      → type3 fail: ORANGE, quarantine topic, go to step 2 with next topic
      → passed after rewrite: YELLOW, continue
      → passed first time: GREEN, continue
   5. generate visual assets
      → type1 fail: retry (up to max_retries)
      → still failing: publish without image, log warning
   6. publish to all target platforms
      → type1 fail: retry with backoff
      → still failing after retries: RED status, alert, stop run
   7. update memory
   8. write report to Google Sheet with final status (GREEN / YELLOW / ORANGE / RED)
   ```

2. Implement `scripts/run_publish_only.py`
   - Takes a quarantined draft from `data/drafts/quarantine/` and publishes it after manual decision
   - This is optional — not a required step in the normal flow

3. Status is always written to Google Sheet, even on RED
   - Pipeline crash does not produce a silent failure

**Acceptance:** Run `python scripts/run_pipeline.py`. Force a type2 QC failure → observe rewrite → observe YELLOW publish. Force a type3 → observe quarantine, observe system pick next topic and publish that instead. Google Sheet shows both outcomes correctly.

---

## Phase 10 — Automation

**Goal:** Pipeline runs on schedule without human intervention.

### Steps

1. Add GitHub Actions workflow (`.github/workflows/run_pipeline.yml`)
   - Scheduled trigger (e.g., daily at 9 AM EST)
   - Secrets injected from GitHub repository secrets
   - Runs `python scripts/run_pipeline.py`
   - On failure: sends notification (method TBD)

2. Add `scripts/sync_sheets.py` to the scheduled run
   - Always pull the latest manual topics before each run

**Acceptance:** Disable manual trigger. Wait for scheduled run. Verify post published and Google Sheet updated without touching the machine.

---

## Phase Sequence Summary

| Phase | Name                  | Dependency         |
|-------|-----------------------|--------------------|
| 0     | Foundation            | None               |
| 1     | Topic Queue           | Phase 0            |
| 2     | Memory                | Phase 0            |
| 3     | Content Generation    | Phase 0, 2         |
| 4     | Quality Control       | Phase 3            |
| 5     | Publishing            | Phase 4            |
| 6     | Visual Assets         | Phase 3            |
| 7     | Signal Pipeline       | Phase 1, 2, 3      |
| 8     | Reporting             | Phase 5            |
| 9     | Pipeline Runner       | Phase 1–8          |
| 10    | Automation            | Phase 9            |

---

## What Is Not Built Yet

- No AI model selection rationale (TBD based on cost vs. quality testing)
- No embedding model for semantic deduplication (Phase 2 uses string similarity; Phase 7+ can upgrade)
- No Threads API implementation (API availability may change — stub ready)
- No performance analytics integration (manual notes in memory for now)
- No multi-language content (English only in v1)
