"""The regression safety net around the proven canonical path (#370).

#351 proved the composition: one intake record enters the production S-00 and
six checked texts leave the production S-13, through
``execute_canonical_topology`` with the production configuration, the
production attempt ledger and the production call budget. That proof held on
the day it was made. This module is what makes it keep holding — the net #370
owns, around the path #351 owns.

It builds **no second engine**. Every run reached from here is #351's
``canonical_run``/``execute`` harness over the production entrypoint, and the
only thing added is *what is read off that run*: seven independent checks over
the trace, the workspace and the manifest. Each returns the seams it found
broken rather than a boolean, so a failure names the seam that went rather than
saying "integration is red" — which is the whole difference between a safety
net and a red light.

The seven checks, and the defect class each exists to catch
----------------------------------------------------------
1. :func:`stage_findings` — a stage silently skipped. The defect this chain
   was built to end is a green test that proves nothing, and the cheapest form
   of it is a composition that quietly stops short.
2. :func:`lineage_findings` — an artifact a consumer read that **no production
   producer of this run wrote**. This is the exact shape of the phantom
   destination-rule defect ``tests/test_363_configuration_producers.py``
   records: ``tests/test_305_…`` and ``tests/test_306_…`` cited a record that
   does not exist and stayed green for months, because a test that authors its
   own input can never notice that nobody produces it. Here
   every consumed reference is resolved, in trace order, against what an
   earlier stage recorded as output — by entity type, ID **and** version — and
   the producing stage is compared against the seam this net declares, so a
   seam that grows a new producer is declared here or it is not a seam the net
   proves.
3. :func:`manifest_findings` — the consumer half of §4.3's verification.
   ``verify_run_workspace`` already proves every stage *output* is in the
   entity index at the digest the index records; nothing proved that of an
   *input*, so a consumer could name a version the manifest does not hold.
4. :func:`call_findings` — a stage that decided nothing. A static artifact
   standing in for a stage makes no model call, so the per-boundary counts are
   the topology's own arithmetic or a stage was bypassed.
5. :func:`fanout_findings` — the six-destination fan-out, as destinations that
   each hold an accepted text.
6. :func:`pass_through_findings` — ``PASS_THROUGH_MARKER`` in no record and no
   file of the workspace.
7. :func:`descent_findings` — the run's own identity chain: the selection is
   about the signal the run identified, the unit descends from the core this
   run produced, and the workspace holds that unit and no other. This is what
   catches a static artifact at a stage that makes no model call, where check 4
   has nothing to see.

:func:`composition_findings` is all seven, which is the integration proof this
slice is judged on. :func:`static_artifact_run` and :func:`bypassed_run` are
the two instruments that break the path on purpose, so that the net can be
shown to catch what it claims to catch, and :func:`enriching_run` is the one
scenario they need that a clean canonical run does not produce: S-03's
production entry decides nothing when nothing blocks a decision, so the stage
is measured on a run whose material does.

Nothing here reaches a network, a provider, a credential or a publication, and
S-14 is not executed.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Final, NamedTuple, Optional

from src.editorial_core.editorial_units import unit_id
from src.editorial_core.material_features import MATERIAL_INSTRUCTIONS
from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.run import golden_engine
from src.run.golden_engine import UNWIRED_STAGES, CanonicalExecution
from src.run.run_manifest import RunManifest
from src.run.run_workspace import EntityRef, StageRecord, file_digest
from src.run.walking_skeleton import CANONICAL_DESTINATIONS, PASS_THROUGH_MARKER
from tests.golden_engine_boundary import (
    CanonicalRun,
    EvidenceJudgment,
    Ledger,
    Material,
    canonical_run,
    execute,
)

#: The stages a canonical run executes, derived from the registry rather than
#: listed: a stage added to the topology below S-14 makes the net demand it,
#: which is the point of deriving it.
STAGES: Final[tuple[str, ...]] = tuple(
    stage.stage_id
    for stage in CANONICAL_TOPOLOGY.stages
    if stage.stage_id not in UNWIRED_STAGES
)

#: The entity type S-00's selection is written under. The engine keeps it
#: private, so it is named here and kept honest by
#: ``test_the_declared_seams_are_the_ones_the_clean_run_records``: a literal
#: that stopped matching would make that test fail rather than make this net
#: quietly stop resolving the first seam.
SELECTION_ENTITY_TYPE: Final[str] = "E-01.selection"

#: The internal seams of the canonical path: which stage may have produced what
#: a consumer read. Declared, not inferred — the thing this net exists to catch
#: is an input nobody produces, and a net that accepted any producer for any
#: type would accept S-13 reading a boundary version S-13 wrote itself.
#:
#: Read as ``(consumer stage, entity type) → the stages that may have produced
#: it``. The core and features entries of the stages **after** S-03 carry it as
#: a producer, because the enrichment loop re-versions both when a gap is open
#: and a later consumer reads what the round committed. The canonical scenario
#: opens none (``test_s03_runs_and_opens_no_enrichment_round``), so those
#: producers are reached by :func:`enriching_run` instead — declared and
#: exercised, rather than declared and taken on trust.
#:
#: S-02's and S-03's own entries do not carry it, and that is the same rule
#: read the other way: the topology runs each of S-00…S-07 once and in order,
#: so what S-02 and S-03 consume was produced upstream of the loop. A net that
#: let S-03 answer for them would accept the trace saying S-03 consumed the
#: E-05 it had just written.
SEAMS: Final[Mapping[tuple[str, str], frozenset[str]]] = {
    ("S-01", SELECTION_ENTITY_TYPE): frozenset({"S-00"}),
    ("S-02", "E-04"): frozenset({"S-01"}),
    ("S-03", "E-05"): frozenset({"S-02"}),
    ("S-04", "E-04"): frozenset({"S-01", "S-03"}),
    ("S-04", "E-05"): frozenset({"S-02", "S-03"}),
    ("S-04", "E-09"): frozenset({"S-04"}),
    ("S-05", "E-04"): frozenset({"S-01", "S-03"}),
    ("S-05", "E-09"): frozenset({"S-04"}),
    ("S-06", "E-09"): frozenset({"S-04"}),
    ("S-06", "E-10"): frozenset({"S-05"}),
    ("S-07", "E-10"): frozenset({"S-05"}),
    ("S-07", "E-11"): frozenset({"S-06"}),
    ("S-08", "E-09"): frozenset({"S-04"}),
    ("S-08", "E-11"): frozenset({"S-06"}),
    ("S-09", "E-13"): frozenset({"S-08"}),
    ("S-10", "E-09"): frozenset({"S-04"}),
    ("S-11", "E-09"): frozenset({"S-04"}),
    ("S-11", "E-11"): frozenset({"S-06"}),
    ("S-12", "E-09"): frozenset({"S-04"}),
    ("S-12", "E-15"): frozenset({"S-12"}),
    ("S-13", "E-09"): frozenset({"S-04"}),
    ("S-13", "E-15"): frozenset({"S-12"}),
}

#: The seams the consumer references by E-15's **content** digest rather than
#: by the digest of the file the workspace wrote. ``_text_ref`` does that
#: deliberately: V-T05 and publication idempotency compare the content, so the
#: reference S-13 records is the one those two can use. Declared here so that
#: the comparison is made against the entity's own ``content_digest`` field
#: (:func:`manifest_findings`) instead of being skipped.
CONTENT_DIGEST_SEAMS: Final[frozenset[tuple[str, str]]] = frozenset(
    {("S-12", "E-15"), ("S-13", "E-15")}
)

#: The boundary the run reaches that §6 does not charge: "Model calls only.
#: Retrieval providers, publishers and the label job are not counted."
RESEARCH_BOUNDARY: Final[str] = "research"

#: What a clean six-destination run asks of each boundary — the topology's own
#: arithmetic, as #351's execution established it. Seven signal- and
#: unit-scoped calls, four planning calls per destination, one barrier round,
#: and three per destination to write and check. It is the net's mutation
#: detector: a stage replaced by a static artifact asks its boundary nothing.
CLEAN_RUN_CALLS: Final[Mapping[str, int]] = {
    "eligibility": 1,
    RESEARCH_BOUNDARY: 1,
    "evidence_judgment": 1,
    "lens": 1,
    "material": 1,
    "boundary": 2,
    "anchor": 1,
    "strategy": 6,
    "ranking": 6,
    "segmentation": 6,
    "plan_check": 6,
    "barrier": 1,
    "writer": 6,
    "text_check": 12,
}

#: Stage → the production function the engine calls for it, by the name it is
#: bound to in ``src/run/golden_engine.py``. The one instrument
#: :func:`static_artifact_run` needs: replacing exactly this name is what
#: "replace one real stage with a static artifact" means, and it is the stage's
#: own production entry rather than a seam beside it.
#:
#: Every wired stage is here, S-03 included. Its entry is ``open_gaps``, and
#: the static artifact a donor canonical run supplies for it is the empty gap
#: set — which is why it is not measured on the canonical scenario, where the
#: real entry returns the same empty set and the substitution would change
#: nothing. :func:`enriching_run` is the scenario where it decides something,
#: and that is where the substitution is made.
STAGE_PRODUCERS: Final[Mapping[str, str]] = {
    "S-00": "select_signal",
    "S-01": "retrieve_evidence_core",
    "S-02": "describe_material",
    "S-03": "open_gaps",
    "S-04": "decide_boundary",
    "S-05": "create_unit",
    "S-06": "choose_anchor",
    "S-07": "decide_destinations",
    "S-08": "propose_strategies",
    "S-09": "select_strategy",
    "S-10": "adapt_strategy",
    "S-11": "check_plan",
    "S-12": "write_prose",
    "S-13": "check_text",
}

#: The one stage of :data:`STAGE_PRODUCERS` whose substitution is measured on
#: :func:`enriching_run` instead of on the canonical scenario. Named here, by
#: the module that knows why, so that the mutation suite picks the host run
#: from the table rather than from a condition written beside the assertion.
ENRICHING_STAGE: Final[str] = "S-03"

#: The four producers the issue names, as the production function each run
#: reads its value from. Three are authorities the configuration loads and the
#: fourth is a lift S-07 makes per run, and :func:`bypassed_run` removes each
#: the same way — by answering ``None``, which is what "nobody produces this"
#: looks like to the code that asked.
REQUIRED_PRODUCERS: Final[Mapping[str, str]] = {
    "StrategyContract": "strategy_contract",
    "AdaptationContract": "adaptation_contract",
    "StrengthLadder": "universal_strength_ladder",
    "UnitFacts": "unit_facts",
}

#: The signal the donor run of :func:`static_artifacts` is about. Different
#: from the host's on purpose: an artifact carries the identities of the run
#: that produced it, so a donor artifact is a *static* artifact in exactly the
#: sense that matters — it was not produced by the run that consumed it.
DONOR_SIGNAL: Final[str] = "sig-370-donor"

#: The signal the net's own runs are about.
NET_SIGNAL: Final[str] = "sig-370-net"


# ===========================================================================
# 1 · every stage executed
# ===========================================================================


def stage_findings(
    records: Sequence[StageRecord], execution: CanonicalExecution
) -> tuple[str, ...]:
    """Every stage of the executed topology recorded at least one execution."""

    found: list[str] = []
    reached = {record.stage for record in records}
    missing = [stage for stage in STAGES if stage not in reached]
    if missing:
        found.append(
            "the run recorded no execution of "
            + ", ".join(missing)
            + "; a stage the topology declares and the trace does not hold is "
            "a stage this composition did not prove"
        )
    beyond = sorted(reached - set(STAGES))
    if beyond:
        found.append(
            "the run recorded " + ", ".join(beyond) + ", which this slice "
            "does not execute; S-14 is #308's and S-15 is SL-12's"
        )
    if execution.stopped_at is not None:
        found.append(
            f"the run stopped at {execution.stopped_at} rather than reaching "
            "the end of the wired topology"
        )
    return tuple(found)


# ===========================================================================
# 2 · producer → ID and version → consumer, at every internal seam
# ===========================================================================


class LineageReport(NamedTuple):
    """What the lineage walk found, and how much it resolved.

    ``resolved`` is carried because a walk that found nothing to resolve is
    not a clean lineage: it is a trace with no references in it, and a net
    that reported that as a pass would be the defect it exists to catch.
    """

    findings: tuple[str, ...]
    resolved: int


def lineage_findings(
    records: Sequence[StageRecord], *, through: Optional[str] = None
) -> LineageReport:
    """Resolve every consumed reference against what an earlier stage wrote.

    Walked in trace order, so a reference that resolves only to an entity
    written *later* is a finding: the chain is a chain because each stage
    consumed something an earlier one produced.

    ``through`` localises the walk to the prefix of the trace that ends at the
    **first** execution of that stage, which is what makes the proof
    progressive: S-00 → S-01, then that plus the next seam, and so on. A break
    at one seam then fails the test named for that seam and leaves the shorter
    ones green.
    """

    prefix, missing = _prefix(records, through)
    found: list[str] = list(missing)
    produced: dict[tuple[str, str, Optional[int]], tuple[str, EntityRef]] = {}
    resolved = 0
    for record in prefix:
        for ref in record.inputs:
            seam = (record.stage, ref.entity_type)
            producers = SEAMS.get(seam)
            if producers is None:
                found.append(
                    f"{record.stage} consumed {ref.entity_type} at "
                    f"{record.scope_key}, and this net declares no such seam; "
                    "a seam is declared before it is proved, or it is not a "
                    "seam the net proves"
                )
                continue
            earlier = produced.get(
                (ref.entity_type, ref.entity_id, ref.version)
            )
            if earlier is None:
                found.append(
                    f"seam {_name(seam)} is broken: {record.stage} consumed "
                    f"{ref.entity_type} {ref.entity_id} v{ref.version} at "
                    f"{record.scope_key}, and no earlier stage of this run "
                    "produced it"
                )
                continue
            producer, output = earlier
            if producer not in producers:
                found.append(
                    f"seam {_name(seam)} is broken: {ref.entity_type} "
                    f"{ref.entity_id} v{ref.version} was produced by "
                    f"{producer}, and the seam declares "
                    + ", ".join(sorted(producers))
                )
                continue
            if seam not in CONTENT_DIGEST_SEAMS and output.digest != ref.digest:
                found.append(
                    f"seam {_name(seam)} is broken: {record.stage} consumed "
                    f"{ref.entity_type} {ref.entity_id} v{ref.version} at "
                    f"digest {ref.digest}, and {producer} wrote "
                    f"{output.digest}"
                )
                continue
            resolved += 1
        for ref in record.outputs:
            produced.setdefault(
                (ref.entity_type, ref.entity_id, ref.version),
                (record.stage, ref),
            )
    return LineageReport(tuple(found), resolved)


def seam_pairs(records: Sequence[StageRecord]) -> frozenset[tuple[str, str]]:
    """Every ``(consumer stage, entity type)`` pair this trace exercised."""

    return frozenset(
        (record.stage, ref.entity_type)
        for record in records
        for ref in record.inputs
    )


def _prefix(
    records: Sequence[StageRecord], through: Optional[str]
) -> tuple[tuple[StageRecord, ...], tuple[str, ...]]:
    """The trace up to the first execution of ``through``, and what is missing."""

    if through is None:
        return tuple(records), ()
    for index, record in enumerate(records):
        if record.stage == through:
            return tuple(records[: index + 1]), ()
    return tuple(records), (
        f"the run never reached {through}, so the seams into it were never "
        "exercised; a seam proof over a stage that did not run proves nothing",
    )


def _name(seam: tuple[str, str]) -> str:
    return f"{seam[1]} → {seam[0]}"


# ===========================================================================
# 3 · the manifest holds the version the consumer named
# ===========================================================================


def manifest_findings(
    records: Sequence[StageRecord], manifest: RunManifest, run_dir: Path
) -> LineageReport:
    """Every consumed reference against the entity index and the bytes on disk.

    The half §4.3 does not cover. ``verify_run_workspace`` proves each stage
    *output* is indexed at the digest the index records; an input was nobody's
    to check, so a consumer naming a version the manifest does not hold would
    pass verification and still be a reference to nothing.
    """

    index = {
        (entry.entity_type, entry.entity_id, entry.version): entry
        for entry in manifest.entities
    }
    found: list[str] = []
    resolved = 0
    for record in records:
        for ref in record.inputs:
            entry = index.get((ref.entity_type, ref.entity_id, ref.version))
            if entry is None:
                found.append(
                    f"{record.stage} consumed {ref.entity_type} "
                    f"{ref.entity_id} v{ref.version}, which the manifest's "
                    "entity index does not hold"
                )
                continue
            path = run_dir / entry.path
            if not path.is_file():
                found.append(
                    f"{entry.path} is indexed and {record.stage} consumed it, "
                    "and it is not in the workspace"
                )
                continue
            actual = file_digest(path)
            if actual != entry.digest:
                found.append(
                    f"{entry.path} digests {actual} and the manifest indexes "
                    f"{entry.digest}; the file changed after the run wrote it"
                )
                continue
            seam = (record.stage, ref.entity_type)
            if seam in CONTENT_DIGEST_SEAMS:
                stated = _content_digest(path)
                if stated != ref.digest:
                    found.append(
                        f"seam {_name(seam)} is broken: {record.stage} "
                        f"consumed content digest {ref.digest}, and "
                        f"{entry.path} states {stated}"
                    )
                    continue
            elif entry.digest != ref.digest:
                found.append(
                    f"{record.stage} consumed {ref.entity_type} "
                    f"{ref.entity_id} v{ref.version} at digest {ref.digest}, "
                    f"and the manifest indexes {entry.digest}"
                )
                continue
            resolved += 1
    return LineageReport(tuple(found), resolved)


def _content_digest(path: Path) -> Optional[str]:
    """E-15's own ``content_digest``, as the entity on disk states it."""

    body = json.loads(path.read_text(encoding="utf-8"))
    value = body.get("content_digest")
    return value if isinstance(value, str) else None


