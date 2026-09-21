"""Issue #290: "one canonical engine" as a checkable property.

CE-1 is a sentence until something can fail on it. These scenarios prove the
three claims the registry and the digest are supposed to support:

- the registry states the whole S-00 … S-15 contract once — order, scopes,
  barrier B1, the permitted backward routes and the counters they spend;
- the digest identifies the *allowed* topology and not the executed path
  (clarification C-1): two runs with different configurations, and a run that
  REPLANs against a run that SKIPs a destination, all carry the same digest;
- a run whose digest differs from the registry fails verification instead of
  being read as evidence of a canonical run.

The placement rule, CE-1's third mechanism, is in
``tests/test_290_ce1_placement.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from src.editorial_core.topology import (
    CANONICAL_TOPOLOGY,
    EDITORIAL_CORE_STAGE_IDS,
    Counter,
    CounterScope,
    ReplanRoute,
    Stage,
    StageScope,
    StageTopology,
    TerminalOutcome,
    topology_digest,
)
from src.run.code_identity import CLEAN_POLICY, CodeIdentity
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_manifest import (
    RunManifest,
    TopologyDigestMismatchError,
    verify_topology_digest,
)
from src.strategy.execution_context import ConfigurationIdentity

TS_UTC = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)


def _configuration(lens: str) -> ConfigurationIdentity:
    """A configuration identity differing only in what its hash covers.

    The editorial lens lives inside the business configuration, so two lens
    settings are two configuration hashes.
    """
    return ConfigurationIdentity(
        schema_version="1.0",
        configuration_id="never-blank",
        configuration_version="1.0.0",
        configuration_hash="sha256:" + (lens * 64)[:64],
    )


def _run_context(lens: str = "a") -> RunContext:
    return RunContext(
        run_id=create_run_id(),
        assignment_id="sig-290",
        started_at=TS_UTC,
        strategy_ref="never-blank",
        strategy_version="1.0.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
        configuration_identity=_configuration(lens),
    )


def _variant(**overrides: Any) -> StageTopology:
    """The canonical topology with some part replaced, revalidated."""
    fields: dict[str, Any] = {
        "stages": CANONICAL_TOPOLOGY.stages,
        "barriers": CANONICAL_TOPOLOGY.barriers,
        "counters": CANONICAL_TOPOLOGY.counters,
        "replan_routes": CANONICAL_TOPOLOGY.replan_routes,
    }
    fields.update(overrides)
    return StageTopology(**fields)


# ===========================================================================
# The registry states the contract once
# ===========================================================================


def test_the_registry_defines_the_sixteen_stages_once_in_order():
    assert CANONICAL_TOPOLOGY.stage_ids == tuple(f"S-{n:02d}" for n in range(16))


def test_each_stage_runs_at_its_contracted_scope():
    by_scope: dict[StageScope, list[str]] = {}
    for stage in CANONICAL_TOPOLOGY.stages:
        by_scope.setdefault(stage.scope, []).append(stage.stage_id)

    assert by_scope == {
        StageScope.SIGNAL: ["S-00", "S-01", "S-02", "S-03", "S-04", "S-05"],
        StageScope.UNIT: ["S-06", "S-07"],
        StageScope.DESTINATION: [
            "S-08", "S-09", "S-10", "S-11", "S-12", "S-13",
        ],
        StageScope.PUBLICATION: ["S-14"],
        StageScope.POST_RUN: ["S-15"],
    }


def test_the_editorial_core_is_s00_to_s13():
    # the scope the placement rule governs, derived from the registry rather
    # than listed a second time
    assert EDITORIAL_CORE_STAGE_IDS == tuple(f"S-{n:02d}" for n in range(14))


def test_barrier_b1_holds_every_writer_until_the_unit_agrees():
    (b1,) = CANONICAL_TOPOLOGY.barriers
    assert (b1.barrier_id, b1.scope, b1.evaluated_at, b1.blocks) == (
        "B1", StageScope.UNIT, "S-11", "S-12",
    )


def test_every_counter_has_its_step2_scope_and_default():
    assert {c.counter_id: (c.scope, c.default_limit) for c in CANONICAL_TOPOLOGY.counters} == {
        "L_enrich": (CounterScope.SIGNAL, 2),
        "L_boundary": (CounterScope.UNIT, 1),
        "L_anchor": (CounterScope.UNIT, 1),
        "L_strategy": (CounterScope.DESTINATION, 2),
        "L_edit": (CounterScope.TEXT, 1),
    }


def test_the_backward_routes_are_the_step2_route_table():
    assert {
        (route.source, route.target, route.counter)
        for route in CANONICAL_TOPOLOGY.backward_routes
    } == {
        ("S-06", "S-03", "L_enrich"),
        ("S-09", "S-06", "L_anchor"),
        ("S-09", "S-08", "L_strategy"),
        ("S-10", "S-08", "L_strategy"),
        ("S-11", "S-08", "L_strategy"),
        ("S-12", "S-08", "L_strategy"),
        ("S-13", "S-12", "L_edit"),
        ("S-13", "S-08", "L_strategy"),
        ("S-13", "S-04", "L_boundary"),
    }


def test_every_backward_route_goes_upstream_and_spends_a_counter():
    # the termination argument: no backward edge is free, so no path loops
    order = CANONICAL_TOPOLOGY.stage_ids
    counters = {counter.counter_id for counter in CANONICAL_TOPOLOGY.counters}
    for route in CANONICAL_TOPOLOGY.backward_routes:
        assert order.index(route.target) < order.index(route.source)
        assert route.counter in counters
        assert route.on_exhaustion in TerminalOutcome


def test_no_route_ever_asks_the_writer_to_repair_a_decision():
    # I-09: S-12 is entered from S-13 only for phrasing and removable facts
    into_the_writer = [r for r in CANONICAL_TOPOLOGY.replan_routes if r.target == "S-12"]
    assert [r.cause for r in into_the_writer] == ["phrasing_or_removable_fact"]


def test_no_outcome_in_the_registry_waits_for_a_human():
    # I-01: every way a route can end is an ARP outcome with a recorded
    # reason. Adding a "hold" or an "awaiting owner" would fail here.
    assert all(
        outcome.value.startswith(("skip_", "degrade_"))
        for outcome in TerminalOutcome
    )


def test_a_route_to_a_stage_the_registry_does_not_define_is_refused():
    without_enrichment = tuple(
        stage for stage in CANONICAL_TOPOLOGY.stages if stage.stage_id != "S-03"
    )
    with pytest.raises(ValueError, match="unknown stage"):
        _variant(stages=without_enrichment)


def test_a_counter_no_route_spends_is_refused():
    with pytest.raises(ValueError, match="spent by none"):
        _variant(counters=CANONICAL_TOPOLOGY.counters + (
            Counter(counter_id="L_invented", scope=CounterScope.UNIT, default_limit=1),
        ))


def test_stages_out_of_execution_order_are_refused():
    reversed_stages = tuple(reversed(CANONICAL_TOPOLOGY.stages))
    with pytest.raises(ValueError, match="execution order"):
        _variant(stages=reversed_stages)


# ===========================================================================
# Acceptance: two configurations, one digest
# ===========================================================================


def test_two_lens_settings_produce_the_same_topology_digest():
    first = RunManifest.for_run(_run_context(lens="a"))
    second = RunManifest.for_run(_run_context(lens="b"))

    assert (
        first.run_context.configuration_identity
        != second.run_context.configuration_identity
    )
    assert first.topology_digest == second.topology_digest == topology_digest()


def test_documentation_and_tunable_limits_stay_out_of_the_digest():
    renamed = _variant(stages=tuple(
        Stage(stage_id=stage.stage_id, name=f"{stage.name} (renamed)", scope=stage.scope)
        for stage in CANONICAL_TOPOLOGY.stages
    ))
    retuned = _variant(counters=tuple(
        Counter(
            counter_id=counter.counter_id,
            scope=counter.scope,
            default_limit=counter.default_limit + 3,
        )
        for counter in CANONICAL_TOPOLOGY.counters
    ))

    # a clearer stage name and a raised attempt limit are not a second engine
    assert topology_digest(renamed) == topology_digest()
    assert topology_digest(retuned) == topology_digest()


def test_a_changed_topology_changes_the_digest():
    without_the_edit_route = _variant(replan_routes=tuple(
        route for route in CANONICAL_TOPOLOGY.replan_routes if route.target != "S-12"
    ) + (
        # keep L_edit spent, so the change under test is the route, not the
        # registry becoming invalid
        ReplanRoute(
            source="S-13", target="S-10", cause="phrasing_or_removable_fact",
            counter="L_edit", on_exhaustion=TerminalOutcome.SKIP_PUBLICATION,
        ),
    ))

    assert topology_digest(without_the_edit_route) != topology_digest()


# ===========================================================================
# Acceptance: a REPLAN and a destination SKIP share one digest (C-1)
# ===========================================================================

#: One destination, sent back to S-08 by its plan check and re-planned.
_REPLANNED_RUN = (
    ("S-00", "signal"), ("S-01", "signal"), ("S-02", "signal"),
    ("S-03", "signal"), ("S-04", "signal"), ("S-05", "signal"),
    ("S-06", "unit"), ("S-07", "unit"),
    ("S-08", "wix"), ("S-09", "wix"), ("S-10", "wix"), ("S-11", "wix"),
    ("S-08", "wix"), ("S-09", "wix"), ("S-10", "wix"), ("S-11", "wix"),
    ("S-12", "wix"), ("S-13", "wix"), ("S-14", "wix"),
)

#: Two eligible destinations, of which Telegram is skipped at S-07 and so
#: never enters S-08; no enrichment round was needed either.
_RUN_WITH_A_SKIPPED_DESTINATION = (
    ("S-00", "signal"), ("S-01", "signal"), ("S-02", "signal"),
    ("S-04", "signal"), ("S-05", "signal"),
    ("S-06", "unit"), ("S-07", "unit"),
    ("S-08", "wix"), ("S-09", "wix"), ("S-10", "wix"), ("S-11", "wix"),
    ("S-12", "wix"), ("S-13", "wix"), ("S-14", "wix"),
)


def _is_permitted(trace: tuple[tuple[str, str], ...]) -> bool:
    return all(
        CANONICAL_TOPOLOGY.permits_transition(before[0], after[0])
        for before, after in zip(trace, trace[1:])
    )


def test_both_executed_paths_are_ones_the_registry_permits():
    assert _REPLANNED_RUN != _RUN_WITH_A_SKIPPED_DESTINATION
    assert _is_permitted(_REPLANNED_RUN)
    assert _is_permitted(_RUN_WITH_A_SKIPPED_DESTINATION)


def test_a_replan_and_a_skipped_destination_carry_the_same_digest():
    digests: set[str] = set()
    for trace in (_REPLANNED_RUN, _RUN_WITH_A_SKIPPED_DESTINATION):
        assert _is_permitted(trace)
        # nothing about the executed path reaches the manifest: the digest is
        # computed from the registry, which is why the two agree (C-1)
        digests.add(RunManifest.for_run(_run_context()).topology_digest)

    assert digests == {topology_digest()}


def test_an_undeclared_backward_move_is_not_a_permitted_transition():
    assert CANONICAL_TOPOLOGY.permits_transition("S-13", "S-12")  # declared edit route
    assert CANONICAL_TOPOLOGY.permits_transition("S-00", "S-04")  # forward past a SKIP
    assert not CANONICAL_TOPOLOGY.permits_transition("S-14", "S-00")
    assert not CANONICAL_TOPOLOGY.permits_transition("S-12", "S-10")


def test_a_transition_from_an_unknown_stage_is_refused():
    with pytest.raises(KeyError, match="unknown stage"):
        CANONICAL_TOPOLOGY.permits_transition("S-08", "S-99")


# ===========================================================================
# Acceptance: a divergent digest fails verification
# ===========================================================================


def test_every_manifest_carries_the_registry_digest_by_construction():
    manifest = RunManifest.for_run(_run_context())

    assert manifest.topology_digest == topology_digest()
    verify_topology_digest(manifest)  # does not raise


def test_a_run_whose_digest_differs_from_the_registry_fails_verification():
    stale = RunManifest.for_run(_run_context()).to_dict()
    stale["topology_digest"] = "sha256:" + "0" * 64

    manifest = RunManifest.from_dict(stale)  # readable, for forensics

    with pytest.raises(TopologyDigestMismatchError, match="canonical"):
        verify_topology_digest(manifest)


def test_a_manifest_round_trips_through_its_serialization():
    identity = CodeIdentity(
        commit_sha="0" * 40, tracked_worktree_clean=True, clean_policy=CLEAN_POLICY,
    )
    original = RunManifest.for_run(_run_context(), code_identity=identity)

    restored = RunManifest.from_dict(original.to_dict())

    assert restored == original
    verify_topology_digest(restored)


def test_a_manifest_without_a_topology_digest_is_refused():
    incomplete = RunManifest.for_run(_run_context()).to_dict()
    del incomplete["topology_digest"]

    with pytest.raises(ValueError, match="topology_digest"):
        RunManifest.from_dict(incomplete)
