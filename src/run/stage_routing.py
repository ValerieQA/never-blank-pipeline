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

Knowledge records are routed and proved the same way (Step 4 §9.6, Step 2 §0.7).
The difference is what a gap means: a lens that did not arrive is a client
obligation the stage worked without, while a **mandatory** record that did not
arrive is a hard-policy surface with a hole in it, which is why those are listed
apart. A stage also declares what its requests may not carry — the label
vocabulary, which is written after the decision and never enters S-00…S-13 — and
a request carrying one is recorded as a violation (AD-07).

Deliberately not stored: prompts, provider keys, model values, article text. A
SHA-256 over the request proves which request was measured without carrying its
contents into an artifact.

Generic: no client, stream, weekday or lens is named here. The Engine records
the routing a contract declared; what that routing means is the contract's.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, Protocol


@dataclass(frozen=True, slots=True)
class RoutedLens:
    """One client obligation a run routed to a stage.

    ``text`` is the whole obligation, in memory only: containment is checked
    against all of it, because a prefix proves nothing about the rest (#280
    review). An article's opening rule can sit in the last paragraph of a
    lens, and a record that called a lens delivered on its first eighty
    characters would vouch for exactly the delivery #279 exists to prove.

    ``as_evidence`` deliberately omits it: the artifact carries identity,
    digest and result, never the client's text.
    """

    identity: str
    digest: str
    text: str

    @property
    def normalized(self) -> str:
        return " ".join((self.text or "").split()).casefold()

    def as_evidence(self) -> dict:
        return {"lens": self.identity, "digest": self.digest}


@dataclass(frozen=True, slots=True)
class RoutedRecord:
    """One knowledge record a run routed to a stage (Step 4 §9.3, §9.6).

    The same proof as a lens, over a second kind of obligation. ``mandatory``
    is what makes it more than a second copy: Step 4 §9.6 lets a stage cut
    descriptive knowledge for context size and never lets it cut a rule, so the
    record has to say which kind each routed item was. A request that left a
    mandatory record out is a request that went out with a hole in its
    hard-policy surface, and ``mandatory_missing`` is where that shows.

    ``text`` is the record's own material, in memory only, for the same reason
    a lens keeps its text: containment is checked against all of it, and the
    evidence carries identity, version and status rather than the words.
    """

    identity: str
    version: int
    tier: str
    #: The status the loader computed for this run, not the one in the file.
    effective_status: str
    digest: str
    text: str
    mandatory: bool = False
    #: True when `review_by` has passed and Step 4 §5 kept the record in force.
    expired_review: bool = False

    @property
    def normalized(self) -> str:
        return " ".join((self.text or "").split()).casefold()

    def as_evidence(self) -> dict:
        return {"record": self.identity, "version": self.version,
                "tier": self.tier, "effective_status": self.effective_status,
                "digest": self.digest, "mandatory": self.mandatory,
                "expired_review": self.expired_review}


#: Not routed, routed and carried, routed and not carried. A reader must be
#: able to tell these apart from the record alone (#280 review, MEDIUM-3).
NOT_ROUTED: Final[str] = "not_routed"
COMPLETE: Final[str] = "complete"
INCOMPLETE: Final[str] = "incomplete"
#: The request carried something it was declared forbidden. Its own state, and
#: the most serious one: a missing obligation is work that did not reach a
#: stage, while a forbidden term is material that must never reach one (AD-07).
VIOLATION: Final[str] = "violation"


def request_surface(system: str, user: str) -> str:
    """The request material routing is verified against (#280 review).

    Both messages, in a deterministic shape. The digest and the containment
    check read this same surface: a digest over less than what was checked
    would describe a different request than the one the record vouches for,
    and routed material placed in a system prompt would read as missing.
    """
    return f"SYSTEM:\n{system or ''}\n\nUSER:\n{user or ''}"


@dataclass(frozen=True, slots=True)
class StageRequest:
    """One model request a stage issued, and whether it carried the routing."""

    stage: str
    #: SHA-256 over ``request_surface`` — system and user together.
    request_sha256: str
    contained: tuple[str, ...]
    missing: tuple[str, ...]
    #: Whether anything was routed to this stage at all.
    routed: bool = True
    #: The same two lists for the knowledge records routed to the stage.
    knowledge_contained: tuple[str, ...] = ()
    knowledge_missing: tuple[str, ...] = ()
    #: The subset of ``knowledge_missing`` that may never be cut. This is the
    #: containment proof Step 4 §9.6 asks for per request: empty means every
    #: mandatory record was present in the request that was actually made.
    mandatory_missing: tuple[str, ...] = ()
    #: Forbidden terms the request carried, recorded as a violation (AD-07).
    forbidden_present: tuple[str, ...] = ()

    @property
    def state(self) -> str:
        if self.forbidden_present:
            return VIOLATION
        if not self.routed:
            return NOT_ROUTED
        if self.missing or self.knowledge_missing:
            return INCOMPLETE
        return COMPLETE

    def as_evidence(self) -> dict:
        return {"stage": self.stage, "request_sha256": self.request_sha256,
                "routed": self.routed, "state": self.state,
                "contained": list(self.contained), "missing": list(self.missing),
                "knowledge_contained": list(self.knowledge_contained),
                "knowledge_missing": list(self.knowledge_missing),
                "mandatory_missing": list(self.mandatory_missing),
                "forbidden_present": list(self.forbidden_present)}


