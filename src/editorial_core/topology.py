"""The stage-topology registry and its digest (Issue #290, slice SL-1).

CE-1 says that neither weekday nor destination may define a separate Editorial
Core pipeline: all of them execute through the same canonical S-00 → S-15
topology. An invariant that exists only as a sentence is not checkable, so
Step 6 §0.1 makes it of three parts, of which this module is the first two:

1. **this registry** — the ordered S-00 … S-15 graph with its execution
   scopes, the plan barrier B1, the permitted REPLAN routes and the attempt
   counters those routes spend, defined exactly once. There is one engine
   because there is one place that says what the engine is;
2. the **topology digest**, written into every RunManifest
   (``src/run/run_manifest.py``), so that a run states which topology it
   claims to have executed and a reader can refuse one that differs;
3. the **placement rule** (``scripts/ci/check_ce1_placement.py``), which keeps
   the modules implementing S-00 … S-13 from growing a weekday or destination
   pipeline of their own.

What the digest identifies (clarification C-1)
----------------------------------------------
The digest identifies the canonical **allowed** topology — the stages, their
scopes, the barriers and the permitted backward routes — and **not the path a
run executed**. A run that SKIPs a destination, REPLANs, exhausts a counter or
takes a backward route produces a different trace and the **same** digest. The
digest is computed from this registry alone: no configuration, lens, weekday,
destination or run value reaches it.

Two things are deliberately outside it:

- stage and barrier **names**, which are documentation;
- counter **default limits**, which Step 2 §0.3 calls tunable implementation
  parameters (OPEN-22). What the contract fixes is that the counter exists, at
  which scope, and what its exhaustion does — and all of that is inside.

``RunCallBudget`` is not a topology counter. It is the run-scoped spend limit
owned by ``src/run/call_budget.py``: it bounds every route rather than
belonging to one.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §0.2
(scopes and barrier B1), §0.3 (attempt counters) and §5.3 (the REPLAN route
table); ``docs/editorial/architecture/07_STEP6_VERTICAL_SLICES.md`` §0.1
(CE-1 and clarification C-1).

This module holds no stage logic. It is the map, not the engine.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The serialization the digest is taken over. Bump it only when the meaning
#: of the payload changes, never when the topology itself does — the digest is
#: how a topology change is noticed.
CANONICAL_TOPOLOGY_SERIALIZATION = "stage-topology-json-v1"

_STAGE_ID_PATTERN = r"^S-(?:0\d|1[0-5])$"


class StageScope(str, Enum):
    """What a stage runs once per (Step 2 §0.2)."""

    SIGNAL = "signal"
    UNIT = "unit"
    DESTINATION = "destination"
    PUBLICATION = "publication"
    POST_RUN = "post_run"


class CounterScope(str, Enum):
    """What an attempt counter is counted per (Step 2 §0.3).

    Deliberately a separate vocabulary from :class:`StageScope`: counters are
    counted per text as well, and no stage runs at text scope.
    """

    SIGNAL = "signal"
    UNIT = "unit"
    DESTINATION = "destination"
    TEXT = "text"


class TerminalOutcome(str, Enum):
    """Where a route ends when its counter is exhausted (Step 2 §5.3).

    Every one of them is an ARP outcome with a recorded reason. None of them
    waits for a human (I-01).
    """

    SKIP_SIGNAL = "skip_signal"
    SKIP_UNIT = "skip_unit"
    SKIP_DESTINATION = "skip_destination"
    SKIP_PUBLICATION = "skip_publication"
    #: S-06 weakens the anchor if it still holds at a lower strength, and skips
    #: the unit if it does not. The choice is made on the evidence, not on a
    #: counter, so both ends are named here rather than split into two routes.
    DEGRADE_OR_SKIP_UNIT = "degrade_or_skip_unit"


class _Registered(BaseModel):
    """Every registry entry is immutable and rejects fields it does not know."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Stage(_Registered):
    """One stage of the canonical topology."""

    stage_id: str = Field(pattern=_STAGE_ID_PATTERN)
    name: str = Field(min_length=1)
    scope: StageScope


class Barrier(_Registered):
    """A point where the run waits for every sibling scope before continuing."""

    barrier_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    scope: StageScope
    #: The stage that evaluates the barrier.
    evaluated_at: str = Field(pattern=_STAGE_ID_PATTERN)
    #: The stage no scope may enter until the barrier passes.
    blocks: str = Field(pattern=_STAGE_ID_PATTERN)


