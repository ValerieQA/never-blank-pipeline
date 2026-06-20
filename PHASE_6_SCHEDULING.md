# Phase 6 — Scheduling

## Schedule

| Field | Value |
|-------|-------|
| Timezone | America/New_York |
| Days | Monday, Wednesday, Friday |
| Time | 06:00 ET |
| Jitter | 0 minutes (MVP) |

## Pipeline Order

1. Generate content + QC (`scripts/generate.py --qc`)
2. Generate + upload image (`scripts/generate_image.py --upload`)
3. Publish Wix (required — provides article URL)
4. Publish LinkedIn, Facebook, Instagram, Threads (independent; any failure doesn't block others)
5. Publish Telegram (skipped if Wix failed — appends article URL)

## Fallback Rules

| Scenario | Behavior |
|----------|----------|
| Content generation fails | Abort cycle |
| QC fails (ORANGE/quarantined) | Abort cycle |
| Image generation fails | Continue without image |
| Wix fails | Skip Telegram; proceed with other social channels |
| Any social channel fails | Continue remaining channels |

## Files

| File | Purpose |
|------|---------|
| `config/schedule.yaml` | Schedule config — timezone, days, time, channel order, fallback rules |
| `scripts/scheduled_publish.py` | Pipeline runner with schedule check |
| `.github/workflows/scheduled_publish.yml` | GitHub Actions cron workflow |

## How to Run

### Check if a publish is due
```bash
python scripts/scheduled_publish.py --check-only
```

### Force immediate publish (bypasses schedule)
```bash
python scripts/scheduled_publish.py --force
```

### Normal scheduled run (exits cleanly if not due)
```bash
python scripts/scheduled_publish.py
```

### Trigger via GitHub Actions manually
GitHub → Actions → "Scheduled Publisher" → Run workflow
- Leave `force` unchecked for a schedule-respecting run
- Check `force` to publish immediately
- Check `check_only` to only inspect whether a run is due

## Cron Configuration

GitHub Actions cron runs in UTC. Two triggers cover both EST and EDT:

```
0 10 * * 1,3,5   # 10:00 UTC = 06:00 EDT (summer)
0 11 * * 1,3,5   # 11:00 UTC = 06:00 EST (winter)
```

The Python script performs the authoritative check using `zoneinfo` and
`America/New_York`. If the current time is outside the 30-minute publish
window, the run exits cleanly with no side effects.

## Verifying the Next Scheduled Run

```bash
python scripts/scheduled_publish.py --check-only
```

On a non-publish day or outside the window, output will be:
```
Due check: Not a publish day (Tuesday); scheduled days: monday, wednesday, friday
Status: NOT DUE
```

On a publish day within the window:
```
Due check: Due — Monday 2026-06-22 06:03 EDT is within the publish window
Status: DUE
```

## Report Location

After each scheduled run:
- `reports/scheduled_publish_report.json`
- `reports/scheduled_publish_report.md`

Also available as GitHub Actions artifacts (retained 90 days).