# ===========================================================================
# 4 · every stage decided, rather than being stood in for
# ===========================================================================


def call_findings(
    ledger: Ledger,
    records: Sequence[StageRecord],
    *,
    expected: Mapping[str, int] = CLEAN_RUN_CALLS,
) -> tuple[str, ...]:
    """The per-boundary counts are the topology's arithmetic, and are charged.

    A static artifact standing in for a stage asks that stage's boundary
    nothing, so this is where such a substitution is seen even when the
    artifact it produced is shaped correctly.
    """

    found: list[str] = []
    counted = boundary_calls(ledger)
    if counted != dict(expected):
        found.append(
            f"the run asked the boundaries {counted}, and the topology's own "
            f"arithmetic is {dict(expected)}; a boundary asked less often than "
            "its stage declares is a stage that did not decide"
        )
    recorded = sum(
        int((record.calls or {}).get("count", 0)) for record in records
    )
    charged = sum(expected.values()) - expected.get(RESEARCH_BOUNDARY, 0)
    if recorded != charged:
        found.append(
            f"the trace records {recorded} model calls and the topology "
            f"charges {charged}; §0.3 gives the run counter one consumer, so "
            "the two are the same number"
        )
    return tuple(found)


def boundary_calls(ledger: Ledger) -> dict[str, int]:
    """What one run asked of each boundary, in :func:`call_findings`' shape.

    Public because a scenario whose arithmetic is not the canonical run's has
    to state what its own is, and the honest way to state it is to measure the
    same scenario unmutated rather than to declare a number nobody derived.
    """

    return dict(Counter(ledger.names))


