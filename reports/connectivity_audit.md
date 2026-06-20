# Never Blank — Publisher Connectivity Audit

Generated: 2026-06-20T01:59:02.537976+00:00

## Secrets
| Secret | Status | Preview |
|--------|--------|---------|
| `NB_OPENAI_API_KEY` | ✓ | sk-p...lzUA (164 chars) |
| `NB_WIX_API_KEY` | ✗ MISSING |  |
| `NB_WIX_SITE_ID` | ✗ MISSING |  |
| `NB_LINKEDIN_ACCESS_TOKEN` | ✗ MISSING |  |
| `NB_META_USER_TOKEN` | ✗ MISSING |  |
| `NB_META_IG_USER_ID` | ✗ MISSING |  |
| `NB_META_FB_PAGE_ID` | ✗ MISSING |  |
| `NB_META_FB_PAGE_TOKEN` | ✗ MISSING |  |
| `NB_THREADS_ACCESS_TOKEN` | ✗ MISSING |  |
| `NB_TELEGRAM_BOT_TOKEN` | ✗ MISSING |  |
| `NB_TELEGRAM_CHANNEL_ID` | ✗ MISSING |  |
| `NB_CLOUDINARY_CLOUD_NAME` | ✗ MISSING |  |
| `NB_CLOUDINARY_API_KEY` | ✗ MISSING |  |
| `NB_CLOUDINARY_API_SECRET` | ✗ MISSING |  |
| `NB_GOOGLE_SHEETS_CREDENTIALS_JSON` | ✗ MISSING |  |
| `NB_GOOGLE_SHEET_ID` | ✗ MISSING |  |

## Platform Results
| Platform | Status | Failure Type | Notes |
|----------|--------|--------------|-------|
| OpenAI | ✓ PASS | — | All checks passed |
| Telegram | ✗ FAIL |  | Missing secret: NB_TELEGRAM_BOT_TOKEN |

### OpenAI
- ✓ API key valid — models endpoint returned 200
- ✓ Model 'gpt-4o' available

---
*Source: scripts/test_publishers.py*