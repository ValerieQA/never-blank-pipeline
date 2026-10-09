"""The evidence path a signal verified through, and who can read it (#308).

Two acceptance runs were spent, each on a signal that failed a *different*
one of the two independent gates:

* run 1 chose `6a72b2abcc466aab`, which cleared S-00 and verified through the
  research/data path. S-04 refused it with
  `no_asset_or_admissible_interpretation`.
* run 2 chose `422a53e0ae83e40a` on documented-case material alone. It states
  no `EDITORIAL_DOMAIN`, so S-00's `FIT-NB-TOPIC-01` refused it on 0 calls and
  the stage under diagnosis was never reached.

Stage 4 already computes which path verified a premise and then discards the
answer: `SOURCE_PREMISE_VERIFIED` collapses both paths into one boolean and the
distinction survives only inside a reason string. These tests pin the two
changes that follow from that, and nothing else:

1. the path is recorded on records the classifier writes, under a closed
   vocabulary, and **absent** when no path verified — never defaulted;
2. both gates can be read together, deterministically and with no model call.

No test here asserts that a documented case will pass S-04. It will not be
known for any signal until a run reports it.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from scripts.golden_engine_candidates import assess, candidates
from scripts.research.enrich import (
    COMPANY_CASE,
    PREMISE_PATH_FIELD,
    RESEARCH_DATA,
    premise_path,
)

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "data" / "research" / "signals_active.jsonl"
CLIENT = ROOT / "clients" / "never_blank"

#: The live signals, by id, read once.
LIVE = {
    json.loads(line)["SIGNAL_ID"]: json.loads(line)
    for line in ACTIVE.read_text(encoding="utf-8").splitlines()
    if line.strip()
}


# ═════════════════════════ 1 · the derivation ══════════════════════════════


def test_a_named_company_with_a_source_takes_the_company_case_path() -> None:
    """A shape, not a verdict: nothing here reads `EVIDENCE_OF_OUTCOME`."""

    assert premise_path({
        "REAL_COMPANY_EXAMPLE": "Zingerman's Delicatessen",
        "SOURCE_FOR_CASE": "https://example.test/case",
        "CONFIDENCE": "high",
    }) == COMPANY_CASE


def test_a_source_without_a_company_is_research_data() -> None:
    """Legitimate Never Blank material, and not a company case — the readiness
    check's own words are "without a named company"."""

    assert premise_path({
        "SOURCE_FOR_CASE": "https://example.test/study",
        "CONFIDENCE": "high",
    }) == RESEARCH_DATA


def test_the_company_path_wins_when_both_would_hold() -> None:
    """A named company with a source is the more specific statement, and the
    one a documented-case role can shortlist on."""

    assert premise_path({
        "REAL_COMPANY_EXAMPLE": "Buffer",
        "SOURCE_FOR_CASE": "https://example.test/case",
        "CONFIDENCE": "medium",
    }) == COMPANY_CASE


@pytest.mark.parametrize("signal", [
    {"SOURCE_FOR_CASE": "https://example.test/x", "CONFIDENCE": "low"},
    {"REAL_COMPANY_EXAMPLE": "Acme"},
    {},
])
def test_an_unverified_premise_has_no_path(signal: dict) -> None:
    """`None` never means research/data, and is never written as a value."""

    assert premise_path(signal) is None


# ═══════════════════ 2 · what the classifier records ═══════════════════════


def _enriched(monkeypatch, payload: dict, seed: dict) -> dict:
    """`enrich_signal` with its one model call replaced — no provider reached."""

    import scripts.research.enrich as enrich

    monkeypatch.setattr(enrich, "chat", lambda *a, **k: json.dumps(payload))
    monkeypatch.setattr(
        enrich, "load_prompt", lambda *a, **k: {"system": "s", "user": "u"}
    )
    # The classifier's own shape: (value, outcome). Unclassified here, because
    # these tests are about the evidence path and not about classification —
    # and an unclassified record is the honest default, never an admitted one.
    monkeypatch.setattr(
        enrich, "classify_against", lambda *a, **k: (None, enrich.CANNOT_ANSWER)
    )
    return enrich.enrich_signal(seed)