# ===========================================================================
# 5 · the six-destination fan-out
# ===========================================================================


def fanout_findings(execution: CanonicalExecution) -> tuple[str, ...]:
    """All six canonical destinations leave S-13 holding an accepted text."""

    found: list[str] = []
    accepted = [item.value for item in execution.accepted]
    if sorted(accepted) != sorted(CANONICAL_DESTINATIONS):
        found.append(
            f"the run accepted {sorted(accepted)} and the canonical fan-out is "
            f"{sorted(CANONICAL_DESTINATIONS)}"
        )
    if len(execution.verdicts) != len(CANONICAL_DESTINATIONS):
        found.append(
            f"{len(execution.verdicts)} text verdicts stand behind "
            f"{len(CANONICAL_DESTINATIONS)} destinations; each accepted text "
            "is accepted by a verdict of its own"
        )
    return tuple(found)


# ===========================================================================
# 6 · no pass-through anywhere
# ===========================================================================


def pass_through_findings(
    records: Sequence[StageRecord], run_dir: Path
) -> tuple[str, ...]:
    """``PASS_THROUGH_MARKER`` in no record and no file this run wrote."""

    found: list[str] = []
    serialized = json.dumps(
        [record.model_dump(mode="json") for record in records]
    )
    if PASS_THROUGH_MARKER in serialized:
        found.append(
            f"{PASS_THROUGH_MARKER} appears in the trace of a canonical run"
        )
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and PASS_THROUGH_MARKER in path.read_text(
            encoding="utf-8"
        ):
            found.append(
                f"{PASS_THROUGH_MARKER} appears in "
                f"{path.relative_to(run_dir)}"
            )
    return tuple(found)


