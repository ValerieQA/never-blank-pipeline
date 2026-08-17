"""Issue #105 / Story #18: Wix retry idempotency and truthful URL provenance.

Deterministic only. Nothing here proves a real Wix publication — live
verification against a real site remains on the deferred track. What these
prove is that a retry of an already-published accepted article creates no
second Wix post, that ambiguous history never manufactures that suppression,
and that a locally constructed URL is never reported as provider-confirmed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from src.editorial.linkedin_composition import article_digest
from src.publishing.idempotency import (
    UNUSABLE_INCONSISTENT,
    UNUSABLE_MALFORMED_RESULTS,
    UNUSABLE_ARTICLE_UNREADABLE,
    UNUSABLE_MISSING_CONTENT_ID,
    UNUSABLE_MISSING_PREFLIGHT,
    UNUSABLE_PROVENANCE_INVALID,
    WixPublicationIdentity,
    find_prior_wix_publication,
)
from src.publishing.package import WixPublicationTarget
from src.publishing.preflight import (
    ChannelPreflightVerdict,
    FreshnessVerdict,
    PreflightDisposition,
    PreflightResult,
    ProvenanceVerdict,
    ReadinessVerdict,
)
from src.publishing.result import PublishStatus, UrlProvenance
from src.publishing.wix import WixPublisher, _resolve_post_url
from src.publishing.wix_media import WixMediaAsset
from tests.test_publication_package import (
    CONFIG,
    FOREIGN_CONFIG,
    RUN,
    SIG,
    _build_wix,
)
from tests import test_generate_and_publish as legacy
from tests.test_linkedin_composition import ARTICLE_BODY

SITE_A = "site-aaaa"
SITE_B = "site-bbbb"
PRIOR_RUN = "run-prior-0001"
POST_ID = "wix-post-777"
PROVIDER_URL = "https://neverblank.co/blog/the-month-you-went-quiet"


def _target(site_id=SITE_A, owner="member-1"):
    return WixPublicationTarget(site_id=site_id, owner_member_id=owner)


def _identity(tmp_path, *, site_id=SITE_A, owner="member-1", article=ARTICLE_BODY):
    package = _build_wix(
        tmp_path,
        target=_target(site_id, owner),
        generated=_generated(article=article),
    )
    return WixPublicationIdentity.from_package(package)


def _generated(*, article=ARTICLE_BODY, **overrides):
    from tests.test_publication_package import _generated as base

    data = base(**overrides)
    data["blog_article"] = article
    return data


def _seed_prior_run(tmp_path, monkeypatch, *, site_id=SITE_A, owner="member-live"):
    """Produce a real canonical prior run by publishing once through main().

    Hand-written artifacts cannot be used any more: a candidate must pass the
    Story #16 whole-run verifier, so the prior evidence has to be a genuine
    chain (assignment → strategy → research → decision → editorial → LinkedIn
    → visual → generated → preflight → publication_results).
    """

    from tests.test_publication_preflight import _live_run, _target_env

    _target_env(monkeypatch)
    monkeypatch.setenv("NB_WIX_SITE_ID", site_id)
    monkeypatch.setenv("NB_WIX_POST_OWNER_ID", owner)
    code, wix_mock, _, _ = _live_run(tmp_path)
    assert code == 0 and wix_mock.publish.call_count == 1
    run_dir = max(
        (path.parent for path in tmp_path.glob("*/runs/*/publication_results.json")),
        key=lambda path: path.stat().st_mtime,
    )
    assert _published_entry(run_dir)["status"] == "PUBLISHED"
    return run_dir


def _published_entry(run_dir: Path) -> dict:
    data = json.loads((run_dir / "publication_results.json").read_text())
    return data["results"]["wix"]


def _rewrite_publication_results(run_dir: Path, **changes):
    """Tamper a prior run's publication record (tests only — never production)."""

    path = run_dir / "publication_results.json"
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


def _live_identity(tmp_path=None, *, site_id=SITE_A, article=None, configuration=None):
    """The identity the *current* run computes for the same live article.

    Built directly from its three components: the duplicate key has no other
    inputs, and in particular it never receives a configuration — which is the
    structural reason a configuration change cannot authorize a duplicate.
    """

    from tests.test_linkedin_composition import ARTICLE_BODY as LIVE_ARTICLE

    return WixPublicationIdentity(
        signal_id=legacy._SIGNAL_ID,
        source_article_digest=article_digest(article or LIVE_ARTICLE),
        wix_site_id=site_id,
    )


