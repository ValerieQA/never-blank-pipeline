"""Issue #200: the canonical URL comes from the published Wix object.

Live run 32740322282 published a social post whose canonical link returned
404. Two defects compounded: the provider was never asked for the URL (its
``URL`` fieldset is opt-in, so the response carried no ``url`` at all), and
the field is a ``PageUrl`` object that the code read as a string — so the
"provider-confirmed" branch could never have worked either. The run then
fell through to a locally constructed route while the site serves another,
and every stage downstream trusted the guess.

The corrected contract has two separate halves, and these scenarios pin
both. **Identity** is structural and comes from the provider object: publish
→ post ID → retrieve that exact post ID with ``fieldsets=URL`` → the
provider returns that same post ID → use the ``PageUrl`` it attached.
**Reachability** is a bounded HTTP request with redirects followed. Nothing
anywhere infers identity from URL text: no slug matching, no path
conventions, no page content, no model.
"""

from __future__ import annotations

import json
import sys
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.publishing.canonical_url import (
    MAX_ATTEMPTS,
    CanonicalUrlVerdict,
    verify_canonical_url,
)
from src.publishing.result import PublishResult, PublishStatus, UrlProvenance
from src.publishing.wix import ProviderUrlLookup, page_url_to_str
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_generate_and_publish import _make_ok_publish_result
from tests.test_research_artifact_lifecycle import ReadyProvider

SITE = "https://www.inneros.online"
POST_ID = "0b3d3da0-6bf5-4b77-ada2-a29455ebdbf0"
SLUG = "the-faster-you-patch-the-income-gap"
#: what the provider reports and the site serves — proven by the live run
LIVE_URL = f"{SITE}/post/{SLUG}"
#: what the pipeline constructed and published a link to — proven 404
DEFECT_URL = f"{SITE}/blog/{SLUG}"


def _reach(url):
    return (url, 200)


def _gone(url):
    return (url, 404)


def _verify(url, provenance=UrlProvenance.PROVIDER_LOOKUP, *, fetch=_reach):
    return verify_canonical_url(
        url=url, provenance=provenance, expected_host=SITE,
        fetch=fetch, sleep=lambda _s: None,
    )


def _lookup(**over):
    base = dict(
        requested_post_id=POST_ID, returned_post_id=POST_ID, url=LIVE_URL,
        provenance=UrlProvenance.PROVIDER_LOOKUP, http_status=200,
    )
    base.update(over)
    return ProviderUrlLookup(**base)


# ===========================================================================
# The provider object contract (items 1, 2, 3, 4)
# ===========================================================================


def test_the_provider_url_object_is_rendered_as_an_absolute_url():
    # the API types this field as PageUrl{base, path}; reading it as a string
    # is what silently produced nothing usable
    assert page_url_to_str({"base": SITE, "path": f"/post/{SLUG}"}) == LIVE_URL
    assert page_url_to_str({"base": SITE + "/", "path": f"post/{SLUG}"}) == LIVE_URL
    assert page_url_to_str(LIVE_URL) == LIVE_URL          # defensive
    assert page_url_to_str(None) == ""
    assert page_url_to_str({"base": SITE}) == ""          # never a half URL
    assert page_url_to_str({"path": "/post/x"}) == ""


def test_the_lookup_requests_the_url_fieldset_by_exact_post_id():
    from src.publishing import wix

    captured = {}

    def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        captured["url"] = url
        return 200, {"post": {
            "id": POST_ID, "slug": SLUG,
            "url": {"base": SITE, "path": f"/post/{SLUG}"},
        }}, ""

    with mock.patch("src.publishing.wix._fetch", side_effect=fake_fetch):
        result = wix._resolve_post_url(POST_ID, {})

    assert POST_ID in captured["url"]
    assert "fieldsets=URL" in captured["url"]              # opt-in field
    assert result.identity_ok() is True                    # item 1
    assert result.url == LIVE_URL
    assert result.provenance is UrlProvenance.PROVIDER_LOOKUP


def test_a_lookup_about_a_different_post_has_no_identity():          # item 2
    mismatched = _lookup(returned_post_id="some-other-post-id")
    assert mismatched.identity_ok() is False
    # …and offers nothing to verify
    view = mismatched.as_result_view()
    assert view.url == ""
    assert view.url_provenance is UrlProvenance.UNAVAILABLE
    assert _verify(view.url, view.url_provenance).verified is False


