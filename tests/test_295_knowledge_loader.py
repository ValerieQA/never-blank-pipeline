"""Issue #295: the knowledge loader — effective status, limits, selection, size.

Step 4 §5, §5.1 and §9 say what a run makes of a valid register. Four claims,
each of which has to be able to fail:

- **Expiry is a demotion, not a deletion** (§5). A `candidate` past its
  `review_by` becomes a `weak-candidate`; a tier-1 `approved-rule` past its
  `review_by` goes on being enforced and is flagged, because dropping a hard
  rule nobody re-checked is the unsafe direction.
- **A weak candidate never acts alone** (§5.1). It cannot exclude a strategy by
  itself, it loses its own tier to any non-expired record, and it counts at its
  original weight only where a non-expired record reinforces it.
- **A record reaches a stage on two conditions** (§9.3): the stage is in its
  `## Influences`, and its condition evaluates true against that stage's inputs.
  Both results are kept, because §4 puts the true/false of every eligible record
  into the routing evidence.
- **Mandatory knowledge is never truncated** (§9.6). Over capacity, the stage
  fails closed *before* the call, and `stage_routing` proves per request that
  every mandatory record was actually in it.

The register under test is the one the repository ships, plus the #294 corpus,
plus `tests/fixtures/knowledge_loader/` — and the first test here is that the
assembly passes the validator, so nothing below rests on register content a run
would have refused to start on.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import pytest

from src.editorial_core.arp import (
    ArpOutcome,
    KnowledgeStatus,
    KnowledgeTier,
    OutcomeRecord,
    OutcomeScope,
    PrecedenceApplication,
    StateCode,
    precedence_log,
)
from src.knowledge.loader import (
    EXPIRED_REVIEW,
    WEAK_CANDIDATE_ALONE,
    WEAK_CANDIDATE_LOSES_ITS_TIER,
    WEAK_CANDIDATE_REINFORCED,
    KnowledgeBase,
    KnowledgePacking,
    LoaderError,
    MandatoryKnowledgeExceedsCapacity,
    RoutedKnowledge,
    StageInputs,
    fit_to_capacity,
    in_precedence_order,
    load_register,
    may_exclude,
    outcome_scope,
    reinforced,
)
from src.knowledge.validator import validate_register
from src.knowledge.vocabulary import load_vocabularies
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_workspace import (
    DeciderKind,
    RunWorkspace,
    StageAttribution,
    StageRecord,
    StageStatus,
)
from src.run.stage_routing import (
    COMPLETE,
    INCOMPLETE,
    VIOLATION,
    RoutedRecord,
    StageRequest,
    StageRouting,
)
from src.strategy.execution_context import ConfigurationIdentity

_REPO_ROOT = Path(__file__).resolve().parents[1]

REGISTER = _REPO_ROOT / "knowledge"
VALID = _REPO_ROOT / "tests" / "fixtures" / "knowledge_register" / "valid" / "register"
LOADER = _REPO_ROOT / "tests" / "fixtures" / "knowledge_loader" / "register"

#: The day these runs happen on. `K-MAT-10` and `K-DST-TG-05` are past their
#: `review_by` on it and everything else is not, which is the whole of §5's
#: asymmetry in one date.
TODAY = date(2026, 9, 23)

TS_UTC = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)

#: What S-09 reads in these tests: a mechanism and comparable items, which makes
#: `K-MAT-10` and `K-MAT-11` both applicable and `K-MAT-12` not.
S09_INPUTS = StageInputs(
    destination="wix",
    features={"parallel_structure": "yes", "mechanism_present": "yes"},
)
S08_INPUTS = StageInputs(
    destination="wix",
    features={"documented_case": "yes", "named_company": "yes"},
)


def build_register(root: Path) -> Path:
    """The shipped register, the #294 corpus and this issue's fixtures."""

    register = root / "register"
    shutil.copytree(REGISTER, register)
    for overlay in (VALID, LOADER):
        shutil.copytree(overlay, register, dirs_exist_ok=True)
    return register


@pytest.fixture()
def register(tmp_path) -> Path:
    return build_register(tmp_path)


@pytest.fixture()
def base(register) -> KnowledgeBase:
    return load_register(register, today=TODAY)


