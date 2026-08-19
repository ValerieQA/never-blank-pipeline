"""The research label routes nothing it cannot uniquely name (Issue #121).

Live run 32197939633 died at intake on `unknown target audience 'founder'` —
before any research artifact, decision or reasoning existed. A useful
documented mechanism and an irrelevant corporate case were rejected
identically, for the same wrong reason.

These tests hold the corrected boundary: a coarse discovery label stops
routing, an explicit request still fails closed, and the component that
decides relevance keeps deciding it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.intake.content_assignment import ContentAssignment
from src.intake.audience_routing import (
    RESEARCH_DERIVED_ORIGINS,
    audience_request,
    is_research_derived,
)
from src.strategy.business_config import BusinessStrategyConfiguration
from src.strategy.execution_context import (
    StrategyExecutionContext,
    StrategyExecutionError,
)

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "strategy" / "current" / "business_strategy.json"


@pytest.fixture(scope="module")
def views():
    config = BusinessStrategyConfiguration.model_validate(json.loads(ACTIVE.read_text()))
    return StrategyExecutionContext.from_configuration(config)


def _assignment(audience, origin="jsonl") -> ContentAssignment:
    return ContentAssignment(
        assignment_id="sig-1",
        origin=origin,
        submitted_at=datetime.now(tz=timezone.utc).isoformat(),
        topic="A documented conversion mechanism",
        target_audience=audience,
        strategy_ref="never-blank-business-strategy",
        strategy_version="1.0",
    )


# ── CASE A — coarse external case reaches the reasoning boundary ─────────────

@pytest.mark.parametrize("label", ["founder", "unclassified", "owner", "creator"])
def test_a_coarse_research_label_stops_routing_instead_of_failing_intake(views, label):
    """The Invisalign case: a real mechanism, a label naming no configured audience."""

    assignment = _assignment(label)
    requested = audience_request(assignment, views.decision_lens_editorial)
    assert requested is None

    selection = views.decision_lens_editorial.select_audience(requested)
    assert selection.audience_id == "small-b2b-agencies"          # the configured default
    assert selection.selection_source == "configured-default"


def test_the_research_label_survives_as_source_metadata(views):
    """Not deleted, not rewritten, and never recorded as the selected audience."""

    assignment = _assignment("founder")
    selection = views.decision_lens_editorial.select_audience(
        audience_request(assignment, views.decision_lens_editorial)
    )
    assert assignment.target_audience == "founder"                # still attributable
    assert selection.audience_id != "founder"
    assert "founder" not in json.dumps(selection.model_dump(mode="json"))


def test_both_strategy_views_agree_so_intake_consistency_still_holds(views):
    requested = audience_request(_assignment("founder"), views.decision_lens_editorial)
    assert (views.decision_lens_editorial.select_audience(requested)
            == views.research.select_audience(requested))


# ── CASE B — a label that does name a configured audience still routes ───────

@pytest.mark.parametrize(
    "label,expected",
    [("agency", "small-b2b-agencies"), ("consultant", "independent-consultants")],
)
def test_a_matching_research_label_is_still_an_explicit_selection(views, label, expected):
    requested = audience_request(_assignment(label), views.decision_lens_editorial)
    assert requested == label                                     # no needless fallback
    selection = views.decision_lens_editorial.select_audience(requested)
    assert selection.audience_id == expected
    assert selection.selection_source == "assignment"


# ── CASE C — moving the boundary opens no relevance loophole ─────────────────

def test_reaching_decision_lens_is_not_relevance(views):
    """An unrelated corporate case may be evaluated — and still cannot PROCEED.

    The audience selection carries the configured problem and objections, the
    material a lens reasons *with*. It carries no verdict, and the accepted
    #58 rule still refuses a judgment resting on analogy alone.
    """

    selection = views.decision_lens_editorial.select_audience(
        audience_request(_assignment("unclassified"), views.decision_lens_editorial)
    )
    payload = json.dumps(selection.model_dump(mode="json")).upper()
    assert "PROCEED" not in payload
    for field in type(selection).model_fields:
        assert "verdict" not in field.lower() and "proceed" not in field.lower()

    contract = (ROOT / "src" / "editorial" / "decision_contract.py").read_text()
    assert "PROCEED requires direct configured-audience evidence" in contract
    assert "basis.basis_type is AudienceRelevanceBasisType.ANALOGY_ONLY" in contract


# ── CASE D — an explicit request still fails closed ──────────────────────────

@pytest.mark.parametrize("origin", ["api", "portal", "telegram", "manual"])
def test_an_explicit_unknown_audience_request_is_not_rescued(views, origin):
    assignment = _assignment("plumbers", origin=origin)
    requested = audience_request(assignment, views.decision_lens_editorial)
    assert requested == "plumbers"
    with pytest.raises(StrategyExecutionError):
        views.decision_lens_editorial.select_audience(requested)


def test_an_explicit_ambiguous_audience_request_is_not_rescued():
    raw = json.loads(ACTIVE.read_text())
    for audience in raw["audiences"][:2]:
        audience["selection_terms"] = list(audience["selection_terms"]) + ["shared term"]
    context = StrategyExecutionContext.from_configuration(
        BusinessStrategyConfiguration.model_validate(raw)
    )
    assignment = _assignment("shared term", origin="api")
    requested = audience_request(assignment, context.decision_lens_editorial)
    assert requested == "shared term"
    with pytest.raises(StrategyExecutionError):
        context.decision_lens_editorial.select_audience(requested)


def test_an_ambiguous_research_label_stops_routing_rather_than_failing():
    """Ambiguous does not uniquely name an audience either, so it is metadata."""

    raw = json.loads(ACTIVE.read_text())
    for audience in raw["audiences"][:2]:
        audience["selection_terms"] = list(audience["selection_terms"]) + ["shared term"]
    context = StrategyExecutionContext.from_configuration(
        BusinessStrategyConfiguration.model_validate(raw)
    )
    requested = audience_request(_assignment("shared term"), context.decision_lens_editorial)
    assert requested is None
    assert context.decision_lens_editorial.select_audience(requested).selection_source == (
        "configured-default"
    )


def test_only_the_research_transport_is_treated_as_metadata():
    assert RESEARCH_DERIVED_ORIGINS == frozenset({"jsonl"})
    assert is_research_derived("jsonl") is True
    for explicit in ("api", "portal", "telegram", "whatsapp", "manual"):
        assert is_research_derived(explicit) is False


# ── CASE E — one audience per run in Release 1 ───────────────────────────────

def test_release_1_evaluates_a_single_configured_audience(views):
    """A signal may interest several audiences; the run still resolves one."""

    assert len(views.decision_lens_editorial.audiences) >= 3
    selection = views.decision_lens_editorial.select_audience(
        audience_request(_assignment("founder"), views.decision_lens_editorial)
    )
    assert isinstance(selection.audience_id, str)
    assert selection.audience_id == views.decision_lens_editorial.default_audience_id


# ── absence and edge shapes ──────────────────────────────────────────────────

@pytest.mark.parametrize("empty", [None, "", "   "])
def test_no_label_requests_nothing(views, empty):
    assert audience_request(_assignment(empty), views.decision_lens_editorial) is None
