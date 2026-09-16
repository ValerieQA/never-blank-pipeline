<!-- #248 required pre-change audit. Read-only, at origin/main 14e4886. Source of truth: issue #248. -->

# Issue #248 audit: why scheduled Facebook, Instagram and Threads publication is blocked

**Read at:** `origin/main` = `14e4886d053df123a5617fb4f153b7917e10e6c7` ("Publish Wednesday f9c2f40f85d82da3 [skip ci]", 2026-09-16). The local checkout is on branch `task/247-wednesday-meta-recovery`, but every citation below is from `origin/main`. Nothing was changed, run or called.

Four findings matter most for the plan:
- **Friday (scheduled Fri 08:17/09:17 UTC):** nothing restricts it to Wix + LinkedIn today. Facebook, Instagram and Threads are reachable. Wix and LinkedIn most likely fail there (see F1).
- **A second Friday publisher exists:** `research_generate_and_publish.yml` also fires on Friday.
- **Monday and the Friday/Sunday research run:** they don't even generate Facebook or Instagram text.
- **The canonical entrypoint:** it has no package, preflight path or adapter for any social channel other than LinkedIn.

## (1) Ownership matrix

| Stream | Workflow + cron | Entry script | Channel payloads generated | Can publish today | Blockers for FB / IG / Threads | Secrets passed to the publish step (names only) | Images per channel |
|---|---|---|---|---|---|---|---|
| **a. Monday** | `monday_publish.yml:29-30` `17 8 * * 1`, `17 9 * * 1`; dispatch `:32` | `generate_and_publish.py --editorial-role never-blank-monday-documented-case` (`monday_publish.yml:230,271-273`) | **Composed:** blog and LinkedIn only, because `composer_formats=_R1_COMPOSER_FORMATS` (`generate_and_publish.py:1891`, `:508`).<br>**Empty:** `facebook_post` is `""` plus a "Source: url" footer when `SOURCE_URL` is set (`:1920`, `:2359-2362`). `instagram_caption` is `""` (`:1921`, `:2363`).<br>**Always built, no model call:** threads (`:1922`) and telegram (`:1923`). | Wix, LinkedIn | `_R1_PUBLISHERS` (`:501`, `:2649`, `:2774`); `_r1_cls` (`:2768`); composer formats (`:508`); image platforms (`:509`, `:2428`); preflight channel whitelist (`preflight.py:62-65`, `:233-238`, `:280`); no package model or builder (`package.py:174-265`); visual passport limited to Wix/LinkedIn (`contract.py:44-47`, `:146-150`); **no Meta/Threads secrets in the workflow** (enforced by a test, see §6) | Step `:229-263`: NB_OPENAI_API_KEY, NB_EXA_API_KEY, NB_OPENAI_CHAT_MODEL, NB_ENRICH_MODEL, NB_ARTICLE_MODEL, NB_SOCIAL_MODEL, NB_WIX_API_KEY, NB_WIX_SITE_ID, NB_WIX_POST_OWNER_ID, NB_WIX_BLOG_CATEGORY_ID, NB_WIX_BLOG_TAG_IDS, NB_WIX_SITE_BASE_URL, NB_ZERNIO_API_KEY, NB_ZERNIO_LINKEDIN_ACCOUNT_ID, NB_CLOUDINARY_{CLOUD_NAME,API_KEY,API_SECRET}, NB_FORCE_REGENERATE_RESEARCH_IMAGES | Blog (1920×1080) and LinkedIn (1200×628) only (`:2428`; `contract.py:291-309`) |
| **b. Wednesday Golden** | `wednesday_golden.yml:11-12` `17 8 * * 3`, `17 9 * * 3` | Same entrypoint with `--editorial-role never-blank-wednesday-golden` (`:166,211-213`), routed to `generate_for_wednesday` (`generate_and_publish.py:1878-1880`) | **All five formats are composed (and paid for)** by the July composer (`wednesday_july/platform_composer.py:231-238`). So `facebook_post` is real text (`:1920`, formatted at `:2359-2362`) and so is `instagram_caption`, with hashtags (`:2363-2371`). Threads and telegram are deterministic. | Wix, LinkedIn | Same as Monday, except the composer is not a blocker. No Meta/Threads secrets (enforced by a test). | Step `:165-202`: the same set as Monday minus EXA, plus NB_DISCOVERY_MODEL, NB_SCORING_MODEL, and NB_RUN_TEXT_CALL_BUDGET="56" (a literal value, not a secret) | Blog and LinkedIn only |
| **c. Friday (record only)** | `scheduled_publish.yml:23-24` `17 8 * * 5`, `17 9 * * 5`; **no `concurrency` group** | `scheduled_publish.py:226-240` runs, as separate subprocesses: `generate.py --qc`, `generate_image.py --upload`, then `publish.py --live --channels <ch>` for wix, then linkedin/facebook/instagram/threads, then telegram only if Wix returned rc 0 | All six text files (`generate.py:121-164`) | **Facebook, Instagram, Threads: not scope-gated.** `publish.py:50-59` maps all six publishers and no `release_scope` import exists.<br>**Wix, LinkedIn: probably fail** (see F1). | None from `release_scope`. Only whether provider/credentials succeed. | `:59-78`: NB_OPENAI_API_KEY, NB_WIX_{API_KEY,SITE_ID,POST_OWNER_ID}, NB_ZERNIO_{API_KEY,LINKEDIN_ACCOUNT_ID}, NB_META_USER_TOKEN, NB_META_IG_USER_ID, NB_META_FB_PAGE_ID, NB_META_FB_PAGE_TOKEN, NB_THREADS_ACCESS_TOKEN, NB_TELEGRAM_{BOT_TOKEN,CHANNEL_ID}, NB_CLOUDINARY_*, NB_GOOGLE_SHEETS_CREDENTIALS_JSON, NB_GOOGLE_SHEET_ID | One master image from `image_url.txt` (`base.py:159-163`). `platform_image_urls` is empty, so every channel falls back to the master (`base.py:112-114`). |
| **d. Visibility (Tue/Thu)** | `visibility_publish.yml:6-7` `0 7 * * 2`, `0 7 * * 4`; **no `concurrency` group** | `generate_and_publish_visibility.py` (`:93`) | All six texts (`vi_pipeline.py:249-254`); drafted at `:251-273` | Scope allows Wix + LinkedIn only (`:300`), but both probably fail (see F1; errors are caught at `:334-336`). | `restrict_to_release_scope(all_publishers)` (`:300`); the four others are stamped SKIPPED (`:306-312`) | `:52-84`: NB_OPENAI_API_KEY, NB_OPENAI_CHAT_MODEL, NB_CLOUDINARY_*, NB_ZERNIO_*, NB_META_FB_PAGE_TOKEN, NB_META_FB_PAGE_ID, NB_META_IG_USER_ID, NB_THREADS_ACCESS_TOKEN, NB_TELEGRAM_*, NB_WIX_{API_KEY,SITE_ID,SITE_BASE_URL,POST_OWNER_ID,BLOG_CATEGORY_ID,BLOG_TAG_IDS} | `generate_and_upload_card` renders all six sizes but returns only the blog master URL (`image_pipeline.py:1494-1533`). `_build_draft` sets only `image_url` (`:268`), so Instagram and Facebook get the 1920×1080 master. |
| **e. Research Full LLM (Fri/Sun)** | `research_generate_and_publish.yml:34` `0 7 * * 5,0`; concurrency `never-blank-publish` (`:37-39`) | `generate_and_publish.py` with no role (`:170`); signal auto-selected (`:57-85`) | Same as Monday: the role-less path is non-Wednesday, so it uses `_R1_COMPOSER_FORMATS` | Wix, LinkedIn | Same as Monday. Its secrets check is skipped on scheduled runs because `if: inputs.dry_run == 'false'` (`:100`) and `inputs` is empty on a schedule. | `:133-164`: the Monday set plus NB_META_FB_PAGE_ID, NB_META_FB_PAGE_TOKEN, NB_META_IG_USER_ID, NB_THREADS_ACCESS_TOKEN, NB_TELEGRAM_* (`:149-154`) | Blog and LinkedIn only |
| **f. Daily Signal Research, Stage 11** | `daily_signal_research.yml:5` `0 8 * * *`; no concurrency group; Stage 11 forced off on ET Wednesdays (`:82-84`) | `run_daily_research.py:191-202` → `publish_packages.py` | All five formats (`generate_article` without `composer_formats`, `publish_packages.py:228-242`); threads and telegram validated (`:111-132`, `:93-108`) | Enabled only if secret `NB_RESEARCH_PUBLISH_ENABLED == "true"` (`:188`; wf `:61`). Scope allows Wix + LinkedIn, which fail with DraftPackage attribute errors (commit `84a85f5` message). | `_PUBLISHERS = restrict_to_release_scope(_ALL_PUBLISHERS)` (`:66`); withheld channels stamped SKIPPED (`:293-300`) | `:38-76`: the full set, including NB_META_FB_PAGE_ID, NB_META_FB_PAGE_TOKEN, NB_META_IG_USER_ID, NB_THREADS_ACCESS_TOKEN, NB_TELEGRAM_*, NB_PUBLISH_MODE="live" | Full six-platform set (`prepare_content_packages(selected)` with no `platforms`, `run_daily_research.py:191`; `prepare_content.py:37`). A per-channel image is swapped in for linkedin/facebook/instagram (`publish_packages.py:304-305`). |

