"""Issue #200: a guessed URL is not a canonical article URL.

Live run 32740322282 published a LinkedIn post whose canonical link returned
404. Two defects compounded: the provider was never asked for the URL (its
``URL`` fieldset is opt-in, so the response carried no ``url`` at all), and
the field is a ``PageUrl`` object that the code read as a string — so the
"provider-confirmed" branch could never have worked either. The run then
fell through to a locally constructed ``/blog/<slug>`` route while the site
serves ``/post/<slug>``, and every stage downstream trusted the guess.

These scenarios pin the corrected contract: ask the provider, read the
object it actually returns, and let nothing become canonical until its
origin is the provider AND it resolves to this post.
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
from src.publishing.wix import page_url_to_str
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_generate_and_publish import _make_ok_publish_result
from tests.test_research_artifact_lifecycle import ReadyProvider

SITE = "https://www.inneros.online"
SLUG = "the-faster-you-patch-the-income-gap-the-quicker-your-own-hands-become-the-choke-point"
#: what the site actually serves — proven by the live run
LIVE_URL = f"{SITE}/post/{SLUG}"
#: what the pipeline constructed and published a link to — proven 404
DEFECT_URL = f"{SITE}/blog/{SLUG}"


def _ok(_url):
    return 200


def _gone(_url):
    return 404


def _verify(url, provenance=UrlProvenance.PROVIDER_LOOKUP, *, probe=_ok, slug=SLUG):
    return verify_canonical_url(
        url=url, provenance=provenance, expected_host=SITE, slug=slug,
        status_probe=probe, sleep=lambda _s: None,
    )


# ===========================================================================
# The provider contract we got wrong (items 1, 2, 3)
# ===========================================================================


def test_the_provider_url_object_is_rendered_as_an_absolute_url():
    # the API types this field as PageUrl{base, path} — reading it as a
    # string is what silently produced nothing usable
    assert page_url_to_str({"base": SITE, "path": f"/post/{SLUG}"}) == LIVE_URL
    assert page_url_to_str({"base": SITE + "/", "path": f"post/{SLUG}"}) == LIVE_URL
    # defensive: a plain string is already the answer
    assert page_url_to_str(LIVE_URL) == LIVE_URL
    # nothing usable stays empty rather than becoming a stringified dict
    assert page_url_to_str(None) == ""
    assert page_url_to_str({"base": SITE}) == ""
    assert page_url_to_str({"path": "/post/x"}) == ""


def test_the_lookup_requests_the_url_fieldset():
    # the URL field is opt-in; without the fieldset the response has no url
    # at all, which is exactly what the live run recorded
    import inspect

    from src.publishing import wix

    source = inspect.getsource(wix._resolve_post_url)
    assert "fieldsets=" in source
    assert wix._URL_FIELDSET == "URL"


def test_a_provider_url_is_accepted_from_either_provider_path():
    # item 1: from the publish response …
    assert _verify(LIVE_URL, UrlProvenance.PROVIDER_CONFIRMED).verified
    # item 2: … or from the lookup by post ID
    assert _verify(LIVE_URL, UrlProvenance.PROVIDER_LOOKUP).verified


def test_a_locally_constructed_route_can_never_be_canonical():
    # item 3: even when it resolves, a local construction is not canonical —
    # origin is a separate obligation from reachability
    verdict = _verify(LIVE_URL, UrlProvenance.LOCALLY_DERIVED, probe=_ok)
    assert verdict.verified is False
    assert verdict.failure_reason == "not_provider_sourced:locally_derived"
    assert UrlProvenance.LOCALLY_DERIVED.is_provider_sourced() is False
    assert UrlProvenance.UNAVAILABLE.is_provider_sourced() is False


# ===========================================================================
# Verification (items 4, 5, 6, 19, 20)
# ===========================================================================


def test_the_live_defect_url_shape_is_rejected():
    # item 19: the exact URL the live run published a link to
    verdict = _verify(DEFECT_URL, probe=_gone)
    assert verdict.verified is False
    assert verdict.failure_reason == "http_404"
    assert verdict.attempts == MAX_ATTEMPTS


def test_the_live_valid_url_shape_is_accepted():
    # item 20: the shape the provider actually reports and the site serves —
    # accepted because the PROVIDER produced it, not because we like the path
    verdict = _verify(LIVE_URL, probe=_ok)
    assert verdict.verified is True
    assert verdict.http_status == 200
    assert verdict.attempts == 1
    assert verdict.url == LIVE_URL


def test_a_wrong_host_is_rejected():                                # item 5
    verdict = _verify(f"https://evil.example/post/{SLUG}", probe=_ok)
    assert verdict.verified is False
    assert verdict.failure_reason == "unexpected_host:evil.example"


def test_a_lookalike_host_is_rejected():
    verdict = _verify(f"https://www.inneros.online.evil.test/post/{SLUG}", probe=_ok)
    assert verdict.verified is False
    assert "unexpected_host" in verdict.failure_reason


def test_a_generic_site_200_that_is_not_this_post_is_rejected():     # item 6
    # the site root answers 200 all day; that proves nothing about the post
    assert _verify(SITE + "/", probe=_ok).failure_reason == "no_page_path"
    # and a real page that is not this post fails the identity check
    other = _verify(f"{SITE}/post/some-other-article", probe=_ok)
    assert other.verified is False
    assert other.failure_reason == "path_does_not_carry_post_slug"


def test_non_https_and_missing_candidates_are_rejected():
    assert _verify(f"http://www.inneros.online/post/{SLUG}").failure_reason == "not_https"
    assert _verify("").failure_reason == "no_candidate_url"


def test_resolution_is_retried_a_bounded_number_of_times():
    # propagation can lag; polling is never open-ended
    seen, slept = [], []
    def flaky(url):
        seen.append(url)
        return 200 if len(seen) == 2 else 404
    verdict = verify_canonical_url(
        url=LIVE_URL, provenance=UrlProvenance.PROVIDER_LOOKUP,
        expected_host=SITE, slug=SLUG,
        status_probe=flaky, sleep=slept.append,
    )
    assert verdict.verified is True and verdict.attempts == 2
    assert len(slept) == 1                       # one backoff, then success

    dead = _verify(LIVE_URL, probe=_gone)
    assert dead.attempts == MAX_ATTEMPTS == 3    # hard ceiling


def test_a_transport_failure_leaves_the_url_unverified():
    verdict = _verify(LIVE_URL, probe=lambda _u: None)
    assert verdict.verified is False
    assert verdict.failure_reason == "unreachable"


def test_the_verdict_is_persistable_evidence():                      # item 12
    audit = _verify(DEFECT_URL, probe=_gone).as_audit_dict()
    assert audit["verified"] is False
    assert audit["provenance"] == "provider_lookup"
    assert audit["failure_reason"] == "http_404"
    assert audit["url"] == DEFECT_URL


# ===========================================================================
# Entrypoint behaviour (items 7, 8, 9, 10, 11, 12, 17)
# ===========================================================================


def _wix_result(url, provenance=UrlProvenance.PROVIDER_LOOKUP, slug=SLUG):
    return PublishResult(
        platform="wix", status=PublishStatus.PUBLISHED,
        url=url, external_id="wix-post-id", url_provenance=provenance,
        provider_slug=slug,
    )


def _live_run(tmp_path, *, wix_result, probe=_ok):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    wix, li = mock.MagicMock(), mock.MagicMock()
    wix.publish.return_value = wix_result
    li.publish.return_value = _make_ok_publish_result("linkedin")
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    # exercise the REAL gate, with an injected network probe
    del patches["verify_canonical_url"]
    real = gap.verify_canonical_url
    patches["verify_canonical_url"] = mock.MagicMock(
        side_effect=lambda **kw: real(**kw, status_probe=probe, sleep=lambda _s: None)
    )
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.dict("os.environ", {"NB_WIX_SITE_BASE_URL": SITE}):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, wix, li, patches


def _results(tmp_path) -> dict:
    return json.loads(
        next(tmp_path.glob("*/runs/*/publication_results.json")).read_text()
    )


def test_an_unverifiable_canonical_url_blocks_linkedin(tmp_path):     # items 7, 9
    code, wix, li, _ = _live_run(
        tmp_path, wix_result=_wix_result(DEFECT_URL), probe=_gone
    )

    assert wix.publish.called
    assert not li.publish.called                                      # item 9
    results = _results(tmp_path)
    assert results["results"]["wix"]["status"] == "PUBLISHED"         # item 8
    assert results["wix_url"] == DEFECT_URL
    assert results["wix_post_id"] == "wix-post-id"
    assert results["results"]["linkedin"]["status"] == "BLOCKED"
    assert "http_404" in results["results"]["linkedin"]["error_message"]
    assert results["completed"] is False
    assert code == 1
    # the refused candidate and its provenance are preserved            item 12
    verification = results["canonical_url_verification"]
    assert verification["verified"] is False
    assert verification["url"] == DEFECT_URL
    assert verification["provenance"] == "provider_lookup"
    assert verification["failure_reason"] == "http_404"


def test_a_locally_derived_url_blocks_linkedin_even_when_reachable(tmp_path):
    code, wix, li, _ = _live_run(
        tmp_path,
        wix_result=_wix_result(DEFECT_URL, UrlProvenance.LOCALLY_DERIVED),
        probe=_ok,
    )

    assert wix.publish.called and not li.publish.called
    results = _results(tmp_path)
    assert results["results"]["wix"]["status"] == "PUBLISHED"
    assert "not_provider_sourced" in results["results"]["linkedin"]["error_message"]


def test_no_text_or_image_is_regenerated_when_the_url_fails(tmp_path):
    with mock.patch(
        "scripts.research.prepare_content.prepare_content_packages",
        side_effect=AssertionError("image generation was reached"),
    ):
        code, wix, li, patches = _live_run(
            tmp_path, wix_result=_wix_result(DEFECT_URL), probe=_gone
        )
    assert code == 1
    assert patches["generate_article"].call_count == 1   # no regeneration
    assert wix.publish.call_count == 1                   # no republication


def test_a_verified_url_is_exactly_what_is_bound_into_package_b(tmp_path):
    # items 10, 11, 17: the normal flow still works, and the URL bound into
    # the enriched package is the verified one
    code, wix, li, patches = _live_run(
        tmp_path, wix_result=_wix_result(LIVE_URL), probe=_ok
    )

    assert code == 0
    assert li.publish.called
    bind = patches["bind_canonical_article_url"]
    assert bind.call_args.args[1] == LIVE_URL                        # item 10
    lineage = patches["validate_social_lineage"]
    assert lineage.call_args.kwargs["canonical_url"] == LIVE_URL
    results = _results(tmp_path)
    entry = results["results"]["linkedin"]
    assert entry["status"] == "PUBLISHED"
    assert entry["canonical_article_url"] == LIVE_URL
    # #196 is intact: the final exact-package ALLOW was still persisted, and
    # the published package is still the one derived from the authorized
    # package. (Digest equality against the REAL preflight evaluator is
    # covered by tests/test_canonical_social_lineage.py; this harness stubs
    # the evaluator, so its artifact carries no verdict to compare.)  item 11
    assert list(tmp_path.glob("*/runs/*/linkedin_final_preflight.json"))
    assert entry["published_package_digest"]
    assert entry["derived_from_digest"]
    assert results["canonical_url_verification"]["verified"] is True  # item 12


# ===========================================================================
# Recovery (items 13, 14, 15, 16)
# ===========================================================================


def test_recovery_from_a_prior_wix_post_reverifies_without_republishing(tmp_path):
    from types import SimpleNamespace

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    wix, li = mock.MagicMock(), mock.MagicMock()   # wix must never publish
    li.publish.return_value = _make_ok_publish_result("linkedin")
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    patches["find_prior_wix_publication"] = mock.MagicMock(
        return_value=SimpleNamespace(
            match=SimpleNamespace(
                run_id="22222222-2222-4222-8222-222222222222",
                post_id="prior-wix-post", url=LIVE_URL,
                url_provenance=UrlProvenance.PROVIDER_LOOKUP,
            ),
            evidence_note=lambda: None,
        )
    )
    probed: list = []
    del patches["verify_canonical_url"]
    real = gap.verify_canonical_url
    patches["verify_canonical_url"] = mock.MagicMock(
        side_effect=lambda **kw: real(
            **kw, status_probe=lambda u: (probed.append(u), 200)[1],
            sleep=lambda _s: None,
        )
    )
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches), \
            mock.patch.dict("os.environ", {"NB_WIX_SITE_BASE_URL": SITE}), \
            mock.patch("scripts.research.prepare_content.prepare_content_packages",
                       side_effect=AssertionError("image generation was reached")):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 0
    assert not wix.publish.called                       # item 13: no duplicate
    assert probed == [LIVE_URL]                         # item 14: re-verified
    assert li.publish.called
    results = _results(tmp_path)
    assert results["results"]["wix"]["status"] == "REUSED"
    assert results["canonical_url_verification"]["verified"] is True


def test_recovery_adds_no_model_or_image_calls():                # items 15, 16
    # the verification path is pure HTTP: no model client is importable from
    # it, and the entrypoint's image step is unreachable once a channel is
    # blocked (proven above by the exploding image patch)
    import inspect

    from src.publishing import canonical_url

    source = inspect.getsource(canonical_url)
    for forbidden in ("chat", "llm_client", "openai", "prepare_content"):
        assert forbidden not in source


def test_the_probe_is_bounded_and_uses_head_before_get():
    import inspect

    from src.publishing import canonical_url

    source = inspect.getsource(canonical_url._http_status)
    assert '("head", "get")' in source
    assert "timeout=REQUEST_TIMEOUT_SECONDS" in source
    assert canonical_url.REQUEST_TIMEOUT_SECONDS <= 30
    assert canonical_url.MAX_ATTEMPTS <= 5
