"""S-13 verifies every text and routes each failure to the layer that decided it.

Issue #307, slice SL-6. The three things these tests are really about:

**Three routes at three different scopes.** S-13 is destination-scoped and spends
`L_edit` (text), `L_strategy` (destination) and `L_boundary` (unit). The ledger
keys on `(counter_id, scope_key)` and validates only that the key is a non-empty
string, so a key of the wrong shape is spent silently — which is what #304's
defect was. Every route test therefore asserts the **exact** scope key, not just
the counter name and the target.

**`L_edit` is 1 per approved plan**, not per text version. `E-15.version` is "+1
per edit", so keying on the text would mint a fresh allowance with every edit.

**A branch decision is recorded, never inferred.** V-T01 and V-T08 route by
`fault_owner`, and patch R2 asks for the owner, the branch name and the criterion.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

import pytest

from src.editorial_core.arp import (
    ArpOutcome,
    AttemptCounterLedger,
    OutcomeScope,
    StateCode,
)
from src.editorial_core.destinations import Destination, destination_scope_key
from src.editorial_core.plan_check import (
    CheckOutcome,
    FaultOwner,
)
from src.editorial_core.text_check import (
    BOUNDARY_COUNTER,
    EDIT_COUNTER,
    STRATEGY_COUNTER,
    CALLS_PER_TEXT_VERSION,
    PriorPublication,
    TextCheckError,
    TextResult,
    affected_siblings,
    check_text,
    edit_scope_key,
    recheck_siblings_after_boundary_commit,
    CALLS_PER_SIBLING_RECHECK,
    shingles,
    text_check_records,
)
from src.editorial_core.writer import Text, revise_prose
from tests.test_306_writer import (
    CHECKS as _PLAN_CHECKS,  # noqa: F401 — imported for its register side effects
    VOICE_TEXT,
    _approved,
    _barrier,
    _brief,
    _core,
    _ledger,
    _prose,
    _Transport as _WriterTransport,
    _two_readings,
    _write,
)

from pathlib import Path

from src.knowledge.loader import load_register

_REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKS = text_check_records(load_register(_REPO_ROOT / "knowledge"))


# ── fixtures ───────────────────────────────────────────────────────────────


def _passing() -> dict[str, Any]:
    return {
        "v_t01": {"holds": True, "findings": []},
        "v_t02": {"holds": True, "findings": []},
        "v_t03": {"holds": True, "findings": []},
    }


def _passing_execution() -> dict[str, Any]:
    return {
        "v_t06": {"holds": True, "findings": []},
        "v_t07": {"holds": True, "findings": []},
        "v_t08": {"holds": True, "findings": []},
    }


class _Transport:
    """Two canned answers, returned in call order, with the count kept."""

    def __init__(
        self,
        truth: Optional[dict[str, Any]] = None,
        execution: Optional[dict[str, Any]] = None,
        *,
        fails: bool = False,
    ) -> None:
        self.answers = [truth or _passing(), execution or _passing_execution()]
        self.fails = fails
        self.calls = 0

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls += 1
        if self.fails:
            raise RuntimeError("the provider refused")
        answer = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        return json.dumps(answer)


def _written(destination: Destination = Destination.LINKEDIN):
    """One accepted first version, from the real S-12 path."""

    decision = _write(transport=_WriterTransport(_prose()), destination=destination)
    assert decision.text is not None
    return decision.text


def _checked(
    *,
    text: Optional[Text] = None,
    truth: Optional[dict[str, Any]] = None,
    execution: Optional[dict[str, Any]] = None,
    counters: Optional[AttemptCounterLedger] = None,
    priors: Sequence[PriorPublication] = (),
    transport: Optional[_Transport] = None,
    destination: Destination = Destination.LINKEDIN,
):
    boundary = _two_readings()
    _, plan, _ = _approved(destination, boundary=boundary)
    subject = text or _written(destination)
    used = transport or _Transport(truth, execution)
    return (
        check_text(
            text=subject,
            plan=plan,
            boundary=boundary,
            core=_core(),
            forbidden=(),
            checks=CHECKS,
            counters=counters or _ledger(),
            transport=used,
            priors=priors,
        ),
        used,
        plan,
        subject,
    )


# ── the scope keys, which is where #304 went wrong ─────────────────────────


def test_l_edit_is_keyed_on_the_approved_plan_not_the_text_version():
    """§0.3: `L_edit | text | 1 per approved plan`."""

    assert edit_scope_key(("plan-abc", 2)) == "plan-abc/v2"
    # the text's own version is nowhere in it
    assert "txt" not in edit_scope_key(("plan-abc", 2))
    with pytest.raises(TextCheckError, match="per approved plan"):
        edit_scope_key(("", 2))


def test_a_text_fault_routes_to_s12_on_l_edit_keyed_to_the_plan():
    """Acceptance: a misquoted figure is the Writer's, and comes back as an edit."""

    counters = _ledger()
    decision, transport, plan, text = _checked(
        truth={
            "v_t01": {
                "holds": False,
                "findings": [
                    {"detail": "the text says 48 million; the core says 4.8 million",
                     "branch": "removable"}
                ],
            },
            "v_t02": {"holds": True, "findings": []},
            "v_t03": {"holds": True, "findings": []},
        },
        counters=counters,
    )

    verdict = decision.verdict
    assert verdict.result is TextResult.EDIT
    assert verdict.counter == EDIT_COUNTER
    assert verdict.outcome is not None
    assert verdict.outcome.outcome is ArpOutcome.REPLAN
    assert verdict.outcome.route_target == "S-12"
    assert verdict.outcome.counter == EDIT_COUNTER
    # the exact key, and it is the plan's
    assert verdict.outcome.scope_key == edit_scope_key(plan.plan_ref)
    assert counters.used(EDIT_COUNTER, edit_scope_key(plan.plan_ref)) == 1
    # and nothing else was spent
    assert counters.used(STRATEGY_COUNTER, plan.scope_key) == 0
    assert counters.used(BOUNDARY_COUNTER, text.unit_id) == 0


