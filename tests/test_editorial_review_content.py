"""Issue #134: a blocked run preserves what it produced, for human review only.

Editorial acceptance blocks before packaging, so a blocked run wrote no
``generated.json`` and its article, LinkedIn body and visuals died with the
runner. These scenarios prove the content is now preserved, that preserving it
changes no decision, and — the part that matters most — that the preserved
record cannot become a way to publish content the gate refused.

Everything runs through the real canonical entrypoint with injected fake
reviewer/revision transports and the real acceptance boundary.
"""

from __future__ import annotations

import json

import pytest

from src.artifacts import (
    REVIEW_ONLY_KIND,
    ArtifactCollisionError,
    load_run_generated,
    write_editorial_review_content_json,
)
from tests.test_editorial_acceptance import (
    FakeReviewTransport,
    FakeRevisionTransport,
    _assert_no_publication_effects,
    _audit,
    _review_payload,
    _run_entry,
)


REVISION_BODY = "Revised article body with the unsupported claims removed."


def _review_content(tmp_path) -> dict:
    records = list(tmp_path.glob("*/runs/*/editorial_review_content.json"))
    assert len(records) == 1
    return json.loads(records[0].read_text())


def _blocking_reviewer(second: str = "revise") -> FakeReviewTransport:
    return FakeReviewTransport(
        _review_payload(
            disposition="revise",
            failed=["unsupported-claims", "evidence-use"],
            guidance="Remove the claims the evidence does not support.",
        ),
        _review_payload(
            disposition=second,
            failed=["unsupported-claims"] if second != "accept" else [],
            guidance="Still asserts audience behaviour as fact." if second != "accept" else "",
        ),
    )


# ===========================================================================
# 1–2. The accepted paths are untouched
# ===========================================================================


def test_an_accepted_article_writes_no_review_record(tmp_path):
    reviewer = FakeReviewTransport(_review_payload())

    code, _ = _run_entry(tmp_path, reviewer=reviewer)

    assert code == 0
    assert list(tmp_path.glob("*/runs/*/generated.json"))  # normal packaging
    # nothing to preserve for review: the article was accepted
    assert not list(tmp_path.glob("*/runs/*/editorial_review_content.json"))


def test_revise_then_accept_still_publishes_and_writes_no_review_record(tmp_path):
    reviewer = _blocking_reviewer(second="accept")
    revisor = FakeRevisionTransport(REVISION_BODY)

    code, _ = _run_entry(tmp_path, reviewer=reviewer, revisor=revisor)

    assert code == 0
    generated = json.loads(next(tmp_path.glob("*/runs/*/generated.json")).read_text())
    assert generated["blog_article"].startswith(REVISION_BODY)
    assert not list(tmp_path.glob("*/runs/*/editorial_review_content.json"))
    assert _audit(tmp_path)["accepted"] is True


# ===========================================================================
# 3. A blocked run preserves what it produced
# ===========================================================================


def test_a_blocked_run_preserves_the_article_linkedin_body_and_visuals(tmp_path):
    reviewer = _blocking_reviewer()
    revisor = FakeRevisionTransport(REVISION_BODY)

    code, _ = _run_entry(tmp_path, reviewer=reviewer, revisor=revisor)

    assert code == 1
    record = _review_content(tmp_path)
    content = record["content"]
    # both articles: what was written, and what the revision made of it
    assert content["article_as_generated"]
    assert content["article_after_revision"] == REVISION_BODY
    assert content["article_as_generated"] != content["article_after_revision"]
    assert content["linkedin_body"]
    # #177: image generation now happens AFTER acceptance, so a blocked run
    # has honestly generated no visuals — that is the cost win, and the
    # record says so instead of pretending assets existed
    assert record["visuals"] == {}
    # the verdict that refused it, beside the content it refused
    assert record["editorial"]["final_disposition"] == "revise"
    assert record["editorial"]["failed_criterion_ids"] == ["unsupported-claims"]
    assert record["editorial"]["revised"] is True
    assert record["editorial"]["rubric"] == "never-blank-editorial-acceptance/1.0"


def test_a_run_blocked_without_a_revision_preserves_the_article_it_wrote(tmp_path):
    reviewer = FakeReviewTransport(_review_payload(disposition="reject", failed=["reader-value"]))

    code, _ = _run_entry(tmp_path, reviewer=reviewer)

    assert code == 1
    content = _review_content(tmp_path)["content"]
    assert content["article_as_generated"]
    # no revision ran, so there is no revised article to claim one
    assert content["article_after_revision"] is None


