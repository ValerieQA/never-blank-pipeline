"""Issue #338: the Reference Library — item IDs, loader, S-11 consumption.

Step 2 §3 lists the Reference Library among S-11's inputs and Step 1 §4 makes
`E-14.exemplars` "a list of (reference library item ID, 'take' note, 'do not
copy' note)". Before this slice the documents were on disk and nothing read
them: `exemplars` could only ever be filled by a caller that had built the items
itself, and no item had an ID an exemplar could name.

Four claims, each of which has to be able to fail:

- **The whole chain runs.** The client's own `editorial/reference/library.md`
  loads into typed items, `check_plan` is handed them, and the approved plan
  comes out carrying an exemplar that names a real item ID with that item's two
  notes. These tests read the client artifact rather than a fixture copy of it,
  so a library that stops loading fails here.
- **An exemplar resolves back.** The ID on an approved plan is resolvable to the
  library item it came from, or it is not a reference.
- **Absent degrades, and says so.** With no library the plan is still approved,
  with no exemplars, and the run records `reference_library_unavailable` as a
  `DEGRADE`. A library that *was* read and holds nothing for the surface records
  nothing — the two are different facts, and neither is allowed to look like the
  other.
- **The IDs are stable.** An item keeps its ID when the library gains an item,
  when the table is reordered and when the item's own fields change, so an
  exemplar an earlier run recorded still names the same item.

No network, no model.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from src.editorial_core.arp import (
    ArpOutcome,
    OutcomeScope,
    StateCode,
    permitted_outcomes,
)
from src.editorial_core.destinations import Destination, destination_scope_key
from src.editorial_core.executable_plan import Exemplar, PlanFormat
from src.editorial_core.plan_check import select_exemplars
from src.run.run_summary import ReasonCategory, reason_category
from src.strategy.client_contracts import DEFAULT_CLIENT_DIR
from src.strategy.reference_library import (
    LIBRARY_FILE,
    ReferenceItem,
    ReferenceLibrary,
    ReferenceLibraryError,
    load_reference_library,
    reference_library,
)
from tests.test_305_executable_plan_and_check import _checked

_REPO_ROOT = Path(__file__).resolve().parents[1]

NEVER_BLANK = _REPO_ROOT / DEFAULT_CLIENT_DIR

#: What `_checked` drafts by default, and therefore what an exemplar selected
#: for it has to be an example for.
DRAFTED = (Destination.LINKEDIN, PlanFormat.POST)

#: One valid row, as the columns take it. Tests vary one cell at a time.
_ROW = (
    "REF-001",
    "linkedin",
    "post",
    "the first line that names one figure",
    "the closing question",
    "posts.md",
)


@pytest.fixture(scope="module")
def never_blank() -> ReferenceLibrary:
    """The client's real directory, as a run would read it today."""

    return reference_library(directory=NEVER_BLANK)


def _write(
    directory: Path, rows: Sequence[Sequence[str]], *, sources: bool = True
) -> Path:
    """A library index in ``directory``, with the documents its rows name."""

    directory.mkdir(parents=True, exist_ok=True)
    header = (
        "| Item ID | Destination | Format | Take | Do not copy | Source |\n"
        "|---|---|---|---|---|---|\n"
    )
    body = "".join("| " + " | ".join(row) + " |\n" for row in rows)
    path = directory / "library.md"
    path.write_text(
        "---\nlibrary_id: fixture\nversion: 1\n---\n\n"
        "# Reference Library\n\n## Items\n\n" + header + body,
        encoding="utf-8",
    )
    if sources:
        for row in rows:
            (directory / row[-1]).write_text("an example\n", encoding="utf-8")
    return path


def _loaded(tmp_path: Path, rows: Sequence[Sequence[str]]) -> ReferenceLibrary:
    return load_reference_library(_write(tmp_path / "reference", rows))


# ── the client has no library yet, and that is a state ────────────────────


