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
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.research.publish_packages import (  # noqa: E402
    _ALL_PUBLISHERS,
    _OUTSIDE_R1_REASON,
    _WITHHELD_CHANNELS,
    UnknownDestination,
    publish_packages,
)
from src.publishing.publication_markers import (  # noqa: E402
    PUBLICATION_UNCONFIRMED,
    AuthorityState,
    MarkerStore,
    PublicationIdentity,
)
from src.publishing.result import PublishStatus  # noqa: E402

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
#: A live cycle that reached the stage but did not settle every destination it
#: drove. Distinct from BAD_INPUT: the inputs were fine and the stage ran.
CYCLE_INCOMPLETE = 3

#: A destination is settled only by proof. ``PUBLISHED`` is a fresh
#: publication; ``REUSED`` is prior canonical evidence that this exact
#: publication already exists (#105) — what a correct repeat run looks like.
#: Nothing else settles one: ``DRAFT_CREATED`` is not a live post,
#: ``PROVIDER_DUPLICATE`` proves *a* duplicate but never which post (#108),
#: and a refusal is not an outcome.
_SETTLED = frozenset({PublishStatus.PUBLISHED.value, PublishStatus.REUSED.value})

#: A scheduled day with nothing left to publish. Visible on purpose: a lane
#: that reports success while publishing nothing is the failure this
#: repository has already paid for twice.
NO_ELIGIBLE_SIGNAL = 4

#: What `--signal-id` is given when nobody named one — a scheduled day.
AUTO = "auto"


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


def _github_output(signal_id: str) -> None:
    """Publish the resolved id as a step output, when running under Actions."""

    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(f"signal_id={signal_id}\n")


def unspent(signal_id: str, channels: list[str]) -> bool:
    """Has the publication authority left every requested destination open?

    The authority, not the consumption list. `published_signal_ids.txt` is
    written only when a whole cycle succeeded, so run 37715852447 — four
    surfaces published, LinkedIn failed — left it untouched and that signal
    still looks unused there. The marker store knows better, and an
    `UNAVAILABLE` answer counts as spent: a selector that cannot read the
    authority must not pick.
    """

    store = MarkerStore(require_shared_claim=False)
    for destination in channels:
        state = store.lookup(
            PublicationIdentity(
                client="never_blank",
                destination=destination,
                source_signal_ids=[signal_id],
            )
        ).state
        if state is not AuthorityState.NO_PUBLICATION:
            return False
    return True


def select_signal(channels: list[str]) -> Optional[str]:
    """The first signal in the research store's own order that can be published.

    Queue order, nothing cleverer. That is the baseline
    `scripts/streams/select_eligible_signal.py` documents before it adds a
    role's eligibility judgment — and the judgment is exactly what this lane
    must not acquire: MVP 1 has no editorial role, and asking a model about
    each candidate would put a paid call in front of every scheduled day.
    So eligibility here is only what the lane already requires of a named
    signal: a prepared package it can publish, and an authority that has not
    spent it.

    Returns ``None`` when the queue is exhausted, which is a reportable
    outcome rather than an error.
    """

    if not SIGNALS.is_file():
        return None

    for line in SIGNALS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            signal_id = str(json.loads(line).get("SIGNAL_ID") or "")
        except json.JSONDecodeError:
            continue
        if not signal_id:
            continue
        try:
            # The lane's own package rules, called rather than restated, so a
            # selected signal cannot fail the validation that follows.
            _package(signal_id, channels)
        except SystemExit:
            continue
        if unspent(signal_id, channels):
            return signal_id

    return None