def test_the_record_is_tied_to_the_exact_run(tmp_path):
    reviewer = _blocking_reviewer()

    _run_entry(tmp_path, reviewer=reviewer, revisor=FakeRevisionTransport(REVISION_BODY))

    record = _review_content(tmp_path)
    run_dir = next(tmp_path.glob("*/runs/*/editorial_review_content.json")).parent
    assert record["run_id"] == run_dir.name
    assert record["signal_id"] == run_dir.parent.parent.name
    assert record["assignment_id"] == record["signal_id"]
    # the acceptance audit for the same run agrees
    assert _audit(tmp_path)["run_id"] == record["run_id"]


# ===========================================================================
# 4 & 7. Review-only, and never a way to publish what was refused
# ===========================================================================


def test_the_record_declares_itself_unpublishable(tmp_path):
    _run_entry(tmp_path, reviewer=_blocking_reviewer(),
               revisor=FakeRevisionTransport(REVISION_BODY))

    record = _review_content(tmp_path)
    assert record["artifact_kind"] == REVIEW_ONLY_KIND
    assert record["publishable"] is False
    assert "NOT approved for publication" in record["notice"]


def test_the_record_cannot_be_loaded_as_a_publishable_package(tmp_path):
    _run_entry(tmp_path, reviewer=_blocking_reviewer(),
               revisor=FakeRevisionTransport(REVISION_BODY))
    run_dir = next(tmp_path.glob("*/runs/*/editorial_review_content.json")).parent

    # --from-package reads generated.json and only generated.json; the review
    # record is not it, and a blocked run has none
    with pytest.raises(FileNotFoundError):
        load_run_generated(tmp_path, run_dir.parent.parent.name, run_dir.name)


def test_the_record_carries_no_publication_shaped_fields(tmp_path):
    _run_entry(tmp_path, reviewer=_blocking_reviewer(),
               revisor=FakeRevisionTransport(REVISION_BODY))

    record = _review_content(tmp_path)
    # nothing a package builder consumes: no strategy provenance, no headline,
    # no blog_article/linkedin_post keys, no target identity
    assert set(record) == {
        "artifact_kind", "publishable", "notice", "run_id", "signal_id",
        "assignment_id", "editorial", "content", "visuals",
    }
    flat = json.dumps(record)
    for forbidden in ("strategy_id", "strategy_version", "generated_at",
                      "blog_article", "linkedin_post", "api_key", "token"):
        assert forbidden not in flat


# ===========================================================================
# 5. The block is still a block
# ===========================================================================


def test_preserving_content_changes_no_publication_effect(tmp_path):
    reviewer = _blocking_reviewer()

    code, patches = _run_entry(
        tmp_path, reviewer=reviewer, revisor=FakeRevisionTransport(REVISION_BODY),
        dry_run=False,
    )

    assert code == 1
    _assert_no_publication_effects(tmp_path, patches)  # no Wix, no LinkedIn, no index entry
    assert _audit(tmp_path)["accepted"] is False
    # the preserved record exists and is not one of the publication effects
    assert list(tmp_path.glob("*/runs/*/editorial_review_content.json"))


# ===========================================================================
# 6. Create-once and provenance guarantees are intact
# ===========================================================================


def test_the_review_record_is_create_once(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_editorial_review_content_json(run_dir, {"run_id": "r"})

    with pytest.raises(ArtifactCollisionError):
        write_editorial_review_content_json(run_dir, {"run_id": "r"})


def test_the_review_record_is_not_a_canonical_artifact(tmp_path):
    from src.reporting.run_report import CANONICAL_ARTIFACTS

    assert "editorial_review_content.json" not in CANONICAL_ARTIFACTS


def test_a_blocked_run_still_reports_honestly_with_the_record_present(tmp_path):
    _run_entry(tmp_path, reviewer=_blocking_reviewer(),
               revisor=FakeRevisionTransport(REVISION_BODY))

    report = json.loads(next(tmp_path.glob("*/runs/*/run_report.json")).read_text())
    assert report["terminal_stage"] == "editorial"
    assert report["completed"] is False
    assert report["channels"] == []
    # the report references canonical artifacts only — preserving review
    # content does not make the run look as though it produced evidence it did
    # not
    assert "editorial_review_content.json" not in [
        item["name"] for item in report["artifacts"]
    ]
