"""
Creates a hardcoded sample draft in data/drafts/latest/ for testing publish.py
without running the full generation pipeline.

Usage:
    python scripts/create_fixture.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LATEST = Path(__file__).parent.parent / "data" / "drafts" / "latest"


BLOG_POST = """\
## Why Most Founders Misread Their Own Momentum

Momentum is one of the most misread signals in early-stage companies.

Not because founders lack intelligence — but because momentum *feels* a particular way, and that feeling is systematically misleading.

### The Pattern

When three customers sign in a week, it feels like traction. When a warm intro meeting turns into a second call, it feels like pipeline. When a feature ships, it feels like progress.

None of these are momentum. They're events.

### What Momentum Actually Is

Momentum is a second-order signal. It shows up in the *rate of change* of leading indicators — not the indicators themselves.

A company with momentum has: shorter sales cycles than last quarter, more inbound than outbound, referrals arriving without prompting. Not because things are happening — because the *rate* at which things happen is accelerating.

### The Practical Distinction

Before your next board update, ask: "Are we reporting events or rates?"

If you can't answer that, you're probably reporting events and calling them momentum.

That's not a failure. It's the default. The clarity comes from building the habit of asking the second question.
"""

LINKEDIN = """\
Most founders confuse events with momentum.

Three customer sign-ups in a week → event.
A warm intro turning into a second call → event.
A feature shipping → event.

Momentum is a second-order signal. It lives in the *rate of change* — not the change itself.

A company with real momentum has shorter sales cycles than last quarter. More inbound than outbound. Referrals arriving without prompting.

Before your next board update: are you reporting events or rates?

If you can't answer that, you're probably calling events momentum.

That's the default. Clarity comes from asking the second question.
"""

FACEBOOK = """\
Most founders misread their own momentum — and it's not a knowledge problem.

It's a signal problem.

Events feel like momentum: a customer signs up, a meeting converts, a feature ships. But momentum is a second-order signal. It shows up in *rates*, not occurrences.

Before your next update, ask: are we reporting events or rates?

That one question changes what you measure.
"""

INSTAGRAM = """\
Momentum isn't what happened. It's the rate at which things are happening.

Most founders are tracking events and calling it momentum. The shift is asking: are things speeding up, or just continuing?

That question changes everything you measure.

#founders #startups #businessstrategy #entrepreneurship #neverblank"""

THREADS = [
    "Most founders misread their own momentum.\n\nNot because they're wrong — because momentum *feels* a particular way that's systematically misleading.",
    "Events feel like momentum.\n\nA customer signs up. A meeting converts. A feature ships.\n\nNone of these are momentum. They're events.",
    "Momentum is a second-order signal.\n\nIt lives in the *rate of change* of leading indicators — not the indicators themselves.",
    "A company with momentum has shorter sales cycles than last quarter. More inbound than outbound. Referrals arriving without prompting.\n\nNot because things happen — because the *rate* accelerates.",
    "Before your next board update: are you reporting events or rates?\n\nIf you can't answer that — you're probably calling events momentum.\n\nThat's the default. Clarity comes from asking the second question.",
]

TELEGRAM = """\
Most founders misread their own momentum.

Events feel like traction: a customer signs up, a meeting converts, a feature ships. But momentum is a second-order signal — it lives in *rates*, not events.

Before your next board update: are you reporting events or rates?

That one question changes what you measure.
"""


def main() -> None:
    LATEST.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    files = {
        "metadata.json": {
            "generated_at":    now,
            "title":           "Why Most Founders Misread Their Own Momentum",
            "wix_slug":        "founders-misread-momentum",
            "observation_type": "paradox",
            "content_goal":    "challenge",
            "platforms":       ["wix", "linkedin", "facebook", "instagram", "threads", "telegram"],
            "manual_topic_id": None,
        },
        "blog_meta.json": {
            "title":            "Why Most Founders Misread Their Own Momentum",
            "meta_description": "The signals that feel like momentum are often noise. Here's the distinction that matters.",
            "hook_sentence":    "Momentum is one of the most misread signals in early-stage companies.",
            "wix_slug":         "founders-misread-momentum",
            "wix_category_id":  "35920a76-8a41-4645-aeb1-322ae240a57a",
            "wix_tags":         ["034e0b1e-c9c9-4940-97c2-af679d22acae", "64d4d6d7-a79c-48a5-9bfa-b62a75a2f278"],
        },
        "threads.json": {"sequence": THREADS},
        "content_matrix.json": {
            "topic_id":           "founders-misread-momentum",
            "topic":              "Momentum misreading",
            "core_idea":          "Founders confuse activity signals with momentum — rate data reveals what event counts hide.",
            "observation":        "Founders treat event counts as momentum proxies, but momentum is a rate signal, not an occurrence signal.",
            "mechanism":          "Individual events feel significant in isolation. Without rate context, the brain treats recency as frequency.",
            "cost_of_ignoring":   "Strategy built on event counts optimizes for noise. Revenue compounds in rate, not in spikes.",
            "strategic_question": "Are you tracking the rate of the pattern, or just whether it happened?",
            "hook_type":          "false_belief",
            "primary_hook":       "Momentum is one of the most misread signals in early-stage companies.",
            "supporting_points":  [
                "Event counts feel like momentum but measure recency, not pattern.",
                "Rate signals — conversion rate, return rate, signal frequency — compound invisibly.",
                "The founder who stops posting during a busy quarter loses the rate signal, not just the post.",
                "Clients read silence as low demand, regardless of your actual workload.",
            ],
            "visual_anchor":      "momentum as rate",
            "sales_angle":        "This is the kind of signal Never Blank is built to keep visible.",
            "soft_cta":           "The system you are watching here is the product.",
            "linkedin_angle":     "Business implication: founders who optimize for event counts make strategy on noise.",
            "instagram_angle":    "Minimal visual paired with the rate vs. events tension — image carries the concept.",
            "facebook_angle":     "Accessible reflection: what most people track versus what actually predicts outcomes.",
            "threads_angle":      "Provocation on momentum → mechanism → cost of optimizing for events → reframe on rate → final implication.",
            "telegram_angle":     "One signal note: momentum is a rate. Most founders are measuring events.",
            "stories_flow":       "Hook: are you measuring momentum or events? → Poll: which do you track? → Insight: rates outlast events → CTA: full article in bio",
            "created_at":         now,
        },
        "qc_report.json": {
            "overall_status": "GREEN",
            "checks": [],
            "rewrite_count": 0,
            "final_status": "GREEN",
            "quarantined": False,
            "quarantine_reason": "",
            "quarantine_path": None,
            "generated_at": now,
            "_note": "fixture — pre-approved content, QC manually cleared",
        },
    }
    text_files = {
        "blog_post.md":   BLOG_POST,
        "linkedin.txt":   LINKEDIN,
        "facebook.txt":   FACEBOOK,
        "instagram.txt":  INSTAGRAM,
        "telegram.txt":   TELEGRAM,
    }

    for name, data in files.items():
        (LATEST / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, content in text_files.items():
        (LATEST / name).write_text(content.strip(), encoding="utf-8")

    print(f"Fixture created in {LATEST}")
    for f in sorted(LATEST.iterdir()):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