def test_a_load_bearing_fact_routes_to_s08_on_l_strategy():
    """Acceptance: the plan required material the core does not hold."""

    counters = _ledger()
    decision, _, plan, text = _checked(
        truth={
            "v_t01": {
                "holds": False,
                "findings": [
                    {"detail": "the thesis rests on a figure the core does not hold",
                     "branch": "load_bearing"}
                ],
            },
            "v_t02": {"holds": True, "findings": []},
            "v_t03": {"holds": True, "findings": []},
        },
        counters=counters,
    )

    verdict = decision.verdict
    assert verdict.result is TextResult.REPLAN
    assert verdict.counter == STRATEGY_COUNTER
    assert verdict.outcome is not None
    assert verdict.outcome.route_target == "S-08"
    assert verdict.outcome.scope_key == destination_scope_key(
        text.unit_id, text.destination
    )
    assert counters.used(STRATEGY_COUNTER, plan.scope_key) == 1
    assert counters.used(EDIT_COUNTER, edit_scope_key(plan.plan_ref)) == 0


def test_an_inadmissible_interpretation_routes_to_s04_on_l_boundary():
    """Acceptance: V-T02, and the counter is the unit's."""

    counters = _ledger()
    decision, _, plan, text = _checked(
        truth={
            "v_t01": {"holds": True, "findings": []},
            "v_t02": {
                "holds": False,
                "findings": [{"detail": "the text asserts a reading the boundary refused",
                              "interpretation_ref": "int-2"}],
            },
            "v_t03": {"holds": True, "findings": []},
        },
        counters=counters,
    )

    verdict = decision.verdict
    assert verdict.counter == BOUNDARY_COUNTER
    assert verdict.outcome is not None
    assert verdict.outcome.route_target == "S-04"
    assert verdict.outcome.scope_key == text.unit_id
    assert verdict.outcome.state_code is StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION
    assert counters.used(BOUNDARY_COUNTER, text.unit_id) == 1
    assert counters.used(EDIT_COUNTER, edit_scope_key(plan.plan_ref)) == 0
    assert counters.used(STRATEGY_COUNTER, plan.scope_key) == 0


