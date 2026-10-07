"""The legacy caller the Wix and LinkedIn adapters used to have (#393).

Until #100/#101 both took a `DraftPackage` and read their target from the
environment. That migration was right for the canonical path — *"a second
independent target selection here would let the external call go to a target
the package digest does not identify"* — and nothing adapted the lane that was
already calling them. So Daily Signal Research's Stage 11 raised
`AttributeError` before any provider call, and #231 emptied the stage rather
than fixing the seam.

This is the compatibility fix at that seam, and these tests hold both halves of
it: the legacy caller works again, and the canonical caller is untouched.

Everything here is deterministic — no credential, no network, no provider. The
publishers are driven in `dry_run`, and the proof that they accept a draft is
that they now fail on a *missing credential* instead of on an attribute.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.publishing.base import DraftPackage
from src.publishing.facebook import FacebookPublisher
from src.publishing.instagram import InstagramPublisher
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.telegram import TelegramPublisher
from src.publishing.threads import ThreadsPublisher
from src.publishing.wix import WixPublisher

#: MVP 1's destinations (owner, 2026-10-07). Threads is deliberately absent.
MVP1 = ("wix", "linkedin", "facebook", "instagram", "telegram")


def _draft() -> DraftPackage:
    """A legacy draft with its target identity filled, as Stage 11 now fills it."""

    return DraftPackage(
        draft_dir=Path("."),
        blog_title="A documented case",
        blog_body="# A documented case\n\nBody.",
        blog_meta={"title": "A documented case", "wix_slug": "a-documented-case"},
        linkedin_text="linkedin",
        instagram_text="instagram",
        facebook_text="facebook",
        threads_sequence=["one"],
        telegram_text="telegram",
        image_url=None,
        wix_slug="a-documented-case",
        wix_site_id="site-id",
        wix_owner_member_id="owner-id",
        linkedin_account_id="account-id",
    )


# ===========================================================================
# 1 · the seam: a legacy draft no longer crashes the two migrated adapters
# ===========================================================================


@pytest.mark.parametrize(
    "publisher, missing_credential",
    [
        (WixPublisher, "NB_WIX_API_KEY"),
        (LinkedInPublisher, "NB_ZERNIO_API_KEY"),
    ],
)
def test_a_migrated_adapter_accepts_the_legacy_draft_again(
    publisher, missing_credential
):
    """It reaches its credential check — which is as far as it can get here.

    Before the fix this raised `AttributeError: 'DraftPackage' object has no
    attribute 'title'` (Wix) and `… 'linkedin_body'` (LinkedIn), from the first
    statement of `publish()`, before the mode check and before any call. A
    clean credential failure is therefore the proof: the adapter got past
    conversion and into its own logic.
    """

    result = publisher().publish(_draft(), "dry_run")

    assert missing_credential in str(result.error_message)


@pytest.mark.parametrize(
    "publisher",
    [FacebookPublisher, InstagramPublisher, TelegramPublisher, ThreadsPublisher],
)
def test_the_unmigrated_adapters_are_unchanged(publisher):
    """They always took a draft, and still do. Nothing was done to them."""

    result = publisher().publish(_draft(), "dry_run")

    assert result.platform
    assert "AttributeError" not in str(result.error_message)


def test_the_canonical_caller_still_gets_its_conversion():
    """The half that must not move: a frozen package is still derived from.

    Asserted on the adapter's source rather than by building a canonical
    package here, because what matters is that the conversion branch still
    exists and is still what a non-draft argument takes.
    """

    import inspect

    for module, conversion in (
        (WixPublisher, "from_wix_package"),
        (LinkedInPublisher, "from_linkedin_package"),
    ):
        source = inspect.getsource(module.publish)
        assert f"DraftPackage.{conversion}(package)" in source
        assert "isinstance(package, DraftPackage)" in source


def test_the_target_identity_still_fails_closed_when_absent(monkeypatch):
    """The #100 guarantee the fix must not weaken.

    A draft that names no target is refused — the adapter does not fall back to
    the environment, which is exactly what #100 removed. The legacy caller now
    supplies the target; it does not get to omit it.

    A sentinel credential is set so the check under test is the one reached:
    the adapter validates its key first, and the suite's autouse guard strips
    every provider variable before each test, so this value is this test's own
    and reaches nothing — the target refusal returns before any HTTP call.
    """

    monkeypatch.setenv("NB_WIX_API_KEY", "sk-fake-never-billed")

    draft = _draft()
    blank = DraftPackage(**{
        **{f: getattr(draft, f) for f in draft.__dataclass_fields__},
        "wix_site_id": "",
        "wix_owner_member_id": "",
    })

    result = WixPublisher().publish(blank, "live")

    assert "target identity" in str(result.error_message)


# ===========================================================================
# 2 · the destination set: the caller names it, the default does not move
# ===========================================================================


def test_an_existing_caller_publishes_exactly_what_it_published_before():
    """`channels=None` is every caller on main today, and it is unchanged.

    #231 decided Stage 11 drives nothing. The compatibility fix removes the
    *reason* that decision was made, not the decision: the nightly job still
    generates, still packages and still publishes nothing until somebody asks.
    """

    from scripts.research.publish_packages import _publishers_for

    assert _publishers_for(None) == []


def test_an_explicit_caller_drives_exactly_the_five_it_names():
    from scripts.research.publish_packages import _publishers_for

    assert [name for name, _ in _publishers_for(MVP1)] == list(MVP1)


def test_threads_is_drivable_but_not_part_of_mvp1():
    """A scope decision, not a removal: it answers when asked, and MVP 1 does not."""

    from scripts.research.publish_packages import _publishers_for

    assert "threads" not in MVP1
    assert [name for name, _ in _publishers_for(["threads"])] == ["threads"]


@pytest.mark.parametrize("bad", [["wix", "linkedni"], ["mastodon"], [], [""]])
def test_a_malformed_destination_set_is_refused(bad):
    """Before anything outward, and named rather than skipped."""

    from scripts.research.publish_packages import (
        UnknownDestination,
        _publishers_for,
    )

    with pytest.raises(UnknownDestination):
        _publishers_for(bad)


def test_release_scope_is_untouched():
    """The authorization boundary is not what changed."""

    from src.publishing.release_scope import (
        NON_R1_PUBLISH_CHANNELS,
        R1_PUBLISH_CHANNELS,
    )

    assert R1_PUBLISH_CHANNELS == ("wix", "linkedin")
    assert NON_R1_PUBLISH_CHANNELS == ("facebook", "instagram", "threads", "telegram")

    source = Path("src/publishing/release_scope.py").read_text(encoding="utf-8")
    assert "_publishers_for" not in source
    assert "mvp" not in source.lower()


def test_the_stage_fills_the_target_identity_it_used_to_omit():
    """The third touch: the three variables July's publishers read themselves."""

    source = Path("scripts/research/publish_packages.py").read_text(encoding="utf-8")

    for field, variable in (
        ("wix_site_id", "NB_WIX_SITE_ID"),
        ("wix_owner_member_id", "NB_WIX_POST_OWNER_ID"),
        ("linkedin_account_id", "NB_ZERNIO_LINKEDIN_ACCOUNT_ID"),
    ):
        assert f'{field}=os.getenv("{variable}", "")' in source


def test_the_golden_engine_is_not_involved() -> None:
    """No canonical package is constructed here, and no preflight."""

    source = Path("scripts/research/publish_packages.py").read_text(encoding="utf-8")

    for forbidden in (
        "WixPublicationPackage",
        "LinkedInPublicationPackage",
        "editorial_core",
        "golden_engine",
    ):
        assert forbidden not in source, forbidden