def test_never_blank_has_no_reference_library_and_the_run_records_why(
    never_blank: ReferenceLibrary,
):
    """The honest state of this client today (#338 repair).

    `clients/never_blank/editorial/reference/` holds research material about
    readability — the source the architecture was written from — and **no
    exemplar texts**. An exemplar is a reference a Writer learns register and
    form from (`K-EXM-01`); a research note about form is not one, and indexing
    those documents as items would hand S-11 exemplars this product does not
    have.

    So Never Blank goes through the supported absent path, which the loader
    keeps distinct from an empty index: an empty one is refused loudly, and
    absence states its reason. Authoring a real corpus is editorial content
    work with its own timeline, not something a loader can produce.
    """

    assert not never_blank.available
    assert never_blank.unavailable_reason
    assert never_blank.digest is None
    assert never_blank.items == ()
    assert never_blank.library_id == ""
    assert never_blank.version == ""


def test_an_exemplar_cannot_be_resolved_against_a_library_that_was_never_read(
    never_blank: ReferenceLibrary,
):
    """An absent library answers no question about items (I-03 in spirit)."""

    with pytest.raises(ReferenceLibraryError):
        never_blank.resolve(
            Exemplar(item_id="REF-999", take="anything", do_not_copy="anything")
        )


def test_an_exemplar_the_library_does_not_hold_is_refused(tmp_path: Path):
    """The same refusal on a library that *was* read — proven synthetically.

    The mechanism is proven on a fixture rather than on the client's artifact,
    because this product has no exemplar corpus to prove it on.
    """

    library = _loaded(tmp_path, [_ROW])

    with pytest.raises(ReferenceLibraryError, match="REF-999"):
        library.resolve(
            Exemplar(item_id="REF-999", take="anything", do_not_copy="anything")
        )


def test_only_items_for_this_destination_and_format_are_attached(tmp_path: Path):
    destination, plan_format = DRAFTED
    library = _loaded(
        tmp_path,
        [
            _ROW,
            ("REF-002", "wix", "article", "the deck", "the summary box", "long.md"),
            (
                "REF-003",
                destination.value,
                "carousel",
                "the slide break",
                "the cover",
                "slides.md",
            ),
        ],
    )

    _, _, decision = _checked(library=library)

    approved = decision.approved
    assert approved is not None
    assert [item.item_id for item in approved.exemplars] == ["REF-001"]
    assert all(
        library.resolve(exemplar).format is plan_format
        for exemplar in approved.exemplars
    )


# ── absent degrades, empty does not ────────────────────────────────────────


def test_a_client_with_no_library_index_gets_the_absence_and_not_an_error(
    tmp_path: Path,
):
    library = reference_library(directory=tmp_path)

    assert not library.available
    assert library.unavailable_reason
    assert library.digest is None
    assert library.items == ()


def test_an_absent_library_has_no_identity_to_record(tmp_path: Path):
    """An input nobody read must not arrive looking like one that was."""

    library = reference_library(directory=tmp_path)

    assert library.library_id == ""
    assert library.version == ""
    with pytest.raises(ReferenceLibraryError):
        ReferenceLibrary(
            library_id="invented",
            version="1",
            items=(),
            path="nowhere",
            unavailable_reason="there was none",
        )


def test_an_unavailable_library_will_not_say_whether_it_holds_an_item(
    tmp_path: Path,
):
    """Cannot say is not no: a shelf nobody opened has answered nothing."""

    library = reference_library(directory=tmp_path)

    with pytest.raises(ReferenceLibraryError, match="REF-001"):
        library.item("REF-001")


def test_an_absent_library_degrades_the_destination_and_the_run_records_it(
    tmp_path: Path,
):
    library = reference_library(directory=tmp_path)

    _, draft, decision = _checked(library=library)

    assert decision.passed
    approved = decision.approved
    assert approved is not None
    assert approved.exemplars == ()
    assert len(decision.outcomes) == 1
    degraded = decision.outcomes[0]
    assert degraded.outcome is ArpOutcome.DEGRADE
    assert degraded.state_code is StateCode.REFERENCE_LIBRARY_UNAVAILABLE
    assert degraded.scope is OutcomeScope.DESTINATION
    assert degraded.scope_key == destination_scope_key(
        draft.unit_id, draft.destination
    )
    assert degraded.reason


