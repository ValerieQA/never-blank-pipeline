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
from pathlib import Path

import pytest

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
