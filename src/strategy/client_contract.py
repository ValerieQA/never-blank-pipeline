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
from enum import Enum
from pathlib import Path
from typing import Final, Optional

from src.editorial_core.arp import KnowledgeTier
from src.editorial_core.destinations import (
    ContractDestination,
    ContractDestinations,
    Destination,
)
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
    strip_comments,
)

#: The contract, relative to the client directory.
CONTRACT_FILE: Final[str] = "contract.md"

#: Where the shared lists live, relative to the client directory.
LISTS_DIRECTORY: Final[str] = "lists"

#: The section the enabled destinations are listed in.
DESTINATIONS_SECTION: Final[str] = "Enabled destinations"

#: The section the client declares its evidence policy in. Optional: a contract
#: without it declares no evidence requirement, which is a choice and not an
#: omission — the same posture as a stream that declares no client ladder.
EVIDENCE_POLICY_SECTION: Final[str] = "Evidence policy"

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


class EvidenceRequirement(str, Enum):
    """Evidence requirements the Engine can execute, by their contract wording.

    The canonical map gives the Client Contract an "evidence policy" beside its
    ceiling, and this is the Engine half of it: a closed vocabulary a client
    declares from, matched literally exactly as ``Enabled destinations`` matches
    :class:`~src.editorial_core.destinations.Destination`. The Engine matches;
    it never interprets, and a wording it does not carry is refused rather than
    passed over.

    What a member means is a **mechanism**, never a taxonomy of claims:

    ``PRIMARY_AUTHORITY_WHERE_DEPENDENT``
        For each claim, ask whether it *depends* on a responsible primary
        authority under the conditions this client wrote beneath the
        declaration — and where it does and none was established, the claim may
        not read as verified.

        The predicate is the client's, and that is the whole point of the
        second review (2026-10-05): "model can name somebody who could confirm
        this" is **not** "this is one of the claim classes for which policy
        requires a primary source". So the Engine asks the client's question
        per claim and carries the client's own words to where it is answered.
        It does not enumerate claim classes, here or anywhere in ``src/``.

    Adding a member is an Engine capability decision, like adding a lens stage.
    """

    PRIMARY_AUTHORITY_WHERE_DEPENDENT = (
        "primary authority where the claim depends on one"
    )


@dataclass(frozen=True, slots=True)
class DeclaredRequirement:
    """One declared requirement and the client's conditions for it.

    ``conditions`` are the indented bullets written beneath the declaration:
    client prose, kept verbatim and **never parsed**. They travel to the stage
    that answers the requirement's question, exactly as a lens body travels to
    the stages its front matter names. The Engine carries them; what they mean
    is the client's.

    A declaration with no conditions is **refused at load** (owner decision
    2026-10-05): its predicate would be empty, every claim would be answered
    "no", and the contract would read as stating a policy while doing nothing.
    That is a configuration error, not a policy — so this type never holds one,
    and the inert-rule state has no way into a run.
    """

    requirement: EvidenceRequirement
    conditions: tuple[str, ...] = ()


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
    #: What the client declared under ``## Evidence policy``, in document order,
    #: each with the client's own conditions beneath it. Empty is a contract
    #: that requires nothing of its evidence beyond what the Engine requires of
    #: everyone's.
    evidence: tuple[DeclaredRequirement, ...] = ()

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

    @property
    def requires_primary_authority(self) -> bool:
        """Did this client declare the primary-authority requirement at all?

        A switch on the *mechanism*, never a verdict about a claim. ``False``
        when the client declared nothing, which is why the Engine caps no claim
        for a client that never asked it to: a requirement nobody stated is not
        a requirement the Engine may supply on the client's behalf.

        Whether any particular claim owes an authority is a separate question,
        answered per claim against :meth:`authority_conditions`. Conflating the
        two is the defect the second review of #387 named: a run-wide boolean
        made every claim with an identifiable party owe one.
        """

        return any(
            item.requirement is EvidenceRequirement.PRIMARY_AUTHORITY_WHERE_DEPENDENT
            for item in self.evidence
        )

    @property
    def authority_conditions(self) -> tuple[str, ...]:
        """The client's own conditions for when a claim depends on an authority.

        Verbatim client prose, carried to the stage that applies it and never
        interpreted here. Empty when the client declared the requirement and
        wrote no conditions, or declared nothing at all — and the Engine does
        not invent a predicate for either case.
        """

        for item in self.evidence:
            if (
                item.requirement
                is EvidenceRequirement.PRIMARY_AUTHORITY_WHERE_DEPENDENT
            ):
                return item.conditions
        return ()

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
        evidence=_evidence_policy(document, path=path),
    )


def _policy_bullets(body: str, *, path: str) -> tuple[tuple[bool, str], ...]:
    """The section's bullets, each as ``(indented, text)``, wrapped lines joined.

    A condition is a sentence or two of client prose and prose wraps, so a line
    that is not itself a bullet continues the bullet above it — the one
    markdown convention this has to honour, because the alternative is a client
    reformatting its own policy and changing what the run applies.

    A line before any bullet is refused rather than attached to nothing.
    """

    bullets: list[tuple[bool, list[str]]] = []
    for line in body.splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            indented = line[: len(line) - len(line.lstrip())] != ""
            bullets.append((indented, [stripped[2:].strip()]))
            continue
        if not bullets:
            raise ClientConfigurationError(
                f"{path}: the evidence policy opens with {stripped[:60]!r}, "
                "which is not a bullet (`- `); every requirement and every "
                "condition is one"
            )
        bullets[-1][1].append(stripped)
    return tuple(
        (indented, " ".join(parts)) for indented, parts in bullets
    )


