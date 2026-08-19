"""The research → strategy audience boundary (exposed by live run 32197939633).

The classifier used to answer "founder" whenever it could not classify a
signal. That is not a truthful default: more than one configured Never Blank
audience is founder-led, so the term claimed a specificity the classifier never
had — and it silently became the audience of 241 of 244 queued signals, none of
which could then pass canonical intake.

The correction keeps research generic and lets configuration decide what its
vocabulary resolves to. These tests hold both halves, and the line between
them: resolving an audience says which configured domain *may evaluate* a
signal. It says nothing about relevance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.research.angles import UNCLASSIFIED_AUDIENCE, VALID_AUDIENCES
from src.strategy.business_config import BusinessStrategyConfiguration
from src.strategy.execution_context import (
    StrategyExecutionContext,
    StrategyExecutionError,
)

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "strategy" / "current" / "business_strategy.json"
ALTERNATE = ROOT / "tests" / "fixtures" / "business_strategy_alternate.json"


def _context(path: Path) -> StrategyExecutionContext:
    config = BusinessStrategyConfiguration.model_validate(json.loads(path.read_text()))
    return StrategyExecutionContext.from_configuration(config)


@pytest.fixture(scope="module")
def active() -> StrategyExecutionContext:
    return _context(ACTIVE)


def _classify(raw: object) -> str:
    """The classifier's normalisation, without calling the model."""

    return raw if raw in VALID_AUDIENCES else UNCLASSIFIED_AUDIENCE


# ── 1–5. the classifier no longer invents specificity ────────────────────────

@pytest.mark.parametrize("raw", ["b2b_saas", "enterprise", "", None, 42, "FOUNDERS!"])
def test_unsupported_output_becomes_unclassified_never_founder(raw):
    assert _classify(raw) == "unclassified"
    assert _classify(raw) != "founder"


def test_classifier_failure_becomes_unclassified(monkeypatch):
    """A model error must not be laundered into a real audience label."""

    import scripts.research.angles as angles

    def _boom(*a, **kw):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(angles, "chat", _boom)
    out = angles.generate_angles({"SIGNAL_ID": "s1", "HEADLINE": "h"})
    assert out["TARGET_AUDIENCE"] == UNCLASSIFIED_AUDIENCE


@pytest.mark.parametrize("term", ["agency", "consultant", "managed_service_provider"])
def test_valid_generic_classifications_are_preserved(term):
    assert _classify(term) == term
    assert term in VALID_AUDIENCES


# ── 6–8. the intended intersections resolve, uniquely ────────────────────────

@pytest.mark.parametrize(
    "term,expected",
    [
        ("agency", "small-b2b-agencies"),
        ("consultant", "independent-consultants"),
        ("managed_service_provider", "managed-service-providers"),
    ],
)
def test_generic_terms_resolve_to_their_configured_audience(active, term, expected):
    assert active.research.select_audience(term).audience_id == expected
    # and the two strategy views must agree, as canonical intake requires
    assert active.decision_lens_editorial.select_audience(term).audience_id == expected


# ── 9–13. everything else still fails closed ─────────────────────────────────

def test_founder_does_not_resolve_although_audiences_are_founder_led(active):
    """Two configured audiences are named "Founder-led …".

    The taxonomy term is strictly less specific than the identity it would
    have to select, so it must resolve to nothing rather than pick one.
    """

    names = [a.name for a in active.research.audiences]
    assert sum("founder-led" in n.casefold() for n in names) >= 2
    with pytest.raises(StrategyExecutionError):
        active.research.select_audience("founder")


@pytest.mark.parametrize("term", ["owner", "service_business", "small_team", "creator"])
def test_broad_terms_receive_no_invented_mapping(active, term):
    with pytest.raises(StrategyExecutionError):
        active.research.select_audience(term)


def test_unclassified_fails_closed_at_canonical_intake(active):
    with pytest.raises(StrategyExecutionError):
        active.research.select_audience(UNCLASSIFIED_AUDIENCE)


def test_an_unrelated_audience_still_fails_closed(active):
    with pytest.raises(StrategyExecutionError):
        active.research.select_audience("plumbers")


def test_ambiguous_configuration_still_fails_closed():
    """Strictness is unchanged: two matches is as fatal as none."""

    raw = json.loads(ACTIVE.read_text())
    for audience in raw["audiences"][:2]:
        audience["selection_terms"] = list(audience["selection_terms"]) + ["shared term"]
    config = BusinessStrategyConfiguration.model_validate(raw)
    context = StrategyExecutionContext.from_configuration(config)
    with pytest.raises(StrategyExecutionError):
        context.research.select_audience("shared term")


# ── 15. a contrasting profile uses the same mechanism, no code change ────────

def test_a_contrasting_profile_resolves_its_own_vocabulary():
    alternate = _context(ALTERNATE)
    declared = alternate.research.audiences[0]
    assert declared.audience_id != "small-b2b-agencies"
    resolved = alternate.research.select_audience(declared.selection_terms[0])
    assert resolved.audience_id == declared.audience_id
    # and this profile does not answer to the active profile's vocabulary
    with pytest.raises(StrategyExecutionError):
        alternate.research.select_audience("agency")


# ── 16–17. resolution is not relevance ───────────────────────────────────────

def test_audience_matching_alone_cannot_make_decision_lens_proceed(active):
    """Domain admission and relevance are different questions.

    A resolved audience carries the configured problem, decision factors and
    objections — the material a lens reasons *with*. It carries no verdict,
    and nothing in the selection can produce one.
    """

    selection = active.research.select_audience("agency")
    assert selection.audience_id == "small-b2b-agencies"
    for field in type(selection).model_fields:
        assert "proceed" not in field.lower()
        assert "verdict" not in field.lower()
    assert "PROCEED" not in json.dumps(selection.model_dump(mode="json")).upper()


def test_analogy_only_remains_non_qualifying():
    """Untouched by this correction, and asserted so it stays that way."""

    contract = (ROOT / "src" / "editorial" / "decision_contract.py").read_text()
    assert "PROCEED requires direct configured-audience evidence" in contract
    assert (
        "basis.basis_type is AudienceRelevanceBasisType.ANALOGY_ONLY"
        in contract
    )
    assert "analogy-only relevance cannot claim a documented direct consequence" in contract


# ── 18. the historical queue is left alone ───────────────────────────────────

def test_no_historical_queue_migration_occurs():
    """The 241 legacy `founder` signals are evidence, not a migration target."""

    rows = [
        json.loads(line)
        for line in (ROOT / "data" / "research" / "signals_active.jsonl")
        .read_text().splitlines() if line.strip()
    ]
    legacy = [r for r in rows if r.get("TARGET_AUDIENCE") == "founder"]
    assert legacy, "the historical signals must remain exactly as recorded"
    # they stay unusable by strict intake rather than being reclassified
    context = _context(ACTIVE)
    with pytest.raises(StrategyExecutionError):
        context.research.select_audience(legacy[0]["TARGET_AUDIENCE"])


# ── regression for the original failure class ────────────────────────────────

def test_a_freshly_classified_signal_crosses_the_boundary_that_rejected_it(active):
    """Run 32197939633 died here, with no signal-specific exception added.

    This asserts only that a correctly classified signal reaches the far side
    of audience resolution. Whether such a signal PROCEEDs is a separate
    question for Decision Lens, decided on its own evidence.
    """

    for term in ("agency", "consultant", "managed_service_provider"):
        editorial = active.decision_lens_editorial.select_audience(term)
        research = active.research.select_audience(term)
        assert editorial == research          # the equality canonical intake checks
        assert editorial.selection_source == "assignment"
