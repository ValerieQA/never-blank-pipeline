"""RunManifest: what a run says it executed (Issues #290, #291, slice SL-1).

Step 3 §4.3 gives the manifest to the run harness, which writes it last, after
S-14 or after the terminal SKIP of the signal or unit. A run directory without
one is incomplete and is never read as a source by another run.

It has two parts. The identity header — ``RunContext`` and ``CodeIdentity``,
reused rather than re-declared — and the **topology digest** the run claims to
have executed (#290). Then the index of what the run actually wrote (#291):
the entity index, the ordered trace index and ``run_digest`` over both, which
Step 3 §4.1 gives the manifest and which the workspace writer
(``src/run/run_workspace.py``) fills in from the writes it performed.

Both digests are present by construction: :meth:`RunManifest.for_run` computes
them and no caller supplies either, so there is no code path that writes a
manifest without them. A manifest read back from disk is a different matter —
it carries whatever was written, which is exactly what makes it evidence — so
:func:`verify_topology_digest` is what a reader calls before trusting it. A
run whose digest differs from the registry did not execute the canonical
S-00 → S-15 topology, and is refused rather than quietly accepted.
:func:`verify_run_digest` is the same gate over the index: it says the two
lists in this file are the lists it was sealed over. What neither can say is
whether the files on disk still match the index — that needs the workspace,
and is ``verify_run_workspace``'s question.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import ValidationError as _PydanticValidationError

from src.editorial_core.topology import topology_digest
from src.run.code_identity import CodeIdentity
from src.run.run_context import RunContext

# Schema version for this contract shape. Bump it when fields are added or
# removed in a breaking way. 1.1 added the Step 3 §4.1 index — a 1.0 manifest
# carried no index and no run digest, so it is a different document, and a
# reader is told that rather than left to discover it field by field.
_SCHEMA_VERSION = "1.1"

_KNOWN_FIELDS = frozenset({
    "schema_version",
    "run_context",
    "code_identity",
    "topology_digest",
    "entities",
    "trace",
    "run_digest",
})

#: Every digest in this contract is a SHA-256 over exact bytes, written the
#: one way the repository writes them.
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"

#: The serialization ``run_digest`` is taken over. Bump it only when the
#: meaning of the payload changes, never when a run's contents do — the digest
#: is how a changed run is noticed.
CANONICAL_RUN_DIGEST_SERIALIZATION = "run-manifest-index-json-v1"

_Entry = TypeVar("_Entry", bound=BaseModel)


class TopologyDigestMismatchError(ValueError):
    """A manifest records a topology that is not the canonical one."""


class RunDigestMismatchError(ValueError):
    """A manifest's run digest is not the digest of the index it carries."""


