"""RunManifest: what a run says it executed (Issue #290, slice SL-1).

Step 3 §4.3 gives the manifest to the run harness, which writes it last, after
S-14 or after the terminal SKIP of the signal or unit. A run directory without
one is incomplete and is never read as a source by another run.

This slice builds the part CE-1 needs and nothing more: the identity header —
``RunContext`` and ``CodeIdentity``, reused rather than re-declared — and the
**topology digest** the run claims to have executed. The entity index, the
trace index and ``run_digest`` (Step 3 §4.1) arrive with the workspace writer.

The digest is present by construction: :meth:`RunManifest.for_run` computes it
from the registry and no caller supplies one, so there is no code path that
writes a manifest without it. A manifest read back from disk is a different
matter — it carries whatever digest was written, which is exactly what makes
it evidence — so :func:`verify_topology_digest` is what a reader calls before
trusting it. A run whose digest differs from the registry did not execute the
canonical S-00 → S-15 topology, and is refused rather than quietly accepted.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import ValidationError as _PydanticValidationError

from src.editorial_core.topology import topology_digest
from src.run.code_identity import CodeIdentity
from src.run.run_context import RunContext

# Schema version for this contract shape. Bump it when fields are added or
# removed in a breaking way.
_SCHEMA_VERSION = "1.0"

_KNOWN_FIELDS = frozenset({
    "schema_version",
    "run_context",
    "code_identity",
    "topology_digest",
})


class TopologyDigestMismatchError(ValueError):
    """A manifest records a topology that is not the canonical one."""


class RunManifest(BaseModel):
    """The header of one run's manifest, with the topology it executed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    run_context: RunContext
    #: Absent when the run could not resolve its own code identity — a
    #: fabricated one would be worse than none (see ``code_identity``).
    code_identity: Optional[CodeIdentity] = None
    topology_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

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
    ) -> "RunManifest":
        """Build the manifest of a run that executed the canonical topology.

        The digest is read from the registry here, once, and cannot be passed
        in: a caller that could choose its own digest could claim to have run
        an engine it did not run.
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
        }
        if self.code_identity is not None:
            data["code_identity"] = self.code_identity.model_dump()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunManifest":
        """Deserialize from a dict (e.g. parsed JSON).

        Reading does not verify the topology: a manifest whose digest differs
        must still be readable, or a mismatched run could not be investigated.
        :func:`verify_topology_digest` is the gate.
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
            )
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            loc = " -> ".join(str(x) for x in first["loc"]) if first["loc"] else "value"
            raise ValueError(f"RunManifest field '{loc}': {first['msg']}") from exc


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
