"""Issue #351: the canonical harness calls the real stages, and no stub survives.

The slice's first acceptance criterion is "removing one real stage call and
restoring a pass-through or static-artifact shortcut **fails a regression
test**". These are those regressions, over the harness
:mod:`src.run.golden_engine` rather than over a helper beside it:

1. **every stage of the topology is accounted for.** ``WIRED_STAGES`` is
   S-00…S-13 derived from the registry, ``UNWIRED_STAGES`` is S-14 and S-15,
   and a stage that is in neither stops the run. Dropping a stage from the
   wiring fails :func:`check_every_stage_is_wired`;
2. **every wired stage's real entry function is imported from its own module
   and called.** Not a count of imports: the table below names the function
   each stage contract declares, including the four the orchestration adds
   (``revise_prose`` for the edit loop, ``re_enter_boundary`` and
   ``recheck_siblings_after_boundary_commit`` for the F-4 re-check,
   ``run_barrier`` for B1), so deleting any one of them fails here. The
   detector carries its own planted negative, so it cannot pass by finding
   nothing;
3. **no pass-through and no legacy artifact is reachable from it.** The
   canonical harness names ``pass_through`` nowhere, carries no refusing
   provider, and never names ``generated.json`` or the two functions that read
   and write it — which is the "``generated.json`` cannot masquerade as E-15"
   criterion at the only seam a canonical run could reach it from;
4. **the two runs cannot be confused.** The pass-through run is SL-1's fixture
   proof and keeps working; its records and its entities say so, and its type
   is not the canonical one.

And the three seams the 2026-09-30 interface audit found: the ``StrengthLadder``
producer, the ``UnitFacts`` lift, and the request digest that makes a
model-deciding StageRecord provable.
"""

from __future__ import annotations