def _call_with(
    routing: StageRouting, stage: str, packing: KnowledgePacking
) -> StageRequest:
    """What a stage does once it holds its material: build it, and send it.

    Its argument is the packing, so a packing that was never produced is a call
    that was never made — which is what §9.6's "the call is not made" has to
    mean in code rather than in a comment.
    """

    return routing.observe(
        stage, user="\n\n".join(item.text for item in packing.routed)
    )


# ----------------------------------------------------------------------
# The register these tests load
# ----------------------------------------------------------------------


def test_the_assembled_register_is_one_a_run_may_start_on(register):
    """Everything below reads a register the §8 validator accepts."""

    assert [finding.render() for finding in validate_register(register)] == []


# ----------------------------------------------------------------------
# Effective status at load (§5)
# ----------------------------------------------------------------------


def test_an_expired_candidate_is_loaded_as_a_weak_candidate(base):
    record = base.record("K-MAT-10")

    assert record.file_status is KnowledgeStatus.CANDIDATE
    assert record.effective_status is KnowledgeStatus.WEAK_CANDIDATE
    assert record.expired_review is True


def test_an_expired_hard_rule_stays_enforced_and_is_flagged(base):
    """§5: dropping a rule nobody re-checked is the unsafe direction."""

    record = base.record("K-DST-TG-05")

    assert record.file_status is KnowledgeStatus.APPROVED_RULE
    assert record.effective_status is KnowledgeStatus.APPROVED_RULE
    assert record.flags == (EXPIRED_REVIEW,)
    assert record.mandatory is True


def test_an_invariant_does_not_lapse(base):
    ladder = base.record("K-LAD-01")

    assert ladder.effective_status is KnowledgeStatus.INVARIANT
    assert ladder.tier is KnowledgeTier.ARCHITECTURAL
    assert ladder.mandatory is True


def test_a_record_inside_its_review_period_is_untouched(base):
    record = base.record("K-MAT-11")

    assert record.effective_status is record.file_status
    assert record.expired_review is False and record.flags == ()


def test_a_retired_record_is_never_loaded(register):
    record = register / "records" / "mat" / "K-MAT-11.md"
    record.write_text(
        record.read_text(encoding="utf-8").replace(
            "status: descriptive", "status: retired", 1
        ),
        encoding="utf-8",
    )

    base = load_register(register, today=TODAY)

    with pytest.raises(LoaderError, match="not loaded into this run"):
        base.record("K-MAT-11")


def test_the_same_register_read_on_a_later_day_demotes_more(register):
    """Effective status is a fact about the day, and is recorded as one."""

    early = load_register(register, today=date(2026, 2, 1))
    later = load_register(register, today=date(2027, 1, 1))

    assert early.record("K-MAT-10").effective_status is KnowledgeStatus.CANDIDATE
    assert later.record("K-MAT-10").effective_status is KnowledgeStatus.WEAK_CANDIDATE
    assert later.loaded_on == date(2027, 1, 1)


# ----------------------------------------------------------------------
# Selection: eligibility × applicability (§9.3)
# ----------------------------------------------------------------------


def test_a_record_reaches_a_stage_it_influences_and_no_other(base):
    selection = base.select("S-09", S09_INPUTS)

    assert {item.identity for item in selection.eligible} == {
        "K-MAT-10", "K-MAT-11", "K-MAT-12",
    }
    assert "K-DST-TG-05" not in {item.identity for item in selection.eligible}


def test_an_eligible_record_whose_condition_is_false_is_read_and_recorded(base):
    """§4: the true/false per record goes into the routing evidence."""

    selection = base.select("S-09", S09_INPUTS)
    results = {item.identity: item.applicable for item in selection.eligible}

    assert results == {"K-MAT-10": True, "K-MAT-11": True, "K-MAT-12": False}
    assert {item.identity for item in selection.routed} == {"K-MAT-10", "K-MAT-11"}


def test_a_destination_rule_applies_only_at_its_own_destination(base):
    telegram = base.select("S-10", StageInputs(destination="telegram"))
    linkedin = base.select("S-10", StageInputs(destination="linkedin"))

    assert "K-DST-TG-05" in {item.identity for item in telegram.routed}
    assert "K-DST-TG-05" not in {item.identity for item in linkedin.routed}
    assert "K-DST-TG-05" in {item.identity for item in linkedin.eligible}


def test_a_stage_that_holds_no_such_input_reads_the_term_as_false(base):
    """An input the stage does not hold is not the value the term asks for."""

    selection = base.select("S-10", StageInputs())

    assert [item.identity for item in selection.routed] == []