# ===========================================================================
# 7 · the run's own identity chain
# ===========================================================================


def descent_findings(
    records: Sequence[StageRecord],
    execution: CanonicalExecution,
    run_dir: Path,
) -> tuple[str, ...]:
    """The artifacts are about the material this run was given.

    Where check 4 has nothing to see — S-05 and S-07 make no model call — this
    is what catches a static artifact: an artifact carries the identities of
    the run that produced it, and three of them are derivable from the intake
    record alone.
    """

    found: list[str] = []
    selection = [
        ref for record in records if record.stage == "S-00" for ref in record.outputs
    ]
    if len(selection) != 1:
        found.append(
            f"S-00 recorded {len(selection)} outputs; one signal becomes one "
            "selection"
        )
    elif execution.signal_ids != (selection[0].entity_id,):
        found.append(
            f"S-00 wrote a selection of {selection[0].entity_id!r} and the run "
            f"identified {execution.signal_ids!r}; a selection is about the "
            "signal the run selected"
        )
    cores = [
        ref
        for record in records
        for ref in record.outputs
        if ref.entity_type == "E-04"
    ]
    if not cores:
        found.append("no stage of the run produced an Evidence Core")
    elif execution.unit_ids != (unit_id(cores[0].entity_id),):
        found.append(
            f"the run's unit is {execution.unit_ids!r} and the core it "
            f"produced is {cores[0].entity_id!r}; AD-03 derives the unit from "
            "the core rather than counting it"
        )
    units = run_dir / "units"
    held = (
        sorted(item.name for item in units.iterdir() if item.is_dir())
        if units.is_dir()
        else []
    )
    if held != sorted(execution.unit_ids):
        found.append(
            f"the workspace holds unit directories {held} and the run created "
            f"{sorted(execution.unit_ids)}; a unit-scoped artifact written "
            "under another unit is an artifact of another run"
        )
    return tuple(found)