**Cross-cutting findings:**
- **F1 (inferred from code, not observed in a run for Friday or Visibility).** `WixPublisher.publish` and `LinkedInPublisher.publish` accept only frozen packages.
  - They call `DraftPackage.from_wix_package(package)` / `from_linkedin_package` (`wix.py:157-171`, `linkedin.py:46-59`). Those read `package.title` and `package.linkedin_body` (`base.py:67`, `:96`).
  - Friday (`publish.py:194`), Visibility (`:329`) and Stage 11 (`:313`) pass a `DraftPackage`, which has neither attribute, so an `AttributeError` follows.
  - In `publish.py` the call isn't wrapped in try/except (`:178-194`), so the Wix subprocess exits non-zero and Friday's telegram step is skipped (`scheduled_publish.py:239-243`).
- **F2.** Friday has two scheduled publishers: `scheduled_publish.yml` (08:17/09:17 UTC) and `research_generate_and_publish.yml` (07:00 UTC Friday). They share no concurrency group.
- **F3.** The docstring of `test_the_friday_publisher_reaches_no_channel_of_its_own` (`tests/test_r1_publish_scope.py:274-281`) says Friday "shells out to the canonical entrypoint". It actually shells out to `scripts/publish.py`, which reaches all six channels. The test only checks that `scheduled_publish.py` contains no `*Publisher` names.
  - Likewise, `test_manual_publishers_may_still_reach_every_channel` (`:213-223`) treats `publish.py` as manual-only. It is also invoked by a scheduled workflow.

## Section 1: the allowlist machinery

**`src/publishing/release_scope.py`**
- `R1_PUBLISH_CHANNELS = ("wix", "linkedin")` (`:33`).
- `NON_R1_PUBLISH_CHANNELS = ("facebook", "instagram", "threads", "telegram")` (`:38-40`).
- `in_release_scope` (`:45-47`), `restrict_to_release_scope` (`:50-58`, order-preserving because Wix must precede LinkedIn), `out_of_release_scope` (`:61-63`).
- The docstring (`:1-25`) states that adding a channel is "a change to this file and nowhere else". That is a single global policy.

