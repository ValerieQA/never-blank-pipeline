"""Issue #302: S-05 makes one unit of a signal, and records the split it did not make.

SL-4's acceptance evidence for the Editorial Units stage, taken from the map's
own two-story walkthrough (§13 D, "a company cut costs by 40% and
simultaneously took on a regulatory risk") — the one walkthrough AD-03 was
written for, and the one the initial cap of 1 deliberately does not honour:

1. the **two-story signal** sets ``split_candidate`` and still becomes exactly
   one unit, whose interpretation scope is the whole admissible set;
2. **no deferred-unit writer is reachable**: the stage cannot reach the ledger,
   the two statuses only a split produces cannot be constructed, and a full
   execution creates nothing outside its own 90-day workspace;
3. rule 3 is recorded as ``not_evaluated`` and can be recorded as nothing else,
   because S-05 makes no call and never asked it;
4. the flag reaches both places Step 3 puts it: the run trace, in the E-10
   ``split`` record, and the durable RunSummary.

And the properties rules 1 and 2 rest on: a premise of a premise is still a
premise, a dependency the boundary does not list fails closed, and support one
reading shares with the other is not support of its own.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.artifacts import ArtifactCollisionError
from src.editorial_core.arp import ArpOutcome, OutcomeRecord, OutcomeScope, StateCode
from src.editorial_core.editorial_units import (
    SPLIT_CAP,
    STAGE,
    EditorialUnit,
    InterpretationPair,
    SplitRecord,
    SplitRuleResult,
    UnitError,
    UnitStatus,
    create_unit,
    run_split_candidate,
    unit_id,
    unit_relative_path,
    write_unit,
)
from src.editorial_core.evidence_core import (
    EvidenceClaim,
    EvidenceCore,
    ObservationKind,
    SourceObservation,
    StrengthLadder,
)
from src.editorial_core.interpretation_boundary import (
    InadmissibleReason,
    Interpretation,
    InterpretationBoundary,
    InterpretationKind,
    Justification,
    ProbeApplication,
    ProbeFinding,
    ReaderConnection,
    boundary_id,
)
from src.editorial_core.relevance_screen import AudienceTransfer, DecisionRef
from src.research.evidence import (
    EvidenceDisposition,
    EvidenceReadiness,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    SourceLocator,
    SourceLocatorKind,
)
from src.run.boundary_commit import Admissibility
from src.run.ledger import LedgerCommitStatus
from src.run.run_context import ExecutionMode, RunContext, create_run_id
from src.run.run_manifest import RunInputs, RunManifest
from src.run.run_summary import RunScope, RunSummary, WorkspaceRef
from src.run.run_workspace import RunWorkspace, WriteOwnershipError, owner_of

_REPO_ROOT = Path(__file__).resolve().parents[1]

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

#: The universal default ladder (K-LAD-01), as the earlier SL-4 suite hands it
#: to S-04. S-05 never reads a strength; it is here because an E-08 record
#: carries one.
LADDER = StrengthLadder(
    ladder_id="K-LAD-01",
    levels=(
        'Reported: "X says / reports …"',
        'Documented in a case: "in this case, …"',
        'Corroborated: "several independent sources show …"',
        'Established: "across … , …"',
    ),
)

SIGNAL = "signal-302-two-story"
CORE = "core-302-two-story"

#: §13 D's claims: two stories in one signal, each with evidence of its own.
CLAIMS: dict[str, str] = {
    "ev-d-1": "The company reports operating costs 40% below the prior year.",
    "ev-d-2": "The filing records the same change as entering a regulated activity.",
    "ev-d-3": "The reduction is reported for the first full quarter after the change.",
    "ev-d-4": "The regulator's register lists the activity as requiring authorisation.",
}

#: The cost story and the risk story, as S-04 would have left them: neither
#: rests on the other, and neither cites a claim the other cites.
COST = "int-302-cost"
RISK = "int-302-risk"


def _core(core_id: str = CORE, version: int = 1) -> EvidenceCore:
    """One walkthrough-D core. E-04 is what S-05 reads the signal from."""

    observations = tuple(
        SourceObservation(
            observation_id=f"obs-{identity}",
            signal_id=SIGNAL,
            source_ref="src-1",
            kind=ObservationKind.QUOTE,
            excerpt=statement,
            attribution=f"Example Press reports: {statement}",
            is_third_party_assertion=False,
        )
        for identity, statement in CLAIMS.items()
    )
    claims = tuple(
        EvidenceClaim(
            evidence_claim_id=identity,
            statement=statement,
            observation_refs=(f"obs-{identity}",),
            source_refs=("src-1",),
            verdict=EvidenceDisposition.ACCEPTED,
            verdict_rationale="The cited excerpt states it.",
            scope="One named company, as reported.",
            strength=LADDER.at(2),
            ceiling=LADDER.at(2),
        )
        for identity, statement in CLAIMS.items()
    )
    return EvidenceCore(
        core_id=core_id,
        version=version,
        signal_ids=(SIGNAL,),
        research_artifact_refs=(("artifact-302", "sha256:" + "d" * 64),),
        sources=(
            NormalizedSource(
                source_id="src-1",
                locator=SourceLocator(
                    kind=SourceLocatorKind.URL, value="https://example.test/item"
                ),
                title="Recorded report",
                publisher="Example Press",
                publication_time=PublicationTime(
                    status=PublicationTimeStatus.KNOWN, value=NOW
                ),
                retrieved_at=NOW,
            ),
        ),
        observations=observations,
        evidence_claims=claims,
        readiness=EvidenceReadiness.READY,
    )


def _interpretation(
    identity: str,
    statement: str,
    *,
    supports: Sequence[str],
    depends_on: Sequence[str] = (),
    admissible: bool = True,
    kind: InterpretationKind = InterpretationKind.CAUSE,
) -> Interpretation:
    return Interpretation(
        interpretation_id=identity,
        version=1,
        statement=statement,
        kind=kind,
        support_refs=tuple(supports),
        depends_on=tuple(depends_on),
        audience_transfer=AudienceTransfer.BOUNDED_EXTERNAL_CASE,
        strength=LADDER.at(2),
        ceiling=LADDER.at(2),
        admissibility=(
            Admissibility.ADMISSIBLE if admissible else Admissibility.INADMISSIBLE
        ),
        rationale=Justification(
            text="The cited claims state it.", refs=tuple(supports[:1])
        ),
        inadmissible_reason=None if admissible else InadmissibleReason.UNSUPPORTED,
        temptation_note=None if admissible else "It reads as the bigger story.",
    )


def _boundary(
    members: Sequence[Interpretation],
    *,
    core_id: str = CORE,
    core_version: int = 1,
    version: int = 1,
) -> InterpretationBoundary:
    """One E-09 snapshot over the two-story core."""

    return InterpretationBoundary(
        boundary_id=boundary_id(core_id),
        version=version,
        core_ref=(core_id, core_version),
        relevance_ref=DecisionRef(
            path="reports/content_packages/signal-302/decision.json",
            digest="sha256:" + "e" * 64,
        ),
        members=tuple(members),
        probes=(
            ProbeApplication(
                record_id="K-TEMPT-01",
                finding=ProbeFinding.NONE_FOUND,
                note="No inflated benefit was proposed.",
            ),
        ),
        outcome=OutcomeRecord(
            outcome=ArpOutcome.RESOLVE,
            state_code=StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION,
            scope=OutcomeScope.SIGNAL,
            scope_key=SIGNAL,
            reason="the boundary admits the readings the evidence supports",
        ),
        reader_connection=ReaderConnection(
            text="Both readings concern a business decision the reader takes.",
            refs=("ev-d-1",),
        ),
    )


def _two_story() -> InterpretationBoundary:
    """§13 D: two independent readings, each on evidence of its own."""

    return _boundary((
        _interpretation(
            COST,
            "The change removed a cost layer, and the saving shows within a quarter.",
            supports=("ev-d-1", "ev-d-3"),
        ),
        _interpretation(
            RISK,
            "The same change moved the business into a regulated activity.",
            supports=("ev-d-2", "ev-d-4"),
            kind=InterpretationKind.CONSEQUENCE_FOR_READER,
        ),
    ))


def _workspace(tmp_path: Path) -> RunWorkspace:
    return RunWorkspace.create(tmp_path / "editorial_runs", create_run_id())


# ===========================================================================
# The two-story signal: the acceptance evidence
# ===========================================================================


def test_a_two_story_signal_sets_split_candidate_and_still_creates_one_unit():
    """AD-03: the rules qualify, the cap holds, and the run records both."""

    unit = create_unit(core=_core(), boundary=_two_story())

    assert unit.split.split_candidate, (
        "two independent readings on separate evidence are exactly the pair "
        "AD-03 rules 1 and 2 qualify"
    )
    assert unit.split.rule_1 is SplitRuleResult.QUALIFIED
    assert unit.split.rule_2 is SplitRuleResult.QUALIFIED
    assert [
        (pair.first, pair.second) for pair in unit.split.qualifying_pairs
    ] == [(COST, RISK)], "the trace names which pair qualified (§1, Trace)"

    # And nothing was split: one unit, active, over the whole admissible set.
    assert isinstance(unit, EditorialUnit)
    assert unit.status is UnitStatus.ACTIVE
    assert unit.interpretation_scope == (COST, RISK)
    assert unit.unit_id == unit_id(CORE)
    assert unit.signal_ids == (SIGNAL,)
    assert unit.core_ref == (CORE, 1)
    assert unit.boundary_ref == (boundary_id(CORE), 1)


def test_the_flag_and_the_rule_results_reach_the_run_trace(tmp_path: Path):
    """§1, Trace: rule results, ``split_candidate``, and the pairs behind it."""

    workspace = _workspace(tmp_path)
    unit = create_unit(core=_core(), boundary=_two_story())
    entry = write_unit(workspace, unit)

    assert entry.path == f"units/{unit.unit_id}/unit.json"
    assert entry.entity_type == "E-10" and entry.writer_stage == STAGE
    written = json.loads(
        (workspace.run_dir / entry.path).read_text(encoding="utf-8")
    )

    assert written["split"]["split_candidate"] is True
    assert written["split"]["cap"] == SPLIT_CAP
    assert written["split"]["rule_1"] == "qualified"
    assert written["split"]["rule_2"] == "qualified"
    assert written["split"]["rule_3"] == "not_evaluated"
    assert written["split"]["pairs"] == [
        {
            "interpretation_refs": [COST, RISK],
            "independent": True,
            "separate_support": True,
            "qualified": True,
        }
    ]
    assert written["status"] == "active"
    assert written["interpretation_scope"] == [COST, RISK]
    assert "expires_at" not in written, (
        "an expiry belongs to a deferred unit; a null one on an active unit is "
        "what a later reader takes for 'this one never expires'"
    )


def test_the_second_story_is_not_created_stored_or_deferred(tmp_path: Path):
    """AD-03: 'no additional unit is created, stored or deferred'."""

    workspace = _workspace(tmp_path)
    unit = create_unit(core=_core(), boundary=_two_story())
    write_unit(workspace, unit)

    units = workspace.run_dir / "units"
    assert [path.name for path in sorted(units.iterdir())] == [unit.unit_id]
    assert [path.name for path in sorted(units.rglob("*.json"))] == ["unit.json"]


def test_rule_3_is_recorded_as_not_evaluated_and_can_be_nothing_else():
    """§1, Decider: it needs anchor calls, and S-05 makes none (Calls: 0)."""

    qualified = create_unit(core=_core(), boundary=_two_story()).split
    empty = SplitRecord()

    assert qualified.rule_3 is SplitRuleResult.NOT_EVALUATED
    assert empty.rule_3 is SplitRuleResult.NOT_EVALUATED
    assert "rule_3" not in SplitRecord.__dataclass_fields__, (
        "a rule nobody evaluated is not a field a caller could fill with a "
        "verdict; S-05 makes no call, so it has none to record"
    )


# ===========================================================================
# Rules 1 and 2, by code
# ===========================================================================


def test_a_reading_that_rests_on_the_other_is_not_independent():
    """Rule 1: 'one is not a premise, consequence or restatement of the other'."""

    unit = create_unit(
        core=_core(),
        boundary=_boundary((
            _interpretation(
                COST, "The change removed a cost layer.", supports=("ev-d-1",)
            ),
            _interpretation(
                RISK,
                "Because the layer went, the activity became a regulated one.",
                supports=("ev-d-2", "ev-d-4"),
                depends_on=(COST,),
            ),
        )),
    )

    assert unit.split.split_candidate is False
    assert unit.split.rule_1 is SplitRuleResult.NOT_QUALIFIED
    assert unit.split.rule_2 is SplitRuleResult.NOT_EVALUATED, (
        "rule 2 is asked about the candidate anchors of an independent pair; "
        "there were none, which is not the same as asking and finding nothing"
    )
    assert unit.split.pairs[0].independent is False
    assert unit.split.pairs[0].separate_support is True, (
        "the pair's supports are recorded whatever rule 1 made of it"
    )


def test_a_premise_of_a_premise_is_still_a_premise():
    """Rule 1 over the chain, not only over the ``depends_on`` list."""

    middle = "int-302-middle"
    unit = create_unit(
        core=_core(),
        boundary=_boundary((
            _interpretation(COST, "The cost layer went.", supports=("ev-d-1",)),
            _interpretation(
                middle,
                "The removal changed what the company does.",
                supports=("ev-d-3",),
                depends_on=(COST,),
            ),
            _interpretation(
                RISK,
                "What it now does needs an authorisation.",
                supports=("ev-d-2", "ev-d-4"),
                depends_on=(middle,),
            ),
        )),
    )

    by_pair = {(pair.first, pair.second): pair for pair in unit.split.pairs}
    assert by_pair[(COST, RISK)].independent is False, (
        "RISK rests on the middle reading, which rests on COST; comparing the "
        "two lists alone would call them independent"
    )
    assert unit.split.split_candidate is False


def test_a_dependency_the_boundary_does_not_list_fails_closed():
    """A premise no reader can resolve is not evidence that two readings stand apart."""

    unit = create_unit(
        core=_core(),
        boundary=_boundary((
            _interpretation(
                COST,
                "The change removed a cost layer.",
                supports=("ev-d-1", "ev-d-3"),
                depends_on=("int-302-not-in-this-boundary",),
            ),
            _interpretation(
                RISK,
                "The activity needs an authorisation.",
                supports=("ev-d-2", "ev-d-4"),
            ),
        )),
    )

    assert unit.split.pairs[0].independent is False
    assert unit.split.split_candidate is False


def test_support_one_reading_shares_with_the_other_is_not_separate_support():
    """Rule 2, both ways round: a subset is not a claim of one's own."""

    unit = create_unit(
        core=_core(),
        boundary=_boundary((
            _interpretation(
                COST,
                "The change removed a cost layer.",
                supports=("ev-d-1", "ev-d-3"),
            ),
            _interpretation(
                RISK,
                "The saving is the whole of what the filing shows.",
                supports=("ev-d-1",),
                kind=InterpretationKind.CONSEQUENCE_FOR_READER,
            ),
        )),
    )

    assert unit.split.rule_1 is SplitRuleResult.QUALIFIED
    assert unit.split.rule_2 is SplitRuleResult.NOT_QUALIFIED
    assert unit.split.split_candidate is False
    assert unit.split.qualifying_pairs == ()