import ast
from dataclasses import MISSING
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from src.editorial_core.destinations import Destination
from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.knowledge.loader import load_register
from src.run import golden_engine
from src.run.golden_engine import (
    CANONICAL_REQUEST_SERIALIZATION,
    GOLDEN_ENGINE_COMPONENT,
    UNWIRED_STAGES,
    WIRED_STAGES,
    GoldenEngineError,
    GoldenEngineSeams,
    StageNotWiredError,
    check_every_stage_is_wired,
    request_digest,
    unit_facts,
    universal_strength_ladder,
)
from src.run.run_context import create_run_id
from src.run.run_workspace import (
    DeciderKind,
    EntityRef,
    StageAttribution,
    StageRecord,
    StageStatus,
)
from src.run.signal_adapter import DOMAIN_FIELD, RISK_FIELD
from src.run.walking_skeleton import (
    CANONICAL_DESTINATIONS,
    GOLDEN_ENGINE_STRATEGY_REF,
    PASS_THROUGH_MARKER,
    SKELETON_COMPONENT,
    GoldenEngineRun,
    SkeletonError,
    SkeletonRun,
    decided_every_destination,
    run_golden_engine,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REGISTER = _REPO_ROOT / "knowledge"

#: Fixed, so that a record whose review lapses after this date does not change
#: what these tests load. The same date #306's checks are loaded at.
TODAY = date(2026, 9, 24)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

#: The canonical harness, read as text. What is asserted about it is what it
#: can reach — a module that can reach a pass-through has one whether it calls
#: it today or not, and that is the property a run of it cannot establish.
_ENGINE_SOURCE = (_REPO_ROOT / "src" / "run" / "golden_engine.py").read_text(
    encoding="utf-8"
)


# ===========================================================================
# (1) Every stage of the topology is accounted for
# ===========================================================================


def test_the_wired_stages_are_the_editorial_core_and_s14():
    """S-00…S-13 from the registry, and S-14 since #308 wired it in shadow.

    The editorial core is still derived rather than listed a second time; S-14
    is named beside it because it is not part of that core — it makes no
    editorial decision — and it is wired all the same.
    """

    assert WIRED_STAGES == (*CANONICAL_TOPOLOGY.editorial_core_stage_ids, "S-14")
    assert UNWIRED_STAGES == ("S-15",)
    assert not set(WIRED_STAGES) & set(UNWIRED_STAGES)
    assert set(WIRED_STAGES) | set(UNWIRED_STAGES) == set(
        CANONICAL_TOPOLOGY.stage_ids
    )


def test_every_stage_the_topology_declares_is_wired_or_declared_unwired():
    check_every_stage_is_wired()


def test_a_stage_the_harness_does_not_wire_stops_the_run(monkeypatch):
    """SL-1's rule, kept: a stage quietly skipped is not the canonical engine.

    The mutation is the one the slice is afraid of — a stage dropped out of the
    wiring — and it is refused before any work is done rather than noticed in a
    folder count afterwards.
    """

    monkeypatch.setattr(golden_engine, "WIRED_STAGES", WIRED_STAGES[:-1])

    with pytest.raises(StageNotWiredError, match="S-14"):
        check_every_stage_is_wired()


def test_the_unwired_stages_are_the_two_this_slice_does_not_own():
    """S-14 is #308's and S-15 is SL-12's, and neither has an implementation.

    Named rather than silently absent: "the run ends at S-13" is a statement
    the module makes, so a later slice that implements S-14 has to move it out
    of this tuple and into the wiring, in the open.
    """

    for stage in UNWIRED_STAGES:
        assert CANONICAL_TOPOLOGY.stage(stage) is not None
        assert stage not in WIRED_STAGES


# ===========================================================================
# (2) Every wired stage's real entry function is imported and called
# ===========================================================================

#: Stage contract → the module that implements it and the function the harness
#: must call. The four entries without a plain ``S-nn`` key are the
#: orchestration this slice adds: a wiring that ran the stages in order and
#: stopped would satisfy every per-stage contract and still miss all four.
STAGE_ENTRIES: dict[str, tuple[str, str]] = {
    "S-00": ("src.editorial_core.signal_selection", "select_signal"),
    "S-01": ("src.editorial_core.evidence_core", "retrieve_evidence_core"),
    "S-01b": ("src.editorial_core.relevance_screen", "screen_relevance"),
    "S-02": ("src.editorial_core.material_features", "describe_material"),
    "S-03": ("src.editorial_core.enrichment", "enrich"),
    "S-04": (
        "src.editorial_core.interpretation_boundary",
        "decide_boundary",
    ),
    "S-04 re-entry": (
        "src.editorial_core.interpretation_boundary",
        "re_enter_boundary",
    ),
    "S-04 commit": (
        "src.editorial_core.interpretation_boundary",
        "commit_boundary_version",
    ),
    "S-05": ("src.editorial_core.editorial_units", "create_unit"),
    "S-06": ("src.editorial_core.anchor", "choose_anchor"),
    "S-07": ("src.editorial_core.destinations", "decide_destinations"),
    "S-14": ("src.editorial_core.publication", "publish_in_shadow"),
    "S-08": (
        "src.editorial_core.candidate_strategies",
        "propose_strategies",
    ),
    "S-09": ("src.editorial_core.strategy_selection", "select_strategy"),
    "S-10": ("src.editorial_core.executable_plan", "adapt_strategy"),
    "S-11": ("src.editorial_core.plan_check", "check_plan"),
    "S-11 B1": ("src.editorial_core.plan_check", "run_barrier"),
    "S-11 F-4": (
        "src.editorial_core.plan_check",
        "recheck_after_boundary_commit",
    ),
    "S-12": ("src.editorial_core.writer", "write_prose"),
    "S-12 edit": ("src.editorial_core.writer", "revise_prose"),
    "S-13": ("src.editorial_core.text_check", "check_text"),
    "S-13 siblings": (
        "src.editorial_core.text_check",
        "recheck_siblings_after_boundary_commit",
    ),
}


def _imported_from(source: str) -> dict[str, str]:
    """Every name this module imports, mapped to the module it came from."""

    found: dict[str, str] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                found[alias.asname or alias.name] = node.module
    return found


def _called(source: str) -> set[str]:
    """Every bare function name this module calls."""

    return {
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


_PLANTED = (
    "from src.editorial_core.writer import revise_prose\n"
    "revise_prose(prior=None)\n"
)

_PLANTED_IMPORT_ONLY = "from src.editorial_core.writer import revise_prose\n"


def test_the_stage_call_detector_sees_a_call_and_an_import_apart():
    """The test below cannot pass by finding an import nobody calls."""

    assert _imported_from(_PLANTED)["revise_prose"] == (
        "src.editorial_core.writer"
    )
    assert "revise_prose" in _called(_PLANTED)
    assert "revise_prose" not in _called(_PLANTED_IMPORT_ONLY)
    assert _called("") == set()


@pytest.mark.parametrize(
    ("stage", "module", "function"),
    [(stage, module, name) for stage, (module, name) in STAGE_ENTRIES.items()],
    ids=list(STAGE_ENTRIES),
)
def test_the_harness_calls_the_real_entry_function_of_every_stage(
    stage: str, module: str, function: str
):
    """Acceptance 1: restoring a shortcut in place of a stage call fails here.

    Both halves are asserted, because either alone can be true of a harness
    that does not execute the stage: the function is imported **from the module
    that implements that contract**, and it is called. An import from somewhere
    else would be a second implementation, and an import nobody calls is the
    standalone-adapter shape this slice was rejected for the first time.
    """

    imported = _imported_from(_ENGINE_SOURCE)

    assert imported.get(function) == module, (
        f"{stage}: the harness does not import {function} from {module}"
    )
    assert function in _called(_ENGINE_SOURCE), (
        f"{stage}: the harness imports {function} and never calls it"
    )


def test_every_wired_stage_has_an_entry_in_the_table():
    """The table cannot pass by leaving a stage out of itself."""

    covered = {stage.split(" ")[0] for stage in STAGE_ENTRIES}

    assert set(WIRED_STAGES) <= covered


# ===========================================================================
# (3) No pass-through and no legacy artifact is reachable
# ===========================================================================


@pytest.mark.parametrize(
    "forbidden",
    [
        PASS_THROUGH_MARKER,
        "RefusingProvider",
        "ProviderRefused",
        "SkeletonFixture",
        "generated.json",
        "load_run_generated",
        "write_generated_json",
    ],
)
def test_the_canonical_harness_cannot_reach_a_stub_or_a_legacy_package(
    forbidden: str,
):
    """Two acceptance criteria at once, at the only seam that could break them.

    ``PASS_THROUGH_MARKER`` occurring 0 times in a canonical trace is a
    property of a harness that cannot write one, and "``generated.json`` cannot
    masquerade as E-15" is a property of a harness that cannot open one. Both
    are asserted over what the module can reach rather than over one run's
    output, because a run proves it for that run and this proves it for every
    run.
    """

    assert forbidden not in _ENGINE_SOURCE


def test_the_canonical_component_is_not_the_pass_through_component():
    """A reader with one StageRecord can tell which run produced it."""

    assert GOLDEN_ENGINE_COMPONENT != SKELETON_COMPONENT
    assert GOLDEN_ENGINE_STRATEGY_REF != SKELETON_COMPONENT
    assert GoldenEngineRun is not SkeletonRun
    assert not hasattr(GoldenEngineRun, "provider")


def test_the_canonical_run_builds_no_transport_and_reads_no_model_variable():
    """#361's variable has no default anywhere, and this is where one would go.

    The harness is handed its model boundaries, so there is no construction
    point here for a fallback to be added to — and the test suite therefore
    needs no model configuration and cannot make a paid call.
    """

    # The name appears in the docstring, which is where a reader is sent to
    # find the bundle; what must not appear is a *construction* of one.
    assert "golden_engine_transports(" not in _ENGINE_SOURCE
    assert "import os" not in _ENGINE_SOURCE
    assert "os.environ" not in _ENGINE_SOURCE


def test_the_seams_are_required_and_frozen():
    """Which boundary a stage is given is decided once, at construction."""

    with pytest.raises(TypeError):
        GoldenEngineSeams()  # type: ignore[call-arg]

    fields = GoldenEngineSeams.__dataclass_fields__
    assert set(fields) == {
        "transports",
        "research",
        "eligibility",
        "evidence_judgment",
        "relevance",
    }
    # No seam has a default. A defaulted provider is the fallback #361 removed,
    # one layer up.
    assert all(item.default is MISSING for item in fields.values())
    assert GoldenEngineSeams.__dataclass_params__.frozen is True


# ===========================================================================
# (4) The StrengthLadder producer (the audit's first seam)
# ===========================================================================


def test_the_universal_ladder_is_adapted_from_the_authority_on_disk():
    """Four stages require a ladder, and this is where the one authority is read.

    The wordings are not repeated here: they are read off
    ``knowledge/ladders/default.md`` through the parser the validator already
    uses, so a keeper who rewords a level changes what a run may assert and
    this test keeps passing — which is the point of having one authority.
    """

    knowledge = load_register(_REGISTER, today=TODAY)

    ladder = universal_strength_ladder(knowledge, register_dir=_REGISTER)

    assert ladder.ladder_id == "K-LAD-01"
    assert len(ladder.levels) == 4
    assert ladder.bottom.level == 1
    assert ladder.top.level == 4
    # Weakest first, and every level is its own wording: `StrengthLadder`
    # refuses a ladder whose levels read alike, so this is the adaptation
    # having preserved the table's order rather than sorted or de-duplicated it.
    assert ladder.wording(ladder.at(1)).startswith("Reported")
    assert ladder.wording(ladder.at(4)).startswith("Established")


def test_a_register_with_no_ladder_refuses_rather_than_inventing_one(tmp_path):
    """A ceiling the engine chose for itself is a ceiling nobody approved."""

    knowledge = load_register(_REGISTER, today=TODAY)

    with pytest.raises(GoldenEngineError, match="strength ladder"):
        universal_strength_ladder(knowledge, register_dir=tmp_path)


# ===========================================================================
# (5) The UnitFacts lift (the audit's second seam)
# ===========================================================================


def test_the_unit_facts_are_lifted_from_the_fields_intake_spells():
    """S-07 compares values; it does not decide what they are."""

    facts = unit_facts({DOMAIN_FIELD: "operations", RISK_FIELD: "low"})

    assert facts.topic_key == "operations"
    assert facts.risk_level == "low"


def test_a_record_that_states_neither_fact_is_fail_closed_not_defaulted():
    """``None`` means the unit states nothing.

    Which is not the same as stating something the contract allows — a contract
    row naming refused topics cannot show that an unnamed topic is not one of
    them, so the direction that publishes nothing unproven is the safe one.
    """

    facts = unit_facts({"HEADLINE": "An unclassified historical signal."})

    assert facts.topic_key is None
    assert facts.risk_level is None


@pytest.mark.parametrize(
    "stated", ["", "   ", ["a", "b"], [], 7, None], ids=[
        "empty", "blank", "several", "none-listed", "number", "null",
    ]
)
def test_a_record_that_states_no_single_value_states_nothing(stated: Any):
    """The same discipline seam 1 applies, because it is the same function.

    A composite of two domains would look like a value a contract rule could
    be compared against and would match nothing — which is worse evidence than
    the absence, and would be read as an admitted value.
    """

    facts = unit_facts({DOMAIN_FIELD: stated, RISK_FIELD: stated})

    assert facts.topic_key is None
    assert facts.risk_level is None


def test_the_lift_reads_the_two_fields_the_adapter_binds_and_no_outcome_field():
    """#365 classifies and #363 owns the vocabulary; this reads two fields.

    The ``*_OUTCOME`` fields beside them record whether the classifier
    admitted, refused or could not answer. Reading one here would turn
    "nobody could classify it" into a value S-07 compares a contract rule
    against, which is the one confusion #365 wrote them to prevent.
    """

    read = unit_facts(
        {
            DOMAIN_FIELD: "operations",
            RISK_FIELD: "low",
            "EDITORIAL_DOMAIN_OUTCOME": "cannot_answer",
            "EDITORIAL_RISK_OUTCOME": "cannot_answer",
        }
    )

    assert (read.topic_key, read.risk_level) == ("operations", "low")
    assert "EDITORIAL_DOMAIN_OUTCOME" not in _ENGINE_SOURCE
    assert "EDITORIAL_RISK_OUTCOME" not in _ENGINE_SOURCE


# ===========================================================================
# (6) The request digest that makes a model-deciding record provable
# ===========================================================================


def test_a_request_digest_is_a_sha256_over_the_requests_that_were_sent():
    digest = request_digest((("instructions", "request"),))

    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_two_different_request_sets_do_not_share_a_digest():
    first = request_digest((("instructions", "one"),))
    second = request_digest((("instructions", "two"),))

    assert first != second


def test_the_digest_is_over_the_order_the_calls_were_made_in():
    """S-04's generate and probe, and S-13's truth and execution, are ordered.

    A digest that did not depend on the order would read two stages that asked
    the same two questions the other way round as having made the same request.
    """

    forward = request_digest((("a", "one"), ("b", "two")))
    backward = request_digest((("b", "two"), ("a", "one")))

    assert forward != backward


def test_the_digest_states_which_serialization_it_is():
    """A changed recipe is a new serialization, never a different digest of the
    same name — the precedent every digest in this repository follows."""

    assert CANONICAL_REQUEST_SERIALIZATION.endswith("-v1")
    assert CANONICAL_REQUEST_SERIALIZATION in _ENGINE_SOURCE


def test_a_stage_that_made_no_call_records_no_digest():
    """"Absent when the stage issued no model request" (§4.2).

    Asserted on the one thing a reader uses the field for: a record with a
    digest made a request, and one without did not. The fake provider of the
    SL-1 harness produces none, which is the distinction acceptance item 4
    rests on.
    """

    assert golden_engine._decider(0) is DeciderKind.CODE
    assert golden_engine._decider(1) is DeciderKind.MODEL


# ===========================================================================
# (7) The call meter: #361's binding, and what was asked of it
# ===========================================================================


class _Binding:
    """A #361-shaped binding: two strings in, one string out."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.seen.append((instructions, request))
        return "{}"


def test_the_meter_forwards_the_two_strings_unchanged():
    """A transport that trimmed, prefixed or templated either would change what
    a stage decided while every test of that stage still passed."""

    binding = _Binding()
    meter = golden_engine._CallMeter(binding)

    answer = meter.complete(instructions="  keep  ", request='{"a": 1}')

    assert answer == "{}"
    assert binding.seen == [("  keep  ", '{"a": 1}')]
    assert meter.binding is binding


def test_the_meter_windows_the_requests_of_one_execution():
    """One stage execution's digest is over its own calls and no others."""

    meter = golden_engine._CallMeter(_Binding())
    meter.complete(instructions="first", request="1")

    mark = meter.mark()
    meter.complete(instructions="second", request="2")
    meter.complete(instructions="third", request="3")

    assert meter.calls == 3
    assert meter.since(mark) == (("second", "2"), ("third", "3"))


def test_each_binding_is_metered_under_its_own_name():
    """"The named type is the unit of routing", so the meters are ten and not one.

    A harness that metered them through one object could hand the evidence
    judgment boundary to a stage that judges no evidence.
    """

    bindings = {name: _Binding() for name in golden_engine._Meters._fields}
    transports = cast(Any, type("_Bundle", (), dict(bindings)))
    meters = golden_engine._meters(transports)

    assert len(meters) == 10
    for name in golden_engine._Meters._fields:
        assert getattr(meters, name).binding is bindings[name]
    # Ten distinct meters, not one object under ten names.
    assert len({id(getattr(meters, name)) for name in meters._fields}) == 10


# ===========================================================================
# (8) Principle B, in both directions
# ===========================================================================


def test_a_canonical_run_over_fewer_than_six_destinations_is_refused(tmp_path):
    """The declaration is checked before anything exists to be cleaned up."""

    with pytest.raises(SkeletonError, match="six destinations"):
        run_golden_engine(
            seams=cast(Any, object()),
            configuration=cast(Any, object()),
            signal={},
            binding=cast(Any, object()),
            destinations=("wix", "linkedin"),
            runs_root=tmp_path / "editorial_runs",
        )

    assert not (tmp_path / "editorial_runs").exists()


def _s07_record(outputs: int) -> StageRecord:
    """One S-07 execution claiming ``outputs`` destination decisions."""

    return StageRecord(
        run_id=create_run_id(),
        seq=0,
        stage="S-07",
        scope_key="unit-351",
        started_at=NOW,
        ended_at=NOW,
        created_by=StageAttribution(
            stage="S-07",
            component=GOLDEN_ENGINE_COMPONENT,
            decider=DeciderKind.RULE,
        ),
        outputs=tuple(
            EntityRef(
                entity_type="E-12",
                entity_id=f"dst-unit-351-{index}",
                digest="sha256:" + f"{index:x}" * 64,
            )
            for index in range(outputs)
        ),
        status=StageStatus.COMPLETED,
    )


def test_a_run_that_decided_about_every_declared_destination_passes():
    decided_every_destination(
        (_s07_record(len(CANONICAL_DESTINATIONS)),), CANONICAL_DESTINATIONS
    )


def test_a_run_one_destination_decision_short_is_refused():
    """The half a destination list alone cannot give.

    A run that reached S-07 and decided about five would otherwise seal a
    verified manifest over a unit one surface short, and nothing downstream
    would notice — six folders are what a reader counts, and five decisions
    make five folders.
    """

    with pytest.raises(SkeletonError, match="destination decision"):
        decided_every_destination(
            (_s07_record(len(CANONICAL_DESTINATIONS) - 1),),
            CANONICAL_DESTINATIONS,
        )


def test_a_run_that_stopped_before_s07_is_not_short_of_decisions():
    """It has none, recorded as the SKIP that ended it."""

    decided_every_destination((), CANONICAL_DESTINATIONS)


def test_the_canonical_destination_list_is_the_one_the_repository_keeps():
    """#227: a duplicated list is a list that drifts."""

    assert len(CANONICAL_DESTINATIONS) == 6
    assert set(CANONICAL_DESTINATIONS) == {item.value for item in Destination}


# ===========================================================================
# (9) What the harness states about where it stopped
# ===========================================================================


def test_the_execution_reports_where_it_stopped_rather_than_how_far_it_got():
    """"cannot answer" and "nothing to answer" are different facts about a run.

    ``stopped_at`` names the stage that ended the run and is ``None`` for one
    that reached the end of the wired topology — so a reader of a short trace
    can tell a signal the contract refused from a run that was cut off, without
    counting records.
    """

    fields = golden_engine.CanonicalExecution._fields

    assert "stopped_at" in fields
    assert golden_engine.CanonicalExecution._field_defaults["stopped_at"] is None


def test_the_execution_reports_fingerprints_and_still_claims_no_publication():
    """E-16 is S-14's and #308 executes S-14 — in shadow, publishing nothing.

    ``accepted`` is a list of destinations holding an accepted text, which is
    not the same claim as published: a text S-13 accepted may be published and
    has not been. So the execution now carries the fingerprints S-14 wrote, and
    still carries no field named for a publication — a shadow run that reported
    one would let a reader of the ledger count it as a run that published.
    """

    fields = golden_engine.CanonicalExecution._fields

    assert "accepted" in fields
    assert "fingerprints" in fields, "#308 wired S-14, which produces E-16"
    assert "packages" in fields
    assert not [name for name in fields if "publication" in name]
