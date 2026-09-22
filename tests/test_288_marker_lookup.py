"""NB-00b (#288): every pre-publish check consults the marker authority.

The authority NB-00a built could only be reached through the publishing
paths' own guard. ``find_prior_*`` still answered from
``packages_dir/<signal_id>/runs/*``, which a hosted runner's checkout does not
have, and selection answered from ``published_signal_ids.txt``, which is only
committed when a whole job succeeded. Both are re-pointed here, and both keep
their existing behaviour when the authority says nothing was published.

What these prove, deterministically and with no external call:

1. one marker-backed lookup answers for all six destinations;
2. an explicitly dispatched signal that has a marker is refused — the path
   that walks past a consumption list does not walk past this;
3. an authority that cannot answer is a ``SKIP``
   (``idempotency_authority_unavailable``) and no publisher is reached;
4. the Step 5 §1.1 LinkedIn digest-mismatch finding, tested: **CONFIRMED**,
   and no longer able to decide anything. See
   ``docs/PUBLICATION_MARKER_LOOKUP.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.streams import select_eligible_signal
from src.editorial.linkedin_composition import article_digest
from src.publishing.formatting import append_canonical_article_link
from src.publishing.idempotency import (
    LinkedInPublicationIdentity,
    WixPublicationIdentity,
    find_prior_linkedin_publication,
    find_prior_publication,
    find_prior_wix_publication,
    signal_publication_state,
)
from src.publishing.publication_markers import (
    AUTHORITY_UNAVAILABLE,
    DESTINATIONS,
    PUBLICATION_POSSIBLY_EXISTS,
    MarkerStore,
    PublicationGuard,
    PublicationIdentity,
    active_client,
)
from src.publishing.result import UrlProvenance
from tests.test_publication_markers import _REAL_LOOKUPS

SIGNAL = "sig-nb00b-0001"
POST_ID = "prior-post-7781"
POST_URL = "https://www.inneros.online/post/a-documented-case"
CANONICAL = "https://www.inneros.online/post/a-documented-case"
COMPOSED = (
    "An owner-led firm documented one operating decision.\n\n"
    "What changed, and what it cost to find out."
)
MONDAY_ROLE = "never-blank-monday-documented-case"


# ── Seeding the authority ────────────────────────────────────────────────────


def _identity(destination: str, signal_id: str = SIGNAL) -> PublicationIdentity:
    return PublicationIdentity(
        client=active_client(),
        destination=destination,
        source_signal_ids=(signal_id,),
    )


def _seed_marker(
    destination: str,
    signal_id: str = SIGNAL,
    *,
    external_id: str = POST_ID,
    url: str = POST_URL,
    provenance: UrlProvenance = UrlProvenance.PROVIDER_CONFIRMED,
) -> None:
    """A proven earlier publication, written the way a real run writes one."""

    marker = MarkerStore().record_marker(
        _identity(destination, signal_id),
        external_id=external_id,
        url=url,
        url_provenance=provenance,
        content_digest=article_digest(COMPOSED),
        run_id="11111111-1111-4111-8111-111111111111",
    )
    assert marker is not None, "the test's own marker was not made durable"


def _seed_intent(destination: str, signal_id: str = SIGNAL) -> None:
    """A crash between the call and the marker: possibly published."""

    intent = MarkerStore().record_intent(
        _identity(destination, signal_id),
        run_id="11111111-1111-4111-8111-111111111111",
    )
    assert intent is not None, "the test's own intent was not made durable"


# ===========================================================================
# 1. One lookup, all six destinations
# ===========================================================================


@pytest.mark.parametrize("destination", DESTINATIONS)
def test_an_untouched_key_is_neither_a_match_nor_a_refusal(destination):
    scan = find_prior_publication(destination, source_signal_ids=[SIGNAL])
    assert scan.match is None
    assert scan.refusal is None
    assert scan.unusable_reasons == ()


@pytest.mark.parametrize("destination", DESTINATIONS)
def test_a_marker_is_a_match_for_every_destination(destination):
    _seed_marker(destination)
    scan = find_prior_publication(destination, source_signal_ids=[SIGNAL])
    assert scan.match is not None
    assert scan.match.destination == destination
    assert scan.match.post_id == POST_ID
    assert scan.match.url == POST_URL
    assert scan.match.url_provenance is UrlProvenance.PROVIDER_CONFIRMED
    assert scan.refusal is None


@pytest.mark.parametrize("destination", DESTINATIONS)
def test_an_intent_without_a_marker_is_a_refusal_for_every_destination(destination):
    _seed_intent(destination)
    scan = find_prior_publication(destination, source_signal_ids=[SIGNAL])
    assert scan.match is None
    assert scan.refusal == PUBLICATION_POSSIBLY_EXISTS


def test_a_store_that_cannot_answer_is_a_refusal_never_a_clean_no(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NB_PUBLICATION_MARKERS_DIR", str(tmp_path / "not-here"))
    scan = find_prior_publication("wix", source_signal_ids=[SIGNAL])
    assert scan.match is None
    assert scan.refusal == AUTHORITY_UNAVAILABLE


def test_a_publication_with_no_source_signal_cannot_be_proven_unpublished():
    # No identity, so no authority, so no publication (S3-I1 rule 7).
    scan = find_prior_publication("wix", source_signal_ids=[])
    assert scan.match is None
    assert scan.refusal == AUTHORITY_UNAVAILABLE


# ===========================================================================
# 2. find_prior_* now read the authority, with no run directories at all
# ===========================================================================


def test_the_wix_lookup_reads_a_marker_with_no_run_evidence_in_the_checkout(
    tmp_path,
):
    """The fresh-checkout case: ``runs/`` does not exist and the answer holds."""

    _seed_marker("wix")
    identity = WixPublicationIdentity(
        signal_id=SIGNAL,
        source_article_digest=article_digest("the accepted article"),
        wix_site_id="site-live",
    )
    scan = find_prior_wix_publication(tmp_path, identity, current_run_id="run-now")
    assert scan.match is not None
    assert scan.match.post_id == POST_ID
    assert scan.match.url_provenance is UrlProvenance.PROVIDER_CONFIRMED


def test_a_rewritten_article_is_still_the_same_wix_publication(tmp_path):
    """The authority's key carries no article digest — deliberately stricter."""

    _seed_marker("wix")
    rewritten = WixPublicationIdentity(
        signal_id=SIGNAL,
        source_article_digest=article_digest("a completely different article"),
        wix_site_id="site-live",
    )
    scan = find_prior_wix_publication(tmp_path, rewritten, current_run_id="run-now")
    assert scan.match is not None