def test_the_three_counters_do_not_mix_scope_semantics():
    """One ledger, three routes, three keys, and none consumes another."""

    counters = _ledger()
    _, _, plan, text = _checked(
        truth={
            "v_t01": {"holds": True, "findings": []},
            "v_t02": {"holds": False, "findings": [{"detail": "inadmissible"}]},
            "v_t03": {"holds": True, "findings": []},
        },
        counters=counters,
    )

    keys = {
        EDIT_COUNTER: edit_scope_key(plan.plan_ref),
        STRATEGY_COUNTER: destination_scope_key(text.unit_id, text.destination),
        BOUNDARY_COUNTER: text.unit_id,
    }
    assert len(set(keys.values())) == 3
    assert counters.used(BOUNDARY_COUNTER, keys[BOUNDARY_COUNTER]) == 1
    assert counters.used(EDIT_COUNTER, keys[EDIT_COUNTER]) == 0
    assert counters.used(STRATEGY_COUNTER, keys[STRATEGY_COUNTER]) == 0


def test_a_version_bump_cannot_mint_another_l_edit():
    """The allowance belongs to the plan, so v2 finds it already spent."""

    counters = _ledger()
    _, _, plan, first = _checked(
        truth={
            "v_t01": {"holds": False,
                      "findings": [{"detail": "phrasing", "branch": "removable"}]},
            "v_t02": {"holds": True, "findings": []},
            "v_t03": {"holds": True, "findings": []},
        },
        counters=counters,
    )
    key = edit_scope_key(plan.plan_ref)
    assert counters.used(EDIT_COUNTER, key) == 1

    second = Text(
        text_id=first.text_id,
        version=first.version + 1,
        unit_id=first.unit_id,
        destination=first.destination,
        plan_ref=first.plan_ref,
        segments=first.segments,
        writer_signal=first.writer_signal,
        inputs=first.inputs,
        links=first.links,
        title=first.title,
        dek=first.dek,
        supersedes=first.text_ref,
    )
    decision, _, _, _ = _checked(
        text=second,
        truth={
            "v_t01": {"holds": False,
                      "findings": [{"detail": "phrasing again", "branch": "removable"}]},
            "v_t02": {"holds": True, "findings": []},
            "v_t03": {"holds": True, "findings": []},
        },
        counters=counters,
    )

    # the key did not change with the version
    assert edit_scope_key(second.plan_ref) == key
    # and the second edit is refused: the publication is skipped, not re-edited
    verdict = decision.verdict
    assert verdict.result is TextResult.SKIP
    assert verdict.outcome is not None
    assert verdict.outcome.outcome is not ArpOutcome.REPLAN
    assert counters.used(EDIT_COUNTER, key) == 1


def test_a_sibling_destination_does_not_consume_another_s_allowance():
    counters = _ledger()
    _, _, li_plan, _ = _checked(
        truth={
            "v_t01": {"holds": False,
                      "findings": [{"detail": "phrasing", "branch": "removable"}]},
            "v_t02": {"holds": True, "findings": []},
            "v_t03": {"holds": True, "findings": []},
        },
        counters=counters,
        destination=Destination.LINKEDIN,
    )
    _, _, wix_plan, _ = _checked(
        truth={
            "v_t01": {"holds": False,
                      "findings": [{"detail": "phrasing", "branch": "removable"}]},
            "v_t02": {"holds": True, "findings": []},
            "v_t03": {"holds": True, "findings": []},
        },
        counters=counters,
        destination=Destination.WIX,
    )

    assert edit_scope_key(li_plan.plan_ref) != edit_scope_key(wix_plan.plan_ref)
    assert counters.used(EDIT_COUNTER, edit_scope_key(li_plan.plan_ref)) == 1
    assert counters.used(EDIT_COUNTER, edit_scope_key(wix_plan.plan_ref)) == 1


