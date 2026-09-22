#!/usr/bin/env python3
"""Which signal the research stream may publish next (NB-00b).

The research workflow used to choose by reading
``data/research/published_signal_ids.txt`` and nothing else. That file is a
signal-level summary committed only when a whole job succeeded, so a run that
published Wix and then failed LinkedIn leaves it untouched and the signal
still looks unused — the partial-success hole in Step 5 §1.1. Selecting it
again sends the same publication back to the destinations that already took
it.

So the marker authority is consulted here, beside the legacy file, exactly as
``select_eligible_signal.py`` does for Monday. This resolver is deliberately
*not* that selector: Monday's runs an editorial eligibility judgement and
spends model calls, and the research stream has always taken the first unused
signal. The only thing that changes is which signals count as unused.

Three outcomes, and the exit code says which:

``0``
    A signal the authority has not spent. It is printed on stdout.
``3``
    A completed search that found none. Publishing nothing is correct and the
    run stays green — the same contract ``select_eligible_signal.py`` uses.
``4``
    The store could not answer. Never read as "nothing was published" — that
    confusion is what turns a fresh checkout into a second publication — and
    never converted into a quiet "nothing to publish" either: an authority
    that cannot answer is infrastructure failure, so the run fails visibly.
    The same distinction ``select_eligible_signal.py`` makes between its
    ``NO_ELIGIBLE`` and ``ELIGIBILITY_FAILURE``.

An explicitly dispatched ``--signal-id`` is checked too. A person naming a
signal is telling the run which one to consider, not overriding the authority
that knows it was already published.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.publishing.idempotency import signal_publication_state
from src.publishing.publication_markers import AUTHORITY_UNAVAILABLE

#: A completed search that selected nothing. Shared with the Monday selector.
NO_ELIGIBLE = 3

#: The authority could not answer. Loud on purpose: a silent green run here
#: would report an outage as a quiet day.
AUTHORITY_FAILURE = 4


def _candidates(active_path: Path) -> list[str]:
    ids: list[str] = []
    if not active_path.is_file():
        return ids
    for line in active_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            signal_id = str(json.loads(line).get("SIGNAL_ID", "")).strip()
        except (json.JSONDecodeError, AttributeError):
            continue
        if signal_id and signal_id not in ids:
            ids.append(signal_id)
    return ids


def _already_done(published_path: Path) -> set[str]:
    if not published_path.is_file():
        return set()
    return {
        line.strip()
        for line in published_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _authority_refuses(signal_id: str, *, store=None) -> tuple[bool, bool]:
    """``(refused, unavailable)`` for one signal, from the marker authority."""

    state = signal_publication_state([signal_id], store=store)
    return state.consumed, state.unavailable


def main(argv: list[str] | None = None, *, store=None) -> int:
    parser = argparse.ArgumentParser(description="Resolve the research stream's signal")
    parser.add_argument("--signal-id", default="",
                        help="an explicitly dispatched signal; still checked")
    parser.add_argument("--active-path", default="data/research/signals_active.jsonl")
    parser.add_argument("--published-path", default="data/research/published_signal_ids.txt")
    args = parser.parse_args(argv)

    done = _already_done(Path(args.published_path))

    requested = args.signal_id.strip()
    if requested:
        if requested in done:
            print(
                f"{requested} is already in the published signals file — "
                "publishing nothing.", file=sys.stderr,
            )
            return NO_ELIGIBLE
        refused, unavailable = _authority_refuses(requested, store=store)
        if unavailable:
            print(f"{AUTHORITY_UNAVAILABLE}: publishing nothing.", file=sys.stderr)
            return AUTHORITY_FAILURE
        if refused:
            print(
                f"{requested} has already been published, or may have been, "
                "for at least one destination — publishing nothing.",
                file=sys.stderr,
            )
            return NO_ELIGIBLE
        print(requested)
        return 0

    for signal_id in _candidates(Path(args.active_path)):
        if signal_id in done:
            continue
        refused, unavailable = _authority_refuses(signal_id, store=store)
        if unavailable:
            # Not "this candidate is unusable" — the authority cannot answer
            # about any of them, so the search cannot continue at all.
            print(f"{AUTHORITY_UNAVAILABLE}: publishing nothing.", file=sys.stderr)
            return AUTHORITY_FAILURE
        if refused:
            continue
        print(signal_id)
        return 0

    print("No unpublished research signal — publishing nothing.", file=sys.stderr)
    return NO_ELIGIBLE


if __name__ == "__main__":
    sys.exit(main())
