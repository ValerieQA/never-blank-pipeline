"""Issue #100 / Story #17: canonical Wix and LinkedIn publication packages.

The package is the final internal contract between accepted run evidence and
an external publishing adapter: strict, frozen, run-bound, channel-specific,
composed only from canonical accepted artifacts, free from credentials, and
impossible to assemble across runs. These tests exercise the real builders
and models directly with real canonical inputs (real visual passports, real
composition records) — no entrypoint harness stand-ins.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.editorial.linkedin_composition import (
    LinkedInCompositionRecord,
    LinkedInCompositionStatus,
    article_digest,
)
from src.publishing.package import (
    LinkedInPublicationPackage,
    LinkedInPublicationTarget,
    PublicationPackageError,
    WixPublicationPackage,
    WixPublicationTarget,
    build_linkedin_publication_package,
    build_wix_publication_package,
    canonical_slug,
)
from src.strategy.execution_context import ConfigurationIdentity
from src.visual.contract import (
    build_visual_assets_record,
    reuse_visual_assets_record,
)
from tests.test_linkedin_composition import ARTICLE_BODY, _native_linkedin_body
from tests.test_visual_contract import DESIGN, _pimgs

SIG = "sig-package-001"
RUN = "run-generation-001"
PUB_RUN = "run-publication-002"
HEADLINE = "Trust Compounds When Presence Is Consistent"

CONFIG = ConfigurationIdentity(
    schema_version="1.0",
    configuration_id="cfg-package",
    configuration_version="3",
    configuration_hash="sha256:" + "a" * 64,
)
FOREIGN_CONFIG = ConfigurationIdentity(
    schema_version="1.0",
    configuration_id="cfg-foreign",
    configuration_version="9",
    configuration_hash="sha256:" + "b" * 64,
)

WIX_TARGET = WixPublicationTarget(
    site_id="site-11111111",
    owner_member_id="member-2222",
    category_ids=("cat-1",),
    tag_ids=("tag-1", "tag-2"),
)
LI_TARGET = LinkedInPublicationTarget(account_id="zernio-account-3333")


def _generated(**overrides) -> dict:
    data = {
        "run_id": RUN,
        "signal_id": SIG,
        "headline": HEADLINE,
        "blog_article": ARTICLE_BODY,
        "linkedin_post": _native_linkedin_body(),
        "configuration_identity": CONFIG.model_dump(),
    }
    data.update(overrides)
    return data


def _visual(tmp_path, *, with_linkedin=True, run_id=RUN, article_body=ARTICLE_BODY):
    return build_visual_assets_record(
        _pimgs(tmp_path, with_linkedin=with_linkedin),
        run_id=run_id,
        signal_id=SIG,
        article_body=article_body,
        design_version=DESIGN,
    )


def _composition(**overrides) -> dict:
    body = _native_linkedin_body()
    data = {
        "run_id": RUN,
        "signal_id": SIG,
        "source_article_digest": article_digest(ARTICLE_BODY),
        "configuration_identity": CONFIG.model_dump(),
        "strategy_id": "strategy-package",
        "strategy_version": "3",
        "composition_rules_version": "linkedin-medium-native/1.0",
        "linkedin_body": body,
        "word_count": len(body.split()),
        "status": "accepted",
    }
    data.update(overrides)
    return data


def _build_wix(tmp_path, **overrides):
    kwargs = dict(
        run_id=RUN,
        signal_id=SIG,
        configuration_identity=CONFIG,
        generated=_generated(),
        visual_record=_visual(tmp_path),
        target=WIX_TARGET,
    )
    kwargs.update(overrides)
    return build_wix_publication_package(**kwargs)


def _build_linkedin(tmp_path, **overrides):
    kwargs = dict(
        run_id=RUN,
        signal_id=SIG,
        configuration_identity=CONFIG,
        generated=_generated(),
        linkedin_composition=_composition(),
        visual_record=_visual(tmp_path),
        target=LI_TARGET,
    )
    kwargs.update(overrides)
    return build_linkedin_publication_package(**kwargs)


# ── Valid packages from one canonical run ────────────────────────────────────


def test_valid_wix_package_from_canonical_run(tmp_path):
    package = _build_wix(tmp_path)
    assert package.channel == "wix"
    assert package.run_id == RUN
    assert package.title == HEADLINE
    assert package.slug == canonical_slug(HEADLINE)
    assert package.body_markdown == ARTICLE_BODY
    assert package.source_article_digest == article_digest(ARTICLE_BODY)
    assert package.cover_image_url.startswith("https://")
    assert package.target == WIX_TARGET
    assert package.package_digest().startswith("sha256:")


def test_valid_linkedin_package_from_canonical_run(tmp_path):
    package = _build_linkedin(tmp_path)
    assert package.channel == "linkedin"
    assert package.run_id == RUN
    assert package.linkedin_body == _native_linkedin_body()
    assert package.source_article_digest == article_digest(ARTICLE_BODY)
    assert package.linkedin_image_url == "https://res.cloudinary.com/nb/linkedin.png"
    assert package.target == LI_TARGET


def test_valid_reuse_publication_packages(tmp_path):
    """--from-package: passport belongs to the publication run, generated to origin."""

    source_visual = _visual(tmp_path)
    reuse_record = reuse_visual_assets_record(
        source_visual.model_dump(mode="json"),
        source_run_id=RUN,
        publication_run_id=PUB_RUN,
        article_body=ARTICLE_BODY,
    )
    wix = _build_wix(tmp_path, run_id=PUB_RUN, visual_record=reuse_record)
    assert wix.run_id == PUB_RUN
    assert wix.body_markdown == ARTICLE_BODY
    linkedin = _build_linkedin(tmp_path, run_id=PUB_RUN, visual_record=reuse_record)
    assert linkedin.run_id == PUB_RUN
    assert linkedin.linkedin_body == _native_linkedin_body()


# ── Visual semantics (Story #15) ─────────────────────────────────────────────


def test_wix_package_rejects_missing_required_visual(tmp_path):
    with pytest.raises(PublicationPackageError, match="visual passport is missing"):
        _build_wix(tmp_path, visual_record=None)


def test_linkedin_package_permits_genuinely_absent_optional_visual(tmp_path):
    package = _build_linkedin(
        tmp_path, visual_record=_visual(tmp_path, with_linkedin=False)
    )
    assert package.linkedin_image_url is None


def test_linkedin_package_rejects_invalid_attempted_visual(tmp_path):
    """An attempted-but-failed LinkedIn visual never becomes a silent text-only
    package: the failure is rejected upstream by the Story #15 gate, so no
    passport exists and package construction fails closed."""

    from src.visual.contract import VisualGateError

    with pytest.raises(VisualGateError):
        build_visual_assets_record(
            _pimgs(tmp_path, linkedin_upload_failed=True),
            run_id=RUN,
            signal_id=SIG,
            article_body=ARTICLE_BODY,
            design_version=DESIGN,
        )
    with pytest.raises(PublicationPackageError, match="visual passport is missing"):
        _build_linkedin(tmp_path, visual_record=None)


# ── Cross-run substitution ───────────────────────────────────────────────────


def test_cross_run_article_substitution_fails(tmp_path):
    foreign_generated = _generated(run_id="run-other-777")
    for build, extra in (
        (_build_wix, {}),
        (_build_linkedin, {}),
    ):
        with pytest.raises(PublicationPackageError, match="cross-run substitution"):
            build(tmp_path, generated=foreign_generated, **extra)


def test_cross_run_visual_substitution_fails(tmp_path):
    foreign_visual = _visual(tmp_path, run_id="run-other-777")
    with pytest.raises(PublicationPackageError, match="different publication run"):
        _build_wix(tmp_path, visual_record=foreign_visual)
    with pytest.raises(PublicationPackageError, match="different publication run"):
        _build_linkedin(tmp_path, visual_record=foreign_visual)


def test_visual_from_different_article_fails(tmp_path):
    other_article = ARTICLE_BODY + "\n\nAn appended paragraph changes the digest."
    visual_of_other = _visual(tmp_path, article_body=other_article)
    with pytest.raises(PublicationPackageError, match="not produced from the accepted article"):
        _build_wix(tmp_path, visual_record=visual_of_other)


def test_reuse_package_with_foreign_origin_fails(tmp_path):
    """Publication-run passport whose origin is NOT the generated artifact's run."""

    source_visual = _visual(tmp_path, run_id="run-other-777")
    reuse_record = reuse_visual_assets_record(
        source_visual.model_dump(mode="json"),
        source_run_id="run-other-777",
        publication_run_id=PUB_RUN,
        article_body=ARTICLE_BODY,
    )
    with pytest.raises(PublicationPackageError, match="origin run"):
        _build_wix(tmp_path, run_id=PUB_RUN, visual_record=reuse_record)


