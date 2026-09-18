"""Issue #196: one canonical article; social distributes it, never bypasses it.

The authorized R1 lineage:

    original external source(s)
      → Never Blank canonical article   (owns the external-source links)
        → social derivatives            (point at the published article)

These scenarios prove the split responsibilities: the canonical article keeps
its undiminished original-source transparency; the LinkedIn derivative no
longer carries an original-source URL and instead receives the REAL published
Wix URL, bound deterministically after Wix succeeds and proven by a
zero-LLM lineage gate; Wix gates social publication fail-closed; and accepted
content is preserved the moment acceptance says ACCEPT, so a later gate can
no longer erase what the run wrote (live run 32666861632).
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial.platform_composer import (
    CLOSING_BRANDED_ECHO_THEN_SOURCES,
    CLOSING_INVITATION_LAST,
    CompositionRejected,
    _build_user_prompt,
    _effective_echo_mode,
    _validate_branded_echo_final,
)
from src.editorial.source_transparency import (
    SocialLineageError,
    SourceTransparencyError,
    validate_social_lineage,
    validate_source_transparency,
)
from src.publishing import formatting
from src.publishing.package import (
    LinkedInPublicationPackage,
    LinkedInPublicationTarget,
    PublicationPackageError,
    bind_canonical_article_url,
)
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_generate_and_publish import (
    _make_ok_publish_result,
    _test_configuration_identity,
)
from tests.test_monday_stream import (
    FIXTURE_SOURCE_TITLE,
    FIXTURE_SOURCE_URL,
    MONDAY_ROLE,
    UNATTRIBUTED_BODY,
    _research_artifact,
    _run_with_role,
)
from tests.test_research_artifact_lifecycle import ReadyProvider

CANONICAL_URL = "https://www.inneros.online/post/the-kitchen-factory"


# ===========================================================================
# 1–2. The split: the article keeps its obligation; LinkedIn loses the old one
# ===========================================================================


def test_the_canonical_article_still_requires_original_source_transparency():
    with pytest.raises(SourceTransparencyError):
        validate_source_transparency(
            article_body=UNATTRIBUTED_BODY, research=_research_artifact()
        )


def test_the_transparency_gate_no_longer_judges_a_linkedin_surface():
    # the LinkedIn obligation moved to validate_social_lineage; the article
    # gate cannot even be handed a social body any more
    assert "linkedin_body" not in inspect.signature(
        validate_source_transparency
    ).parameters


# ===========================================================================
# Deterministic canonical-link enrichment (zero LLM)
# ===========================================================================


def _linkedin_package(body: str = "Post body.\n\nNever Blank: the echo.") -> (
        LinkedInPublicationPackage):
    from src.publishing.package import article_digest

    return LinkedInPublicationPackage(
        run_id="11111111-1111-4111-8111-111111111111",
        signal_id="sig-196",
        configuration_identity=_test_configuration_identity(),
        source_article_digest=article_digest("the accepted article"),
        linkedin_body=body,
        linkedin_image_url=None,
        target=LinkedInPublicationTarget(account_id="acct-1"),
    )


def test_binding_inserts_exactly_the_wix_result_url():         # items 5–6
    enriched = bind_canonical_article_url(_linkedin_package(), CANONICAL_URL)
    assert CANONICAL_URL in enriched.linkedin_body
    assert enriched.canonical_article_url == CANONICAL_URL
    # and the assembled body carries no other URL
    validate_social_lineage(
        social_body=enriched.linkedin_body, canonical_url=CANONICAL_URL
    )


def test_binding_keeps_a_trailing_hashtag_line_last():
    enriched = bind_canonical_article_url(
        _linkedin_package("Body.\n\nNever Blank: echo.\n\n#NeverBlank #CustomerTrust"),
        CANONICAL_URL,
    )
    lines = [ln for ln in enriched.linkedin_body.splitlines() if ln.strip()]
    assert lines[-1] == "#NeverBlank #CustomerTrust"
    assert lines[-2] == CANONICAL_URL
    assert lines[-3] == formatting.CANONICAL_LINK_INVITATION


def test_binding_refuses_a_missing_url():
    with pytest.raises(PublicationPackageError):
        bind_canonical_article_url(_linkedin_package(), "")


def test_binding_and_lineage_validation_make_zero_llm_calls():  # item 8
    with mock.patch("src.utils.llm_client.chat",
                    side_effect=AssertionError("LLM was called")), \
         mock.patch("src.utils.llm_client.chat_parsed",
                    side_effect=AssertionError("LLM was called")):
        enriched = bind_canonical_article_url(_linkedin_package(), CANONICAL_URL)
        validate_social_lineage(
            social_body=enriched.linkedin_body, canonical_url=CANONICAL_URL
        )


def test_the_authorized_package_is_not_mutated():
    package = _linkedin_package()
    before = package.package_digest()
    bind_canonical_article_url(package, CANONICAL_URL)
    assert package.package_digest() == before
    assert package.canonical_article_url is None


# ===========================================================================
# 7, 9–10. The social lineage gate
# ===========================================================================


def test_a_body_without_the_canonical_url_fails_lineage():      # item 7
    with pytest.raises(SocialLineageError):
        validate_social_lineage(
            social_body="A post with no link at all.",
            canonical_url=CANONICAL_URL,
        )


def test_a_missing_canonical_url_fails_lineage():               # item 7
    with pytest.raises(SocialLineageError):
        validate_social_lineage(social_body="Anything.", canonical_url="")


def test_a_wrong_destination_fails_lineage():                   # item 7
    body = f"Read on: https://evil.example/post/the-kitchen-factory"
    with pytest.raises(SocialLineageError):
        validate_social_lineage(social_body=body, canonical_url=CANONICAL_URL)


def test_a_competing_original_source_url_fails_lineage():       # item 9
    body = (
        f"Post.\n\n{CANONICAL_URL}\n\nSource: {FIXTURE_SOURCE_URL}"
    )
    with pytest.raises(SocialLineageError) as exc:
        validate_social_lineage(social_body=body, canonical_url=CANONICAL_URL)
    assert "competing" in str(exc.value)


def test_naming_the_original_publisher_is_fine():               # item 10
    body = (
        f"{FIXTURE_SOURCE_TITLE} profiled a founder who rebuilt at home.\n\n"
        f"Never Blank: the echo.\n\nWant to read more?\n{CANONICAL_URL}"
    )
    validate_social_lineage(social_body=body, canonical_url=CANONICAL_URL)


def test_an_equivalent_rendering_of_the_same_url_is_recognised():
    body = f"Read: HTTPS://WWW.INNEROS.ONLINE/post/the-kitchen-factory/"
    validate_social_lineage(social_body=body, canonical_url=CANONICAL_URL)


# ===========================================================================
# 11–12. Echo and title invariance
# ===========================================================================


def test_the_branded_contract_upgrades_the_social_echo_to_verbatim():
    assert _effective_echo_mode("medium", CLOSING_BRANDED_ECHO_THEN_SOURCES) == (
        "verbatim_final"
    )
    # roles that declare nothing keep the format default — no global change
    assert _effective_echo_mode("medium", CLOSING_INVITATION_LAST) == "adapt"
    assert _effective_echo_mode("long", CLOSING_BRANDED_ECHO_THEN_SOURCES) == "full"


def test_the_social_prompt_demands_the_exact_echo_under_the_contract():
    structured = {"echo_line": "The echo travels whole."}
    prompt = _build_user_prompt(
        structured, "medium", "none",
        closing_contract=CLOSING_BRANDED_ECHO_THEN_SOURCES,
    )
    assert "word for word" in prompt
    assert "never adapted" in prompt
    assert "Do not write any URL" in prompt
    assert "[adapt]" not in prompt


def test_wix_echo_equals_linkedin_echo_verbatim():              # item 11
    echo = "Compressed to a kitchen, a business measures time in batches."
    article_body = (
        f"Article prose.\n\n**Never Blank:** {echo}\n\nSources:\n- entry"
    )
    social_body = f"Post prose, its own rhythm.\n\nNever Blank: {echo}"
    # the same echo string satisfies both surfaces' structural validators
    assert article_body.count(echo) == 1 and social_body.count(echo) == 1
    _validate_branded_echo_final(social_body, echo, "medium")


def test_an_adapted_echo_is_rejected_on_the_social_surface():   # item 11
    echo = "Compressed to a kitchen, a business measures time in batches."
    adapted = "Squeezed into a kitchen, the business counts time in batches."
    with pytest.raises(CompositionRejected):
        _validate_branded_echo_final(
            f"Post.\n\nNever Blank: {adapted}", echo, "medium"
        )


def test_nothing_may_follow_the_social_echo_in_the_composed_body():
    echo = "The echo."
    with pytest.raises(CompositionRejected):
        _validate_branded_echo_final(
            f"Post.\n\nNever Blank: {echo}\nP.S. one more thought", echo, "medium"
        )


def test_social_formats_cannot_introduce_a_title():             # item 12
    # the composer contract: only the blog format returns a title …
    composer_source = Path("src/editorial/platform_composer.py").read_text()
    assert 'Other formats return "title": null.' in composer_source
    # … and the entrypoint reads a title from the long format alone
    entry_source = Path("scripts/generate_and_publish.py").read_text()
    assert 'platforms["long"].get("title")' in entry_source
    for other in ("medium", "reading", "instagram", "short"):
        assert f'platforms["{other}"].get("title")' not in entry_source
        assert f'platforms["{other}"]["title"]' not in entry_source


# ===========================================================================
# 3–4, 17. Wix gates LinkedIn (entrypoint behaviour)
# ===========================================================================


def _live_run(tmp_path, *, wix_publisher, linkedin_publisher):
    argv, patches = _entry_patches(tmp_path, dry_run=False)
    patches["WixPublisher"] = mock.MagicMock(return_value=wix_publisher)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=linkedin_publisher)
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)
    return code, patches


def _publication_results(tmp_path) -> dict:
    records = list(tmp_path.glob("*/runs/*/publication_results.json"))
    assert len(records) == 1
    return json.loads(records[0].read_text())


def test_wix_failure_means_linkedin_is_not_attempted(tmp_path):  # item 3
    wix = mock.MagicMock()
    wix.publish.side_effect = RuntimeError("wix is down")
    li = mock.MagicMock()
    code, patches = _live_run(tmp_path, wix_publisher=wix, linkedin_publisher=li)

    assert not li.publish.called
    results = _publication_results(tmp_path)
    assert results["results"]["wix"]["status"] == "FAILED"
    assert results["results"]["linkedin"]["status"] == "BLOCKED"
    assert "no verified canonical article URL" in (
        results["results"]["linkedin"]["error_message"]
    )
    assert results["wix_url"] == ""
    assert code == 1  # a run that published nothing it intended is not complete


def test_a_wix_result_without_a_url_blocks_linkedin(tmp_path):   # item 4
    wix = mock.MagicMock()
    ok_no_url = _make_ok_publish_result("wix")
    ok_no_url.url = ""
    ok_no_url.to_dict.return_value = {**ok_no_url.to_dict.return_value, "url": ""}
    wix.publish.return_value = ok_no_url
    li = mock.MagicMock()
    _, patches = _live_run(tmp_path, wix_publisher=wix, linkedin_publisher=li)

    assert not li.publish.called
    results = _publication_results(tmp_path)
    assert results["results"]["linkedin"]["status"] == "BLOCKED"


def test_wix_success_hands_its_exact_url_to_the_linkedin_path(tmp_path):  # 5–6
    wix = mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li = mock.MagicMock()
    li.publish.return_value = _make_ok_publish_result("linkedin")
    code, patches = _live_run(tmp_path, wix_publisher=wix, linkedin_publisher=li)

    assert code == 0
    bind = patches["bind_canonical_article_url"]
    lineage = patches["validate_social_lineage"]
    assert bind.call_count == 1
    assert bind.call_args.args[1] == "https://example.com/wix"   # the REAL result
    assert lineage.call_count == 1
    assert lineage.call_args.kwargs["canonical_url"] == "https://example.com/wix"
    assert li.publish.called
    # the object the publisher received is exactly what the binder returned
    # (the harness binder is identity, so: the package it was handed)
    assert li.publish.call_args.args[0] is bind.call_args.args[0]


def test_wix_success_linkedin_failure_preserves_the_wix_result(tmp_path):  # 17
    wix = mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li = mock.MagicMock()
    li.publish.side_effect = RuntimeError("zernio 500")
    code, _ = _live_run(tmp_path, wix_publisher=wix, linkedin_publisher=li)

    results = _publication_results(tmp_path)
    assert results["results"]["wix"]["status"] == "PUBLISHED"
    assert results["wix_url"] == "https://example.com/wix"
    assert results["wix_post_id"] == "wix-post-id"
    assert results["results"]["linkedin"]["status"] == "FAILED"
    assert results["completed"] is False
    assert code == 1


def test_a_reused_wix_publication_still_feeds_linkedin_its_url(tmp_path):  # 18
    from types import SimpleNamespace

    from src.publishing.result import UrlProvenance

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    wix = mock.MagicMock()   # must never be asked to publish again
    li = mock.MagicMock()
    li.publish.return_value = _make_ok_publish_result("linkedin")
    # #200: the reuse path re-asks the provider for the known post rather
    # than trusting the recorded URL
    from src.publishing.wix import ProviderUrlLookup

    wix.lookup_canonical_url.side_effect = lambda post_id, *, site_id: (
        ProviderUrlLookup(post_id, post_id, CANONICAL_URL,
                          UrlProvenance.PROVIDER_LOOKUP, 200)
    )
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    patches["find_prior_wix_publication"] = mock.MagicMock(
        return_value=SimpleNamespace(
            match=SimpleNamespace(
                run_id="22222222-2222-4222-8222-222222222222",
                post_id="prior-wix-post",
                url=CANONICAL_URL,
                url_provenance=UrlProvenance.PROVIDER_CONFIRMED,
            ),
            evidence_note=lambda: None,
        )
    )
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert code == 0
    assert not wix.publish.called                      # no duplicate Wix post
    assert li.publish.called                           # social still distributed
    assert patches["bind_canonical_article_url"].call_args.args[1] == CANONICAL_URL
    results = _publication_results(tmp_path)
    assert results["results"]["wix"]["status"] == "REUSED"
    assert results["wix_url"] == CANONICAL_URL


def test_the_linkedin_body_no_longer_receives_the_original_source_line(tmp_path):
    # item 9 at the entrypoint: the only source_line application left is the
    # blog's markdown Sources footer — nothing appends a bare original URL to
    # the LinkedIn text any more
    wix = mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li = mock.MagicMock()
    li.publish.return_value = _make_ok_publish_result("linkedin")
    _, patches = _live_run(tmp_path, wix_publisher=wix, linkedin_publisher=li)

    styles = [
        call.args[2] for call in patches["formatting"].source_line.call_args_list
    ]
    # one source-line application remains: the blog's markdown Sources
    # footer. The non-R1 Facebook body is not composed outside the owner-
    # controlled preview, and an empty body never receives a footer.
    assert styles == ["blog_markdown"]
    # and the LinkedIn assembly no longer applies one at all
    entry_source = Path("scripts/generate_and_publish.py").read_text()
    li_block = entry_source.split("linkedin_text   = formatting.append_hashtags(")[1]
    li_block = li_block.split("facebook_text")[0]
    assert "source_line" not in li_block


# ===========================================================================
# 13–16. Accepted-content preservation
# ===========================================================================


def _unattributed_monday_article() -> dict:
    import copy

    from tests.test_generate_and_publish import _FAKE_ARTICLE

    article = copy.deepcopy(_FAKE_ARTICLE)
    article["platforms"]["long"]["body"] = UNATTRIBUTED_BODY
    article["platforms"]["medium"]["body"] = "A LinkedIn body."
    return article


def test_accepted_content_survives_a_transparency_block(tmp_path):  # item 13
    code, patches, _ = _run_with_role(
        tmp_path, MONDAY_ROLE, _unattributed_monday_article()
    )

    assert code == 1                                    # the gate still blocks
    records = list(tmp_path.glob("*/runs/*/accepted_composition.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record["content"]["article_body"] == UNATTRIBUTED_BODY
    assert record["content"]["linkedin_body"] == "A LinkedIn body."
    assert record["content"]["echo"]
    assert record["content"]["title"]
    # …while the run still produced no publishable package
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_the_preserved_record_is_declared_unpublishable(tmp_path):  # item 14
    _run_with_role(tmp_path, MONDAY_ROLE, _unattributed_monday_article())
    record = json.loads(
        next(tmp_path.glob("*/runs/*/accepted_composition.json")).read_text()
    )
    assert record["publishable"] is False
    assert record["artifact_kind"] == "accepted_composition"
    assert "NOT publishable" in record["notice"]


def test_the_preserved_record_is_not_canonical():                   # item 15
    from src.reporting.run_report import CANONICAL_ARTIFACTS

    assert "accepted_composition.json" not in CANONICAL_ARTIFACTS
    assert not any("accepted_composition" in name for name in CANONICAL_ARTIFACTS)


def test_from_package_cannot_consume_the_preserved_record():        # item 16
    # the reuse path loads generated.json and only generated.json
    loader = inspect.getsource(gap.load_run_generated)
    assert "generated.json" in loader
    assert "accepted_composition" not in loader
    # and no loader for the record exists at all — it is write-only evidence
    import src.artifacts as artifacts

    assert not any(
        name.startswith("load") and "accepted_composition" in name
        for name in dir(artifacts)
    )


def test_a_fully_successful_run_also_preserves_its_acceptance(tmp_path):
    code, patches, _ = _run_with_role(tmp_path, MONDAY_ROLE)
    assert code == 0
    assert len(list(tmp_path.glob("*/runs/*/accepted_composition.json"))) == 1


# ===========================================================================
# Final exact-package authorization (#196 review correction)
#
# The trust contract: exact frozen package → exact-package ALLOW → external
# side effect. The enriched package B is a different frozen package from the
# preflight-authorized A, so B receives its own persisted ALLOW — from the
# same preflight machinery — before the LinkedIn publisher is called, and
# the digest handed to the publisher must equal the digest that ALLOW names.
# ===========================================================================


def test_the_enriched_package_is_a_different_frozen_package():
    package = _linkedin_package()
    enriched = bind_canonical_article_url(package, CANONICAL_URL)
    assert enriched.package_digest() != package.package_digest()


def test_the_enriched_package_receives_its_own_preflight_verdict(tmp_path):
    wix = mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li = mock.MagicMock()
    li.publish.return_value = _make_ok_publish_result("linkedin")
    code, patches = _live_run(tmp_path, wix_publisher=wix, linkedin_publisher=li)

    assert code == 0
    preflight_calls = patches["evaluate_publication_preflight"].call_args_list
    # once for the run's channel packages, once for the enriched package
    assert len(preflight_calls) == 2
    final_outcomes = preflight_calls[1].kwargs["channel_outcomes"]
    assert len(final_outcomes) == 1
    assert final_outcomes[0].channel == "linkedin"
    # the package judged by the final verdict IS the one the binder returned
    # and IS the one the publisher was handed
    assert final_outcomes[0].package is li.publish.call_args.args[0]
    # and the persisted ALLOW exists as its own run artifact
    assert len(list(tmp_path.glob("*/runs/*/linkedin_final_preflight.json"))) == 1


def test_the_final_allow_is_persisted_before_the_publisher_is_called(tmp_path):
    # a publisher that fails AFTER the final ALLOW leaves the verdict behind:
    # persistence cannot depend on the side effect it authorizes
    wix = mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li = mock.MagicMock()
    li.publish.side_effect = RuntimeError("zernio 500")
    code, _ = _live_run(tmp_path, wix_publisher=wix, linkedin_publisher=li)

    assert code == 1
    assert len(list(tmp_path.glob("*/runs/*/linkedin_final_preflight.json"))) == 1
    results = _publication_results(tmp_path)
    assert results["results"]["linkedin"]["status"] == "FAILED"


def test_a_final_preflight_block_stops_the_publisher(tmp_path):
    from types import SimpleNamespace

    from src.publishing.preflight import PreflightDisposition

    from tests.test_generate_and_publish import _fake_preflight

    calls = []

    def blocking_second_pass(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _fake_preflight(**kwargs)
        verdict = SimpleNamespace(
            channel="linkedin",
            disposition=PreflightDisposition.BLOCK,
            blocking_reasons=(),
            package_digest=None,
        )
        return SimpleNamespace(
            run_disposition=PreflightDisposition.ALLOW,
            run_blocking_reasons=(),
            channels=(verdict,),
            verdict_for={"linkedin": verdict}.get,
            model_dump_json=lambda **_: "{}",
        )

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    wix = mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li = mock.MagicMock()
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    patches["evaluate_publication_preflight"] = mock.MagicMock(
        side_effect=blocking_second_pass
    )
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert not li.publish.called
    results = _publication_results(tmp_path)
    assert results["results"]["linkedin"]["status"] == "BLOCKED"
    assert "final exact-package preflight" in (
        results["results"]["linkedin"]["error_message"]
    )
    assert code == 1


def test_a_digest_mismatch_with_the_final_verdict_fails_closed(tmp_path):
    from types import SimpleNamespace

    from src.publishing.preflight import PreflightDisposition

    from tests.test_generate_and_publish import _fake_preflight

    calls = []

    def wrong_digest_second_pass(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _fake_preflight(**kwargs)
        verdict = SimpleNamespace(
            channel="linkedin",
            disposition=PreflightDisposition.ALLOW,
            blocking_reasons=(),
            package_digest="sha256:" + "f" * 64,   # names a different package
        )
        return SimpleNamespace(
            run_disposition=PreflightDisposition.ALLOW,
            run_blocking_reasons=(),
            channels=(verdict,),
            verdict_for={"linkedin": verdict}.get,
            model_dump_json=lambda **_: "{}",
        )

    argv, patches = _entry_patches(tmp_path, dry_run=False)
    wix = mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li = mock.MagicMock()
    patches["WixPublisher"] = mock.MagicMock(return_value=wix)
    patches["LinkedInPublisher"] = mock.MagicMock(return_value=li)
    patches["evaluate_publication_preflight"] = mock.MagicMock(
        side_effect=wrong_digest_second_pass
    )
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator)

    assert not li.publish.called
    results = _publication_results(tmp_path)
    assert results["results"]["linkedin"]["status"] == "FAILED"
    assert "does not match" in results["results"]["linkedin"]["error_message"]
    assert code == 1


def test_the_real_machinery_binds_the_allow_to_the_enriched_digest():
    # the invariant with the REAL preflight verdict model: the ALLOW names
    # exactly the enriched package's digest
    from src.publishing.preflight import ChannelPackageOutcome

    enriched = bind_canonical_article_url(_linkedin_package(), CANONICAL_URL)
    outcome = ChannelPackageOutcome.valid("linkedin", enriched)
    assert outcome.package.package_digest() == enriched.package_digest()


def test_publication_results_carry_the_lineage_evidence(tmp_path):
    wix = mock.MagicMock()
    wix.publish.return_value = _make_ok_publish_result("wix")
    li = mock.MagicMock()
    li.publish.return_value = _make_ok_publish_result("linkedin")
    _, patches = _live_run(tmp_path, wix_publisher=wix, linkedin_publisher=li)

    entry = _publication_results(tmp_path)["results"]["linkedin"]
    published_package = li.publish.call_args.args[0]
    assert entry["published_package_digest"] == published_package.package_digest()
    assert entry["derived_from_digest"]      # the run-preflight-authorized A
    assert entry["canonical_article_url"] == "https://example.com/wix"


def test_a_linkedin_entry_blocked_before_enrichment_carries_no_evidence(tmp_path):
    wix = mock.MagicMock()
    wix.publish.side_effect = RuntimeError("wix is down")
    li = mock.MagicMock()
    _, _ = _live_run(tmp_path, wix_publisher=wix, linkedin_publisher=li)

    entry = _publication_results(tmp_path)["results"]["linkedin"]
    assert "published_package_digest" not in entry
    assert "canonical_article_url" not in entry
    # and no final verdict was fabricated for a package that never existed
    assert not list(tmp_path.glob("*/runs/*/linkedin_final_preflight.json"))
