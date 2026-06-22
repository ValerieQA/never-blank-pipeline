# Never Blank System Map

## Editorial & Style
- Editorial style (article formula, audience, writing rules): docs/NEVER_BLANK_EDITORIAL_STYLE.md
- Brand voice (tone, forbidden phrases, hook rules, platform differences): config/brand_voice.md
- Brand identity (palette, fonts, logo): config/brand.yaml

## Research Pipeline
- Pipeline documentation: docs/NEVER_BLANK_RESEARCH_PIPELINE.md
- RSS sources config: config/research_sources.yaml
- Scoring weights: config/scoring_weights.yaml
- Discovery: scripts/research/discover.py
- Scoring: scripts/research/score.py
- Enrichment: scripts/research/enrich.py
- Angle generation: scripts/research/angles.py
- Sheets sync (write): scripts/research/sync_to_sheets.py
- Sheets pull-back: scripts/research/sync_from_sheets.py
- Archive: scripts/research/archive.py
- Daily orchestrator: scripts/research/run_daily_research.py
- Workflow: .github/workflows/daily_signal_research.yml
- Active signals (source of truth): data/research/signals_active.jsonl
- Selected for content: data/research/selected_signals.jsonl
- Seen index (dedup): data/research/seen_index.json
- Archive: data/research/archive/signals_YYYY_MM.jsonl

## Content Generation
- Content strategy: config/strategy.yaml
- Content matrix config: config/content_matrix.yaml
- Intelligence config: config/intelligence.yaml
- Blog generation prompt: config/prompts/blog_post.yaml
- Content matrix prompt: config/prompts/content_matrix.yaml
- Strategy brief prompt: config/prompts/strategy_brief.yaml

## Platform Prompts
- LinkedIn: config/prompts/linkedin_post.yaml
- Instagram: config/prompts/instagram_caption.yaml
- Facebook: config/prompts/facebook_post.yaml
- Threads: config/prompts/threads_post.yaml
- Telegram: config/prompts/telegram_post.yaml
- Stories: config/prompts/stories_post.yaml
- Channel strategy: config/platforms.yaml

## Image System
- Visual system (6 families, palette): config/visual_system.yaml
- Image generation prompt: config/prompts/image_generation.yaml
- Image hook prompt: config/prompts/image_hook.yaml

## QC & Rewrite
- QC config: config/quality.yaml
- Factuality check: config/prompts/qc_factuality.yaml
- Voice check: config/prompts/qc_voice.yaml
- Rewrite prompt: config/prompts/rewrite_with_feedback.yaml

## Research & Discovery
- Observation discovery: config/prompts/observation_discovery.yaml
- Observation scoring: config/prompts/observation_score.yaml
- Topic extraction: config/prompts/topic_extract.yaml
- Topic scoring: config/prompts/topic_score.yaml

## Publishing
- Publish script: scripts/publish.py
- Generate + publish workflow: .github/workflows/generate_and_publish.yml
- Scheduled publish workflow: .github/workflows/scheduled_publish.yml
- Schedule config: config/schedule.yaml

## Sheets Sync (Content)
- Content matrix sync: src/utils/google_sheets.py
- Content sheet: NB_GOOGLE_SHEET_ID env var

## Reports
- Publish reports: reports/publish_report.{json,md}
- Research reports: reports/research_YYYY-MM-DD.json
- Full live test reports: reports/full_live_matrix_test.{json,md}

## Architecture & History
- Architecture overview: ARCHITECTURE.md
- Implementation log: IMPLEMENTATION_PLAN.md, PHASE_5D_REPORT.md, PHASE_6_SCHEDULING.md