# ── precedence: a decision error outranks phrasing ─────────────────────────


def test_a_replan_class_finding_outranks_an_edit_class_one():
    """§3: "A text with both an edit-class and a replan-class finding follows the
    replan route: a decision error outranks phrasing"."""

    counters = _ledger()
    decision, _, plan, text = _checked(
        truth={
            "v_t01": {"holds": False,
                      "findings": [{"detail": "phrasing", "branch": "removable"}]},
            "v_t02": {"holds": True, "findings": []},
            "v_t03": {"holds": False, "findings": [{"detail": "the chain breaks"}]},
        },
        counters=counters,
    )

    verdict = decision.verdict
    assert verdict.counter == STRATEGY_COUNTER
    assert verdict.outcome is not None and verdict.outcome.route_target == "S-08"
    # the edit-class finding is recorded, and did not spend its counter
    assert any(
        item.check_id == "V-T01" and item.result is CheckOutcome.FAIL
        for item in verdict.checks
    )
    assert counters.used(EDIT_COUNTER, edit_scope_key(plan.plan_ref)) == 0


def test_the_boundary_route_outranks_both():
    counters = _ledger()
    decision, _, plan, text = _checked(
        truth={
            "v_t01": {"holds": False,
                      "findings": [{"detail": "phrasing", "branch": "removable"}]},
            "v_t02": {"holds": False, "findings": [{"detail": "inadmissible"}]},
            "v_t03": {"holds": False, "findings": [{"detail": "chain"}]},
        },
        counters=counters,
    )

    assert decision.verdict.counter == BOUNDARY_COUNTER
    assert counters.used(BOUNDARY_COUNTER, decision.verdict.unit_id) == 1
    assert counters.used(EDIT_COUNTER, edit_scope_key(plan.plan_ref)) == 0
    assert counters.used(STRATEGY_COUNTER, plan.scope_key) == 0


# ── fault_owner is recorded on every branch decision (patch R2) ────────────


def test_every_branch_decision_records_owner_branch_and_criterion():
    for branch, owner in (("removable", FaultOwner.WRITER), ("load_bearing", FaultOwner.PLAN)):
        decision, _, _, _ = _checked(
            truth={
                "v_t01": {"holds": False,
                          "findings": [{"detail": "a figure", "branch": branch}]},
                "v_t02": {"holds": True, "findings": []},
                "v_t03": {"holds": True, "findings": []},
            }
        )
        result = next(
            item for item in decision.verdict.checks if item.check_id == "V-T01"
        )
        assert result.fault_owner is owner
        assert result.branch == branch
        assert result.criterion


def test_an_unnamed_branch_defaults_to_the_plan_not_the_writer():
    """§3: "default to the plan branch when uncertain" — I-09.

    Charging a decision error to the prose would ask the Writer to repair a
    decision it never made.
    """

    decision, _, _, _ = _checked(
        truth={
            "v_t01": {"holds": False, "findings": [{"detail": "something is off"}]},
            "v_t02": {"holds": True, "findings": []},
            "v_t03": {"holds": True, "findings": []},
        }
    )
    result = next(item for item in decision.verdict.checks if item.check_id == "V-T01")

    assert result.fault_owner is FaultOwner.PLAN
    assert result.branch == "load_bearing"
    assert decision.verdict.counter == STRATEGY_COUNTER