def test_linkedin_composition_from_other_run_fails(tmp_path):
    with pytest.raises(PublicationPackageError, match="cross-run substitution"):
        _build_linkedin(
            tmp_path, linkedin_composition=_composition(run_id="run-other-777")
        )


def test_linkedin_composition_against_other_article_fails(tmp_path):
    with pytest.raises(PublicationPackageError, match="not accepted"):
        _build_linkedin(
            tmp_path,
            linkedin_composition=_composition(
                source_article_digest="sha256:" + "c" * 64
            ),
        )


# ── Configuration identity ───────────────────────────────────────────────────


def test_wrong_configuration_identity_fails(tmp_path):
    with pytest.raises(PublicationPackageError, match="authoritative configuration"):
        _build_wix(tmp_path, configuration_identity=FOREIGN_CONFIG)
    with pytest.raises(PublicationPackageError, match="authoritative configuration"):
        _build_linkedin(tmp_path, configuration_identity=FOREIGN_CONFIG)


def test_composition_with_foreign_configuration_fails(tmp_path):
    with pytest.raises(PublicationPackageError, match="configuration"):
        _build_linkedin(
            tmp_path,
            linkedin_composition=_composition(
                configuration_identity=FOREIGN_CONFIG.model_dump()
            ),
        )


def test_generated_without_configuration_identity_fails(tmp_path):
    generated = _generated()
    del generated["configuration_identity"]
    with pytest.raises(PublicationPackageError, match="no configuration identity"):
        _build_wix(tmp_path, generated=generated)


