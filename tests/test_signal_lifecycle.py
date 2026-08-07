"""
Stage 1.5 — Signal Lifecycle Contract Tests.

Coverage:
  - All 8 boolean combinations for derive_* functions
  - @property consistency after mutation
  - force_override does not rewrite ARTICLE_READY
  - legacy dict string types (not bool)
  - SOURCE_PREMISE_VERIFIED tri-state preservation
  - to_editorial blocks rejected, passes admitted/override
  - EditorialContext rejects invalid admission_status
  - __post_init__ validation (confidence, source_premise_verified)
  - from_dict: old records with None fields
  - from_dict: BUSINESS_RESPONSES_OBSERVED list→str normalization
  - from_dict: score fields str→int normalization
  - to_dict write-then-read round-trip (typed fields)
  - passthrough: unknown keys preserved in to_dict, absent in adapters
  - selection gate equivalence: 242 real JSONL records
  - preflight equivalence: 242 real JSONL records
  - RECOMMENDED_FOR_ARTICLE alias verified against real data
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.lifecycle.signal_lifecycle import (
    EditorialContext,
    ResearchContext,
    _KNOWN_JSONL_KEYS,
    derive_admission_status,
    derive_factual_readiness,
)

SIGNALS_ACTIVE = Path("data/research/signals_active.jsonl")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rc(**overrides) -> ResearchContext:
    defaults = dict(
        signal_id="test_id",
        headline="Test Headline",
        signal_type="trend",
        region="Global",
        industry="Tech",
        source_name="Test Source",
        source_url="https://example.com",
        source_date="2026-08-06",
        date_found="2026-08-06",
        article_ready=True,
        source_premise_verified="true",
        core_fact="Core fact text",
        confidence="high",
        source_for_case="https://example.com/source",
        real_company_example="Acme Corp",
        outcome_if_known="Positive outcome",
        did_it_work="Yes",
        evidence_of_outcome="Evidence text",
        source_quality="high",
        notes="",
        score_recommended=True,
        article_readiness_score=8,
        signal_strength="high",
        channel_fit_score=7,
        discussion_potential="medium",
        score_reason="Strong signal",
        core_tension="Core tension",
        business_lesson="Business lesson",
        why_this_case_is_interesting="Why interesting",
        why_it_matters_to_business="Why it matters",
        business_responses_observed="Various responses",
        problem_faced="Problem description",
        response_taken="Response taken",
        counter_example="Counter example",
        time_horizon="6 months",
        interesting_question="Interesting question?",
        never_blank_angle="Never blank angle",
        possible_signature_line="Signature line",
        potential_hook="Hook text",
        target_audience="founder",
        primary_channel="linkedin",
        linkedin_angle="LinkedIn angle",
        blog_angle="Blog angle",
        threads_angle="Threads angle",
        story_angle="Story angle",
        force_override=False,
        approved_override_raw="",
        raw_summary="Raw summary",
        discovery_confidence="high",
    )
    defaults.update(overrides)
    return ResearchContext(**defaults)


# ---------------------------------------------------------------------------
# derive_* functions — all 8 combinations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("article_ready,score_rec,force_override,exp_fr,exp_as", [
    (False, False, False, "insufficient", "rejected"),
    (False, False, True,  "insufficient", "force_override"),
    (False, True,  False, "insufficient", "rejected"),
    (False, True,  True,  "insufficient", "force_override"),
    (True,  False, False, "ready",        "rejected"),
    (True,  False, True,  "ready",        "force_override"),
    (True,  True,  False, "ready",        "admitted"),
    (True,  True,  True,  "ready",        "force_override"),
])
def test_derive_all_8_combinations(
    article_ready, score_rec, force_override, exp_fr, exp_as
):
    assert derive_factual_readiness(article_ready) == exp_fr
    assert derive_admission_status(article_ready, score_rec, force_override) == exp_as


# ---------------------------------------------------------------------------
# @property consistency after mutation
# ---------------------------------------------------------------------------

def test_properties_consistent_after_mutation():
    rc = _make_rc(article_ready=True, score_recommended=True, force_override=False)
    assert rc.factual_readiness == "ready"
    assert rc.admission_status == "admitted"

    rc.article_ready = False
    assert rc.factual_readiness == "insufficient"
    assert rc.admission_status == "rejected"  # not stale "admitted"

    rc.force_override = True
    assert rc.admission_status == "force_override"  # override now active


# ---------------------------------------------------------------------------
# force_override does NOT rewrite ARTICLE_READY
# ---------------------------------------------------------------------------

def test_force_override_does_not_rewrite_article_ready():
    rc = _make_rc(article_ready=False, score_recommended=False, force_override=True)
    assert rc.admission_status == "force_override"

    d = rc.to_legacy_dict()
    assert d["ARTICLE_READY"] == "false"
    assert d["FORCE_PUBLISH_OVERRIDE"] == "true"


def test_admitted_signal_article_ready_true():
    rc = _make_rc(article_ready=True, score_recommended=True, force_override=False)
    d = rc.to_legacy_dict()
    assert d["ARTICLE_READY"] == "true"
    assert d["FORCE_PUBLISH_OVERRIDE"] == "false"


# ---------------------------------------------------------------------------
# Legacy dict types — strings, not booleans
# ---------------------------------------------------------------------------

def test_legacy_dict_values_are_strings_not_booleans():
    rc = _make_rc(article_ready=True, force_override=False)
    d = rc.to_legacy_dict()
    assert isinstance(d["ARTICLE_READY"], str)
    assert isinstance(d["FORCE_PUBLISH_OVERRIDE"], str)
    assert isinstance(d["SOURCE_PREMISE_VERIFIED"], str)


# ---------------------------------------------------------------------------
# SOURCE_PREMISE_VERIFIED tri-state preserved exactly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spv", ["true", "false", "unknown"])
def test_source_premise_verified_tristate_preserved(spv):
    rc = _make_rc(source_premise_verified=spv)
    assert rc.to_legacy_dict()["SOURCE_PREMISE_VERIFIED"] == spv
    assert rc.to_dict()["SOURCE_PREMISE_VERIFIED"] == spv


# ---------------------------------------------------------------------------
# to_editorial: blocks rejected, passes admitted and force_override
# ---------------------------------------------------------------------------

def test_to_editorial_blocks_rejected():
    rc = _make_rc(article_ready=False, score_recommended=False, force_override=False)
    assert rc.admission_status == "rejected"
    with pytest.raises(ValueError, match="admission_status='rejected'"):
        rc.to_editorial({})


def test_to_editorial_admitted_passes():
    rc = _make_rc(article_ready=True, score_recommended=True, force_override=False)
    ec = rc.to_editorial({"pkg_key": "value"})
    assert ec.admission_status == "admitted"
    assert ec.article_ready is True


def test_to_editorial_force_override_passes_with_insufficient_evidence():
    rc = _make_rc(article_ready=False, score_recommended=False, force_override=True)
    ec = rc.to_editorial({})
    assert ec.admission_status == "force_override"
    assert ec.article_ready is False  # factual readiness unchanged


def test_to_editorial_preserves_article_ready_false():
    """force_override admitted signal: ARTICLE_READY stays false in legacy dict."""
    rc = _make_rc(article_ready=False, force_override=True)
    ec = rc.to_editorial({})
    d = ec.to_legacy_dict()
    assert d["ARTICLE_READY"] == "false"
    assert d["FORCE_PUBLISH_OVERRIDE"] == "true"


# ---------------------------------------------------------------------------
# EditorialContext: rejects invalid admission_status
# ---------------------------------------------------------------------------

def test_editorial_context_rejects_rejected_status():
    rc = _make_rc(article_ready=True, score_recommended=True)
    with pytest.raises(ValueError, match="admission_status"):
        EditorialContext(
            signal_id="x",
            headline="x",
            factual_readiness="ready",
            admission_status="rejected",
            force_override=False,
            article_ready=True,
            source_premise_verified="true",
            approved_override_raw="",
            core_fact="",
            core_tension="",
            business_lesson="",
            real_company_example=None,
            outcome_if_known="",
            problem_faced="",
            response_taken="",
            why_this_case_is_interesting="",
            counter_example="",
            never_blank_angle="",
            possible_signature_line="",
            potential_hook="",
            target_audience="founder",
            linkedin_angle="",
            blog_angle="",
            threads_angle="",
            story_angle="",
            source_name="",
            source_url="",
            industry="",
        )


# ---------------------------------------------------------------------------
# __post_init__ validation
# ---------------------------------------------------------------------------

def test_post_init_rejects_invalid_confidence():
    with pytest.raises(ValueError, match="Invalid confidence"):
        _make_rc(confidence="maybe")


def test_post_init_rejects_invalid_source_premise_verified():
    with pytest.raises(ValueError, match="Invalid source_premise_verified"):
        _make_rc(source_premise_verified="yes")


@pytest.mark.parametrize("confidence", ["high", "medium", "low"])
def test_post_init_accepts_valid_confidence(confidence):
    rc = _make_rc(confidence=confidence)
    assert rc.confidence == confidence


@pytest.mark.parametrize("spv", ["true", "false", "unknown"])
def test_post_init_accepts_valid_spv(spv):
    rc = _make_rc(source_premise_verified=spv)
    assert rc.source_premise_verified == spv


# ---------------------------------------------------------------------------
# from_dict: old records with None fields
# ---------------------------------------------------------------------------

def test_from_dict_old_record_all_none_fields():
    """Pre-Stage-1A records: ARTICLE_READY absent → False; SPV absent → 'unknown'."""
    record = {"SIGNAL_ID": "abc123", "HEADLINE": "Test headline"}
    rc = ResearchContext.from_dict(record)
    assert rc.article_ready is False
    assert rc.score_recommended is False
    assert rc.force_override is False
    assert rc.source_premise_verified == "unknown"
    assert rc.factual_readiness == "insufficient"
    assert rc.admission_status == "rejected"
    assert rc.confidence == "low"
    assert rc.target_audience == "founder"
    assert rc.outcome_if_known == "unknown"
    assert rc.did_it_work == "unknown"


def test_from_dict_normalizes_business_responses_observed_list():
    record = {
        "SIGNAL_ID": "x",
        "BUSINESS_RESPONSES_OBSERVED": ["response A", "response B"],
    }
    rc = ResearchContext.from_dict(record)
    assert isinstance(rc.business_responses_observed, str)
    parsed = json.loads(rc.business_responses_observed)
    assert parsed == ["response A", "response B"]


def test_from_dict_normalizes_score_fields_to_int():
    record = {
        "SIGNAL_ID": "x",
        "ARTICLE_READINESS_SCORE": "8",
        "CHANNEL_FIT_SCORE": "7",
    }
    rc = ResearchContext.from_dict(record)
    assert rc.article_readiness_score == 8
    assert isinstance(rc.article_readiness_score, int)
    assert rc.channel_fit_score == 7
    assert isinstance(rc.channel_fit_score, int)


def test_from_dict_score_fields_none_default_zero():
    record = {"SIGNAL_ID": "x", "ARTICLE_READINESS_SCORE": None}
    rc = ResearchContext.from_dict(record)
    assert rc.article_readiness_score == 0


def test_from_dict_spv_none_becomes_unknown():
    rc = ResearchContext.from_dict({"SIGNAL_ID": "x", "SOURCE_PREMISE_VERIFIED": None})
    assert rc.source_premise_verified == "unknown"


def test_from_dict_approved_override_true_sets_force_override():
    rc = ResearchContext.from_dict({"SIGNAL_ID": "x", "APPROVED_OVERRIDE": "true"})
    assert rc.force_override is True
    assert rc.approved_override_raw == "true"


def test_from_dict_force_publish_override_true_sets_force_override():
    rc = ResearchContext.from_dict({"SIGNAL_ID": "x", "FORCE_PUBLISH_OVERRIDE": "true"})
    assert rc.force_override is True


# ---------------------------------------------------------------------------
# to_dict write-then-read round-trip (typed fields)
# ---------------------------------------------------------------------------

def test_to_dict_roundtrip_typed_fields():
    """New ResearchContext can round-trip through JSONL without losing typed data."""
    rc = _make_rc(
        article_ready=True,
        score_recommended=True,
        force_override=False,
        source_premise_verified="true",
        article_readiness_score=8,
        channel_fit_score=7,
        confidence="medium",
    )
    serialized = rc.to_dict()
    rc2 = ResearchContext.from_dict(serialized)

    assert rc2.signal_id == rc.signal_id
    assert rc2.article_ready == rc.article_ready
    assert rc2.score_recommended == rc.score_recommended
    assert rc2.force_override == rc.force_override
    assert rc2.article_readiness_score == rc.article_readiness_score
    assert rc2.channel_fit_score == rc.channel_fit_score
    assert rc2.source_premise_verified == rc.source_premise_verified
    assert rc2.confidence == rc.confidence
    assert rc2.factual_readiness == rc.factual_readiness
    assert rc2.admission_status == rc.admission_status
    assert rc2.approved_override_raw == rc.approved_override_raw
    assert rc2.headline == rc.headline
    assert rc2.core_fact == rc.core_fact


def test_to_dict_contains_stage_15_new_fields():
    rc = _make_rc(article_ready=True, score_recommended=True)
    d = rc.to_dict()
    assert d["FACTUAL_READINESS"] == "ready"
    assert d["ADMISSION_STATUS"] == "admitted"


# ---------------------------------------------------------------------------
# Passthrough
# ---------------------------------------------------------------------------

def test_passthrough_unknown_keys_preserved_in_to_dict():
    record = {
        "SIGNAL_ID": "x",
        "HEADLINE": "test",
        "UNKNOWN_FUTURE_FIELD": "some_value",
        "another_extra": 42,
    }
    rc = ResearchContext.from_dict(record)
    serialized = rc.to_dict()
    assert serialized["UNKNOWN_FUTURE_FIELD"] == "some_value"
    assert serialized["another_extra"] == 42
    assert type(serialized["another_extra"]) is int


def test_passthrough_not_in_adapters():
    record = {
        "SIGNAL_ID": "x",
        "UNKNOWN_KEY": "secret_value",
        "HEADLINE": "test",
    }
    rc = ResearchContext.from_dict(record)
    assert "UNKNOWN_KEY" not in rc.to_legacy_dict()
    assert "UNKNOWN_KEY" not in rc.to_research_dict()
    assert "UNKNOWN_KEY" in rc.to_dict()


def test_whyitmatters_typo_variant_goes_to_passthrough():
    """WHY_IT_MATTERS_TO_BUSINESSES (typo) is not in _KNOWN_JSONL_KEYS → passthrough."""
    assert "WHY_IT_MATTERS_TO_BUSINESSES" not in _KNOWN_JSONL_KEYS
    record = {"SIGNAL_ID": "x", "WHY_IT_MATTERS_TO_BUSINESSES": "value"}
    rc = ResearchContext.from_dict(record)
    assert rc.to_dict()["WHY_IT_MATTERS_TO_BUSINESSES"] == "value"


# ---------------------------------------------------------------------------
# Selection gate equivalence — 242 real JSONL records
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not SIGNALS_ACTIVE.exists(), reason="signals_active.jsonl not found")
def test_selection_gate_equivalence():
    """
    admission_status must match the legacy boolean gate from run_daily_research.py
    (lines 149-161) for all 242 records in signals_active.jsonl.

    Legacy gate:
      if FORCE_PUBLISH_OVERRIDE or APPROVED_OVERRIDE == "true": admit
      elif SCORE_RECOMMENDED=true AND ARTICLE_READY=true AND SCORE >= select_min: admit
      else: skip
    """
    select_min = 7
    mismatches = []

    for line in SIGNALS_ACTIVE.read_text().splitlines():
        s = json.loads(line)
        rc = ResearchContext.from_dict(s)

        legacy_override = (
            str(s.get("FORCE_PUBLISH_OVERRIDE", "") or s.get("APPROVED_OVERRIDE", "")).lower()
            == "true"
        )
        legacy_score_ok = (
            str(s.get("SCORE_RECOMMENDED_FOR_ARTICLE", "false")).lower() == "true"
            and str(s.get("ARTICLE_READY", "false")).lower() == "true"
            and int(s.get("ARTICLE_READINESS_SCORE", "0") or "0") >= select_min
        )
        legacy_admitted = legacy_override or legacy_score_ok
        new_admitted = rc.admission_status in ("admitted", "force_override")

        if new_admitted != legacy_admitted:
            mismatches.append({
                "signal_id": s.get("SIGNAL_ID"),
                "legacy": legacy_admitted,
                "new": new_admitted,
                "article_ready": rc.article_ready,
                "score_recommended": rc.score_recommended,
                "force_override": rc.force_override,
            })

    assert mismatches == [], (
        f"{len(mismatches)} selection gate mismatches:\n"
        + "\n".join(str(m) for m in mismatches[:5])
    )


# ---------------------------------------------------------------------------
# Preflight equivalence — 242 real JSONL records
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not SIGNALS_ACTIVE.exists(), reason="signals_active.jsonl not found")
def test_preflight_equivalence():
    """
    Publish preflight equivalence: rc.article_ready + rc.force_override must
    produce the same blocked/not-blocked decision as the original dict-based
    preflight for all 242 signals_active.jsonl records.

    Original preflight (pre-Stage-1.5):
      article_ready_str = str(signal.get("ARTICLE_READY", "")).lower()
      force_override = str(signal.get("FORCE_PUBLISH_OVERRIDE","") or ...).lower() == "true"
      blocked = (article_ready_str != "true") and not force_override

    New preflight (Stage 1.5):
      rc = ResearchContext.from_dict(signal)
      blocked = not rc.article_ready and not rc.force_override

    Score (SCORE_RECOMMENDED) is NOT part of the publish preflight — this test
    explicitly verifies that the fix from REQUEST CHANGES #2 is correct.
    """
    mismatches = []

    for line in SIGNALS_ACTIVE.read_text().splitlines():
        s = json.loads(line)
        rc = ResearchContext.from_dict(s)
        d = rc.to_legacy_dict()

        # Legacy preflight branch
        legacy_ar_str = str(s.get("ARTICLE_READY", "")).lower()
        legacy_fo = (
            str(s.get("FORCE_PUBLISH_OVERRIDE", "") or s.get("APPROVED_OVERRIDE", "")).lower()
            == "true"
        )
        legacy_blocked = (legacy_ar_str != "true") and not legacy_fo

        # New preflight branch: uses rc.article_ready + rc.force_override directly
        # (NOT rc.admission_status — score is not a publish gate)
        new_blocked = not rc.article_ready and not rc.force_override

        if new_blocked != legacy_blocked:
            mismatches.append({
                "signal_id": s.get("SIGNAL_ID"),
                "legacy_blocked": legacy_blocked,
                "new_blocked": new_blocked,
                "legacy_ar": legacy_ar_str,
                "new_ar": rc.article_ready,
            })

    assert mismatches == [], (
        f"{len(mismatches)} preflight mismatches:\n"
        + "\n".join(str(m) for m in mismatches[:5])
    )


# ---------------------------------------------------------------------------
# RECOMMENDED_FOR_ARTICLE alias verified against real data
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not SIGNALS_ACTIVE.exists(), reason="signals_active.jsonl not found")
def test_recommended_for_article_alias_has_zero_mismatches():
    """
    Verifies that RECOMMENDED_FOR_ARTICLE == ARTICLE_READY in all records
    where both are present, proving the alias assumption used in to_dict().
    """
    mismatches = []
    for line in SIGNALS_ACTIVE.read_text().splitlines():
        s = json.loads(line)
        rfa = s.get("RECOMMENDED_FOR_ARTICLE")
        ar = s.get("ARTICLE_READY")
        if rfa is not None and ar is not None and rfa != ar:
            mismatches.append(
                f"SIGNAL_ID={s.get('SIGNAL_ID')}: "
                f"RECOMMENDED={rfa!r}, ARTICLE_READY={ar!r}"
            )
    assert mismatches == [], f"Alias mismatches found:\n" + "\n".join(mismatches)


# ---------------------------------------------------------------------------
# Parametrized: selection gate — all combinations + missing fields
# ---------------------------------------------------------------------------
#
# Selection gate (run_daily_research.py) semantics:
#   force_override → admit (score irrelevant)
#   ARTICLE_READY=true AND SCORE_RECOMMENDED=true AND score >= min → admit
#   else → skip
#
# rc.admission_status + score threshold encodes all three conditions.
# ---------------------------------------------------------------------------

# fmt: (article_ready_str, score_rec_str, force_publish_str, approved_override_str, score_str, select_min, exp_admitted)
@pytest.mark.parametrize("ar,score_rec,fp_override,ao_override,score_str,select_min,exp_admitted", [
    # --- Normal admitted path ---
    ("true",  "true",  "",      "",      "8", 7, True),   # admitted, score passes
    ("true",  "true",  "",      "",      "7", 7, True),   # admitted, score == min
    # --- Score below threshold ---
    ("true",  "true",  "",      "",      "6", 7, False),  # admitted by gate but score too low
    # --- Score not recommended ---
    ("true",  "false", "",      "",      "9", 7, False),  # article_ready but not score_rec
    # --- Article not ready ---
    ("false", "true",  "",      "",      "9", 7, False),  # score_rec but not article_ready
    ("false", "false", "",      "",      "9", 7, False),  # neither
    # --- FORCE_PUBLISH_OVERRIDE bypasses all ---
    ("false", "false", "true",  "",      "0", 7, True),   # FORCE_PUBLISH_OVERRIDE only
    ("true",  "true",  "true",  "",      "0", 7, True),   # FORCE + admitted (score ignored)
    ("false", "false", "true",  "",      "6", 7, True),   # FORCE + low score → admitted
    # --- APPROVED_OVERRIDE as alternate key (no FORCE_PUBLISH_OVERRIDE) ---
    ("false", "false", "",      "true",  "0", 7, True),   # APPROVED_OVERRIDE only → admitted
    ("false", "false", "",      "true",  "6", 7, True),   # APPROVED_OVERRIDE + low score
    # --- Both keys set, conflicting values ---
    ("false", "false", "false", "true",  "0", 7, True),   # AO=true wins over FP=false
    ("false", "false", "true",  "false", "0", 7, True),   # FP=true wins over AO=false
    # --- Missing / absent fields ---
    ("",      "",      "",      "",      "",  7, False),  # all absent
    (None,    None,    None,    None,    None, 7, False), # all None
    # --- No override key at all ---
    ("false", "false", "",      "",      "0", 7, False),  # no override → blocked
])
def test_selection_gate_parametrized(
    ar, score_rec, fp_override, ao_override, score_str, select_min, exp_admitted
):
    record = {
        "SIGNAL_ID":                     "x",
        "ARTICLE_READY":                 ar,
        "SCORE_RECOMMENDED_FOR_ARTICLE": score_rec,
        "FORCE_PUBLISH_OVERRIDE":        fp_override,
        "APPROVED_OVERRIDE":             ao_override,
        "ARTICLE_READINESS_SCORE":       score_str,
    }
    record = {k: v for k, v in record.items() if v is not None}

    rc = ResearchContext.from_dict(record)
    score = rc.article_readiness_score
    admitted = (
        rc.admission_status == "force_override"
        or (rc.admission_status == "admitted" and score >= select_min)
    )
    assert admitted == exp_admitted, (
        f"article_ready={rc.article_ready} score_rec={rc.score_recommended} "
        f"force_override={rc.force_override} score={score} → {rc.admission_status}"
    )


# ---------------------------------------------------------------------------
# Parametrized: publish preflight — all combinations + missing fields
#
# Publish preflight (generate_and_publish.py) semantics:
#   blocked = (not article_ready) AND (not force_override)
#
# Score is NOT a publish gate. A signal admitted to selected_signals.jsonl
# with ARTICLE_READY=true must be publishable regardless of SCORE_RECOMMENDED.
# ---------------------------------------------------------------------------

# fmt: (article_ready_str, score_rec_str, force_publish_str, approved_override_str, exp_blocked)
@pytest.mark.parametrize("ar,score_rec,fp_override,ao_override,exp_blocked", [
    # article_ready=true always passes — score irrelevant
    ("true",  "true",  "",      "",      False),  # admitted signal → not blocked
    ("true",  "false", "",      "",      False),  # score not rec, article ready → not blocked
    ("true",  "",      "",      "",      False),  # score absent, article ready → not blocked
    # article_ready=false blocked unless override
    ("false", "true",  "",      "",      True),   # score ok but not article ready → blocked
    ("false", "false", "",      "",      True),   # neither → blocked
    ("",      "",      "",      "",      True),   # all absent → blocked
    (None,    None,    None,    None,    True),   # all None → blocked
    # FORCE_PUBLISH_OVERRIDE bypasses article_ready
    ("false", "false", "true",  "",      False),  # FORCE_PUBLISH_OVERRIDE only → not blocked
    ("",      "",      "true",  "",      False),  # absent fields + FORCE → not blocked
    ("true",  "false", "true",  "",      False),  # FORCE + article_ready=true → not blocked
    # APPROVED_OVERRIDE as alternate override key (no FORCE_PUBLISH_OVERRIDE)
    ("false", "false", "",      "true",  False),  # APPROVED_OVERRIDE only → not blocked
    ("false", "false", "",      "true",  False),  # same as above
    # Both absent → still blocked
    ("false", "false", "",      "",      True),   # neither key set → blocked
    # Conflicting values: at least one "true" → not blocked
    ("false", "false", "false", "true",  False),  # AO=true, FP=false → not blocked
    ("false", "false", "true",  "false", False),  # FP=true, AO=false → not blocked
    ("false", "false", "false", "false", True),   # both explicitly false → blocked
])
def test_publish_preflight_parametrized(
    ar, score_rec, fp_override, ao_override, exp_blocked
):
    record = {
        "SIGNAL_ID":                     "x",
        "ARTICLE_READY":                 ar,
        "SCORE_RECOMMENDED_FOR_ARTICLE": score_rec,
        "FORCE_PUBLISH_OVERRIDE":        fp_override,
        "APPROVED_OVERRIDE":             ao_override,
    }
    record = {k: v for k, v in record.items() if v is not None}

    rc = ResearchContext.from_dict(record)
    blocked = not rc.article_ready and not rc.force_override
    assert blocked == exp_blocked, (
        f"article_ready={rc.article_ready} force_override={rc.force_override} "
        f"score_rec={rc.score_recommended} → blocked={blocked}"
    )


def test_publish_preflight_score_not_a_gate():
    """
    Critical: SCORE_RECOMMENDED=false must NOT block publish.
    Old preflight only checked ARTICLE_READY; Stage 1.5 must preserve this.
    """
    rc = ResearchContext.from_dict({
        "SIGNAL_ID": "x",
        "ARTICLE_READY": "true",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "false",
        "FORCE_PUBLISH_OVERRIDE": "",
    })
    assert rc.article_ready is True
    assert rc.score_recommended is False
    assert rc.admission_status == "rejected"      # rejected at selection gate
    blocked = not rc.article_ready and not rc.force_override
    assert blocked is False, (
        "Signal with ARTICLE_READY=true must pass publish preflight "
        "even when SCORE_RECOMMENDED=false"
    )


def test_editorial_context_wiring_deferred_to_stage2():
    """
    Documents that EditorialContext is defined but not wired in Stage 1.5.
    to_editorial() works for admitted/force_override signals only.
    Signals passing publish preflight (article_ready=true, score_rec=false)
    would raise ValueError in to_editorial() — this is the reason wiring
    is deferred to Stage 2.
    """
    # Signal that passes publish preflight (article_ready) but not selection gate
    rc = ResearchContext.from_dict({
        "SIGNAL_ID": "x",
        "ARTICLE_READY": "true",
        "SCORE_RECOMMENDED_FOR_ARTICLE": "false",
    })
    # Passes publish preflight
    assert not (not rc.article_ready and not rc.force_override)
    # But cannot construct EditorialContext without force_override
    import pytest as _pytest
    with _pytest.raises(ValueError, match="admission_status='rejected'"):
        rc.to_editorial({})
