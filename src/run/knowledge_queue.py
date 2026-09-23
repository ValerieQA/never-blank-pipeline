"""The knowledge queue: what the keeper is asked to decide (Issue #297, SL-2).

Step 3 §3.2 gives the durable ledger one file per KnowledgeQueueItem, under
``data/editorial/knowledge_queue/<item_id>.json``, and patch S4-R1 splits the
producers by kind: **S-15** writes ``observation`` and ``vt02_feedback`` items
from a finished run, and the **Knowledge Maintenance job** (offline, scheduled,
`src/knowledge/maintenance.py`) writes ``expiry_review`` items. Each kind has
exactly one producer, so this module holds the record and never the producing.

Why the id is derived and not allocated
---------------------------------------
§5.2 asks for "one KnowledgeQueueItem per record per expiry, never one per
run". A job that allocated a fresh id on every scheduled pass would ask the
keeper the same question once a day until they answered it, which is how a
queue stops being read. So the id of an expiry item is a function of exactly
what makes it one question — the record and the `review_by` that fell due
(:meth:`ExpiryReviewItem.identity_for`). Tomorrow's pass computes the same id,
the create-once ledger write refuses the path, and one expiry stays one item.

A **new** `review_by` is a new id. That is the other half of the same rule: a
record the keeper re-reviewed comes back into the queue when its next review
falls due, and nothing has to remember that it was ever there.

Public-safe by shape (§3.3, P9)
-------------------------------
The ledger is committed to a public repository. §3.3 enforces that on a
RunSummary twice, in the shape of the record and again with a validator over
the serialized values, because a RunSummary has fields a caller could put a
sentence in. This record has none: every field is a closed vocabulary, a date,
a bounded count, or an identifier the register's own id format already fixes.
There is no free text for a second pass to find.

Which is why an item names the record and not the file it is in. The path would
be the one open string here, and a client rule's path names the client — while
the record id and ``source`` say everything the keeper needs in order to find
it, in terms the ledger can hold.

Sources: ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md``
§3.2 and §3.3; ``docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md``
§5 and §5.2, with patch ``PATCH_S4R1_STEP4.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic import ValidationError as _PydanticValidationError

from src.editorial_core.arp import KnowledgeStatus, KnowledgeTier
from src.run.ledger import write_record

#: Schema version of this record shape.
SCHEMA_VERSION = "1.0"

#: ``data/editorial/knowledge_queue/<item_id>.json`` (§3.2). Flat, because a
#: queue item belongs to the keeper and not to a client or a month: the two
#: producers write into one queue, which is the thing the keeper works through.
QUEUE_DIRECTORY = "knowledge_queue"

#: The alphabet the ledger draws an identifier from, as ``run_summary.py`` sets
#: it out: a field that takes an identifier takes an identifier, and not a
#: phrase that happens to have no space in it.
_IDENTIFIER_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9._+-]*$"

_Identifier = Annotated[str, StringConstraints(pattern=_IDENTIFIER_PATTERN)]

#: The two file statuses expiry demotes (§5), as ``arp.py`` holds them for a
#: KnowledgeRef. Every other status stays in force and is flagged instead,
#: because dropping a rule nobody re-checked is the unsafe direction.
_DEMOTABLE_STATUSES = frozenset({
    KnowledgeStatus.DESCRIPTIVE,
    KnowledgeStatus.CANDIDATE,
})


class KnowledgeQueueError(ValueError):
    """A queue item was asked for something its contract refuses."""


class QueueItemKind(str, Enum):
    """The closed kind vocabulary, and the producer split of patch S4-R1.

    ``OBSERVATION`` and ``VT02_FEEDBACK`` are S-15's and arrive with the slice
    that builds it; they are named here because the split is what makes each
    kind have exactly one producer, and a vocabulary with one member would say
    the maintenance job owns the whole queue.
    """

    OBSERVATION = "observation"
    VT02_FEEDBACK = "vt02_feedback"
    EXPIRY_REVIEW = "expiry_review"


class RegisterRecordKind(str, Enum):
    """Which of the two register formats the item is about (§2, §3)."""

    KNOWLEDGE = "knowledge"
    CHECK = "check"


class RegisterSource(str, Enum):
    """Where the file lives: the universal register, or a client folder (§1).

    Client rules stay with the client, so "the register" alone would not name
    every file §5.2 asks the job to scan — and a keeper reading the queue needs
    to know which of the two authorities a record belongs to.
    """

    REGISTER = "register"
    CLIENT = "client"


class KnowledgeQueueItem(BaseModel):
    """One question in the keeper's offline queue (§3.2).

    What every item has, whichever producer raised it. The kind says what it
    is about and the subclass carries what that kind needs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SCHEMA_VERSION
    item_id: _Identifier
    kind: QueueItemKind
    #: The day the producer raised it.
    raised_on: date

    @field_validator("schema_version", mode="after")
    @classmethod
    def _schema_version_known(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {SCHEMA_VERSION!r}; got {value!r}"
            )
        return value

    def relative_path(self) -> str:
        """``knowledge_queue/<item_id>.json`` (§3.2)."""

        return f"{QUEUE_DIRECTORY}/{self.item_id}.json"

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible: enums as values, dates as ISO-8601."""

        return self.model_dump(mode="json")


class ExpiryReviewItem(KnowledgeQueueItem):
    """A record whose review has fallen due, for the keeper to decide (§5.2).

    It asks for a decision and takes none: I-02 puts every status change with
    the keeper, offline, and §5.2 scopes this job out of "changing any
    knowledge status". What the item carries is what the record was on the day
    the review fell due — the status in the file, what §5 made of it, and the
    `review_by` that lapsed — so the keeper can see whether the expiry demoted
    the record or left a rule enforced without anybody re-checking it.
    """

    kind: QueueItemKind = QueueItemKind.EXPIRY_REVIEW
    record_id: _Identifier
    record_version: int = Field(ge=1)
    record_kind: RegisterRecordKind
    source: RegisterSource
    #: The `review_by` this item is about. With the record id, it is the
    #: identity of one expiry (:meth:`identity_for`).
    review_by: date
    #: The status the keeper wrote in the file.
    file_status: KnowledgeStatus
    #: What §5 makes of the record on :attr:`raised_on`. Equal to the file
    #: status until expiry demotes a `descriptive` or a `candidate`.
    effective_status: KnowledgeStatus
    #: Absent for a check record, which has a rule status and no tier (§3).
    tier: Optional[KnowledgeTier] = None
    #: True when `review_by` had already passed; false inside the warning
    #: window, where the item is raised early so the review can happen before
    #: the record loses its weight.
    expired: bool

    @staticmethod
    def identity_for(record_id: str, review_by: date) -> str:
        """The id of the one item for this record and this expiry (§5.2)."""

        return (
            f"KQ-{QueueItemKind.EXPIRY_REVIEW.value}-{record_id}-"
            f"{review_by.isoformat()}"
        )

    @model_validator(mode="after")
    def _one_expiry_of_one_record(self) -> "ExpiryReviewItem":
        if self.kind is not QueueItemKind.EXPIRY_REVIEW:
            raise ValueError(
                "an expiry review item is of kind "
                f"{QueueItemKind.EXPIRY_REVIEW.value!r}; got {self.kind.value!r}, "
                "and each kind of §3.2 has exactly one producer"
            )
        expected = self.identity_for(self.record_id, self.review_by)
        if self.item_id != expected:
            raise ValueError(
                f"item_id is {self.item_id!r} and the record and expiry make it "
                f"{expected!r}; the id is derived so that one expiry of one "
                "record is one item however often the job runs (§5.2)"
            )
        if self.expired != (self.review_by < self.raised_on):
            raise ValueError(
                f"{self.record_id} is recorded as "
                f"{'expired' if self.expired else 'not expired'} with "
                f"review_by {self.review_by.isoformat()} on "
                f"{self.raised_on.isoformat()}; expiry is the comparison, not a "
                "second opinion about it"
            )
        if self.file_status is KnowledgeStatus.WEAK_CANDIDATE:
            raise ValueError(
                f"{self.record_id} claims weak-candidate as its file status; "
                "that status is computed from `review_by` and is never written "
                "in a file (§2.3)"
            )
        if self.file_status is KnowledgeStatus.RETIRED:
            raise ValueError(
                f"{self.record_id} is retired, and a retired record is kept for "
                "traceability and never loaded into a run (§2.3): asking the "
                "keeper to re-review one is asking about a record they closed"
            )
        if self.effective_status != self.file_status and not (
            self.effective_status is KnowledgeStatus.WEAK_CANDIDATE
            and self.expired
            # The demotion is the loader's, and the loader makes it for an
            # expired knowledge record of a demotable status and for nothing
            # else: a check keeps its `rule_status` however long it has gone
            # unreviewed (§3, §5), so a check demoted here is an item that
            # tells the keeper a rule stopped applying when it did not.
            and self.record_kind is RegisterRecordKind.KNOWLEDGE
            and self.file_status in _DEMOTABLE_STATUSES
        ):
            raise ValueError(
                f"{self.record_id} is {self.file_status.value} in its file and "
                f"{self.effective_status.value} here; §5 demotes an expired "
                "`descriptive` or `candidate` knowledge record and leaves every "
                "other status, and every check, as written"
            )
        if self.record_kind is RegisterRecordKind.CHECK and self.tier is not None:
            raise ValueError(
                f"{self.record_id} is a check record and carries tier "
                f"{self.tier.value}; a check has a rule status and a class, and "
                "no tier (§3)"
            )
        if self.record_kind is RegisterRecordKind.KNOWLEDGE and self.tier is None:
            raise ValueError(
                f"{self.record_id} is a knowledge record with no tier; every "
                "record has exactly one, and the keeper reads the queue by what "
                "the expiry costs (§2.2)"
            )
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExpiryReviewItem":
        """Strictly reload one item (P7), or say what is wrong with it."""

        if not isinstance(data, Mapping):
            raise KnowledgeQueueError(
                "ExpiryReviewItem.from_dict expects a mapping; got "
                f"{type(data).__name__}"
            )
        try:
            return cls.model_validate(dict(data))
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            loc = " -> ".join(str(x) for x in first["loc"]) if first["loc"] else "value"
            raise KnowledgeQueueError(
                f"knowledge queue item field '{loc}': {first['msg']}"
            ) from exc


def write_queue_item(
    item: KnowledgeQueueItem, *, root: Optional[Path] = None
) -> Path:
    """Write one queue item into the durable ledger and return its path.

    One record, one file (P4), create-once (P1) — which is what makes the
    derived id of §5.2 into idempotency rather than into a convention: the
    second write of the same expiry raises
    :class:`~src.artifacts.ArtifactCollisionError`, and the producer is the one
    that decides that an item already queued is not an error.
    """

    return write_record(item.relative_path(), item.to_dict(), root=root)
