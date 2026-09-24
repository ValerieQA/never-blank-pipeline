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

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

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
    RunInputs,
    RunManifest,
    TopologyDigestMismatchError,
    verify_topology_digest,
)
from src.strategy.execution_context import ConfigurationIdentity

TS_UTC = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)

#: Every manifest states its §4.1 inputs (#336). These runs are about the
#: topology digest, which no input touches, so they state that they read none.
_INPUTS = RunInputs.stated_absent("topology fixture: no editorial input")


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
    first = RunManifest.for_run(_run_context(lens="a"), inputs=_INPUTS)
    second = RunManifest.for_run(_run_context(lens="b"), inputs=_INPUTS)

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


def _lane_stages(*scopes: StageScope) -> tuple[str, ...]:
    """The stages of these scopes, in registry order."""
    return tuple(
        stage.stage_id for stage in CANONICAL_TOPOLOGY.stages if stage.scope in scopes
    )


_SIGNAL_LANE = "signal"
_UNIT_LANE = "unit"

_SIGNAL_STAGES = _lane_stages(StageScope.SIGNAL)
_UNIT_STAGES = _lane_stages(StageScope.UNIT)
#: S-08 … S-14: what one destination executes on its own, publication
#: included — S-14 fingerprints one text for one destination. Observation
#: (S-15) is post-run and outside what these two scenarios need.
_DESTINATION_STAGES = _lane_stages(StageScope.DESTINATION, StageScope.PUBLICATION)


@dataclass(frozen=True)
class _Finding:
    """What a stage reports every time the simulated run reaches it.

    Not an error the harness invents: a finding is the ``cause`` of one row of
    the Step 2 §5.3 route table, and the registry alone decides where it goes,
    which counter it spends and what happens when that counter runs out.
    ``occurrences`` is how many times the stage reports it before it is
    satisfied — once for a run that REPLANs and recovers, more than the
    counter allows for one that exhausts it.
    """

    stage_id: str
    lane: str
    cause: str
    occurrences: int = 1


class _SimulatedRun:
    """A run of the canonical topology that records what it executed.

    Not an engine: it holds no stage logic, which #290 keeps out of this
    slice. It walks the registry's order, takes the backward routes the
    registry declares, spends the counters those routes spend and ends a lane
    on the terminal outcome the registry names — so a REPLAN and a
    destination SKIP are *produced* by running rather than written down. What
    it yields is an executed path and a manifest, which is what clarification
    C-1 is a claim about.

    A lane is one scope instance: the signal, the unit, or one destination.
    The simulation has a single signal and a single unit, so keying counters
    by lane counts them per the scope Step 2 §0.3 gives them.
    """

    def __init__(
        self,
        run_context: RunContext,
        destinations: tuple[str, ...],
        findings: tuple[_Finding, ...] = (),
    ) -> None:
        self.manifest = RunManifest.for_run(run_context, inputs=_INPUTS)
        self.steps: list[tuple[str, str]] = []
        self.outcomes: list[tuple[str, TerminalOutcome]] = []
        self._unresolved = {(f.stage_id, f.lane): f.occurrences for f in findings}
        self._causes = {(f.stage_id, f.lane): f.cause for f in findings}
        self._spent: dict[tuple[str, str], int] = {}

        if self._walk(_SIGNAL_STAGES, _SIGNAL_LANE) and self._walk(
            _UNIT_STAGES, _UNIT_LANE
        ):
            for destination in destinations:
                self._walk(_DESTINATION_STAGES, destination)

    def path(self, destination: str) -> tuple[str, ...]:
        """The stages one destination executed, from the shared prefix on."""
        return tuple(
            stage_id
            for stage_id, lane in self.steps
            if lane in (_SIGNAL_LANE, _UNIT_LANE, destination)
        )

    def _walk(self, stage_ids: tuple[str, ...], lane: str) -> bool:
        """Execute these stages in order; ``False`` when the lane ends early."""
        index = 0
        while index < len(stage_ids):
            self.steps.append((stage_ids[index], lane))
            route = self._route_raised_at(stage_ids[index], lane)
            if route is None:
                index += 1
                continue
            if self._spend(route.counter, lane):
                index = stage_ids.index(route.target)
                continue
            self.outcomes.append((lane, route.on_exhaustion))
            return False
        return True

    def _route_raised_at(self, stage_id: str, lane: str) -> Optional[ReplanRoute]:
        """The route the registry gives the finding this stage reports."""
        unresolved = self._unresolved.get((stage_id, lane), 0)
        if unresolved <= 0:
            return None
        self._unresolved[(stage_id, lane)] = unresolved - 1
        cause = self._causes[(stage_id, lane)]
        # exactly one row, or the scenario named a route the registry does not
        # have and the harness must say so rather than invent one
        (route,) = [
            candidate
            for candidate in CANONICAL_TOPOLOGY.replan_routes
            if candidate.source == stage_id and candidate.cause == cause
        ]
        return route

    def _spend(self, counter_id: str, lane: str) -> bool:
        """Charge one attempt to the counter; ``False`` when it is exhausted."""
        (counter,) = [
            candidate
            for candidate in CANONICAL_TOPOLOGY.counters
            if candidate.counter_id == counter_id
        ]
        spent = self._spent.get((counter_id, lane), 0)
        if spent >= counter.default_limit:
            return False
        self._spent[(counter_id, lane)] = spent + 1
        return True


