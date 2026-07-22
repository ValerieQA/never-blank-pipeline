"""
Never Blank Strategy Engine — Content Planner (Phase 2/3).

Generates a monthly ContentPlan from:
  - Active Strategy
  - Extracted PatternRecords from market research
  - Publication calendar (weeks, dates)

Output: list[ContentPlanItem] + CSV + Markdown renderings.

Wiring:
  market_analyzer.py → PatternRecords
  loader.py         → Strategy
  content_planner.py → ContentPlanItem list
  → strategy/current/content_plan.json
  → strategy/current/content_plan.csv
  → strategy/current/content_plan.md
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from src.strategy.models import (
    Confidence,
    ContentPlanItem,
    ContentRole,
    PatternRecord,
    Strategy,
)
from src.strategy.validators import validate_content_plan
from src.utils.llm_client import chat, model_article
from src.utils.logger import get_logger

log = get_logger("strategy.content_planner")

_CURRENT_DIR = Path("strategy/current")

_SYSTEM = """You are a content strategist for Never Blank.

Never Blank publishes articles and posts that help small B2B service business owners recognize
the structural pattern of owner-dependent presence — and feel the commercial cost of it.

Never Blank sells itself through the quality of its analysis, not through direct advertising.

Your task: generate one content plan item for the given week and pattern.

The article arc is:
  Hook → Recognition → Tension → Market Observation → Investigation → Mechanism →
  Business Consequence → Reframe → Compound Presence Connection → Echo → Soft CTA

Rules:
- Hook must open a gap immediately. Not a topic statement — the point.
- Recognition: the reader must see their own situation, specifically.
- Mechanism: the structural cause, not the symptom.
- Reframe: must genuinely contest the obvious explanation.
- Compound Presence Connection: the semantic link between the mechanism and cumulative presence.
  Can be part of Reframe, or the transition to Echo. Not a required separate paragraph.
- Echo: the thought that remains. Specific to this article. Not a summary, not advice.
  If no strong Echo candidate exists, set echo to null — do not force a weak one.
  A null echo must be accompanied by a brief echo_omission_reason string.
- CTA: determined by cta_mode from the strategy. Never model discretion.
- Company/brand: use only as evidence, never as protagonist.
  The article must survive if the company name is removed.

Target: small B2B service businesses — agencies, consultants, MSPs.

Return JSON matching this exact structure:
{
  "topic": "",
  "working_title": "",
  "target_reader": "",
  "reader_problem": "",
  "market_signal": "",
  "pattern": "",
  "sales_objective": "",
  "main_argument": "",
  "hook": "",
  "recognition": "",
  "mechanism": "",
  "business_consequence": "",
  "reframe": "",
  "compound_presence_connection": "",
  "echo": null,
  "echo_omission_reason": null,
  "cta": "",
  "website_angle": "",
  "linkedin_angle": "",
  "instagram_angle": "",
  "facebook_angle": "",
  "threads_angle": "",
  "telegram_angle": "",
  "seo_keywords": [],
  "geo_questions": []
}"""


def _content_role_for_slot(week: int, slot: int) -> ContentRole:
    """Return the content role for a specific week/slot combination (slot = 0, 1, 2)."""
    roles_by_week = {
        1: [ContentRole.RECOGNITION, ContentRole.EDUCATION, ContentRole.RECOGNITION],
        2: [ContentRole.PROOF, ContentRole.REFRAME, ContentRole.RECOGNITION],
        3: [ContentRole.EDUCATION, ContentRole.OBJECTION, ContentRole.PROOF],
        4: [ContentRole.REFRAME, ContentRole.CONVERSION, ContentRole.RECOGNITION],
    }
    week_roles = roles_by_week.get(week, [ContentRole.RECOGNITION, ContentRole.EDUCATION, ContentRole.REFRAME])
    return week_roles[slot % len(week_roles)]


def generate_content_item(
    pattern: PatternRecord,
    strategy: Strategy,
    week: int,
    item_index: int,
    publication_date: Optional[date] = None,
    cta_mode: Optional[str] = None,
    slot: int = 0,
) -> ContentPlanItem:
    """
    Generate one ContentPlanItem from a PatternRecord and active Strategy.
    """
    effective_cta = cta_mode or strategy.primary_cta_intent or "none"
    role = _content_role_for_slot(week, slot)

    user = f"""Generate a content plan item for week {week} of the Never Blank content strategy.

ACTIVE STRATEGY:
  Strategy: {strategy.strategy_name}
  Selected problem: {strategy.selected_problem}
  Primary message: {strategy.primary_message}
  Desired reader realization: {strategy.desired_reader_realization}
  Compound Presence role: {strategy.compound_presence_role}
  CTA mode: {effective_cta}
  Presence Debt focus: {strategy.presence_debt_focus}