def test_v_t08_branches_the_same_way():
    for branch, counter in (("execution", EDIT_COUNTER), ("strategy", STRATEGY_COUNTER)):
        decision, _, _, _ = _checked(
            execution={
                "v_t06": {"holds": True, "findings": []},
                "v_t07": {"holds": True, "findings": []},
                "v_t08": {"holds": False,
                          "findings": [{"detail": "the ending recaps", "branch": branch}]},
            }
        )
        assert decision.verdict.counter == counter
        result = next(
            item for item in decision.verdict.checks if item.check_id == "V-T08"
        )
        assert result.branch == branch
        assert result.criterion


def test_a_check_result_cannot_record_an_owner_without_its_branch():
    from src.editorial_core.plan_check import CheckClass, CheckMethod, CheckResult, Finding
    from src.editorial_core.arp import KnowledgeStatus

    with pytest.raises(Exception, match="branch and criterion"):
        CheckResult(
            check_id="V-T01",
            check_class=CheckClass.HARD,
            rule_status=KnowledgeStatus.APPROVED_RULE,
            method=CheckMethod.CODE_AND_MODEL,
            result=CheckOutcome.FAIL,
            findings=(Finding(detail="x"),),
            fault_owner=FaultOwner.WRITER,
        )


# ── acceptance: no accepted text carries an inadmissible interpretation ────


def test_an_accepted_text_passed_every_hard_check():
    decision, transport, _, _ = _checked()

    verdict = decision.verdict
    assert verdict.result is TextResult.ACCEPTED
    assert verdict.accepted
    assert all(item.result is CheckOutcome.PASS for item in verdict.checks)
    assert {item.check_id for item in verdict.checks} == {
        f"V-T0{n}" for n in range(1, 9)
    }
    assert verdict.route is None and verdict.counter is None


def test_a_text_the_boundary_refuses_is_never_accepted():
    decision, _, _, _ = _checked(
        truth={
            "v_t01": {"holds": True, "findings": []},
            "v_t02": {"holds": False, "findings": [{"detail": "inadmissible reading"}]},
            "v_t03": {"holds": True, "findings": []},
        }
    )
    assert not decision.accepted
    assert decision.verdict.result is not TextResult.ACCEPTED


# ── exactly two calls, and no answer is not a pass ─────────────────────────


def test_exactly_two_calls_per_text_version():
    _, transport, _, _ = _checked()
    assert transport.calls == CALLS_PER_TEXT_VERSION == 2


def test_a_call_that_produced_no_answer_skips_the_publication():
    decision, _, plan, _ = _checked(transport=_Transport(fails=True))

    verdict = decision.verdict
    assert verdict.result is TextResult.SKIP
    assert verdict.outcome is not None
    assert verdict.outcome.state_code is StateCode.TEXT_CHECK_UNAVAILABLE
    assert verdict.outcome.scope is OutcomeScope.PUBLICATION
    assert any(item.result is CheckOutcome.NOT_ANSWERED for item in verdict.checks)


# ── V-T05: terminal, no counter, and an empty prior set is a pass ──────────


def test_a_near_exact_republication_is_terminal_and_spends_nothing():
    counters = _ledger()
    text = _written()
    prior = PriorPublication(
        fingerprint_id="fp-1",
        destination=text.destination,
        content_digest=text.content_digest,
    )
    decision, transport, plan, _ = _checked(
        text=text, counters=counters, priors=(prior,)
    )

    verdict = decision.verdict
    assert verdict.result is TextResult.SKIP
    assert verdict.outcome is not None
    assert verdict.outcome.state_code is StateCode.NEAR_EXACT_REPUBLICATION
    assert verdict.counter is None
    # terminal: no counter spent, and the calls were never made
    assert counters.used(EDIT_COUNTER, edit_scope_key(plan.plan_ref)) == 0
    assert transport.calls == 0


def test_no_prior_publication_is_a_pass_and_not_an_absent_check():
    decision, _, _, _ = _checked(priors=())

    result = next(item for item in decision.verdict.checks if item.check_id == "V-T05")
    assert result.result is CheckOutcome.PASS
    assert decision.accepted


