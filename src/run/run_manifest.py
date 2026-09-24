"""RunManifest: what a run says it executed (Issues #290, #291, #336, SL-1).

Step 3 §4.3 gives the manifest to the run harness, which writes it last, after
S-14 or after the terminal SKIP of the signal or unit. A run directory without
one is incomplete and is never read as a source by another run.

It has three parts. The identity header — ``RunContext`` and ``CodeIdentity``,
reused rather than re-declared — and the **topology digest** the run claims to
have executed (#290). The **input versions** it executed against (#336): the
Step 3 §4.1 set — Client Contract, Audience Profile, Editorial Lens, knowledge
register, platform knowledge, reference library and strength ladder — each
with a digest, sealed by ``inputs_digest``. Then the index of what the run
actually wrote (#291): the entity index, the ordered trace index and
``run_digest`` over both, which Step 3 §4.1 gives the manifest and which the
workspace writer (``src/run/run_workspace.py``) fills in from the writes it
performed.

All three digests are present by construction: :meth:`RunManifest.for_run`
computes them and no caller supplies any, so there is no code path that writes
a manifest without them. A manifest read back from disk is a different matter
— it carries whatever was written, which is exactly what makes it evidence —
so :func:`verify_topology_digest` is what a reader calls before trusting it. A
run whose digest differs from the registry did not execute the canonical
S-00 → S-15 topology, and is refused rather than quietly accepted.
:func:`verify_run_digest` is the same gate over the index: it says the two
lists in this file are the lists it was sealed over. :func:`verify_input_digests`
is the same gate over §4.1: it says the inputs in this file are the inputs the
run sealed, so a run states which inputs it executed against and the statement
can be checked rather than taken. What none of them can say is whether the
files on disk still match the index — that needs the workspace, and is
``verify_run_workspace``'s question.

Where each input's identity comes from is not here: this module fixes the
shape a run states it in, and ``src/run/run_inputs.py`` reads the identity out
of the contracts and the register a run actually loaded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import Enum
from typing import Any, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic import ValidationError as _PydanticValidationError

from src.editorial_core.topology import topology_digest
from src.run.code_identity import CodeIdentity
from src.run.run_context import RunContext

# Schema version for this contract shape. Bump it when fields are added or
# removed in a breaking way. 1.1 added the Step 3 §4.1 index — a 1.0 manifest
# carried no index and no run digest, so it is a different document, and a
# reader is told that rather than left to discover it field by field. 1.2
# added the §4.1 input versions (#336): a 1.1 manifest said which files a run
# wrote and never which inputs it wrote them from, so it cannot answer the one
# question `inputs` exists for.
_SCHEMA_VERSION = "1.2"

_KNOWN_FIELDS = frozenset({
    "schema_version",
    "run_context",
    "code_identity",
    "topology_digest",
    "inputs",
    "entities",
    "trace",
    "run_digest",
})

#: Every digest in this contract is a SHA-256 over exact bytes, written the
#: one way the repository writes them.
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"

#: An ISO-8601 calendar day, as the register writes `verified_on`.
_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

#: The serialization ``run_digest`` is taken over. Bump it only when the
#: meaning of the payload changes, never when a run's contents do — the digest
#: is how a changed run is noticed.
CANONICAL_RUN_DIGEST_SERIALIZATION = "run-manifest-index-json-v1"

#: The same, for ``inputs_digest``. Separate from the index serialization
#: because the two seal different things and move for different reasons.
CANONICAL_RUN_INPUTS_SERIALIZATION = "run-manifest-inputs-json-v1"

_Entry = TypeVar("_Entry", bound=BaseModel)


class TopologyDigestMismatchError(ValueError):
    """A manifest records a topology that is not the canonical one."""


class RunDigestMismatchError(ValueError):
    """A manifest's run digest is not the digest of the index it carries."""


class InputDigestMismatchError(ValueError):
    """A manifest's inputs digest is not the digest of the inputs it carries."""


class _IndexEntry(BaseModel):
    """Every entry inside a manifest — index or input version — is immutable
    and rejects unknown fields."""

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


# ----------------------------------------------------------------------
# Input versions (§4.1)
# ----------------------------------------------------------------------