@dataclass
class StageRouting:
    """The run's routing record: what was routed, and what went out."""

    run_id: str = ""
    plan_stage: str = ""
    routed: dict[str, tuple[RoutedLens, ...]] = field(default_factory=dict)
    knowledge: dict[str, tuple[RoutedRecord, ...]] = field(default_factory=dict)
    #: Vocabulary no request of a declaring stage may carry (AD-07).
    forbidden: dict[str, tuple[str, ...]] = field(default_factory=dict)
    requests: list[StageRequest] = field(default_factory=list)

    def route(self, stage: str, lenses: Sequence[RoutedLens]) -> None:
        """Declare what this run routed to ``stage`` before it runs."""
        self.routed[stage] = tuple(lenses)

    def route_knowledge(self, stage: str, records: Sequence[RoutedRecord]) -> None:
        """Declare the knowledge records routed to ``stage`` before it runs."""
        self.knowledge[stage] = tuple(records)

    def forbid(self, stage: str, terms: Sequence[str]) -> None:
        """Declare vocabulary ``stage`` may not carry into a request.

        The label vocabulary is what this exists for: labels are written after
        the decision and never reach S-00…S-13, so a request carrying one is
        recorded as a violation rather than left for a reader to notice (AD-07,
        Step 2 §0.7).
        """
        self.forbidden[stage] = tuple(term for term in terms if term.strip())

    def observe(self, stage: str, system: str = "", user: str = "") -> StageRequest:
        """Measure one outgoing request against what ``stage`` was routed.

        The surface measured is both messages (``request_surface``), the
        digest covers exactly what the containment check read, and an
        obligation counts as contained only when the request carries ALL of
        it — whitespace normalized, nothing else forgiven. Knowledge records
        are measured the same way, and a mandatory record that is missing is
        listed twice: once as missing, once as the containment proof §9.6 asks
        each request for.
        """
        lenses = self.routed.get(stage, ())
        records = self.knowledge.get(stage, ())
        surface = request_surface(system, user)
        haystack = " ".join(surface.split()).casefold()
        contained, missing = _containment(lenses, haystack)
        carried, absent = _containment(records, haystack)
        record = StageRequest(
            stage=stage,
            request_sha256=hashlib.sha256(surface.encode("utf-8")).hexdigest(),
            contained=contained, missing=missing,
            routed=bool(lenses or records),
            knowledge_contained=carried, knowledge_missing=absent,
            mandatory_missing=tuple(
                item.identity
                for item in records
                if item.mandatory and item.identity in absent
            ),
            forbidden_present=_terms_present(
                self.forbidden.get(stage, ()), haystack
            ),
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

    def knowledge_delivered_to(self, stage: str) -> tuple[str, ...]:
        """Record ids some request from ``stage`` actually carried."""
        seen: list[str] = []
        for record in self.requests:
            if record.stage != stage:
                continue
            seen.extend(i for i in record.knowledge_contained if i not in seen)
        return tuple(seen)

    def violations(self) -> tuple[StageRequest, ...]:
        """Every request that carried forbidden vocabulary (AD-07)."""
        return tuple(
            record for record in self.requests if record.forbidden_present
        )

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
            "knowledge": {
                stage: [item.as_evidence() for item in items]
                for stage, items in sorted(self.knowledge.items())
            },
            "forbidden": {
                stage: list(terms) for stage, terms in sorted(self.forbidden.items())
            },
            "requests": [record.as_evidence() for record in self.requests],
            "delivered": {
                stage: list(self.delivered_to(stage)) for stage in sorted(self.routed)
            },
            "knowledge_delivered": {
                stage: list(self.knowledge_delivered_to(stage))
                for stage in sorted(self.knowledge)
            },
        }


class _Obligation(Protocol):
    """What containment needs of a routed thing: a name, and all of its text."""

    @property
    def identity(self) -> str: ...

    @property
    def normalized(self) -> str: ...


def _containment(
    expected: Sequence[_Obligation], haystack: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Which obligations the request carried, and which it did not."""
    contained: list[str] = []
    missing: list[str] = []
    for item in expected:
        whole = item.normalized
        (contained if whole and whole in haystack else missing).append(item.identity)
    return tuple(contained), tuple(missing)


def _terms_present(terms: Sequence[str], haystack: str) -> tuple[str, ...]:
    """Forbidden terms the request carried, however each one was spelt.

    ``material_label``, ``Material Label`` and ``material label`` are one term,
    and the words have to stand on their own: a term is present when its words
    appear in order separated by nothing but spaces, underscores or hyphens.
    Anything looser would report a forbidden term inside an ordinary word.
    """
    present: list[str] = []
    for term in terms:
        pattern = _term_pattern(term)
        if pattern is not None and pattern.search(haystack):
            present.append(term)
    return tuple(present)


@lru_cache(maxsize=512)
def _term_pattern(term: str) -> re.Pattern[str] | None:
    words = [part for part in re.split(r"[^A-Za-z0-9]+", term) if part]
    if not words:
        return None
    joined = r"[\s_\-]+".join(re.escape(word) for word in words)
    return re.compile(rf"\b{joined}\b", re.IGNORECASE)


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


def observe_request(system: str = "", user: str = "") -> None:
    """Hook for the shared model client: measure one outgoing request.

    Called after the run's call budget has accepted the call and before the
    provider is dispatched, so a call the budget refused is never written down
    as one that went out (#280 review, MEDIUM-1). A no-op unless a run is
    recording and a stage is named, so nothing outside a recorded generation
    pays for it.
    """
    routing, name = _ROUTING.get(), _STAGE.get()
    if routing is None or not name:
        return
    routing.observe(name, system, user)
