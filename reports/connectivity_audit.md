# Never Blank — Publisher Connectivity Audit

Generated: 2026-06-20T01:39:31.991332+00:00

## Secrets
| Secret | Status | Preview |
|--------|--------|---------|
| `NB_OPENAI_API_KEY` | ✓ | sk-p...H1IA (164 chars) |
| `NB_WIX_API_KEY` | ✓ | IST....VsPN (600 chars) |
| `NB_WIX_SITE_ID` | ✓ | b254...67de (36 chars) |
| `NB_LINKEDIN_ACCESS_TOKEN` | ✓ | AQWq...yOZQ (350 chars) |
| `NB_META_USER_TOKEN` | ✓ | EAAY...ZDZD (286 chars) |
| `NB_META_IG_USER_ID` | ✓ | 1784...5275 (17 chars) |
| `NB_META_FB_PAGE_ID` | ✓ | 1219...8622 (16 chars) |
| `NB_META_FB_PAGE_TOKEN` | ✓ | EAAY...gFAF (238 chars) |
| `NB_THREADS_ACCESS_TOKEN` | ✓ | THAA...GMZD (202 chars) |
| `NB_TELEGRAM_BOT_TOKEN` | ✓ | 8826...RlfU (46 chars) |
| `NB_TELEGRAM_CHANNEL_ID` | ✓ | @nev...eros (20 chars) |
| `NB_CLOUDINARY_CLOUD_NAME` | ✓ | df0l...7izx (9 chars) |
| `NB_CLOUDINARY_API_KEY` | ✓ | 9648...4388 (15 chars) |
| `NB_CLOUDINARY_API_SECRET` | ✓ | S697...CuWM (27 chars) |
| `NB_GOOGLE_SHEETS_CREDENTIALS_JSON` | ✓ | valid JSON (2342 chars) |
| `NB_GOOGLE_SHEET_ID` | ✓ | 1vC-...xAdo (44 chars) |

## Platform Results
| Platform | Status | Notes |
|----------|--------|-------|
| OpenAI | ✓ PASS | All checks passed |
| Telegram | ✓ PASS | All checks passed |
| Wix | ✗ FAIL | Cannot reach Wix APIs: HTTP Error 403: Forbidden |
| LinkedIn | ✗ FAIL | LinkedIn token invalid (HTTP 403). Re-authorize at LinkedIn Developer portal. |
| Facebook | ✗ FAIL | Page API failed: HTTP Error 400: Bad Request |
| Instagram | ✗ FAIL | IG API failed: HTTP Error 400: Bad Request |
| Threads | ✗ FAIL | Threads API call failed: HTTP Error 400: Bad Request |
| Google Sheets | ⚠ WARNING | Cannot test auth without 'cryptography' package. Run: pip install cryptography. Credentials JSON is valid. |
| Cloudinary | ⚠ WARNING | Cloudinary credentials work but logo not found at /tmp/Never-Blank-pipeline/assets/logo/never-blank-logo.png. Add logo before generating images. |

### OpenAI
- ✓ API key valid — models endpoint returned 200
- ✓ Model 'gpt-4o' available

### Telegram
- ✓ Bot identity (getMe) — @never_blank_publisher_bot
- ✓ Channel access (getChat) — type=channel title='Never Blank'
- ✓ Bot can post (admin check) — bot status in channel: administrator

### Wix
- ✗ Site access — blog categories: HTTP Error 403: Forbidden | site-list: HTTP Error 403: Forbidden

**Action required:** Cannot reach Wix APIs: HTTP Error 403: Forbidden

### LinkedIn
- ✗ Token valid — HTTP 403 — token expired or revoked

**Action required:** LinkedIn token invalid (HTTP 403). Re-authorize at LinkedIn Developer portal.

### Facebook
- ✗ Page access — HTTP Error 400: Bad Request

**Action required:** Page API failed: HTTP Error 400: Bad Request

### Instagram
- ✗ IG account access — HTTP Error 400: Bad Request

**Action required:** IG API failed: HTTP Error 400: Bad Request

### Threads
- ✗ Threads profile access — HTTP Error 400: Bad Request

**Action required:** Threads API call failed: HTTP Error 400: Bad Request

### Google Sheets
- ✓ Credentials JSON valid — service_account=never-blank-pipeline@never-blank.iam.gserviceaccount.com
- ✗ JWT signing (cryptography package) — pip install cryptography required for full auth check
- ✓ Spreadsheet URL format — ID=1vC-UzTpY1qv32Fg5C66BceRkgrnMFae-gVoYVKrxAdo

**Action required:** Cannot test auth without 'cryptography' package. Run: pip install cryptography. Credentials JSON is valid.

### Cloudinary
- ✓ Credentials valid (usage API) — plan=Free storage_used=242814315B
- ✓ Upload permission (test image) — uploaded to: https://res.cloudinary.com/df0lt7izx/image/upload/v1781919570/never-blank/audit-test/connectivity-test-1781919570.png
- ✓ Test asset cleanup — test image deleted
- ✗ Logo file exists — NOT FOUND: /tmp/Never-Blank-pipeline/assets/logo/never-blank-logo.png
- ✓ Output folder: images — /tmp/Never-Blank-pipeline/data/images
- ✓ Output folder: drafts — /tmp/Never-Blank-pipeline/data/drafts

**Action required:** Cloudinary credentials work but logo not found at /tmp/Never-Blank-pipeline/assets/logo/never-blank-logo.png. Add logo before generating images.

---
*Source: scripts/test_publishers.py*