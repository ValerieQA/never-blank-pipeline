"""S-10's contract material in production: voice, forbidden, fixed slots, hashtags.

Issue #368, slice SL-6.47. ``AdaptationContract`` is read at eleven places across
S-10 and S-11 and was constructed **nowhere** in ``src/`` or ``scripts/``. This is
the producer, and it composes the four fields from four authorities without
becoming a fifth one:

======================= ==================================================
``voice_brief_ref``     the voice document the contract references (#337)
``forbidden``           the client's shared list, resolved at tier 2 (#337)
``fixed_slots``         the client's own ``K-NB-*`` rule records, loaded
``hashtags``            the static vocabulary the contract declares
======================= ==================================================

The ending mode comes from ``K-NB-01`` and not from here
--------------------------------------------------------
Owner decision, 2026-09-30: ``K-NB-01`` is the client authority for the fixed
ending mode. The record says so machine-readably, in the one fixed clause at the
end of its own ``## Influences`` entry — the grammar #363 established for
``K-DST`` records, reused rather than reinvented::

    - S-10 · `E-14.fixed_slots` — … [fixes: ending_mode = kicker]

So the value is the record's. Nothing in this module names ``ending_mode`` or
``kicker``: editing the record changes the produced :class:`FixedSlot`, and a
literal here would make the record decorative. The clause is read exactly or not
at all — an unreadable spec, two clauses on one entry, or a clause on an entry
that names no ``E-14`` field are each a refusal, because a producer that guessed
would hand V-P04 a constraint nobody wrote.

Hashtags: the vocabulary is the client's, the policy is the destination's
------------------------------------------------------------------------
``AdaptationContract.hashtags`` is "the client's tag list. The **policy** is the
destination's". This module supplies only the list, and only the part of it that
is a *declaration*: ``#NeverBlank`` and ``#CustomerTrust``, read from the
contract. ``#CompoundPresence`` is conditional on the accepted article naming
Compound Presence and the industry tag is derived from the signal; both are
computations, they stay where they are computed, and a computed tag declared here
would be a claim the client never made. ``DestinationRules`` and the hashtag
policy #363 owns are untouched, and **nothing here imports**
``src/publishing/hashtags.py`` — that module is a *consumer* of the declared
vocabulary, which is the direction that leaves one authority for it.

Sources: `docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md` §3 (S-10,
S-11); `docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md` §4 (E-14);
`docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md` §2.2, §2.3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Optional

from src.editorial_core.arp import KnowledgeTier
from src.editorial_core.executable_plan import (
    AdaptationContract,
    FixedSlot,
    PlanError,
)
from src.knowledge.client_rules import ClientRuleSet, client_rules
from src.knowledge.loader import LoadedRecord
from src.knowledge.markdown import Document, DocumentError, load_document
from src.knowledge.records import Influence
from src.strategy.client_contract import (
    CONTRACT_FILE,
    ClientConfigurationError,
    client_contract,
    voice_brief,
)
from src.strategy.client_contracts import client_dir
from src.strategy.strategy_contract import (
    StrategyContractError,
    without_comments,
)

#: The stage whose inputs this producer builds.
STAGE: Final[str] = "S-10"

#: The ``E-14`` field a fixed slot belongs to, spelled as ``knowledge/vocab/
#: fields.md`` spells it.
FIXED_SLOTS_FIELD: Final[str] = "E-14.fixed_slots"

#: The tier a record must carry to fix a slot. A fixed slot is a constraint
#: V-P04 enforces, and Step 1 §4 makes it "the contract (tier 2)". A tier-3
#: candidate declaring one is refused rather than dropped: approval is what puts
#: a client rule in force (§2.3), and a candidate that silently fixed nothing
#: would leave the plan unconstrained with no sign that a rule had been read.
FIXING_TIER: Final[KnowledgeTier] = KnowledgeTier.APPROVED_CLIENT_RULE

#: The section declaring the static, client-owned hashtag words.
HASHTAG_SECTION: Final[str] = "Hashtag vocabulary"

#: The one machine-readable clause of an ``## Influences`` entry (#363).
_FIXES = re.compile(r"\[fixes:(?P<spec>[^\]]*)\]")

#: ``<slot> = <value>``. A slot name is an entity field name, and the value is
#: what the plan carries; neither may be empty, and a spec with no ``=`` states
#: a value for no slot.
_SLOT = re.compile(r"^(?P<name>[a-z][a-z0-9_]*)\s*=\s*(?P<value>[^=]+)$")


class AdaptationContractError(ValueError):
    """The client's configuration cannot be read as S-10's contract material."""


@dataclass(frozen=True, slots=True)
class DeclaredSlot:
    """One slot one client rule fixes, and the record that fixed it."""

    slot: FixedSlot
    record_id: str
    source: str


def adaptation_contract(
    *,
    directory: Optional[Path] = None,
    register: Optional[Path] = None,
    root: Optional[Path] = None,
    today: Optional[date] = None,
) -> AdaptationContract:
    """The contract material S-10 adapts to and S-11 checks a plan against.

    A **hard** input. Every path out of here is either a complete
    :class:`AdaptationContract` or a refusal: there is no partially composed
    contract and no field standing in for one that could not be read, because a
    plan adapted to a contract missing a rule is a plan nobody can check against
    the rule.

    The refusal is an :class:`AdaptationContractError`, or the
    :class:`~src.knowledge.client_rules.ClientRulesError` the registry raised.
    That one is deliberately not rewrapped: a register a run may not start on is
    not a contract that could not be composed, and flattening the two would hide
    which of them happened.
    """

    client = directory if directory is not None else client_dir()
    try:
        contract = client_contract(directory=client)
        reference = voice_brief(contract, root=root).brief_ref
    except ClientConfigurationError as exc:
        raise AdaptationContractError(str(exc)) from exc

    slots = fixed_slots(
        client_rules(directory=client, register=register, today=today)
    )
    try:
        return AdaptationContract(
            voice_brief_ref=reference,
            # #337's list, with the rule and the tier every entry already
            # carries: V-P04's route is decided by the tier of the rule a plan
            # broke, and anything done to them here would be a second opinion
            # about a resolution #337 owns.
            forbidden=contract.forbidden,
            fixed_slots=tuple(item.slot for item in slots),
            hashtags=client_hashtags(directory=client),
        )
    except PlanError as exc:
        raise AdaptationContractError(f"{client / CONTRACT_FILE}: {exc}") from exc


# ----------------------------------------------------------------------
# The fixed slots, from the client's own rule records
# ----------------------------------------------------------------------


def fixed_slots(rules: ClientRuleSet) -> tuple[DeclaredSlot, ...]:
    """Every slot the client's loaded rules fix, read exactly from the records."""

    declared: dict[str, DeclaredSlot] = {}
    for loaded in rules.records:
        for item in _declared_by(loaded):
            held = declared.setdefault(item.slot.name, item)
            if held is not item:
                raise AdaptationContractError(
                    f"{held.record_id} ({held.source}) and {item.record_id} "
                    f"({item.source}) both fix `{item.slot.name}`; two records "
                    "fixing one slot fix neither, and choosing between them is "
                    "the keeper's decision rather than a tie-break this producer "
                    "invents"
                )
    return tuple(declared[name] for name in sorted(declared))