def test_a_check_reaches_the_stage_its_own_route_table_names(base):
    text_check = base.select("S-13", S09_INPUTS)

    assert [check.identity for check in text_check.checks] == ["V-T01"]
    assert "V-T01" in {item.identity for item in text_check.mandatory}
    # V-S10 routes nothing at all, so the register does not place it: the stage
    # that applies a soft check says so out of its own Step 2 contract.
    assert base.select("S-11", S09_INPUTS).checks == ()


# ----------------------------------------------------------------------
# Acceptance evidence 1: an expired candidate cannot exclude a strategy
# ----------------------------------------------------------------------


def test_an_expired_candidate_cannot_exclude_a_strategy(base):
    """§5.1 rule 1. The conflict is a hint, and the strategy survives it."""

    selection = base.select("S-09", S09_INPUTS)
    alone = [item for item in selection.routed if item.identity == "K-MAT-10"]

    assert [item.is_weak for item in alone] == [True]
    assert may_exclude(alone) is False


def test_the_same_exclusion_stands_once_a_non_expired_record_is_behind_it(base):
    selection = base.select("S-09", S09_INPUTS)

    assert may_exclude(selection.routed) is True


def test_an_exclusion_resting_on_nothing_excludes_nothing(base):
    assert may_exclude(()) is False


def test_a_reinforced_weak_candidate_may_act(base):
    selection = base.select("S-09", S09_INPUTS)
    weak = next(item for item in selection.routed if item.identity == "K-MAT-10")

    supported = reinforced(weak, base.record("K-MAT-11"))

    assert supported.reinforced_by == "K-MAT-11"
    assert may_exclude([supported]) is True
    assert supported.ref().reinforced_by == "K-MAT-11"


# ----------------------------------------------------------------------
# The other two weak-candidate limits (§5.1 rules 2 and 3)
# ----------------------------------------------------------------------


def test_a_weak_candidate_loses_its_own_tier_whatever_the_confidences(base):
    """K-MAT-10 is `high` and K-MAT-11 is `medium`; the demotion still decides."""

    selection = base.select("S-09", S09_INPUTS)

    assert [item.identity for item in selection.routed] == ["K-MAT-11", "K-MAT-10"]


def test_the_precedence_log_refuses_a_weak_candidate_winning_its_tier(base):
    selection = base.select("S-09", S09_INPUTS)
    strong = next(item for item in selection.routed if item.identity == "K-MAT-11")
    weak = next(item for item in selection.routed if item.identity == "K-MAT-10")

    accepted = PrecedenceApplication(
        conflict="compare the items, or follow the mechanism through one",
        winner=strong.ref(),
        loser=weak.ref(),
        rule_applied=WEAK_CANDIDATE_LOSES_ITS_TIER,
    )
    assert accepted.loser.effective_status is KnowledgeStatus.WEAK_CANDIDATE

    with pytest.raises(ValueError, match="weak candidate"):
        PrecedenceApplication(
            conflict="the same conflict, decided the other way",
            winner=weak.ref(),
            loser=strong.ref(),
            rule_applied=WEAK_CANDIDATE_LOSES_ITS_TIER,
        )


def test_a_reinforced_weak_candidate_may_win_its_tier(base):
    selection = base.select("S-09", S09_INPUTS)
    strong = next(item for item in selection.routed if item.identity == "K-MAT-11")
    weak = reinforced(
        next(item for item in selection.routed if item.identity == "K-MAT-10"),
        base.record("K-MAT-11"),
    )

    application = PrecedenceApplication(
        conflict="compare the items, or follow the mechanism through one",
        winner=weak.ref(),
        loser=strong.ref(),
        rule_applied=WEAK_CANDIDATE_REINFORCED,
    )

    assert application.winner.reinforced_by == "K-MAT-11"


def test_reinforcement_is_refused_where_the_register_does_not_support_it(base):
    """§5.1 rule 3 is the same tier or a higher one, never a weaker record."""

    selection = base.select("S-09", S09_INPUTS)
    weak = next(item for item in selection.routed if item.identity == "K-MAT-10")
    strong = next(item for item in selection.routed if item.identity == "K-MAT-11")

    with pytest.raises(LoaderError, match="cannot reinforce itself"):
        reinforced(weak, base.record("K-MAT-10"))
    with pytest.raises(LoaderError, match="not a weak candidate"):
        reinforced(strong, base.record("K-MAT-11"))
    # K-DST-LI-03 is tier 4 and has not expired: non-expired is not enough.
    with pytest.raises(LoaderError, match="never by a weaker record"):
        reinforced(weak, base.record("K-DST-LI-03"))