class InputKind(str, Enum):
    """The Step 3 §4.1 set: every input a run states it executed against.

    Each value is also the name of the :class:`RunInputs` field that carries
    it, so the set cannot grow an input the manifest has no place for.
    """

    CLIENT_CONTRACT = "client_contract"
    AUDIENCE_PROFILE = "audience_profile"
    EDITORIAL_LENS = "editorial_lens"
    KNOWLEDGE_REGISTER = "knowledge_register"
    PLATFORM_KNOWLEDGE = "platform_knowledge"
    REFERENCE_LIBRARY = "reference_library"
    STRENGTH_LADDER = "strength_ladder"


class PlatformVerification(_IndexEntry):
    """One platform knowledge record, and the day somebody last verified it.

    §4.1 records platform knowledge by its **verification dates**, because
    what a destination rule is worth is how recently it was checked — which is
    why Step 4 §8 rule 8 requires the date on every ``K-DST-*`` record.
    """

    record_id: str = Field(min_length=1)
    verified_on: str = Field(pattern=_DATE_PATTERN)


class InputVersion(_IndexEntry):
    """One §4.1 input: what the run read, or a statement that it read none.

    Exactly one of the two, and nothing in between. An input the run read
    carries a digest; an input it did not read carries a stated reason and no
    identity at all. That asymmetry is the point: an artifact that does not
    exist yet — the Audience Profile, which #335 owns — is recorded as absent
    rather than given an invented identity, and a reader can tell the two
    apart without knowing which slices have landed.
    """

    kind: InputKind
    #: What the run read, by name: a stream contract identity, the lens
    #: identities, the register's git commit, the ladder's record ID. Several
    #: where the input is several documents, and empty where it has no name
    #: outside its own bytes — a register in a tree with no commit has none,
    #: and the digest is then the whole of its identity.
    identities: tuple[str, ...] = ()
    #: ``sha256:<hex>`` over what was read. Absent exactly when the input is.
    digest: Optional[str] = Field(default=None, pattern=_DIGEST_PATTERN)
    #: Set only for platform knowledge, which §4.1 records by its dates.
    verified_on: tuple[PlatformVerification, ...] = ()
    #: Why there is no identity to record. Set exactly when the input is
    #: absent, so an unread input says which unread input it is.
    absent_reason: Optional[str] = None

    @model_validator(mode="after")
    def _read_or_stated_absent(self) -> "InputVersion":
        if self.digest is None and self.absent_reason is None:
            raise ValueError(
                f"{self.kind.value}: an input version either carries the "
                "digest of what was read or says why it has none, and this "
                "one does neither"
            )
        if self.digest is not None and self.absent_reason is not None:
            raise ValueError(
                f"{self.kind.value}: an input version carrying a digest was "
                "read, so it has no reason to be absent, and this one states "
                "both"
            )
        if self.absent_reason is not None:
            if not self.absent_reason.strip():
                raise ValueError(
                    f"{self.kind.value}: an absent input states why it is "
                    "absent, and a blank reason states nothing"
                )
            if self.identities or self.verified_on:
                raise ValueError(
                    f"{self.kind.value}: an input the run did not read has "
                    "nothing to identify"
                )
        if self.verified_on and self.kind is not InputKind.PLATFORM_KNOWLEDGE:
            raise ValueError(
                f"{self.kind.value}: verification dates belong to "
                f"{InputKind.PLATFORM_KNOWLEDGE.value}; §4.1 records every "
                "other input by its version"
            )
        return self

    @property
    def present(self) -> bool:
        """Did the run read this input at all?"""

        return self.digest is not None

    @classmethod
    def absent(cls, kind: InputKind, reason: str) -> "InputVersion":
        """State that the run read this input nowhere, and why."""

        return cls(kind=kind, absent_reason=reason)