class _IndexEntry(BaseModel):
    """Every manifest index entry is immutable and rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EntityIndexEntry(_IndexEntry):
    """One entity the run wrote: what it is, where it is, who wrote it.

    Step 3 §4.1 entity index. ``writer_stage`` is the load-bearing field: it
    is what makes "did any stage write outside its paths?" answerable from the
    manifest alone, by comparing it with the owner the §2.3 table gives the
    path.
    """

    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    #: Absent for the entities Step 3 §2.5 writes exactly once rather than
    #: versioning. When present it is also in the file name (P2).
    version: Optional[int] = Field(default=None, ge=1)
    #: POSIX path relative to the run workspace root.
    path: str = Field(min_length=1)
    digest: str = Field(pattern=_DIGEST_PATTERN)
    writer_stage: str = Field(min_length=1)


class TraceIndexEntry(_IndexEntry):
    """One StageRecord, in the ordered trace index (Step 3 §4.1)."""

    #: Monotonic within the run, so the index order is the execution order.
    seq: int = Field(ge=0)
    stage: str = Field(min_length=1)
    scope_key: str = Field(min_length=1)
    path: str = Field(min_length=1)
    digest: str = Field(pattern=_DIGEST_PATTERN)


def compute_run_digest(
    entities: Sequence[EntityIndexEntry],
    trace: Sequence[TraceIndexEntry],
) -> str:
    """``sha256:<hex>`` over the sorted entity and trace digests (§4.1).

    Sorted, so the value does not depend on the order a run happened to write
    in; over the digests alone, so it changes when any indexed file changes
    and only then. Where each file sits and which stage wrote it are checked
    per entry rather than folded in here — a digest that moved when a path did
    would say "something changed" where the entry says which stage broke which
    rule.
    """

    payload = json.dumps(
        {
            "serialization": CANONICAL_RUN_DIGEST_SERIALIZATION,
            "entities": sorted(entry.digest for entry in entities),
            "trace": sorted(entry.digest for entry in trace),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RunManifest(BaseModel):
    """One run's manifest: the topology it executed and the files it wrote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    run_context: RunContext
    #: Absent when the run could not resolve its own code identity — a
    #: fabricated one would be worse than none (see ``code_identity``).
    code_identity: Optional[CodeIdentity] = None
    topology_digest: str = Field(pattern=_DIGEST_PATTERN)
    entities: tuple[EntityIndexEntry, ...] = ()
    trace: tuple[TraceIndexEntry, ...] = ()
    run_digest: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator("schema_version", mode="after")
    @classmethod
    def _schema_version_known(cls, value: str) -> str:
        if value != _SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {_SCHEMA_VERSION!r}; got {value!r}"
            )
        return value

    @classmethod
    def for_run(
        cls,
        run_context: RunContext,
        code_identity: Optional[CodeIdentity] = None,
        *,
        entities: Sequence[EntityIndexEntry] = (),
        trace: Sequence[TraceIndexEntry] = (),
    ) -> "RunManifest":
        """Build the manifest of a run that executed the canonical topology.

        Both digests are computed here, once, and neither can be passed in: a
        caller that could choose its own topology digest could claim to have
        run an engine it did not run, and one that could choose its own run
        digest could seal an index over files it never wrote.
        """

        if not isinstance(run_context, RunContext):
            raise ValueError(
                "run_context must be a RunContext instance; "
                f"got {type(run_context).__name__}"
            )
        return cls(
            schema_version=_SCHEMA_VERSION,
            run_context=run_context,
            code_identity=code_identity,
            topology_digest=topology_digest(),
            entities=tuple(entities),
            trace=tuple(trace),
            run_digest=compute_run_digest(entities, trace),
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dict."""

        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "run_context": self.run_context.to_dict(),
            "topology_digest": self.topology_digest,
            "entities": [entry.model_dump() for entry in self.entities],
            "trace": [entry.model_dump() for entry in self.trace],
            "run_digest": self.run_digest,
        }
        if self.code_identity is not None:
            data["code_identity"] = self.code_identity.model_dump()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunManifest":
        """Deserialize from a dict (e.g. parsed JSON).

        Reading verifies neither digest: a manifest whose topology or index
        differs must still be readable, or a mismatched run could not be
        investigated. :func:`verify_topology_digest` and
        :func:`verify_run_digest` are the gates.
        """

        if not isinstance(data, dict):
            raise ValueError(
                f"RunManifest.from_dict expects a dict; got {type(data).__name__}"
            )

        unknown = set(data.keys()) - _KNOWN_FIELDS
        if unknown:
            raise ValueError(
                f"RunManifest.from_dict received unknown field(s): "
                f"{sorted(unknown)}. Allowed fields: {sorted(_KNOWN_FIELDS)}"
            )

        raw_context = data.get("run_context")
        if not isinstance(raw_context, dict):
            raise ValueError(
                "run_context must be a serialized RunContext object; got "
                f"{type(raw_context).__name__}"
            )

        raw_identity = data.get("code_identity")
        identity: Optional[CodeIdentity] = None
        if raw_identity is not None:
            if not isinstance(raw_identity, dict):
                raise ValueError(
                    "code_identity must be a serialized CodeIdentity object or "
                    f"absent; got {type(raw_identity).__name__}"
                )
            identity = CodeIdentity(**raw_identity)

        try:
            return cls(
                schema_version=data.get("schema_version", ""),
                run_context=RunContext.from_dict(raw_context),
                code_identity=identity,
                topology_digest=data.get("topology_digest", ""),
                entities=_index(data.get("entities"), EntityIndexEntry, "entities"),
                trace=_index(data.get("trace"), TraceIndexEntry, "trace"),
                run_digest=data.get("run_digest", ""),
            )
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            loc = " -> ".join(str(x) for x in first["loc"]) if first["loc"] else "value"
            raise ValueError(f"RunManifest field '{loc}': {first['msg']}") from exc


def _index(
    raw: Any, entry_type: type[_Entry], field: str
) -> tuple[_Entry, ...]:
    """Validate one manifest index list, saying which entry is wrong.

    An absent list reads as an empty one: a run that wrote nothing indexes
    nothing, and its ``run_digest`` says exactly that.
    """

    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(
            f"{field} must be a list of objects; got {type(raw).__name__}"
        )
    entries: list[_Entry] = []
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(
                f"{field}[{position}] must be an object; got {type(item).__name__}"
            )
        try:
            entries.append(entry_type.model_validate(item))
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            loc = " -> ".join(str(x) for x in first["loc"]) if first["loc"] else "value"
            raise ValueError(f"{field}[{position}] '{loc}': {first['msg']}") from exc
    return tuple(entries)


def verify_topology_digest(manifest: RunManifest) -> None:
    """Raise unless the manifest records the canonical topology.

    Fails closed, and says which way the two differ: either the run executed
    something that was not the canonical engine, or the registry changed after
    it ran. Both are answers a reader needs before using the run as evidence;
    neither is a reason to rewrite the manifest.
    """

    expected = topology_digest()
    if manifest.topology_digest != expected:
        raise TopologyDigestMismatchError(
            f"run {manifest.run_context.run_id} records topology digest "
            f"{manifest.topology_digest}, but the canonical registry is "
            f"{expected}; the run did not execute the canonical S-00 → S-15 "
            "topology, or the registry changed after it ran"
        )


def verify_run_digest(manifest: RunManifest) -> None:
    """Raise unless the manifest's run digest is the digest of its own index.

    A cheap check over one file, and deliberately only that: it proves the
    entity and trace lists are the ones the run was sealed over, so an entry
    added, dropped or edited afterwards is visible without reading the
    workspace at all.
    """

    expected = compute_run_digest(manifest.entities, manifest.trace)
    if manifest.run_digest != expected:
        raise RunDigestMismatchError(
            f"run {manifest.run_context.run_id} records run digest "
            f"{manifest.run_digest}, but the index it carries digests to "
            f"{expected}; the manifest's own index changed after the run "
            "sealed it"
        )