def _with_expired_platform_record(register: Path) -> KnowledgeBase:
    """The same register with the tier-4 destination record past its review."""

    record = register / "records" / "dst" / "K-DST-LI-03.md"
    record.write_text(
        record.read_text(encoding="utf-8").replace(
            "review_by: 2026-12-21", "review_by: 2026-01-21", 1
        ),
        encoding="utf-8",
    )
    return load_register(register, today=TODAY)


def test_two_demoted_records_do_not_add_up_to_one(register):
    base = _with_expired_platform_record(register)
    weak = RoutedKnowledge.of_record(base.record("K-MAT-10"), applicable=True)

    assert base.record("K-DST-LI-03").is_weak is True
    with pytest.raises(LoaderError, match="itself a weak candidate"):
        reinforced(weak, base.record("K-DST-LI-03"))


def test_an_expired_rule_does_not_reinforce_a_weak_candidate(base):
    """§5 keeps an old rule's status, which is not the currency rule 3 asks for.

    `K-DST-TG-05` is a tier-1 `approved-rule` past its `review_by`, so it is
    neither weak nor of a weaker tier: nothing but the lapsed review itself
    stands between it and reinforcing `K-MAT-10` into an exclusion.
    """

    weak = RoutedKnowledge.of_record(base.record("K-MAT-10"), applicable=True)
    supporter = base.record("K-DST-TG-05")

    assert supporter.is_weak is False and supporter.expired_review is True
    with pytest.raises(LoaderError, match="past its own `review_by`"):
        reinforced(weak, supporter)
    assert may_exclude([weak]) is False


def test_a_higher_tier_may_reinforce_a_demoted_record(register):
    base = _with_expired_platform_record(register)
    demoted = RoutedKnowledge.of_record(base.record("K-DST-LI-03"), applicable=True)

    # Tier 4 reinforced by a non-expired tier 3: the same tier or a higher one.
    assert reinforced(demoted, base.record("K-MAT-11")).reinforced_by == "K-MAT-11"


def test_precedence_order_puts_the_ladder_above_the_tier_ladder(base):
    ordered = in_precedence_order(base.select("S-08", S08_INPUTS).routed)

    assert [item.identity for item in ordered][0] == "K-LAD-01"


# ----------------------------------------------------------------------
# Acceptance evidence 2: an oversized mandatory set fails closed
# ----------------------------------------------------------------------


def test_an_oversized_mandatory_set_skips_before_the_call_is_made(base):
    routing = StageRouting(run_id="r-295", plan_stage="S-08")
    selection = base.select("S-08", S08_INPUTS)
    assert {item.identity for item in selection.mandatory} == {"K-LAD-01"}

    with pytest.raises(MandatoryKnowledgeExceedsCapacity) as raised:
        _call_with(routing, "S-08", fit_to_capacity(selection, capacity=10))

    outcome = raised.value.outcome(scope_key="units/unit-295/destinations/wix")
    assert outcome.outcome is ArpOutcome.SKIP
    assert outcome.state_code is StateCode.MANDATORY_KNOWLEDGE_EXCEEDS_CAPACITY
    assert outcome.scope is OutcomeScope.DESTINATION
    assert [ref.record_id for ref in outcome.knowledge] == ["K-LAD-01"]
    # No incomplete hard-policy surface was sent, because no surface was built.
    assert routing.requests == []


def test_the_skip_names_the_sizes_it_failed_on(base):
    selection = base.select("S-08", S08_INPUTS)

    with pytest.raises(MandatoryKnowledgeExceedsCapacity) as raised:
        fit_to_capacity(selection, capacity=10)

    packing = raised.value.packing
    assert packing.capacity == 10
    assert packing.mandatory_size > packing.capacity
    assert "10" in str(raised.value) and "K-LAD-01" in str(raised.value)