def test_a_stage_handed_no_library_at_all_records_the_same_absence():
    """The default is the degraded state, not a silent empty shelf."""

    _, _, decision = _checked(library=None)

    approved = decision.approved
    assert approved is not None
    assert approved.exemplars == ()
    assert [item.state_code for item in decision.outcomes] == [
        StateCode.REFERENCE_LIBRARY_UNAVAILABLE
    ]


def test_a_library_that_was_read_and_offers_nothing_records_nothing(
    tmp_path: Path,
):
    """The shelf answered, and the answer was none. That is not a degrade."""

    library = _loaded(
        tmp_path,
        [("REF-001", "wix", "article", "the deck", "the summary box", "long.md")],
    )

    _, _, decision = _checked(library=library)

    approved = decision.approved
    assert approved is not None
    assert approved.exemplars == ()
    assert decision.outcomes == ()


def test_the_lookup_itself_separates_the_two(tmp_path: Path):
    """Both ends at the seam S-11 calls, not only through the stage."""

    _, draft, _ = _checked(library=None)
    empty = _loaded(
        tmp_path,
        [("REF-001", "wix", "article", "the deck", "the summary box", "long.md")],
    )

    assert select_exemplars(draft, empty).degraded is None
    assert select_exemplars(draft, None).degraded is not None
    assert (
        select_exemplars(draft, reference_library(directory=tmp_path)).degraded
        is not None
    )


def test_the_degrade_is_bounded_and_counted():
    """A state the indicators cannot group is a degrade nobody reads."""

    assert permitted_outcomes(StateCode.REFERENCE_LIBRARY_UNAVAILABLE) == frozenset(
        {ArpOutcome.DEGRADE}
    )
    assert (
        reason_category(StateCode.REFERENCE_LIBRARY_UNAVAILABLE)
        is ReasonCategory.KNOWLEDGE
    )


# ── the IDs are stable ─────────────────────────────────────────────────────


def test_an_exemplar_survives_the_library_gaining_an_item(tmp_path: Path):
    """The acceptance claim: a reference does not break on a new row."""

    before = _loaded(tmp_path / "before", [_ROW])
    _, _, decision = _checked(library=before)
    approved = decision.approved
    assert approved is not None
    (recorded,) = approved.exemplars

    after = _loaded(
        tmp_path / "after",
        [
            ("REF-007", "linkedin", "post", "the second line", "the emoji", "new.md"),
            _ROW,
            ("REF-008", "wix", "article", "the deck", "the box", "long.md"),
        ],
    )

    still = after.resolve(recorded)
    assert still.item_id == recorded.item_id
    assert still.take == recorded.take
    assert still.do_not_copy == recorded.do_not_copy


def test_an_id_that_spelled_out_the_item_would_not_be_stable(tmp_path: Path):
    """`REF-LI-01` would have to change when the destination did."""

    with pytest.raises(ReferenceLibraryError, match="REF-LI-01"):
        _loaded(tmp_path, [("REF-LI-01", *_ROW[1:])])
    with pytest.raises(ReferenceLibraryError, match="K-EXM-LI-01"):
        _loaded(tmp_path / "second", [("K-EXM-LI-01", *_ROW[1:])])


def test_one_id_cannot_name_two_items(tmp_path: Path):
    with pytest.raises(ReferenceLibraryError, match="REF-001"):
        _loaded(
            tmp_path,
            [
                _ROW,
                ("REF-001", "wix", "article", "the deck", "the box", "long.md"),
            ],
        )


# ── refused, never guessed ─────────────────────────────────────────────────


def test_an_item_without_both_notes_is_refused(tmp_path: Path):
    """An example handed over without the second note is a template."""

    no_take = ("REF-001", "linkedin", "post", "", "the closing question", "p.md")
    no_stop = ("REF-001", "linkedin", "post", "the first line", "", "p.md")
    with pytest.raises(ReferenceLibraryError, match="REF-001"):
        _loaded(tmp_path / "no-take", [no_take])
    with pytest.raises(ReferenceLibraryError, match="REF-001"):
        _loaded(tmp_path / "no-stop", [no_stop])


