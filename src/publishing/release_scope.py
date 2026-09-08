"""Which channels a Release 1 automatic run is allowed to publish to.

One list, in one place. Release 1 publishes the canonical article to Wix and
its native derivative to LinkedIn; every other surface is generated, packaged
and stored, but not published.

Why this module exists (#227)
-----------------------------
The canonical entrypoint has always known this, and states it as
``_R1_PUBLISHERS``. Two older automatic paths did not: Stage 11 of Daily
Signal Research and the visibility publisher each carried their own list of
six publishers, written before Release 1 narrowed the scope, and neither was
updated when it did. On 2026-09-06 and 2026-09-07 the research path published
to Facebook, Instagram and Telegram — while Wix and LinkedIn failed — because
nothing in it had ever been told what Release 1 publishes. Forensics: #159.

A duplicated list is a list that drifts, so the scope now lives here and the
three paths import it. Adding a channel to Release 1 is a change to this file
and nowhere else.

This module deliberately says nothing about *how* to publish and imports no
publisher: it is the authorization boundary, and keeping it free of
implementation is what lets a publisher class stay in the repository, fully
usable by a manual or non-R1 caller, without becoming reachable from a
scheduled run.
"""

from __future__ import annotations

from typing import Iterable, Sequence, TypeVar

#: The only channels an automatic Release 1 run may publish to.
R1_PUBLISH_CHANNELS: tuple[str, ...] = ("wix", "linkedin")

#: Generated and packaged in Release 1, never published by an automatic run.
#: Their publisher implementations remain complete and importable — a manual
#: operator tool may still use them; a scheduled path may not.
NON_R1_PUBLISH_CHANNELS: tuple[str, ...] = (
    "facebook", "instagram", "threads", "telegram",
)

T = TypeVar("T")


def in_release_scope(channel: str) -> bool:
    """Is this channel authorized for an automatic Release 1 publication?"""
    return channel.strip().lower() in R1_PUBLISH_CHANNELS


def restrict_to_release_scope(
    publishers: Iterable[tuple[str, T]]
) -> list[tuple[str, T]]:
    """Keep only the ``(channel, publisher)`` pairs Release 1 authorizes.

    Order is preserved, because Wix must run before LinkedIn: LinkedIn's post
    carries the canonical article URL that publishing Wix produces.
    """
    return [pair for pair in publishers if in_release_scope(pair[0])]


def out_of_release_scope(channels: Sequence[str]) -> list[str]:
    """The channels that were dropped — for logging what did not publish."""
    return [name for name in channels if not in_release_scope(name)]