def test_the_reason_category_the_skip_records_is_in_the_vocabulary(register):
    """The state code and the term the keeper reads are one word (§8, §9.6)."""

    reasons = load_vocabularies(register).get("reason_categories")

    assert reasons.term(StateCode.MANDATORY_KNOWLEDGE_EXCEEDS_CAPACITY.value)


def test_the_skip_is_at_the_scope_of_the_stage_that_failed():
    assert outcome_scope("S-04") is OutcomeScope.SIGNAL
    assert outcome_scope("S-06") is OutcomeScope.UNIT
    assert outcome_scope("S-10") is OutcomeScope.DESTINATION
    with pytest.raises(LoaderError, match="outside the run's scopes"):
        outcome_scope("S-15")


# ----------------------------------------------------------------------
# Size discipline: what may be cut, and in what order (§9.6)
# ----------------------------------------------------------------------


def test_only_descriptive_and_weaker_records_are_cut(base):
    selection = base.select("S-08", S08_INPUTS)
    mandatory_size = sum(len(item.text) for item in selection.mandatory)

    packing = fit_to_capacity(selection, capacity=mandatory_size)

    assert [item.identity for item in packing.mandatory] == ["K-LAD-01"]
    assert packing.included == ()
    assert [item.identity for item in packing.excluded] == ["K-MAT-02"]
    assert packing.size == packing.mandatory_size


def test_everything_that_fits_is_carried(base):
    selection = base.select("S-08", S08_INPUTS)

    packing = fit_to_capacity(selection, capacity=100_000)

    assert packing.excluded == ()
    assert {item.identity for item in packing.routed} == {"K-LAD-01", "K-MAT-02"}
    assert [ref.record_id for ref in packing.refs] == ["K-LAD-01", "K-MAT-02"]


def test_the_weak_end_is_what_goes_first(base):
    """Cutting in tier order is reading the precedence order backwards."""

    selection = base.select("S-09", S09_INPUTS)
    keep_one = len(
        next(item for item in selection.routed if item.identity == "K-MAT-11").text
    )

    packing = fit_to_capacity(selection, capacity=keep_one)

    assert [item.identity for item in packing.included] == ["K-MAT-11"]
    assert [item.identity for item in packing.excluded] == ["K-MAT-10"]


def test_a_stage_may_measure_a_request_its_own_way(base):
    selection = base.select("S-08", S08_INPUTS)

    packing = fit_to_capacity(
        selection, capacity=1, size_of=lambda item: 1 if item.mandatory else 5
    )

    assert packing.mandatory_size == 1 and packing.included == ()


def test_a_negative_capacity_is_refused(base):
    with pytest.raises(LoaderError, match="not negative"):
        fit_to_capacity(base.select("S-08", S08_INPUTS), capacity=-1)


# ----------------------------------------------------------------------
# The containment proof, per request (§9.6, Step 2 §0.7)
# ----------------------------------------------------------------------


def _routed(packing: KnowledgePacking) -> list[RoutedRecord]:
    return [
        RoutedRecord(
            identity=item.identity,
            version=item.version,
            tier=item.record.tier.value if item.record else "",
            effective_status=(
                item.record.effective_status.value if item.record else ""
            ),
            digest=item.digest,
            text=item.text,
            mandatory=item.mandatory,
            expired_review=item.expired_review,
        )
        for item in packing.routed
    ]


def test_a_request_that_carried_its_knowledge_proves_it(base):
    routing = StageRouting(run_id="r-295", plan_stage="S-08")
    packing = fit_to_capacity(base.select("S-08", S08_INPUTS), capacity=100_000)
    routing.route_knowledge("S-08", _routed(packing))

    request = _call_with(routing, "S-08", packing)

    assert request.state == COMPLETE
    assert set(request.knowledge_contained) == {"K-LAD-01", "K-MAT-02"}
    assert request.mandatory_missing == ()
    assert routing.knowledge_delivered_to("S-08") == request.knowledge_contained


def test_a_request_that_dropped_a_mandatory_record_says_which(base):
    routing = StageRouting(run_id="r-295", plan_stage="S-08")
    packing = fit_to_capacity(base.select("S-08", S08_INPUTS), capacity=100_000)
    routing.route_knowledge("S-08", _routed(packing))

    request = routing.observe(
        "S-08",
        user="\n\n".join(
            item.text for item in packing.routed if item.identity != "K-LAD-01"
        ),
    )

    assert request.state == INCOMPLETE
    assert request.knowledge_missing == ("K-LAD-01",)
    assert request.mandatory_missing == ("K-LAD-01",)


