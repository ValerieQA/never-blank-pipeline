# Strategy History

This directory contains the complete record of all Never Blank strategy cycles.

**Rules:**
- Append-only. Previous strategy directories are never modified.
- Each strategy gets its own subdirectory named `{year}-{month}-{strategy-id}/`
- Every directory contains both machine-readable (JSON) and human-readable (MD) versions
- Weekly and monthly reviews are added during the cycle, not after

**Current strategy:** see `../current/`

## Directory structure

```
history/
  {year}-{month}-{strategy-id}/
    strategy.json           ← original strategy at launch
    strategy.md             ← human-readable version
    research_snapshot.json  ← market signals that informed the strategy
    content_plan.json       ← planned topics for this cycle
    content_plan.csv        ← same, for Excel/Sheets
    weekly_review_01.json
    weekly_review_01.md
    weekly_review_02.json
    weekly_review_02.md
    weekly_review_03.json
    weekly_review_03.md
    weekly_review_04.json
    weekly_review_04.md
    monthly_review.json     ← end-of-cycle full assessment
    monthly_review.md
    lessons.json            ← what to carry forward
```

## What gets recorded

- Original strategy and its rationale
- Market research that informed it
- Content plan with all planned topics, hooks, mechanisms, echoes
- Each week's performance and decision
- End-of-month full assessment
- Decision: CONTINUE / CONTINUE_WITH_ADJUSTMENTS / REPLACE_STRATEGY
- Lessons learned

This file is the audit trail that lets us understand why each strategy was chosen and what actually happened.
