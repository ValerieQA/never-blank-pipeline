"""Issue #308: S-14 in shadow — fingerprints for all six, and nothing published.

The slice that runs the whole canonical chain to measure what it costs. So the
two things these tests are about are what S-14 *produced* and what it did
**not** reach: the fingerprint of every accepted text, and no provider, no image
pipeline and no marker store.

The package states are the sharp part. ``PO-DECISION-V1`` (2026-10-02) requires
three of them to be distinguishable — built, required input unavailable, and no
package type yet — and requires exactly one refusal to be absorbed as the
expected shadow state: the visual passport this run does not have because it
does not call the image pipeline. Every other refusal of the real builder stays
a real failure, and the tests below plant each kind.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

import pytest
import yaml

from src.editorial_core.destinations import Destination, DestinationMode
from src.editorial_core.publication import (
    NO_VISUAL_PASSPORT,
    NO_VS02_PRODUCER,
    PACKAGED_DESTINATIONS,
    DistributionMetric,
    PackageInputs,
    PackageState,
    PublicationError,
    ScalarMetric,
    _absorbed,
    _packaged,
    fingerprint_ledger_path,
)
from src.publishing.package import (
    PackageFailureCategory,
    PublicationPackageError,
    WixPublicationTarget,
)
from src.editorial_core.publication import FINGERPRINTS_DIRECTORY
from src.run.ledger import (
    LedgerCommitFailure,
    LedgerCommitReport,
    LedgerCommitStatus,
)
from src.run.walking_skeleton import run_golden_engine, run_walking_skeleton
from src.visual.contract import build_visual_assets_record
from tests.golden_engine_boundary import canonical_run, execute
from tests.test_visual_contract import DESIGN, _pimgs

#: The article body the passport is built over. Taken from the visual
#: contract's own harness so the passport is a real one, not a near-miss.
from tests.test_visual_contract import ARTICLE  # noqa: E402


@pytest.fixture(scope="module")
def shadow(tmp_path_factory):
    """One clean canonical run, all the way through S-14."""

    run = canonical_run(tmp_path_factory.mktemp("shadow"))
    execution, workspace, budget = execute(run)
    return run, execution, workspace, budget


# ===========================================================================
# S-14 ran, cost nothing, and fingerprinted everything it accepted
# ===========================================================================


def test_the_run_reaches_s14_and_fingerprints_all_six(shadow):
    """SL-7's own acceptance: the whole chain, every destination, no publish."""

    _, execution, _, _ = shadow

    assert "S-14" in {record.stage for record in execution.records}
    assert len(execution.fingerprints) == 6
    assert {item.destination for item in execution.fingerprints} == set(Destination)
    assert len(set(execution.accepted)) == 6
    assert execution.stopped_at is None


def test_s14_costs_no_model_call(shadow):
    """§1's Calls column is 0, and the stage takes no transport to make one."""

    _, execution, _, budget = shadow
    recorded = sum(record.calls["count"] for record in execution.records)
    s14 = [record for record in execution.records if record.stage == "S-14"]

    assert len(s14) == 1
    assert s14[0].calls["count"] == 0
    # The clean canonical run cost 50 before S-14 was wired, and costs 50 now.
    assert recorded == 50
    assert budget.used == recorded


def test_no_fingerprint_claims_a_publication(shadow):
    """``publication`` is "if published", and a shadow run published nothing."""

    _, execution, _, _ = shadow

    for item in execution.fingerprints:
        assert item.publication is None
        # AD-07: labels are post-decision and never routed to S-00…S-13.
        assert item.label_ref is None
        assert item.mode in (DestinationMode.PUBLISH, DestinationMode.GENERATE_ONLY)


def test_every_fingerprint_is_written_to_the_run_and_to_the_ledger(shadow):
    """§2.2 keeps a run copy; §3.2 keeps the durable one, indefinitely."""

    run, execution, workspace, _ = shadow

    for item in execution.fingerprints:
        in_run = workspace.run_dir / "fingerprints" / f"{item.fingerprint_id}.json"
        assert in_run.exists(), item.fingerprint_id
        entity = json.loads(in_run.read_text(encoding="utf-8"))
        assert entity["fingerprint_id"] == item.fingerprint_id
        assert entity["content_digest"].startswith("sha256:")
    month = f"{run.run_context.started_at.year:04d}-{run.run_context.started_at.month:02d}"
    durable = fingerprint_ledger_path(execution.fingerprints[0], month=month)
    assert durable.startswith("fingerprints/")
    assert durable.endswith(".json")