def test_a_label_the_request_carried_is_recorded_as_a_violation(base):
    """AD-07: labels are written after the decision and never reach S-00…S-13."""

    routing = StageRouting(run_id="r-295", plan_stage="S-08")
    packing = fit_to_capacity(base.select("S-08", S08_INPUTS), capacity=100_000)
    routing.route_knowledge("S-08", _routed(packing))
    routing.forbid("S-08", base.forbidden_terms)

    clean = _call_with(routing, "S-08", packing)
    leaked = routing.observe(
        "S-08",
        user="\n\n".join(item.text for item in packing.routed)
        + "\n\nThe material label is Teardown, so open on the failure.",
    )

    assert clean.forbidden_present == () and clean.state == COMPLETE
    assert set(leaked.forbidden_present) == {"material_label", "Teardown"}
    assert leaked.state == VIOLATION
    assert routing.violations() == (leaked,)


def test_the_routing_record_carries_no_record_text(base):
    routing = StageRouting(run_id="r-295", plan_stage="S-08")
    packing = fit_to_capacity(base.select("S-08", S08_INPUTS), capacity=100_000)
    routing.route_knowledge("S-08", _routed(packing))
    _call_with(routing, "S-08", packing)

    flattened = json.dumps(routing.as_evidence(), ensure_ascii=False)

    assert "K-LAD-01" in flattened
    assert base.record("K-LAD-01").routed_text.split("\n")[0] not in flattened


# ----------------------------------------------------------------------
# Acceptance evidence 3: the fixture trace
# ----------------------------------------------------------------------


def _run_context(run_id: str) -> RunContext:
    return RunContext(
        run_id=run_id,
        assignment_id="sig-295",
        started_at=TS_UTC,
        strategy_ref="never-blank",
        strategy_version="1.0.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
        configuration_identity=ConfigurationIdentity(
            schema_version="1.0",
            configuration_id="never-blank",
            configuration_version="1.0.0",
            configuration_hash="sha256:" + "a" * 64,
        ),
    )


class Trace(NamedTuple):
    """One written run, and the one StageRecord in its trace."""

    run_dir: Path
    record: dict


def _fixture_trace(base: KnowledgeBase, tmp_path: Path) -> Trace:
    """One S-09 execution, written the way a run writes it, and read back."""

    selection = base.select("S-09", S09_INPUTS)
    strong = next(item for item in selection.routed if item.identity == "K-MAT-11")
    weak = next(item for item in selection.routed if item.identity == "K-MAT-10")
    supported = reinforced(weak, base.record("K-MAT-11"))

    routing = StageRouting(run_id="", plan_stage="S-09")
    packing = fit_to_capacity(selection, capacity=100_000)
    routing.route_knowledge("S-09", _routed(packing))
    _call_with(routing, "S-09", packing)

    run_id = create_run_id()
    routing.run_id = run_id
    workspace = RunWorkspace.create(tmp_path / "editorial_runs", run_id)
    entry = workspace.write_stage_record(
        StageRecord(
            run_id=run_id,
            seq=0,
            stage="S-09",
            scope_key="units/unit-295/destinations/wix",
            started_at=TS_UTC,
            ended_at=TS_UTC + timedelta(seconds=30),
            created_by=StageAttribution(
                stage="S-09",
                component="strategy-selection",
                decider=DeciderKind.RULE,
                request_digest=None,
            ),
            routing=routing.as_evidence(),
            outcomes=(
                OutcomeRecord(
                    outcome=ArpOutcome.DEGRADE,
                    state_code=StateCode.PLATFORM_KNOWLEDGE_EXPIRED,
                    scope=OutcomeScope.DESTINATION,
                    reason="a demoted record was the only support for the move",
                    knowledge=(supported.ref(),),
                ),
            ),
            precedence=(
                PrecedenceApplication(
                    conflict="compare the items, or follow the mechanism through one",
                    winner=strong.ref(),
                    loser=weak.ref(),
                    rule_applied=WEAK_CANDIDATE_LOSES_ITS_TIER,
                ),
            ),
            status=StageStatus.COMPLETED,
        )
    )
    workspace.write_manifest(_run_context(run_id))
    return Trace(
        run_dir=workspace.run_dir,
        record=json.loads(
            (workspace.run_dir / entry.path).read_text(encoding="utf-8")
        ),
    )