# ===========================================================================
# All seven: the integration proof
# ===========================================================================


def composition_findings(
    *,
    records: Sequence[StageRecord],
    execution: CanonicalExecution,
    ledger: Ledger,
    run_dir: Path,
    manifest: Optional[RunManifest] = None,
    expected_calls: Optional[Mapping[str, int]] = CLEAN_RUN_CALLS,
) -> tuple[str, ...]:
    """Every seam of the canonical composition, as the seams that went.

    ``manifest`` is optional because a run executed through
    ``execute_canonical_topology`` is not sealed — the manifest is
    ``run_golden_engine``'s, written last (§4.3) — and the mutation scenarios
    execute the topology without sealing it. When one is given, check 3 runs
    too.

    ``expected_calls`` is ``None`` for a scenario whose arithmetic is not the
    clean run's and is asserted at the scenario instead. It is a deliberate
    opt-out and not a default: a scenario that quietly skipped check 4 would
    be the one place a bypassed stage could hide.
    """

    lineage = lineage_findings(records)
    found: list[str] = []
    found += stage_findings(records, execution)
    found += lineage.findings
    if not lineage.resolved:
        found.append(
            "the lineage walk resolved no reference at all; a trace that "
            "consumed nothing is not a chain"
        )
    if manifest is not None:
        indexed = manifest_findings(records, manifest, run_dir)
        found += indexed.findings
        if not indexed.resolved:
            found.append(
                "no consumed reference was resolved against the manifest"
            )
    if expected_calls is not None:
        found += call_findings(ledger, records, expected=expected_calls)
    found += fanout_findings(execution)
    found += pass_through_findings(records, run_dir)
    found += descent_findings(records, execution, run_dir)
    return tuple(found)


