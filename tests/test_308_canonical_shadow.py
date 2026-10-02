"""Issue #308 (NB-07a, SL-7): the canonical shadow run, end to end.

SL-7's two acceptance criteria are about *runs*, so these are about runs: N
consecutive executions of the production entrypoint over real stages, each
sealed and verified, each holding six destination decisions. Everything else
here is the property that makes those runs safe to schedule — that S-14
publishes nothing, and cannot.

Every run below is the production path: ``run_golden_engine`` over
``execute_canonical_topology``, with #351's deterministic doubles in the five
seams production hands in. No stage is replaced, no entity is hand-authored,
and the S-14 under test is the one the engine calls. Nothing reaches a network,
a provider, a credential or a publication.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from src.editorial_core.destinations import Destination, DestinationMode
from src.editorial_core.plan_check import CheckOutcome, Finding
from src.editorial_core.text_check import TextFingerprint, TextResult, TextVerdict
from src.run import golden_engine, shadow_publication
from src.run.call_budget import (
    GOLDEN_ENGINE_MAX_CEILING,
    CallBudgetConfigurationError,
)
from src.run.golden_engine import UNWIRED_STAGES, WIRED_STAGES
from src.run.shadow_publication import (
    CANONICAL_PACKAGERS,
    FINGERPRINT_ENTITY_TYPE,
    PUBLICATION_ENTITY_TYPE,
    WITHHELD_IN_SHADOW_RUN,
    DestinationPublication,
    PackageOutcome,
    PackageState,
    ShadowPublicationError,
    portfolio_text,
    prior_publication,
    publish_in_shadow,
    write_fingerprint_record,
)
from src.run.shadow_run import (
    SHADOW_CEILING_VAR,
    SHADOW_MEASUREMENT_FLOOR,
    configured_shadow_ceiling,
)
from src.run.walking_skeleton import CANONICAL_DESTINATIONS, run_golden_engine
from tests.golden_engine_boundary import NOW, canonical_run

#: How many consecutive shadow runs the acceptance criterion is read over.
#: Three rather than two, because two runs can collide on a shared identity by
#: accident and the third is what shows the identity is per run and not per
#: pair. The signal is **the same** for all three, which is the case that
#: matters: a unit ID is derived from the core, so three runs of one signal are
#: three remembrances of one unit, and they must not overwrite each other.
CONSECUTIVE_RUNS = 3

SHADOW_SIGNAL = "sig-308-shadow"


class Sequence3(NamedTuple):
    """The sequence of sealed runs the acceptance proofs are read over."""

    runs: tuple[Any, ...]
    ledger: Path


def _sealed(root: Path, ledger: Path, *, signal_id: str = SHADOW_SIGNAL):
    """One sealed canonical run through the production entrypoint.

    ``ledger_dir`` is redirected rather than defaulted: ``data/editorial`` is
    tracked, and a test that wrote a real learning record into it would arrive
    in the diff of whatever commit happened to follow (#231, #370).
    """

    run = canonical_run(root, signal_id=signal_id)
    return run_golden_engine(
        seams=run.seams,
        configuration=run.configuration,
        signal=run.signal,
        binding=run.binding,
        runs_root=run.runs_root,
        started_at=run.now,
        now=run.now,
        ledger_dir=ledger,
    )


@pytest.fixture(scope="module")
def consecutive(tmp_path_factory) -> Sequence3:
    """``CONSECUTIVE_RUNS`` sealed canonical runs over the same real signal.

    Module-scoped because every proof below is about this same sequence:
    re-running it per test would make the ledger assertions assertions about
    separate sequences, which is exactly what they are there to rule out.
    Nothing is instrumented here — these are the acceptance runs, and the
    instrument lives in :func:`handed` instead.
    """

    root = tmp_path_factory.mktemp("shadow308")
    ledger = root / "ledger"
    return Sequence3(
        tuple(
            _sealed(root / f"run{index}", ledger)
            for index in range(CONSECUTIVE_RUNS)
        ),
        ledger,
    )


@pytest.fixture(scope="module")
def handed(tmp_path_factory) -> tuple[dict[str, Any], Any]:
    """What the engine handed S-14 on one run, and that run's own result.

    One extra run, instrumented: ``publish_in_shadow`` is wrapped in a
    pass-through that keeps the call's arguments and returns the real answer
    unchanged — the shape ``golden_engine_net._recorder`` uses. The values are
    the run's real typed artifacts, which is what makes the cases below about
    the production stage rather than about hand-authored inputs.
    """

    captured: dict[str, Any] = {}
    real = shadow_publication.publish_in_shadow

    def recording(**kwargs: Any):
        captured.update(kwargs)
        return real(**kwargs)

    root = tmp_path_factory.mktemp("handed308")
    golden_engine.publish_in_shadow = recording  # type: ignore[assignment]
    try:
        run = _sealed(root, root / "ledger", signal_id="sig-308-handed")
    finally:
        golden_engine.publish_in_shadow = real  # type: ignore[assignment]
    assert captured, "the engine called the shadow stage"
    return captured, run


# ===========================================================================
# Acceptance 1 · N consecutive shadow runs complete with verified manifests
# ===========================================================================


def test_three_consecutive_shadow_runs_complete_with_verified_manifests(
    consecutive,
):
    """Acceptance: the runs complete, and each seals a manifest that verifies.

    "Complete" is ``stopped_at is None`` — the run reached the end of the wired
    topology, which since #308 means S-14 — and "verified" is the sealed
    workspace checked against its own manifest: every indexed file present at
    the digest the index records, every stage record accounted for, and nothing
    in the workspace that the index does not hold.

    Reverting S-14 makes this fail at the stage set: a run that ends at S-13
    records no S-14 execution, and ``stopped_at`` would not say so — it names
    the stage that *stopped* a run and is ``None`` for one that ran out of
    wired stages, whichever stage that happened to be.
    """

    runs = consecutive.runs

    assert len(runs) == CONSECUTIVE_RUNS
    for run in runs:
        assert run.execution.stopped_at is None
        assert "S-14" in {record.stage for record in run.records}
        assert run.verification.verified_stage_records == len(run.records)
        assert run.verification.verified_entities == len(run.manifest.entities)
        assert run.summary_path.exists()
    # Three runs, three identities: a sequence whose runs shared a run_id would
    # satisfy every assertion above and be one run counted three times.
    assert len({run.run_context.run_id for run in runs}) == CONSECUTIVE_RUNS


def test_each_run_remembers_its_own_texts_in_the_durable_ledger(consecutive):
    """The fingerprints of consecutive runs of one signal do not collide.

    The ledger is shared by every run and writes each record once (P1), while a
    unit ID is derived from the core — so three runs of one signal name one
    unit. A fingerprint named for the unit would make the second run's write
    collide with the first's, after its workspace was already sealed. Named for
    the run, all eighteen are on the shelf.
    """

    runs, ledger = consecutive.runs, consecutive.ledger
    written = sorted(path.name for path in ledger.rglob("*.json"))
    identities = [
        identity for run in runs for identity in run.execution.fingerprint_ids
    ]

    assert len(identities) == CONSECUTIVE_RUNS * len(CANONICAL_DESTINATIONS)
    assert len(set(identities)) == len(identities)
    for identity in identities:
        assert f"{identity}.json" in written
    # One unit across the three runs, which is what makes the collision real
    # rather than hypothetical.
    assert len({run.execution.unit_ids for run in runs}) == 1


def test_the_summary_lists_the_fingerprints_and_no_publication(consecutive):
    """§3.3's two fields, each saying what this run did and did not do.

    ``fingerprint_ids`` is what S-14 produced; ``publications`` is empty,
    because a publication that never happened must not appear in the ledger as
    one that resolved. A run that listed one would be counted by every
    publication indicator built on this record.
    """

    runs = consecutive.runs

    for run in runs:
        assert run.summary.fingerprint_ids == run.execution.fingerprint_ids
        assert len(run.summary.fingerprint_ids) == len(CANONICAL_DESTINATIONS)
        assert run.summary.publications == ()
        assert run.summary.publication_unconfirmed == ()


# ===========================================================================
# Acceptance 2 · every run contains six destination decisions
# ===========================================================================


def test_every_run_contains_six_destination_decisions(consecutive):
    """Acceptance: six decisions, six fingerprints, in every run.

    Principle B in both halves: S-07 decided about each of the six — the run
    would not have sealed otherwise, ``decided_every_destination`` refuses it —
    and S-14 remembered a text for each, so no destination is carried to the
    end of the run and then quietly dropped before the portfolio sees it.
    """

    runs = consecutive.runs

    for run in runs:
        decided = [
            record for record in run.records if record.stage == "S-07"
        ]
        produced = sum(len(record.outputs) for record in decided)
        assert produced == len(CANONICAL_DESTINATIONS) == 6
        assert {item.destination.value for item in run.execution.fingerprints} == set(
            CANONICAL_DESTINATIONS
        )
        assert {
            item.destination.value for item in run.execution.publications
        } == set(CANONICAL_DESTINATIONS)


def test_s14_runs_once_per_destination_and_makes_no_model_call(consecutive):
    """§3's Decider is ``code`` and its Calls column is 0.

    One execution per destination, each recording the fingerprint and the
    publication record it wrote, and none of them charging the budget: a
    measurement whose last stage cost model calls would be measuring something
    the contract says does not exist.
    """

    runs = consecutive.runs

    for run in runs:
        records = [record for record in run.records if record.stage == "S-14"]
        assert len(records) == len(CANONICAL_DESTINATIONS)
        for record in records:
            assert record.calls["count"] == 0
            assert record.created_by.decider.value == "code"
            assert record.created_by.request_digest is None
            assert {ref.entity_type for ref in record.outputs} == {
                FINGERPRINT_ENTITY_TYPE,
                PUBLICATION_ENTITY_TYPE,
            }


def test_the_wired_topology_now_ends_at_s14(consecutive):
    """S-14 is wired and S-15 is the one stage that is not.

    Asserted against the engine's own declaration rather than against a list
    here, so that a stage dropped back out of the wiring fails this rather than
    being noticed in a trace somebody happens to read.
    """

    assert "S-14" in WIRED_STAGES
    assert UNWIRED_STAGES == ("S-15",)
    runs = consecutive.runs
    assert {record.stage for record in runs[0].records} == set(WIRED_STAGES)


# ===========================================================================
# No publish call, and no way to make one
# ===========================================================================


#: The shadow stage, read as text. What is asserted about it is what it can
#: reach: a module that can reach a publisher has one whether it calls it today
#: or not, and that is the property a run of it cannot establish.
_SHADOW_SOURCE = Path(shadow_publication.__file__).read_text(encoding="utf-8")

#: The imports that would put a platform, or the authority that arbitrates
#: real publications, within this stage's reach. Import-shaped rather than bare
#: names, for the reason ``test_351`` tests for ``golden_engine_transports(``
#: and not for the bare name: the module docstring is where a reader is sent to
#: find out what it deliberately does not import, and naming it there is the
#: documentation rather than the breach.
_UNREACHABLE = (
    "from src.publishing.publication_markers",
    "from src.publishing.idempotency",
    "from src.publishing.wix",
    "from src.publishing.linkedin",
    "from src.publishing.facebook",
    "from src.publishing.instagram",
    "from src.publishing.threads",
    "from src.publishing.telegram",
    "record_intent(",
    "PublishResult",
)


@pytest.mark.parametrize("forbidden", _UNREACHABLE)
def test_the_shadow_stage_cannot_reach_a_publisher_or_the_marker_store(
    forbidden: str,
):
    """"No external publish call" as a property of the module, not of a run.

    A run proves it for that run; this proves it for every run. The shadow
    stage imports no publisher and no idempotency authority, so there is
    nothing for a later edit to reach by accident — and an edit that added one
    would fail here rather than in a workflow that had already published.
    """

    assert forbidden not in _SHADOW_SOURCE


def test_the_detector_sees_an_import_it_is_given():
    """The test above cannot pass by reading a file that has no imports at all.

    The one failure mode of a source-text assertion: a path that moved, a read
    that returned nothing, a module that was renamed. Asserting what the source
    *does* contain is what rules all three out.
    """

    assert "from src.editorial_core.destinations import" in _SHADOW_SOURCE
    assert len(_SHADOW_SOURCE) > 1000


def test_every_publication_record_says_it_published_nothing_and_why(
    consecutive,
):
    """``published`` and ``withheld`` are two facts, and both are recorded.

    A destination whose publication failed and one whose run never publishes
    are the same ``False``. The reason is what separates them, and it is a
    closed token rather than a sentence because it reaches persisted evidence.
    """

    runs = consecutive.runs

    for run in runs:
        for record in run.execution.publications:
            assert record.published is False
            assert record.withheld == WITHHELD_IN_SHADOW_RUN
            assert record.preflight is None
            assert record.mode in set(DestinationMode)


def test_a_publication_record_cannot_be_constructed_as_published():
    """The shape refuses the claim, so no caller can make it.

    Not a flag this stage sets to ``False``: a record that said it published
    would be describing a run that did not happen, and the type is where that
    is refused rather than in the one caller that happens to check.
    """

    with pytest.raises(ShadowPublicationError, match="published"):
        DestinationPublication(
            unit_id="unit-308",
            destination=Destination.WIX,
            mode=DestinationMode.PUBLISH,
            text_ref=("txt-308", 1),
            verdict_ref="tv-txt-308-v1",
            fingerprint_id="fp-308-wix",
            package=PackageOutcome(
                state=PackageState.BUILDER_NOT_AVAILABLE, expected_from="SL-9"
            ),
            published=True,
        )


def test_the_sealed_workspace_holds_no_publication_marker(consecutive):
    """Nothing the run wrote claims a platform saw it.

    Read off the files rather than off the objects: the workspace is what a
    reader of a shadow run opens, and a marker-shaped file in it would be read
    as a publication whatever the record beside it said.
    """

    runs = consecutive.runs
    run = runs[0]

    for path in run.run_dir.rglob("publication.json"):
        body = json.loads(path.read_text(encoding="utf-8"))
        assert body["published"] is False
        assert body["withheld"] == WITHHELD_IN_SHADOW_RUN
    assert not list(run.run_dir.rglob("*.intent.json"))
    assert not list(run.run_dir.rglob("*marker*"))


# ===========================================================================
# Packages where they exist
# ===========================================================================


def test_every_destination_is_packaged_or_records_why_it_is_not(consecutive):
    """"Packages where they exist", with the absence recorded per destination.

    Read against the registry rather than against today's contents of it: the
    expectation per destination is "built if a packager is registered for it,
    and the recorded absence otherwise", so the slice that registers one
    (SL-9 for Wix and LinkedIn, SL-8 for the other four) makes this follow
    instead of making it fail. What the rule rules out is the third state —
    a destination with no package and no record of why, which is
    indistinguishable from one whose package was built and discarded.
    """

    runs = consecutive.runs

    for run in runs:
        for record in run.execution.publications:
            if record.destination in CANONICAL_PACKAGERS:
                assert record.package.state is PackageState.BUILT
                assert record.package.digest
                continue
            assert record.package.state is PackageState.BUILDER_NOT_AVAILABLE
            assert record.package.digest is None
            assert record.package.expected_from
            assert record.package.expected_from.startswith("SL-")


def test_a_destination_with_a_packager_records_its_digest(handed):
    """The loop packages whatever it is offered, which is what SL-9 will add.

    Offered one packager for one destination, over the real accepted texts of a
    real run: that destination's record carries ``built`` and the digest, and
    the other five still carry the recorded absence. So SL-9 adds a row to the
    registry and changes no logic here — the shape #231 left ``_PUBLISHERS``
    empty for.
    """

    captured, _ = handed

    class _Packager:
        def package_digest(self, *, text: Any, plan: Any) -> str:
            return f"sha256:{text.text_id}"

    packaged = publish_in_shadow(
        **{**captured, "packagers": {Destination.WIX: _Packager()}}
    )
    by_destination = {
        record.destination: record.package for record in packaged.records
    }

    assert by_destination[Destination.WIX].state is PackageState.BUILT
    assert by_destination[Destination.WIX].digest
    assert by_destination[Destination.WIX].expected_from is None
    for destination, package in by_destination.items():
        if destination is Destination.WIX:
            continue
        assert package.state is PackageState.BUILDER_NOT_AVAILABLE


def test_a_package_outcome_cannot_claim_a_state_its_digest_contradicts():
    """"No builder" and "an empty package" are different facts.

    Both directions, because either alone leaves the other readable as its
    opposite: a built package without a digest records nothing, and an absent
    builder with one records a package nobody made.
    """

    with pytest.raises(ShadowPublicationError, match="digest"):
        PackageOutcome(state=PackageState.BUILT)
    with pytest.raises(ShadowPublicationError, match="digest"):
        PackageOutcome(
            state=PackageState.BUILDER_NOT_AVAILABLE, digest="sha256:x"
        )


# ===========================================================================
# What a later run may read these fingerprints as
# ===========================================================================


def test_a_shadow_fingerprint_is_portfolio_pressure_and_not_a_publication(
    consecutive,
):
    """V-S05 counts it; V-T05 does not.

    The two narrow views are two questions. V-S05 asks how close a text is to
    the portfolio and counts generated texts too; V-T05 asks whether this text
    has already been published here, and a shadow run's answer is no. A single
    projection serving both would make a later run refuse a text as a
    republication of something nobody can open.
    """

    runs = consecutive.runs

    for fingerprint in runs[0].execution.fingerprints:
        assert fingerprint.published is False
        assert prior_publication(fingerprint) is None
        portfolio = portfolio_text(fingerprint)
        assert isinstance(portfolio, TextFingerprint)
        assert portfolio.fingerprint_id == fingerprint.fingerprint_id
        assert portfolio.destination is fingerprint.destination
        # The run copy carries what V-S05 compares: a projection that answered
        # `None` for every dimension would be a fingerprint nothing can use.
        assert portfolio.reader_path
        assert portfolio.shingles


def test_the_mode_is_s07s_and_says_nothing_about_what_happened(consecutive):
    """``mode`` is carried from E-12, and it is never read as an outcome.

    Two halves. It is **carried**: every fingerprint's mode is the one S-07
    wrote into that destination's ``decision.json``, read back off the sealed
    workspace rather than off the object beside it, so a stage that decided a
    mode of its own would fail here. And it is **not an outcome**: whichever
    mode a destination was given, nothing published it — a reader that took a
    ``publish`` mode for a publication would count every shadow run as one.
    """

    runs = consecutive.runs
    run = runs[0]
    unit = run.execution.unit_ids[0]

    for fingerprint in run.execution.fingerprints:
        decision = json.loads(
            (
                run.run_dir
                / "units"
                / unit
                / "destinations"
                / fingerprint.destination.value
                / "decision.json"
            ).read_text(encoding="utf-8")
        )
        assert fingerprint.mode.value == decision["mode"]
        assert fingerprint.published is False
        assert prior_publication(fingerprint) is None


# ===========================================================================
# The durable copy carries no text (§3.4, §6)
# ===========================================================================


def test_the_ledger_copy_of_an_unpublished_fingerprint_carries_no_text(
    consecutive,
):
    """§6: unpublished bodies and source excerpts stay out of the public tier.

    The workspace copy is the 90-day Actions artifact and carries the opening,
    the ending and the n-grams V-S05 compares; the ledger copy is committed to
    a public repository and carries the measurements, the content digest and no
    text at all.
    """

    runs, ledger = consecutive.runs, consecutive.ledger
    fingerprint = runs[0].execution.fingerprints[0]
    workspace_copy = fingerprint.as_entity()
    ledger_copy = fingerprint.as_ledger_record()

    assert workspace_copy["text_profile"]["shingles"]
    assert workspace_copy["text_profile"]["opening"]
    for field in ("opening", "ending", "shingles", "body"):
        assert field not in ledger_copy["text_profile"]
        assert field not in ledger_copy
    assert ledger_copy["content_digest"] == fingerprint.content_digest

    path = ledger / fingerprint.relative_path(NOW)
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == ledger_copy


def test_a_ledger_record_that_carried_text_is_refused_rather_than_written(
    tmp_path, monkeypatch, consecutive
):
    """The one writer into tier 2 is where the public-repository rule holds.

    Not a convention the serializer is trusted to keep: a serializer that grew
    a text-bearing field would otherwise commit an unpublished body to a public
    repository, and nothing downstream would notice. The check is over the
    payload actually about to be written, nested keys included.
    """

    runs = consecutive.runs
    fingerprint = runs[0].execution.fingerprints[0]

    def leaking(self: Any) -> dict[str, Any]:
        return {"fingerprint_id": self.fingerprint_id, "body": "the prose"}

    monkeypatch.setattr(
        type(fingerprint), "as_ledger_record", leaking, raising=True
    )

    with pytest.raises(ShadowPublicationError, match="public repository"):
        write_fingerprint_record(fingerprint, started_at=NOW, root=tmp_path)

    assert not list(tmp_path.rglob("*.json"))


# ===========================================================================
# Only an accepted text reaches S-14
# ===========================================================================


def test_s14_refuses_a_text_its_verdict_does_not_judge(handed):
    """§2.5 gives one verdict per text version, and S-14 reads the pair.

    A verdict on another version is the fail-closed case that matters: it is a
    verdict that passed, about prose nobody checked, and a fingerprint of it
    would enter the portfolio as a text that held.
    """

    captured, _ = handed
    item = captured["accepted"][0]
    text_id, version = item.verdict.text_ref
    mismatched = replace(
        item, verdict=replace(item.verdict, text_ref=(text_id, version + 1))
    )

    with pytest.raises(ShadowPublicationError, match="one verdict per text"):
        publish_in_shadow(
            run_id=captured["run_id"],
            client=captured["client"],
            unit_id=captured["unit_id"],
            accepted=(mismatched,),
        )


def test_s14_refuses_a_text_the_checks_sent_back(handed):
    """§3: "only accepted texts reach S-14", and this is where that holds.

    Remembering a text S-13 routed back would put it in the portfolio as a
    text that held, and every later V-T05 and V-S05 comparison would be made
    against prose no check approved.
    """

    captured, _ = handed
    item = captured["accepted"][0]
    sent_back = replace(item, verdict=_rejected(item.verdict))

    with pytest.raises(ShadowPublicationError, match="only an accepted text"):
        publish_in_shadow(
            run_id=captured["run_id"],
            client=captured["client"],
            unit_id=captured["unit_id"],
            accepted=(sent_back,),
        )


#: The finding the routed check carries. A failing check must carry one:
#: ``CheckResult`` refuses a non-passing result with no finding, because "a
#: failure and a question nobody answered are both things a reader has to be
#: told the shape of". So the detail is a real one rather than a placeholder.
_FINDING = "the closing sentence states the point the piece withheld"


def _rejected(verdict: TextVerdict) -> TextVerdict:
    """The run's own verdict, as the object a routed text carries.

    Derived from the real one rather than authored, and routed the way S-13
    routes: ``TextVerdict`` refuses a rejected verdict with every check passing
    and ``CheckResult`` refuses a failing check with no finding, so the finding
    is put where S-13 would have put it — on a check — and the result follows
    it. Both constructors therefore have to admit this object, which is what
    makes it the production type in a state the production S-13 produces rather
    than a shape assembled to trip the stage.
    """

    first, rest = verdict.checks[0], verdict.checks[1:]
    return replace(
        verdict,
        checks=(
            replace(
                first,
                result=CheckOutcome.FAIL,
                findings=(Finding(detail=_FINDING),),
            ),
            *rest,
        ),
        result=TextResult.EDIT,
    )


def test_s14_refuses_a_text_from_another_unit(handed):
    """A fingerprint names what it remembers.

    The engine writes ``publication.json`` under **this** unit's destination
    path, so a record about another unit would be a file whose path and
    contents disagree — and the workspace verification cannot see that, because
    digests and write ownership are both satisfied by a record that is
    internally consistent and about something else.
    """

    captured, _ = handed
    item = captured["accepted"][0]

    with pytest.raises(ShadowPublicationError, match="fingerprint names what"):
        publish_in_shadow(
            run_id=captured["run_id"],
            client=captured["client"],
            unit_id="unit-core-some-other-signal",
            accepted=(item,),
        )


# ===========================================================================
# The measurement ceiling, at both ends
# ===========================================================================


def test_the_shadow_ceiling_defaults_to_the_canonical_maximum(monkeypatch):
    """Unset, and empty, both mean "not configured".

    Empty because GitHub Actions renders an unconfigured variable as an empty
    string in ``env:`` (#173): refusing one would make a scheduled run fail for
    a value nobody set. The default is the maximum, which is a runaway guard
    and never a target spend.
    """

    monkeypatch.delenv(SHADOW_CEILING_VAR, raising=False)
    assert configured_shadow_ceiling() == GOLDEN_ENGINE_MAX_CEILING

    monkeypatch.setenv(SHADOW_CEILING_VAR, "")
    assert configured_shadow_ceiling() == GOLDEN_ENGINE_MAX_CEILING
    monkeypatch.setenv(SHADOW_CEILING_VAR, "   ")
    assert configured_shadow_ceiling() == GOLDEN_ENGINE_MAX_CEILING


@pytest.mark.parametrize(
    "value",
    [
        str(SHADOW_MEASUREMENT_FLOOR - 1),
        str(GOLDEN_ENGINE_MAX_CEILING + 1),
        "0",
        "-1",
        "50.0",
        "050",
        "+50",
        " 50",
        "fifty",
    ],
)
def test_the_shadow_ceiling_is_refused_outside_its_two_ends(
    monkeypatch, value: str
):
    """Both ends are checked, and neither is clamped.

    The maximum is the canonical path's own, and the floor is what a clean
    six-destination run costs: a ceiling below it stops the run partway and
    what the baseline would then record is the cost of the stop. SL-7 asks for
    a ceiling "set high enough not to truncate the measurement", and this is
    where that is enforced rather than hoped for.
    """

    monkeypatch.setenv(SHADOW_CEILING_VAR, value)

    with pytest.raises(CallBudgetConfigurationError, match="must be a canonical"):
        configured_shadow_ceiling()


@pytest.mark.parametrize(
    "value", [SHADOW_MEASUREMENT_FLOOR, GOLDEN_ENGINE_MAX_CEILING]
)
def test_the_shadow_ceiling_accepts_both_of_its_own_ends(monkeypatch, value):
    """A range that refused its own endpoints would be a narrower range."""

    monkeypatch.setenv(SHADOW_CEILING_VAR, str(value))

    assert configured_shadow_ceiling() == value


def test_the_measurement_floor_is_what_a_clean_run_actually_costs(consecutive):
    """The floor is measured, not chosen.

    #351 established a clean six-destination run at 50 logical calls, and the
    runs above are that run. If the engine's cost changes, this fails and the
    floor is re-derived — rather than a constant drifting away from the thing
    it is a floor on.
    """

    runs = consecutive.runs

    for run in runs:
        assert run.summary.calls_total == SHADOW_MEASUREMENT_FLOOR
        assert run.summary.call_budget_limit == GOLDEN_ENGINE_MAX_CEILING
    assert SHADOW_MEASUREMENT_FLOOR <= GOLDEN_ENGINE_MAX_CEILING