**Every importer and consumer:**
- **`scripts/generate_and_publish.py`**
  - Imports at `:258-261`; aliases `_R1_PUBLISHERS` and `_NON_R1_PUBLISHERS` at `:501-502`.
  - Used at `:557` (`_stop_with_preflight` outcomes), `:2649` (package construction), `:2774` (publish loop) and `:3033` (the `[skipped-not-r1]` line).
  - The docstring states the scope at `:86-88`.
  - It still imports `FacebookPublisher`, `InstagramPublisher`, `TelegramPublisher` and `ThreadsPublisher` (`:225-226`, `:262-263`) but never uses them. A test depends on them staying patchable (see §6).
- **`scripts/generate_and_publish_visibility.py`:** imports at `:43-46`; used at `:300` and `:306-312`.
- **`scripts/research/publish_packages.py`:** imports at `:31-34`; `_PUBLISHERS` at `:66`, `_WITHHELD_CHANNELS` at `:68`, log at `:208-214`, SKIPPED results at `:293-300`.
- **Tests:** `tests/test_r1_publish_scope.py`, `tests/test_publish_packages.py:11`, `tests/test_generate_and_publish.py:24-25` (see §6).
- **Docs:** `docs/monday-architecture/MONDAY_TARGET_ARCHITECTURE.md:276,290`; `reports/monday-architecture/MONDAY_CURRENT_STATE.md:169,381`.

**Other hard-coded Wix/LinkedIn-only lists:**

| Location | What it restricts |
|---|---|
| `generate_and_publish.py:508` `_R1_COMPOSER_FORMATS = ("long", "medium")` | Composed formats, used at `:1891` (the only `composer_formats=` call site) |
| `generate_and_publish.py:509` `_R1_IMAGE_PLATFORMS = ["blog", "linkedin"]` | Image platforms, used at `:2428` |
| `generate_and_publish.py:2768` `_r1_cls = {"wix": ..., "linkedin": ...}` | Which publisher classes the loop can construct |
| `generate_and_publish.py:2582-2600`, `:2608-2632` | `_build_channel` has only a wix branch and an else-branch that assumes LinkedIn |
| `generate_and_publish.py:2821-2825` | `channel_view` is wix, otherwise linkedin |
| `generate_and_publish.py:2314` | Validation runs for `("blog", "linkedin")` only |
| `generate_and_publish.py:3129` | Analytics collectors are `[BlogCollector(), LinkedInCollector()]` |
| `src/publishing/preflight.py:62-65` `CHANNEL_CREDENTIAL_ENV = {wix, linkedin}` | Also acts as the channel whitelist in `ChannelPreflightVerdict._release1_channel` (`:233-238`) |
| `preflight.py:226` | `target: Union[WixPublicationTarget, LinkedInPublicationTarget]` |
| `preflight.py:280` | `channels ... max_length=2` |
| `preflight.py:484-492` | `_target_is_identified`: Wix, otherwise assumes `account_id` |
| `src/visual/contract.py:44-47` `RELEASE1_CHANNELS` | Enforced at `:146-150` ("non-Release-1 channels"); builder at `:291-309` |
| `src/reporting/run_report.py:131-136` | `ChannelReport` accepts wix or linkedin only |
| `run_report.py:446` | Iterates `("wix", "linkedin")` |
| `run_report.py:336` | Locally derived URL allowed for Wix only |
| `src/publishing/idempotency.py:227-231`, `:278-305` | Destination and package rebuild branch on wix, otherwise linkedin |
| `src/strategy/business_config.py:182-184` `ChannelRules` | Only `wix` and `linkedin` fields |
| `src/strategy/execution_context.py:190-253` | Views: wix, linkedin, visual (`wix_rules` / `linkedin_rules`) |
| `src/editorial/editorial_role.py:104-106` | Surface rules for wix and linkedin only |
| `EditorialRole.wix_rules` / `linkedin_rules` (`business_config.py:112-113`) | Role-level surface rules exist for these two only |
| Workflow "Check (R1) publish secrets" steps | Monday `:206-225`, Wednesday `:144-160` |