PATTERN TO USE:
  Pattern: {pattern.pattern_name}
  Small business situation: {pattern.small_business_situation}
  Underlying mechanism: {pattern.underlying_mechanism}
  Customer behavior: {pattern.customer_behavior}
  Business risk: {pattern.business_risk}
  Business opportunity: {pattern.business_opportunity}
  Sales relevance: {pattern.sales_relevance}
  Compound Presence relevance: {pattern.compound_presence_relevance}

CONTENT ROLE THIS WEEK: {role.value}
  recognition = make reader see their own situation
  education   = explain the mechanism clearly
  proof       = show the pattern with a concrete example or data
  reframe     = genuinely contest the obvious explanation
  objection   = address why owners don't act on this
  conversion  = move reader toward a concrete step

Generate the content plan item. Return JSON only."""

    raw = chat(_SYSTEM, user, json_mode=True, model=model_article())
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Content planner LLM returned invalid JSON: {exc}") from exc

    content_id = f"{strategy.strategy_id}-w{week}-{item_index:02d}"

    raw_echo = data.get("echo") or None  # treat "" and missing as null
    item = ContentPlanItem(
        content_id=content_id,
        week=week,
        publication_date=publication_date,
        strategy_id=strategy.strategy_id,
        content_role=role,
        source_pattern_id=pattern.pattern_id,
        topic=data.get("topic", pattern.pattern_name),
        working_title=data.get("working_title", ""),
        target_reader=data.get("target_reader", strategy.target_audience),
        reader_problem=data.get("reader_problem", pattern.small_business_situation),
        market_signal=data.get("market_signal", pattern.observed_signals[0] if pattern.observed_signals else ""),
        pattern=data.get("pattern", pattern.pattern_name),
        sales_objective=data.get("sales_objective", strategy.commercial_goal),
        main_argument=data.get("main_argument", ""),
        hook=data.get("hook", ""),
        recognition=data.get("recognition", ""),
        mechanism=data.get("mechanism", pattern.underlying_mechanism),
        business_consequence=data.get("business_consequence", pattern.business_risk),
        reframe=data.get("reframe", ""),
        compound_presence_connection=data.get("compound_presence_connection", ""),
        echo=raw_echo,
        echo_omission_reason=data.get("echo_omission_reason") or None,
        cta_mode=effective_cta,
        cta=data.get("cta", ""),
        website_angle=data.get("website_angle", ""),
        linkedin_angle=data.get("linkedin_angle", ""),
        instagram_angle=data.get("instagram_angle", ""),
        facebook_angle=data.get("facebook_angle", ""),
        threads_angle=data.get("threads_angle", ""),
        telegram_angle=data.get("telegram_angle", ""),
        seo_keywords=data.get("seo_keywords", []),
        geo_questions=data.get("geo_questions", []),
    )

    log.info("Content planner: generated item %s — %r", content_id, item.working_title[:60])
    return item


def generate_monthly_content_plan(
    strategy: Strategy,
    patterns: list[PatternRecord],
    items_per_week: int = 3,
    start_date: Optional[date] = None,
) -> list[ContentPlanItem]:
    """
    Generate a full monthly content plan (12–14 items across 4 weeks).

    Patterns are cycled across weeks. If fewer patterns than items,
    patterns are reused with different content roles.

    Args:
        strategy:       Active Strategy
        patterns:       PatternRecords from market_analyzer
        items_per_week: Target publications per week (default 3 = Mon/Wed/Fri)
        start_date:     First publication date (defaults to next Monday)
    """
    if not patterns:
        raise ValueError("Cannot generate content plan: no patterns provided")

    # Cap at 3 items/week — schedule is Mon/Wed/Fri only.
    if items_per_week > 3:
        log.warning("items_per_week=%d capped to 3 (Mon/Wed/Fri schedule)", items_per_week)
        items_per_week = 3

    if start_date is None:
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7
        start_date = today + timedelta(days=days_until_monday)

    cta_distribution = _build_cta_distribution(strategy.primary_cta_intent, items_per_week * 4)

    items: list[ContentPlanItem] = []
    cta_idx = 0
    expected_total = items_per_week * 4

    for week in range(1, 5):
        week_start = start_date + timedelta(weeks=week - 1)
        pub_dates = [week_start, week_start + timedelta(days=2), week_start + timedelta(days=4)]

        for slot in range(items_per_week):
            pattern_idx = len(items) % len(patterns)
            pattern     = patterns[pattern_idx]
            pub_date    = pub_dates[slot]
            cta_mode    = cta_distribution[cta_idx % len(cta_distribution)]
            cta_idx    += 1
            item_index  = len(items) + 1

            try:
                item = generate_content_item(
                    pattern=pattern,
                    strategy=strategy,
                    week=week,
                    item_index=item_index,
                    publication_date=pub_date,
                    cta_mode=cta_mode,
                    slot=slot,
                )
                items.append(item)
            except Exception as exc:
                log.error("Content planner: failed to generate item %d (week %d, slot %d): %s",
                          item_index, week, slot, exc)

    if len(items) < expected_total:
        raise ValueError(
            f"Content plan incomplete: expected {expected_total} items, generated {len(items)}. "
            "Check LLM errors above — some items failed generation."
        )

    validate_content_plan(items, strategy.strategy_id)
    log.info("Content plan generated: %d items for strategy %s", len(items), strategy.strategy_id)
    return items


def _build_cta_distribution(primary_intent: str, total: int) -> list[str]:
    """
    Build an interleaved CTA sequence.

    Primary intent appears on even positions (roughly every other item).
    Other modes fill odd positions in round-robin order.
    No mode runs more than twice consecutively.

    Example for primary_intent="reflection", total=12:
      reflection, none, reflection, diagnostic, reflection, none,
      reflection, example_request, reflection, none, reflection, diagnostic
    """
    primary = primary_intent or "none"
    others = [m for m in ["none", "reflection", "diagnostic", "example_request", "direct_conversation"]
              if m != primary]

    result: list[str] = []
    alt_idx = 0
    for i in range(total):
        if i % 2 == 0:
            result.append(primary)
        else:
            result.append(others[alt_idx % len(others)])
            alt_idx += 1
    return result


# ── Output renderers ───────────────────────────────────────────────────────────

def save_content_plan(items: list[ContentPlanItem], output_dir: Path = _CURRENT_DIR) -> None:
    """Save content plan as JSON, CSV, and Markdown."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _save_json(items, output_dir / "content_plan.json")
    _save_csv(items, output_dir / "content_plan.csv")
    _save_markdown(items, output_dir / "content_plan.md")
    log.info("Content plan saved to %s", output_dir)