def test_a_prior_on_another_destination_is_not_this_destination_s_duplicate():
    text = _written(Destination.LINKEDIN)
    elsewhere = PriorPublication(
        fingerprint_id="fp-wix",
        destination=Destination.WIX,
        content_digest=text.content_digest,
    )
    decision, _, _, _ = _checked(text=text, priors=(elsewhere,))

    assert decision.accepted


# ── I-10: the fingerprint projection cannot carry a label ──────────────────


def test_the_prior_publication_view_has_no_label_field():
    """E-16's access rule: "label records are never routed to S-00…S-13".

    A stage handed the whole fingerprint would route labels into a stage forbidden
    to see them, so the label is not a field of this view and cannot arrive by
    accident.
    """

    fields = set(PriorPublication.__dataclass_fields__)

    assert "label_ref" not in fields
    assert not [name for name in fields if "label" in name]


# ── V-T05 does not cite a record the register does not hold ────────────────


def test_no_check_result_cites_k_div_06():
    """V-T05's record names `K-DIV-06` in prose; the register holds no K-DIV.

    `knowledge_used` is resolved against loaded records, so citing it would fail
    on a record nobody transcribed. Transcription is #308's work.
    """

    decision, _, _, _ = _checked()
    for item in decision.verdict.checks:
        for finding in item.findings:
            assert "K-DIV" not in (finding.rule_ref or "")


# ── the precondition ───────────────────────────────────────────────────────


def test_a_refused_plan_produces_no_text_for_this_stage_to_check():
    """§3's Pre, held by the type rather than by a guard here.

    S-13 has no `plan_holds` check because it cannot need one: `Text` refuses to
    exist with `plan_holds = false`, so a plan the Writer refused never becomes an
    E-15 at all — S-12 routed it to S-08 instead. A guard that could never fire
    would read as protection where there is none.
    """

    from src.editorial_core.writer import WriterError, WriterSignal

    text = _written()
    with pytest.raises(WriterError, match="plan does not hold"):
        Text(
            text_id=text.text_id,
            version=text.version,
            unit_id=text.unit_id,
            destination=text.destination,
            plan_ref=text.plan_ref,
            segments=text.segments,
            writer_signal=WriterSignal(plan_holds=False, reason="cannot hold"),
            inputs=text.inputs,
            links=text.links,
        )


def test_a_text_and_a_plan_that_are_not_the_same_pair_are_refused():
    """The half of the Pre the type cannot hold."""

    boundary = _two_readings()
    _, wix_plan, _ = _approved(Destination.WIX, boundary=boundary)
    linkedin_text = _written(Destination.LINKEDIN)

    with pytest.raises(TextCheckError, match="is checked against the plan it"):
        check_text(
            text=linkedin_text,
            plan=wix_plan,
            boundary=boundary,
            core=_core(),
            forbidden=(),
            checks=CHECKS,
            counters=_ledger(),
            transport=_Transport(),
        )


# ── the S-12 edit entry this slice adds ───────────────────────────────────


def test_the_edit_entry_produces_the_next_version_of_the_same_text():
    """#307's interface extension: S-13's `L_edit` route has somewhere to go."""

    boundary = _two_readings()
    strategy, plan, verdict = _approved(Destination.LINKEDIN, boundary=boundary)
    prior = _written()
    decision = revise_prose(
        prior=prior,
        findings=("the text says 48 million; the core says 4.8 million",),
        plan=plan,
        verdict=verdict,
        barrier=_barrier([plan], [verdict], boundary=boundary),
        strategy=strategy,
        boundary=boundary,
        core=_core(),
        brief=_brief(),
        counters=_ledger(),
        transport=_WriterTransport(_prose()),
    )

    assert decision.text is not None
    assert decision.text.text_id == prior.text_id
    assert decision.text.version == prior.version + 1
    assert decision.text.supersedes == prior.text_ref
    assert decision.text.plan_ref == prior.plan_ref
    assert decision.calls == 1