def test_an_item_for_a_surface_the_engine_does_not_have_is_refused(tmp_path: Path):
    with pytest.raises(ReferenceLibraryError, match="mastodon"):
        _loaded(tmp_path / "destination", [("REF-001", "mastodon", *_ROW[2:])])
    with pytest.raises(ReferenceLibraryError, match="sonnet"):
        _loaded(
            tmp_path / "format",
            [("REF-001", "linkedin", "sonnet", *_ROW[3:])],
        )


def test_an_item_pointing_at_a_document_that_is_not_there_is_refused(
    tmp_path: Path,
):
    path = _write(tmp_path / "reference", [_ROW], sources=False)

    with pytest.raises(ReferenceLibraryError, match="posts.md"):
        load_reference_library(path)


def test_an_item_cannot_reach_out_of_the_reference_directory(tmp_path: Path):
    reaches = ("../secrets.md", "nested/posts.md", "..", "/etc/passwd")
    for index, reach in enumerate(reaches):
        path = _write(
            tmp_path / f"case{index}", [(*_ROW[:-1], reach)], sources=False
        )
        with pytest.raises(ReferenceLibraryError, match="REF-001"):
            load_reference_library(path)


def _at_the_configured_place(root: Path, text: str) -> None:
    """Put an index where ``reference_library`` looks for the client's."""

    path = root / LIBRARY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_library_that_is_there_and_will_not_load_stops_the_run(tmp_path: Path):
    """Absent is a client that has none; broken is a keeper error."""

    _at_the_configured_place(
        tmp_path,
        "---\nlibrary_id: fixture\nversion: 1\n---\n\n# Reference Library\n",
    )

    with pytest.raises(ReferenceLibraryError, match="Items"):
        reference_library(directory=tmp_path)


def test_a_library_without_its_front_matter_is_refused(tmp_path: Path):
    _at_the_configured_place(
        tmp_path,
        "---\nversion: 1\n---\n\n# Reference Library\n\n## Items\n\n"
        "| Item ID | Destination | Format | Take | Do not copy | Source |\n"
        "|---|---|---|---|---|---|\n"
        "| REF-001 | linkedin | post | a | b | posts.md |\n",
    )

    with pytest.raises(ReferenceLibraryError, match="library_id"):
        reference_library(directory=tmp_path)


def test_the_client_index_is_found_where_the_client_directory_says(tmp_path: Path):
    """Replace the client, replace the library: no Engine code changes."""

    _at_the_configured_place(
        tmp_path,
        "---\nlibrary_id: other-client\nversion: 3\n---\n\n"
        "# Reference Library\n\n## Items\n\n"
        "| Item ID | Destination | Format | Take | Do not copy | Source |\n"
        "|---|---|---|---|---|---|\n"
        "| REF-004 | telegram | channel_post | the lede | the sign-off | ch.md |\n",
    )
    (tmp_path / LIBRARY_FILE).parent.joinpath("ch.md").write_text(
        "an example\n", encoding="utf-8"
    )

    library = reference_library(directory=tmp_path)

    assert library.available
    assert library.library_id == "other-client"
    assert [item.item_id for item in library.items] == ["REF-004"]


def test_a_library_with_no_row_is_refused_rather_than_read_as_empty(tmp_path: Path):
    """Read-and-empty would be indistinguishable from never-read."""

    with pytest.raises(ReferenceLibraryError, match="no rows"):
        _loaded(tmp_path, [])


def test_an_item_that_is_read_is_the_item_the_row_wrote(tmp_path: Path):
    library = _loaded(tmp_path, [_ROW])

    assert library.items == (
        ReferenceItem(
            item_id="REF-001",
            destination=Destination.LINKEDIN,
            format=PlanFormat.POST,
            take="the first line that names one figure",
            do_not_copy="the closing question",
            source="posts.md",
        ),
    )
    assert library.item("REF-002") is None
