"""ENGINE: load a client's human-readable contracts and route them to stages.

Owner decision D12 (#240): the Engine is content-domain agnostic. What a stream
is for, what makes a signal usable, which sources count, how a revision should
behave — all of that is a **client's** policy, written by people as Markdown
documents under the client's directory. This module is the Engine side of that
boundary: it reads those documents, validates their shape, and hands each stage
exactly the client text addressed to it. It knows nothing about any client.

Three document kinds:

* **Stream contract** (``<client>/streams/*.md``). Parsed, so its headings are a
  contract — ``## Purpose`` then ``## Selection``, and optionally ``## Plan`` —
  and a missing or unknown heading fails instead of silently dropping a rule
  (#233 F-03). Under ``## Selection`` the client may group bullets under any
  ``###`` headings; every bullet is one selection requirement. Under ``## Plan``
  each ``###`` heading names one **plan slot** the Engine carries (#267) and its
  bullets are that slot's client-owned values; a slot name the Engine does not
  carry fails rather than being ignored. Front matter: ``stream_id``,
  ``version``, ``role_id``, ``selection`` — exact data the Engine needs, nothing
  else.
* **Lens** (``<client>/lenses/*.md``). Not parsed: the whole body is delivered
  verbatim to the stages its front matter names — ``lens_id``, ``version``,
  ``applies_to`` (stream ids), ``stages``, and optionally ``activates_on``.
  Without ``activates_on`` a lens is a **standing obligation** and reaches its
  stages on every run; with it the lens is **conditional** and reaches them only
  when the run supplies activation evidence for one of the conditions it names
  (#267). A condition is decided on the run's research evidence, so a
  conditional lens may route only to stages that run after research
  (``CONDITIONAL_STAGES``); one routed to ``selection`` is refused rather than
  loaded as policy nothing can execute. Zero lenses is a valid state.
* **Shared list** (``<client>/lists/*.md``). A list of strings the client's
  output may not contain — machine tells, banned phrases, whatever the client
  puts in it. Front matter: ``list_id``, ``version``, ``applies_to`` (stream
  ids); body: one bullet per entry. Shared because one list applies to as many
  streams as it names. The Engine matches; what is in the list is client policy.

In every kind, an HTML comment (``<!-- ... -->``) is a note for people and is
never delivered to a model.

Stages the Engine can route to today: ``selection`` (the candidate judgment),
``writing`` (the article and post composers) and ``revision`` (the reviser).

Which client is active is deployment configuration, not code: ``NB_CLIENT_DIR``,
defaulting to this repository's own client directory. Replacing the client means
replacing that directory — the Replace-the-client test (#240 D12 addendum).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from src.knowledge.ladder import CLIENT_LADDER_SLOT, level_names

#: The deployment default. Another customer sets NB_CLIENT_DIR; no code changes.
DEFAULT_CLIENT_DIR: Final[Path] = Path("clients/never_blank")

#: Stages a lens may address. Adding one is an Engine capability decision.
STAGES: Final[frozenset[str]] = frozenset({"selection", "writing", "revision"})

#: The stages a conditional lens can execute at (#267): those that run after
#: research, where the evidence a condition is decided on exists. ``selection``
#: is not one — it chooses the candidate before any research is done, so no
#: activation decision can precede it. In the order a run reaches them.
CONDITIONAL_STAGES: Final[tuple[str, ...]] = ("writing", "revision")

#: Selection modes the Engine implements. ``first_valid``: read candidates in
#: queue order and select the first that satisfies every selection requirement.
SELECTION_MODES: Final[frozenset[str]] = frozenset({"first_valid"})

#: Plan slots whose value is one string the run chooses from what the contract
#: permits. The names are Engine structure; every value is the client's, so an
#: editorial rotation changes a document and never this list (#267).
PLAN_SCALAR_SLOTS: Final[tuple[str, ...]] = (
    "claim_strength_ceiling", "ending_mode", "audience_currency",
    "reader_verifiable_artifact",
)

#: Plan slots the contract states as a list. What the client declares stands for
#: every run; a run may add to it, never drop from it.
PLAN_LIST_SLOTS: Final[tuple[str, ...]] = ("factual_restrictions", "acknowledged_limits")

#: Plan slots a run derives from its own evidence. A contract that declares
#: values for one of these is refused: it would be stating in advance what only
#: the run can find.
PLAN_RUN_SLOTS: Final[tuple[str, ...]] = (
    "central_claim", "evidence_package", "active_lenses", "portable_noun", "lineage",
)

#: Every slot an ``EditorialPlan`` carries.
PLAN_SLOTS: Final[tuple[str, ...]] = (
    *PLAN_SCALAR_SLOTS, *PLAN_LIST_SLOTS, *PLAN_RUN_SLOTS
)

_STREAM_KEYS: Final[frozenset[str]] = frozenset({"stream_id", "version", "role_id", "selection"})
_LENS_KEYS: Final[frozenset[str]] = frozenset({"lens_id", "version", "applies_to", "stages"})
#: Declared by a conditional lens only; absent means a standing obligation.
_LENS_OPTIONAL_KEYS: Final[frozenset[str]] = frozenset({"activates_on"})
_LIST_KEYS: Final[frozenset[str]] = frozenset({"list_id", "version", "applies_to"})
#: The stream heading contract, in order. Level-3 headings are allowed under
#: Selection (any name the client likes) and under Plan (one Engine slot each).
_STREAM_HEADINGS: Final[tuple[str, ...]] = ("Purpose", "Selection")
#: May follow the contract headings; the streams that plan nothing omit it.
_STREAM_PLAN_HEADING: Final[str] = "Plan"

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


class _UniqueKeyLoader(yaml.SafeLoader):
    """YAML with duplicate keys refused: last-value-wins would silently drop one."""


def _construct_unique_mapping(loader, node, deep=False):
    keys = [loader.construct_object(key, deep=deep) for key, _ in node.value]
    duplicated = sorted({str(k) for k in keys if keys.count(k) > 1})
    if duplicated:
        raise ClientContractError(f"duplicate front-matter key(s): {', '.join(duplicated)}")
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


class ClientContractError(ValueError):
    """A client document cannot be read as a contract; nothing may run on it."""


def client_dir() -> Path:
    """The active client's directory (``NB_CLIENT_DIR``, else the default)."""
    configured = os.environ.get("NB_CLIENT_DIR", "").strip()
    return Path(configured) if configured else DEFAULT_CLIENT_DIR