def test_a_verified_company_case_records_its_path(monkeypatch) -> None:
    record = _enriched(
        monkeypatch,
        {
            "REAL_COMPANY_EXAMPLE": "Zingerman's Delicatessen",
            "SOURCE_FOR_CASE": "https://example.test/case",
            "CORE_FACT": "a fact",
            "CONFIDENCE": "high",
        },
        {"SIGNAL_ID": "aaa1", "HEADLINE": "h", "SOURCE_URL": "https://example.test"},
    )

    assert record[PREMISE_PATH_FIELD] == COMPANY_CASE
    assert record["SOURCE_PREMISE_VERIFIED"] == "true"


def test_a_verified_research_signal_records_the_other_path(monkeypatch) -> None:
    record = _enriched(
        monkeypatch,
        {
            "SOURCE_FOR_CASE": "https://example.test/study",
            "CORE_FACT": "a fact",
            "CONFIDENCE": "high",
        },
        {"SIGNAL_ID": "bbb2", "HEADLINE": "h", "SOURCE_URL": "https://example.test"},
    )

    assert record[PREMISE_PATH_FIELD] == RESEARCH_DATA
    assert record["SOURCE_PREMISE_VERIFIED"] == "true"


def test_an_unverified_signal_carries_no_path_field_at_all(monkeypatch) -> None:
    """Absent, not empty and not defaulted — the posture #365 holds for an
    unclassified domain."""

    record = _enriched(
        monkeypatch,
        {"CORE_FACT": "a fact", "CONFIDENCE": "low"},
        {"SIGNAL_ID": "ccc3", "HEADLINE": "h", "SOURCE_URL": "https://example.test"},
    )

    assert PREMISE_PATH_FIELD not in record
    assert record["SOURCE_PREMISE_VERIFIED"] == "false"


def test_a_stale_path_does_not_survive_re_enrichment(monkeypatch) -> None:
    """Independent review, #401: the input record may already carry a path.

    `merged` starts from the input, so writing only when a path verifies is
    not enough — a value from an earlier enrichment would read as current for
    a signal whose evidence no longer verifies. Absence has to be produced.
    """

    record = _enriched(
        monkeypatch,
        {"CORE_FACT": "a fact", "CONFIDENCE": "low"},
        {
            "SIGNAL_ID": "stale",
            "HEADLINE": "h",
            "SOURCE_URL": "https://example.test",
            PREMISE_PATH_FIELD: COMPANY_CASE,   # left over from before
        },
    )

    assert PREMISE_PATH_FIELD not in record
    assert record["SOURCE_PREMISE_VERIFIED"] == "false"


def test_a_stale_path_is_replaced_when_the_other_path_verifies(monkeypatch) -> None:
    """And the complement: a surviving wrong value is as bad as a surviving
    stale one."""

    record = _enriched(
        monkeypatch,
        {
            "SOURCE_FOR_CASE": "https://example.test/study",
            "CORE_FACT": "a fact",
            "CONFIDENCE": "high",
        },
        {
            "SIGNAL_ID": "swap",
            "HEADLINE": "h",
            "SOURCE_URL": "https://example.test",
            PREMISE_PATH_FIELD: COMPANY_CASE,
        },
    )

    assert record[PREMISE_PATH_FIELD] == RESEARCH_DATA


def test_the_boolean_and_the_path_cannot_disagree() -> None:
    """They were two copies of one derivation; now the boolean comes from the
    path, so no record can carry `verified=true` with no path."""

    source = inspect.getsource(
        __import__("scripts.research.enrich", fromlist=["enrich_signal"]).enrich_signal
    )

    assert "premise_verified = path is not None" in source


def test_the_field_is_not_a_schema_default() -> None:
    """A default would write the field onto every new record whether a path
    verified it or not, and absence would stop meaning absence."""

    from scripts.research.run_daily_research import SCHEMA_DEFAULTS

    assert PREMISE_PATH_FIELD not in SCHEMA_DEFAULTS


def test_no_historical_record_acquired_the_field() -> None:
    """#365: no backfill, no migration of the existing records. This change
    adds a field going forward and touches nothing already written.
    """

    assert [
        sid for sid, r in LIVE.items() if PREMISE_PATH_FIELD in r
    ] == []