def test_a_lookup_without_a_page_url_has_nothing_canonical(monkeypatch):  # item 3
    from src.publishing import wix

    monkeypatch.setenv("NB_WIX_SITE_BASE_URL", SITE)
    with mock.patch("src.publishing.wix._fetch", return_value=(
        200, {"post": {"id": POST_ID, "slug": SLUG}}, ""
    )):
        result = wix._resolve_post_url(POST_ID, {})

    assert result.identity_ok() is True        # the post is real …
    assert result.url == ""                    # … but has no provider URL
    assert result.provenance is UrlProvenance.UNAVAILABLE
    # a locally built route is recorded as evidence, never offered as canonical
    assert result.local_candidate.startswith(SITE)
    assert result.as_result_view().url == ""


def test_a_failed_lookup_yields_no_canonical_url():                  # item 4
    from src.publishing import wix

    with mock.patch("src.publishing.wix._fetch", return_value=(500, {}, "")):
        result = wix._resolve_post_url(POST_ID, {})
    assert result.url == ""
    assert result.identity_ok() is False
    assert result.provenance is UrlProvenance.UNAVAILABLE


# ===========================================================================
# Reachability (items 5, 6, 7, 8) — no identity inference from URL text
# ===========================================================================


def test_a_reachable_provider_url_passes():                          # item 5
    verdict = _verify(LIVE_URL)
    assert verdict.verified is True
    assert verdict.url == LIVE_URL
    assert verdict.http_status == 200
    assert verdict.final_resolved_url == ""      # no redirect occurred
    assert verdict.attempts == 1


def test_a_404_provider_url_is_refused():                            # item 6
    # the exact URL the live run published a link to
    verdict = _verify(DEFECT_URL, fetch=_gone)
    assert verdict.verified is False
    assert verdict.failure_reason == "http_404"
    assert verdict.attempts == MAX_ATTEMPTS


def test_a_same_site_redirect_passes_and_is_recorded():              # item 7
    moved = f"{SITE}/post/{SLUG}-v2"
    verdict = _verify(LIVE_URL, fetch=lambda _u: (moved, 200))
    assert verdict.verified is True
    # the provider's URL stays canonical; the movement is recorded, never
    # silently substituted
    assert verdict.url == LIVE_URL
    assert verdict.final_resolved_url == moved
    assert verdict.as_audit_dict()["final_resolved_url"] == moved


def test_a_redirect_that_leaves_the_expected_host_is_refused():      # item 8
    verdict = _verify(LIVE_URL, fetch=lambda _u: ("https://elsewhere.test/x", 200))
    assert verdict.verified is False
    assert verdict.failure_reason == "redirect_left_expected_host:elsewhere.test"


def test_the_expected_host_is_matched_structurally():
    assert _verify(f"https://evil.test/post/{SLUG}").failure_reason == (
        "unexpected_host:evil.test"
    )
    assert "unexpected_host" in _verify(
        f"https://www.inneros.online.evil.test/post/{SLUG}"
    ).failure_reason
    assert _verify(f"http://www.inneros.online/post/{SLUG}").failure_reason == "not_https"
    assert _verify("").failure_reason == "no_candidate_url"


# ===========================================================================
# Locally-derived routes (items 9, 10) and the withdrawn slug heuristic
# (items 11, 12)
# ===========================================================================


@pytest.mark.parametrize("candidate", [DEFECT_URL, LIVE_URL])
def test_a_locally_derived_route_never_qualifies(candidate):     # items 9, 10
    # neither the wrong shape nor the right one: origin is the disqualifier,
    # so "fixing" the path would not have fixed anything
    verdict = _verify(candidate, UrlProvenance.LOCALLY_DERIVED, fetch=_reach)
    assert verdict.verified is False
    assert verdict.failure_reason == "not_provider_sourced:locally_derived"
    assert UrlProvenance.LOCALLY_DERIVED.is_provider_sourced() is False
    assert UrlProvenance.UNAVAILABLE.is_provider_sourced() is False


def test_url_text_is_never_identity_evidence():                     # item 11
    import inspect

    from src.publishing import canonical_url

    # the withdrawn heuristic is gone from the decision itself: no slug
    # parameter, and no path/title inspection anywhere in the executable code
    assert "slug" not in inspect.signature(verify_canonical_url).parameters
    body = inspect.getsource(canonical_url.verify_canonical_url)
    for heuristic in ("slug", "/post/", "/blog/", "title"):
        assert heuristic not in body


