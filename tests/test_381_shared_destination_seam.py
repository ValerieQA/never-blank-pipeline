"""Issue #381 (NB-08s): one shared seam for destination capability, not four.

Why. All four SL-8 slices (#310–#313) need the same five places widened, so
four concurrent PRs in them conflict by construction. The owner resolved D1
architecturally: build the seam once, consume it per destination.

What the tests below are mostly about is the **boundary**, not the widening.
An interfaces-only slice is dangerous in one specific way: it is one line away
from also granting capability or authorization. So the heaviest assertions here
are that `AS_IS_CAPABILITY` still reports four destinations incapable, and that
`R1_PUBLISH_CHANNELS` still names two — because being *representable* in a
verdict, having a package, and being authorized to publish are three different
facts, and this slice moves only the first.
"""

from __future__ import annotations

import pytest

from src.analytics import registry
from src.analytics.collector_protocol import AnalyticsCollector
from src.editorial_core.destinations import AS_IS_CAPABILITY, Destination
from src.publishing import package as package_module
from src.publishing.package import (
    PACKAGE_BUILDERS,
    PublicationPackageError,
    UnsupportedDestinationError,
    package_builder,
    packageable_destinations,
)
from src.publishing.preflight import CHANNEL_CREDENTIAL_ENV, PreflightResult
from src.publishing.publication_markers import DESTINATIONS
from src.publishing.release_scope import NON_R1_PUBLISH_CHANNELS, R1_PUBLISH_CHANNELS

#: The four this slice must leave incapable.
NOT_YET = ("facebook", "instagram", "threads", "telegram")


# ===========================================================================
# The boundary: nothing became capable, nothing became publishable
# ===========================================================================


def test_the_capability_census_is_unchanged_by_this_slice():
    """Interfaces are not capability, and the census is what says so.

    AD-02 §3 needs all five parts. This slice builds the *places* a package,
    a preflight entry and a collector can exist; it builds none of them for
    these four destinations, so all three parts must still read absent. A row
    flipping here would be the slice claiming work it did not do.
    """

    for name in NOT_YET:
        capability = AS_IS_CAPABILITY[Destination(name)]
        assert not capability.capable
        assert set(capability.missing) == {
            "package",
            "preflight",
            "metrics_collector",
        }, f"{name}: {capability.missing}"

    # And the two that were capable still are, by the same five parts.
    for name in ("wix", "linkedin"):
        assert AS_IS_CAPABILITY[Destination(name)].capable


def test_the_rollout_scope_is_unchanged_by_this_slice():
    """Representable is not authorized. `release_scope` owns the third fact."""

    assert R1_PUBLISH_CHANNELS == ("wix", "linkedin")
    assert NON_R1_PUBLISH_CHANNELS == ("facebook", "instagram", "threads", "telegram")


def test_the_census_and_the_registries_agree_about_who_has_what():
    """The two sources are checked against each other, never derived.

    `AS_IS_CAPABILITY` stays hand-written on purpose — AD-02 §3 is explicit
    that the editorial core must not read the publishers to learn what it may
    decide. So the registries cannot *produce* the census; this test is how a
    disagreement between them is caught instead.
    """

    for destination, capability in AS_IS_CAPABILITY.items():
        name = destination.value
        assert capability.package == (name in packageable_destinations()), name
        assert capability.metrics_collector == (
            name in registry.collectable_destinations()
        ), name
        # Preflight is the one that is now wider than capability, deliberately:
        # a destination can be represented in a verdict before it has a package.
        if capability.preflight:
            assert name in CHANNEL_CREDENTIAL_ENV, name


# ===========================================================================
# Preflight: a third channel is representable
# ===========================================================================


def test_a_third_and_fourth_channel_are_representable():
    """What the hard `max_length=2` made impossible."""

    assert len(CHANNEL_CREDENTIAL_ENV) == 6
    for name in NOT_YET:
        assert name in CHANNEL_CREDENTIAL_ENV, name

    field = PreflightResult.model_fields["channels"]
    limits = [m.max_length for m in field.metadata if hasattr(m, "max_length")]
    assert limits == [len(CHANNEL_CREDENTIAL_ENV)], (
        "the bound follows the declared vocabulary rather than a literal 2"
    )


def test_each_channel_names_its_authenticating_secret():
    """The rule the existing two already followed, applied and not invented.

    `wix` names its API key and not `NB_WIX_SITE_BASE_URL`, so a page *id* is
    not a credential either. Instagram sharing Facebook's page token is what
    `src/publishing/instagram.py` actually reads.
    """

    assert CHANNEL_CREDENTIAL_ENV["wix"] == "NB_WIX_API_KEY"
    assert CHANNEL_CREDENTIAL_ENV["linkedin"] == "NB_ZERNIO_API_KEY"
    assert CHANNEL_CREDENTIAL_ENV["facebook"] == "NB_META_FB_PAGE_TOKEN"
    assert CHANNEL_CREDENTIAL_ENV["instagram"] == "NB_META_FB_PAGE_TOKEN"
    assert CHANNEL_CREDENTIAL_ENV["threads"] == "NB_THREADS_ACCESS_TOKEN"
    assert CHANNEL_CREDENTIAL_ENV["telegram"] == "NB_TELEGRAM_BOT_TOKEN"

    for name, variable in CHANNEL_CREDENTIAL_ENV.items():
        assert not variable.endswith("_ID"), f"{name} names an identifier, not a secret"
        assert not variable.endswith("_URL"), f"{name} names a location, not a secret"