@dataclass(frozen=True, slots=True)
class StreamContract:
    stream_id: str
    version: str
    role_id: str
    selection: str
    #: ``## Purpose`` — the stream's editorial intent, as prose.
    purpose: str
    #: Every bullet under ``## Selection``, verbatim, in document order.
    requirements: tuple[str, ...]
    path: str
    digest: str
    #: ``## Plan``: one entry per declared slot, values in document order. Empty
    #: when the stream declares no plan, which is a valid state.
    plan_slots: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def identity(self) -> str:
        return f"{self.stream_id}/{self.version}"

    def plan_values(self, slot: str) -> tuple[str, ...]:
        """What the contract declares for ``slot``; empty when it declares none.

        Order is the client's own and carries whatever meaning the client gave
        it — for ``claim_strength_ceiling`` it is the strength ladder, weakest
        first, which is the only reason the Engine can compare two strengths
        without knowing what either one means.

        A ladder level may also declare which universal level it maps to
        (``… → universal level 2``, Step 4 §7). That declaration is about the
        level, not part of its name, so what the Engine carries into a plan stays
        the wording a person reads. ``plan_slots`` keeps the line as written,
        which is what the register validator reads it from.
        """
        if slot not in PLAN_SLOTS:
            raise ClientContractError(f"unknown plan slot {slot!r}")
        for name, values in self.plan_slots:
            if name == slot:
                return level_names(values) if slot == CLIENT_LADDER_SLOT else values
        return ()


