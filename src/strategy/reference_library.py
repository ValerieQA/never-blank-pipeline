"""ENGINE: the Reference Library, the examples S-11 attaches to an approved plan.

Step 2 §3 lists the Reference Library among S-11's inputs, and Step 1 §4 makes
``E-14.exemplars`` "a list of (reference library item ID, 'take' note, 'do not
copy' note)" — empty in the S-10 draft, filled in the approved version. This is
the input side of that sentence: the client's reference documents, indexed by
**item IDs** an exemplar can name, loaded into the typed value S-11's lookup
reads. A document on disk that nothing loads is not an input, whatever the
contract lists.

It is **configuration**, the way a Client Contract and the Audience Profile are:
documents the client writes, read from the active client's directory
(``NB_CLIENT_DIR``), validated on load, produced by no stage and changed by no
run.

The index, not the documents
----------------------------
``editorial/reference/library.md`` names the items; the documents it points at
are the client's editorial source of truth and are not parsed here. An item is
one row: an ID, the destination and format it is an example *for*, the take
note, the do-not-copy note, and the document it is in. The notes travel with
the item rather than with the plan that borrowed it — an example handed to a
Writer without the second note is a template, which is the thing a reference
library exists not to be.

The IDs are stable because they are written down
------------------------------------------------
``REF-<nnn>`` carries nothing it could contradict: not the destination, not the
format, not the row's position. An item re-pointed at another destination,
re-worded or moved in the table keeps its name, and a library that gains an item
renumbers nothing — so an ``E-14.exemplars`` entry recorded by an earlier run
still names the same item. This module never assigns an ID; it reads the one the
keeper wrote, and refuses two rows that claim the same one.

Absent degrades, broken does not
--------------------------------
The library is a soft input: a client that has not written one runs without
exemplars, and S-11 records the absence rather than the plan losing its examples
silently (``reference_library_unavailable``, ``DEGRADE``). A library that *is*
there and cannot be read is a different fact and stops the run, for the reason
every other client document does (``docs/engine/CLIENT_CONTRACTS.md``, "Refused,
never guessed"): degrading on a malformed index would strip the exemplars out of
every plan of every run and say nothing about why.

Sources: ``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §4 (E-14
``exemplars``); ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §3
(S-11 Inputs); ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md``
§319.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Optional

from src.editorial_core.destinations import Destination
from src.editorial_core.executable_plan import Exemplar, PlanFormat
from src.knowledge.markdown import Document, DocumentError, load_document, parse_table
from src.strategy.client_contracts import client_dir

#: The client's library index, relative to the active client's directory. One
#: per client: two indexes over one shelf is two answers to "which item is
#: REF-002".
LIBRARY_FILE: Final[str] = "editorial/reference/library.md"

#: Front matter: which library this is, and which version of it. What it *says*
#: is the table below.
_FIELDS: Final[tuple[str, ...]] = ("library_id", "version")

_ITEMS_SECTION: Final[str] = "Items"

_COLUMNS: Final[tuple[str, ...]] = (
    "Item ID",
    "Destination",
    "Format",
    "Take",
    "Do not copy",
    "Source",
)

#: ``REF-`` and a number. Deliberately not ``REF-<destination>-<n>``: an ID that
#: spells out a fact about the item is an ID that has to change when the fact
#: does, and an exemplar recorded against the old spelling would then name
#: nothing.
_ITEM_ID = re.compile(r"^REF-[0-9]{3}$")


class ReferenceLibraryError(ValueError):
    """The Reference Library is there and cannot be read as one."""


@dataclass(frozen=True, slots=True)
class ReferenceItem:
    """One Reference Library item, as the exemplar lookup reads it (§3, Inputs).

    The take and do-not-copy notes belong to the item and not to the plan that
    borrowed it: an example handed to a Writer without the second note is a
    template, which is the thing the reference library exists not to be.
    """

    item_id: str
    destination: Destination
    format: PlanFormat
    take: str
    do_not_copy: str
    #: The document in the reference directory this item is an example from.
    source: str

    def __post_init__(self) -> None:
        if not _ITEM_ID.match(self.item_id):
            raise ReferenceLibraryError(
                f"{self.item_id!r} is not a reference library item ID; an item "
                "is `REF-` and three digits, and an ID that spelled out the "
                "destination or the row number would have to change when those "
                "did — which is an exemplar reference breaking on an edit"
            )
        if not self.take.strip() or not self.do_not_copy.strip():
            raise ReferenceLibraryError(
                f"{self.item_id} carries no take note or no do-not-copy note; "
                "both travel with the item, and one without the other is an "
                "example nobody bounded"
            )
        if not self.source.strip():
            raise ReferenceLibraryError(
                f"{self.item_id} names no document; an example is an example "
                "from something"
            )
        if (
            "/" in self.source
            or "\\" in self.source
            or self.source.strip() in {".", ".."}
        ):
            raise ReferenceLibraryError(
                f"{self.item_id} names {self.source!r}; an item's document is a "
                "file of the reference directory, named directly, and a path "
                "out of it is a library reaching somewhere it does not own"
            )

    def as_exemplar(self) -> Exemplar:
        """This item as the ``E-14.exemplars`` entry S-11 attaches."""

        return Exemplar(
            item_id=self.item_id, take=self.take, do_not_copy=self.do_not_copy
        )


@dataclass(frozen=True, slots=True)
class ReferenceLibrary:
    """One client's Reference Library, as S-11 is handed it.

    Two states, and they are not the same state. A library that was read carries
    its identity, its items and the digest of what was read; one that is not
    there carries ``unavailable_reason`` and no identity at all — the asymmetry
    the run manifest's input versions already use (#336), for the same reason:
    an input nobody read must not arrive looking like one that was read and said
    nothing.

    ``items`` is never empty in the first state — a ``## Items`` table with no
    rows is refused on load — so "the library has no example for this surface"
    and "there is no library" cannot be confused by looking at the list.
    """

    library_id: str
    version: str
    items: tuple[ReferenceItem, ...]
    path: str
    #: ``sha256:<hex>`` over the index as it was read. Absent exactly when the
    #: library is.
    digest: Optional[str] = None
    #: Why there was nothing to read. Set exactly when the library is absent.
    unavailable_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if (self.digest is None) == (self.unavailable_reason is None):
            raise ReferenceLibraryError(
                f"{self.path}: a Reference Library either carries the digest of "
                "what was read or says why it has none, and this one does "
                f"{'both' if self.digest is not None else 'neither'}"
            )
        if self.unavailable_reason is not None:
            self._absent_and_says_so()
            return
        if not self.library_id.strip() or not self.version.strip():
            raise ReferenceLibraryError(
                f"{self.path}: a library that was read is named and versioned; "
                "an exemplar recorded against an unnamed library cannot be "
                "resolved against the right one later"
            )
        if not self.items:
            raise ReferenceLibraryError(
                f"{self.path}: holds no item; an empty library and an absent one "
                "are different facts, and a library read as empty would make the "
                "second look like the first"
            )
        named = [item.item_id for item in self.items]
        repeated = sorted({name for name in named if named.count(name) > 1})
        if repeated:
            raise ReferenceLibraryError(
                f"{self.path}: " + ", ".join(repeated) + " names two items; an "
                "item ID is what an exemplar resolves through, and one that "
                "resolves to two things resolves to neither"
            )

    def _absent_and_says_so(self) -> None:
        if not self.unavailable_reason or not self.unavailable_reason.strip():
            raise ReferenceLibraryError(
                f"{self.path}: an absent library states why it is absent, and a "
                "blank reason states nothing"
            )
        if self.items or self.library_id or self.version:
            raise ReferenceLibraryError(
                f"{self.path}: a library the run did not read has nothing to "
                "identify and no item to offer"
            )

    @property
    def available(self) -> bool:
        """Was there a library to read at all?"""

        return self.unavailable_reason is None

    def item(self, item_id: str) -> Optional[ReferenceItem]:
        """The item with this ID, or ``None`` where this library has none.

        Refuses to answer for a library that was not read. ``None`` means "this
        library holds no such item", which is a statement about a shelf somebody
        looked at; a library nobody could open has made no statement, and
        returning ``None`` for it would turn "cannot say" into "no".
        """

        if not self.available:
            raise ReferenceLibraryError(
                f"{self.path}: {self.unavailable_reason}; nothing was read, so "
                f"whether {item_id} is in it is not a question this answers"
            )
        for item in self.items:
            if item.item_id == item_id:
                return item
        return None

    def resolve(self, exemplar: Exemplar) -> ReferenceItem:
        """The library item one ``E-14.exemplars`` entry names.

        What makes an exemplar a reference rather than a pair of notes: the ID
        it carries is resolvable back to the item the notes came from, or it is
        refused here.
        """

        found = self.item(exemplar.item_id)
        if found is None:
            raise ReferenceLibraryError(
                f"{self.path}: the exemplar names {exemplar.item_id}, which is "
                "not an item of this library; an exemplar that resolves to "
                "nothing is a note the Writer cannot go back to"
            )
        return found

    @classmethod
    def unavailable(cls, path: str, reason: str) -> "ReferenceLibrary":
        """A library there was nothing to read — the soft-input state."""

        return cls(
            library_id="",
            version="",
            items=(),
            path=path,
            unavailable_reason=reason,
        )


def parse_reference_library(document: Document) -> ReferenceLibrary:
    """Read one library index. Raises :class:`ReferenceLibraryError`."""

    path = document.path
    missing = [name for name in _FIELDS if document.field(name) is None]
    if missing:
        raise ReferenceLibraryError(
            f"{path}: front matter is missing {', '.join(missing)}"
        )
    unknown = sorted(set(document.field_names) - set(_FIELDS))
    if unknown:
        raise ReferenceLibraryError(
            f"{path}: front matter has no field {', '.join(unknown)}; a "
            f"Reference Library declares {' and '.join(_FIELDS)}"
        )

    body = document.section(_ITEMS_SECTION)
    if body is None:
        raise ReferenceLibraryError(
            f"{path}: no `## {_ITEMS_SECTION}` section; that is where the library "
            "says which item is which"
        )
    try:
        rows = parse_table(body, path=path, section=_ITEMS_SECTION, columns=_COLUMNS)
    except DocumentError as exc:
        raise ReferenceLibraryError(str(exc)) from exc

    items = tuple(_item(row, path=path) for row in rows)
    return ReferenceLibrary(
        library_id=document.field("library_id") or "",
        version=document.field("version") or "",
        items=items,
        path=path,
        digest=document.digest,
    )


def load_reference_library(path: Path) -> ReferenceLibrary:
    """Read one library index and the documents it points at.

    The sources are checked here rather than in :func:`parse_reference_library`
    because only a path knows where the reference directory is. An item naming a
    document that is not beside the index is refused: the chain this module
    exists to make real runs from the artifact to the plan, and an item pointing
    at nothing is a note about a document rather than a reference to one.

    Raises :class:`ReferenceLibraryError`.
    """

    try:
        document = load_document(path)
    except DocumentError as exc:
        raise ReferenceLibraryError(str(exc)) from exc
    library = parse_reference_library(document)
    for item in library.items:
        if not (path.parent / item.source).is_file():
            raise ReferenceLibraryError(
                f"{library.path}: {item.item_id} is an example from "
                f"{item.source!r}, which is not in {path.parent}; an item "
                "pointing at a document nobody can open is a note about one"
            )
    return library


def reference_library(*, directory: Optional[Path] = None) -> ReferenceLibrary:
    """The active client's Reference Library, or the stated absence of one.

    The soft-input entry point: a client with no index runs without exemplars
    and S-11 records that it did. An index that exists and does not load raises
    — it is a keeper error, not a client that has not written one yet.
    """

    root = directory if directory is not None else client_dir()
    path = root / LIBRARY_FILE
    if not path.is_file():
        return ReferenceLibrary.unavailable(
            str(path),
            "this client has no Reference Library index; S-11 approves plans "
            "without exemplars",
        )
    return load_reference_library(path)


def _item(row: tuple[str, ...], *, path: str) -> ReferenceItem:
    """One table row as an item. Raises :class:`ReferenceLibraryError`."""

    item_id, destination, plan_format = row[0], row[1], row[2]
    take, do_not_copy, source = row[3], row[4], row[5]
    try:
        return ReferenceItem(
            item_id=item_id,
            destination=Destination(destination),
            format=PlanFormat(plan_format),
            take=take,
            do_not_copy=do_not_copy,
            source=source,
        )
    except ValueError as exc:
        if isinstance(exc, ReferenceLibraryError):
            raise ReferenceLibraryError(f"{path}: {exc}") from exc
        raise ReferenceLibraryError(
            f"{path}: {item_id or 'an item'} is for destination "
            f"{destination!r} in format {plan_format!r}; the destinations are "
            + " / ".join(member.value for member in Destination)
            + " and the formats are "
            + " / ".join(member.value for member in PlanFormat)
        ) from exc