def _declared_by(loaded: LoadedRecord) -> tuple[DeclaredSlot, ...]:
    """The slots one record's influence entries fix.

    Every entry is scanned, not only this stage's. An entry that fixes a value at
    a stage this producer does not build is **refused** rather than skipped: a
    clause nobody reads is a rule the keeper believes is in force, and it would be
    invisible from both ends.
    """

    found: list[DeclaredSlot] = []
    for influence in loaded.record.influences:
        clauses = _FIXES.findall(influence.text)
        if not clauses:
            # An entry that shapes a field without stating a value fixes
            # nothing, and that is a normal record: `K-NB-01` also shapes
            # `E-14.segments` without fixing it.
            continue
        if len(clauses) > 1:
            raise AdaptationContractError(
                f"{loaded.record.path}: the `## Influences` entry "
                f"{influence.text[:50]!r} carries two `[fixes: …]` clauses; one "
                "entry fixes one value"
            )
        if influence.stage != STAGE:
            raise AdaptationContractError(
                f"{loaded.record.path}: {loaded.identity} fixes a value on its "
                f"{influence.stage} entry, and this producer builds {STAGE}'s "
                "contract material. A clause no producer reads is a rule the "
                "keeper believes is in force, so it is refused rather than left "
                "unread"
            )
        found.append(_slot(loaded, influence, clauses[0]))
    return tuple(found)