# ── A proven canonical prior publication suppresses a duplicate ──────────────


def _scan_for(tmp_path, identity):
    return find_prior_wix_publication(
        tmp_path, identity, current_run_id="run-current-attempt"
    )


def test_proven_prior_publication_is_found(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is not None
    assert scan.match.run_id == run_dir.name
    assert scan.match.post_id == _published_entry(run_dir)["external_id"]
    assert scan.unusable_count == 0


def test_different_run_id_still_matches(tmp_path, monkeypatch):
    """The retry identity deliberately excludes run_id: the current run's own
    id is different by construction, and the prior run still matches."""
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is not None and scan.match.run_id != "run-current-attempt"
    assert run_dir.name != "run-current-attempt"


def test_different_configuration_still_matches(tmp_path, monkeypatch):
    """Configuration is provenance, not a republish switch.

    The prior run is canonically valid under its own configuration; the
    current identity is computed under a different one. The duplicate key
    never compares them, so the retry is still suppressed.
    """
    _seed_prior_run(tmp_path, monkeypatch)
    scan = _scan_for(tmp_path, _live_identity(tmp_path, configuration=FOREIGN_CONFIG))
    assert scan.match is not None, "a configuration change must not authorize a duplicate"


def test_configuration_is_not_part_of_the_duplicate_key():
    assert set(WixPublicationIdentity.__dataclass_fields__) == {
        "signal_id", "source_article_digest", "wix_site_id",
    }


def test_different_owner_member_id_still_matches(tmp_path, monkeypatch):
    """Author metadata is not the destination — it cannot unlock a duplicate."""
    _seed_prior_run(tmp_path, monkeypatch, owner="member-someone-else")
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is not None


# ── Legitimately different publications are not suppressed ───────────────────


def test_different_site_publishes_independently(tmp_path, monkeypatch):
    _seed_prior_run(tmp_path, monkeypatch, site_id=SITE_B)
    scan = _scan_for(tmp_path, _live_identity(tmp_path, site_id=SITE_A))
    assert scan.match is None
    assert scan.unusable_count == 0          # a different destination is not "unusable"


def test_different_article_publishes_independently(tmp_path, monkeypatch):
    _seed_prior_run(tmp_path, monkeypatch)
    other = "A different accepted article entirely, with its own digest."
    scan = _scan_for(tmp_path, _live_identity(tmp_path, article=other))
    assert scan.match is None
    assert scan.unusable_count == 0


@pytest.mark.parametrize(
    "status", ["DRAFT_CREATED", "FAILED", "BLOCKED", "SKIPPED", "REUSED"]
)
def test_non_published_prior_status_never_suppresses(tmp_path, monkeypatch, status):
    """Only a proven live publication counts — a draft is not a publication."""
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    data = json.loads((run_dir / "publication_results.json").read_text())
    data["results"]["wix"]["status"] = status
    (run_dir / "publication_results.json").write_text(json.dumps(data))
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert scan.unusable_count == 0


# ── The candidate must be a proven canonical chain of its own ────────────────


def test_candidate_run_id_namespace_mismatch_is_unusable(tmp_path, monkeypatch):
    """publication_results claiming another run than its own directory."""
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    _rewrite_publication_results(run_dir, run_id="run-claimed-elsewhere")
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert UNUSABLE_PROVENANCE_INVALID in scan.unusable_reasons


def test_candidate_with_inconsistent_configuration_is_unusable(tmp_path, monkeypatch):
    """The candidate's own publication configuration contradicts its run."""
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    _rewrite_publication_results(
        run_dir, configuration_identity=FOREIGN_CONFIG.model_dump()
    )
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert UNUSABLE_PROVENANCE_INVALID in scan.unusable_reasons


def test_candidate_with_substituted_generation_lineage_is_unusable(
    tmp_path, monkeypatch
):
    """The referenced article digest still matches, but the lineage is forged.

    The publication is pointed at a copy of the accepted article placed in a
    foreign run directory: the digest check alone would pass, so only the
    whole-run verifier can catch it.
    """
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    forged = run_dir.parent / "run-forged-generation"
    forged.mkdir()
    (forged / "generated.json").write_text(
        (run_dir / "generated.json").read_text(), encoding="utf-8"
    )
    _rewrite_publication_results(
        run_dir, generation_run_id="run-forged-generation",
        source_run_id="run-forged-generation",
    )
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert UNUSABLE_PROVENANCE_INVALID in scan.unusable_reasons


def test_a_corrupt_candidate_does_not_hide_a_valid_one(tmp_path, monkeypatch):
    """Scanning continues past unusable evidence to a genuinely valid run."""
    corrupt = _seed_prior_run(tmp_path, monkeypatch)
    _rewrite_publication_results(corrupt, run_id="run-claimed-elsewhere")
    # a second, untouched canonical publication of the same article/site
    valid = _seed_prior_run(tmp_path, monkeypatch)
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    # a corrupt sibling neither suppresses nor hides the genuine publication;
    # whether its reason is recorded depends on scan order, which is why the
    # assertion is on the match, not on the reason list
    assert scan.match is not None
    assert scan.match.run_id == valid.name
    assert corrupt.name != valid.name


# ── The target evidence must belong to the candidate ─────────────────────────
#
# Story #16 verification covers the generation/publication chain but not the
# Story #17 verdict, so the verdict that names the destination has to be proven
# to be the candidate's own. These cover the relabel/swap surface directly.


def _tamper_preflight(run_dir: Path, mutate):
    verdict = json.loads((run_dir / "preflight_result.json").read_text())
    mutate(verdict)
    (run_dir / "preflight_result.json").write_text(json.dumps(verdict))


def test_relabelled_target_in_prior_preflight_is_unusable(tmp_path, monkeypatch):
    """A valid publication to site B cannot be relabelled as site A."""

    run_dir = _seed_prior_run(tmp_path, monkeypatch, site_id=SITE_B)

    def relabel(verdict):
        for channel in verdict["channels"]:
            if channel["channel"] == "wix":
                channel["target"]["site_id"] = SITE_A

    _tamper_preflight(run_dir, relabel)

    scan = _scan_for(tmp_path, _live_identity(tmp_path, site_id=SITE_A))
    assert scan.match is None, "a relabelled target must never suppress a publication"
    assert scan.unusable_count == 1
    assert UNUSABLE_INCONSISTENT in scan.unusable_reasons


def test_foreign_preflight_copied_into_another_run_is_rejected(tmp_path, monkeypatch):
    """A structurally valid verdict from another run proves nothing here."""

    first = _seed_prior_run(tmp_path, monkeypatch)
    second = _seed_prior_run(tmp_path, monkeypatch)
    (second / "preflight_result.json").write_text(
        (first / "preflight_result.json").read_text(), encoding="utf-8"
    )
    # the donor is removed so only the run carrying the foreign verdict remains
    (first / "publication_results.json").unlink()

    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert UNUSABLE_INCONSISTENT in scan.unusable_reasons


def test_prior_preflight_with_tampered_configuration_is_unusable(tmp_path, monkeypatch):
    """The verdict must carry the candidate run's authoritative configuration."""

    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    _tamper_preflight(
        run_dir,
        lambda verdict: verdict.update(
            configuration_identity=FOREIGN_CONFIG.model_dump()
        ),
    )
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert UNUSABLE_INCONSISTENT in scan.unusable_reasons


def test_prior_preflight_claiming_another_run_is_unusable(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    _tamper_preflight(
        run_dir, lambda verdict: verdict.update(run_id="run-claimed-elsewhere")
    )
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert UNUSABLE_INCONSISTENT in scan.unusable_reasons


def test_valid_prior_verdict_reconstructs_its_authorized_package(tmp_path, monkeypatch):
    """The binding is real: the recorded digest is reproducible from evidence.

    A valid candidate matches, which is only possible because its verdict's
    ``package_digest`` was successfully rebuilt from the accepted article, the
    run's own visual passport, its configuration and the verdict's target.
    """

    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    verdict = json.loads((run_dir / "preflight_result.json").read_text())
    wix_channel = next(c for c in verdict["channels"] if c["channel"] == "wix")
    assert wix_channel["package_digest"].startswith("sha256:")

    assert _scan_for(tmp_path, _live_identity(tmp_path)).match is not None

    # …and a digest that no longer describes its own contents is rejected
    _tamper_preflight(
        run_dir,
        lambda v: [
            c.update(package_digest="sha256:" + "e" * 64)
            for c in v["channels"] if c["channel"] == "wix"
        ],
    )
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert UNUSABLE_INCONSISTENT in scan.unusable_reasons


# ── Ambiguity never manufactures idempotency ─────────────────────────────────


def test_malformed_prior_results_do_not_suppress(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    (run_dir / "publication_results.json").write_text("{not json", encoding="utf-8")
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert scan.unusable_reasons == (UNUSABLE_MALFORMED_RESULTS,)


def test_missing_prior_preflight_does_not_suppress(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    (run_dir / "preflight_result.json").unlink()
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert scan.unusable_reasons == (UNUSABLE_MISSING_PREFLIGHT,)


def test_missing_prior_content_id_does_not_suppress(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    data = json.loads((run_dir / "publication_results.json").read_text())
    data["results"]["wix"]["external_id"] = ""
    (run_dir / "publication_results.json").write_text(json.dumps(data))
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert scan.unusable_reasons == (UNUSABLE_MISSING_CONTENT_ID,)


def test_prior_preflight_blocking_wix_is_inconsistent_evidence(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    verdict = json.loads((run_dir / "preflight_result.json").read_text())
    for channel in verdict["channels"]:
        if channel["channel"] == "wix":
            channel["disposition"] = "BLOCK"
            channel["blocking_reasons"] = ["credential_missing"]
    verdict["run_disposition"] = "BLOCK"
    verdict["run_blocking_reasons"] = ["readiness_failed"]
    for channel in verdict["channels"]:
        channel["disposition"] = "BLOCK"
        channel["blocking_reasons"] = channel["blocking_reasons"] or ["run_blocked"]
    (run_dir / "preflight_result.json").write_text(json.dumps(verdict))
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    assert UNUSABLE_INCONSISTENT in scan.unusable_reasons


def test_missing_generation_evidence_does_not_suppress(tmp_path, monkeypatch):
    """A publication pointing at a generation run that does not exist."""
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    _rewrite_publication_results(run_dir, generation_run_id="run-that-does-not-exist")
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None
    # the whole-run verifier catches it before the digest is even derived
    assert UNUSABLE_PROVENANCE_INVALID in scan.unusable_reasons


def test_unreadable_article_evidence_is_a_typed_unusable_reason(tmp_path):
    """Defense in depth: the digest derivation itself fails closed."""
    from src.publishing.idempotency import _prior_article_digest

    digest, reason = _prior_article_digest(tmp_path, "sig-x", "run-missing")
    assert digest is None and reason == UNUSABLE_ARTICLE_UNREADABLE
    digest, reason = _prior_article_digest(tmp_path, "sig-x", "")
    assert digest is None and reason is not None


def test_unusable_evidence_note_is_sanitized(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    (run_dir / "publication_results.json").write_text("{not json", encoding="utf-8")
    note = _scan_for(tmp_path, _live_identity(tmp_path)).evidence_note()
    assert note == {"count": 1, "reasons": [UNUSABLE_MALFORMED_RESULTS]}
    # typed reason codes only — no raw artifact content, no verifier prose
    assert "not json" not in json.dumps(note)


def test_no_prior_runs_at_all(tmp_path):
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is None and scan.unusable_count == 0
    assert scan.evidence_note() is None


def test_the_current_run_never_matches_itself(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    scan = find_prior_wix_publication(
        tmp_path, _live_identity(tmp_path), current_run_id=run_dir.name
    )
    assert scan.match is None


def test_prior_record_without_provenance_is_not_promoted(tmp_path, monkeypatch):
    """A URL whose origin was never recorded is never called provider-confirmed."""
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    data = json.loads((run_dir / "publication_results.json").read_text())
    data["results"]["wix"]["url"] = PROVIDER_URL
    data["results"]["wix"].pop("url_provenance", None)
    (run_dir / "publication_results.json").write_text(json.dumps(data))
    scan = _scan_for(tmp_path, _live_identity(tmp_path))
    assert scan.match is not None
    assert scan.match.url == PROVIDER_URL
    assert scan.match.url_provenance is UrlProvenance.UNAVAILABLE


# ── URL provenance at the adapter boundary ───────────────────────────────────


def test_provider_returned_url_is_provider_confirmed():
    with mock.patch("src.publishing.wix._fetch", return_value=(
        200, {"post": {"slug": "the-slug", "url": PROVIDER_URL}}, ""
    )):
        url, provenance = _resolve_post_url("post-1", {})
    assert url == PROVIDER_URL
    assert provenance is UrlProvenance.PROVIDER_CONFIRMED


def test_local_fallback_is_locally_derived(monkeypatch):
    monkeypatch.setenv("NB_WIX_SITE_BASE_URL", "https://neverblank.co/")
    with mock.patch("src.publishing.wix._fetch", return_value=(
        200, {"post": {"slug": "the-slug"}}, ""
    )):
        url, provenance = _resolve_post_url("post-1", {})
    assert url == "https://neverblank.co/blog/the-slug"
    assert provenance is UrlProvenance.LOCALLY_DERIVED


def test_no_usable_url_is_unavailable(monkeypatch):
    monkeypatch.delenv("NB_WIX_SITE_BASE_URL", raising=False)
    with mock.patch("src.publishing.wix._fetch", return_value=(
        200, {"post": {"slug": "the-slug"}}, ""
    )):
        url, provenance = _resolve_post_url("post-1", {})
    assert url == ""
    assert provenance is UrlProvenance.UNAVAILABLE

    with mock.patch("src.publishing.wix._fetch", return_value=(404, {}, "")):
        url, provenance = _resolve_post_url("post-1", {})
    assert (url, provenance) == ("", UrlProvenance.UNAVAILABLE)


def test_publish_carries_url_provenance(tmp_path, monkeypatch):
    """A live publish records where its URL came from."""
    monkeypatch.setenv("NB_WIX_API_KEY", "secret")
    package = _build_wix(tmp_path, target=_target())

    def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        if method == "POST" and "draft-posts" in url and "publish" not in url:
            return 201, {"draftPost": {"id": "draft-1"}}, ""
        if method == "GET" and "draft-posts" in url:
            return 200, {"draftPost": {
                "media": {"wixMedia": {"image": {"id": "file-1"}}}
            }}, ""
        if "publish" in url:
            return 200, {"post": {"id": POST_ID, "url": PROVIDER_URL}}, ""
        return 200, {}, ""

    with mock.patch("src.publishing.wix.import_image",
                    return_value=WixMediaAsset(file_id="file-1")):
        with mock.patch("src.publishing.wix._fetch", side_effect=fake_fetch):
            result = WixPublisher().publish(package, "live")

    assert result.status is PublishStatus.PUBLISHED
    assert result.external_id == POST_ID
    assert result.url_provenance is UrlProvenance.PROVIDER_CONFIRMED
    assert result.to_dict()["url_provenance"] == "provider_confirmed"


# ── End-to-end through the canonical entrypoint ──────────────────────────────
#
# These run the real idempotency check inside main(), with the real #101
# preflight, to prove the side-effect placement: a proven prior publication
# suppresses the Wix call entirely (no media import, no draft, no publish),
# while everything ambiguous still publishes.

import sys  # noqa: E402

import scripts.generate_and_publish as gap  # noqa: E402
from scripts.generate_and_publish import main  # noqa: E402
from tests.test_publication_preflight import _live_run, _target_env  # noqa: E402


def _prior_for_live_run(tmp_path, monkeypatch, *, status=None, malformed_results=False):
    """Seed a real canonical prior publication, optionally degraded."""

    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    if malformed_results:
        (run_dir / "publication_results.json").write_text("{not json", encoding="utf-8")
    elif status is not None:
        data = json.loads((run_dir / "publication_results.json").read_text())
        data["results"]["wix"]["status"] = status
        (run_dir / "publication_results.json").write_text(json.dumps(data))
    return run_dir


def _real_scan_run(tmp_path, **overrides):
    """`_live_run` with the real idempotency scan wired back in."""

    overrides.setdefault("find_prior_wix_publication", find_prior_wix_publication)
    return _live_run(tmp_path, **overrides)


def _current_publication(tmp_path):
    """The publication evidence of the run under test, not of the seeded prior."""

    paths = list(tmp_path.glob(f"{legacy._SIGNAL_ID}/runs/*/publication_results.json"))
    assert paths, "the run under test wrote no publication evidence"
    # the run under test is the one written last
    newest = max(paths, key=lambda path: path.stat().st_mtime)
    return json.loads(newest.read_text())


def test_sequential_retry_reuses_and_calls_no_wix_endpoint(tmp_path, monkeypatch):
    prior_run = _prior_for_live_run(tmp_path, monkeypatch)
    with mock.patch("src.publishing.wix.import_image") as media, \
         mock.patch("src.publishing.wix._fetch") as fetch:
        code, wix_mock, li_mock, verdicts = _real_scan_run(tmp_path)

    # the publisher class was never asked to publish…
    wix_mock.publish.assert_not_called()
    # …and no Wix network work happened at all
    media.assert_not_called()
    fetch.assert_not_called()
    assert li_mock.publish.called          # the other channel is unaffected

    published = _current_publication(tmp_path)
    prior = _published_entry(prior_run)
    wix = published["results"]["wix"]
    assert wix["status"] == "REUSED"
    # the prior publication's evidence is preserved exactly, not re-derived
    assert wix["external_id"] == prior["external_id"]
    assert wix["url"] == prior["url"]
    assert wix["url_provenance"] == prior["url_provenance"]
    assert wix["reused_from_run_id"] == prior_run.name
    assert published["wix_reused_from_run_id"] == prior_run.name
    assert wix["run_id"] and wix["run_id"] != prior_run.name  # current identity apart
    assert published["completed"] is True                  # a reuse is not a failure
    assert code == 0


def test_reused_run_does_not_append_a_second_history_entry(tmp_path, monkeypatch):
    _prior_for_live_run(tmp_path, monkeypatch)
    history = mock.MagicMock()
    with mock.patch("src.publishing.wix.import_image"), \
         mock.patch("src.publishing.wix._fetch"):
        _real_scan_run(tmp_path, append_published_entry=history)
    entry = history.call_args.args[0]
    assert "wix" not in entry.publications, (
        "a retry must not be recorded as a second freshly published Wix post"
    )


def test_first_publication_publishes_exactly_once(tmp_path, monkeypatch):
    _target_env(monkeypatch)
    code, wix_mock, li_mock, verdicts = _real_scan_run(tmp_path)
    assert wix_mock.publish.call_count == 1
    published = _current_publication(tmp_path)
    assert published["results"]["wix"]["status"] == "PUBLISHED"
    assert published["wix_reused_from_run_id"] is None
    assert published["unusable_prior_publication_evidence"] is None


def test_prior_draft_does_not_suppress_live_publication(tmp_path, monkeypatch):
    _prior_for_live_run(tmp_path, monkeypatch, status="DRAFT_CREATED")
    code, wix_mock, _, _ = _real_scan_run(tmp_path)
    assert wix_mock.publish.call_count == 1


@pytest.mark.parametrize("status", ["FAILED", "BLOCKED", "SKIPPED"])
def test_prior_unsuccessful_result_does_not_suppress(tmp_path, monkeypatch, status):
    _prior_for_live_run(tmp_path, monkeypatch, status=status)
    code, wix_mock, _, _ = _real_scan_run(tmp_path)
    assert wix_mock.publish.call_count == 1


def test_unusable_prior_evidence_is_recorded_and_publication_proceeds(
    tmp_path, monkeypatch
):
    _prior_for_live_run(tmp_path, monkeypatch, malformed_results=True)
    code, wix_mock, _, _ = _real_scan_run(tmp_path)
    assert wix_mock.publish.call_count == 1
    published = _current_publication(tmp_path)
    note = published["unusable_prior_publication_evidence"]
    assert note == {"count": 1, "reasons": [UNUSABLE_MALFORMED_RESULTS]}
    assert published["results"]["wix"]["status"] == "PUBLISHED"


def test_preflight_block_is_never_bypassed_by_idempotency(tmp_path, monkeypatch):
    """A blocked channel never reaches the idempotency check at all."""

    _prior_for_live_run(tmp_path, monkeypatch)
    monkeypatch.delenv("NB_WIX_API_KEY", raising=False)   # Wix credential missing
    with mock.patch("src.publishing.wix.import_image") as media, \
         mock.patch("src.publishing.wix._fetch") as fetch:
        code, wix_mock, li_mock, verdicts = _real_scan_run(tmp_path)

    wix_mock.publish.assert_not_called()
    media.assert_not_called()
    fetch.assert_not_called()
    published = _current_publication(tmp_path)
    # blocked, never reused — the prior publication cannot rescue a blocked run
    assert published["results"]["wix"]["status"] == "BLOCKED"
    assert published["wix_reused_from_run_id"] is None
