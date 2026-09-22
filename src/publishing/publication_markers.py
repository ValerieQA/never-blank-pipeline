"""The publication idempotency authority: intent and marker per destination.

A published post cannot be un-published, so "never publish the same thing
twice" cannot depend on any other commit succeeding. This module is the
durable authority invariant **S3-I1** requires (Step 3 §3.6): a committed,
per-destination store that every publishing path consults before an
irreversible call and writes to immediately after one succeeds.

The store::

    data/editorial/publication_markers/<client>/<destination>/<key>.json
    data/editorial/publication_markers/<client>/<destination>/<key>.intent.json

The **publication identity key** is ``(client, destination, sorted source
signal IDs)`` — deliberately with no article digest (Step 5 §1.1). One
publication per signal set per destination: rewriting the article is not a
licence to publish it to the same place a second time. That is the same
semantics ``data/research/published_signal_ids.txt`` already has, and stricter
than the digest-based key in :mod:`src.publishing.idempotency`.

The transaction a publishing path performs, per destination (Step 2, S-14 ARP):

1. **Lookup** — :meth:`PublicationGuard.check`. A marker means the publication
   exists: reuse it, call nothing. An intent without a marker means *possibly
   published*: ``SKIP`` (``publication_possibly_exists``). An authority that
   cannot answer: ``SKIP`` (``idempotency_authority_unavailable``). Fail
   closed, and never wait for a human.
2. **Intent** — :meth:`PublicationGuard.record_intent`, durable, *before* the
   external call. No durable intent, no call.
3. the external call.
4. **Marker** — :meth:`PublicationGuard.record_marker`, durable, immediately
   after that destination succeeded, written first and alone with its own
   retries, before and independently of the learning-ledger commit. When it
   cannot be made durable the run records ``publication_unconfirmed`` for the
   key and ends normally; the next run reads the intent and skips.

Semantics are **at most once**: a lost post is preferred to a duplicate. Every
ambiguity therefore resolves towards "possibly published" — the exact opposite
of :mod:`src.publishing.idempotency`, where unusable evidence must never
suppress an authorized publication. The two modules answer different
questions: that one asks *can I prove this was published?*, this one asks *can
I prove it was not?*

Clearing an unconfirmed key is offline maintenance (I-02): a person deletes
the intent file, or an authoritative external lookup confirms no publication
exists. Nothing inside a run clears one by assumption.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Iterable, Optional

from src.publishing.release_scope import (
    NON_R1_PUBLISH_CHANNELS,
    R1_PUBLISH_CHANNELS,
)
from src.publishing.result import PublishResult, PublishStatus, UrlProvenance
from src.strategy.client_contracts import client_dir

if TYPE_CHECKING:  # pragma: no cover — typing only, no import weight at runtime
    from src.publishing.base import DraftPackage

#: Every destination this authority keys — all six, composed from the release
#: scope lists rather than restated here, because a duplicated list drifts
#: (#227). A marker is evidence, not an authorization: release scope decides
#: what a run *may* publish, this store records what it already *did*.
DESTINATIONS: Final[tuple[str, ...]] = (
    *R1_PUBLISH_CHANNELS,
    *NON_R1_PUBLISH_CHANNELS,
)

#: The committed store. ``NB_PUBLICATION_MARKERS_DIR`` redirects it exactly as
#: ``NB_PACKAGES_DIR`` redirects the run-artifact root, so a test never writes
#: idempotency evidence into the tracked tree and one test's marker can never
#: suppress another test's publication.
DEFAULT_MARKERS_DIR: Final[Path] = Path("data/editorial/publication_markers")

#: ARP reason codes (Step 2, S-14). Sanitized constants: they reach persisted
#: run evidence, so no path, exception text or provider payload is ever one.
AUTHORITY_UNAVAILABLE: Final[str] = "idempotency_authority_unavailable"
PUBLICATION_POSSIBLY_EXISTS: Final[str] = "publication_possibly_exists"
PUBLICATION_UNCONFIRMED: Final[str] = "publication_unconfirmed"

#: The marker is written first and alone, with its own retries (§3.6 point 4).
#: Small and bounded: nothing waits, and an unwritable marker is a recorded
#: ``publication_unconfirmed``, not a stalled run.
_MARKER_WRITE_ATTEMPTS: Final[int] = 3
_MARKER_RETRY_SECONDS: Final[float] = 0.1

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class PublicationIdentityError(ValueError):
    """The identity key cannot be formed, so nothing may be published."""


def markers_root() -> Path:
    """Where the authority lives (``NB_PUBLICATION_MARKERS_DIR``, else default)."""

    configured = os.environ.get("NB_PUBLICATION_MARKERS_DIR", "").strip()
    return Path(configured) if configured else DEFAULT_MARKERS_DIR


def active_client() -> str:
    """The deployment's client identifier — its client directory's name."""

    return client_dir().name


def content_digest(text: str) -> str:
    """Digest of what was published: recorded as evidence, never part of the key."""

    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def draft_source_signal_ids(draft: "DraftPackage") -> tuple[str, ...]:
    """The source signal IDs a draft carries, for its identity key.

    The current publishing paths each name their source differently — the
    research packages carry ``signal_id``, the visibility queue carries
    ``queue_item_id``, the legacy Friday generator carries ``manual_topic_id``
    — and each one identifies the *source* the draft was written from, which
    is what the key is made of. ``source_signal_ids`` is read first so a path
    that publishes one article from several signals can say so.

    A draft naming none of them has no identity, so it has no authority, so it
    does not publish: an unidentifiable publication is precisely the one that
    could silently repeat.
    """

    metadata = draft.metadata or {}
    declared = metadata.get("source_signal_ids")
    if isinstance(declared, (list, tuple)):
        return tuple(
            value.strip()
            for value in declared
            if isinstance(value, str) and value.strip()
        )
    for field in ("signal_id", "queue_item_id", "manual_topic_id"):
        value = metadata.get(field)
        if isinstance(value, str) and value.strip():
            return (value.strip(),)
    return ()


def destination_text(draft: "DraftPackage", destination: str) -> str:
    """What this destination actually publishes — recorded in its marker.

    Evidence only: the text never enters the identity key, so a rewrite of the
    same signal is still the same publication.
    """

    if destination == "wix":
        return draft.blog_body
    if destination == "linkedin":
        return draft.linkedin_text
    if destination == "facebook":
        return draft.facebook_text
    if destination == "instagram":
        return draft.instagram_text
    if destination == "threads":
        return "\n".join(draft.threads_sequence)
    if destination == "telegram":
        return draft.telegram_text
    return ""


def _path_token(value: str) -> str:
    """A path-safe rendering of one identity component.

    Leading and trailing dots go with the unsafe characters, so no component
    can become ``.`` or ``..`` and address anything outside the store.
    """

    return _UNSAFE.sub("-", value).strip("-.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_dir(path: Path) -> bool:
    """Make a directory entry durable, and say whether it worked.

    A rename is not durable until the directory holding it is synced, so a
    swallowed failure here reports a durable write that a power loss can still
    undo — an intent that vanishes after its publication is exactly the double
    publication this store exists to prevent. The caller decides what to do
    with a false; nothing here decides it quietly.
    """

    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        os.fsync(fd)
    except OSError:
        return False
    finally:
        os.close(fd)
    return True


def _created_ancestors(path: Path) -> tuple[Path, ...]:
    """The directories ``path`` does not have yet, nearest last.

    Creating ``a/b/c`` makes three directory entries, and each one needs its
    own parent synced. Recorded before the ``mkdir`` because afterwards they
    all exist and there is no way to tell which ones this call made.
    """

    missing: list[Path] = []
    current = path
    while not current.exists() and current != current.parent:
        missing.append(current)
        current = current.parent
    missing.reverse()
    return tuple(missing)


def _write_durably(path: Path, payload: dict) -> bool:
    """Write one authority file so that a crash cannot leave it half-written.

    Temp file in the destination directory, flushed and fsynced, then renamed
    over the target and the directory fsynced: a reader sees the whole file or
    no file. Returns whether the write is durable — the caller decides what an
    undurable write means, because for an intent it forbids the call and for a
    marker it records ``publication_unconfirmed``.
    """

    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fresh = _created_ancestors(path.parent)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
    except OSError:
        return False
    # Every directory this call created, then the one holding the file. A
    # missed sync on a fresh ancestor loses the whole subtree, file and all.
    for directory in fresh:
        if not _fsync_dir(directory.parent):
            return False
    return _fsync_dir(path.parent)


class _Claim(Enum):
    """The outcome of trying to take the claim for one key."""

    OURS = "ours"
    TAKEN = "taken"
    FAILED = "failed"


def _claim_durably(path: Path, payload: dict) -> _Claim:
    """Create ``path`` exclusively, or report that someone already holds it.

    ``record_intent`` used to write the intent the way a marker is written —
    a temp file renamed over the target. That is the right shape for a value
    being replaced and the wrong one for a claim being taken: two runs that
    both read "nothing published" would both rename their own intent into
    place, both believe they may call, and both publish (#321 review). The
    claim is therefore an exclusive create: the filesystem decides which run
    wins, and only the winner may make the external call.

    Written straight to the final name rather than through a temp file,
    because the exclusivity IS the rename here. A crash mid-write leaves a
    truncated file, and that is safe in the only direction that matters:
    ``lookup`` treats the existence of an intent as "possibly published"
    without parsing it, so the next run refuses the key.
    """

    fresh = _created_ancestors(path.parent)
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return _Claim.TAKEN
    except OSError:
        return _Claim.FAILED
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        # The claim file stays. It forbids the call, which is the safe
        # direction, and the next run reads it as a key that may already
        # have been published.
        return _Claim.FAILED
    for directory in fresh:
        if not _fsync_dir(directory.parent):
            return _Claim.FAILED
    return _Claim.OURS if _fsync_dir(path.parent) else _Claim.FAILED


@dataclass(frozen=True)
class PublicationIdentity:
    """What makes two publications the same publication (Step 5 §1.1).

    No article digest: one publication per signal set per destination. A new
    article for the same signals is the same publication — deliberately
    stricter than the digest-based key this authority stands beside.
    """

    client: str
    destination: str
    source_signal_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        client = self.client.strip()
        if not client:
            raise PublicationIdentityError("a publication identity needs a client")
        destination = self.destination.strip().lower()
        if destination not in DESTINATIONS:
            raise PublicationIdentityError(
                f"unknown destination {self.destination!r} "
                f"(known: {', '.join(DESTINATIONS)})"
            )
        signals = tuple(
            sorted({value.strip() for value in self.source_signal_ids if value.strip()})
        )
        if not signals:
            raise PublicationIdentityError(
                "a publication identity needs at least one source signal ID"
            )
        object.__setattr__(self, "client", client)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "source_signal_ids", signals)

    @property
    def key(self) -> str:
        """The stable file name for this identity.

        A readable prefix, so a person doing offline maintenance can find the
        file, followed by a digest of the exact canonical signal set, so two
        different sets can never share a name however the prefix was sanitized
        or truncated.
        """

        canonical = "\n".join(self.source_signal_ids)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        prefix = "+".join(_path_token(value) for value in self.source_signal_ids)
        prefix = prefix[:60].strip("-.+")
        return f"{prefix}-{digest}" if prefix else digest


@dataclass(frozen=True)
class PublicationIntent:
    """Durable record that an external call for this key is about to happen."""

    key: str
    client: str
    destination: str
    source_signal_ids: tuple[str, ...]
    content_digest: str
    run_id: str
    recorded_at: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "client": self.client,
            "destination": self.destination,
            "source_signal_ids": list(self.source_signal_ids),
            "content_digest": self.content_digest,
            "run_id": self.run_id,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True)
class PublicationMarker:
    """Durable proof that this publication reached this destination (§3.6 p4)."""

    key: str
    client: str
    destination: str
    source_signal_ids: tuple[str, ...]
    external_id: str
    url: str
    url_provenance: str
    content_digest: str
    run_id: str
    published_at: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "client": self.client,
            "destination": self.destination,
            "source_signal_ids": list(self.source_signal_ids),
            "external_id": self.external_id,
            "url": self.url,
            "url_provenance": self.url_provenance,
            "content_digest": self.content_digest,
            "run_id": self.run_id,
            "published_at": self.published_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> "PublicationMarker":
        """Read a stored marker, or refuse it.

        Only a successful publication writes a marker, so a file that cannot
        be read as one is still evidence that something was published. The
        caller turns the refusal into *possibly published*, never into a
        licence to publish again — which is why this is free to be strict
        about the structural fields.
        """

        if not isinstance(data, dict):
            raise PublicationIdentityError("a marker must be a JSON object")
        for field in ("key", "client", "destination"):
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                raise PublicationIdentityError(f"a marker needs a {field}")
        signals = data.get("source_signal_ids")
        if not isinstance(signals, list) or not all(
            isinstance(value, str) for value in signals
        ):
            raise PublicationIdentityError("a marker needs its source signal IDs")

        def _text(field: str) -> str:
            value = data.get(field)
            return value if isinstance(value, str) else ""

        return cls(
            key=str(data["key"]),
            client=str(data["client"]),
            destination=str(data["destination"]),
            source_signal_ids=tuple(signals),
            external_id=_text("external_id"),
            url=_text("url"),
            url_provenance=_text("url_provenance"),
            content_digest=_text("content_digest"),
            run_id=_text("run_id"),
            published_at=_text("published_at"),
        )


class AuthorityState(str, Enum):
    """What the authority knows about one publication identity key."""

    #: no marker and no intent: this publication has never been attempted
    NO_PUBLICATION = "no_publication"
    #: a readable marker: the publication exists and can be reused
    PUBLISHED = "published"
    #: an intent with no usable marker: at most once means this is a skip
    POSSIBLY_PUBLISHED = "possibly_published"
    #: the store cannot answer at all; a missing answer is never "no"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AuthorityLookup:
    """The answer to "has this exact publication already happened?"."""

    state: AuthorityState
    marker: Optional[PublicationMarker] = None
    reason: Optional[str] = None

    @property
    def may_publish(self) -> bool:
        return self.state is AuthorityState.NO_PUBLICATION


class MarkerStore:
    """The durable authority: one file per publication, plus its intent."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else markers_root()

    def destination_dir(self, identity: PublicationIdentity) -> Path:
        return self.root / _path_token(identity.client) / identity.destination

    def marker_path(self, identity: PublicationIdentity) -> Path:
        return self.destination_dir(identity) / f"{identity.key}.json"

    def intent_path(self, identity: PublicationIdentity) -> Path:
        return self.destination_dir(identity) / f"{identity.key}.intent.json"

    def lookup(self, identity: PublicationIdentity) -> AuthorityLookup:
        """Query the authority for one key, before any external call."""

        marker_path = self.marker_path(identity)
        intent_path = self.intent_path(identity)
        try:
            # The store root is committed and carries a folder marker, so its
            # absence means this checkout has no authority at all rather than
            # "nothing was ever published" — the one confusion that could turn
            # a fresh CI checkout into a second publication.
            if not self.root.is_dir():
                return AuthorityLookup(
                    AuthorityState.UNAVAILABLE, reason=AUTHORITY_UNAVAILABLE
                )
            marker_exists = marker_path.is_file()
            intent_exists = intent_path.is_file()
        except OSError:
            return AuthorityLookup(
                AuthorityState.UNAVAILABLE, reason=AUTHORITY_UNAVAILABLE
            )

        if marker_exists:
            try:
                marker = PublicationMarker.from_dict(
                    json.loads(marker_path.read_text(encoding="utf-8"))
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return AuthorityLookup(
                    AuthorityState.POSSIBLY_PUBLISHED,
                    reason=PUBLICATION_POSSIBLY_EXISTS,
                )
            return AuthorityLookup(AuthorityState.PUBLISHED, marker=marker)
        if intent_exists:
            return AuthorityLookup(
                AuthorityState.POSSIBLY_PUBLISHED, reason=PUBLICATION_POSSIBLY_EXISTS
            )
        return AuthorityLookup(AuthorityState.NO_PUBLICATION)

    def record_intent(
        self,
        identity: PublicationIdentity,
        *,
        run_id: str,
        content_digest: str = "",
    ) -> Optional[PublicationIntent]:
        """Record durably that the external call for this key is about to happen.

        Returns ``None`` when the intent could not be made durable — and then
        the call must not happen. An unrecorded external call is exactly the
        double publication this store exists to prevent.
        """

        intent = PublicationIntent(
            key=identity.key,
            client=identity.client,
            destination=identity.destination,
            source_signal_ids=identity.source_signal_ids,
            content_digest=content_digest,
            run_id=run_id,
            recorded_at=_now(),
        )
        path = self.intent_path(identity)
        claimed = _claim_durably(path, intent.to_dict())
        if claimed is _Claim.OURS:
            return intent
        if claimed is _Claim.TAKEN:
            # Another run holds the claim for this key. `lookup` already refuses
            # a key whose intent exists, so this is the simultaneous case that
            # lookup cannot see: both runs read "nothing published", and only
            # the run that created the file may make the call.
            existing = self._read_intent(path)
            if existing is not None and existing.run_id == run_id:
                # Our own earlier claim in this same run — re-entry, not a race.
                return existing
        return None

    def _read_intent(self, path: Path) -> Optional[PublicationIntent]:
        """The intent on disk, or ``None`` when it cannot be read as one.

        Unreadable is not "absent": the caller treats it as another run's
        claim, because a half-written claim is still a claim.
        """

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            return PublicationIntent(
                key=str(data.get("key", "")),
                client=str(data.get("client", "")),
                destination=str(data.get("destination", "")),
                source_signal_ids=tuple(data.get("source_signal_ids", ()) or ()),
                content_digest=str(data.get("content_digest", "")),
                run_id=str(data.get("run_id", "")),
                recorded_at=str(data.get("recorded_at", "")),
            )
        except (TypeError, ValueError):
            return None

    def record_marker(
        self,
        identity: PublicationIdentity,
        *,
        external_id: str,
        url: str = "",
        url_provenance: UrlProvenance = UrlProvenance.UNAVAILABLE,
        content_digest: str = "",
        run_id: str,
    ) -> Optional[PublicationMarker]:
        """Write the marker first and alone, with its own retries (§3.6 p4).

        Returns ``None`` when no attempt was durable: the publication happened
        and the run must record ``publication_unconfirmed`` for this key. The
        intent stays on disk, so the next run treats the key as possibly
        published and skips.
        """

        marker = PublicationMarker(
            key=identity.key,
            client=identity.client,
            destination=identity.destination,
            source_signal_ids=identity.source_signal_ids,
            external_id=external_id,
            url=url,
            url_provenance=url_provenance.value,
            content_digest=content_digest,
            run_id=run_id,
            published_at=_now(),
        )
        path = self.marker_path(identity)
        for attempt in range(_MARKER_WRITE_ATTEMPTS):
            if _write_durably(path, marker.to_dict()):
                return marker
            if attempt + 1 < _MARKER_WRITE_ATTEMPTS:
                time.sleep(_MARKER_RETRY_SECONDS)
        return None


@dataclass(frozen=True)
class GuardDecision:
    """Whether this destination may be published, and the evidence if not."""

    destination: str
    proceed: bool
    marker: Optional[PublicationMarker] = None
    reason: Optional[str] = None


class PublicationGuard:
    """One publication unit's side of the S-14 publication transaction.

    Built once per unit — the run's client and its source signal IDs — and
    then asked per destination. It never raises: a unit whose identity cannot
    be formed has no authority, and no authority means no publication, which
    is the answer a publishing path needs rather than an exception it has to
    interpret at the edge of an irreversible call.
    """

    def __init__(
        self,
        *,
        source_signal_ids: Iterable[str],
        run_id: str,
        client: Optional[str] = None,
        store: Optional[MarkerStore] = None,
    ) -> None:
        self.run_id = run_id
        self.store = store if store is not None else MarkerStore()
        self._client = client
        self._source_signal_ids = tuple(source_signal_ids)

    def identity(self, destination: str) -> Optional[PublicationIdentity]:
        """This unit's identity at ``destination``, or ``None`` if unformable."""

        try:
            client = self._client if self._client is not None else active_client()
            return PublicationIdentity(
                client=client,
                destination=destination,
                source_signal_ids=self._source_signal_ids,
            )
        except (ValueError, OSError):
            return None

    def key(self, destination: str) -> str:
        """The identity key, for the run's own evidence. Empty when unformable."""

        identity = self.identity(destination)
        return identity.key if identity is not None else ""

    def check(self, destination: str) -> GuardDecision:
        """Step 1 of the transaction: may this destination be called at all?"""

        identity = self.identity(destination)
        if identity is None:
            return GuardDecision(destination, False, reason=AUTHORITY_UNAVAILABLE)
        lookup = self.store.lookup(identity)
        if lookup.state is AuthorityState.PUBLISHED:
            return GuardDecision(destination, False, marker=lookup.marker)
        if lookup.may_publish:
            return GuardDecision(destination, True)
        return GuardDecision(
            destination, False, reason=lookup.reason or AUTHORITY_UNAVAILABLE
        )

    def record_intent(
        self, destination: str, *, content_digest: str = ""
    ) -> GuardDecision:
        """Step 2: durable intent, before the irreversible call.

        Answers in the same shape as :meth:`check`, so a call site has one
        decision to act on rather than two: a refusal here means the external
        call must not be made, because an unrecorded call is the double
        publication this authority exists to prevent.
        """

        identity = self.identity(destination)
        if identity is not None and self.store.record_intent(
            identity, run_id=self.run_id, content_digest=content_digest
        ):
            return GuardDecision(destination, True)
        return GuardDecision(destination, False, reason=AUTHORITY_UNAVAILABLE)

    def record_marker(
        self,
        destination: str,
        result: PublishResult,
        *,
        content_digest: str = "",
    ) -> Optional[PublicationMarker]:
        """Step 4: the marker for a destination that has just succeeded."""

        identity = self.identity(destination)
        if identity is None:
            return None
        return self.store.record_marker(
            identity,
            external_id=result.external_id or "",
            url=result.url or "",
            url_provenance=result.url_provenance,
            content_digest=content_digest,
            run_id=self.run_id,
        )


def proves_publication(result: PublishResult) -> bool:
    """Is this result proof that the destination now holds a live publication?

    Only ``PUBLISHED``. A draft is not proof the article is live, and a marker
    written for one would suppress the real publication forever — the same rule
    :mod:`src.publishing.idempotency` already keeps for prior evidence. Stated
    once here so every publishing path writes markers on the same condition.
    """

    return result.status is PublishStatus.PUBLISHED


def refused_result(decision: GuardDecision, *, run_id: str = "") -> PublishResult:
    """The result a destination gets when the authority refused the call.

    A marker is a proven publication, so the channel is ``REUSED`` and carries
    the evidence the earlier run recorded. Everything else is ``SKIPPED`` with
    its ARP reason: this run published nothing, and says exactly why.
    """

    if decision.marker is not None:
        try:
            provenance = UrlProvenance(decision.marker.url_provenance)
        except ValueError:
            # A URL whose origin cannot be established is never promoted.
            provenance = UrlProvenance.UNAVAILABLE
        return PublishResult(
            platform=decision.destination,
            status=PublishStatus.REUSED,
            external_id=decision.marker.external_id or None,
            url=decision.marker.url or None,
            url_provenance=provenance,
            reused_from_run_id=decision.marker.run_id or None,
            run_id=run_id,
        )
    return PublishResult(
        platform=decision.destination,
        status=PublishStatus.SKIPPED,
        error_message=decision.reason or AUTHORITY_UNAVAILABLE,
        run_id=run_id,
    )
