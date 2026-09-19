"""ENGINE: load a client's human-readable contracts and route them to stages.

Owner decision D12 (#240): the Engine is content-domain agnostic. What a stream
is for, what makes a signal usable, which sources count, how a revision should
behave — all of that is a **client's** policy, written by people as Markdown
documents under the client's directory. This module is the Engine side of that
boundary: it reads those documents, validates their shape, and hands each stage
exactly the client text addressed to it. It knows nothing about any client.

Two document kinds:

* **Stream contract** (``<client>/streams/*.md``). Parsed, so its headings are a
  contract — ``## Purpose`` then ``## Selection`` — and a missing or unknown
  heading fails instead of silently dropping a rule (#233 F-03). Under
  ``## Selection`` the client may group bullets under any ``###`` headings; every
  bullet is one selection requirement. Front matter: ``stream_id``, ``version``,
  ``role_id``, ``selection`` — exact data the Engine needs, nothing else.
* **Lens** (``<client>/lenses/*.md``). Not parsed: the whole body is delivered
  verbatim to the stages its front matter names — ``lens_id``, ``version``,
  ``applies_to`` (stream ids), ``stages``. Zero lenses is a valid state.
  Optional ``activation``: ``always`` (the default) or ``conditional`` (#263). A
  conditional lens has exactly two sections — ``## Activation``, the client's
  own condition, and ``## When active``, its behaviour — and reaches its stages
  only when a run's research evidence meets that condition. The Engine decides
  *whether* the client's condition holds; it never knows *what* the condition
  is. A conditional lens cannot address ``selection``: whether it applies is
  decided from research evidence, which selection runs before.

In either kind, an HTML comment (``<!-- ... -->``) is a note for people and is
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

#: The deployment default. Another customer sets NB_CLIENT_DIR; no code changes.
DEFAULT_CLIENT_DIR: Final[Path] = Path("clients/never_blank")

#: Stages a lens may address. Adding one is an Engine capability decision.
STAGES: Final[frozenset[str]] = frozenset({"selection", "writing", "revision"})

#: Selection modes the Engine implements. ``first_valid``: read candidates in
#: queue order and select the first that satisfies every selection requirement.
SELECTION_MODES: Final[frozenset[str]] = frozenset({"first_valid"})

_STREAM_KEYS: Final[frozenset[str]] = frozenset({"stream_id", "version", "role_id", "selection"})
_LENS_KEYS: Final[frozenset[str]] = frozenset({"lens_id", "version", "applies_to", "stages"})
_LENS_OPTIONAL_KEYS: Final[frozenset[str]] = frozenset({"activation"})
#: How a lens is applied. ``conditional``: only when the run's research
#: evidence meets the client's own ``## Activation`` condition (#263).
ACTIVATIONS: Final[frozenset[str]] = frozenset({"always", "conditional"})
#: The conditional-lens heading contract, in order.
_CONDITIONAL_HEADINGS: Final[tuple[str, ...]] = ("Activation", "When active")
#: The stream heading contract, in order. Level-3 headings under Selection are free.
_STREAM_HEADINGS: Final[tuple[str, ...]] = ("Purpose", "Selection")

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

    @property
    def identity(self) -> str:
        return f"{self.stream_id}/{self.version}"


@dataclass(frozen=True, slots=True)
class Lens:
    lens_id: str
    version: str
    applies_to: tuple[str, ...]
    stages: tuple[str, ...]
    #: The whole body, verbatim — the Engine never interprets it. For a
    #: conditional lens: its ``## When active`` behaviour only.
    text: str
    path: str
    digest: str
    #: ``always`` or ``conditional`` (#263).
    activation: str = "always"
    #: A conditional lens's own ``## Activation`` condition, verbatim.
    activation_criteria: str = ""

    @property
    def identity(self) -> str:
        return f"{self.lens_id}/{self.version}"

    @property
    def conditional(self) -> bool:
        return self.activation == "conditional"


@dataclass(frozen=True, slots=True)
class ClientContracts:
    """Everything a client supplies for one stream, routed by stage."""

    stream: StreamContract
    lenses: tuple[Lens, ...]

    def for_stage(self, stage: str, active: "frozenset[str] | set[str] | tuple[str, ...]" = ()
                  ) -> tuple[str, ...]:
        """The client texts addressed to ``stage``.

        Always-on lenses every time; a conditional lens only when its id is
        in ``active`` — the lenses this run's evidence activated (#263).
        """
        if stage not in STAGES:
            raise ClientContractError(f"unknown stage {stage!r}")
        return tuple(
            lens.text for lens in self.lenses
            if stage in lens.stages and (not lens.conditional or lens.lens_id in active)
        )

    @property
    def conditional_lenses(self) -> tuple[Lens, ...]:
        """The lenses whose use depends on a run's evidence (#263)."""
        return tuple(lens for lens in self.lenses if lens.conditional)

    @property
    def selection_requirements(self) -> tuple[str, ...]:
        """The stream's own rules, then every lens routed to selection."""
        return (*self.stream.requirements, *self.for_stage("selection"))

    @property
    def provenance(self) -> dict:
        """What a run records: the exact client texts that governed it."""
        return {
            "stream": {"identity": self.stream.identity, "path": self.stream.path,
                       "digest": self.stream.digest},
            "lenses": [{"identity": lens.identity, "path": lens.path,
                        "digest": lens.digest, "stages": list(lens.stages),
                        "activation": lens.activation}
                       for lens in self.lenses],
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


def _require_keys(data: dict, keys: frozenset[str], path: Path) -> None:
    unknown = sorted(str(k) for k in data if k not in keys)
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
        if level == 3 and current == "Selection":
            sections[current].append(line)
            continue
        raise ClientContractError(
            f"{path}: `{line.strip()}` — only `###` group headings are allowed, "
            "and only under `## Selection`"
        )
    if tuple(found) != _STREAM_HEADINGS:
        raise ClientContractError(
            f"{path}: headings must be exactly [## Purpose, ## Selection] in that order; "
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
    )


def _conditional_sections(body: str, path: Path) -> tuple[str, str]:
    """A conditional lens's ``## Activation`` and ``## When active`` texts.

    Exactly those two ``##`` sections, in that order, both non-empty; one
    ``#`` title may precede them. Anything else fails the run rather than
    letting a condition or a behaviour go missing.
    """
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current: str | None = None
    for line in body.splitlines():
        match = _HEADING.match(line)
        if match and len(match.group(1)) == 2:
            name = match.group(2).strip()
            if name in sections:
                raise ClientContractError(f"{path}: `## {name}` appears twice")
            sections[name], current = [], name
            order.append(name)
            continue
        if match and len(match.group(1)) == 1 and current is None:
            continue                                   # a title before the sections
        if current is None:
            if line.strip():
                raise ClientContractError(
                    f"{path}: a conditional lens has no text before `## Activation`")
            continue
        sections[current].append(line)
    if tuple(order) != _CONDITIONAL_HEADINGS:
        raise ClientContractError(
            f"{path}: a conditional lens needs exactly `## Activation` then "
            f"`## When active`; found {', '.join(f'## {h}' for h in order) or 'none'}"
        )
    texts = tuple(re.sub(r"\n{3,}", "\n\n", "\n".join(sections[h])).strip()
                  for h in _CONDITIONAL_HEADINGS)
    for heading, text in zip(_CONDITIONAL_HEADINGS, texts):
        if not text:
            raise ClientContractError(f"{path}: `## {heading}` is empty")
    return texts[0], texts[1]


def load_lens(path: Path) -> Lens:
    raw, text = _read(path)
    data, body = _front_matter(text, path)
    body = _strip_comments(body, path)
    _require_keys({k: v for k, v in data.items() if k not in _LENS_OPTIONAL_KEYS},
                  _LENS_KEYS, path)
    activation = data.get("activation", "always")
    if activation not in ACTIVATIONS:
        raise ClientContractError(
            f"{path}: front-matter `activation` must be one of "
            f"{', '.join(sorted(ACTIVATIONS))}; got {activation!r}"
        )
    stages = _text_list(data, "stages", path)
    unknown = sorted(set(stages) - STAGES)
    if unknown:
        raise ClientContractError(
            f"{path}: unknown stage(s) {', '.join(unknown)} "
            f"(the Engine routes to: {', '.join(sorted(STAGES))})"
        )
    criteria = ""
    if activation == "conditional":
        if "selection" in stages:
            raise ClientContractError(
                f"{path}: a conditional lens cannot address `selection` — whether it "
                "applies is decided from research evidence, which selection precedes"
            )
        criteria, content = _conditional_sections(body, path)
    else:
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
        activation=activation,
        activation_criteria=criteria,
    )


# ── resolution ──────────────────────────────────────────────────────────────


def contracts_for_role(role_id: str, directory: Path | None = None) -> ClientContracts | None:
    """The client's contracts for the stream that governs ``role_id``, if any.

    Every document is read and validated, so a broken file fails the run even
    when it governs another stream. A role claimed by two stream contracts, or a
    lens id declared twice, is refused: one authority per rule. ``None`` means
    the client supplies nothing for this role, which is a valid state.
    """
    root = directory if directory is not None else client_dir()
    streams_dir, lenses_dir = root / "streams", root / "lenses"
    streams = [load_stream_contract(p) for p in sorted(streams_dir.glob("*.md"))] \
        if streams_dir.is_dir() else []
    lenses = [load_lens(p) for p in sorted(lenses_dir.glob("*.md"))] \
        if lenses_dir.is_dir() else []

    ids = [lens.lens_id for lens in lenses]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ClientContractError(f"lens id(s) declared twice: {', '.join(duplicated)}")
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
    )