def test_one_admissible_reading_leaves_rule_1_unqualified():
    """Rule 1's first condition: 'at least two admissible interpretations'."""

    unit = create_unit(
        core=_core(),
        boundary=_boundary((
            _interpretation(COST, "The cost layer went.", supports=("ev-d-1",)),
        )),
    )

    assert unit.split.pairs == ()
    assert unit.split.rule_1 is SplitRuleResult.NOT_QUALIFIED
    assert unit.split.rule_2 is SplitRuleResult.NOT_EVALUATED
    assert unit.split.split_candidate is False
    assert unit.interpretation_scope == (COST,)


def test_an_inadmissible_reading_is_neither_scope_nor_a_split_candidate():
    """§1 Post: the scope is the *admissible* set, and only it can split."""

    refused = "int-302-refused"
    unit = create_unit(
        core=_core(),
        boundary=_boundary((
            _interpretation(COST, "The cost layer went.", supports=("ev-d-1",)),
            _interpretation(
                refused,
                "Every business that does this saves 40%.",
                supports=(),
                admissible=False,
                kind=InterpretationKind.GENERALIZATION,
            ),
        )),
    )

    assert unit.interpretation_scope == (COST,)
    assert unit.split.pairs == ()
    assert unit.split.split_candidate is False


# ===========================================================================
# The cap, and the unit that is never deferred
# ===========================================================================


