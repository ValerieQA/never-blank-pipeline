"""Issue #296: the knowledge the engine needs before it can run at all.

NB-02a (#294) built the register's format and its validator, and shipped no
content. This is the content: the universal strength ladder, the check records
for V-P01…V-S10 with the routes of Step 2 §5.3, the seven `K-TEMPT` probe
families of Step 2 §4 U-1, one `K-DST` record for each of the six destinations,
and Never Blank's own rules written as records in the client folder.

Content is data, so almost every test here reads the shipped files rather than a
fixture. The validator already refuses a malformed record — `test_294` proves
that against a corpus — and what this file asserts is what a validator cannot:
that the set is **complete** (every destination has a record, every check of the
map is present, the seven families are all there) and that each check's routes
are the routes the engine actually executes, compared row by row against the
stage-topology registry rather than against a second copy of the table.

The client rules are held to the register's own rules by laying them over a copy
of the register as records: they live in the client folder, where the register's
CI caller does not read them, and a format nothing checks is a format that rots.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts.ci.check_knowledge_register import client_rule_paths
from src.editorial_core.topology import CANONICAL_TOPOLOGY, TerminalOutcome
from src.knowledge.grammar import DESTINATION, parse_condition
from src.knowledge.ladder import (
    CLIENT_LADDER_SLOT,
    UNIVERSAL_TOP_LEVEL,
    client_ladder_problems,
    parse_universal_ladder,
)
from src.knowledge.markdown import load_document
from src.knowledge.records import (
    BRANCHING_CHECKS,
    ROUTE_NONE,
    CheckRecord,
    KnowledgeRecord,
    parse_check_record,
    parse_knowledge_record,
)
from src.knowledge.validator import validate_register
from src.knowledge.vocabulary import load_vocabularies
from src.strategy.client_contracts import load_stream_contract

_REPO_ROOT = Path(__file__).resolve().parents[1]

REGISTER = _REPO_ROOT / "knowledge"
CLIENTS = _REPO_ROOT / "clients"
CLIENT_RULES = CLIENTS / "never_blank" / "rules"

CHECKS = REGISTER / "checks"
DESTINATION_RECORDS = REGISTER / "records" / "dst"
PROBE_FAMILIES = REGISTER / "records" / "tempt"

VOCABULARIES = load_vocabularies(REGISTER)

#: Every check of map §9, which is the set the seed set had to cover.
EXPECTED_CHECKS = (
    *(f"V-P0{number}" for number in range(1, 6)),
    *(f"V-T0{number}" for number in range(1, 9)),
    *(f"V-S0{number}" for number in range(1, 10)),
    "V-S10",
)

#: Step 2 §4 U-1: seven families, taken from real errors rather than invented.
PROBE_FAMILY_COUNT = 7


def records_in(directory: Path, pattern: str = "*.md") -> list[KnowledgeRecord]:
    """Every record of a directory, parsed as the register reads it."""

    return [
        parse_knowledge_record(load_document(path))
        for path in sorted(directory.glob(pattern))
    ]


def checks() -> list[CheckRecord]:
    """Every check record the register ships."""

    return [
        parse_check_record(load_document(path)) for path in sorted(CHECKS.glob("*.md"))
    ]


# ----------------------------------------------------------------------
# The seed set as a whole
# ----------------------------------------------------------------------


def test_the_validator_accepts_the_seed_set():
    findings = validate_register(REGISTER, client_rule_paths=client_rule_paths(CLIENTS))
    assert [finding.render() for finding in findings] == []


def test_the_ladder_has_four_levels_and_level_4_is_the_tightened_one():
    ladder = parse_knowledge_record(load_document(REGISTER / "ladders" / "default.md"))
    levels = parse_universal_ladder(ladder)

    assert len(levels) == UNIVERSAL_TOP_LEVEL
    # Patch S4-R1's correction, and the whole reason level 4 is worded as it
    # is: one study, however well designed, is corroboration and not more, so
    # "established" needs statistics that measure the thing or many cases.
    assert "one individual study" in levels[2].evidence.lower()
    assert "no higher" in levels[2].evidence.lower()
    assert "systematic review" in levels[3].evidence.lower()


# ----------------------------------------------------------------------
# Check records: the set, and the routes
# ----------------------------------------------------------------------


def test_every_check_of_the_map_has_a_record():
    assert sorted(check.check_id for check in checks()) == sorted(EXPECTED_CHECKS)


@pytest.mark.parametrize("check_id", EXPECTED_CHECKS)
def test_each_check_routes_exactly_as_the_topology_declares(check_id):
    check = parse_check_record(load_document(CHECKS / f"{check_id}.md"))
    outcomes = {outcome.value for outcome in TerminalOutcome}

    for row in check.routes:
        if row.is_hint:
            assert check.check_class == "S", "a hard check does not produce hints"
            assert (row.cause, row.counter, row.on_exhaustion) == (
                ROUTE_NONE,
                ROUTE_NONE,
                ROUTE_NONE,
            )
            continue
        assert check.check_class == "H", "a soft check routes nothing (I-12)"
        if row.is_terminal:
            assert row.on_exhaustion in outcomes
            assert (row.cause, row.counter) == (ROUTE_NONE, ROUTE_NONE)
            continue
        source, target = row.edge
        declared = [
            route
            for route in CANONICAL_TOPOLOGY.replan_routes
            if route.source == source and route.cause == row.cause
        ]
        assert declared, f"{check_id}: {source} has no route for {row.cause!r}"
        route = declared[0]
        assert (route.target, route.counter, route.on_exhaustion.value) == (
            target,
            row.counter,
            row.on_exhaustion,
        )


def test_the_plan_checks_run_at_s_11_and_the_text_checks_at_s_13():
    for check in checks():
        sources = {row.edge[0] for row in check.routes if row.edge is not None}
        if not sources:
            continue
        expected = "S-11" if check.check_id.startswith("V-P") else "S-13"
        assert sources == {expected}, check.check_id


def test_the_two_branching_checks_carry_their_branches():
    for check_id in BRANCHING_CHECKS:
        check = parse_check_record(load_document(CHECKS / f"{check_id}.md"))
        assert (check.branch_criterion or "").strip(), check_id
        # Each branch names a different owner, which is the point of the branch:
        # one goes back to the Writer, the other to the layer that planned it.
        targets = {row.edge[1] for row in check.routes if row.edge is not None}
        assert targets == {"S-12", "S-08"}, check_id


def test_no_soft_check_carries_a_threshold_without_an_owner():
    # I-12, from the other side of the validator: the shipped set declares no
    # threshold at all, so no soft signal acts on a number nobody approved.
    for check in checks():
        if check.check_class == "S":
            assert check.threshold == "none", check.check_id
            assert not (check.approved_by or "").strip(), check.check_id


def test_no_hard_check_rests_on_research_alone():
    # I-13, which this issue must preserve: a research finding does not become a
    # hard check. The seed set ships none that would need that approval.
    for check in checks():
        if check.is_hard:
            assert "RES" not in check.evidence_classes, check.check_id


# ----------------------------------------------------------------------
# One K-DST record per destination, for all six
# ----------------------------------------------------------------------


def test_every_destination_has_at_least_one_record():
    covered = set()
    for record in records_in(DESTINATION_RECORDS):
        condition = parse_condition(record.applies_when, VOCABULARIES)
        covered.update(
            atom.name for atom in condition.atoms() if atom.family == DESTINATION
        )

    assert covered == set(VOCABULARIES.get("destinations").names)


def test_every_destination_record_says_when_it_was_verified():
    # Rule 8 already refuses one that does not, and the reason it matters is
    # expiry: §5 computes a destination record's 90 days from this date.
    for record in records_in(DESTINATION_RECORDS):
        assert record.verified_on, record.record_id
        assert record.review_by, record.record_id


# ----------------------------------------------------------------------
# The seven probe families (Step 2 §4 U-1, Step 4 §6)
# ----------------------------------------------------------------------


def test_there_are_seven_probe_families():
    families = records_in(PROBE_FAMILIES)
    assert len(families) == PROBE_FAMILY_COUNT
    assert all(record.is_probe_family for record in families)


def test_each_probe_family_is_tier_3_and_influences_s_04_only():
    for record in records_in(PROBE_FAMILIES):
        assert record.tier == "3", record.record_id
        assert record.status in ("descriptive", "candidate"), record.record_id
        assert {influence.stage for influence in record.influences} == {"S-04"}


def test_each_probe_family_asks_a_question_and_cites_a_real_output():
    for record in records_in(PROBE_FAMILIES):
        probe = (record.document.section("Probe") or "").strip()
        examples = (record.document.section("Real examples") or "").strip()
        assert probe.endswith("?"), f"{record.record_id}: the probe is a question"
        # §6: at least one real engine output, cited by sample-pack or run
        # reference. Both spellings of "cited" that exist in this repository are
        # a package under reports/ and a walkthrough of the map.
        assert (
            "reports/content_packages/" in examples
            or "CANONICAL_EDITORIAL_MAP_v1.md" in examples
        ), record.record_id


# ----------------------------------------------------------------------
# Never Blank's rules in the client folder
# ----------------------------------------------------------------------


def test_the_client_rules_are_records_the_register_would_accept(tmp_path):
    """The rules live outside the register, so nothing else checks their shape.

    Laid over a copy of the register under their own family directory, they are
    judged by every rule that can judge a record: front matter, status and tier,
    approvals, the condition grammar, the stages and fields they name, identity
    and versioning, and the credential scan.
    """

    register = tmp_path / "register"
    shutil.copytree(REGISTER, register)
    family = register / "records" / "nb"
    family.mkdir(parents=True)
    for path in sorted(CLIENT_RULES.glob("K-NB-*.md")):
        shutil.copy(path, family / path.name)

    findings = validate_register(register)
    assert [finding.render() for finding in findings] == []


def test_the_client_rules_are_the_client_s_own_tier():
    rules = records_in(CLIENT_RULES, "K-NB-*.md")
    assert rules, "the client folder holds no rule records"
    for record in rules:
        # §2.3: an approved client rule is tier 2, an unapproved one is a tier-3
        # candidate. Neither is ever tier 1 — that is hard platform policy, and
        # it is not something a client writes.
        assert (record.status, record.tier) in (
            ("approved-rule", "2"),
            ("candidate", "3"),
        ), record.record_id
        assert "CLIENT" in record.evidence_classes, record.record_id


def test_a_declared_client_ladder_maps_every_level_to_a_universal_one():
    """Conditional on purpose: declaring a ladder is the client's decision.

    Never Blank declares none today, so the universal ladder is in force
    unchanged. The moment a contract declares one, §7 requires every level to
    say which universal level it maps to, and this asserts it for whichever
    client contract this repository ships.
    """

    for path in client_rule_paths(CLIENTS):
        declared = load_stream_contract(path).plan_slots
        values = next(
            (levels for slot, levels in declared if slot == CLIENT_LADDER_SLOT), ()
        )
        if not values:
            continue
        assert client_ladder_problems(values, path=str(path)) == ()
