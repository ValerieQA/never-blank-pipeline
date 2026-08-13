"""
Characterization tests for research YAML prompts (Stage 1A).

These tests verify that:
1. All six research prompt YAML files load without error.
2. Loaded system text contains the expected key phrases that define
   Never Blank editorial territory (not exhaustive NLP, but meaningful
   content anchors that would catch a blank or wrong file).
3. Variable interpolation produces non-empty, non-placeholder output.
4. No variable remains unresolved as the literal string "{var_name}".
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils.config_loader import load_prompt


RESEARCH_PROMPTS = [
    "research/signal_selector",
    "research/signal_enrichment",
    "research/content_package",
    "research/score",
    "research/enrich",
    "research/angles",
]


@pytest.mark.parametrize("name", RESEARCH_PROMPTS)
def test_prompt_loads_without_error(name):
    prompt = load_prompt(name)
    assert isinstance(prompt, dict)
    assert "system" in prompt
    assert "user" in prompt


@pytest.mark.parametrize("name", RESEARCH_PROMPTS)
def test_prompt_system_is_non_empty(name):
    prompt = load_prompt(name)
    assert len(prompt["system"].strip()) > 50, f"{name}: system text too short"


# ── Content anchors — key phrases that must survive the YAML extraction ────────

def test_signal_selector_never_blank_identity():
    p = load_prompt("research/signal_selector")
    assert "Never Blank" in p["system"]
    assert "ALWAYS REJECT" in p["system"]
    assert "observable" in p["system"].lower()


def test_signal_selector_rejects_tips_articles():
    p = load_prompt("research/signal_selector")
    assert "tips" in p["system"].lower() or "X tips" in p["system"]


def test_signal_enrichment_schema_fields():
    p = load_prompt("research/signal_enrichment")
    assert "SIGNAL_TYPE" in p["system"]
    assert "discovery_confidence" in p["system"]
    assert "REGION" in p["system"]


def test_content_package_platform_keys():
    p = load_prompt("research/content_package")
    for platform in ("blog", "linkedin", "facebook", "instagram", "threads", "stories"):
        assert platform in p["system"], f"Missing platform key: {platform}"


def test_content_package_voice_rules():
    p = load_prompt("research/content_package")
    assert "Never Blank voice" in p["system"]
    assert "Forbidden" in p["system"]


def test_score_criteria_placeholder():
    p = load_prompt("research/score", {"criteria_desc": "- relevance (5 pts): relevant\n", "count": "3", "batch_text": "items"})
    assert "relevance (5 pts): relevant" in p["system"]
    assert "3" in p["user"]


def test_enrich_critical_rules():
    p = load_prompt("research/enrich")
    assert "Never invent" in p["system"]
    assert "REAL_COMPANY_EXAMPLE" in p["system"]
    assert "CONFIDENCE" in p["system"]


def test_angles_valid_audiences():
    p = load_prompt("research/angles")
    assert "founder" in p["system"]
    assert "POTENTIAL_HOOK" in p["system"]
    assert "NEVER_BLANK_ANGLE" in p["system"]


# ── Variable interpolation ─────────────────────────────────────────────────────

def test_signal_selector_interpolates_categories():
    cats = "visibility interruption, owner bottleneck"
    avoid = "generic AI hype"
    batch = "[0] Test headline | summary"
    p = load_prompt("research/signal_selector", {
        "categories": cats,
        "avoid": avoid,
        "batch_text": batch,
    })
    assert cats in p["system"]
    assert avoid in p["system"]
    assert batch in p["user"]


def test_signal_enrichment_interpolates_count():
    p = load_prompt("research/signal_enrichment", {
        "categories": "visibility interruption",
        "count": "7",
        "batch_text": "items here",
    })
    assert "7" in p["user"]


def test_enrich_interpolates_headline():
    headline = "Unique test headline XYZ"
    p = load_prompt("research/enrich", {
        "headline": headline,
        "source_name": "Test Source",
        "source_url": "https://example.com",
        "source_date": "2026-08-05",
        "raw_summary": "A summary.",
        "signal_type": "visibility interruption",
        "region": "US",
        "industry": "retail",
    })
    assert headline in p["user"]


def test_angles_interpolates_signal_fields():
    p = load_prompt("research/angles", {
        "headline": "Test headline",
        "core_fact": "Fact here",
        "core_tension": "Tension here",
        "real_company_example": "Acme Corp",
        "business_lesson": "Lesson here",
        "why_this_case_is_interesting": "Because interesting",
        "signal_type": "owner bottleneck",
    })
    assert "Acme Corp" in p["user"]
    assert "owner bottleneck" in p["user"]


def test_content_package_interpolates_all_fields():
    p = load_prompt("research/content_package", {
        "headline": "A strong headline",
        "core_tension": "Tension",
        "business_lesson": "Lesson",
        "core_fact": "Fact",
        "real_company_example": "BrandCo",
        "never_blank_angle": "Angle",
        "possible_signature_line": "Signature",
        "potential_hook": "Hook text",
        "target_audience": "founder",
        "selected_audience_id": "operators",
        "selected_audience_problem": "Problem",
        "business_positioning": "Positioning",
        "content_territories": "[\"Territory\"]",
        "preferred_claims": "[\"Claim\"]",
        "restrictions": "[\"Restriction\"]",
    })
    assert "BrandCo" in p["user"]
    assert "Hook text" in p["user"]


# ── No unresolved placeholders after full variable injection ───────────────────

_UNRESOLVED_RE = re.compile(r"\{[a-z_]+\}")


def test_no_unresolved_placeholders_after_full_injection():
    """All prompts with their required variables must leave no {var} strings."""
    cases = [
        ("research/signal_selector", {
            "categories": "cat1, cat2",
            "avoid": "avoid1",
            "batch_text": "[0] item",
        }),
        ("research/signal_enrichment", {
            "categories": "cat1",
            "count": "2",
            "batch_text": "items",
        }),
        ("research/score", {
            "criteria_desc": "- crit: desc",
            "count": "1",
            "batch_text": "signal",
        }),
        ("research/enrich", {
            "headline": "H", "source_name": "S", "source_url": "U",
            "source_date": "D", "raw_summary": "R", "signal_type": "T",
            "region": "US", "industry": "I",
        }),
        ("research/angles", {
            "headline": "H", "core_fact": "F", "core_tension": "T",
            "real_company_example": "E", "business_lesson": "L",
            "why_this_case_is_interesting": "W", "signal_type": "S",
        }),
        ("research/content_package", {
            "headline": "H", "core_tension": "T", "business_lesson": "L",
            "core_fact": "F", "real_company_example": "E",
            "never_blank_angle": "A", "possible_signature_line": "P",
            "potential_hook": "K", "target_audience": "founder",
            "selected_audience_id": "operators",
            "selected_audience_problem": "Problem",
            "business_positioning": "Positioning",
            "content_territories": "[]", "preferred_claims": "[]",
            "restrictions": "[]",
        }),
    ]
    for name, variables in cases:
        p = load_prompt(name, variables)
        for field in ("system", "user"):
            text = p.get(field, "")
            unresolved = _UNRESOLVED_RE.findall(text)
            assert not unresolved, (
                f"{name}.{field} has unresolved placeholders after injection: {unresolved}"
            )