def _slot(
    loaded: LoadedRecord, influence: Influence, spec: str
) -> DeclaredSlot:
    """One ``[fixes: <slot> = <value>]`` clause, as the slot it states.

    Neither the slot nor the value is named anywhere below: both are the
    record's, and a literal here would make the record decorative.
    """

    if FIXED_SLOTS_FIELD not in influence.fields:
        raise AdaptationContractError(
            f"{loaded.record.path}: the `## Influences` entry "
            f"{influence.text[:50]!r} fixes a value and does not name "
            f"`{FIXED_SLOTS_FIELD}`; a slot this producer carries belongs to that "
            "field, and a clause on any other field is a value S-10 has nowhere "
            "to put"
        )
    if loaded.tier is not FIXING_TIER:
        raise AdaptationContractError(
            f"{loaded.record.path}: {loaded.identity} is tier "
            f"{loaded.tier.value} and fixes `{FIXED_SLOTS_FIELD}`. A fixed slot is "
            f"a constraint V-P04 enforces, which Step 1 §4 puts at tier "
            f"{FIXING_TIER.value}; approval is what moves a client rule there "
            "(§2.3), and this producer does not apply a rule the client has not "
            "approved"
        )
    match = _SLOT.match(" ".join(spec.split()))
    if match is None:
        raise AdaptationContractError(
            f"{loaded.record.path}: {loaded.identity} fixes a slot as "
            f"{spec.strip()!r}; the clause is written `[fixes: <slot> = <value>]` "
            "— one slot name, one value, and both are the rule rather than a hint "
            "this producer completes"
        )
    try:
        slot = FixedSlot(
            name=match.group("name").strip(),
            value=match.group("value").strip(),
            rule_ref=loaded.identity,
        )
    except PlanError as exc:
        raise AdaptationContractError(f"{loaded.record.path}: {exc}") from exc
    return DeclaredSlot(
        slot=slot, record_id=loaded.identity, source=loaded.record.path
    )


# ----------------------------------------------------------------------
# The hashtag vocabulary, from the client's contract
# ----------------------------------------------------------------------


def client_hashtags(*, directory: Optional[Path] = None) -> tuple[str, ...]:
    """The static, client-owned hashtag words, in the order they are declared.

    The **vocabulary** and nothing else. Whether a surface carries tags at all is
    the destination's decision and stays with the destination's own rules (#363);
    a conditional or derived tag is a computation and is not declared here. A
    missing declaration raises: a client that publishes tags has words it wants
    used, and an engine that supplied them would be writing the client's voice.
    """

    root = directory if directory is not None else client_dir()
    path = root / CONTRACT_FILE
    if not path.is_file():
        raise AdaptationContractError(
            f"{path}: this client has no contract, and the words its posts are "
            "tagged with are the client's own"
        )
    try:
        document = load_document(path)
    except DocumentError as exc:
        raise AdaptationContractError(str(exc)) from exc
    return parse_hashtags(document)


def parse_hashtags(document: Document) -> tuple[str, ...]:
    """The ``## Hashtag vocabulary`` section, read exactly."""

    body = document.section(HASHTAG_SECTION)
    if body is None:
        raise AdaptationContractError(
            f"{document.path}: no `## {HASHTAG_SECTION}` section; that is where "
            "the client states the static tags its posts carry, and the engine has "
            "no word of its own to put there"
        )
    try:
        stated = without_comments(
            body, path=document.path, section=HASHTAG_SECTION
        )
    except StrategyContractError as exc:
        raise AdaptationContractError(str(exc)) from exc

    tags: list[str] = []
    for line in stated.splitlines():
        entry = line.strip()
        if not entry:
            continue
        if not entry.startswith("- "):
            raise AdaptationContractError(
                f"{document.path}: every declared hashtag is a bullet (`- `); got "
                f"{entry[:60]!r}"
            )
        tag = entry[2:].strip()
        if not tag.startswith("#") or len(tag) < 2 or len(tag.split()) != 1:
            raise AdaptationContractError(
                f"{document.path}: `## {HASHTAG_SECTION}` declares {tag!r}, which "
                "is not a hashtag; one word, beginning with `#`, with at least one "
                "character after it"
            )
        if tag in tags:
            raise AdaptationContractError(
                f"{document.path}: `## {HASHTAG_SECTION}` declares {tag} twice; "
                "saying a tag twice says nothing more than saying it once"
            )
        tags.append(tag)
    if not tags:
        raise AdaptationContractError(
            f"{document.path}: `## {HASHTAG_SECTION}` declares no tag. The section "
            "is the client's vocabulary, and a client that wanted none would have "
            "no hashtag policy to declare either — an empty list here is a section "
            "somebody emptied rather than a decision"
        )
    return tuple(tags)