@dataclass(frozen=True, slots=True)
class Lens:
    lens_id: str
    version: str
    applies_to: tuple[str, ...]
    stages: tuple[str, ...]
    #: The whole body, verbatim — the Engine never interprets it.
    text: str
    path: str
    digest: str
    #: The conditions any one of which activates this lens. Empty is a standing
    #: obligation: it applies to every run of the stream.
    activates_on: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        return f"{self.lens_id}/{self.version}"

    @property
    def is_standing(self) -> bool:
        return not self.activates_on


@dataclass(frozen=True, slots=True)
class SharedList:
    list_id: str
    version: str
    applies_to: tuple[str, ...]
    #: One entry per bullet, verbatim — the Engine matches, never interprets.
    entries: tuple[str, ...]
    path: str
    digest: str

    @property
    def identity(self) -> str:
        return f"{self.list_id}/{self.version}"


@dataclass(frozen=True, slots=True)
class ClientContracts:
    """Everything a client supplies for one stream, routed by stage."""

    stream: StreamContract
    lenses: tuple[Lens, ...]
    lists: tuple[SharedList, ...] = ()

    def for_stage(self, stage: str) -> tuple[str, ...]:
        """The standing obligations routed to ``stage``.

        A conditional lens is deliberately not here: it reaches a stage only
        through an ``EditorialPlan`` that recorded what activated it (#267), so
        a call site that predates conditions cannot deliver one unconditionally.
        """
        if stage not in STAGES:
            raise ClientContractError(f"unknown stage {stage!r}")
        return tuple(
            lens.text for lens in self.lenses
            if stage in lens.stages and lens.is_standing
        )

    def conditional_for_stage(self, stage: str) -> tuple[Lens, ...]:
        """The lenses routed to ``stage`` that a run must activate to use."""
        if stage not in STAGES:
            raise ClientContractError(f"unknown stage {stage!r}")
        return tuple(
            lens for lens in self.lenses
            if stage in lens.stages and not lens.is_standing
        )

    @property
    def requires_plan(self) -> bool:
        """Whether a run must build an ``EditorialPlan`` to carry this contract.

        Two independent reasons, either one sufficient: the stream declares a
        ``## Plan``, or some lens is conditional — a conditional lens reaches a
        model only through a plan that recorded what activated it, so without
        one it could never apply.
        """
        return bool(self.stream.plan_slots) or any(
            not lens.is_standing for lens in self.lenses
        )

    @property
    def activation_conditions(self) -> tuple[str, ...]:
        """Every condition some conditional lens names, in document order."""
        conditions: list[str] = []
        for lens in self.lenses:
            conditions.extend(c for c in lens.activates_on if c not in conditions)
        return tuple(conditions)

    @property
    def banned_entries(self) -> tuple[tuple[str, str], ...]:
        """``(entry, list identity)`` for every entry of every shared list."""
        return tuple(
            (entry, shared.identity) for shared in self.lists for entry in shared.entries
        )

    @property
    def selection_requirements(self) -> tuple[str, ...]:
        """The stream's own rules, then every standing lens routed to selection."""
        return (*self.stream.requirements, *self.for_stage("selection"))

    @property
    def provenance(self) -> dict:
        """What a run records: the exact client texts that governed it."""
        return {
            "stream": {"identity": self.stream.identity, "path": self.stream.path,
                       "digest": self.stream.digest},
            "lenses": [{"identity": lens.identity, "path": lens.path,
                        "digest": lens.digest, "stages": list(lens.stages),
                        "activates_on": list(lens.activates_on)}
                       for lens in self.lenses],
            "lists": [{"identity": shared.identity, "path": shared.path,
                       "digest": shared.digest}
                      for shared in self.lists],
        }


# ── parsing ─────────────────────────────────────────────────────────────────


