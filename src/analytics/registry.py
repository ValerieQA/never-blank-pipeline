"""Which destination has a metrics collector, and how to get it (NB-08s).

Today the registry is the caller's literal list: `scripts/run_analytics.py`
writes ``collectors=[BlogCollector(), LinkedInCollector()]``, and
`collector_protocol`'s own instructions say to add a platform by importing its
collector "and include it in the collectors= list". That works for two. For six
it means the answer to "does this destination have a collector" lives in a
script's argument list, where `AS_IS_CAPABILITY` cannot check it and a new
destination slice cannot register into it.

So this module is the one place that answers it, and nothing else about
analytics changes: :class:`AnalyticsCollector` is untouched,
``orchestrator.run_analytics_pipeline`` still takes its ``collectors=``
argument, and `blog.py` and `linkedin.py` are exactly as they were.

**Two vocabularies, deliberately kept apart.** A destination is ``wix``; the
collector's platform — and `PublishedEntry.platform` — is ``blog``. That
translation already exists in `src/visual/contract.py`'s
``RELEASE1_CHANNELS`` (``'wix': ('blog', True)``), so it is carried here rather
than invented, and the registry is keyed by **destination** because that is
what capability and the rollout scope are keyed by.

**This is not capability.** A destination absent below has no collector, which
is what ``AS_IS_CAPABILITY`` already records for four of them. Registering one
here is the whole of what "it has a metrics collector" means — and authorization
to publish remains a third question that ``release_scope`` owns.
"""

from __future__ import annotations

from typing import Callable, Mapping

from src.analytics.collector_protocol import AnalyticsCollector


class NoCollectorError(RuntimeError):
    """No metrics collector is registered for this destination."""


#: Destination name → the collector's ``platform`` string. Only the
#: destinations whose two names differ need an entry; everything else is its
#: own platform name.
_PLATFORM_OF: Mapping[str, str] = {"wix": "blog"}


def collector_platform(destination: str) -> str:
    """The ``platform`` string the collector for ``destination`` reports."""

    return _PLATFORM_OF.get(destination, destination)


def _blog() -> AnalyticsCollector:
    from src.analytics.blog import BlogCollector

    return BlogCollector()


def _linkedin() -> AnalyticsCollector:
    from src.analytics.linkedin import LinkedInCollector

    return LinkedInCollector()


#: Destination → a factory for its collector.
#:
#: Factories rather than instances: a collector reads its credentials when it
#: is constructed, so building all of them to answer "which exist" would make
#: a question about capability depend on the environment of whoever asked.
#: Imports are inside the factories for the same reason — importing this module
#: must not require every platform's dependencies to be installed.
COLLECTOR_FACTORIES: Mapping[str, Callable[[], AnalyticsCollector]] = {
    "wix": _blog,
    "linkedin": _linkedin,
}


def collectable_destinations() -> tuple[str, ...]:
    """The destinations with a registered collector, in canonical order.

    Canonical order and not alphabetical: ``publication_markers.DESTINATIONS``
    is the declared destination sequence, and it is what keeps this list
    behaviour-preserving. Sorting would have put LinkedIn before Wix and
    silently reordered ``collectors_attempted`` in every analytics run —
    a reporting change nobody asked for, from a helper that was only supposed
    to answer which collectors exist.
    """

    from src.publishing.publication_markers import DESTINATIONS

    order = {name: index for index, name in enumerate(DESTINATIONS)}
    return tuple(
        sorted(COLLECTOR_FACTORIES, key=lambda name: (order.get(name, len(order)), name))
    )


def collector_for(destination: str) -> AnalyticsCollector:
    """Build the collector for ``destination``, or fail closed.

    Raising rather than returning ``None`` for the reason
    ``package.package_builder`` raises: the one safe reading of "this
    destination has no collector" is that nothing may proceed as though it
    did, and an exception is what enforces it at every call site.
    """

    try:
        factory = COLLECTOR_FACTORIES[destination]
    except KeyError:
        raise NoCollectorError(
            f"no metrics collector is registered for {destination!r}; "
            f"registered: {', '.join(collectable_destinations())}"
        ) from None
    return factory()


def registered_collectors() -> list[AnalyticsCollector]:
    """Every registered collector, in destination order.

    What `scripts/run_analytics.py` used to spell as a literal list. Keeping
    the order deterministic matters because the pipeline reports
    ``collectors_attempted`` in the order it ran them.
    """

    return [collector_for(name) for name in collectable_destinations()]