def test_no_publisher_image_pipeline_or_marker_is_reachable_from_s14():
    """Not behind a flag: the module names none of them.

    A shadow mode that depended on a flag could be switched on by a later edit.
    What makes "no publish call" checkable is that there is no such call to
    switch — so this reads the stage's own source.
    """

    source = Path("src/editorial_core/publication.py").read_text(encoding="utf-8")

    for forbidden in (
        "publish(",
        "WixPublisher",
        "LinkedInPublisher",
        "PublicationGuard",
        "record_intent",
        "record_marker",
        "generate_image",
        "image_pipeline",
        "build_visual_assets_record",
    ):
        assert forbidden not in source, forbidden


# ===========================================================================
# text_profile — measured where it can be, explicitly absent where it cannot
# ===========================================================================


def test_the_profile_measures_what_this_main_can_measure(shadow):
    """The three the entity names, from counting and from E-13's own refs."""

    _, execution, _, _ = shadow
    profile = execution.fingerprints[0].text_profile

    assert profile.paragraph_lengths.measured
    assert profile.sentence_lengths.measured
    assert profile.paragraph_lengths.values, "the accepted text has paragraphs"
    assert profile.first_evidence_position.measured
    assert 0.0 <= (profile.first_evidence_position.value or 0) <= 1.0


def test_the_vs02_metric_with_no_producer_is_absent_and_says_why(shadow):
    """`PO-DECISION-V1`: explicitly absent, never a zero nobody measured."""

    _, execution, _, _ = shadow
    profile = execution.fingerprints[0].text_profile

    assert len(profile.unmeasured) == 1
    (metric,) = profile.unmeasured
    assert metric.name == "abstraction_before_first_evidence"
    assert not metric.measured
    assert metric.absent_reason == NO_VS02_PRODUCER
    assert "no producer on main" in metric.absent_reason


def test_the_serialized_profile_keeps_a_measured_zero_apart_from_no_producer():
    """The schema requirement the owner set, asserted on the serialized form.

    Three different facts, three different shapes. A reader a year from now has
    the JSON and no objects, so this is the only place the distinction can live.
    """

    measured_zero = ScalarMetric(name="m", value=0.0).as_entity()
    measured_empty = DistributionMetric(name="d", values=()).as_entity()
    not_measured = ScalarMetric(name="m", absent_reason="no producer").as_entity()

    assert measured_zero == {"name": "m", "value": 0.0, "absent_reason": None}
    assert measured_empty["values"] == [] and measured_empty["absent_reason"] is None
    assert not_measured["value"] is None
    assert not_measured["absent_reason"] == "no producer"
    # And the three are mutually distinguishable without reading the name.
    assert measured_zero != not_measured
    assert measured_empty["values"] is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "m"},
        {"name": "m", "value": 1.0, "absent_reason": "both"},
    ],
)
def test_a_metric_that_is_neither_or_both_is_refused(kwargs):
    """A metric says one thing. Neither, or both, is unreadable either way."""

    with pytest.raises(PublicationError):
        ScalarMetric(**kwargs)


# ===========================================================================
# The three package states (owner decision, 2026-10-02)
# ===========================================================================


def test_the_four_destinations_with_no_package_type_are_recorded_distinctly(shadow):
    """Not the same state as Wix/LinkedIn missing an input, and not silence."""

    _, execution, _, _ = shadow
    states = {
        record.destination: record.state for record in execution.packages
    }

    assert len(execution.packages) == 6
    for destination in Destination:
        if destination in PACKAGED_DESTINATIONS:
            assert states[destination] is PackageState.REQUIRED_INPUT_UNAVAILABLE
        else:
            assert states[destination] is PackageState.NO_PACKAGE_TYPE
    # The two states carry different reasons, and neither is the other's.
    for record in execution.packages:
        if record.state is PackageState.NO_PACKAGE_TYPE:
            assert "no canonical publication package exists" in (record.reason or "")
            assert "visual passport" not in (record.reason or "")
        else:
            assert "cannot supply" in (record.reason or "")
            assert record.digest is None


def test_a_canonical_shadow_run_names_every_input_it_cannot_supply(shadow):
    """The reason is structured enough to act on, not "unavailable"."""

    _, execution, _, _ = shadow
    wix = next(
        record
        for record in execution.packages
        if record.destination is Destination.WIX
    )

    for named in ("run_id", "signal_id", "generated", "wix target"):
        assert named in (wix.reason or ""), named
    assert "could not be attempted" in (wix.reason or ""), (
        "a canonical run cannot even call the builder, and says which inputs "
        "are why"
    )