# ═══════════════ 3 · reading both gates, deterministically ═════════════════


def _record(sid: str, **over) -> dict:
    base = {
        "SIGNAL_ID": sid,
        "HEADLINE": f"headline {sid}",
        "SOURCE_NAME": "Example",
        "SOURCE_URL": "https://example.test/a",
        "EDITORIAL_DOMAIN": "marketing_sales_cx",
        "EDITORIAL_RISK": "low",
        "SOURCE_FOR_CASE": "https://example.test/case",
        "CONFIDENCE": "high",
    }
    base.update(over)
    return base


def test_a_company_case_signal_that_clears_s00_is_a_candidate() -> None:
    found = candidates(
        [_record("ok1", REAL_COMPANY_EXAMPLE="Zingerman's")], client_dir=CLIENT
    )

    assert [c["signal_id"] for c in found] == ["ok1"]


def test_a_company_case_signal_that_fails_s00_is_not_a_candidate() -> None:
    """Run 2's shape exactly: all the material, no stated classification."""

    rec = _record("run2", REAL_COMPANY_EXAMPLE="Stripe")
    rec.pop("EDITORIAL_DOMAIN")
    rec.pop("EDITORIAL_RISK")

    verdict = assess(rec, client_dir=CLIENT)

    assert verdict["premise_path"] == COMPANY_CASE
    assert verdict["s00_passes"] is False
    assert "FIT-NB-TOPIC-01" in verdict["refused_by"]
    assert candidates([rec], client_dir=CLIENT) == []


def test_a_research_signal_that_clears_s00_is_not_a_candidate() -> None:
    """Run 1's shape: eligible, and refused at S-04 for want of a company case."""

    verdict = assess(_record("run1"), client_dir=CLIENT)

    assert verdict["s00_passes"] is True
    assert verdict["premise_path"] == RESEARCH_DATA
    assert candidates([_record("run1")], client_dir=CLIENT) == []


def test_an_unverified_signal_is_not_a_candidate() -> None:
    rec = _record("weak", CONFIDENCE="low")

    assert assess(rec, client_dir=CLIENT)["premise_path"] is None
    assert candidates([rec], client_dir=CLIENT) == []


def test_a_stated_but_unadmitted_domain_is_not_a_candidate() -> None:
    """S-00 is a strict allow-list, and this reader must not soften it."""

    rec = _record("off", REAL_COMPANY_EXAMPLE="Acme", EDITORIAL_DOMAIN="uranium")

    assert candidates([rec], client_dir=CLIENT) == []


# ── against the live queue, asserted as properties rather than counts ───────


def test_the_live_queue_separates_the_two_failed_runs_and_the_held_candidate() -> None:
    """The one assertion that would have prevented both wasted authorizations.

    Properties, not counts, so a new signal arriving does not break it.
    """

    held = assess(LIVE["7965169a1ae121c5"], client_dir=CLIENT)
    assert held["s00_passes"] is True
    assert held["premise_path"] == COMPANY_CASE

    run1 = assess(LIVE["6a72b2abcc466aab"], client_dir=CLIENT)
    assert run1["s00_passes"] is True
    assert run1["premise_path"] == RESEARCH_DATA

    run2 = assess(LIVE["422a53e0ae83e40a"], client_dir=CLIENT)
    assert run2["premise_path"] == COMPANY_CASE
    assert run2["s00_passes"] is False


def test_the_reader_asks_no_model_anything() -> None:
    """Choosing a candidate must never cost a call — asserted on executable
    source, because a comment saying so is not the absence."""

    import scripts.golden_engine_candidates as reader

    tree = ast.parse(inspect.getsource(reader))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body.pop(0)
    code = ast.unparse(tree)

    for forbidden in ("chat(", "model_enrich", "model_discovery", "OpenAI"):
        assert forbidden not in code, forbidden


def test_the_reader_writes_nothing() -> None:
    """A selection tool that mutated the queue would be a migration (#365)."""

    import scripts.golden_engine_candidates as reader

    code = inspect.getsource(reader)

    for forbidden in ("write_text", "open(", "_append_jsonl", "dump("):
        assert forbidden not in code, forbidden