class Counter(_Registered):
    """An attempt counter. Every backward route spends one, so no loop is free."""

    counter_id: str = Field(min_length=1)
    scope: CounterScope
    #: Step 2 §0.3 initial default. Tunable (OPEN-22), and therefore outside
    #: the digest: raising a limit is configuration, not a second engine.
    default_limit: int = Field(ge=1)


class ReplanRoute(_Registered):
    """One row of the Step 2 §5.3 route table.

    A route says where a failure goes, which counter it spends and how it ends
    when that counter runs out. The failure is routed to the layer that made
    the wrong decision (I-09), which is why most targets are upstream.
    """

    source: str = Field(pattern=_STAGE_ID_PATTERN)
    target: str = Field(pattern=_STAGE_ID_PATTERN)
    #: A closed machine token, not free text: it is recorded in the trace.
    cause: str = Field(min_length=1)
    counter: str = Field(min_length=1)
    on_exhaustion: TerminalOutcome


class StageTopology(_Registered):
    """The canonical S-00 → S-15 graph: what the engine is allowed to do."""

    stages: tuple[Stage, ...] = Field(min_length=1)
    barriers: tuple[Barrier, ...]
    counters: tuple[Counter, ...]
    replan_routes: tuple[ReplanRoute, ...]

    @model_validator(mode="after")
    def _internally_consistent(self) -> "StageTopology":
        stage_ids = [stage.stage_id for stage in self.stages]
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError("a stage may appear in the topology only once")
        if stage_ids != sorted(stage_ids):
            raise ValueError(
                "stages must be declared in execution order; "
                f"got {', '.join(stage_ids)}"
            )

        counter_ids = [counter.counter_id for counter in self.counters]
        if len(set(counter_ids)) != len(counter_ids):
            raise ValueError("a counter may be declared only once")

        known_stages = set(stage_ids)
        for barrier in self.barriers:
            unknown = {barrier.evaluated_at, barrier.blocks} - known_stages
            if unknown:
                raise ValueError(
                    f"barrier {barrier.barrier_id} names unknown "
                    f"stage(s) {', '.join(sorted(unknown))}"
                )
            if stage_ids.index(barrier.blocks) <= stage_ids.index(barrier.evaluated_at):
                raise ValueError(
                    f"barrier {barrier.barrier_id} must block a stage after the "
                    f"one that evaluates it; {barrier.blocks} is not after "
                    f"{barrier.evaluated_at}"
                )

        for route in self.replan_routes:
            unknown = {route.source, route.target} - known_stages
            if unknown:
                raise ValueError(
                    f"route {route.source}→{route.target} ({route.cause}) names "
                    f"unknown stage(s) {', '.join(sorted(unknown))}"
                )
            if route.source == route.target:
                raise ValueError(
                    f"route {route.cause} leaves and enters {route.source}; "
                    "a stage that retries itself spends no counter"
                )
            if route.counter not in counter_ids:
                raise ValueError(
                    f"route {route.source}→{route.target} ({route.cause}) spends "
                    f"unknown counter {route.counter}"
                )

        unspent = set(counter_ids) - {route.counter for route in self.replan_routes}
        if unspent:
            raise ValueError(
                "every counter must be spent by a route; "
                f"{', '.join(sorted(unspent))} is spent by none"
            )
        return self

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    @property
    def stage_ids(self) -> tuple[str, ...]:
        """The stages in execution order."""

        return tuple(stage.stage_id for stage in self.stages)

    @property
    def editorial_core_stage_ids(self) -> tuple[str, ...]:
        """S-00 … S-13: every stage before publication.

        Derived from the scopes rather than listed again, so the CE-1
        placement rule and the registry cannot disagree about where the core
        ends. Publication and observation are outside it: they are where
        destination capability legitimately decides what happens.
        """

        return tuple(
            stage.stage_id
            for stage in self.stages
            if stage.scope not in (StageScope.PUBLICATION, StageScope.POST_RUN)
        )

    @property
    def backward_routes(self) -> tuple[ReplanRoute, ...]:
        """The routes that re-enter an earlier stage.

        The rest of the route table moves forward: a boundary re-entry that
        leaves the anchor standing continues into S-08 in the ordinary
        direction, and an enrichment gap opened at S-01 is closed by S-03 on
        the way past. Only these edges can make the graph cycle, and each one
        spends a finite counter, which is why every path terminates.
        """

        return tuple(
            route
            for route in self.replan_routes
            if self._index(route.target) < self._index(route.source)
        )

    def stage(self, stage_id: str) -> Stage:
        """The named stage, or ``KeyError``."""

        for stage in self.stages:
            if stage.stage_id == stage_id:
                return stage
        raise KeyError(
            f"unknown stage {stage_id!r}; the topology defines "
            f"{', '.join(self.stage_ids)}"
        )

    def permits_transition(self, source: str, target: str) -> bool:
        """May a run move from one stage execution to the next?

        Forward to any later stage: a SKIP leaves stages unexecuted, and an
        execution that skips them is the same topology taking a shorter path
        (C-1). Backward only along a declared route, because an undeclared
        backward edge is a second engine.
        """

        source_index = self._index(source)
        target_index = self._index(target)
        if target_index > source_index:
            return True
        return any(
            route.source == source and route.target == target
            for route in self.backward_routes
        )

    # ------------------------------------------------------------------
    # Digest
    # ------------------------------------------------------------------

    def digest_payload(self) -> dict[str, Any]:
        """What the digest is taken over.

        Names and tunable limits are absent by design — see the module
        docstring. Stages keep their declared order because the order *is* the
        topology; everything else is sorted so that the digest does not depend
        on the order the registry happens to list it in.
        """

        return {
            "serialization": CANONICAL_TOPOLOGY_SERIALIZATION,
            "stages": [
                {"stage_id": stage.stage_id, "scope": stage.scope.value}
                for stage in self.stages
            ],
            "barriers": sorted(
                (
                    {
                        "barrier_id": barrier.barrier_id,
                        "scope": barrier.scope.value,
                        "evaluated_at": barrier.evaluated_at,
                        "blocks": barrier.blocks,
                    }
                    for barrier in self.barriers
                ),
                key=lambda entry: entry["barrier_id"],
            ),
            "counters": sorted(
                (
                    {"counter_id": counter.counter_id, "scope": counter.scope.value}
                    for counter in self.counters
                ),
                key=lambda entry: entry["counter_id"],
            ),
            "replan_routes": sorted(
                (
                    {
                        "source": route.source,
                        "target": route.target,
                        "cause": route.cause,
                        "counter": route.counter,
                        "on_exhaustion": route.on_exhaustion.value,
                    }
                    for route in self.replan_routes
                ),
                key=lambda entry: (entry["source"], entry["target"], entry["cause"]),
            ),
        }

    def digest(self) -> str:
        """``sha256:<hex>`` over the canonical serialization of the topology."""

        payload = json.dumps(
            self.digest_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _index(self, stage_id: str) -> int:
        try:
            return self.stage_ids.index(stage_id)
        except ValueError:
            raise KeyError(
                f"unknown stage {stage_id!r}; the topology defines "
                f"{', '.join(self.stage_ids)}"
            ) from None


#: The canonical topology. One engine means one of these.
CANONICAL_TOPOLOGY = StageTopology(
    stages=(
        Stage(stage_id="S-00", name="Signal selection", scope=StageScope.SIGNAL),
        Stage(stage_id="S-01", name="Evidence Core and relevance screen", scope=StageScope.SIGNAL),
        Stage(stage_id="S-02", name="Material features and initial assets", scope=StageScope.SIGNAL),
        Stage(stage_id="S-03", name="Enrichment loop", scope=StageScope.SIGNAL),
        Stage(stage_id="S-04", name="Interpretation Boundary", scope=StageScope.SIGNAL),
        Stage(stage_id="S-05", name="Editorial Units", scope=StageScope.SIGNAL),
        Stage(stage_id="S-06", name="Anchor", scope=StageScope.UNIT),
        Stage(stage_id="S-07", name="Destinations", scope=StageScope.UNIT),
        Stage(stage_id="S-08", name="Candidate strategies", scope=StageScope.DESTINATION),
        Stage(stage_id="S-09", name="Strategy selection", scope=StageScope.DESTINATION),
        Stage(stage_id="S-10", name="Executable plan", scope=StageScope.DESTINATION),
        Stage(stage_id="S-11", name="Plan check and exemplars", scope=StageScope.DESTINATION),
        Stage(stage_id="S-12", name="Writer", scope=StageScope.DESTINATION),
        Stage(stage_id="S-13", name="Text check", scope=StageScope.DESTINATION),
        Stage(stage_id="S-14", name="Publication and fingerprint", scope=StageScope.PUBLICATION),
        Stage(stage_id="S-15", name="Observation", scope=StageScope.POST_RUN),
    ),
    barriers=(
        # V-P03 compares the plans of all destinations of a unit, so it runs at
        # unit scope inside a destination-scoped stage, and no text is written
        # for any destination of that unit before it passes. Plans are cheap;
        # prose is not.
        Barrier(
            barrier_id="B1",
            name="Plan barrier",
            scope=StageScope.UNIT,
            evaluated_at="S-11",
            blocks="S-12",
        ),
    ),
    counters=(
        Counter(counter_id="L_enrich", scope=CounterScope.SIGNAL, default_limit=2),
        Counter(counter_id="L_boundary", scope=CounterScope.UNIT, default_limit=1),
        Counter(counter_id="L_anchor", scope=CounterScope.UNIT, default_limit=1),
        Counter(counter_id="L_strategy", scope=CounterScope.DESTINATION, default_limit=2),
        Counter(counter_id="L_edit", scope=CounterScope.TEXT, default_limit=1),
    ),
    replan_routes=(
        ReplanRoute(
            source="S-01",
            target="S-03",
            cause="relevance_revise_or_hold",
            counter="L_enrich",
            on_exhaustion=TerminalOutcome.SKIP_SIGNAL,
        ),
        ReplanRoute(
            source="S-04",
            target="S-06",
            cause="anchor_invalidated_by_re_entry",
            counter="L_anchor",
            on_exhaustion=TerminalOutcome.SKIP_UNIT,
        ),
        ReplanRoute(
            source="S-04",
            target="S-08",
            cause="boundary_re_entry_without_anchor_loss",
            counter="L_strategy",
            on_exhaustion=TerminalOutcome.SKIP_DESTINATION,
        ),
        ReplanRoute(
            source="S-06",
            target="S-03",
            cause="ambiguity_touches_anchor",
            counter="L_enrich",
            on_exhaustion=TerminalOutcome.DEGRADE_OR_SKIP_UNIT,
        ),
        ReplanRoute(
            source="S-09",
            target="S-06",
            cause="no_admissible_candidate_on_any_destination",
            counter="L_anchor",
            on_exhaustion=TerminalOutcome.SKIP_UNIT,
        ),
        ReplanRoute(
            source="S-09",
            target="S-08",
            cause="no_admissible_candidate",
            counter="L_strategy",
            on_exhaustion=TerminalOutcome.SKIP_DESTINATION,
        ),
        ReplanRoute(
            source="S-10",
            target="S-08",
            cause="adaptation_cannot_meet_hard_constraint",
            counter="L_strategy",
            on_exhaustion=TerminalOutcome.SKIP_DESTINATION,
        ),
        ReplanRoute(
            source="S-11",
            target="S-08",
            cause="plan_check_failed",
            counter="L_strategy",
            on_exhaustion=TerminalOutcome.SKIP_DESTINATION,
        ),
        ReplanRoute(
            # V-P03 sends back only the destinations that deviated from the
            # anchor; the others keep their approval.
            source="S-11",
            target="S-08",
            cause="plan_deviates_from_the_unit",
            counter="L_strategy",
            on_exhaustion=TerminalOutcome.SKIP_DESTINATION,
        ),
        ReplanRoute(
            source="S-12",
            target="S-08",
            cause="plan_does_not_hold",
            counter="L_strategy",
            on_exhaustion=TerminalOutcome.SKIP_DESTINATION,
        ),
        ReplanRoute(
            # Phrasing and misquoted or removable facts are the only findings
            # the Writer is asked to repair: it edits against the same approved
            # plan. A decision error is never charged to it (I-09).
            source="S-13",
            target="S-12",
            cause="phrasing_or_removable_fact",
            counter="L_edit",
            on_exhaustion=TerminalOutcome.SKIP_PUBLICATION,
        ),
        ReplanRoute(
            source="S-13",
            target="S-08",
            cause="structural_or_load_bearing_fault",
            counter="L_strategy",
            on_exhaustion=TerminalOutcome.SKIP_DESTINATION,
        ),
        ReplanRoute(
            source="S-13",
            target="S-04",
            cause="interpretation_inadmissible_or_unlisted",
            counter="L_boundary",
            on_exhaustion=TerminalOutcome.SKIP_DESTINATION,
        ),
    ),
)

#: The stages the CE-1 placement rule governs: S-00 … S-13.
EDITORIAL_CORE_STAGE_IDS: tuple[str, ...] = CANONICAL_TOPOLOGY.editorial_core_stage_ids


def topology_digest(topology: Optional[StageTopology] = None) -> str:
    """The digest a RunManifest records: ``sha256:<hex>``.

    Takes no run, configuration or trace, and that is the point — the value it
    returns cannot vary with a lens setting, a weekday, a destination or an
    executed path. The optional argument exists for tests that need to digest
    a variant topology; production callers pass nothing.
    """

    return (topology or CANONICAL_TOPOLOGY).digest()
