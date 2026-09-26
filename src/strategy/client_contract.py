"""The Client Contract's configured inputs: what this client enables, forbids and sounds like.

Issue #337, slice SL-2. Three inputs the stage contracts declare and nothing
loaded: S-07's **enabled destinations**, S-10's and S-12's **voice brief**, and
the **forbidden** phrasing S-10 resolves into ``E-14`` and V-T06 later enforces.

Producers, not contracts
------------------------
Every type below this module fills already exists and is already injected:
:class:`~src.editorial_core.executable_plan.ForbiddenItem` and
:class:`~src.editorial_core.executable_plan.AdaptationContract` for S-10,
:class:`~src.editorial_core.writer.VoiceBrief` for S-12, and
:class:`~src.editorial_core.destinations.Destination` for S-07. So this module
writes **producers** and changes no consumer: the chain the stage contracts
describe — human-editable configuration, a loader, a typed runtime value, the
stage — runs from here.

Three things that are not each other (AD-02 §3)
----------------------------------------------
**Enabled** is the client's answer: which destinations it wants published to.
**Capable** is the Engine's: whether a publisher, package and preflight exist,
declared in code. **Rollout scope** is the deployment's: which capable
destinations today's release publishes to (``release_scope.py``), temporary by
contract. S-07 resolves the three in that order and this module supplies only
the first — it never reads ``release_scope`` and never decides a mode.

Which tier a forbidden entry is
-------------------------------
Step 1 §4: ``forbidden`` holds "phrases and construction types in force",
"resolved from the contract (**tier 2**) and hard policy (**tier 1**)". So:

* **tier 2** is this client's own list, in its own directory, authored by whoever
  owns the client's editorial policy;
* **tier 1** is hard platform policy from the register — a ``K-DST-*`` record at
  tier 1, as S-07 reads them. No record forbids wording today, so the tier-1
  contribution is **empty**, and empty is the honest answer rather than a gap.

``config/machine_tells/shared.yaml`` is deliberately **not** a source here. Every
one of its entries is ``tier: directional`` — the legacy machine-tells
vocabulary, where *directional* means advisory — and a directional engine
heuristic is not hard platform policy. It also carries regex patterns and lede
moves, which are not phrases. It stays where it is, read by
``src/editorial/machine_tells.py`` for the pre-canonical path, so that path keeps
working while the Golden Engine is off.

What V-T06 gets, and what it does not get yet
---------------------------------------------
V-T06 is ``method: code+model``: the phrases are matched by code, the
construction types go to the model, "however it is worded". This module supplies
the typed configuration and the deterministic matching seam —
``ForbiddenItem.matches`` already matches phrases only, and says why. The
remaining half of V-T06, a finding routed to S-12 on ``L_edit``, needs S-13,
which does not exist yet (#307). Nothing here pretends otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Optional

from src.editorial_core.arp import KnowledgeTier
from src.editorial_core.destinations import Destination
from src.editorial_core.executable_plan import ForbiddenItem, ForbiddenKind
from src.editorial_core.writer import VoiceBrief
from src.knowledge.markdown import (
    Document,
    DocumentError,
    load_document,
    parse_document,
)
from src.strategy.client_contracts import (
    ClientContractError,
    SharedList,
    client_dir,
    load_shared_list,
)

#: The contract, relative to the client directory.
CONTRACT_FILE: Final[str] = "contract.md"

#: Where the shared lists live, relative to the client directory.
LISTS_DIRECTORY: Final[str] = "lists"

#: The section the enabled destinations are listed in.
DESTINATIONS_SECTION: Final[str] = "Enabled destinations"

#: Front matter, all required and nothing else accepted.
_FIELDS: Final[tuple[str, ...]] = (
    "contract_id",
    "version",
    "voice_ref",
    "forbidden_ref",
)

#: The tier a client's own list carries: Step 1 §4's "the contract (tier 2)",
#: which the register names for what it is — an approved client rule. Tier 1 is
#: ``HARD_PLATFORM_POLICY``, which is why the legacy engine list (every entry
#: ``tier: directional``) is not a source here.
CONTRACT_TIER: Final[KnowledgeTier] = KnowledgeTier.APPROVED_CLIENT_RULE


class ClientConfigurationError(ValueError):
    """The client's configuration cannot be read as a contract."""