def _evidence_policy(
    document: Document, *, path: str
) -> tuple[DeclaredRequirement, ...]:
    """What the client declared under ``## Evidence policy``, matched literally.

    Two levels, and the split is the boundary:

    * a **top-level** bullet names one requirement the Engine can execute, and
      is matched against :class:`EvidenceRequirement` — a wording the Engine
      does not carry is refused with the vocabulary named, because a
      requirement written down and silently dropped is the one failure mode a
      client cannot see;
    * an **indented** bullet beneath it is that requirement's condition, in the
      client's own words. Never matched, never parsed, never normalised: it is
      carried to the stage that applies it, as a lens body is.

    Absent section → nothing declared, which ``requires_primary_authority``
    reads as "this client asks for no authority" rather than as a default the
    Engine chose.
    """

    body = document.section(EVIDENCE_POLICY_SECTION)
    if body is None:
        return ()
    try:
        body = strip_comments(body, Path(path))
    except ClientContractError as exc:
        raise ClientConfigurationError(str(exc)) from exc

    bullets = _policy_bullets(body, path=path)
    declared: list[EvidenceRequirement] = []
    conditions: dict[EvidenceRequirement, list[str]] = {}
    for indented, text in bullets:
        if indented:
            if not declared:
                raise ClientConfigurationError(
                    f"{path}: the evidence policy opens with the indented "
                    f"condition {text[:60]!r}; a condition states when a "
                    "requirement applies, so it follows the requirement it is "
                    "about"
                )
            conditions[declared[-1]].append(text)
            continue
        wording = text.lower()
        try:
            requirement = EvidenceRequirement(wording)
        except ValueError:
            raise ClientConfigurationError(
                f"{path}: declares the evidence requirement {wording!r}, which "
                "is not one this engine can execute; it carries "
                + ", ".join(repr(item.value) for item in EvidenceRequirement)
                + ". A condition for when a requirement applies is an indented "
                "bullet beneath it, not a requirement of its own"
            ) from None
        if requirement in declared:
            raise ClientConfigurationError(
                f"{path}: declares {wording!r} twice; saying a requirement "
                "twice says nothing more than saying it once"
            )
        declared.append(requirement)
        conditions[requirement] = []
    for requirement in declared:
        if not conditions[requirement]:
            raise ClientConfigurationError(
                f"{path}: declares {requirement.value!r} and states no "
                "condition for when it applies. A requirement whose predicate "
                "is empty is answered 'no' for every claim, so it would read "
                "as declared policy and do nothing — a configuration error, "
                "not a policy (owner decision 2026-10-05). State the "
                "conditions as indented bullets beneath it, or remove the "
                f"`## {EVIDENCE_POLICY_SECTION}` section to require nothing"
            )
    return tuple(
        DeclaredRequirement(
            requirement=requirement, conditions=tuple(conditions[requirement])
        )
        for requirement in declared
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


def contract_destinations(contract: ClientContract) -> ContractDestinations:
    """The contract as S-07's declared-destination input (§1, required).

    **The client contract is authoritative over the six canonical destinations**,
    so this produces a row for every one of them and never leaves one out. That
    is the whole care this function takes, because S-07 keeps three states apart
    and two of them are easy to confuse:

    * **declared and enabled** — the client switched it on: ``enabled=True``.
    * **declared and disabled** — the client switched it off: ``enabled=False``,
      which S-07 excludes as ``CONTRACT_DISABLED``, citing this contract's rule.
    * **undeclared** — the contract never mentioned it, recorded by S-07 as
      :attr:`DestinationDecisionSet.undeclared`.

    ``ContractDestinations``' own docstring is why the difference matters: the
    destinations it does not declare "are not excluded: they are unknown to the
    contract … so a reader can tell a destination the client turned off from one
    it never mentioned". A destination missing from the contract's *enabled* list
    is the first of those, not the second — the client did mention it, by writing
    a contract that covers its surfaces — so omitting the row would report a
    deliberate choice as an oversight. This producer therefore never yields
    ``undeclared``; a contract that covers all six has nothing unknown in it.

    ``rule_id`` names the contract's row **for that destination**, not the
    contract as a whole: §1 Post asks for "exactly one decision, eligible or
    excluded, each with a rule and a tier", and ``ContractDestinations`` refuses
    two rows sharing an ID because "a name two rows answer to names neither". The
    version travels with it, so a decision recorded today still names the contract
    version that made it.

    Nothing here reads capability or the rollout scope. Whether an enabled
    destination *publishes* or only generates is S-07's own resolution from its
    other two inputs, and today's Wix + LinkedIn behaviour comes from there
    rather than from this file.
    """

    return ContractDestinations(
        rows=tuple(
            ContractDestination(
                destination=destination,
                rule_id=(
                    f"{contract.contract_id}-destination-{destination.value} "
                    f"v{contract.version}"
                ),
                enabled=contract.enables(destination),
            )
            for destination in Destination
        )
    )


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