def classify(
    reports: list[dict], requested: list[str]
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Every requested destination, accounted for: settled, expected, unresolved.

    Run 37715852447 published to four surfaces, failed LinkedIn, and reported
    success, because this entry returned 0 whatever its table said. The three
    groups are the repair: only proof settles a destination, only the stated
    Release 1 scope refusal is an expected absence, and anything else leaves
    the cycle incomplete.

    It reads the report **against the request**, not on its own terms. A table
    is not evidence that every destination was attempted: a destination that
    silently vanishes from the results is indistinguishable from one that was
    never driven, and #227 stayed hidden for months on exactly that. So a
    requested destination with no result, a destination reported twice, a
    result for something nobody asked for, and a report with no results at
    all are each unresolved rather than absent.

    ``publication_unconfirmed`` counts as unresolved too (NB-00a §3.6 p5): the
    post exists and its marker does not, so the next run will skip the key.
    That needs a person even though the destination itself published.
    """

    settled: list[str] = []
    expected: list[str] = []
    unresolved: list[tuple[str, str]] = []

    wanted = [name.strip().lower() for name in requested if str(name).strip()]
    # Channels the release scope withholds are reported without being asked
    # for, and that is the one expected extra (#227 item 8).
    permitted = set(wanted) | set(_WITHHELD_CHANNELS)
    seen: dict[str, int] = {}

    if not reports:
        unresolved.append(("(report)", "the stage reported nothing"))

    for index, report in enumerate(reports):
        results = report.get("results") or {}
        if not isinstance(results, dict) or not results:
            unresolved.append((f"(report {index})", "no results reported"))
            continue

        for name, result in sorted(results.items()):
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                unresolved.append((name, "reported more than once"))
                continue
            if name not in permitted:
                unresolved.append((name, "result for a destination nobody requested"))
                continue
            if not isinstance(result, dict):
                unresolved.append((name, "result is not a result"))
                continue

            status = str(result.get("status") or "")
            reason = str(result.get("error_message") or "")
            if status in _SETTLED:
                settled.append(name)
            elif status == PublishStatus.SKIPPED.value and reason == _OUTSIDE_R1_REASON:
                expected.append(name)
            else:
                unresolved.append((name, reason or status or "no status reported"))

        for key in report.get(PUBLICATION_UNCONFIRMED) or []:
            unresolved.append((str(key), PUBLICATION_UNCONFIRMED))

    for name in wanted:
        if name not in seen:
            unresolved.append((name, "requested, and no result was reported"))

    return settled, expected, unresolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--signal-id", required=True,
        help=f"a signal id, or {AUTO!r} to take the first publishable one in queue order",
    )
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

    signal_id = args.signal_id
    if signal_id == AUTO:
        selected = select_signal(channels)
        if selected is None:
            print(
                "  no publishable signal: every discovered signal either has no "
                "package\n  for these destinations or has already been spent by "
                "the publication\n  authority. Nothing was called."
            )
            return NO_ELIGIBLE_SIGNAL
        signal_id = selected
        print(f"  selected   {signal_id} (first publishable in queue order)")

    # The resolved id, for the step that marks the cycle complete. On a
    # scheduled day `--signal-id` is `auto`, and appending *that* to the
    # consumption list would record a signal nobody published. Same mechanism
    # and same output name `wednesday_golden.yml` already reads.
    _github_output(signal_id)

    signal = _signal(signal_id)
    package, image_url = _package(signal_id, channels)

    print(f"  signal     {signal_id}")
    print(f"  headline   {str(signal.get('HEADLINE'))[:88]}")
    print(f"  source     {signal.get('SOURCE_NAME')} · found {signal.get('DATE_FOUND')}")
    print(f"  package    {PACKAGES / (signal_id + '.json')}")
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

    settled, expected, unresolved = classify(reports, channels)

    if unresolved:
        print(
            f"\n  INCOMPLETE: {len(settled)} destination(s) settled, "
            f"{len(unresolved)} unresolved."
        )
        for name, why in unresolved:
            print(f"    {name:10} {why[:78]}")
        print(
            "  The settled destinations' evidence is preserved; the cycle is "
            "not complete.\n  A destination that published stays published — "
            "read the markers before re-running."
        )
        return CYCLE_INCOMPLETE

    if not settled:
        print(
            "\n  INCOMPLETE: nothing was published and nothing was reused."
            f"\n  Expected absences only: {', '.join(expected) or 'none'}."
        )
        return CYCLE_INCOMPLETE

    print(f"\n  complete: {', '.join(settled)} settled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