@dataclass(frozen=True, slots=True)
class ClientContract:
    """What the client configured, typed, with the identity of what was read.

    ``enabled`` is the client's list and nothing else: no capability, no rollout
    scope. ``forbidden`` is resolved — every entry already carries the rule that
    imposed it and its tier, because V-P04's route is decided by the tier of the
    rule a plan broke and a finding that could not name the record would be
    routed by whoever read it.
    """

    contract_id: str
    version: str
    enabled: tuple[Destination, ...]
    forbidden: tuple[ForbiddenItem, ...]
    voice_ref: str
    path: str
    digest: str

    def __post_init__(self) -> None:
        if not self.contract_id.strip() or not self.version.strip():
            raise ClientConfigurationError(
                f"{self.path}: a contract that was read is named and versioned; "
                "a plan recording a contract without one cannot be resolved "
                "against the right version later"
            )
        if not self.enabled:
            raise ClientConfigurationError(
                f"{self.path}: enables no destination; a client with nothing "
                "enabled has asked for no publication at all, which is a "
                "configuration nobody meant to write rather than a run with "
                "nothing to do"
            )
        named = [item.value for item in self.enabled]
        repeated = sorted({name for name in named if named.count(name) > 1})
        if repeated:
            raise ClientConfigurationError(
                f"{self.path}: enables " + ", ".join(repeated) + " twice; the "
                "list says which destinations are on, and saying one twice says "
                "nothing more than saying it once"
            )

    def enables(self, destination: Destination) -> bool:
        """Did the client switch this destination on?"""

        return destination in self.enabled

    def phrases(self) -> tuple[ForbiddenItem, ...]:
        """The forbidden entries code may match (V-T06's code half)."""

        return tuple(
            item for item in self.forbidden if item.kind is ForbiddenKind.PHRASE
        )

    def constructions(self) -> tuple[ForbiddenItem, ...]:
        """The forbidden entries only the model can judge (V-T06's model half)."""

        return tuple(
            item
            for item in self.forbidden
            if item.kind is ForbiddenKind.CONSTRUCTION
        )


def parse_client_contract(
    document: Document, *, forbidden: tuple[ForbiddenItem, ...]
) -> ClientContract:
    """Read one contract document. Raises :class:`ClientConfigurationError`.

    ``forbidden`` arrives resolved because the entries live in a list the
    contract only names: a parser that went and read another file would make the
    contract's own digest cover something it does not contain.
    """

    path = document.path
    missing = [name for name in _FIELDS if document.field(name) is None]
    if missing:
        raise ClientConfigurationError(
            f"{path}: front matter is missing {', '.join(missing)}"
        )
    unknown = sorted(set(document.field_names) - set(_FIELDS))
    if unknown:
        raise ClientConfigurationError(
            f"{path}: front matter has no field {', '.join(unknown)}; a client "
            f"contract declares {', '.join(_FIELDS)}"
        )

    body = document.section(DESTINATIONS_SECTION)
    if body is None:
        raise ClientConfigurationError(
            f"{path}: no `## {DESTINATIONS_SECTION}` section; that is where the "
            "client says which destinations it has switched on"
        )

    enabled: list[Destination] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--") or stripped.startswith("-->"):
            continue
        if not stripped.startswith("- "):
            raise ClientConfigurationError(
                f"{path}: every enabled destination is a bullet (`- `); got "
                f"{stripped[:60]!r}"
            )
        name = stripped[2:].strip().lower()
        try:
            enabled.append(Destination(name))
        except ValueError:
            raise ClientConfigurationError(
                f"{path}: enables {name!r}, which is not a destination this "
                "engine has; the six surfaces are "
                + ", ".join(item.value for item in Destination)
            ) from None

    return ClientContract(
        contract_id=document.field("contract_id") or "",
        version=document.field("version") or "",
        enabled=tuple(enabled),
        forbidden=forbidden,
        voice_ref=document.field("voice_ref") or "",
        path=path,
        digest=document.digest,
    )


def forbidden_from(shared: SharedList) -> tuple[ForbiddenItem, ...]:
    """The client's list as ``E-14``'s ``forbidden`` entries, at tier 2.

    Every entry of a shared list is a phrase: the list's own note is that "the
    Engine matches these strings and never interprets them". A construction type
    is not a string and would have to say so, so nothing here invents one.

    ``rule_ref`` names the list and its version rather than the entry, because
    that is the record a finding cites: the entry is what was broken, the list is
    what forbade it.
    """

    rule_ref = f"{shared.list_id} v{shared.version}"
    return tuple(
        ForbiddenItem(
            kind=ForbiddenKind.PHRASE,
            value=entry,
            rule_ref=rule_ref,
            tier=CONTRACT_TIER,
        )
        for entry in shared.entries
    )