def test_the_package_build_is_actually_attempted(tmp_path):
    """Given everything but the passport, the real builder is called.

    The attempt is what distinguishes this from skipping packaging: the refusal
    in the record is the production builder's own, quoted, and it is reached
    only by calling it.
    """

    inputs = PackageInputs(
        run_id="run-308",
        signal_id="sig-308",
        configuration_identity=object(),
        generated={"headline": "h"},
        visual_record=None,
        wix_target=WixPublicationTarget(site_id="site-1", owner_member_id="owner-1"),
    )

    record = _packaged(Destination.WIX, inputs)

    assert record.state is PackageState.REQUIRED_INPUT_UNAVAILABLE
    assert NO_VISUAL_PASSPORT in (record.reason or "")
    assert "the builder refused:" in (record.reason or ""), (
        "the real builder was called and its own refusal is recorded"
    )
    assert "visual passport" in (record.reason or "")


def test_a_failure_that_is_not_the_missing_passport_is_not_swallowed(tmp_path):
    """The fail-closed boundary, against the real builder.

    A passport is supplied, so the gate this slice trips is not reachable — and
    the generated artifact is missing what the next gate reads. That refusal is
    a real failure of a run that had everything it needed, and it must come out
    as an exception rather than as an expected absence.
    """

    passport = build_visual_assets_record(
        _pimgs(tmp_path),
        run_id="run-308",
        signal_id="sig-308",
        article_body=ARTICLE,
        design_version=DESIGN,
    )
    inputs = PackageInputs(
        run_id="run-308",
        signal_id="sig-308",
        configuration_identity=object(),
        generated={},  # no headline: a later gate, not the passport gate
        visual_record=passport,
        wix_target=WixPublicationTarget(site_id="site-1", owner_member_id="owner-1"),
    )

    with pytest.raises(PublicationPackageError):
        _packaged(Destination.WIX, inputs)


@pytest.mark.parametrize(
    "category",
    [
        PackageFailureCategory.LINEAGE,
        PackageFailureCategory.CONFIGURATION,
        PackageFailureCategory.CHANNEL_PACKAGE,
        PackageFailureCategory.TARGET,
    ],
)
def test_only_a_provenance_refusal_without_a_passport_is_absorbed(category):
    """The discriminator is two facts, and the category alone is not enough.

    A generated artifact missing its headline raises ``PROVENANCE`` too, so the
    category cannot carry the decision by itself. What carries it is that this
    stage passed no passport — and then only the gate that asks for one can have
    fired, because it is the builder's first statement.
    """

    refusal = PublicationPackageError("boom", category)

    assert _absorbed(refusal, visual_record=None) is None
    assert _absorbed(refusal, visual_record=object()) is None
    provenance = PublicationPackageError(
        "the required Wix visual passport is missing",
        PackageFailureCategory.PROVENANCE,
    )
    assert _absorbed(provenance, visual_record=None) is not None
    assert _absorbed(provenance, visual_record=object()) is None, (
        "a passport was supplied, so this is somebody else's provenance failure"
    )


# ===========================================================================
# The durable records are committed by the canonical mechanism, by path
# ===========================================================================
#
# What these six tests are about: S-14 writes six durable E-16 records, and the
# RunSummary *states* the status of the commit that holds them (Step 3 §3.3).
# For that statement to mean anything, the learning commit has to be over those
# exact files. It used to be over `paths=()` while a workflow step staged the
# whole `data/editorial` directory — so the summary reported the status of an
# empty commit, and the files reached the repository by a mechanism the summary
# knew nothing about and could not report on.


def _spy(monkeypatch, report: LedgerCommitReport):
    """Record every ledger commit the run asks for, and answer with `report`.

    A spy rather than a real repository: these tests are about *which paths are
    handed to the commit step*, which is the fact the summary's status is a
    statement about. `test_the_learning_commit_stages_only_the_records_this_run_wrote`
    below does the same thing against a real git repository, so the pathspec is
    proven twice — once as an argument and once as a tree.
    """

    calls: list[tuple[str, tuple[Path, ...]]] = []

    def record(*, paths, message, repo_root, attempts, retry_seconds):
        calls.append((message, tuple(paths)))
        return report

    monkeypatch.setattr("src.run.walking_skeleton.commit_ledger", record)
    return calls