def test_the_wix_lookup_still_reads_this_checkout_when_the_authority_is_empty(
    tmp_path,
):
    """Nothing published: the run-directory scan is reached, and finds nothing."""

    identity = WixPublicationIdentity(
        signal_id=SIGNAL,
        source_article_digest=article_digest("the accepted article"),
        wix_site_id="site-live",
    )
    scan = find_prior_wix_publication(tmp_path, identity, current_run_id="run-now")
    assert scan.match is None
    assert scan.refusal is None


# ===========================================================================
# 3. The LinkedIn digest mismatch (Step 5 §1.1, "TO TEST"): CONFIRMED
# ===========================================================================


def test_binding_the_canonical_link_moves_the_accepted_body_digest():
    """Half one of the finding: the two digests can never be the same string.

    The identity the canonical entrypoint builds digests
    ``package.linkedin_body``. The run-directory scan digests
    ``linkedin_composition.json``'s body, which cannot contain the link — the
    URL does not exist until Wix has published. The link block is appended
    unconditionally, so the two digests always differ.
    """

    enriched = append_canonical_article_link(COMPOSED, CANONICAL)
    assert enriched != COMPOSED
    assert CANONICAL in enriched
    assert article_digest(enriched) != article_digest(COMPOSED)


def test_the_entrypoint_binds_the_canonical_link_before_it_looks_for_a_prior():
    """Half two: the order that made the mismatch reachable, from the source.

    Read out of the publication section itself, the way
    ``tests/test_canonical_social_lineage.py`` reads the LinkedIn assembly:
    what is being asserted is a property of the entrypoint's order, and a
    harness that stubs the binder — as the legacy one does — cannot show it.
    """

    publication = Path("scripts/generate_and_publish.py").read_text().split(
        "_r1_cls = {"
    )[1]
    assert publication.index("bind_canonical_article_url(") < publication.index(
        "find_prior_linkedin_publication("
    )