def load_client_contract(
    path: Path, *, lists: Optional[Path] = None
) -> ClientContract:
    """Read the contract and the list it names. Raises :class:`ClientConfigurationError`.

    The list is read here rather than in :func:`parse_client_contract` because
    only a path knows where the client's ``lists/`` directory is.
    """

    try:
        document = load_document(path)
    except DocumentError as exc:
        raise ClientConfigurationError(str(exc)) from exc

    named = document.field("forbidden_ref")
    if named is None or not named.strip():
        raise ClientConfigurationError(
            f"{path}: names no forbidden list; a contract that forbids nothing "
            "says so with an empty list rather than by leaving the field out"
        )
    directory = lists if lists is not None else path.parent / LISTS_DIRECTORY
    shared = _shared_list(directory, named.strip(), contract=str(path))
    return parse_client_contract(document, forbidden=forbidden_from(shared))


def client_contract(*, directory: Optional[Path] = None) -> ClientContract:
    """The active client's contract.

    A **hard** input, unlike the Reference Library: a run cannot decide which
    destinations to write for by guessing. A missing contract raises rather than
    degrading, because there is no honest default — see #337 and the standing
    rule that a layer refuses to choose a value the architecture leaves to the
    client.
    """

    root = directory if directory is not None else client_dir()
    path = root / CONTRACT_FILE
    if not path.is_file():
        raise ClientConfigurationError(
            f"{path}: this client has no contract; the destinations a run writes "
            "for, the voice it writes in and the phrasing it must avoid are the "
            "client's to state, and none of them has a default the engine may "
            "pick"
        )
    return load_client_contract(path)


def load_voice_brief(path: Path) -> VoiceBrief:
    """The voice document, typed, at the version it declares.

    The document stays human-editable prose and is referenced rather than
    embedded (#337): what is typed is its identity and its text, so that
    ``E-14.voice_brief_ref`` names a version and S-12 can refuse a brief the plan
    was not approved against.
    """

    if not path.is_file():
        raise ClientConfigurationError(
            f"{path}: the contract references this voice document and it is not "
            "there; a reference to a document nobody can open is not a voice"
        )
    try:
        document = parse_document(path.read_text(encoding="utf-8"), str(path))
    except DocumentError as exc:
        raise ClientConfigurationError(str(exc)) from exc

    voice_id = document.field("voice_id")
    version = document.field("version")
    if not voice_id or not voice_id.strip() or not version or not version.strip():
        raise ClientConfigurationError(
            f"{path}: a voice document declares `voice_id` and `version`; "
            "`E-14.voice_brief_ref` is a reference to a *version*, and prose "
            "with no version cannot be referenced at all"
        )
    body = document.text.strip()
    if not body:
        raise ClientConfigurationError(f"{path}: the voice document says nothing")
    return VoiceBrief(brief_ref=f"{voice_id.strip()} v{version.strip()}", text=body)


def voice_brief(
    contract: ClientContract, *, root: Optional[Path] = None
) -> VoiceBrief:
    """The voice the contract references, resolved from the repository root."""

    base = root if root is not None else Path.cwd()
    return load_voice_brief(base / contract.voice_ref)


def _shared_list(directory: Path, list_id: str, *, contract: str) -> SharedList:
    """The shared list with this ``list_id``, from the client's ``lists/``."""

    if not directory.is_dir():
        raise ClientConfigurationError(
            f"{contract}: names the forbidden list {list_id!r} and there is no "
            f"{directory} to find it in"
        )
    found: list[SharedList] = []
    for candidate in sorted(directory.glob("*.md")):
        try:
            shared = load_shared_list(candidate)
        except ClientContractError:
            continue
        if shared.list_id == list_id:
            found.append(shared)
    if not found:
        raise ClientConfigurationError(
            f"{contract}: names the forbidden list {list_id!r}, and no list in "
            f"{directory} declares that `list_id`"
        )
    if len(found) > 1:
        raise ClientConfigurationError(
            f"{contract}: {list_id!r} is declared by "
            + ", ".join(item.path for item in found)
            + "; one `list_id` names one list"
        )
    return found[0]