def _is_permitted(path: tuple[str, ...]) -> bool:
    return all(
        CANONICAL_TOPOLOGY.permits_transition(before, after)
        for before, after in zip(path, path[1:])
    )


#: Wix's plan check fails once; S-11 sends it back to S-08 and it recovers.
_PLAN_CHECK_FAILS_ONCE = _Finding(
    stage_id="S-11", lane="wix", cause="plan_check_failed",
)

#: Telegram never finds an admissible strategy, so S-09 keeps sending it back
#: to S-08 until L_strategy runs out and the route's terminal outcome — a
#: destination SKIP — is what ends the lane. More occurrences than any limit.
_TELEGRAM_NEVER_FINDS_A_STRATEGY = _Finding(
    stage_id="S-09", lane="telegram", cause="no_admissible_candidate",
    occurrences=99,
)


def test_a_replanning_run_re_enters_the_stage_the_registry_routes_it_to():
    run = _SimulatedRun(_run_context(), ("wix",), (_PLAN_CHECK_FAILS_ONCE,))

    assert run.path("wix").count("S-08") == 2  # planned twice
    assert run.path("wix")[-1] == "S-14"  # and published on the second plan
    assert run.outcomes == []
    assert _is_permitted(run.path("wix"))


def test_a_run_that_exhausts_a_counter_skips_that_destination_and_no_other():
    run = _SimulatedRun(
        _run_context(), ("wix", "telegram"), (_TELEGRAM_NEVER_FINDS_A_STRATEGY,)
    )

    assert run.outcomes == [("telegram", TerminalOutcome.SKIP_DESTINATION)]
    assert run.path("telegram")[-1] == "S-09"  # ended where it ran out
    assert "S-14" not in run.path("telegram")  # so it never published
    assert run.path("wix")[-1] == "S-14"  # while its sibling published
    assert _is_permitted(run.path("telegram"))


def test_a_replan_and_a_skipped_destination_carry_the_same_digest():
    replanned = _SimulatedRun(
        _run_context(lens="a"), ("wix",), (_PLAN_CHECK_FAILS_ONCE,)
    )
    skipped = _SimulatedRun(
        _run_context(lens="b"),
        ("wix", "telegram"),
        (_TELEGRAM_NEVER_FINDS_A_STRATEGY,),
    )

    # the two runs executed genuinely different paths: one re-entered S-08 and
    # published, the other ended a destination on an exhausted counter
    assert replanned.path("wix") != skipped.path("wix")
    assert replanned.outcomes == []
    assert skipped.outcomes == [("telegram", TerminalOutcome.SKIP_DESTINATION)]

    # and their manifests carry one digest, because it identifies the allowed
    # topology and not the path a run took through it (C-1)
    assert (
        replanned.manifest.topology_digest
        == skipped.manifest.topology_digest
        == topology_digest()
    )
    verify_topology_digest(replanned.manifest)
    verify_topology_digest(skipped.manifest)


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
    manifest = RunManifest.for_run(_run_context(), inputs=_INPUTS)

    assert manifest.topology_digest == topology_digest()
    verify_topology_digest(manifest)  # does not raise


def test_a_run_whose_digest_differs_from_the_registry_fails_verification():
    stale = RunManifest.for_run(_run_context(), inputs=_INPUTS).to_dict()
    stale["topology_digest"] = "sha256:" + "0" * 64

    manifest = RunManifest.from_dict(stale)  # readable, for forensics

    with pytest.raises(TopologyDigestMismatchError, match="canonical"):
        verify_topology_digest(manifest)


def test_a_manifest_round_trips_through_its_serialization():
    identity = CodeIdentity(
        commit_sha="0" * 40, tracked_worktree_clean=True, clean_policy=CLEAN_POLICY,
    )
    original = RunManifest.for_run(
        _run_context(), code_identity=identity, inputs=_INPUTS
    )

    restored = RunManifest.from_dict(original.to_dict())

    assert restored == original
    verify_topology_digest(restored)


def test_a_manifest_without_a_topology_digest_is_refused():
    incomplete = RunManifest.for_run(_run_context(), inputs=_INPUTS).to_dict()
    del incomplete["topology_digest"]

    with pytest.raises(ValueError, match="topology_digest"):
        RunManifest.from_dict(incomplete)