def _save_json(items: list[ContentPlanItem], path: Path) -> None:
    data = [json.loads(item.model_dump_json()) for item in items]
    path.write_text(json.dumps(data, indent=2, default=str))


_CSV_COLUMNS = [
    "Date", "Week", "Strategy", "Content Role", "Topic", "Title",
    "Target Reader", "Reader Problem", "Market Signal", "Sales Objective",
    "Hook", "Recognition", "Mechanism", "Business Consequence", "Reframe",
    "Compound Presence Connection", "Echo", "CTA Mode", "CTA",
    "Website Angle", "LinkedIn Angle", "Instagram Angle",
    "Facebook Angle", "Threads Angle", "Telegram Angle",
    "SEO Keywords", "GEO Questions", "Status",
]


def _save_csv(items: list[ContentPlanItem], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for item in items:
            writer.writerow({
                "Date":                      str(item.publication_date or ""),
                "Week":                      item.week,
                "Strategy":                  item.strategy_id,
                "Content Role":              item.content_role.value,
                "Topic":                     item.topic,
                "Title":                     item.working_title,
                "Target Reader":             item.target_reader,
                "Reader Problem":            item.reader_problem,
                "Market Signal":             item.market_signal,
                "Sales Objective":           item.sales_objective,
                "Hook":                      item.hook,
                "Recognition":               item.recognition,
                "Mechanism":                 item.mechanism,
                "Business Consequence":      item.business_consequence,
                "Reframe":                   item.reframe,
                "Compound Presence Connection": item.compound_presence_connection,
                "Echo":                      item.echo,
                "CTA Mode":                  item.cta_mode,
                "CTA":                       item.cta,
                "Website Angle":             item.website_angle,
                "LinkedIn Angle":            item.linkedin_angle,
                "Instagram Angle":           item.instagram_angle,
                "Facebook Angle":            item.facebook_angle,
                "Threads Angle":             item.threads_angle,
                "Telegram Angle":            item.telegram_angle,
                "SEO Keywords":              ", ".join(item.seo_keywords),
                "GEO Questions":             " | ".join(item.geo_questions),
                "Status":                    item.status,
            })


def _save_markdown(items: list[ContentPlanItem], path: Path) -> None:
    lines = ["# Never Blank — Content Plan\n"]
    current_week = 0
    for item in items:
        if item.week != current_week:
            current_week = item.week
            lines.append(f"\n## Week {item.week}\n")
        date_str = str(item.publication_date) if item.publication_date else "TBD"
        lines.append(f"### {date_str} — {item.working_title}")
        lines.append(f"**Role:** {item.content_role.value} | **CTA mode:** {item.cta_mode}")
        lines.append(f"\n**Hook:** {item.hook}")
        lines.append(f"**Mechanism:** {item.mechanism}")
        lines.append(f"**Reframe:** {item.reframe}")
        lines.append(f"**Compound Presence:** {item.compound_presence_connection}")
        lines.append(f"**Echo:** {item.echo or '_(none — will be generated at article time)_'}")
        if item.cta:
            lines.append(f"**CTA:** {item.cta}")
        lines.append("")
    path.write_text("\n".join(lines))