def _sealed(
    tmp_path,
    *,
    commit: bool,
    ledger_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
):
    """One complete six-destination canonical run, sealed through `_write_ledger`."""

    run = canonical_run(tmp_path)
    return run_golden_engine(
        seams=run.seams,
        configuration=run.configuration,
        signal=run.signal,
        binding=run.binding,
        runs_root=run.runs_root,
        ledger_dir=ledger_dir if ledger_dir is not None else run.runs_root.parent / "ledger",
        started_at=run.now,
        now=run.now,
        commit=commit,
        repo_root=repo_root if repo_root is not None else tmp_path,
    )


def test_the_learning_commit_is_handed_the_six_durable_fingerprint_paths(
    tmp_path, monkeypatch
):
    """Six accepted destinations, six E-16 records, six paths — and no glob.

    The run's own report of what it wrote (`fingerprint_ids`) and the paths it
    hands to the commit step are the same six records seen two ways, so a
    summary that names six fingerprints cannot be sitting on a commit of none.
    """

    calls = _spy(monkeypatch, LedgerCommitReport(status=LedgerCommitStatus.COMMITTED))
    ledger = tmp_path / "named-ledger"
    sealed = _sealed(tmp_path, commit=True, ledger_dir=ledger)

    assert len(set(sealed.execution.accepted)) == 6
    assert len(calls) == 2, "one learning commit, then one for the summary"

    learning_message, learning_paths = calls[0]
    assert len(learning_paths) == 6
    assert learning_paths == sealed.execution.fingerprint_paths
    assert "6 learning record(s)" in learning_message
    # Every path is a durable E-16 record that is really there, and the set of
    # them is exactly the set of fingerprints the summary names.
    assert all(path.exists() for path in learning_paths)
    assert {path.stem for path in learning_paths} == set(sealed.summary.fingerprint_ids)
    assert {path.parent.parent.parent.name for path in learning_paths} == {
        FINGERPRINTS_DIRECTORY
    }
    # Under the ledger the caller named, like the summary beside them. S-14 used
    # to write to this process's default root while the summary went to the
    # named one, which put one run's records in two places and left the commit
    # able to reach only one of them.
    for path in (*learning_paths, sealed.summary_path):
        assert ledger in path.parents

    # The summary's own commit is the second step and is over the summary alone:
    # it states the first step's status, so it cannot be in the same commit.
    _, summary_paths = calls[1]
    assert summary_paths == (sealed.summary_path,)


def test_a_committed_learning_record_set_is_reported_as_committed(
    tmp_path, monkeypatch
):
    """The status of *those* records reaches `RunSummary.ledger_commit`."""

    _spy(monkeypatch, LedgerCommitReport(status=LedgerCommitStatus.COMMITTED, attempts=1))
    sealed = _sealed(tmp_path, commit=True)

    assert sealed.summary.ledger_commit is LedgerCommitStatus.COMMITTED
    assert sealed.records_commit.status is LedgerCommitStatus.COMMITTED
    assert len(sealed.summary.fingerprint_ids) == 6


def test_a_failed_learning_commit_is_reported_and_the_records_stay_on_disk(
    tmp_path, monkeypatch
):
    """§3.1: a lost learning record is a recorded fact, not a run failure.

    The run does not raise, the summary says `failed`, and the six records are
    still where S-14 put them — which is the whole reason the status is worth
    recording. A `committed` here would be the dangerous value: nobody would go
    looking for files the ledger says it already has.
    """

    _spy(
        monkeypatch,
        LedgerCommitReport(
            status=LedgerCommitStatus.FAILED,
            attempts=3,
            failure=LedgerCommitFailure.PUSH_FAILED,
        ),
    )
    sealed = _sealed(tmp_path, commit=True)

    assert sealed.summary.ledger_commit is LedgerCommitStatus.FAILED
    assert sealed.records_commit.failure is LedgerCommitFailure.PUSH_FAILED
    assert len(sealed.execution.fingerprint_paths) == 6
    for path in sealed.execution.fingerprint_paths:
        assert path.exists(), "a failed commit does not undo the record"
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["fingerprint_id"] == path.stem
        assert stored["content_digest"]