# ===========================================================================
# The scenario where S-03 decides something
# ===========================================================================

#: The one note that makes the canonical material block a decision. A note
#: becomes an E-07 only when it names the stage and the decision it stops
#: (F-3: S-03 is the sole producer of a gap), so this is the whole difference
#: between a run that enriches and one that does not — and it is a *model*
#: answer about the material, not an artifact authored into the path.
BLOCKING_NOTE: Final[Mapping[str, Any]] = {
    "kind": "evidence",
    "description": (
        "The material states what the carrier committed to and not what the "
        "commitment does to what a later buyer pays."
    ),
    "refs": [],
    "blocks_stage": "S-04",
    "blocks": "whether this material carries a reading the audience can act on",
}


class EnrichingMaterial(Material):
    """S-02's boundary in a scenario whose material blocks a decision.

    Two answers rather than one, and both are the answers an external boundary
    gives:

    * the description carries :data:`BLOCKING_NOTE`, which is what opens the
      gap S-03 then has to search for;
    * the extended assessment of the round is answered with the response this
      repository recorded for this case, because
      ``ExtendedEvidenceAssessor`` reaches **this** transport inside the loop
      rather than S-01's judgment seam — the same two-call boundary, routed by
      instructions exactly as the production stages route theirs.

    Nothing internal is replaced. What the engine does with the note — opening
    the E-07, building the search, re-assessing, recomputing the description
    and re-versioning the core — is S-03's own production path, and the point
    of the scenario is that the path is there to be bypassed.
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__(ledger)
        self._judgment = EvidenceJudgment(ledger)

    def answer(self, *, instructions: str, request: str) -> str:
        if instructions != MATERIAL_INSTRUCTIONS:
            return self._judgment.answer(
                instructions=instructions, request=request
            )
        described = json.loads(
            super().answer(instructions=instructions, request=request)
        )
        return json.dumps({**described, "notes": [dict(BLOCKING_NOTE)]})


def enriching_run(root: Path, *, signal_id: str = NET_SIGNAL) -> CanonicalRun:
    """One canonical run whose material opens a gap the loop must work on.

    The production path, unchanged: #351's configuration, producers,
    orchestration, ledger and budget, with one of the five handed-in seams
    answering differently. That is the line this slice draws — a deterministic
    substitute belongs at an external boundary and nowhere else — and it is
    what makes this a second *scenario* of the canonical path rather than a
    second path.
    """

    run = canonical_run(root, signal_id=signal_id)
    transports = replace(
        run.seams.transports, material=EnrichingMaterial(run.ledger)
    )
    return replace(run, seams=replace(run.seams, transports=transports))


# ===========================================================================
# The two instruments that break the path on purpose
# ===========================================================================


class MutationReport(NamedTuple):
    """What the net saw when one stage of the path was replaced.

    ``error`` is carried beside ``findings`` because a static artifact is
    frequently refused by the next production stage's own precondition — a
    unit whose boundary does not answer for its core, a plan written twice
    into one create-once path — and a refusal is a detection. What would **not**
    be a detection is a run that completed with no finding, which is exactly
    what :attr:`detected` is false for.
    """

    stage: str
    findings: tuple[str, ...]
    error: Optional[str]

    @property
    def detected(self) -> bool:
        return bool(self.findings) or self.error is not None


def static_artifacts(root: Path) -> dict[str, Any]:
    """One clean donor run's stage outputs, kept for substitution.

    The donor is a real canonical run over a **different** signal, recorded
    through the production functions rather than authored: that is what makes
    each captured value a typed artifact a production producer really made,
    and what makes substituting it into another run a *static* artifact — one
    the consuming run did not produce.

    Authoring them instead would make the mutation prove the author's idea of
    the shape rather than the net's ability to notice a foreign artifact.

    S-03's donated value is the empty gap set, because that is what the entry
    answers on a run with nothing to close. It is the weakest of the donations
    and the one worth having: a gap detector replaced by "nothing is missing"
    is the substitution a scenario with nothing missing cannot tell apart,
    which is why its host run is :func:`enriching_run`.
    """

    run = canonical_run(root, signal_id=DONOR_SIGNAL)
    store: dict[str, Any] = {}
    with _recording(store):
        execution, _, _ = execute(run)
    if execution.stopped_at is not None or len(set(execution.accepted)) != len(
        CANONICAL_DESTINATIONS
    ):
        raise AssertionError(
            "the donor run did not complete, so its stage outputs are not "
            f"artifacts a production producer made: stopped at "
            f"{execution.stopped_at!r} with {execution.accepted!r}"
        )
    missing = sorted(set(STAGE_PRODUCERS) - set(store))
    if missing:
        raise AssertionError(
            "the donor run never reached the production entry of "
            + ", ".join(missing)
            + "; a stage whose producer was not called cannot supply a static "
            "artifact, and the table names the entry the engine calls"
        )
    return store


def static_artifact_run(
    root: Path,
    *,
    stage: str,
    artifacts: Mapping[str, Any],
    enriching_calls: Optional[Mapping[str, int]] = None,
) -> MutationReport:
    """Replace one stage's production entry with a static artifact, and run.

    The engine, the configuration, the ledger and the budget are the
    production ones; exactly one name in ``src/run/golden_engine.py`` is
    rebound, and it is the stage's own entry function. That is the narrowest
    form of "this stage no longer produces what it produces" that the
    composition can be given.

    The host run is the canonical scenario for every stage but
    :data:`ENRICHING_STAGE`, which is substituted into :func:`enriching_run`
    because on the canonical one its entry answers what the substitute
    answers. ``enriching_calls`` is that scenario's own arithmetic, measured
    by :func:`boundary_calls` off an unmutated run of it, and it is required
    rather than defaulted: measuring the enriching scenario against the
    canonical counts would report a mutation nobody made, and this case would
    then pass whatever the engine did.
    """

    if stage == ENRICHING_STAGE:
        if enriching_calls is None:
            raise AssertionError(
                f"{stage} is substituted into the enriching scenario, and the "
                "counts it is measured against are that scenario's own; "
                "without them the case proves nothing it claims to"
            )
        run = enriching_run(root, signal_id=NET_SIGNAL)
        expected: Mapping[str, int] = enriching_calls
    else:
        run = canonical_run(root, signal_id=NET_SIGNAL)
        expected = CLEAN_RUN_CALLS
    static = artifacts[stage]
    with rebound(STAGE_PRODUCERS[stage], lambda *_args, **_kwargs: static):
        try:
            execution, workspace, _ = execute(run)
        except Exception as error:  # the stage after it refused the artifact
            return MutationReport(stage, (), f"{type(error).__name__}: {error}")
    return MutationReport(
        stage,
        composition_findings(
            records=execution.records,
            execution=execution,
            ledger=run.ledger,
            run_dir=workspace.run_dir,
            expected_calls=expected,
        ),
        None,
    )


class BypassReport(NamedTuple):
    """What a run whose required producer was removed managed to produce."""

    producer: str
    accepted: tuple[str, ...]
    stopped_at: Optional[str]
    error: Optional[str]

    @property
    def fails_closed(self) -> bool:
        """Nothing was accepted, and the run did not claim to complete."""

        return not self.accepted and (
            self.error is not None or self.stopped_at is not None
        )


def bypassed_run(root: Path, *, producer: str) -> BypassReport:
    """Assemble and run the canonical path with one required producer removed.

    The producer is rebound to one that answers ``None`` — "nobody produces
    this" — and the configuration is then assembled by the **production**
    :func:`~src.run.golden_engine.golden_engine_configuration`, so what the
    run is handed is what a run would be handed if that producer did not
    exist. Nothing is substituted for it: the point is that the path cannot be
    walked without it, not that it can be walked with a stand-in.

    The rebinding spans the assembly **and** the run, because the four
    producers are not all read at the same moment: three are authorities the
    configuration loads before S-00, and ``unit_facts`` is the lift S-07 makes
    out of the intake record while the run is under way.
    """

    name = REQUIRED_PRODUCERS[producer]
    with rebound(name, lambda *_args, **_kwargs: None):
        try:
            run = canonical_run(root, signal_id=NET_SIGNAL)
            execution, _, _ = execute(run)
        except Exception as error:
            return BypassReport(producer, (), None, f"{type(error).__name__}: {error}")
    return BypassReport(
        producer,
        tuple(item.value for item in execution.accepted),
        execution.stopped_at,
        None,
    )


@contextmanager
def rebound(name: str, replacement: Any) -> Iterator[None]:
    """Rebind one name in the engine's module namespace, and put it back.

    The engine calls every stage entry and every configuration producer as a
    module global, so this is the whole of "that producer is not there" — and
    the narrowest form of it: nothing about the orchestration, the workspace,
    the ledger or the budget changes.
    """

    original = getattr(golden_engine, name)
    setattr(golden_engine, name, replacement)
    try:
        yield
    finally:
        setattr(golden_engine, name, original)


@contextmanager
def _recording(store: dict[str, Any]) -> Iterator[None]:
    """Keep the first value each stage's production entry returned."""

    originals = {
        name: getattr(golden_engine, name)
        for name in STAGE_PRODUCERS.values()
    }
    for stage, name in STAGE_PRODUCERS.items():
        setattr(golden_engine, name, _recorder(stage, originals[name], store))
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(golden_engine, name, original)


def _recorder(stage: str, original: Any, store: dict[str, Any]) -> Any:
    """``original``, unchanged, with its first answer kept under ``stage``."""

    def recorded(*args: Any, **kwargs: Any) -> Any:
        value = original(*args, **kwargs)
        store.setdefault(stage, value)
        return value

    return recorded
