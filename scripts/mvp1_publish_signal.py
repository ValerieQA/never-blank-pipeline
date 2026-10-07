#!/usr/bin/env python3
"""MVP 1: publish one already-discovered signal's existing package (#393).

The July lane discovered its own signals, packaged them and published. This is
the smallest entry into the publishing half of that lane for **one named
signal whose package already exists** — nothing is discovered or
illustrated here. A **live** run does generate: Stage 11 has always produced the
six final texts at publication time, in July as today, and that behaviour is
kept rather than bypassed (owner decision 2026-10-07). The image is the one the
package already carries, hosted; no image is generated.

It hands `publish_packages` its two existing inputs and does nothing else:

    data/research/signals_active.jsonl          the signal, as discovered
    reports/content_packages/<signal>.json      its package, as prepared
      → publish_packages([signal], [package], mode=…, channels=…)

Everything after that — the draft, the per-destination marker authority, the
index and history writes — is the stage's own, unchanged.

**Fail closed before anything outward.** A signal that is not in the store, a
package that is missing, a package with no text for a requested destination,
and a missing image are each refused with exit 2, before the stage is called.
A destination the stage cannot drive is refused by the stage itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.research.publish_packages import (  # noqa: E402
    _ALL_PUBLISHERS,
    UnknownDestination,
    publish_packages,
)

SIGNALS = Path("data/research/signals_active.jsonl")
PACKAGES = Path("reports/content_packages")

#: MVP 1's destinations (owner, 2026-10-07). Threads is deliberately absent.
MVP1_CHANNELS = ("wix", "linkedin", "facebook", "instagram", "telegram")

#: Which package text each destination needs. `wix` and `linkedin` read the
#: blog and linkedin entries the package already carries; telegram is built
#: from the blog body and the article URL by the stage itself.
_REQUIRED_CONTENT = {
    "wix": "blog",
    "linkedin": "linkedin",
    "facebook": "facebook",
    "instagram": "instagram",
}

BAD_INPUT = 2


def _signal(signal_id: str) -> dict:
    if not SIGNALS.is_file():
        raise SystemExit(f"{SIGNALS} does not exist — nothing has been discovered")
    for line in SIGNALS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("SIGNAL_ID", "")) == signal_id:
            return row
    raise SystemExit(
        f"signal {signal_id!r} is not in {SIGNALS}. MVP 1 publishes what the "
        "system discovered; it does not invent a subject"
    )


def _package(signal_id: str, channels: list[str]) -> tuple[dict, str]:
    path = PACKAGES / f"{signal_id}.json"
    if not path.is_file():
        raise SystemExit(
            f"no content package at {path}. MVP 1 does not generate one — "
            "run the research lane's packaging stage first"
        )
    package = json.loads(path.read_text(encoding="utf-8"))
    content = package.get("content") or {}
    missing = [
        channel for channel in channels
        if channel in _REQUIRED_CONTENT and not content.get(_REQUIRED_CONTENT[channel])
    ]
    if missing:
        raise SystemExit(
            f"package {path.name} carries no text for: {', '.join(missing)}"
        )
    images = (package.get("images") or {}).get("platform_images") or {}
    # `platform_images` carries one entry per surface plus two metadata keys
    # (`_design_version`, `_method`) whose values are strings, so an entry is
    # only a surface when it is a mapping.
    hosted = [
        (name, entry["url"])
        for name, entry in images.items()
        if isinstance(entry, dict) and entry.get("url")
    ]
    if not hosted:
        raise SystemExit(
            f"package {path.name} has no hosted image. MVP 1 does not generate "
            "one; the package must already carry it"
        )
    return package, hosted[0][1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-id", required=True)
    parser.add_argument(
        "--channels", default=",".join(MVP1_CHANNELS),
        help="Comma-separated destinations, in the stage's own publication order",
    )
    # There is deliberately no dry-run mode. Stage 11 generates the six texts
    # before it touches a publisher, so a rehearsal through it costs nine model
    # calls and posts nothing — the worst of both (owner decision 2026-10-07).
    # `inspect` is free because it never calls the stage: it answers only
    # whether this signal *could* be published, which is what a gate needs.
    parser.add_argument(
        "--mode", choices=("inspect", "live"), default="inspect",
        help="inspect checks the inputs and calls nothing; live generates and publishes",
    )
    args = parser.parse_args(argv)

    channels = [name.strip().lower() for name in args.channels.split(",") if name.strip()]
    # Checked here, before the mode branch, and not left to the stage: the
    # stage is only reached by a live run, so a typo would otherwise pass
    # `inspect` and surface for the first time on a paid one. The vocabulary is
    # the stage's own, so there is one answer to what a destination is.
    known = {name for name, _ in _ALL_PUBLISHERS}
    unknown = [name for name in channels if name not in known]
    if unknown:
        raise SystemExit(
            f"unknown destination(s): {', '.join(unknown)}; "
            f"known: {', '.join(sorted(known))}"
        )
    if not channels:
        raise SystemExit("no destination requested")

    signal = _signal(args.signal_id)
    package, image_url = _package(args.signal_id, channels)

    print(f"  signal     {args.signal_id}")
    print(f"  headline   {str(signal.get('HEADLINE'))[:88]}")
    print(f"  source     {signal.get('SOURCE_NAME')} · found {signal.get('DATE_FOUND')}")
    print(f"  package    {PACKAGES / (args.signal_id + '.json')}")
    print(f"  mode       {args.mode}")
    print(f"  channels   {', '.join(channels)}")
    print(f"  image      {image_url}")

    if args.mode == "inspect":
        print(
            "\n  inspect: inputs are present and publishable. Nothing was "
            "called.\n  A live run generates the six texts (Stage 11, nine "
            "model calls) and publishes to the destinations above."
        )
        return 0

    try:
        reports = publish_packages(
            [signal], [package], mode=args.mode, channels=channels
        )
    except UnknownDestination as exc:
        print(f"\n  refused: {exc}")
        return BAD_INPUT

    if not reports:
        print(
            "\n  the stage published nothing and said nothing: "
            "NB_RESEARCH_PUBLISH_ENABLED is not 'true'"
        )
        return BAD_INPUT

    for report in reports:
        for name, result in sorted((report.get("results") or {}).items()):
            print(f"  {name:10} {result.get('status'):22} {str(result.get('error_message') or result.get('url') or '')[:64]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