def test_an_unknown_channel_is_still_refused():
    """Widening the vocabulary is not opening it."""

    from src.publishing.preflight import ChannelPreflightVerdict, PreflightDisposition

    with pytest.raises(ValueError, match="unsupported publication channel"):
        ChannelPreflightVerdict(
            channel="mastodon",
            package_valid=False,
            credential_ready=False,
            disposition=PreflightDisposition.BLOCK,
            blocking_reasons=("package_invalid",),
        )


# ===========================================================================
# Packages: a destination registers a builder
# ===========================================================================


def test_only_the_two_existing_destinations_have_a_package_builder():
    assert packageable_destinations() == ("linkedin", "wix")
    assert set(PACKAGE_BUILDERS) == {"wix", "linkedin"}


def test_the_two_existing_builders_are_registered_unchanged():
    """Registered as they are: no wrapper, no adapted signature."""

    assert package_builder("wix") is package_module.build_wix_publication_package
    assert (
        package_builder("linkedin")
        is package_module.build_linkedin_publication_package
    )


def test_an_unregistered_destination_fails_closed():
    """And fails closed as a package error, so existing callers need no new
    exception to keep refusing."""

    for name in NOT_YET:
        with pytest.raises(UnsupportedDestinationError) as caught:
            package_builder(name)
        assert name in str(caught.value)
        assert isinstance(caught.value, PublicationPackageError)


# ===========================================================================
# Collectors: a registry, and the behaviour it must not change
# ===========================================================================


def test_only_the_two_existing_destinations_have_a_collector():
    assert registry.collectable_destinations() == ("wix", "linkedin")
    for name in NOT_YET:
        with pytest.raises(registry.NoCollectorError, match=name):
            registry.collector_for(name)


def test_the_registry_reproduces_the_literal_list_it_replaced_in_order():
    """`run_analytics.py` used to spell `[BlogCollector(), LinkedInCollector()]`.

    Order is behaviour here — the pipeline reports `collectors_attempted` in
    the order it ran them — so the registry follows
    `publication_markers.DESTINATIONS` rather than sorting. Sorting put
    LinkedIn first, which is how an interfaces-only change would have
    reordered every analytics run's report.
    """

    built = registry.registered_collectors()
    assert [type(item).__name__ for item in built] == [
        "BlogCollector",
        "LinkedInCollector",
    ]
    assert [item.platform for item in built] == ["blog", "linkedin"]
    order = {name: index for index, name in enumerate(DESTINATIONS)}
    keys = [order[name] for name in registry.collectable_destinations()]
    assert keys == sorted(keys), "canonical destination order, not alphabetical"


def test_the_destination_and_platform_vocabularies_stay_distinct():
    """A destination is `wix`; the collector's platform is `blog`.

    Carried from `visual.contract.RELEASE1_CHANNELS`, where the same
    translation already lives, rather than invented here.
    """

    from src.visual.contract import RELEASE1_CHANNELS

    assert registry.collector_platform("wix") == "blog"
    assert RELEASE1_CHANNELS["wix"][0] == "blog"
    assert registry.collector_platform("linkedin") == "linkedin"
    # Everything else is its own platform name, including the four with no
    # collector — asking the question must not require a collector to exist.
    for name in NOT_YET:
        assert registry.collector_platform(name) == name


def test_every_registered_collector_satisfies_the_untouched_protocol():
    for collector in registry.registered_collectors():
        assert isinstance(collector, AnalyticsCollector)
        assert isinstance(collector.platform, str) and collector.platform


def test_asking_which_collectors_exist_builds_none_of_them():
    """A collector reads credentials when constructed, so the census must not.

    Otherwise "which destinations have a collector" would depend on whose
    environment asked.
    """

    import inspect

    source = inspect.getsource(registry.collectable_destinations)
    assert "collector_for" not in source
    assert "factory()" not in source
    # The factories are what defer construction; the map holds callables.
    for name, factory in registry.COLLECTOR_FACTORIES.items():
        assert callable(factory), name
        assert not isinstance(factory, AnalyticsCollector), name


# ===========================================================================
# No Editorial Core destination branch
# ===========================================================================


def test_no_editorial_core_module_branches_on_a_destination_name():
    """The seam is in `src/publishing` and `src/analytics`, by construction.

    `destinations.py` names the six — that is the vocabulary, and AD-02 §3's
    census lives there. What must not appear is editorial behaviour keyed on a
    destination's *name* in the core, which is how a destination-specific
    editorial path starts.
    """

    import pathlib

    for path in pathlib.Path("src/editorial_core").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in NOT_YET:
            # A quoted destination name inside a conditional is the shape this
            # forbids; the enum and the census reference them without one.
            assert f'== "{name}"' not in text, f"{path}: branch on {name}"
            assert f'"{name}" ==' not in text, f"{path}: branch on {name}"
