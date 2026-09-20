"""ENGINE: what each stage was routed, and what its request actually held (#279).

Forensic #278 could not answer one question about a real run: did the client
document that governs a decision reach the stage that made it? The contract was
loaded, hashed and recorded in lineage, and the run still could not show which
model request carried it. Code inspection answered it; artifacts could not.

This records the answer while the run happens. For each stage the run declares
what it routed there — lens identity, version and digest — and every model
request that stage makes is checked against that material as it goes out. What
is written down is:

    run_id · stage · routed lens identities+digests · request digest · contained

``contained`` is the load-bearing field: it is computed from the request itself,
not from the intention to send it. A stage that was routed a lens and issued a
request without it produces ``contained: false``, which is exactly the defect
#278 had to read source code to find.

Deliberately not stored: prompts, provider keys, model values, article text. A
SHA-256 over the request proves which request was measured without carrying its
contents into an artifact.

Generic: no client, stream, weekday or lens is named here. The Engine records
the routing a contract declared; what that routing means is the contract's.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RoutedLens:
    """One client obligation a run routed to a stage."""

    identity: str
    digest: str
    #: A short, stable fragment of the lens text, used to test the request.
    probe: str

    def as_evidence(self) -> dict:
        return {"lens": self.identity, "digest": self.digest}


@dataclass(frozen=True, slots=True)
class StageRequest:
    """One model request a stage issued, and whether it carried the routing."""

    stage: str
    request_sha256: str
    contained: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing

    def as_evidence(self) -> dict:
        return {"stage": self.stage, "request_sha256": self.request_sha256,
                "contained": list(self.contained), "missing": list(self.missing),
                "complete": self.complete}


@dataclass
class StageRouting:
    """The run's routing record: what was routed, and what went out."""

    run_id: str = ""
    plan_stage: str = ""
    routed: dict[str, tuple[RoutedLens, ...]] = field(default_factory=dict)
    requests: list[StageRequest] = field(default_factory=list)

    def route(self, stage: str, lenses: Sequence[RoutedLens]) -> None:
        """Declare what this run routed to ``stage`` before it runs."""
        self.routed[stage] = tuple(lenses)

    def observe(self, stage: str, request: str) -> StageRequest:
        """Measure one outgoing request against what ``stage`` was routed."""
        expected = self.routed.get(stage, ())
        haystack = " ".join((request or "").split()).casefold()
        contained: list[str] = []
        missing: list[str] = []
        for lens in expected:
            probe = " ".join(lens.probe.split()).casefold()
            (contained if probe and probe in haystack else missing).append(lens.identity)
        record = StageRequest(
            stage=stage,
            request_sha256=hashlib.sha256((request or "").encode("utf-8")).hexdigest(),
            contained=tuple(contained), missing=tuple(missing),
        )
        self.requests.append(record)
        return record

    def delivered_to(self, stage: str) -> tuple[str, ...]:
        """Lens identities some request from ``stage`` actually carried."""
        seen: list[str] = []
        for record in self.requests:
            if record.stage != stage:
                continue
            seen.extend(i for i in record.contained if i not in seen)
        return tuple(seen)

    def as_evidence(self) -> dict:
        return {
            "artifact_kind": "stage_routing",
            "publishable": False,
            "notice": (
                "Diagnostic evidence only: what each stage was routed and "
                "whether its model requests carried it. No prompt, credential "
                "or article text is stored."
            ),
            "run_id": self.run_id,
            "plan_stage": self.plan_stage,
            "routed": {
                stage: [lens.as_evidence() for lens in lenses]
                for stage, lenses in sorted(self.routed.items())
            },
            "requests": [record.as_evidence() for record in self.requests],
            "delivered": {
                stage: list(self.delivered_to(stage)) for stage in sorted(self.routed)
            },
        }


#: The recorder for the run in progress; ``None`` outside a recorded run, and
#: then every hook below is a no-op.
_ROUTING: ContextVar[StageRouting | None] = ContextVar("nb_stage_routing", default=None)

#: The stage whose model calls are being made right now.
_STAGE: ContextVar[str] = ContextVar("nb_stage", default="")


@contextmanager
def recording(routing: StageRouting) -> Iterator[StageRouting]:
    """Record stage routing for the run inside this block."""
    token = _ROUTING.set(routing)
    try:
        yield routing
    finally:
        _ROUTING.reset(token)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Attribute the model calls made inside this block to ``name``."""
    token = _STAGE.set(name)
    try:
        yield
    finally:
        _STAGE.reset(token)


def current() -> StageRouting | None:
    return _ROUTING.get()


def observe_request(request: str) -> None:
    """Hook for the shared model client: measure one outgoing request.

    A no-op unless a run is recording and a stage is named, so nothing outside
    a recorded generation pays for it.
    """
    routing, name = _ROUTING.get(), _STAGE.get()
    if routing is None or not name:
        return
    routing.observe(name, request)