**History:**
- **`d85e600` (2026-08-11), "feat(task-26): establish canonical Release 1 orchestration entry point".** Introduced `_R1_PUBLISHERS` and the `[skipped-not-r1]` line. Later touched by `2ea1935` and `4590138` (2026-08-11) and `c8a0f3c` (2026-08-16, task-101).
- **`c013698` (2026-08-22), "R1 pays only for the surfaces it publishes (#175)".** Introduced `_R1_COMPOSER_FORMATS` and `_R1_IMAGE_PLATFORMS`.
  - Stated rationale: avoid 4 model calls and 4 image composite+upload operations per run.
  - Files: `platform_composer.py` and `pipeline.py` (the `formats=` parameter), `prepare_content.py` (the `platforms=` parameter), `tests/test_r1_surface_reduction.py`.
  - (`825a10d` #246 matches `-S` only through docs.)
- **`84a85f5` (2026-09-07), "#229: only Release 1's own channels may auto-publish"; merged as PR #230 (`654ef38`, branch `feature/task-227-r1-publish-scope`).** Introduced `release_scope.py` and `R1_PUBLISH_CHANNELS`.
  - Why: on 2026-09-06 and 2026-09-07, Stage 11 published to Facebook, Instagram and Telegram while Wix and LinkedIn failed with DraftPackage attribute errors.
  - The visibility path had published Telegram on 2026-08-20.
  - An overlap check had been masking both until #222 removed it. Forensics are in #159.
  - The commit states that `generate_and_publish.py` behaviour is unchanged, and that Threads was "withheld by the same rule" while it was already failing with HTTP 400.
  - Files: `generate_and_publish.py`, `generate_and_publish_visibility.py`, `publish_packages.py`, `release_scope.py`, `tests/test_publish_packages.py`, `tests/test_r1_publish_scope.py`.

## Section 2: per-stream traces (details beyond the matrix)

- **Monday**
  - Due check: `monday_publish.yml:81-100`. Signal selection: `scripts/streams/select_eligible_signal.py --editorial-role`, using `--published-path data/research/published_signal_ids.txt` (`select_eligible_signal.py:102`).
  - A `--from-package` retry is refused if the signal is already consumed (`:150`).
  - The role resolves at `generate_and_publish.py:908-926`. It carries `cta_mode: none` (`:940-946`), `require_source_transparency` (`:1862`) and `closing_contract` (`:1894-1896`).
- **Wednesday**
  - The signal comes from the July supply (`generate_and_publish.py:974-997`, `supply_wednesday_signal(..., seen_ids=published_signal_ids())`). The signal id is read back from the log (`wednesday_golden.yml:219-221`).
  - Everything after generation is shared with Monday (comment at `:1869-1877`).
- **Friday**
  - Scheduling comes from `config/schedule.yaml` via `scripts/streams/due_check` (`scheduled_publish.py:25-32`, `:45-76`).
  - Setup installs only `python-dotenv openai Pillow cloudinary PyYAML numpy google-auth google-api-python-client` (`scheduled_publish.yml:55`).
  - Recorded only; no redesign proposed.
- **Visibility**
  - Queue state machine: `generate_and_publish_visibility.py:208-242`; stuck-item recovery: `:145-192`.
  - Retry skips platforms that already succeeded (`:315-321`, from `visibility_history.jsonl`).
  - Final status treats SKIPPED as neutral (`:489-492`).
  - It uses `load_active_strategy` (strategy.json), not the business configuration or roles (`:356-363`).
- **Research Full LLM:** role-less, so decision policy is `decision_lens` (`:1283-1286`). Otherwise identical to Monday's publication path.
- **Stage 11**
  - Not canonical (`run_daily_research.py:4-11`).
  - No preflight, no idempotency, no run namespace. Writes a flat `{sig}_generated.json` (`publish_packages.py:288-291`, `:329-331`).
  - The failure summary is used only to fail the job loudly (`run_daily_research.py:204-216`, `:269-273`).

## Section 3: the canonical packaging path in `generate_and_publish.py`

**Packages**
- `package.py` defines only `WixPublicationTarget` (`:140-160`), `LinkedInPublicationTarget` (`:163-171`), `WixPublicationPackage` (channel `Literal["wix"]`, `:174-219`) and `LinkedInPublicationPackage` (channel `Literal["linkedin"]`, `:222-264`, with `canonical_article_url` at `:237`).
- Both extend `_PackageModel` (frozen, `extra="forbid"`, `package_digest()` = sha256 of canonical JSON, `:113-131`).
- Builders:
  - `build_wix_publication_package` (`:391-441`): requires the visual passport; cover image is `visual_record.wix_url`.
  - `build_linkedin_publication_package` (`:494-596`): requires the accepted LinkedIn composition, whose body must equal `generated.linkedin_post` (`:566-571`); image only when `linkedin_visual is VALID` (`:572-580`).
  - `bind_canonical_article_url` (`:444-491`) builds a new frozen LinkedIn package.
  - Shared binding across run, signal, configuration and article digest: `_bind_generated_to_run` (`:307-388`).

**Preflight** (`preflight.py:327-481`)
- Shared checks: provenance (`verify_run_provenance`), readiness, configuration consistency, freshness, package `run_id`, run-scoped failures.
- Per channel: package validity, `_target_is_identified`, and `_credential_ready(channel)`, which reads `CHANNEL_CREDENTIAL_ENV[channel]` (`:321-324`). An unknown channel raises `KeyError` there.
- Channels are constrained at `:62-65`, `:226`, `:233-238`, `:280` and `:484-492`.
- `ChannelPackageOutcome` (`:155-213`) itself is channel-agnostic.
- `schema_version` is fixed at "1.0" (`:57`, `:282-287`). Historical verdicts are strictly reloaded by idempotency (`idempotency.py:204-207`).

**`_build_channel`** (`:2580-2647`)
- Targets come from environment variables: `NB_WIX_*` and `NB_ZERNIO_LINKEDIN_ACCOUNT_ID`.
- It is called for each name in `_R1_PUBLISHERS` (`:2649`).
- From-package runs load `linkedin_composition.json` (`:2565-2575`).

**Publish loop** (`:2768-3022`)
- Blocked verdicts are recorded as BLOCKED (`:2775-2787`).
- **"Wix gates social publication" (#196/#200), `:2788-2819`:** `linkedin` is attempted only if `_canonical_verdict` is verified. The verdict comes from `verify_canonical_url(url, provenance, expected_host=NB_WIX_SITE_BASE_URL)` (`:2725-2756`), applied to the Wix result (`:3002-3008`) or to a fresh provider lookup when Wix was REUSED (`:2987-2994`).
- The gate is written as `name == "linkedin"`; it isn't generic to "social".
- A configuration-identity check runs against the channel view (`:2820-2830`), then a digest equality check against the verdict (`:2831-2837`).
- **How LinkedIn gets the URL:**
  - `bind_canonical_article_url(_package, _canonical_verdict.url)` (`:2855`), then `validate_social_lineage` (`:2856-2859`).
  - A **second, exact-package preflight** is evaluated and persisted to `linkedin_final_preflight.json` (`:2873-2887`; writer in `src/artifacts/__init__.py:547-558`), then its digest is checked (`:2919-2923`).
  - Lineage evidence is attached to the result (`:2929-2933`, `:3021-3022`).
- **Idempotency:** `find_prior_wix_publication` / `find_prior_linkedin_publication` (`:2941-2995`) can produce REUSED.
- **Publish call:** `_r1_cls[name]().publish(_package, "live", strategy_view=channel_view)` (`:2997-2999`), then `_normalize_publish_result` (`:608-630`).
- **Run failure:** any channel whose status isn't in `_COMPLETED_STATUSES` fails the run (`:3037-3044`, `:3150-3154`, exit 1).

**What Facebook, Instagram or Threads would need in order to pass through this path.** Each item below is currently absent.
1. **Frozen package models** with a `channel` Literal, target model, body field(s), image field(s) and `canonical_article_url` (`package.py`).
2. **Builders** binding to `generated.json` (`facebook_post`, `instagram_caption`, `threads_sequence`), the visual passport and configuration identity, with `PackageFailureCategory` classification.
   - There is no accepted-composition artifact for these channels, unlike `linkedin_composition.json` (`:494-571`).
   - For Monday and role-less runs, the bodies are empty because of `_R1_COMPOSER_FORMATS`.
3. **Non-secret target identity:** e.g. an FB page id or IG user id. Threads currently has none; it resolves `/me` at publish time (`threads.py:97-105`).
4. **Preflight changes:** entries in `CHANNEL_CREDENTIAL_ENV`, target Union members, `_target_is_identified` branches, and a larger `PreflightResult.channels` `max_length`. These must stay loadable by `idempotency._validated_prior_target` for old verdicts.
5. **Provenance and digest:** the package digest works automatically once the models exist. Lineage validation (like `validate_social_lineage`) and a final exact-package preflight would be needed if a canonical URL is bound. The final-preflight artifact name is LinkedIn-specific (`write_linkedin_final_preflight_json`).
6. **Publisher adapters that accept a frozen package:** `publish(package, mode, *, strategy_view=None)` plus `DraftPackage.from_<channel>_package`. The current FB/IG/Threads signature `publish(self, draft, mode)` would raise `TypeError` on the `strategy_view=` keyword at `:2997-2999`.
7. **Strategy/channel views** for the configuration-identity check (`:2821-2830`; `execution_context.py:174-198`).
8. **Per-channel image assets in the passport:** `RELEASE1_CHANNELS`, `_validate_channel`, the `VisualAssetsRecord` validator, `build_visual_assets_record`, the `reuse_visual_assets_record` path (`generate_and_publish.py:1798-1806`), and `_R1_IMAGE_PLATFORMS`.
9. **Idempotency identity and scan** per channel (none exists for FB/IG/Threads).
10. **`run_report.ChannelReport`** channel whitelist and `:446` iteration.
11. **URL provenance:** these publishers leave the default `UrlProvenance.UNAVAILABLE` (`result.py:72`) while returning a URL, which `run_report.py:331-332` rejects.
12. **Loop wiring:** `_r1_cls`, the channel-view selection, and whether each new channel sits behind the Wix gate (`:2799`).

## Section 4: the Facebook, Instagram and Threads publishers

**`facebook.py`**
- **Inputs:**
  - env `NB_META_FB_PAGE_ID` and `NB_META_FB_PAGE_TOKEN`; missing either gives FAILED (`:26-34`);
  - `draft.facebook_text`; empty gives FAILED (`:39-41`);
  - `draft.image_for("facebook")` (`:43`).
- **Post type:** with an image it POSTs `/{page}/photos` with `url` + `caption`; otherwise `/{page}/feed` with `message` (`:56-70`).
- **Length limits:** none.
- **Idempotency or duplicate handling:** none.
- **Returns:** `post_id` or `id`, and a locally built URL `https://www.facebook.com/{post_id}` (`:79-82`). Provenance stays at the default UNAVAILABLE.
- **Modes:** `draft_only` gives SKIPPED; `dry_run` gives SKIPPED.

**`instagram.py`**
- **Inputs:**
  - env `NB_META_IG_USER_ID` and `NB_META_FB_PAGE_TOKEN`, used as the IG token (`:31-39`);
  - an image is **required**; without one it returns SKIPPED (`:44-49`);
  - `instagram_text`; empty gives FAILED (`:51-53`).
- **Flow:** create container → poll `status_code` up to 10×3 s (`:86-102`) → `media_publish` → fetch permalink (`:122-129`).
- **Returns:** `media_id`. The URL is the permalink, or the generic `https://www.instagram.com/` as a fallback (`:131-134`). That fallback is not verifiable.
- **Length and duplicates:** no caption limit enforced, no idempotency.
- **Interaction with the canonical path:** SKIPPED is not a completed status there, so it would fail a canonical run (`generate_and_publish.py:333-341`, `:3037`).

**`threads.py`**
- **Inputs:** env `NB_THREADS_ACCESS_TOKEN` only (`:71-73`); `threads_sequence`; empty gives FAILED (`:78-80`).
- **Posts:** text only (`media_type TEXT`, `:32`), so no image. Each post is truncated to 500 chars (`:111`); dry run only warns above 500 (`:83-87`). The user id comes from `/me` (`:98-105`). Posts form a reply chain with a fixed 5 s sleep (`:120`).
- **Failure semantics:** if the first post fails, the result is FAILED. If a later post fails, the chain stops **and still returns PUBLISHED** (`:113-117`, `:122-126`, `:131-138`).
- **Returns:** the first media id and a locally built URL `https://www.threads.net/t/{first_id}` (`:137`). A media id is not a shortcode, so that URL is probably not the real post URL (inference).
- **Idempotency:** none.

**Sequence builders:** the canonical `_build_threads` (`generate_and_publish.py:409-431`) does not run `validate_platform_output`. Stage 11's version does (`publish_packages.py:127`).

**Shared:** all three use `_fetch` (`base.py:185-214`); `BasePublisher.publish` is documented as taking a frozen package (`base.py:258-268`).

## Section 5: per-channel image assets

**Sizes available** (`PLATFORM_SIZES`, `image_pipeline.py:97-104`): facebook 1200×628, instagram 1080×1350, threads 1080×1080. The Instagram brand QA check exists (`:113-123`).

**`prepare_content.py`**
- `PLATFORMS` covers six surfaces (`:37`). A per-platform composite and Cloudinary upload runs for each (`:196-214`), scoped by `platforms=` (`:343-357`).
- **Reuse path:** every platform gets the **same** `existing_url` with the nominal size string (`:284-297`). Instagram would then receive the master image labelled "1080x1350".
- **Failure:** image generation failure yields empty URLs (`:313-328`).

**Where `_R1_IMAGE_PLATFORMS` restricts it**
- The canonical regeneration call passes `platforms=_R1_IMAGE_PLATFORMS` (`generate_and_publish.py:2426-2431`).
- When the signal package cache is current (`_load_package_images`, `:393-401`; `needs_regen` at `:2417-2420`), `pimgs` may already hold facebook/instagram entries written by daily research. They are listed in `platform_image_urls` (`:2446-2450`), but that dict only reaches review evidence (`:2084`). They never reach the passport or any package.

**Visual passport** (`contract.py`)
- Only Wix (required) and LinkedIn (optional) (`:44-47`).
- `_validate_channel` checks dimensions against the actual file when a local path exists (`:217-260`).
- The record validator rejects any other channel (`:146-150`).

**`docs/VISUAL_CONTRACT.md`**
- Wix required, LinkedIn optional (`:6-16`).
- "Only Release 1 channels (Wix, LinkedIn) are recorded — no Instagram/Facebook/Threads/Telegram visual behavior is introduced" (`:45-46`).

**Visibility and Friday:** only one master URL reaches the draft (see matrix).

## Section 6: tests that encode Wix/LinkedIn-only assumptions

**`tests/test_r1_publish_scope.py`**
- `test_release_1_publishes_wix_and_linkedin_and_nothing_else` (`:82`)
- `test_no_non_r1_channel_is_in_scope` (`:90`)
- `test_the_r1_channels_stay_in_scope` (`:95`)
- `test_the_filter_preserves_order_because_linkedin_needs_the_wix_url` (`:100`)
- `test_the_authority_imports_no_publisher` (`:109`)
- `test_daily_research_can_only_publish_the_r1_channels` (`:128`)
- `test_daily_research_cannot_auto_publish_the_channels_it_published` (`:138`)
- `test_daily_research_records_the_withheld_channels_rather_than_omitting_them` (`:147`)
- `test_the_research_publisher_list_is_not_a_hand_maintained_literal` (`:157`)
- `test_the_visibility_flow_is_scheduled_and_therefore_automatic` (`:173`)
- `test_the_visibility_flow_cannot_auto_publish_non_r1_channels` (`:181`)
- `test_repairing_the_model_id_cannot_revive_non_r1_publishing` (`:197`)
- `test_manual_publishers_may_still_reach_every_channel` (`:213`)
- `test_the_publisher_implementations_were_not_deleted` (`:226`)
- `test_the_canonical_entrypoint_still_declares_the_same_scope` (`:237`)
- `test_the_canonical_entrypoint_never_constructed_a_non_r1_publisher` (`:246`, a static check that the FB/IG/Threads/Telegram class names are never referenced)
- `test_the_canonical_streams_still_run_the_canonical_entrypoint` (`:266`)
- `test_the_friday_publisher_reaches_no_channel_of_its_own` (`:274`, see F3)
- `test_importing_the_authority_constructs_nothing` (`:343`)

**`tests/test_generate_and_publish.py`**
- `test_invokes_wix_and_linkedin_once_each` (`:675`)
- `test_never_instantiates_non_r1_publishers` (`:680-705`)
- `TestNonR1PublisherIsolation.test_r1_publishers_constant` (`:714`)
- `test_non_r1_publishers_constant` (`:717`)
- `test_non_r1_failure_does_not_affect_successful_r1_exit_code` (`:720-737`)

**`tests/test_publish_packages.py`**
- The all-publishers-failed history scenario. It monkeypatches `_PUBLISHERS` to wix+linkedin (`:182-185`) and asserts that the withheld set is a subset of `NON_R1_PUBLISH_CHANNELS` (`:206-215`).
- I didn't capture the enclosing test's name; it lives just above `:180`.

**`tests/test_r1_surface_reduction.py`**
- `test_the_canonical_run_requests_only_the_r1_formats` (`:144`; asserts formats `("long","medium")` and hashtag calls `== ["linkedin"]`)
- `test_the_package_contract_is_intact_with_inactive_surfaces_empty` (`:154`; `facebook_post == ""`, `instagram_caption == ""`)
- `test_monday_and_wednesday_share_the_single_reduced_call_site` (`:169`)
- `test_image_reuse_builds_assets_for_active_platforms_only` (`:185`)
- `test_the_entrypoint_scopes_image_platforms_to_r1` (`:208`)
- `test_daily_research_keeps_the_full_platform_set` (`:214`)

**Other tests**
- `tests/test_visual_contract.py`: `test_entrypoint_persists_immutable_run_scoped_visual_passport` (`:222`, asserts derivative channels `== {"wix","linkedin"}` at `:232-234`) and `test_schema_valid_but_semantically_invalid_passports_are_rejected` (`:405`, the instagram → "non-Release-1" case at `:395-396`).
- `tests/test_monday_stream.py`: `test_the_required_publish_secrets_are_wix_and_linkedin_only` (`:1172-1183`) asserts that no `NB_META_*`, `NB_THREADS_*` or `NB_TELEGRAM_*` appears anywhere in `monday_publish.yml`.
- `tests/test_wednesday_golden.py`: `test_wednesday_workflow_uses_canonical_visual_and_r1_publish_surfaces` (`:527`, excludes `NB_META`, `NB_THREADS`, `NB_TELEGRAM` from the generate step's env at `:543-544`).
- `tests/test_canonical_social_lineage.py:411-416` treats the Facebook body as "non-R1 … out of scope".
- `tests/test_canonical_publish_credentials.py::test_no_unrelated_credential_wiring_was_removed` (`:71-82`) requires the research workflow to keep its Meta/Threads/Telegram wiring. This test supports enablement rather than blocking it.
- `tests/test_vi_end_to_end.py:272-350` mocks results for all six publishers. I didn't verify how it interacts with the SKIPPED stamping.

**Not found:** grep for "unsupported Release 1 publication channel" and `CHANNEL_CREDENTIAL_ENV` in `tests/` returned nothing. The strict preflight and run-report channel validators are not directly pinned by name.

## Section 7: consumption and no-duplicate guarantees to preserve

- **`data/research/published_signal_ids.txt`** is written by workflows only, per run and per signal, not per channel, and only on `success()`:
  - Monday `:277`, `:285-291`;
  - Wednesday `:225`, `:230-234`;
  - Research F/Sun `:174`, `:182-188`.
  - Friday, Visibility and Stage 11 don't write it.
  - Readers: Monday retry guard (`:150`), Wednesday retry guard (`:118`), `select_eligible_signal.py:102`, `wednesday_supply.published_signal_ids` (`:60`, `:175`, `:269`), research auto-select (`:65-78`).
- **Consequence:** a canonical run returns 1 if *any* attempted channel is not completed (`generate_and_publish.py:3037-3044`, `:3150-3154`). The marker step is then skipped even though Wix may already be live.
  - Wix and LinkedIn are protected on retry by proven-evidence idempotency: `find_prior_wix_publication` / `find_prior_linkedin_publication` produce REUSED (`:2941-2995`; `idempotency.py:1-30`, `:414-432`, `:520`).
  - These scans are **per channel**, keyed by `(signal_id, article digest, site_id)` and `(signal, accepted LinkedIn body digest, account_id)` (`idempotency.py:62-99`).
  - FB/IG/Threads have no equivalent, so a retry could post duplicates.
- **REUSED** is completed but not OK (`:333-341`; `result.py:79-89`). It is excluded from history.
- **PROVIDER_DUPLICATE** (`result.py:20`) is produced only by LinkedIn on HTTP 409 (`linkedin.py:166-179`). It belongs to neither status set, so it counts as a failure. It never suppresses a later publication (`idempotency.py:430-431`).
- **`strategy/published_content_index.jsonl`**
  - Canonical path: one `PublishedEntry` per run, with a per-channel `publications` map built from OK statuses only (`generate_and_publish.py:3094-3123`).
  - Stage 11: one entry per signal, only if some publication succeeded (`publish_packages.py:332-383`).
  - Model: `strategy/models.py:501-524`. Writes are append-only and errors are swallowed (`history.py:186-204`).
  - Monday, Wednesday and Research commit it in the marker step.
- **Visibility** keeps per-item state and per-platform retry in `visibility_history.jsonl` (`:119-140`, `:315-321`). It does not use the signal marker or the index.
- **Run artifacts** (`publication_results.json`, preflight) are written once per run (`:3035-3091`; docstring `:43-64`).
- **Concurrency:** group `never-blank-publish` covers Monday (`:53-55`), Wednesday (`:32-34`) and Research (`:37-39`) only.

## Section 8: where a per-stream channel scope could be declared

**What exists today**
- `EditorialRole` (`business_config.py:90-162`) has: `role_id`, `intent`, `structure`, `forbidden`, `eligibility_criteria`, `wix_rules`, `linkedin_rules`, `require_source_transparency`, `decision_policy`, acceptance rubric path/identity, `cta_mode`, `closing_contract`.
- **No `channels` or destinations field exists.** The model is `extra="forbid"` (`:32-35`), so any new key needs a model change.
- The comments at `:108-111` and `:133-140` state the principle that role-specific behaviour belongs on the role, "not the shared `channels.*`", because otherwise it "would silently change every other stream's output". That is the existing precedent for per-stream scoping.

**`strategy/current/business_strategy.json`**
- `channels` has only `wix` and `linkedin` (`:233-305`).
- Roles:
  - `never-blank-monday-documented-case` (`:345-396`): `require_source_transparency`, `decision_policy role_bounded_r1`, `cta_mode none`, `closing_contract branded_echo_then_sources`.
  - `never-blank-wednesday-golden` (`:398-444`): transparency, rubric, `role_bounded_r1`.

**Loaders and consumers**
- `resolve_editorial_role` and `render_editorial_role_rules` (`editorial_role.py:50`, `:81-110`) handle wix/linkedin surfaces only.
- `StrategyExecutionContext` exposes wix, linkedin and visual views only (`execution_context.py:174-253`).
- `is_wednesday_role` (`wednesday_routing.py:41-54`) is the only role-based routing seam besides role fields.

**Identity side-effect:** `configuration_hash` covers the entire validated configuration (`execution_context.py:64-89`). Any added role field changes `ConfigurationIdentity`. That affects `--from-package` freshness and configuration checks against source runs produced under the old identity (`generate_and_publish.py:2661-2670`; builders' CONFIGURATION category, `package.py:557-562`).

**Streams with no role or business-configuration hook at all**
- Research F/Sun is role-less.
- Visibility, Stage 11 and Friday read `strategy.json` via `load_active_strategy`, not the business configuration.
- Their only current "scope" declarations are code lists (`publish_packages.py:47-68`; visibility `:292-300`; `scheduled_publish.py:232-240`) plus workflow secret wiring.

**Docs only (not implemented):** `MONDAY_TARGET_ARCHITECTURE.md:20-32`, `:56`, `:61-82` proposes per-stream Markdown front matter with `channels: [wix, linkedin]` (`:77`), and "Channel behaviour … overridable per stream" (`:56`). There is no `strategy/never-blank/` directory on `origin/main`.

**Conclusion:** nothing in code today models per-stream publication destinations.

## Minimum change surface (files and functions any implementation must touch; no design proposed)

**Shared canonical machinery (Monday, Wednesday, Research F/Sun)**
- `src/publishing/release_scope.py`
  - All constants and helpers.
  - Whatever replaces or augments the global allowlist must avoid silently changing Visibility and Stage 11, which import it.
- `scripts/generate_and_publish.py`
  - Constants: `_R1_PUBLISHERS` / `_NON_R1_PUBLISHERS` (`:501-502`), `_R1_COMPOSER_FORMATS` (`:508`, `:1891`), `_R1_IMAGE_PLATFORMS` (`:509`, `:2428`).
  - Channel construction and preflight stop: `_stop_with_preflight` (`:551-558`), `_build_channel` (`:2580-2649`).
  - Publish loop: `_r1_cls`, the channel view, the Wix gate, final preflight, idempotency (`:2768-3022`).
  - Reporting: `[skipped-not-r1]` (`:3033`), the failure and consumption semantics (`:3037-3044`, `:3150-3155`), validation list (`:2314`), analytics (`:3129`), docstring (`:86-88`).
  - Pass-through text for FB/IG (`:1920-1921`, `:2359-2371`); `_build_threads` (`:409-431`).
  - The unused publisher imports (`:225-226`, `:262-263`).
- `src/publishing/package.py`: new models, targets, builders, and URL binding.
- `src/publishing/preflight.py`: `CHANNEL_CREDENTIAL_ENV`, `ChannelPreflightVerdict.target` / `_release1_channel`, `PreflightResult.channels` `max_length`, `_target_is_identified`.
- `src/publishing/base.py`: `DraftPackage.from_*_package` factories.
- `src/publishing/facebook.py`, `instagram.py`, `threads.py`: package-in `publish(..., *, strategy_view=None)`, URL provenance, Threads partial-chain semantics, Instagram SKIPPED semantics.
- `src/publishing/idempotency.py`: per-channel identity and scans; `_validated_prior_target` and `_authorized_package_digest_matches` channel branches.
- `src/publishing/canonical_url.py` / `validate_social_lineage` call sites, if new channels carry the canonical link.
- `src/artifacts/__init__.py`: `write_linkedin_final_preflight_json` is LinkedIn-named.
- `src/visual/contract.py`: `RELEASE1_CHANNELS`, validator, `build_visual_assets_record`, `reuse_visual_assets_record`. Plus `docs/VISUAL_CONTRACT.md`.
- `scripts/research/prepare_content.py`: reuse path (`:284-297`) if per-channel sizes matter.
- `src/reporting/run_report.py`: `ChannelReport._release1_channel` (`:131-136`), `:336`, `:446`.
- `src/strategy/execution_context.py` (channel views) and, if scope is declared in configuration, `src/strategy/business_config.py` (`EditorialRole` / `ChannelRules`), `strategy/current/business_strategy.json` and `src/editorial/editorial_role.py`.
- Tests: all files listed in §6.

**Per stream**
- **Monday:** `.github/workflows/monday_publish.yml` (secret wiring in the generate step `:229-263` and check step `:206-225`); `tests/test_monday_stream.py:1172-1183`; role entry in `business_strategy.json:345-396`.
- **Wednesday:** `.github/workflows/wednesday_golden.yml` (`:144-160`, `:165-202`); `tests/test_wednesday_golden.py:527-544`; role entry at `:398-444`. Text is already composed by `wednesday_july/platform_composer.py:231-238`.
- **Research F/Sun (role-less):** the workflow already passes the secrets (`:149-154`). Any role-less scope has to be expressed without a role object. Note the Friday overlap (F2).
- **Visibility:** `scripts/generate_and_publish_visibility.py` (`:43-46`, `:289-338`, `:489-492`), `_build_draft` / image wiring (`:251-273`, `:430-445`); `tests/test_r1_publish_scope.py:173-205`; `tests/test_vi_end_to_end.py`. Its Wix/LinkedIn DraftPackage incompatibility (F1) is independent of this change.
- **Stage 11:** `scripts/research/publish_packages.py` (`:44-68`, `:205-214`, `:293-328`); `tests/test_r1_publish_scope.py:128-165`; `tests/test_publish_packages.py:182-215`. Workflow gates: `daily_signal_research.yml:61`, `:82-84`. It has the same F1 issue.
- **Friday (record only; don't redesign):** `scheduled_publish.py:232-240` and `publish.py:50-59` are ungated today. Any global change in `release_scope.py` does not affect Friday unless `publish.py` is changed. `tests/test_r1_publish_scope.py:213-223` and `:274-281` are the pins to revisit.