# ── Run identity ─────────────────────────────────────────────────────────────


def test_empty_run_identity_fails(tmp_path):
    with pytest.raises(PublicationPackageError, match="run_id must be non-empty"):
        _build_wix(tmp_path, run_id="")
    with pytest.raises(PublicationPackageError, match="run_id must be non-empty"):
        _build_linkedin(tmp_path, run_id="  ")


def test_package_model_rejects_empty_run_id_directly(tmp_path):
    wix = _build_wix(tmp_path)
    with pytest.raises(ValidationError):
        WixPublicationPackage(**{**wix.model_dump(), "run_id": ""})


# ── Channel separation and no-fallback ───────────────────────────────────────


def test_channel_content_cannot_be_swapped(tmp_path):
    """The LinkedIn body comes only from the accepted composition; a generated
    artifact claiming a different linkedin_post (e.g. a reading/blog body) is
    rejected — no channel-body fallback exists."""

    with pytest.raises(PublicationPackageError, match="no channel-body fallback"):
        _build_linkedin(tmp_path, generated=_generated(linkedin_post=ARTICLE_BODY))


def test_channel_literals_are_fixed(tmp_path):
    wix = _build_wix(tmp_path)
    linkedin = _build_linkedin(tmp_path)
    with pytest.raises(ValidationError):
        WixPublicationPackage(**{**wix.model_dump(), "channel": "linkedin"})
    with pytest.raises(ValidationError):
        LinkedInPublicationPackage(**{**linkedin.model_dump(), "channel": "wix"})


