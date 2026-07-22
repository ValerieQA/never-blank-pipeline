# Never Blank — Evaluation Rules

**Status:** Production  
**Last updated:** 2026-07-22

---

## Analytics model

Every published piece generates an analytics record per platform.

```json
{
  "content_id": "",
  "platform": "",
  "published_at": "",
  "collected_at": "",
  "impressions": null,
  "reach": null,
  "views": null,
  "likes": null,
  "comments": null,
  "shares": null,
  "saves": null,
  "profile_visits": null,
  "new_followers": null,
  "link_clicks": null,
  "website_sessions": null,
  "cta_actions": null,
  "leads": null,
  "qualified_leads": null,
  "notes": ""
}
```

### Metric value semantics

- `0` — confirmed absence (data was collected and the value is zero)
- `null` — data unavailable from this platform's API
- `"not_collected"` — data exists but has not been retrieved yet

Never substitute `0` when data is missing. The distinction matters for strategy evaluation.

---

## Lead tracking

Leads are the primary KPI. Every analytics record has explicit `leads` and `qualified_leads` fields.

If no automated capture is available for a platform:
- The field remains `null` until manually populated
- The schema persists — it is not removed because the data isn't automated yet
- Weekly review explicitly flags unpopulated lead fields as requiring manual input

Lead sources to track (where automation is possible):
- LinkedIn DMs referencing a post
- Instagram message inquiries
- Telegram channel inquiries
- Website contact form submissions (via UTM or session source)
- Direct email mentions

---

## Weekly review decision logic

Input: analytics records for the past 7 days + cumulative since strategy start.

```
leads > 0
  → CONTINUE (with note on lead quality)

leads == 0 AND engagement_trend == "growing"
  → CONTINUE or ADJUST_EXECUTION (based on rate and recency)

leads == 0 AND engagement_trend == "flat"
  → ADJUST_EXECUTION (change hooks, topics, or CTA mode)

leads == 0 AND engagement_trend == "declining"
  → REVIEW_STRATEGY

insufficient_data (< 3 posts published)
  → CONTINUE (collect more data)
```

`engagement_trend` is computed from: saves + shares + substantive comments + CTA actions, compared to baseline (prior 4 weeks or platform average if no prior data).

---

## Monthly review decision logic

```
leads_total > 0 AND trend == "positive"
  → CONTINUE_STRATEGY

leads_total > 0 AND trend == "mixed"
  → CONTINUE_WITH_ADJUSTMENTS

leads_total == 0 AND early_signals_trend == "positive"
  → CONTINUE_WITH_ADJUSTMENTS or INSUFFICIENT_DATA (based on weeks elapsed)

leads_total == 0 AND early_signals_trend != "positive"
  → REPLACE_STRATEGY

data_coverage < 0.5 (fewer than half of planned posts published)
  → INSUFFICIENT_DATA
```

---

## Outlier detection

A post is flagged as outlier if:
- Impressions or saves > 2× the platform average for the strategy period
- Generated a direct lead or inquiry
- Received substantive comments showing genuine self-recognition (qualitative, not automated)

Outliers feed into next cycle's content plan — which angles, hooks, or mechanisms resonated most.

---

## Qualitative review (not automated)

Platform metrics do not capture:
- Whether Recognition landed (reader saw their own situation)
- Whether Echo worked (the thought remained)
- Whether comments showed genuine self-recognition vs. generic response
- Whether a named concept (e.g., Presence Debt, Compound Presence) was repeated back by readers

These require human or LLM-assisted reading of actual post comments and responses.

The monthly review template includes explicit fields for this qualitative assessment, clearly labeled as `qualitative_judgment`, not platform metrics. They can be filled manually or via an LLM pass over comments.

---

## Presence Debt concept tracking (Campaign 1, decision 21)

Presence Debt is the flagship named concept being tested in Campaign 1.  
Working definition: "the accumulated cost of the periods when a business disappears from customers' view and has to rebuild recognition, familiarity, and trust again."

Track per article that uses the concept:
- Was it introduced or referenced?
- Was it used in a hook, mechanism, reframe, or echo?
- Did any comments repeat the term or the concept without the term?
- Did it appear in any inbound inquiry?

Do not force Presence Debt into every article. Track its introduction and resonance separately.