def test_a_provider_url_passes_even_when_its_path_carries_no_slug():  # item 12
    # identity came from the post-ID round trip; the path shape is the
    # provider's business and may be anything it serves
    opaque = f"{SITE}/a/9f3c1d2e"
    verdict = _verify(opaque)
    assert verdict.verified is True
    assert verdict.url == opaque


def test_bounded_retries_and_transport_failure():
    slept = []
    seen = []

    def flaky(url):
        seen.append(url)
        return (url, 200) if len(seen) == 2 else (url, 404)

    verdict = verify_canonical_url(
        url=LIVE_URL, provenance=UrlProvenance.PROVIDER_LOOKUP,
        expected_host=SITE, fetch=flaky, sleep=slept.append,
    )
    assert verdict.verified is True and verdict.attempts == 2
    assert len(slept) == 1

    dead = _verify(LIVE_URL, fetch=_gone)
    assert dead.attempts == MAX_ATTEMPTS == 3            # hard ceiling
    assert _verify(LIVE_URL, fetch=lambda _u: None).failure_reason == "unreachable"


def test_the_client_follows_redirects_rather_than_custom_3xx_logic():
    import inspect

    from src.publishing import canonical_url

    source = inspect.getsource(canonical_url._fetch_final)
    assert "allow_redirects=True" in source
    assert "max_redirects = MAX_REDIRECTS" in source
    assert "timeout=REQUEST_TIMEOUT_SECONDS" in source
    assert canonical_url.MAX_ATTEMPTS <= 5
    assert canonical_url.REQUEST_TIMEOUT_SECONDS <= 30


# ===========================================================================
# Entrypoint: fail closed (items 13, 14, 18)
# ===========================================================================


def _wix_result(url, provenance=UrlProvenance.PROVIDER_LOOKUP, lookup=None):
    result = PublishResult(
        platform="wix", status=PublishStatus.PUBLISHED,
        url=url, external_id=POST_ID, url_provenance=provenance,
    )
    result.provider_lookup = lookup if lookup is not None else _lookup(url=url)
    return result


def _live_run(tmp_path, *, wix_result, fetch=_reach, extra=None):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    wix, li = mock.MagicMock(), mock.MagicMock()
    wix.publish.return_value = wix_result
    li.publish.return_value = _make_ok_publish_result("linkedin")
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    del patches["verify_canonical_url"]                 # exercise the REAL gate
    real = gap.verify_canonical_url
    patches["verify_canonical_url"] = mock.MagicMock(
        side_effect=lambda **kw: real(**kw, fetch=fetch, sleep=lambda _s: None)
    )
    if extra:
        patches.update(extra)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.dict("os.environ", {"NB_WIX_SITE_BASE_URL": SITE}):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, wix, li, patches


def _results(tmp_path) -> dict:
    return json.loads(
        next(tmp_path.glob("*/runs/*/publication_results.json")).read_text()
    )


@pytest.mark.parametrize(
    "case, lookup, fetch, expected_reason",
    [
        # the provider never answered about the post
        ("lookup_failure",
         _lookup(returned_post_id="", url="", http_status=500,
                 provenance=UrlProvenance.UNAVAILABLE),
         _reach, "no_candidate_url"),
        # the provider answered about a DIFFERENT post
        ("post_id_mismatch",
         _lookup(returned_post_id="a-different-post"),
         _reach, "no_candidate_url"),
        # the provider knows the post but attached no URL to it
        ("missing_page_url",
         _lookup(url="", provenance=UrlProvenance.UNAVAILABLE,
                 local_candidate=DEFECT_URL),
         _reach, "no_candidate_url"),
        # the provider's own URL does not answer publicly
        ("unreachable_page_url", _lookup(url=DEFECT_URL), _gone, "http_404"),
    ],
)
def test_wix_success_with_a_broken_chain_blocks_linkedin(       # items 13, 14
    tmp_path, case, lookup, fetch, expected_reason
):
    # whichever link of the chain breaks, the outcome is identical: Wix stays
    # published and truthful, LinkedIn is never attempted
    view = lookup.as_result_view()
    result = _wix_result(view.url, view.url_provenance, lookup=lookup)
    code, wix, li, patches = _live_run(tmp_path, wix_result=result, fetch=fetch)

    assert wix.publish.called
    assert not li.publish.called
    results = _results(tmp_path)
    assert results["results"]["wix"]["status"] == "PUBLISHED"
    assert results["results"]["linkedin"]["status"] == "BLOCKED"
    assert expected_reason in results["results"]["linkedin"]["error_message"]
    assert results["completed"] is False
    assert code == 1
    assert results["canonical_url_verification"]["verified"] is False
    # and the audit preserves WHICH link broke, so the four cases stay
    # distinguishable long after the run
    audit = results["canonical_url_provider_lookup"]
    assert audit["requested_post_id"] == POST_ID
    assert audit["identity_ok"] is (case != "post_id_mismatch"
                                    and case != "lookup_failure")
    if case == "missing_page_url":
        assert audit["provider_page_url"] == ""
        assert audit["local_candidate"] == DEFECT_URL   # evidence, not canonical
    if case == "post_id_mismatch":
        assert audit["returned_post_id"] == "a-different-post"


