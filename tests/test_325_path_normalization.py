"""No two tracked paths may differ only by Unicode normalization (#325).

Why this needs a check and not just a cleanup
---------------------------------------------
macOS stores `ресёрч` decomposed and git precomposes it when reading the
directory (`core.precomposeunicode=true`, the default there). Once a decomposed
spelling is committed, the index holds two entries for one file — and on macOS
`git status` stays **clean**, because the normalization-insensitive filesystem
satisfies both from the single file on disk. The duplicate is therefore invisible
exactly where it is created, and shows up as two copies on a Linux checkout.

That is why cleaning it three times (#321, #288, #289) did not hold: any
`git add -A` in a worktree still holding the other spelling puts it back.
"""

from __future__ import annotations

import subprocess
import unicodedata
from pathlib import Path

import pytest

from scripts.ci.check_path_normalization import (
    decomposed,
    duplicates,
    main,
    tracked_paths,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: The decomposed and precomposed spellings of one name, as macOS and git see it.
#: `и` + U+0306 against `й`, and `е` + U+0308 against `ё` — indistinguishable on
#: screen, which is the whole difficulty.
NFD_NAME = "ресёрч.md"
NFC_NAME = "ресёрч.md"


def test_the_two_spellings_really_are_indistinguishable_but_different():
    """The premise: same displayed name, different bytes, same NFC form."""

    assert NFD_NAME != NFC_NAME
    assert unicodedata.normalize("NFC", NFD_NAME) == NFC_NAME
    assert NFD_NAME == unicodedata.normalize("NFD", NFD_NAME)


def test_a_normalization_equivalent_pair_is_reported_as_a_duplicate():
    found = duplicates([f"a/{NFD_NAME}", f"a/{NFC_NAME}", "a/plain.md"])

    assert len(found) == 1
    group = next(iter(found.values()))
    assert sorted(group) == sorted([f"a/{NFD_NAME}", f"a/{NFC_NAME}"])


def test_paths_that_differ_by_more_than_normalization_are_not_duplicates():
    assert duplicates([f"a/{NFC_NAME}", f"b/{NFC_NAME}", "a/other.md"]) == {}


def test_a_lone_decomposed_path_is_caught_before_it_becomes_a_duplicate():
    """It is not a duplicate yet; a macOS worktree will make it one."""

    assert decomposed([f"a/{NFD_NAME}", "a/plain.md"]) == [f"a/{NFD_NAME}"]
    assert decomposed([f"a/{NFC_NAME}", "a/plain.md"]) == []


# ── the repository itself ──────────────────────────────────────────────────


def test_this_repository_tracks_no_normalization_duplicate():
    """The acceptance: exactly one spelling of every path is tracked."""

    paths = tracked_paths()

    assert paths
    assert duplicates(paths) == {}
    assert decomposed(paths) == []


def test_the_client_docx_is_tracked_exactly_once():
    """The file this issue is about, and its content is not the subject.

    #325 asks for exactly one tracked copy with the content unchanged, so this
    asserts the count and the single blob rather than anything about the document.
    """

    listed = subprocess.run(
        [
            "git",
            "-c",
            "core.quotepath=false",
            "-c",
            "core.precomposeunicode=false",
            "ls-files",
            "-s",
            "-z",
            "--",
            "clients/never_blank/editorial/reference/",
        ],
        capture_output=True,
        check=True,
        cwd=_REPO_ROOT,
    )
    rows = [row for row in listed.stdout.decode("utf-8").split("\0") if row]
    docx = [row for row in rows if row.endswith(".docx")]

    assert len(docx) == 1
    assert unicodedata.normalize("NFC", docx[0]) == docx[0]


def test_the_check_fails_on_a_tree_that_still_holds_the_duplicate():
    """Driven against a revision, so the failing case is a real one.

    `origin/main` carries the duplicate until this lands, which makes it the one
    honest way to prove the check catches it. Once it is merged the duplicate is
    gone from `main`, and this test then asserts the same thing the repository-wide
    test does — so it is written to accept either answer rather than to fail the
    day it succeeds.
    """

    available = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "origin/main"],
        capture_output=True,
        cwd=_REPO_ROOT,
    )
    if available.returncode != 0:
        pytest.skip("no origin/main in this checkout")

    on_main = tracked_paths("origin/main")
    if duplicates(on_main):
        assert main(["--revision", "origin/main"]) == 1
    else:
        assert main(["--revision", "origin/main"]) == 0


def test_the_check_passes_on_the_index_it_is_shipped_with():
    assert main([]) == 0
