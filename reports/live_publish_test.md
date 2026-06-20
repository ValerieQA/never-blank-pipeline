# Never Blank — Phase 5D Live Publish Test

Run ID:    `20260620_183113`  
Generated: 2026-06-20T18:32:03+00:00  
Preflight: ✓ PASS  
Wave 1:    ✓ PASS  

## Results

| Platform | Status | External ID | URL |
|----------|--------|-------------|-----|
| wix | PUBLISHED | 3adb55fc-19a2-4477-ab90-9b57daf0e01e | Wix dashboard |
| telegram | PUBLISHED | 7 | [t.me/never_blank_inneros/7](https://t.me/never_blank_inneros/7) |
| facebook | PUBLISHED | 1219637131228622_122110184097356169 | [link](https://www.facebook.com/1219637131228622_122110184097356169) |
| instagram | PUBLISHED | 17860586622641229 | [instagram.com/p/DZ0V48Bjk8o/](https://www.instagram.com/p/DZ0V48Bjk8o/) |
| linkedin | FAILED | — | — |
| threads | PUBLISHED | 18125757235646787 | [threads.net/t/18125757235646787](https://www.threads.net/t/18125757235646787) |

## Errors

- **linkedin**: Cannot resolve LinkedIn author URN.
  `w_member_social` scope does not expose user ID via token introspection.
  **Fix**: Add `NB_LINKEDIN_AUTHOR_URN` to GitHub Secrets.
  How to find: LinkedIn Developer Portal → Tools → OAuth 2.0 tools → generate token with `r_basicprofile` scope → response includes member URN.

## Summary

- Published: 5 — wix, telegram, facebook, instagram, threads
- Failed:    1 — linkedin
- Skipped:   0 — none

**Phase 6 scheduling safe to start: CONDITIONAL**
5/6 channels working. LinkedIn requires one manual step (NB_LINKEDIN_AUTHOR_URN secret).
Phase 6 can start without LinkedIn, or after LinkedIn secret is added.

*Source: scripts/live_publish_test.py*