def test_the_learning_commit_stages_only_the_records_this_run_wrote(tmp_path):
    """Against a real repository: six files in the tree, and the stranger left alone.

    Two files are planted in the same ledger the run writes to — another run's
    fingerprint and a publication marker, which §3.6 commits by its own step —
    and the learning commit must take neither. `commit_ledger` passes a pathspec
    to every git command for exactly this reason; the test is here because the
    *caller* is what used to defeat it.

    The push fails (there is no remote), so the status is `failed` while the
    commit exists locally — the honest pair §3.1 asks for.
    """

    repo = tmp_path / "repo"
    ledger = repo / "data" / "editorial"
    ledger.mkdir(parents=True)
    for argv in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "ledger@example.test"),
        ("config", "user.name", "Ledger Test"),
        ("commit", "-q", "--allow-empty", "-m", "root"),
    ):
        subprocess.run(["git", "-C", str(repo), *argv], check=True)

    stranger = ledger / "fingerprints" / "other" / "2026-10" / "fp-other-run-wix.json"
    stranger.parent.mkdir(parents=True)
    stranger.write_text("{}", encoding="utf-8")
    marker = ledger / "markers" / "withheld.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")

    sealed = _sealed(tmp_path, commit=True, ledger_dir=ledger, repo_root=repo)
    assert sealed.summary.ledger_commit is LedgerCommitStatus.FAILED
    assert sealed.records_commit.failure is LedgerCommitFailure.PUSH_FAILED

    # The learning commit is the first of the two, so it is HEAD~1 once the
    # summary's commit lands on top of it.
    committed = subprocess.run(
        ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD~1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert len(committed) == 6
    assert {Path(name).stem for name in committed} == set(
        sealed.summary.fingerprint_ids
    )

    untracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert str(stranger.relative_to(repo)) in untracked
    assert str(marker.relative_to(repo)) in untracked


def test_a_run_that_writes_no_learning_record_says_so(tmp_path, monkeypatch):
    """The pass-through run hands no paths, and `commit_ledger` is not lied to.

    `nothing_to_commit` is the honest answer for it: #293's run names a
    fingerprint ID per destination without writing a durable record, so there is
    no file for a learning commit to hold. Empty is the value, not a gap — and
    it must not become six paths borrowed from somewhere.
    """

    calls = _spy(
        monkeypatch, LedgerCommitReport(status=LedgerCommitStatus.NOTHING_TO_COMMIT)
    )
    run_walking_skeleton(
        runs_root=tmp_path / "runs",
        ledger_dir=tmp_path / "ledger",
        commit=True,
        repo_root=tmp_path,
    )

    assert [paths for _, paths in calls][0] == ()
    assert "0 learning record(s)" in calls[0][0]


def test_the_shadow_workflow_has_no_second_generic_ledger_commit():
    """One mechanism, and it is the run's own.

    The workflow used to run `git add data/editorial` after the run. That staged
    whatever was untracked under the ledger — another run's records, a marker
    §3.6 withheld — and it committed the summary's own file in the same breath
    as the records the summary reports on. It is gone: the run commits, by path,
    and the workflow only gives it an identity to commit as.
    """

    parsed = yaml.safe_load(
        Path(".github/workflows/canonical_shadow.yml").read_text(encoding="utf-8")
    )
    steps = parsed["jobs"]["shadow"]["steps"]
    # The run is the last step that executes a **shell**, which is the property
    # this used to assert as "the last step" outright. #308's evidence repair
    # adds an `upload-artifact` step after it; that step has no `run` block, so
    # it cannot stage, commit or push anything — see
    # `tests/test_308_shadow_evidence.py`, which holds its whole contract.
    shells = [step.get("name") for step in steps if step.get("run")]
    assert shells[-1] == "Run the canonical chain in shadow"
    names = [step.get("name") for step in steps]
    for step in steps[names.index("Run the canonical chain in shadow") + 1:]:
        assert "run" not in step, f"a shell step follows the run: {step.get('name')}"

    # What the job *runs*, with the comments stripped: a line that explains why
    # there is no `git add` here is not a `git add`.
    for step in steps:
        for line in step.get("run", "").splitlines():
            code = line.split("#", 1)[0]
            for forbidden in ("git add", "git commit", "git push"):
                assert forbidden not in code, f"{step['name']}: {line.strip()}"

    asked = steps[names.index("Run the canonical chain in shadow")]["run"]
    assert "--commit" in asked, "the run's own mechanism has to be asked for"


# ===========================================================================
# The composition root reads the intake record, not a prepared package
# ===========================================================================
#
# Acceptance run 1 (37166701563) failed two seconds in, before any model call,
# with `ResearchGateError: research requires at least one required, preferred,
# or discovery source`. The cause was not the gate: `_signal` was reading
# `reports/content_packages/<id>.json`, which is the legacy pipeline's prepared
# *output* — five keys, no `SOURCE_URL` — instead of the intake record the
# research pipeline writes. Three modules name the right file, and the run had
# been pointed at the wrong one.


def test_the_shadow_run_reads_the_intake_record_from_the_research_queue():
    """The queue, by SIGNAL_ID — the same file the production selector reads.

    `select_eligible_signal.py --active-path` defaults to it,
    `src/strategy/contract_fit.py` calls it "the real intake record", and
    `src/run/signal_adapter.py` says S-00 reads the record "spelled as intake
    spells it". A prepared package is spelled nothing like it.
    """

    from scripts.run_canonical_shadow import ACTIVE_SIGNALS, PACKAGES_DIR, _signal

    assert ACTIVE_SIGNALS == Path("data/research/signals_active.jsonl")
    # PACKAGES_DIR stays, for the legacy research run_dir S-01's lineage wraps.
    assert PACKAGES_DIR == Path("reports/content_packages")

    queued = [
        json.loads(line)
        for line in ACTIVE_SIGNALS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    first = next(r for r in queued if r.get("SIGNAL_ID"))
    record = _signal(first["SIGNAL_ID"])

    assert record["SIGNAL_ID"] == first["SIGNAL_ID"]
    # The fields the research gate and S-00 actually need, which the prepared
    # package does not carry.
    assert record.get("SOURCE_URL"), "a prepared package has no source URL"
    assert record.get("CORE_FACT") and record.get("SIGNAL_TYPE")
    assert len(record) > 5, "five keys is the shape of the wrong file"


def test_the_research_gate_passes_on_a_real_queued_record():
    """What run 1 crashed on, asserted directly.

    `build_source_directives` needs one required, preferred or discovery
    source. The queue's `SOURCE_URL` is the required one; the prepared package
    had none, so the gate refused before the engine was ever constructed.
    """

    from src.research.lifecycle import build_source_directives
    from scripts.run_canonical_shadow import ACTIVE_SIGNALS, _signal

    queued = [
        json.loads(line)
        for line in ACTIVE_SIGNALS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = _signal(next(r for r in queued if r.get("SIGNAL_ID"))["SIGNAL_ID"])

    directives = build_source_directives(record)
    assert directives, "the gate the run died on"
    assert any(item.directive_id == "required-source-1" for item in directives)


def test_the_composition_root_does_not_pre_screen_the_contract_fields():
    """A record S-00 will refuse is read, passed on, and refused in the trace.

    `src/run/signal_adapter.py` is explicit that a pre-screen would be wrong:
    it "would take the refusal away from the rule that owns it and leave the
    trace unable to say which rule decided". So `_signal` must hand over a
    record with no `EDITORIAL_DOMAIN` / `EDITORIAL_RISK` rather than raise —
    the measurement needs the refusal recorded, not hidden.
    """

    import inspect

    from scripts.run_canonical_shadow import ACTIVE_SIGNALS, _signal
    from src.run.signal_adapter import DOMAIN_FIELD, golden_engine_fit_rules
    from src.run.signal_adapter import selection_candidate

    source = inspect.getsource(_signal)
    assert DOMAIN_FIELD not in source, "the fit rule owns this refusal"
    assert "EDITORIAL_RISK" not in source

    queued = [
        json.loads(line)
        for line in ACTIVE_SIGNALS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    unclassified = next(
        (r for r in queued if r.get("SIGNAL_ID") and not r.get(DOMAIN_FIELD)), None
    )
    if unclassified is None:  # pragma: no cover - the queue is classified
        pytest.skip("every queued record carries the classification")

    record = _signal(unclassified["SIGNAL_ID"])
    assert DOMAIN_FIELD not in record or not record[DOMAIN_FIELD]

    # And the refusal lands on the rule, naming the field, as the trace needs.
    verdicts = golden_engine_fit_rules(
        directory=Path("clients/never_blank")
    ).evaluate(selection_candidate(record).signal)
    refused = {v.rule_id: v for v in verdicts if not v.passed}
    assert "FIT-NB-TOPIC-01" in refused
    assert refused["FIT-NB-TOPIC-01"].field == DOMAIN_FIELD


def test_a_signal_absent_from_the_queue_is_refused_by_name():
    """Not a traceback, and not a silent empty record."""

    from scripts.run_canonical_shadow import _signal

    with pytest.raises(SystemExit, match="is not in data/research"):
        _signal("0000000000000000")