def test_the_trace_shows_both_statuses_and_the_reinforcement(base, tmp_path):
    record = _fixture_trace(base, tmp_path).record

    demoted = record["outcomes"][0]["knowledge"][0]
    assert demoted["record_id"] == "K-MAT-10"
    assert demoted["file_status"] == "candidate"
    assert demoted["effective_status"] == "weak-candidate"
    assert demoted["reinforced_by"] == "K-MAT-11"
    assert demoted["tier"] == "3" and demoted["record_version"] == 1


def test_the_trace_shows_the_demoted_record_losing_its_conflict(base, tmp_path):
    record = _fixture_trace(base, tmp_path).record

    application = record["precedence"][0]
    assert application["winner"]["record_id"] == "K-MAT-11"
    assert application["winner"]["effective_status"] == "descriptive"
    assert application["loser"]["effective_status"] == "weak-candidate"
    assert application["rule_applied"] == WEAK_CANDIDATE_LOSES_ITS_TIER


def test_the_trace_shows_which_records_the_request_actually_carried(base, tmp_path):
    record = _fixture_trace(base, tmp_path).record

    routed = {item["record"]: item for item in record["routing"]["knowledge"]["S-09"]}
    assert routed["K-MAT-10"]["effective_status"] == "weak-candidate"
    assert routed["K-MAT-10"]["expired_review"] is True
    assert routed["K-MAT-11"]["expired_review"] is False
    assert record["routing"]["requests"][0]["state"] == COMPLETE
    assert record["routing"]["requests"][0]["mandatory_missing"] == []


def test_the_run_reads_its_own_precedence_log_back(base, tmp_path):
    """U-3: the log is the ordered view over the trace, not a second file."""

    run_dir = _fixture_trace(base, tmp_path).run_dir
    records = [
        StageRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted((run_dir / "trace").glob("*.json"))
    ]

    entries = precedence_log(records)

    assert [entry.stage for entry in entries] == ["S-09"]
    assert entries[0].application.loser.record_id == "K-MAT-10"
    assert entries[0].application.rule_applied == WEAK_CANDIDATE_LOSES_ITS_TIER


# ----------------------------------------------------------------------
# What the loader refuses
# ----------------------------------------------------------------------


def test_a_register_the_validator_would_have_refused_does_not_load(register):
    record = register / "records" / "mat" / "K-MAT-10.md"
    record.write_text(
        record.read_text(encoding="utf-8").replace(
            "review_by: 2026-03-01", "review_by: soon", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(LoaderError, match="expiry is computed from it"):
        load_register(register, today=TODAY)


def test_a_condition_that_does_not_parse_does_not_load(register):
    record = register / "records" / "mat" / "K-MAT-10.md"
    record.write_text(
        record.read_text(encoding="utf-8").replace(
            "feature parallel_structure is yes", "material_label is Teardown", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(LoaderError, match="I-10"):
        load_register(register, today=TODAY)


def test_a_file_cannot_hand_the_loader_the_status_the_loader_computes(register):
    """§2.3: `weak-candidate` is set by the loader and never written in a file."""

    record = register / "records" / "mat" / "K-MAT-10.md"
    record.write_text(
        record.read_text(encoding="utf-8").replace(
            "status: candidate", "status: weak-candidate", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(LoaderError, match="never written in"):
        load_register(register, today=TODAY)


def test_a_check_has_no_knowledge_ref_of_its_own(base):
    check = next(
        item
        for item in base.select("S-13", S09_INPUTS).mandatory
        if item.identity == "V-T01"
    )

    with pytest.raises(LoaderError, match="KnowledgeRef records"):
        check.ref()


def test_the_rule_that_limits_a_weak_candidate_is_named_for_the_log():
    """The PrecedenceLog says which limit decided, not just "precedence"."""

    assert "§5.1 rule 1" in WEAK_CANDIDATE_ALONE
    assert "§5.1 rule 2" in WEAK_CANDIDATE_LOSES_ITS_TIER
    assert "§5.1 rule 3" in WEAK_CANDIDATE_REINFORCED


def test_the_label_vocabulary_arrives_with_the_register(base):
    """A stage does not have to remember to fetch what it may not carry."""

    assert "material_label" in base.forbidden_terms
    assert "Teardown" in base.forbidden_terms