def test_a_cap_other_than_one_is_refused_rather_than_obeyed():
    """AD-03: raising it 'is a configuration change plus an explicit decision'."""

    with pytest.raises(UnitError, match="split cap of 2"):
        create_unit(core=_core(), boundary=_two_story(), cap=2)

    with pytest.raises(UnitError, match="cap 2"):
        SplitRecord(cap=2)


def test_a_deferred_or_expired_unit_cannot_be_constructed():
    """The statuses only a split produces, and nothing writes (Step 3 §3.2)."""

    fields: dict[str, Any] = dict(
        unit_id=unit_id(CORE),
        signal_ids=(SIGNAL,),
        core_ref=(CORE, 1),
        boundary_ref=(boundary_id(CORE), 1),
        interpretation_scope=(COST,),
        split=SplitRecord(),
    )

    for status in (UnitStatus.DEFERRED, UnitStatus.EXPIRED):
        with pytest.raises(UnitError, match=status.value):
            EditorialUnit(**fields, status=status)

    # The statuses a later stage does reach are untouched.
    assert EditorialUnit(**fields, status=UnitStatus.SKIPPED).status is (
        UnitStatus.SKIPPED
    )


def test_no_deferred_unit_writer_is_reachable(tmp_path: Path):
    """Step 3 §3.2: 'No writer is enabled while cap = 1'.

    Three ways round, because absence is what has to be shown: the stage cannot
    reach the ledger the durable record lives in, no unit it could hand a
    writer can carry a deferred status, and a full execution leaves nothing
    outside the run's own 90-day workspace.
    """

    module = _REPO_ROOT / "src" / "editorial_core" / "editorial_units.py"
    imported = {
        node.module
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not [name for name in imported if "ledger" in name], (
        "data/editorial/units/<client>/<unit_id>.json is a ledger path, and "
        "S-05 does not import the ledger"
    )

    runs_root = tmp_path / "editorial_runs"
    workspace = RunWorkspace.create(runs_root, create_run_id())
    write_unit(workspace, create_unit(core=_core(), boundary=_two_story()))

    outside = [
        path
        for path in tmp_path.rglob("*")
        if path != runs_root and runs_root not in path.parents
    ]
    assert outside == [], "S-05 writes into the run workspace and nowhere else"


# ===========================================================================
# Storage
# ===========================================================================


def test_the_unit_path_belongs_to_this_stage_and_is_written_once(tmp_path: Path):
    """§2.3: ``units/*/unit.json`` is S-05's, and P1 writes each path once."""

    workspace = _workspace(tmp_path)
    unit = create_unit(core=_core(), boundary=_two_story())
    relative = unit_relative_path(unit.unit_id)

    assert owner_of(relative) == STAGE
    write_unit(workspace, unit)

    with pytest.raises(ArtifactCollisionError):
        write_unit(workspace, unit)
    with pytest.raises(WriteOwnershipError):
        workspace.write_entity(
            stage="S-06",
            relative_path=relative,
            entity_type="E-10",
            entity_id=unit.unit_id,
            payload=unit.as_entity(),
        )


def test_a_second_execution_over_one_core_names_the_same_unit():
    """One signal is one unit, so a repeat is not a second one."""

    first = create_unit(core=_core(), boundary=_two_story())
    second = create_unit(core=_core(), boundary=_two_story())

    assert first.unit_id == second.unit_id
    assert unit_relative_path(first.unit_id) == f"units/{first.unit_id}/unit.json"


# ===========================================================================
# What the stage refuses to be handed
# ===========================================================================


def test_a_boundary_admitting_nothing_never_becomes_a_unit():
    """§1 Pre: 'boundary has at least one admissible interpretation'."""

    refused = _boundary((
        _interpretation(
            COST,
            "Every business that does this saves 40%.",
            supports=(),
            admissible=False,
            kind=InterpretationKind.GENERALIZATION,
        ),
    ))

    with pytest.raises(UnitError, match="admitting no interpretation"):
        create_unit(core=_core(), boundary=refused)


def test_a_boundary_over_another_core_version_is_refused():
    """A unit states both refs; two that describe different material cannot."""

    with pytest.raises(UnitError, match="core at"):
        create_unit(core=_core(version=2), boundary=_two_story())


def test_a_unit_with_an_empty_scope_is_not_a_unit():
    """§1 Post: the unit's scope is the full admissible set, never nothing."""

    with pytest.raises(UnitError, match="empty interpretation scope"):
        EditorialUnit(
            unit_id=unit_id(CORE),
            signal_ids=(SIGNAL,),
            core_ref=(CORE, 1),
            boundary_ref=(boundary_id(CORE), 1),
            interpretation_scope=(),
            split=SplitRecord(),
        )


def test_a_pair_of_one_reading_with_itself_is_refused():
    """Rule 1 is a test on two readings."""

    with pytest.raises(UnitError, match="paired with itself"):
        InterpretationPair(
            first=COST, second=COST, independent=True, separate_support=True
        )


# ===========================================================================
# The durable ledger (Step 3 §3.3)
# ===========================================================================

_INPUTS = RunInputs.stated_absent("unit fixture: no editorial input")


def _summary(units: Sequence[EditorialUnit]) -> RunSummary:
    context = RunContext(
        run_id=create_run_id(),
        assignment_id=SIGNAL,
        started_at=NOW,
        strategy_ref="never-blank",
        strategy_version="1.0.0",
        execution_mode=ExecutionMode.DRY_RUN,
        schema_version="1.0",
    )
    return RunSummary.for_run(
        run_context=context,
        manifest=RunManifest.for_run(context, inputs=_INPUTS),
        records=(),
        scopes=(RunScope(scope=OutcomeScope.SIGNAL, scope_key=SIGNAL),),
        client="never_blank",
        signal_ids=(SIGNAL,),
        unit_ids=tuple(unit.unit_id for unit in units),
        workspace=WorkspaceRef(
            artifact_name="editorial-run-302",
            retention_days=90,
            expires_on=date(2026, 12, 23),
            manifest_digest="sha256:" + "a" * 64,
        ),
        call_budget_limit=40,
        ledger_commit=LedgerCommitStatus.NOT_ATTEMPTED,
        split_candidate=run_split_candidate(units),
    )


def test_the_flag_reaches_the_summary_that_outlives_the_workspace():
    """§3.3: ``split_candidate`` is what the AD-03 observation is counted from."""

    unit = create_unit(core=_core(), boundary=_two_story())
    summary = _summary((unit,))

    assert summary.split_candidate is True
    reloaded = RunSummary.from_dict(summary.to_dict())
    assert reloaded.split_candidate is True, (
        "the observation has to survive the 90-day workspace to be a rate"
    )


def test_a_run_whose_signal_would_not_have_split_carries_a_false_flag():
    """The flag counts the signals that qualified, and no others."""

    single = _boundary((
        _interpretation(COST, "The cost layer went.", supports=("ev-d-1",)),
    ))
    unit = create_unit(core=_core(), boundary=single)

    assert run_split_candidate((unit,)) is False
    assert run_split_candidate(()) is False
    assert _summary((unit,)).split_candidate is False


def test_the_run_flag_is_true_when_any_unit_of_it_qualified():
    """One summary, one flag, and a run may hold several units (AD-04)."""

    qualified = create_unit(core=_core(), boundary=_two_story())
    other_core = _core(core_id="core-302-other")
    plain = create_unit(
        core=other_core,
        boundary=_boundary(
            (_interpretation(COST, "The cost layer went.", supports=("ev-d-1",)),),
            core_id="core-302-other",
        ),
    )

    assert run_split_candidate((plain, qualified)) is True
    assert run_split_candidate((plain,)) is False


# ===========================================================================
# The vocabulary
# ===========================================================================


def test_the_status_vocabulary_is_the_entity_s():
    """Step 1 §4 lists five statuses; S-05 produces one of them."""

    assert [status.value for status in UnitStatus] == [
        "active",
        "deferred",
        "skipped",
        "completed",
        "expired",
    ]
    assert create_unit(core=_core(), boundary=_two_story()).status is UnitStatus.ACTIVE


def test_an_unsafe_unit_id_never_reaches_a_path():
    """A unit ID becomes a directory name, and traversal is refused there."""

    with pytest.raises(ValueError):
        unit_relative_path("../escape")
