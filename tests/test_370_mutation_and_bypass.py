"""Issue #370: the net is shown to catch what it claims to catch.

A safety net nobody has torn is a net nobody has measured. Every proof in
``tests/test_370_integration_net.py`` is green over the path as it stands; this
module breaks the path on purpose, one seam at a time, and requires the net to
notice. Three families, and each answers one acceptance criterion:

1. **a real stage replaced by a static artifact.** One case per wired stage,
   all fourteen. The substitute is not authored: it is the output a *donor*
   canonical run's production producer really made, over a different signal —
   which is exactly what a "static artifact" is, an artifact the consuming run
   did not produce. An authored one would test the author's idea of the shape;
   this tests whether the net can tell a foreign artifact from the run's own.
   Thirteen are substituted into the canonical scenario and S-03 into the
   enriching one, because a gap detector replaced by "nothing is missing" is
   only a mutation on a run where something is.
2. **a required production producer removed.** Each of the four the issue
   names answers ``None`` in turn — "nobody produces this" — with the
   configuration assembled by the production ``golden_engine_configuration``
   and the run executed by the production engine, and the path must fail
   closed: no accepted text, and no run that claims to have completed.
3. **a stage-to-stage reference broken.** The net's own sensitivity, over the
   trace and the manifest of a clean run: a version nobody produced, a digest
   nobody wrote, a reference that resolves only to a later output, an
   undeclared seam, a stage dropped from the trace, a manifest that does not
   hold the consumed version, and an entity file that left the workspace after
   the run sealed it. These cannot be proved by breaking the engine — there is
   no production path that writes a wrong version — so they are proved the way
   this repository proves its other detectors: with a planted violation.

The defect class behind all three is the one the chain was built to end.
``tests/test_305_…`` and ``tests/test_306_…`` cited a destination-rule id that
names no record — the one ``tests/test_363_configuration_producers.py`` keeps
retired — and stayed green for months, because a test that authors its own
input can never notice that nobody produces it.

Nothing here reaches a network, a provider, a credential or a publication.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.editorial_core.destinations import UnitFacts
from src.run import golden_engine
from src.run.run_workspace import StageRecord
from src.run.signal_adapter import DOMAIN_FIELD, RISK_FIELD
from src.run.walking_skeleton import CANONICAL_DESTINATIONS, run_golden_engine
from tests.golden_engine_boundary import canonical_run, execute
from tests.golden_engine_net import (
    CLEAN_RUN_CALLS,
    DONOR_SIGNAL,
    ENRICHING_STAGE,
    NET_SIGNAL,
    REQUIRED_PRODUCERS,
    STAGE_PRODUCERS,
    boundary_calls,
    bypassed_run,
    enriching_run,
    lineage_findings,
    manifest_findings,
    rebound,
    stage_findings,
    static_artifact_run,
    static_artifacts,
)

#: A digest no file of any run has, in the shape ``EntityRef`` requires.
FOREIGN_DIGEST = "sha256:" + "0" * 64


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    """One donor canonical run's stage outputs, captured once.

    Module-scoped because capturing them is a whole canonical run: a
    substitution per stage over a fresh host run each is the expensive half,
    and re-donating per case would double it without proving anything more.
    """

    return static_artifacts(tmp_path_factory.mktemp("donor370"))


@pytest.fixture(scope="module")
def enriching(tmp_path_factory):
    """One clean run of the enriching scenario, and what it asked each boundary.

    The baseline the S-03 substitution is measured against, and it is measured
    rather than declared: what that case proves is a difference between the
    same scenario mutated and unmutated, and a number written here by hand
    would be a third thing that could be wrong.

    Module-scoped for the reason the donor is — it is a whole canonical run.
    """

    root = tmp_path_factory.mktemp("enriching370")
    run = enriching_run(root, signal_id=NET_SIGNAL)
    execution, _, _ = execute(run)
    return run, execution


@pytest.fixture(scope="module")
def sealed(tmp_path_factory):
    """One clean sealed run, whose evidence the planted violations mutate.

    Read-only here: every mutation below builds a new tuple or copies the
    workspace, so no case can leave the others looking at a trace some earlier
    case edited.
    """

    root = tmp_path_factory.mktemp("planted370")
    run = canonical_run(root, signal_id=NET_SIGNAL)
    return run_golden_engine(
        seams=run.seams,
        configuration=run.configuration,
        signal=run.signal,
        binding=run.binding,
        runs_root=run.runs_root,
        started_at=run.now,
        now=run.now,
        ledger_dir=root / "ledger",
    )


# ===========================================================================
# 1 · a real stage replaced by a static artifact
# ===========================================================================


def test_the_donor_run_supplies_an_artifact_for_every_substitutable_stage(
    artifacts,
):
    """The instrument works before it is used to measure anything.

    One captured output per wired stage, each produced by the production entry
    the engine calls — and the donor is a different signal, so an artifact
    substituted into the host run carries identities the host never produced.
    Without this, a case below could pass because the substitution never
    happened.

    S-03's is the empty gap set, which is what its entry answers on a run with
    nothing to close. It is named here rather than left to be noticed, because
    it is the one donation that carries no identity of the donor at all and so
    the one that needs a host run whose own answer would differ.
    """

    assert sorted(artifacts) == sorted(STAGE_PRODUCERS)
    assert all(value is not None for value in artifacts.values())
    assert DONOR_SIGNAL != NET_SIGNAL
    assert artifacts[ENRICHING_STAGE] == ()


@pytest.mark.parametrize("stage", sorted(STAGE_PRODUCERS))
def test_replacing_one_real_stage_with_a_static_artifact_is_caught(
    tmp_path: Path, artifacts, enriching, stage: str
):
    """Acceptance: replacing any one real stage makes the proof fail.

    Exactly one name in ``src/run/golden_engine.py`` is rebound — the stage's
    own production entry — and everything else is the production path: the
    orchestration, the configuration, the workspace, the attempt ledger and the
    call budget. So what this measures is the composition noticing that one
    stage stopped producing what it produces.

    Two shapes of detection, and both count. The stage that reads the static
    artifact next frequently refuses it by its own precondition — a unit whose
    boundary does not answer for its core, a plan written twice into one
    create-once path — and a refusal is the composition failing closed. Where
    nothing refuses, the net reports it: the substituted stage asked its model
    boundary nothing, or the artifact's identities are not this run's.

    ``ENRICHING_STAGE`` is the one stage whose host run is not the canonical
    scenario, and ``static_artifact_run`` picks it: its entry is the gap
    detection, and on a run with nothing to close the substitute is the
    stage's own answer handed back to it — a case that cannot fail and
    therefore proves nothing. It is measured on the scenario whose material
    blocks a decision, against that scenario's own measured arithmetic.

    What would **not** be a detection is a run that completed with the net
    finding nothing, which is what :attr:`MutationReport.detected` is false for.
    """

    clean, _ = enriching
    report = static_artifact_run(
        tmp_path,
        stage=stage,
        artifacts=artifacts,
        enriching_calls=boundary_calls(clean.ledger),
    )

    assert report.detected, (
        f"{stage} was replaced by an artifact of another run and the "
        "composition proof stayed green"
    )


def test_the_enriching_scenario_spends_what_the_canonical_one_does_not(
    enriching,
):
    """The S-03 case has a baseline, and the baseline is a round that ran.

    Everything the substitution above claims rests on this: the unmutated
    scenario reaches a boundary the canonical one does not, because S-03
    opened a gap and searched for it. A scenario that quietly stopped
    enriching would leave that case comparing a run with nothing in it against
    a baseline with nothing in it, and passing for the wrong reason.
    """

    run, execution = enriching
    calls = boundary_calls(run.ledger)

    assert execution.stopped_at is None
    assert len(set(execution.accepted)) == len(CANONICAL_DESTINATIONS)
    assert calls["material"] > CLEAN_RUN_CALLS["material"], calls


def test_the_substitution_is_undone_and_the_path_is_the_production_path(
    tmp_path: Path, artifacts
):
    """The instrument leaves nothing behind.

    A rebinding that outlived its case would make every later test in the
    session a test of a mutated engine — green or red for a reason nobody
    wrote. So the entry is compared with itself across a substitution, and a
    clean run afterwards is required to complete.
    """

    before = getattr(golden_engine, STAGE_PRODUCERS["S-06"])
    static_artifact_run(tmp_path / "mutated", stage="S-06", artifacts=artifacts)

    assert getattr(golden_engine, STAGE_PRODUCERS["S-06"]) is before
    run = canonical_run(tmp_path / "clean", signal_id=NET_SIGNAL)
    execution, _, _ = execute(run)
    assert len(set(execution.accepted)) == len(CANONICAL_DESTINATIONS)


# ===========================================================================
# 2 · a required production producer removed
# ===========================================================================


@pytest.mark.parametrize("producer", sorted(REQUIRED_PRODUCERS))
def test_removing_a_required_production_producer_fails_closed(
    tmp_path: Path, producer: str
):
    """Acceptance: bypassing a required producer makes the proof fail closed.

    The four the issue names. ``StrategyContract``, ``AdaptationContract`` and
    ``StrengthLadder`` are authorities a run *loads*, each from its own
    producer in ``golden_engine_configuration``; ``UnitFacts`` is the lift S-07
    makes out of the intake record while the run is under way. Each is removed
    in turn by rebinding its producer to one that answers ``None``, across the
    assembly and the run alike, and everything else is the production path —
    so what the run is handed is what it would be handed if that producer were
    not there.

    Nothing is substituted for the missing value. The claim is that the path
    cannot be walked without it, and "fails closed" is the conjunction of two
    things: no destination holds an accepted text, and the run does not report
    a completed traversal. A run that produced five texts and said so would be
    worse than one that stopped.
    """

    report = bypassed_run(tmp_path, producer=producer)

    assert report.accepted == (), (
        f"the canonical path accepted {report.accepted} with no "
        f"{producer} producer"
    )
    assert report.fails_closed, report


def test_the_unit_facts_s07_decides_on_move_with_the_record_they_are_lifted_from(
    tmp_path: Path,
):
    """The lift is a lift, and not a producer answering the same thing twice.

    §1 says the two values are "lifted out and handed over", and what they are
    lifted from is the two fields #365 persists on the intake record before
    S-00 sees it. A spy over **one** run cannot tell that apart from a
    producer that answers those two strings whatever record it is handed — the
    fixture's classifications are constants, and a constant matches a
    constant.

    So the production path is walked twice, over two records stating two
    editorial domains the client contract admits, and what S-07 was handed has
    to move with the record it came from. A replacement that answered the
    canonical record's domain both times fails the second case.

    The production ``decide_destinations`` still runs: the spy passes the call
    through, so each of these is the canonical run and not a run with S-07
    replaced.
    """

    seen: list[UnitFacts] = []
    original = golden_engine.decide_destinations

    def watching(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs["facts"])
        return original(*args, **kwargs)

    first = canonical_run(tmp_path / "first", signal_id=NET_SIGNAL)
    second = canonical_run(tmp_path / "second", signal_id=NET_SIGNAL)
    # The contract's own admitted values, in its own spelling: a second domain
    # chosen here would be a value the client never approved, and S-00 would
    # refuse the record before S-07 could be asked anything.
    admitted = first.configuration.fit_rules.rules[0].admits
    assert len(admitted) >= 2, (
        "the client contract admits one editorial domain, so no second record "
        "can distinguish the lift from a constant; this case has to be "
        "rewritten rather than left passing"
    )
    assert first.signal[DOMAIN_FIELD] == admitted[0]
    other = replace(
        second, signal={**second.signal, DOMAIN_FIELD: admitted[-1]}
    )

    with rebound("decide_destinations", watching):
        for run in (first, other):
            execution, _, _ = execute(run)
            assert execution.stopped_at is None

    assert [facts.topic_key for facts in seen] == [admitted[0], admitted[-1]]
    assert {facts.risk_level for facts in seen} == {first.signal[RISK_FIELD]}


def test_a_record_that_states_neither_classification_never_reaches_s07(
    tmp_path: Path,
):
    """And the record that states nothing is refused before S-07, not at it.

    A record carrying neither field is refused by the fit rule that owns the
    refusal, at S-00, before anything is spent — so the run this net would
    otherwise prove does not happen at all. That is the fail-closed direction
    on the *record*: the engine does not reach S-07 and decide six
    destinations on facts it made up on the way. The fail-closed direction on
    the *producer* is the bypass case above, where the record states both and
    the lift is the thing that is gone.
    """

    run = canonical_run(tmp_path, signal_id=NET_SIGNAL)
    stated = {
        key: value
        for key, value in run.signal.items()
        if key not in {DOMAIN_FIELD, RISK_FIELD}
    }

    execution, _, _ = execute(replace(run, signal=stated))

    assert execution.stopped_at == "S-00"
    assert execution.accepted == ()
    assert {record.stage for record in execution.records} == {"S-00"}


# ===========================================================================
# 3 · a stage-to-stage artifact or version reference broken
# ===========================================================================


def test_a_consumer_that_names_a_version_nobody_produced_is_caught(sealed):
    """Acceptance: breaking one stage-to-stage version reference fails the proof.

    S-05 reads the boundary version S-04 committed. Moved to a version this run
    never wrote, the reference resolves to nothing — and the finding names the
    seam, the version and the scope, which is what makes the failure legible
    without reading the trace.
    """

    planted = _with_changed_input(
        sealed.records, stage="S-05", on="E-09", version=99
    )

    findings = lineage_findings(planted).findings

    assert findings, "a version nobody produced resolved"
    assert any(
        "E-09" in item and "S-05" in item and "v99" in item
        for item in findings
    ), findings


def test_a_consumer_that_names_a_digest_nobody_wrote_is_caught(sealed):
    """The identity resolved and the bytes did not.

    A reference by ID and version alone would pass here: the entity exists and
    the version is the one S-04 wrote. What is broken is the digest, which is
    how "the consumer read the artifact the producer wrote" is distinguished
    from "the consumer read something with the same name".
    """

    planted = _with_changed_input(
        sealed.records, stage="S-05", on="E-09", digest=FOREIGN_DIGEST
    )

    findings = lineage_findings(planted).findings

    assert findings, "a digest nobody wrote resolved"
    assert any(FOREIGN_DIGEST in item for item in findings), findings


def test_a_reference_that_resolves_only_to_a_later_output_is_caught(sealed):
    """The chain is a chain because the producer ran first.

    The two records are swapped rather than edited, so S-01 consumes a
    selection that is still written — just written afterwards. A walk that
    resolved against the whole trace at once would call this clean, which is
    why the walk is in trace order.
    """

    records = list(sealed.records)
    records[0], records[1] = records[1], records[0]

    findings = lineage_findings(tuple(records)).findings

    assert findings, "a reference to a later output resolved"
    assert any("S-01" in item for item in findings), findings


def test_an_undeclared_seam_is_caught(sealed):
    """A seam is declared before it is proved, or it is not a seam.

    This is the phantom-id shape in its purest form: a consumer reading an
    entity type nobody declares a producer for. The net refuses to resolve it
    at all rather than looking for any earlier output that happens to match.
    """

    planted = _with_changed_input(
        sealed.records, stage="S-05", on="E-04", entity_type="E-99"
    )

    findings = lineage_findings(planted).findings

    assert findings, "an undeclared seam resolved"
    assert any("declares no such seam" in item for item in findings), findings


def test_a_stage_dropped_from_the_trace_is_caught(sealed):
    """A composition that skipped a stage is not the composition.

    Named rather than counted: the finding says which stage left no execution
    record, because "the trace is shorter than it was" is not something a
    reader can act on.
    """

    planted = tuple(
        record for record in sealed.records if record.stage != "S-06"
    )

    findings = stage_findings(planted, sealed.execution)

    assert findings, "a trace with no S-06 execution passed"
    assert "S-06" in findings[0]


def test_a_manifest_that_does_not_hold_the_consumed_version_is_caught(sealed):
    """The consumer half of §4.3, which nothing checked before this slice.

    ``verify_run_workspace`` proves every recorded *output* is in the entity
    index at the digest the index holds. With the index entry for the boundary
    marker removed, that verification still passes for every output that
    remains — and a consumer naming the version it read resolves to nothing.
    """

    kept = tuple(
        entry for entry in sealed.manifest.entities if entry.entity_type != "E-09"
    )
    assert len(kept) < len(sealed.manifest.entities), "nothing was removed"
    planted = sealed.manifest.model_copy(update={"entities": kept})

    report = manifest_findings(sealed.records, planted, sealed.run_dir)

    assert report.findings, "a manifest missing the consumed version passed"
    assert any(
        "entity index does not hold" in item for item in report.findings
    ), report.findings


def test_an_entity_file_that_left_the_workspace_is_caught(
    sealed, tmp_path: Path
):
    """The reference resolved, the index agreed, and the bytes are gone.

    Over a copy of the sealed workspace, so the shared run stays the run every
    other proof here is about. A reference whose file is missing is exactly the
    state a trace cites a record that does not exist in — and the one a check
    that stopped at the index would report as clean.
    """

    copied = tmp_path / "copy"
    shutil.copytree(sealed.run_dir, copied)
    removed = next(
        copied / entry.path
        for entry in sealed.manifest.entities
        if entry.entity_type == "E-09"
    )
    removed.unlink()

    report = manifest_findings(sealed.records, sealed.manifest, copied)

    assert report.findings, "a reference to a file that is gone resolved"
    assert any("not in the workspace" in item for item in report.findings), (
        report.findings
    )


def test_the_planted_violations_are_the_only_thing_wrong_with_the_evidence(
    sealed,
):
    """Each case above is one violation, and the clean evidence has none.

    Without this, every assertion in this section could be passing on a trace
    that was already broken — a detector that reports a finding whatever it is
    given detects nothing.
    """

    assert lineage_findings(sealed.records).findings == ()
    assert stage_findings(sealed.records, sealed.execution) == ()
    assert manifest_findings(
        sealed.records, sealed.manifest, sealed.run_dir
    ).findings == ()


# ===========================================================================
# Helpers
# ===========================================================================


def _with_changed_input(
    records: tuple[StageRecord, ...],
    *,
    stage: str,
    on: str,
    **changes: Any,
) -> tuple[StageRecord, ...]:
    """The trace with one consumed reference of one stage changed.

    ``stage`` and ``on`` name the seam the violation is planted in — the first
    execution of that stage, and its reference of that entity type — so each
    case below says which seam it broke rather than relying on the order a
    stage happens to list its inputs in.

    ``model_copy`` and not a rebuild: a StageRecord validates itself on
    construction, and a planted violation the model refused would prove the
    model's validators rather than the net's checks. What is being asked is
    what the net does with a record describing a reference nobody produced —
    the state a trace is in when a stage is wired to something not there.
    """

    planted: list[StageRecord] = []
    done = False
    for record in records:
        changed = [
            ref.model_copy(update=changes)
            if not done and ref.entity_type == on
            else ref
            for ref in record.inputs
        ]
        if not done and record.stage == stage and changed != list(record.inputs):
            planted.append(record.model_copy(update={"inputs": tuple(changed)}))
            done = True
        else:
            planted.append(record)
    if not done:
        raise AssertionError(
            f"the first {stage} execution consumed no {on}, so nothing was "
            "planted and the case would prove nothing"
        )
    return tuple(planted)