def test_nothing_is_regenerated_when_the_chain_breaks(tmp_path):
    with mock.patch(
        "scripts.research.prepare_content.prepare_content_packages",
        side_effect=AssertionError("image generation was reached"),
    ):
        code, wix, li, patches = _live_run(
            tmp_path, wix_result=_wix_result(DEFECT_URL), fetch=_gone
        )
    assert code == 1
    assert patches["generate_article"].call_count == 1
    assert wix.publish.call_count == 1


def test_the_verified_provider_url_is_what_reaches_package_b(tmp_path):
    code, wix, li, patches = _live_run(
        tmp_path, wix_result=_wix_result(LIVE_URL), fetch=_reach
    )

    assert code == 0 and li.publish.called
    assert patches["bind_canonical_article_url"].call_args.args[1] == LIVE_URL
    assert patches["validate_social_lineage"].call_args.kwargs[
        "canonical_url"] == LIVE_URL
    results = _results(tmp_path)
    entry = results["results"]["linkedin"]
    assert entry["canonical_article_url"] == LIVE_URL
    # the audit chain reads end to end: published post X, asked for X, got
    # this PageUrl for X, it was reachable                        item 18
    lookup = results["canonical_url_provider_lookup"]
    assert lookup["requested_post_id"] == POST_ID
    assert lookup["returned_post_id"] == POST_ID
    assert lookup["identity_ok"] is True
    assert lookup["provider_page_url"] == LIVE_URL
    assert results["canonical_url_verification"]["verified"] is True
    # #196 chain untouched
    assert list(tmp_path.glob("*/runs/*/linkedin_final_preflight.json"))
    assert entry["published_package_digest"] and entry["derived_from_digest"]


# ===========================================================================
# Recovery (items 15, 16, 17)
# ===========================================================================


def test_recovery_re_resolves_from_the_provider_and_never_republishes(tmp_path):
    from types import SimpleNamespace

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    wix, li = mock.MagicMock(), mock.MagicMock()
    li.publish.return_value = _make_ok_publish_result("linkedin")
    # the prior run recorded the DEAD locally-derived URL; recovery must not
    # trust it, and must ask the provider again
    wix.lookup_canonical_url.return_value = _lookup()
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    patches["find_prior_wix_publication"] = mock.MagicMock(
        return_value=SimpleNamespace(
            match=SimpleNamespace(
                run_id="22222222-2222-4222-8222-222222222222",
                post_id=POST_ID, url=DEFECT_URL,
                url_provenance=UrlProvenance.LOCALLY_DERIVED,
            ),
            evidence_note=lambda: None,
        )
    )
    del patches["verify_canonical_url"]
    real = gap.verify_canonical_url
    patches["verify_canonical_url"] = mock.MagicMock(
        side_effect=lambda **kw: real(**kw, fetch=_reach, sleep=lambda _s: None)
    )
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.dict("os.environ", {"NB_WIX_SITE_BASE_URL": SITE}), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=AssertionError("image generation was reached")):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 0
    assert not wix.publish.called                     # item 16: no duplicate
    assert wix.lookup_canonical_url.called            # item 15: same contract
    assert wix.lookup_canonical_url.call_args.args[0] == POST_ID
    # the dead recorded URL was discarded in favour of the provider's answer
    assert patches["bind_canonical_article_url"].call_args.args[1] == LIVE_URL
    results = _results(tmp_path)
    assert results["results"]["wix"]["status"] == "REUSED"
    assert results["wix_url"] == LIVE_URL
    assert results["canonical_url_provider_lookup"]["identity_ok"] is True


def test_the_recovery_path_costs_no_model_or_image_call():      # item 17
    import inspect

    from src.publishing import canonical_url, wix

    for module in (canonical_url, inspect.getmodule(wix.WixPublisher)):
        source = inspect.getsource(module)
        for forbidden in ("llm_client", "chat(", "prepare_content"):
            assert forbidden not in source