def _front_matter(text: str, path: Path) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ClientContractError(f"{path}: front matter must open on the first line")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ClientContractError(f"{path}: front matter is never closed") from None
    try:
        data = yaml.load("\n".join(lines[1:end]), Loader=_UniqueKeyLoader) or {}  # noqa: S506
    except ClientContractError as exc:
        raise ClientContractError(f"{path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ClientContractError(f"{path}: front matter is not valid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise ClientContractError(f"{path}: front matter must be a mapping")
    return data, "\n".join(lines[end + 1:])


def _require_keys(
    data: dict, keys: frozenset[str], path: Path, optional: frozenset[str] = frozenset()
) -> None:
    unknown = sorted(str(k) for k in data if k not in keys and k not in optional)
    missing = sorted(keys - set(data))
    if unknown:
        raise ClientContractError(f"{path}: unknown front-matter key(s): {', '.join(unknown)}")
    if missing:
        raise ClientContractError(f"{path}: missing front-matter key(s): {', '.join(missing)}")


def _text(data: dict, key: str, path: Path) -> str:
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise ClientContractError(f"{path}: front-matter `{key}` must be a non-empty string")
    return value.strip()


def _text_list(data: dict, key: str, path: Path) -> tuple[str, ...]:
    value = data[key]
    if (not isinstance(value, list) or not value
            or not all(isinstance(v, str) and v.strip() for v in value)
            or len(set(value)) != len(value)):
        raise ClientContractError(
            f"{path}: front-matter `{key}` must be a non-empty list of distinct strings"
        )
    return tuple(v.strip() for v in value)


def _strip_comments(body: str, path: Path) -> str:
    """Remove people-only notes; a malformed one must not reach a model."""
    stripped = _COMMENT.sub("", body)
    if "<!--" in stripped or "-->" in stripped:
        raise ClientContractError(f"{path}: an HTML comment is not closed (`<!--` … `-->`)")
    return stripped


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read(path: Path) -> tuple[bytes, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ClientContractError(f"{path}: cannot be read ({exc})") from exc
    return raw, raw.decode("utf-8")


def _bullets(lines: list[str], path: Path) -> tuple[str, ...]:
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or _HEADING.match(line):
            continue
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        elif items and line[:1].isspace():
            items[-1] = f"{items[-1]} {stripped}"
        else:
            raise ClientContractError(
                f"{path}: every line under `## Selection` must be a `###` group heading, "
                f"a bullet (`- `) or its indented continuation; got {stripped[:60]!r}"
            )
    if not items:
        raise ClientContractError(f"{path}: `## Selection` has no rules")
    return tuple(items)


def _plan(lines: list[str], path: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """``## Plan`` as declared slots — the Engine's names, the client's values.

    A ``###`` heading the Engine does not carry stops the run: a slot whose name
    was misspelt would otherwise be a policy the client wrote and nothing reads,
    which is the failure this section exists to make impossible (#267).
    """
    groups: list[tuple[str, list[str]]] = []
    for line in lines:
        heading = _HEADING.match(line)
        if heading:
            slot = heading.group(2).strip()
            if slot not in PLAN_SLOTS:
                raise ClientContractError(
                    f"{path}: `### {slot}` is not a plan slot the Engine carries "
                    f"(slots: {', '.join(PLAN_SCALAR_SLOTS + PLAN_LIST_SLOTS)})"
                )
            if slot in PLAN_RUN_SLOTS:
                raise ClientContractError(
                    f"{path}: `### {slot}` is decided by the run from its own evidence; "
                    "a contract may require it but may not state its value"
                )
            if any(name == slot for name, _ in groups):
                raise ClientContractError(f"{path}: plan slot `{slot}` is declared twice")
            groups.append((slot, []))
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if not groups:
            raise ClientContractError(
                f"{path}: every line under `## Plan` belongs to a `### <slot>` group; "
                f"got {stripped[:60]!r}"
            )
        values = groups[-1][1]
        if stripped.startswith("- "):
            values.append(stripped[2:].strip())
        elif values and line[:1].isspace():
            values[-1] = f"{values[-1]} {stripped}"
        else:
            raise ClientContractError(
                f"{path}: every line under `### {groups[-1][0]}` must be a bullet (`- `) "
                f"or its indented continuation; got {stripped[:60]!r}"
            )
    for slot, values in groups:
        if not values:
            raise ClientContractError(f"{path}: plan slot `{slot}` declares no values")
        if len(set(values)) != len(values):
            raise ClientContractError(f"{path}: plan slot `{slot}` repeats a value")
    return tuple((slot, tuple(values)) for slot, values in groups)


def load_stream_contract(path: Path) -> StreamContract:
    raw, text = _read(path)
    data, body = _front_matter(text, path)
    body = _strip_comments(body, path)
    _require_keys(data, _STREAM_KEYS, path)
    selection = _text(data, "selection", path)
    if selection not in SELECTION_MODES:
        raise ClientContractError(
            f"{path}: selection {selection!r} is not implemented "
            f"(supported: {', '.join(sorted(SELECTION_MODES))})"
        )

    found: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        match = _HEADING.match(line)
        if not match:
            if current is not None:
                sections[current].append(line)
            continue
        level = len(match.group(1))
        if level == 1:
            # one document title, for people, before the contract begins
            if found:
                raise ClientContractError(
                    f"{path}: `{line.strip()}` — a `#` title may only precede `## Purpose`"
                )
            continue
        if level == 2:
            current = match.group(2).strip()
            found.append(current)
            sections[current] = []
            continue
        if level == 3 and current in (_STREAM_HEADINGS[1], _STREAM_PLAN_HEADING):
            sections[current].append(line)
            continue
        raise ClientContractError(
            f"{path}: `{line.strip()}` — only `###` group headings are allowed, "
            "and only under `## Selection` or `## Plan`"
        )
    if tuple(found) not in (_STREAM_HEADINGS, (*_STREAM_HEADINGS, _STREAM_PLAN_HEADING)):
        raise ClientContractError(
            f"{path}: headings must be exactly [## Purpose, ## Selection], optionally "
            f"followed by [## Plan], in that order; "
            f"found [{', '.join('## ' + f for f in found) or 'none'}]"
        )
    purpose = " ".join(" ".join(l.split()) for l in sections["Purpose"] if l.strip())
    if not purpose:
        raise ClientContractError(f"{path}: `## Purpose` is empty")
    return StreamContract(
        stream_id=_text(data, "stream_id", path),
        version=_text(data, "version", path),
        role_id=_text(data, "role_id", path),
        selection=selection,
        purpose=purpose,
        requirements=_bullets(sections["Selection"], path),
        path=str(path),
        digest=_digest(raw),
        plan_slots=_plan(sections.get(_STREAM_PLAN_HEADING, []), path),
    )


def load_lens(path: Path) -> Lens:
    raw, text = _read(path)
    data, body = _front_matter(text, path)
    body = _strip_comments(body, path)
    _require_keys(data, _LENS_KEYS, path, optional=_LENS_OPTIONAL_KEYS)
    stages = _text_list(data, "stages", path)
    unknown = sorted(set(stages) - STAGES)
    if unknown:
        raise ClientContractError(
            f"{path}: unknown stage(s) {', '.join(unknown)} "
            f"(the Engine routes to: {', '.join(sorted(STAGES))})"
        )
    activates_on = (
        _text_list(data, "activates_on", path) if "activates_on" in data else ()
    )
    unexecutable = [stage for stage in stages if stage not in CONDITIONAL_STAGES]
    if activates_on and unexecutable:
        raise ClientContractError(
            f"{path}: a conditional lens (`activates_on`) cannot route to "
            f"{', '.join(unexecutable)} — its condition is decided on the run's "
            "research evidence, which does not exist yet at that stage. A "
            f"conditional lens may route to: {', '.join(CONDITIONAL_STAGES)}; "
            "make it a standing lens to apply it at selection"
        )
    content = re.sub(r"\n{3,}", "\n\n", body).strip()
    if not content:
        raise ClientContractError(f"{path}: the lens has no content")
    return Lens(
        lens_id=_text(data, "lens_id", path),
        version=_text(data, "version", path),
        applies_to=_text_list(data, "applies_to", path),
        stages=stages,
        text=content,
        path=str(path),
        digest=_digest(raw),
        activates_on=activates_on,
    )


def load_shared_list(path: Path) -> SharedList:
    raw, text = _read(path)
    data, body = _front_matter(text, path)
    body = _strip_comments(body, path)
    _require_keys(data, _LIST_KEYS, path)
    entries: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        # a `#` title is for people, exactly as in the other document kinds
        if not stripped or _HEADING.match(line):
            continue
        if stripped.startswith("- "):
            entries.append(stripped[2:].strip())
        elif entries and line[:1].isspace():
            entries[-1] = f"{entries[-1]} {stripped}"
        else:
            raise ClientContractError(
                f"{path}: every line of a shared list must be a bullet (`- `) or its "
                f"indented continuation; got {stripped[:60]!r}"
            )
    if not entries:
        raise ClientContractError(f"{path}: the list has no entries")
    if len(set(entries)) != len(entries):
        raise ClientContractError(f"{path}: the list repeats an entry")
    return SharedList(
        list_id=_text(data, "list_id", path),
        version=_text(data, "version", path),
        applies_to=_text_list(data, "applies_to", path),
        entries=tuple(entries),
        path=str(path),
        digest=_digest(raw),
    )


# ── resolution ──────────────────────────────────────────────────────────────


def contracts_for_role(role_id: str, directory: Path | None = None) -> ClientContracts | None:
    """The client's contracts for the stream that governs ``role_id``, if any.

    Every document is read and validated, so a broken file fails the run even
    when it governs another stream. A role claimed by two stream contracts, or a
    lens or list id declared twice, is refused: one authority per rule. ``None``
    means the client supplies nothing for this role, which is a valid state.
    """
    root = directory if directory is not None else client_dir()
    streams_dir, lenses_dir = root / "streams", root / "lenses"
    lists_dir = root / "lists"
    streams = [load_stream_contract(p) for p in sorted(streams_dir.glob("*.md"))] \
        if streams_dir.is_dir() else []
    lenses = [load_lens(p) for p in sorted(lenses_dir.glob("*.md"))] \
        if lenses_dir.is_dir() else []
    lists = [load_shared_list(p) for p in sorted(lists_dir.glob("*.md"))] \
        if lists_dir.is_dir() else []

    ids = [lens.lens_id for lens in lenses]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ClientContractError(f"lens id(s) declared twice: {', '.join(duplicated)}")
    list_ids = [shared.list_id for shared in lists]
    duplicated = sorted({i for i in list_ids if list_ids.count(i) > 1})
    if duplicated:
        raise ClientContractError(f"list id(s) declared twice: {', '.join(duplicated)}")
    stream_ids = [stream.stream_id for stream in streams]
    duplicated = sorted({i for i in stream_ids if stream_ids.count(i) > 1})
    if duplicated:
        raise ClientContractError(
            f"stream id(s) declared by more than one stream contract: {', '.join(duplicated)}"
        )
    matches = [s for s in streams if s.role_id == role_id]
    if len(matches) > 1:
        raise ClientContractError(
            f"role {role_id!r} is claimed by more than one stream contract: "
            + ", ".join(m.path for m in matches)
        )
    if not matches:
        return None
    stream = matches[0]
    return ClientContracts(
        stream=stream,
        lenses=tuple(lens for lens in lenses if stream.stream_id in lens.applies_to),
        lists=tuple(shared for shared in lists if stream.stream_id in shared.applies_to),
    )