def test_the_edit_entry_refuses_a_different_plan():
    boundary = _two_readings()
    strategy, plan, verdict = _approved(Destination.LINKEDIN, boundary=boundary)
    other = _written(Destination.WIX)

    with pytest.raises(Exception, match="same plan"):
        revise_prose(
            prior=other,
            findings=("x",),
            plan=plan,
            verdict=verdict,
            barrier=_barrier([plan], [verdict], boundary=boundary),
            strategy=strategy,
            boundary=boundary,
            core=_core(),
            brief=_brief(),
            counters=_ledger(),
            transport=_WriterTransport(_prose()),
        )


def test_the_edit_entry_refuses_an_edit_with_nothing_to_repair():
    boundary = _two_readings()
    strategy, plan, verdict = _approved(Destination.LINKEDIN, boundary=boundary)

    with pytest.raises(Exception, match="no finding"):
        revise_prose(
            prior=_written(),
            findings=(),
            plan=plan,
            verdict=verdict,
            barrier=_barrier([plan], [verdict], boundary=boundary),
            strategy=strategy,
            boundary=boundary,
            core=_core(),
            brief=_brief(),
            counters=_ledger(),
            transport=_WriterTransport(_prose()),
        )


# ── F-4: the boundary moved after a sibling was already accepted ───────────


def _at_version(boundary, version: int):
    """The same boundary, at a later version — what an S-04 re-entry leaves."""

    import dataclasses

    return dataclasses.replace(boundary, version=version)


def test_a_sibling_accepted_at_the_old_version_is_re_checked_at_the_new_one():
    """§5.4, defect F-4 — the scenario in full.

    boundary vN → sibling A accepted under vN → sibling B triggers V-T02 and an
    S-04 re-entry → boundary becomes vN+1 → A gets the **targeted truth re-check**
    against vN+1 → and if that fails, A cannot remain publishable.

    Without this, A stays accepted against a version that no longer holds: S-11's
    code checks re-run on plans and the S-12 precondition compares versions, but a
    text that already passed S-13 is looked at again by nothing else.
    """

    boundary = _two_readings()
    counters = _ledger()

    # A is accepted under vN
    a_decision, _, a_plan, a_text = _checked(
        destination=Destination.LINKEDIN, counters=counters
    )
    assert a_decision.verdict.accepted
    assert a_decision.verdict.boundary_ref == (boundary.boundary_id, boundary.version)

    # B discovers an inadmissible reading and routes to S-04, which commits vN+1
    b_decision, _, _, b_text = _checked(
        destination=Destination.WIX,
        truth={
            "v_t01": {"holds": True, "findings": []},
            "v_t02": {"holds": False, "findings": [{"detail": "a reading the boundary refuses"}]},
            "v_t03": {"holds": True, "findings": []},
        },
        counters=counters,
    )
    assert b_decision.verdict.counter == BOUNDARY_COUNTER
    assert counters.used(BOUNDARY_COUNTER, b_text.unit_id) == 1

    committed = _at_version(boundary, boundary.version + 1)

    # A is now affected: accepted, and judged against an older version
    assert affected_siblings([a_decision.verdict], committed) == (a_decision.verdict,)

    # the targeted re-check: one call, and only V-T02
    transport = _Transport()
    transport.answers = [{"v_t02": {"holds": False,
                                    "findings": [{"detail": "no longer admissible"}]}}]
    rechecked = recheck_siblings_after_boundary_commit(
        boundary=committed,
        accepted=((a_text, a_decision.verdict),),
        core=_core(),
        plans={a_text.destination: a_plan},
        checks=CHECKS,
        counters=counters,
        transport=transport,
    )

    assert len(rechecked) == 1
    verdict = rechecked[0].verdict
    # A cannot remain publishable
    assert not verdict.accepted
    assert verdict.result is not TextResult.ACCEPTED
    # and the verdict now says which boundary judged it
    assert verdict.boundary_ref == (committed.boundary_id, committed.version)
    # exactly one call, not the usual two
    assert transport.calls == CALLS_PER_SIBLING_RECHECK == 1