def test_unaccepted_composition_fails(tmp_path):
    assert list(LinkedInCompositionStatus) == [LinkedInCompositionStatus.ACCEPTED]
    with pytest.raises(PublicationPackageError, match="invalid"):
        _build_linkedin(
            tmp_path, linkedin_composition=_composition(status="rejected")
        )


# ── Trust boundary: no credentials, no local paths ───────────────────────────


def test_no_credentials_or_secrets_enter_the_package(tmp_path, monkeypatch):
    """Builders take no environment input; secret-bearing env never leaks in."""

    secret = "sk-super-secret-key-000"
    for var in (
        "NB_WIX_API_KEY",
        "NB_ZERNIO_API_KEY",
        "NB_WIX_SITE_ID",
        "NB_ZERNIO_LINKEDIN_ACCOUNT_ID",
    ):
        monkeypatch.setenv(var, secret)
    wix = _build_wix(tmp_path)
    linkedin = _build_linkedin(tmp_path)
    for package in (wix, linkedin):
        dumped = package.model_dump_json()
        assert secret not in dumped
        for token in ("key", "token", "secret", "password", "credential"):
            assert not any(
                token in name for name in package.model_dump()
            ), f"package field names must not carry {token!r}"


def test_local_filesystem_path_never_becomes_package_url(tmp_path):
    wix = _build_wix(tmp_path)
    with pytest.raises(ValidationError, match="https"):
        WixPublicationPackage(
            **{**wix.model_dump(), "cover_image_url": "/tmp/render/blog.png"}
        )
    linkedin = _build_linkedin(tmp_path)
    with pytest.raises(ValidationError, match="https"):
        LinkedInPublicationPackage(
            **{**linkedin.model_dump(), "linkedin_image_url": "file:///tmp/li.png"}
        )


def test_target_identity_is_required_and_whitespace_free():
    with pytest.raises(ValidationError):
        WixPublicationTarget(site_id="", owner_member_id="member-1")
    with pytest.raises(ValidationError):
        WixPublicationTarget(site_id="site 1", owner_member_id="member-1")
    with pytest.raises(ValidationError):
        LinkedInPublicationTarget(account_id="")


# ── Immutability and determinism ─────────────────────────────────────────────


def test_packages_are_frozen(tmp_path):
    wix = _build_wix(tmp_path)
    with pytest.raises(ValidationError):
        wix.title = "tampered"
    linkedin = _build_linkedin(tmp_path)
    with pytest.raises(ValidationError):
        linkedin.linkedin_body = "tampered"


def test_package_digest_is_deterministic_and_content_bound(tmp_path):
    first = _build_wix(tmp_path)
    second = _build_wix(tmp_path)
    assert first.package_digest() == second.package_digest()
    reloaded = WixPublicationPackage.model_validate(first.model_dump(mode="json"))
    assert reloaded.package_digest() == first.package_digest()
    li_first = _build_linkedin(tmp_path)
    li_reloaded = LinkedInPublicationPackage.model_validate(
        li_first.model_dump(mode="json")
    )
    assert li_reloaded.package_digest() == li_first.package_digest()
    assert li_first.package_digest() != first.package_digest()


def test_wix_package_is_self_proving(tmp_path):
    """Digest, slug, and body are mutually locked inside the strict model."""

    wix = _build_wix(tmp_path)
    with pytest.raises(ValidationError, match="accepted article"):
        WixPublicationPackage(
            **{**wix.model_dump(), "body_markdown": ARTICLE_BODY + " tampered"}
        )
    with pytest.raises(ValidationError, match="deterministic slug"):
        WixPublicationPackage(**{**wix.model_dump(), "slug": "handcrafted-slug"})


def test_strict_models_reject_unknown_fields(tmp_path):
    wix = _build_wix(tmp_path)
    with pytest.raises(ValidationError):
        WixPublicationPackage(**{**wix.model_dump(), "raw_response": {}})