def test_the_linkedin_lookup_matches_although_the_body_digest_moved(tmp_path):
    """And the result: the moved digest no longer decides anything.

    The authority's key is ``(client, destination, signal set)``, so the body
    the identity carries — enriched or not — cannot move the answer.
    """

    # LinkedIn's URL is legitimately unavailable (#108); the publication ID is
    # the proof, and it is what a REUSED result carries.
    _seed_marker(
        "linkedin",
        external_id="li-post-1",
        url="",
        provenance=UrlProvenance.UNAVAILABLE,
    )
    enriched = LinkedInPublicationIdentity(
        signal_id=SIGNAL,
        accepted_linkedin_body_digest=article_digest(
            append_canonical_article_link(COMPOSED, CANONICAL)
        ),
        linkedin_account_id="account-live",
    )
    composed_only = LinkedInPublicationIdentity(
        signal_id=SIGNAL,
        accepted_linkedin_body_digest=article_digest(COMPOSED),
        linkedin_account_id="account-live",
    )
    for identity in (enriched, composed_only):
        scan = find_prior_linkedin_publication(
            tmp_path, identity, current_run_id="run-now"
        )
        assert scan.match is not None
        assert scan.match.post_id == "li-post-1"


# ===========================================================================
# 4. The canonical entrypoint: a dispatched signal, and an absent authority
# ===========================================================================


def _publication_results(tmp_path, signal_id) -> dict:
    paths = list(tmp_path.glob(f"{signal_id}/runs/*/publication_results.json"))
    assert paths, "the run under test wrote no publication evidence"
    newest = max(paths, key=lambda path: path.stat().st_mtime)
    return json.loads(newest.read_text())["results"]


def test_a_dispatched_signal_that_has_a_marker_is_refused(tmp_path, monkeypatch):
    """``--signal-id`` is how a dispatch bypasses a consumption list (§1.1).

    It does not bypass the authority: the run is the real canonical entrypoint,
    dispatched at a signal both destinations already have a marker for, and
    neither publisher is reached.
    """

    from tests import test_generate_and_publish as legacy
    from tests.test_publication_preflight import _live_run, _target_env

    _target_env(monkeypatch)
    _seed_marker("wix", legacy._SIGNAL_ID, external_id="wix-post-1", url=POST_URL)
    _seed_marker(
        "linkedin", legacy._SIGNAL_ID, external_id="li-post-1", url="",
        provenance=UrlProvenance.UNAVAILABLE,
    )

    _, wix, linkedin, _ = _live_run(
        tmp_path, PublicationGuard=PublicationGuard, **_REAL_LOOKUPS
    )

    wix.publish.assert_not_called()
    linkedin.publish.assert_not_called()
    results = _publication_results(tmp_path, legacy._SIGNAL_ID)
    assert results["wix"]["status"] == "REUSED"
    assert results["wix"]["external_id"] == "wix-post-1"
    assert results["linkedin"]["status"] == "REUSED"
    assert results["linkedin"]["external_id"] == "li-post-1"


def test_an_authority_that_cannot_answer_skips_and_publishes_nothing(
    tmp_path, monkeypatch
):
    """Fail closed, no wait (§3.6 rule 2): the store is not in this checkout."""

    from tests import test_generate_and_publish as legacy
    from tests.test_publication_preflight import _live_run, _target_env

    _target_env(monkeypatch)
    monkeypatch.setenv(
        "NB_PUBLICATION_MARKERS_DIR", str(tmp_path / "authority-not-in-checkout")
    )

    _, wix, linkedin, _ = _live_run(
        tmp_path, PublicationGuard=PublicationGuard, **_REAL_LOOKUPS
    )

    wix.publish.assert_not_called()
    linkedin.publish.assert_not_called()
    results = _publication_results(tmp_path, legacy._SIGNAL_ID)
    assert results["wix"]["status"] == "SKIPPED"
    assert results["wix"]["error_message"] == AUTHORITY_UNAVAILABLE


# ===========================================================================
# 5. Selection reads the authority beside published_signal_ids.txt
# ===========================================================================