def test_a_sibling_that_still_holds_is_re_accepted_at_the_new_version():
    """A passing re-check is not a no-op: the verdict moves to the new version."""

    boundary = _two_readings()
    counters = _ledger()
    decision, _, plan, text = _checked(counters=counters)
    committed = _at_version(boundary, boundary.version + 1)

    transport = _Transport()
    transport.answers = [{"v_t02": {"holds": True, "findings": []}}]
    rechecked = recheck_siblings_after_boundary_commit(
        boundary=committed,
        accepted=((text, decision.verdict),),
        core=_core(),
        plans={text.destination: plan},
        checks=CHECKS,
        counters=counters,
        transport=transport,
    )

    verdict = rechecked[0].verdict
    assert verdict.accepted
    assert verdict.boundary_ref == (committed.boundary_id, committed.version)
    assert transport.calls == 1
    # a passing re-check spends no counter
    assert counters.used(BOUNDARY_COUNTER, text.unit_id) == 0


def test_a_sibling_already_at_the_current_version_is_not_re_checked():
    """It was judged against what is now true; a call would buy nothing."""

    boundary = _two_readings()
    decision, _, plan, text = _checked()

    assert affected_siblings([decision.verdict], boundary) == ()

    transport = _Transport()
    rechecked = recheck_siblings_after_boundary_commit(
        boundary=boundary,
        accepted=((text, decision.verdict),),
        core=_core(),
        plans={text.destination: plan},
        checks=CHECKS,
        counters=_ledger(),
        transport=transport,
    )

    assert rechecked == ()
    assert transport.calls == 0


def test_a_sibling_that_was_not_accepted_is_not_re_checked():
    """Only accepted texts can reach S-14, so only they need protecting from drift."""

    boundary = _two_readings()
    decision, _, plan, text = _checked(
        truth={
            "v_t01": {"holds": False,
                      "findings": [{"detail": "phrasing", "branch": "removable"}]},
            "v_t02": {"holds": True, "findings": []},
            "v_t03": {"holds": True, "findings": []},
        }
    )
    assert not decision.verdict.accepted

    committed = _at_version(boundary, boundary.version + 1)
    assert affected_siblings([decision.verdict], committed) == ()


def test_a_re_check_that_cannot_be_read_does_not_leave_the_sibling_publishable():
    """An unanswered re-check is not a passing one."""

    boundary = _two_readings()
    decision, _, plan, text = _checked()
    committed = _at_version(boundary, boundary.version + 1)

    rechecked = recheck_siblings_after_boundary_commit(
        boundary=committed,
        accepted=((text, decision.verdict),),
        core=_core(),
        plans={text.destination: plan},
        checks=CHECKS,
        counters=_ledger(),
        transport=_Transport(fails=True),
    )

    verdict = rechecked[0].verdict
    assert not verdict.accepted
    assert verdict.outcome is not None
    assert verdict.outcome.state_code is StateCode.TEXT_CHECK_UNAVAILABLE


def test_the_re_check_refuses_to_run_without_the_plan_the_text_executes():
    boundary = _two_readings()
    decision, _, _, text = _checked()
    committed = _at_version(boundary, boundary.version + 1)

    with pytest.raises(TextCheckError, match="without the approved plan"):
        recheck_siblings_after_boundary_commit(
            boundary=committed,
            accepted=((text, decision.verdict),),
            core=_core(),
            plans={},
            checks=CHECKS,
            counters=_ledger(),
            transport=_Transport(),
        )
