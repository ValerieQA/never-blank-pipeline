"""Issue #370: the progressive seam proofs, and the one full regression proof.

#351 proved that the canonical composition runs. What it did not do — and what
this module is — is make that proof **localising**. A single opaque
end-to-end test that goes red says "integration is broken"; the tests here say
which seam went, because each one is about one seam of the production path and
is given only the prefix of the trace that ends at that seam.

The chain, in the order the proofs are written:

* ``S-00 → S-01`` first: the selection the production S-00 wrote is the
  selection the production S-01 read, by entity type, ID and version;
* then that **plus** the next seam, and so on through ``E-15 → S-13``;
* then one full ``S-00 → S-13`` regression proof over the same sealed run,
  which is the whole net at once (:func:`composition_findings`).

Every run here is the production path: ``run_golden_engine`` over
``execute_canonical_topology``, with #351's deterministic boundary doubles in
the five seams production hands in. No stage is replaced, no entity is
hand-authored, and nothing writes into the workspace but the engine. The one
authored input is the intake record — the external boundary of the chain,
because #365's classifier sits upstream of S-00 and is provider-dependent —
and its two classifications are read off the client contract's own fit rules
rather than chosen here.

Nothing reaches a network, a provider, a credential or a publication, and S-14
is not executed.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from src.editorial_core.destinations import Destination
from src.run.golden_engine import GOLDEN_ENGINE_COMPONENT
from src.run.run_workspace import DeciderKind
from src.run.transports import MODEL_VAR
from src.run.walking_skeleton import CANONICAL_DESTINATIONS, run_golden_engine
from src.utils import llm_client
from tests.golden_engine_boundary import Ledger, TextCheck, canonical_run, execute
from tests.golden_engine_net import (
    CLEAN_RUN_CALLS,
    NET_SIGNAL,
    SEAMS,
    SELECTION_ENTITY_TYPE,
    STAGE_PRODUCERS,
    STAGES,
    composition_findings,
    descent_findings,
    fanout_findings,
    lineage_findings,
    manifest_findings,
    pass_through_findings,
    seam_pairs,
    stage_findings,
)

#: The consumer stages, in topology order. S-00 is absent because it consumes
#: nothing: the record it reads is the chain's external boundary, not a seam
#: between two stages.
CONSUMERS = tuple(stage for stage in STAGES if stage != "S-00")

#: The three seams the clean canonical scenario does not reach, and which route
#: reaches each. Declared so that ``SEAMS`` cannot quietly grow an entry nobody
#: exercises — the state the register was in when a destination-rule id was
#: cited by two test modules and produced by nothing.
UNEXERCISED_BY_A_CLEAN_RUN = (
    ("S-04", "E-09"),
    ("S-12", "E-15"),
    ("S-13", "E-09"),
)


@pytest.fixture(scope="module")
def sealed(tmp_path_factory):
    """One clean canonical run, executed once, sealed, and read by every test.

    Sealed through the production entrypoint rather than through
    ``execute_canonical_topology`` alone, because half of what this net proves
    is about the manifest: §4.3's verification covers every stage *output*
    against the entity index, and the consumed half — producer → ID and
    version → consumer — was nobody's to check until here.

    Module-scoped because it is the same run each of these proofs is about.
    Re-running it per test would not prove anything more and would turn the
    progressive chain into thirteen separate compositions.
    """

    root = tmp_path_factory.mktemp("net370")
    run = canonical_run(root, signal_id=NET_SIGNAL)
    result = run_golden_engine(
        seams=run.seams,
        configuration=run.configuration,
        signal=run.signal,
        binding=run.binding,
        runs_root=run.runs_root,
        started_at=run.now,
        now=run.now,
        # The ledger is redirected rather than defaulted: `data/editorial` is
        # tracked, and a test run that wrote a real run record into it would
        # arrive in the diff of whatever commit happened to follow.
        ledger_dir=root / "ledger",
    )
    return run, result


# ===========================================================================
# The progressive chain: one seam, then that plus the next
# ===========================================================================


@pytest.mark.parametrize("stage", CONSUMERS)
def test_the_seams_into_each_stage_resolve_to_a_production_producer(
    sealed, stage: str
):
    """``S-00 → S-01``, then that plus the next seam, and so on to S-13.

    Each case is given the prefix of the trace that ends at the **first**
    execution of its stage, so a break at one seam fails the proof named for
    that seam and leaves the shorter ones green. The failure message names the
    seam, the entity version and the scope it was consumed at — which is the
    whole difference between this and "integration is red".

    What is being resolved is not "a reference exists" but "an earlier stage of
    *this* run produced exactly this entity type, ID and version, and it is a
    stage this net declares as that seam's producer". A test that authored the
    input could never make that claim, which is the defect class the phantom
    destination-rule id belonged to.
    """

    _, result = sealed
    report = lineage_findings(result.records, through=stage)

    assert report.findings == (), "\n".join(report.findings)
    assert report.resolved >= 1, (
        f"the walk through {stage} resolved no reference, so it proved nothing"
    )


def test_each_step_of_the_chain_resolves_more_than_the_step_before(sealed):
    """The chain is progressive, and not thirteen views of one assertion.

    Without this, every case above could be reading the same two records and
    passing — a parametrized test that looks like coverage and is one test. The
    resolved count is strictly increasing because each stage of the topology
    consumes at least one artifact an earlier one produced.
    """

    _, result = sealed
    resolved = [
        lineage_findings(result.records, through=stage).resolved
        for stage in CONSUMERS
    ]

    assert resolved == sorted(set(resolved)), resolved
    assert resolved[0] >= 1
    assert resolved[-1] >= 45, (
        "the chain through S-13 resolves the references of every stage before "
        "it; #351 puts the run's own total at 50 or more"
    )


def test_a_seam_proof_over_a_stage_that_did_not_run_proves_nothing(sealed):
    """The localising claim cannot be satisfied by a trace that stopped short.

    ``through`` names a stage, and a prefix that never reaches it would
    otherwise be a clean walk over a shorter run — which is exactly how a
    composition that quietly stops at S-06 would pass every seam proof past it.
    """

    _, result = sealed
    truncated = tuple(
        record for record in result.records if record.stage != "S-09"
    )

    report = lineage_findings(truncated, through="S-09")

    assert report.findings, "a seam proof over a stage that did not run passed"
    assert "never reached S-09" in report.findings[0]


# ===========================================================================
# The one full S-00 → S-13 regression proof
# ===========================================================================


def test_the_full_canonical_composition_has_no_broken_seam(sealed):
    """Every check of the net, over one sealed production run.

    This is the regression proof the slice is judged on: the stages the
    topology declares each executed, every consumed reference resolves to the
    production producer that wrote it — in the trace and in the manifest, at
    the digest the workspace recorded — the per-boundary call counts are the
    topology's own arithmetic, all six destinations hold an accepted text, no
    ``pass_through`` marker is anywhere, and the run's artifacts are about the
    material it was given.
    """

    run, result = sealed

    findings = composition_findings(
        records=result.records,
        execution=result.execution,
        ledger=run.ledger,
        run_dir=result.run_dir,
        manifest=result.manifest,
    )

    assert findings == (), "\n".join(findings)


def test_every_stage_is_reached_through_production_orchestration(sealed):
    """Reached by the engine, and recorded as the engine's.

    ``component`` is the layer that executed the stage, and a canonical
    execution is told apart from anything else by that value alone — so a
    record written by some other harness beside the engine would be visible
    here rather than counted as a stage the composition reached.
    """

    _, result = sealed

    assert stage_findings(result.records, result.execution) == ()
    assert {record.created_by.component for record in result.records} == {
        GOLDEN_ENGINE_COMPONENT
    }
    assert result.execution.stopped_at is None


def test_the_manifest_resolves_every_consumed_version(sealed):
    """The half §4.3 left open: the consumer side of the entity index.

    ``verify_run_workspace`` proves each recorded *output* is indexed at the
    digest the index holds; nothing proved it of an input, so a stage naming a
    version the manifest does not hold would verify and still be a reference to
    nothing. Here every consumed reference is resolved against the index, the
    file is read back and re-digested, and E-15 is compared against its own
    ``content_digest`` — the value V-T05 and publication idempotency use.
    """

    _, result = sealed

    report = manifest_findings(result.records, result.manifest, result.run_dir)

    assert report.findings == (), "\n".join(report.findings)
    assert report.resolved == lineage_findings(result.records).resolved, (
        "the manifest resolved fewer references than the trace did"
    )
    assert result.verification.verified_stage_records == len(result.records)
    assert result.verification.verified_entities == len(
        result.manifest.entities
    )


def test_the_declared_seams_are_the_ones_the_clean_run_records(sealed):
    """``SEAMS`` is a declaration, and this is what keeps it one.

    Two directions, and both matter. No pair the run exercised may be
    undeclared, or the net would be resolving a seam nobody wrote down; and no
    pair may be declared that no scenario reaches, which is the state the
    register was in when two test modules cited a destination-rule id nothing
    produced. The three that a clean run does not reach are named, with the
    route that reaches each proved below.
    """

    _, result = sealed
    exercised = seam_pairs(result.records)

    assert exercised <= set(SEAMS), sorted(exercised - set(SEAMS))
    assert sorted(set(SEAMS) - exercised) == sorted(
        UNEXERCISED_BY_A_CLEAN_RUN
    )
    assert (
        "S-01",
        SELECTION_ENTITY_TYPE,
    ) in exercised, "the first seam of the chain was not exercised"


# ===========================================================================
# The fan-out, and what each lane carries out of S-13
# ===========================================================================


def test_the_six_destination_fanout_is_exercised(sealed):
    """Six lanes, six accepted texts, six verdicts, six destination folders."""

    _, result = sealed

    assert fanout_findings(result.execution) == ()
    assert {item.value for item in result.execution.accepted} == set(
        CANONICAL_DESTINATIONS
    )
    assert {path.name for path in result.destination_dirs} == set(
        CANONICAL_DESTINATIONS
    )
    assert {
        verdict.destination for verdict in result.execution.verdicts
    } == set(Destination)


def test_s03_runs_and_opens_no_enrichment_round(sealed):
    """S-03 executes, consumes S-02's features, and runs zero rounds.

    "No blocking gap → zero rounds" is the ordinary result and the common one,
    and the stage still records that it ran: a stage that left no entity is not
    a stage that did not execute. It is also why S-03 is absent from
    ``STAGE_PRODUCERS``: a stage that asks no boundary and opens no round has
    no artifact a static one could be stood in for, so its seam is proved by
    what it consumed rather than by a substitution that would change nothing.
    """

    run, result = sealed
    records = [record for record in result.records if record.stage == "S-03"]

    assert len(records) == 1
    (record,) = records
    assert (record.calls or {}).get("count", 0) == 0
    assert record.created_by.decider is DeciderKind.CODE
    assert record.created_by.request_digest is None
    assert [ref.entity_type for ref in record.inputs] == ["E-05"]
    assert all(ref.entity_type == "E-07" for ref in record.outputs)
    # One material call in the whole run, and it is S-02's: an enrichment round
    # would be a second, so this is the evidence that none ran.
    assert run.ledger.count("material") == CLEAN_RUN_CALLS["material"] == 1
    assert "S-03" not in STAGE_PRODUCERS


# ===========================================================================
# No provider, no credential, no model configuration
# ===========================================================================


def test_the_composition_reaches_no_provider_client(tmp_path, monkeypatch):
    """The whole path, with the one door to a billed call nailed shut.

    ``tests/conftest.py`` already strips the key variables, which makes a real
    call fail; this makes it fail *visibly as a test failure* rather than as a
    provider error inside a stage. ``_get_client`` is where every billed call
    begins, and ``chat`` is the only charged caller of it, so a run that
    completes with both of them raising reached neither.
    """

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "the canonical composition reached the OpenAI client; its model "
            "boundaries are handed in as seams precisely so it cannot"
        )

    monkeypatch.setattr(llm_client, "_get_client", refuse)
    monkeypatch.setattr(llm_client, "chat", refuse)

    run = canonical_run(tmp_path, signal_id=NET_SIGNAL)
    execution, workspace, _ = execute(run)

    assert composition_findings(
        records=execution.records,
        execution=execution,
        ledger=run.ledger,
        run_dir=workspace.run_dir,
    ) == ()


def test_the_composition_needs_no_live_model_configuration(
    tmp_path, monkeypatch
):
    """CI stays green without ``NB_GOLDEN_ENGINE_MODEL`` or a key.

    #361 makes that variable the only source of the model and refuses
    construction without it — which is why the canonical path takes its
    transports as a handed-in seam rather than building them. Asserted with the
    variable removed from the environment, so a run that had started reading it
    would fail here instead of on a runner that happens not to set it.
    """

    monkeypatch.delenv(MODEL_VAR, raising=False)
    assert MODEL_VAR not in os.environ
    assert "NB_OPENAI_API_KEY" not in os.environ

    run = canonical_run(tmp_path, signal_id=NET_SIGNAL)
    execution, _, _ = execute(run)

    assert len(set(execution.accepted)) == len(CANONICAL_DESTINATIONS)
    assert execution.stopped_at is None


# ===========================================================================
# The three routes a clean run does not take
# ===========================================================================


def test_the_bounded_edit_loop_keeps_every_seam_of_the_composition(tmp_path):
    """``L_edit`` routes S-13 → S-12 once, and the net still resolves.

    The edit is the one place a stage consumes its **own** earlier output: the
    revision is the next version of a text S-12 wrote, so ``E-15 → S-12`` is a
    seam of the path and is reached by no clean run. Asserted as the whole net
    over the edit scenario — one extra write and two extra checks, which is the
    loop's own arithmetic — so that the edited text is proved to descend from
    the text it revises rather than merely to exist.
    """

    run = canonical_run(
        tmp_path,
        signal_id=NET_SIGNAL,
        text_check=TextCheck(Ledger(), fails="V-T06", from_call=1),
    )
    execution, workspace, _ = execute(run)

    findings = composition_findings(
        records=execution.records,
        execution=execution,
        ledger=run.ledger,
        run_dir=workspace.run_dir,
        expected_calls={**CLEAN_RUN_CALLS, "writer": 7, "text_check": 14},
    )
    assert findings == (), "\n".join(findings)
    assert ("S-12", "E-15") in seam_pairs(execution.records)


def test_a_replan_back_into_s08_keeps_every_seam_of_the_composition(tmp_path):
    """``L_strategy`` routes S-13 → S-08, and the re-planned lane still resolves.

    The route is only taken if the record that authorizes it travels: #304's
    ``_authorized`` refuses an attempt that cannot name which counter paid for
    it at which scope, so a seventh S-08 execution is the proof that the
    authorization propagated and not merely that the stage was re-called. What
    this adds to #351 is that the re-planned lane's second candidate set, plan,
    verdict and text all resolve through the net like the first.

    ``expected_calls`` is ``None`` here: a re-plan changes seven of the
    fourteen counts, and the scenario asserts the one the route is about rather
    than restating an arithmetic nobody derived.
    """

    run = canonical_run(
        tmp_path,
        signal_id=NET_SIGNAL,
        text_check=TextCheck(Ledger(), fails="V-T03", from_call=1),
    )
    execution, workspace, _ = execute(run)

    findings = composition_findings(
        records=execution.records,
        execution=execution,
        ledger=run.ledger,
        run_dir=workspace.run_dir,
        expected_calls=None,
    )
    assert findings == (), "\n".join(findings)
    assert run.ledger.count("strategy") == 7, "the route back to S-08 was taken"
    assert sum(1 for item in execution.records if item.stage == "S-08") == 7


def test_the_f4_sibling_recheck_keeps_the_lineage_of_every_sibling(tmp_path):
    """A boundary commit mid-run, and the two seams only it reaches.

    The sixth text fails V-T02, so five siblings are already accepted when the
    boundary moves — the situation F-4 exists for. Two seams of the path are
    reached here and nowhere else: ``E-09 → S-04``, the re-entry reading the
    version it replaces, and ``E-09 → S-13``, the sibling re-check reading the
    version that put those five in question.

    The net's lineage walk is what is asserted, over a run that does **not**
    reach six accepted texts: this scenario runs the canonical ceiling out, so
    the fan-out check would correctly report five. What must still hold is that
    every artifact consumed after the commit was produced by this run, and that
    the second boundary version is the one the later stages read.
    """

    run = canonical_run(
        tmp_path,
        signal_id=NET_SIGNAL,
        text_check=TextCheck(Ledger(), fails="V-T02", from_call=6),
    )
    execution, workspace, _ = execute(run)

    report = lineage_findings(execution.records)
    assert report.findings == (), "\n".join(report.findings)
    assert pass_through_findings(execution.records, workspace.run_dir) == ()
    assert descent_findings(
        execution.records, execution, workspace.run_dir
    ) == ()

    exercised = seam_pairs(execution.records)
    assert ("S-04", "E-09") in exercised, "the re-entry read no boundary"
    assert ("S-13", "E-09") in exercised, "no sibling was re-checked"
    # Two S-04 executions and two boundary versions: the first, and the one the
    # re-entry committed. A run with one would have re-checked nothing.
    boundaries = {
        ref.version
        for record in execution.records
        for ref in record.outputs
        if ref.entity_type == "E-09"
    }
    assert boundaries == {1, 2}
    assert len(set(execution.accepted)) == 5