class _AlwaysEligible:
    """Eligibility transport that accepts every candidate, and records asks."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.requests.append(json.loads(request)["source_case"].get("SIGNAL_ID", ""))
        return json.dumps(
            {"eligible": True, "reason": "a documented owner-led operating case"}
        )


def _candidate(index: int) -> dict:
    return {
        "SIGNAL_ID": f"sig-nb00b-{index}",
        "HEADLINE": f"A documented owner-led case number {index}",
        "CORE_FACT": "A small firm documented an operating decision.",
        "REAL_COMPANY_EXAMPLE": "Owner-led firm",
    }


def _select(tmp_path, transport, *, signal_id=""):
    queue = tmp_path / "selection"
    queue.mkdir(parents=True, exist_ok=True)
    active = queue / "signals_active.jsonl"
    active.write_text(
        "\n".join(json.dumps(_candidate(index)) for index in (1, 2)) + "\n"
    )
    published = queue / "published_signal_ids.txt"
    published.write_text("")            # the summary says nothing was published
    audit_path = queue / "audit.json"
    argv = [
        "--editorial-role", MONDAY_ROLE,
        "--active-path", str(active),
        "--published-path", str(published),
        "--audit-out", str(audit_path),
    ]
    if signal_id:
        argv += ["--signal-id", signal_id]
    code = select_eligible_signal.main(argv, transport=transport)
    return code, json.loads(audit_path.read_text())


def test_selection_passes_over_a_signal_the_authority_has_already_spent(tmp_path):
    """The partial-success hole: the summary is empty, the marker is not."""

    _seed_marker("wix", "sig-nb00b-1", external_id="wix-post-1")
    transport = _AlwaysEligible()

    code, audit = _select(tmp_path, transport)

    assert code == 0
    assert audit["selected_signal_id"] == "sig-nb00b-2"
    # never judged: an already-published signal is not a candidate, and a
    # judgment costs a provider call
    assert transport.requests == ["sig-nb00b-2"]
    assert audit["already_published"]["sig-nb00b-1"]["published"] == ["wix"]
    assert audit["candidates_available"] == 1


def test_an_unconfirmed_key_also_removes_the_candidate(tmp_path):
    """At most once: an intent with no marker means *possibly* published."""

    _seed_intent("linkedin", "sig-nb00b-1")
    transport = _AlwaysEligible()

    code, audit = _select(tmp_path, transport)

    assert code == 0
    assert audit["selected_signal_id"] == "sig-nb00b-2"
    assert audit["already_published"]["sig-nb00b-1"]["possibly_published"] == [
        "linkedin"
    ]


def test_an_explicitly_dispatched_signal_with_a_marker_is_refused(tmp_path):
    _seed_marker("wix", "sig-nb00b-1", external_id="wix-post-1")
    transport = _AlwaysEligible()

    code, audit = _select(tmp_path, transport, signal_id="sig-nb00b-1")

    assert code == select_eligible_signal.NO_ELIGIBLE
    assert audit["outcome"] == "already_published"
    assert audit["selected_signal_id"] is None
    assert transport.requests == []


def test_selection_selects_nothing_when_the_authority_cannot_answer(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NB_PUBLICATION_MARKERS_DIR", str(tmp_path / "not-here"))
    transport = _AlwaysEligible()

    code, audit = _select(tmp_path, transport)

    assert code == select_eligible_signal.ELIGIBILITY_FAILURE
    assert audit["outcome"] == AUTHORITY_UNAVAILABLE
    assert audit["selected_signal_id"] is None
    assert transport.requests == []


def test_the_signal_level_state_covers_every_destination():
    _seed_marker("telegram")
    _seed_intent("threads")
    state = signal_publication_state([SIGNAL])
    assert state.published == ("telegram",)
    assert state.possibly_published == ("threads",)
    assert state.consumed is True


def test_an_untouched_signal_is_not_consumed():
    state = signal_publication_state([SIGNAL])
    assert state.consumed is False
    assert state.unavailable is False


def test_an_unreachable_store_makes_the_signal_state_unavailable(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NB_PUBLICATION_MARKERS_DIR", str(tmp_path / "not-here"))
    state = signal_publication_state([SIGNAL])
    assert state.unavailable is True
    # and an unavailable authority is never read as "nothing was published"
    assert state.consumed is False
    assert state.as_audit_dict()["unavailable"] is True