def compute_inputs_digest(inputs: Sequence[InputVersion]) -> str:
    """``sha256:<hex>`` over the §4.1 input versions, each one whole.

    Over each entry entire, and not over its digest alone the way
    :func:`compute_run_digest` is. An input's evidence is what the run says it
    read — the identity, the verification dates, the stated absence — and not
    only the bytes behind it: a run that swapped a named contract for an
    unnamed one of the same content executed against something else, and the
    seal has to move with it.
    """

    payload = json.dumps(
        {
            "serialization": CANONICAL_RUN_INPUTS_SERIALIZATION,
            "inputs": sorted(
                (entry.model_dump(mode="json") for entry in inputs),
                key=lambda entry: str(entry["kind"]),
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RunInputs(BaseModel):
    """The §4.1 input versions of one run, and the digest that seals them.

    One field per input, so "carries every §4.1 input" is the shape of the
    type rather than a rule somebody remembers to apply: a run cannot leave
    one out, it can only state that it read none.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_contract: InputVersion
    audience_profile: InputVersion
    editorial_lens: InputVersion
    knowledge_register: InputVersion
    platform_knowledge: InputVersion
    reference_library: InputVersion
    strength_ladder: InputVersion
    inputs_digest: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _each_entry_is_the_input_it_is_filed_under(self) -> "RunInputs":
        for kind in InputKind:
            entry: InputVersion = getattr(self, kind.value)
            if entry.kind is not kind:
                raise ValueError(
                    f"the {kind.value} input carries a {entry.kind.value} "
                    "version; §4.1 is a set of named inputs, and a version "
                    "filed under another name is a run stating the wrong "
                    "thing about itself"
                )
        return self

    @property
    def entries(self) -> tuple[InputVersion, ...]:
        """Every §4.1 input, in the order :class:`InputKind` declares them."""

        return tuple(getattr(self, kind.value) for kind in InputKind)

    @classmethod
    def of(
        cls,
        *,
        client_contract: InputVersion,
        audience_profile: InputVersion,
        editorial_lens: InputVersion,
        knowledge_register: InputVersion,
        platform_knowledge: InputVersion,
        reference_library: InputVersion,
        strength_ladder: InputVersion,
    ) -> "RunInputs":
        """Seal one run's input versions.

        ``inputs_digest`` is computed here and cannot be passed in, for the
        reason ``run_digest`` cannot: a caller free to choose its own seal
        could state inputs the run never executed against.
        """

        stated: dict[str, InputVersion] = {
            InputKind.CLIENT_CONTRACT.value: client_contract,
            InputKind.AUDIENCE_PROFILE.value: audience_profile,
            InputKind.EDITORIAL_LENS.value: editorial_lens,
            InputKind.KNOWLEDGE_REGISTER.value: knowledge_register,
            InputKind.PLATFORM_KNOWLEDGE.value: platform_knowledge,
            InputKind.REFERENCE_LIBRARY.value: reference_library,
            InputKind.STRENGTH_LADDER.value: strength_ladder,
        }
        return cls(
            **stated,
            inputs_digest=compute_inputs_digest(tuple(stated.values())),
        )

    @classmethod
    def stated_absent(cls, reason: str) -> "RunInputs":
        """A run that read none of the §4.1 inputs, saying so for each.

        Not a default and not a blank: the reason is the caller's, so a run
        that read something and failed to record it cannot arrive here by
        omission. It is what a fixture shadow run has to say — the walking
        skeleton's stages are pass-throughs and read no contract, no lens and
        no register, and the manifest states that rather than nothing.
        """

        def absent(kind: InputKind) -> InputVersion:
            return InputVersion.absent(kind, reason)

        return cls.of(
            client_contract=absent(InputKind.CLIENT_CONTRACT),
            audience_profile=absent(InputKind.AUDIENCE_PROFILE),
            editorial_lens=absent(InputKind.EDITORIAL_LENS),
            knowledge_register=absent(InputKind.KNOWLEDGE_REGISTER),
            platform_knowledge=absent(InputKind.PLATFORM_KNOWLEDGE),
            reference_library=absent(InputKind.REFERENCE_LIBRARY),
            strength_ladder=absent(InputKind.STRENGTH_LADDER),
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible, with every input stated even where it is absent."""

        data: dict[str, Any] = {
            entry.kind.value: entry.model_dump(mode="json")
            for entry in self.entries
        }
        data["inputs_digest"] = self.inputs_digest
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunInputs":
        """Deserialize from a dict, or say what is wrong with it.

        Reading verifies no digest, exactly as reading a manifest does not:
        :func:`verify_input_digests` is the gate, and inputs that do not
        verify must stay readable or a mismatch could not be investigated.
        """

        if not isinstance(data, dict):
            raise ValueError(
                f"RunInputs.from_dict expects a dict; got {type(data).__name__}"
            )
        try:
            return cls.model_validate(data)
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            loc = " -> ".join(str(x) for x in first["loc"]) if first["loc"] else "value"
            raise ValueError(f"RunInputs field '{loc}': {first['msg']}") from exc


class RunManifest(BaseModel):
    """One run's manifest: what it executed, against what, and what it wrote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    run_context: RunContext
    #: Absent when the run could not resolve its own code identity — a
    #: fabricated one would be worse than none (see ``code_identity``).
    code_identity: Optional[CodeIdentity] = None
    topology_digest: str = Field(pattern=_DIGEST_PATTERN)
    #: The §4.1 input versions. Required, and with no default: a run that
    #: cannot say which inputs it executed against cannot be reproduced, and
    #: a default would let it say nothing by saying nothing.
    inputs: RunInputs
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
        inputs: RunInputs,
        entities: Sequence[EntityIndexEntry] = (),
        trace: Sequence[TraceIndexEntry] = (),
    ) -> "RunManifest":
        """Build the manifest of a run that executed the canonical topology.

        The topology and run digests are computed here, once, and neither can
        be passed in: a caller that could choose its own topology digest could
        claim to have run an engine it did not run, and one that could choose
        its own run digest could seal an index over files it never wrote.
        ``inputs`` arrives already sealed, by :meth:`RunInputs.of` and for the
        same reason — but it is required rather than defaulted, because what a
        run read is the caller's knowledge and not this module's.
        """

        if not isinstance(run_context, RunContext):
            raise ValueError(
                "run_context must be a RunContext instance; "
                f"got {type(run_context).__name__}"
            )
        if not isinstance(inputs, RunInputs):
            raise ValueError(
                "inputs must be a RunInputs instance; "
                f"got {type(inputs).__name__}"
            )
        return cls(
            schema_version=_SCHEMA_VERSION,
            run_context=run_context,
            code_identity=code_identity,
            topology_digest=topology_digest(),
            inputs=inputs,
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
            "inputs": self.inputs.to_dict(),
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

        Reading verifies no digest: a manifest whose topology, inputs or index
        differs must still be readable, or a mismatched run could not be
        investigated. :func:`verify_topology_digest`,
        :func:`verify_input_digests` and :func:`verify_run_digest` are the
        gates.
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

        raw_inputs = data.get("inputs")
        if not isinstance(raw_inputs, dict):
            raise ValueError(
                "inputs must be a serialized RunInputs object; got "
                f"{type(raw_inputs).__name__}. A manifest without the Step 3 "
                "§4.1 input versions is a schema 1.1 document"
            )

        try:
            return cls(
                schema_version=data.get("schema_version", ""),
                run_context=RunContext.from_dict(raw_context),
                code_identity=identity,
                topology_digest=data.get("topology_digest", ""),
                inputs=RunInputs.from_dict(raw_inputs),
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


def verify_input_digests(manifest: RunManifest) -> None:
    """Raise unless the manifest's inputs digest is the digest of its inputs.

    The §4.1 counterpart of :func:`verify_run_digest`, and the reason writing
    the inputs down is worth anything: a run states which Client Contract,
    lens, knowledge register, ladder and platform knowledge it executed
    against, and a reader who cannot check that statement holds a claim rather
    than evidence. A run whose recorded input digests do not verify is refused
    instead of trusted — and stays readable, for the forensic reason the other
    two gates leave a mismatched manifest readable.
    """

    expected = compute_inputs_digest(manifest.inputs.entries)
    if manifest.inputs.inputs_digest != expected:
        raise InputDigestMismatchError(
            f"run {manifest.run_context.run_id} records inputs digest "
            f"{manifest.inputs.inputs_digest}, but the input versions it "
            f"carries digest to {expected}; the manifest's own §4.1 inputs "
            "changed after the run sealed them"
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
