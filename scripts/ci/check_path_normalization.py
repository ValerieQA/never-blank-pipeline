#!/usr/bin/env python3
"""Refuse two tracked paths that differ only by Unicode normalization (#325).

The trap this closes
--------------------
macOS stores a filename like ``ресёрч`` decomposed (``е`` + U+0308), and git
with ``core.precomposeunicode=true`` — the default there — precomposes it to
``ё`` when it reads the directory. If a decomposed spelling is ever committed,
the index ends up holding **two** entries for the same file:

  11_…дочитываемой_ресёрч_…docx   (NFD)
  11_…дочитываемой_ресёрч_…docx   (NFC)

On macOS ``git status`` stays clean, because the normalization-insensitive
filesystem satisfies both entries from the one file on disk. So the duplicate is
invisible where it is created. On a Linux checkout the two spellings are
different byte sequences and git writes **two copies** of the file, which is how
this reached CI and contaminated unrelated Editorial Core PRs (#288, #289, #321).

A ``git add -A`` in a worktree that still holds the other spelling re-adds it,
which is why cleaning it once was not enough and a check is the fix.

What it checks
--------------
Every tracked path, compared under NFC. Two paths that normalize to the same
string are a duplicate, and one path that is not already NFC is the thing that
becomes one. Both are reported with the exact spellings, because the two are
indistinguishable in a terminal and a message that did not show the bytes would
be a message nobody could act on.

The canonical form for this repository is **NFC**, which is what
``core.precomposeunicode=true`` produces: with NFC tracked, a macOS working tree
matches the index and nothing is re-added. Tracking the decomposed spelling
instead would leave git reporting it deleted and its precomposed twin untracked,
for ever.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import unicodedata
from collections import defaultdict


def tracked_paths(revision: str | None = None) -> list[str]:
    """Every path git tracks, read without quoting or precomposition.

    ``core.quotepath=false`` so the bytes arrive as they are, and
    ``core.precomposeunicode=false`` so git does not hide the very difference
    this looks for.
    """

    git = [
        "git",
        "-c",
        "core.quotepath=false",
        "-c",
        "core.precomposeunicode=false",
    ]
    command = (
        git + ["ls-tree", "-r", "--name-only", "-z", revision]
        if revision
        else git + ["ls-files", "-z"]
    )
    result = subprocess.run(command, capture_output=True, check=True)
    return [item for item in result.stdout.decode("utf-8").split("\0") if item]


def duplicates(paths: list[str]) -> dict[str, list[str]]:
    """Paths grouped by their NFC form, keeping only the groups with two or more."""

    grouped: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        grouped[unicodedata.normalize("NFC", path)].append(path)
    return {key: value for key, value in grouped.items() if len(value) > 1}


def decomposed(paths: list[str]) -> list[str]:
    """Tracked paths that are not in the canonical NFC form."""

    return [path for path in paths if path != unicodedata.normalize("NFC", path)]


def _shown(path: str) -> str:
    """The path, with its non-ASCII characters spelled out as code points."""

    marks = "".join(
        f"U+{ord(character):04X} " for character in path if not character.isascii()
    )
    return f"{path}\n      code points: {marks.strip()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revision",
        default=None,
        help="check a revision's tree instead of the index (e.g. origin/main)",
    )
    arguments = parser.parse_args(argv)

    paths = tracked_paths(arguments.revision)
    collisions = duplicates(paths)
    stragglers = [item for item in decomposed(paths) if item not in sum(collisions.values(), [])]

    if collisions:
        print(
            f"paths: {len(paths)} tracked, "
            f"{len(collisions)} normalization-equivalent duplicate group(s)\n"
        )
        for group in collisions.values():
            print("  the same file is tracked under two spellings:")
            for path in group:
                form = (
                    "NFC" if path == unicodedata.normalize("NFC", path) else "NFD"
                )
                print(f"    [{form}] {_shown(path)}")
            print()
        print(
            "Keep the NFC spelling and drop the other:\n"
            "  git -c core.precomposeunicode=false rm --cached -- '<the NFD path>'\n"
            "The file on disk is untouched; only the duplicate index entry goes."
        )
        return 1

    if stragglers:
        print(f"paths: {len(paths)} tracked, {len(stragglers)} not in NFC\n")
        for path in stragglers:
            print(f"  [NFD] {_shown(path)}")
        print(
            "\nThese are not duplicates yet, but a macOS worktree will add their\n"
            "precomposed twins and make them duplicates. Re-add them as NFC."
        )
        return 1

    print(f"paths: {len(paths)} tracked, all NFC, no normalization duplicates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
