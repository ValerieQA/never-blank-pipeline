"""The destination's rules in production: what fixes a surface's three values.

Issue #363, slice SL-6.45. ``DestinationRules`` is required at thirteen call
sites across S-10 (``executable_plan.py``) and S-11 (``plan_check.py``), it
mandates three values — ``format_rule``, ``length_rule``, ``hashtag_rule`` — and
until now nothing outside the tests built one. This is the producer.

It transcribes; it does not choose
----------------------------------
Every ``K-DST-*`` record already names its own target machine-readably:
``## Applies when`` supplies the destination binding, and ``## Influences`` names
the exact ``E-14`` field the record fixes. What ``## Influences`` did **not**
carry was the value itself, and reading one out of the entry's prose would be
guessing — "the text status as the default form" and "text with an image where
one exists" name no format term at all. So a record that fixes a value says so
in one fixed clause at the end of its own influence entry::

    - S-10 · `E-14.length_target` — the 250–400 word range. [fixes: 250–400 words]

The clause is read exactly or not at all: an unknown format name, a range with
one end, a unit the engine does not count, two clauses on one entry, or a clause
on an entry that names no ``E-14`` field are each a refusal. Nothing here
interpolates, and nothing here falls back — a destination whose value no
authority supplies is a construction failure, which is what the three mandatory
fields already meant.

Two authorities, one existing ladder
------------------------------------
Twelve of Never Blank's eighteen values are tier-2 client policy and six are
platform knowledge, so a value arrives from either side of the split: an
admissible :class:`~src.editorial_core.executable_plan.PlatformRule` at tier 1 or
4, or a :class:`~src.editorial_core.executable_plan.ClientRule` at tier 2. Which
of two competing rules governs a field is decided by the ladder that already
exists — ``arp.tier_rank()``, strongest first. No new ordering is written here,
and nothing inside a tier separates two rules:

1. a tier-1 hard platform policy beats a tier-2 client rule;
2. a tier-2 client rule beats a tier-4 platform ranking;
3. equal authority on one field **refuses**, loudly — two equal authorities
   fixing one field fix neither;
4. the loser is recorded in ``other_rules``, never merged and never dropped;
5. neither source supplying a required value is a construction failure.

The refusal lives here and not in ``DestinationRules.__post_init__`` because
precedence is field-aware and only this module still knows which field a rule
competed for: once a losing rule sits in ``other_rules`` that provenance is gone.

What this module deliberately does not read
-------------------------------------------
``platform_composer._WORD_RANGE`` and ``src.publishing.hashtags._COUNT_RANGE``
are legacy private constants. They are **migration provenance** for decisions
already taken and recorded in the client contract, never a runtime dependency,
and neither is imported here. LinkedIn in particular never sources its length
from ``_WORD_RANGE``'s 120–220: ``K-DST-LI-01`` states 250–400 and is the
authority, which is why the contract declares no LinkedIn length rule at all.

A record whose ``## Applies when`` is not exactly one ``destination is …`` term
is **unbound** and reaches no destination through this producer. That is the
whole of the ``K-DST-META-*`` question: a destination is never inferred from a
record's prefix, and "all Meta destinations" is not a binding. Where the map
does not determine a binding, the record is transcribed unbound and raised as a
keeper question rather than guessed at.

``K-DST-TH-02`` is absent from the register on the map's own authority: "Live
author replies give +42%. **Unavailable in an autonomous system** — this is
knowledge for the Client Contract, not for the production run." Transcribing it
as an engine record would import knowledge the map routes elsewhere. The
exclusion is recorded in ``knowledge/README.md`` with that reason so a later
reader finds a decision rather than an oversight.

Sources: ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §8.6;
``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §3 (S-10, S-11);
``docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md`` §4, §5.1, §9.3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Mapping, Optional, Union

from src.editorial_core.arp import KnowledgeTier, tier_rank
from src.editorial_core.destinations import Destination
from src.editorial_core.executable_plan import (
    ClientRule,
    DestinationRules,
    FixingRule,
    HashtagPolicy,
    LengthTarget,
    LengthUnit,
    PlanError,
    PlanFormat,
    PlatformRule,
)
from src.knowledge.grammar import DESTINATION, Atom
from src.knowledge.loader import LoadedRecord, LoaderError, load_register
from src.knowledge.markdown import DocumentError, load_document, parse_table
from src.knowledge.records import Influence
from src.strategy.client_contract import CONTRACT_FILE
from src.strategy.client_contracts import client_dir

#: The register, relative to the repository root, as the CI caller spells it.
REGISTER_DIR: Final[Path] = Path("knowledge")

#: The id prefix of a destination record. The family directory is `dst/`, and
#: the validator already refuses a record filed outside its own family.
DESTINATION_PREFIX: Final[str] = "K-DST-"

#: Where a destination record lives, for the message that says where to look.
DESTINATION_RECORDS: Final[str] = "records/dst"

#: The stage whose inputs this producer builds.
STAGE: Final[str] = "S-10"

#: The three ``E-14`` fields ``DestinationRules`` mandates, spelled as
#: ``knowledge/vocab/fields.md`` spells them.
FORMAT_FIELD: Final[str] = "E-14.format"
LENGTH_FIELD: Final[str] = "E-14.length_target"
HASHTAG_FIELD: Final[str] = "E-14.hashtags"
FIXED_FIELDS: Final[tuple[str, ...]] = (FORMAT_FIELD, LENGTH_FIELD, HASHTAG_FIELD)

#: The tiers ``PlatformRule`` admits (§3: "K-DST records at tiers 1 and 4"). A
#: record at any other tier is not a rule this producer applies: it still
#: reaches the stage through the register's own selection, carrying whatever
#: authority its tier gives it, which is exactly what tier 3 means.
PLATFORM_TIERS: Final[tuple[KnowledgeTier, ...]] = (
    KnowledgeTier.HARD_PLATFORM_POLICY,
    KnowledgeTier.PLATFORM_RANKING,
)

#: The contract section holding the client's own destination rules.
CONTRACT_SECTION: Final[str] = "Destination rules"

_CONTRACT_COLUMNS: Final[tuple[str, ...]] = (
    "rule_id", "destination", "fixes", "value", "statement",
)

#: The one machine-readable clause of an ``## Influences`` entry. Everything
#: else on the line is prose for a person, exactly as §2 says.
_FIXES = re.compile(r"\[fixes:(?P<spec>[^\]]*)\]")

#: ``<minimum>–<maximum> <unit>``. An en dash is what a person writes and a
#: hyphen is what a person types; both spell one range, and a range with one end
#: spells none.
_RANGE = re.compile(
    r"^(?P<minimum>\d+)\s*[–—-]\s*(?P<maximum>\d+)\s+(?P<unit>[a-z]+)$"
)

_COMMENT = re.compile(r"<!--.*?-->", re.S)

#: Whether a rule admits a plan that complies with it. The register has no field
#: for this, and inventing one is out of this slice — so every rule this
#: producer builds admits a compliant variant, which is what every record it
#: reads is: a length range admits a shorter plan, an originality rule admits
#: original material, a disclosure rule admits a disclosure. A record that
#: admitted none would end a destination outright (V-P04), which is a tier-1
#: decision the owner approves on the record rather than one a loader infers.
_COMPLIANT_VARIANT: Final[bool] = True

#: What a rule may fix: one of E-14's three mandated values.
FixedValue = Union[PlanFormat, LengthTarget, HashtagPolicy]


class DestinationRulesError(ValueError):
    """The destination's rules cannot be built from the configuration on disk."""


@dataclass(frozen=True, slots=True)
class Fixed:
    """One value one rule fixes, and the ``E-14`` field it fixes it for."""

    field: str
    value: FixedValue


@dataclass(frozen=True, slots=True)
class BoundRule:
    """One rule, the destination it binds to, and what it fixes there.

    ``source`` is the file that **declares** it: a record under
    ``knowledge/records/dst/`` for a platform rule, the client contract for a
    client rule. A finding cites the ``rule_id``, and an id whose declaring
    source nobody can open is an id a reader cannot check.
    """

    rule: FixingRule
    destination: Destination
    fixes: tuple[Fixed, ...]
    source: str
    #: Step 4 §5: the record's review has lapsed and the loader demoted it. A
    #: client rule is never one — the contract carries no review date, and
    #: inventing an expiry for it here would be a rule nobody wrote. Carried as
    #: register metadata and deliberately **not** consulted by :func:`_authority`:
    #: it must not break a tie inside a tier (#363).
    weak: bool = False

    def value_for(self, field: str) -> Optional[FixedValue]:
        return next((item.value for item in self.fixes if item.field == field), None)


@dataclass(frozen=True, slots=True)
class RuleCatalogue:
    """Every rule that may fix a destination value, from both authorities."""

    bound: tuple[BoundRule, ...]
    register_path: str
    contract_path: str
    #: Records whose ``## Applies when`` is not one destination term. They reach
    #: no destination through this producer, and they are kept so that a keeper
    #: can see which records are waiting on a binding rather than missing.
    unbound: tuple[str, ...] = ()

    def sources(self) -> Mapping[str, str]:
        """Every ``rule_id``, mapped to the file that declares it."""

        return {item.rule.rule_id: item.source for item in self.bound}

    def for_destination(self, destination: Destination) -> tuple[BoundRule, ...]:
        return tuple(
            item for item in self.bound if item.destination is destination
        )

    def rules_for(self, destination: Destination) -> DestinationRules:
        """This destination's three values and the rules that fixed them."""

        return _compose(destination, self.for_destination(destination))


def destination_rules(
    destination: Destination,
    *,
    register: Optional[Path] = None,
    contract: Optional[Path] = None,
    today: Optional[date] = None,
) -> DestinationRules:
    """The rules S-10 adapts to and S-11 checks against, for one destination.

    A **hard** input. Every path out of here is either a complete
    ``DestinationRules`` or a :class:`DestinationRulesError`: there is no
    permissive default, no empty table and no partially built object, because a
    surface adapted to rules nobody stated is a surface adapted to nothing.
    """

    return rule_catalogue(
        register=register, contract=contract, today=today
    ).rules_for(destination)


def rule_catalogue(
    *,
    register: Optional[Path] = None,
    contract: Optional[Path] = None,
    today: Optional[date] = None,
) -> RuleCatalogue:
    """Read both authorities once. Raises :class:`DestinationRulesError`.

    Both are read together because the refusals are about the pair: an id the
    register and the contract both claim names neither rule, and a field two
    equal authorities fix is fixed by neither.
    """

    register_dir = register if register is not None else REGISTER_DIR
    contract_path = (
        contract if contract is not None else client_dir() / CONTRACT_FILE
    )

    platform, unbound = _register_rules(register_dir, today=today)
    client = _contract_rules(contract_path)

    declared: dict[str, str] = {}
    for item in (*platform, *client):
        first = declared.setdefault(item.rule.rule_id, item.source)
        if first != item.source:
            raise DestinationRulesError(
                f"{item.rule.rule_id} is declared by both {first} and "
                f"{item.source}; a finding cites the rule that made it, and a "
                "name two rules answer to names neither"
            )

    return RuleCatalogue(
        bound=(*platform, *client),
        register_path=str(register_dir),
        contract_path=str(contract_path),
        unbound=unbound,
    )


# ----------------------------------------------------------------------
# The register side
# ----------------------------------------------------------------------


def _register_rules(
    register_dir: Path, *, today: Optional[date]
) -> tuple[tuple[BoundRule, ...], tuple[str, ...]]:
    """Every destination record that is a rule S-10 applies, and the unbound."""

    try:
        base = load_register(register_dir, today=today)
    except LoaderError as exc:
        raise DestinationRulesError(
            f"{register_dir}: the register cannot be read, so no destination has "
            f"rules to adapt to — {exc}"
        ) from exc

    bound: list[BoundRule] = []
    unbound: list[str] = []
    for loaded in base.records:
        if not loaded.identity.startswith(DESTINATION_PREFIX):
            continue
        destination = _binding(loaded)
        if destination is None:
            unbound.append(loaded.identity)
            continue
        if loaded.tier not in PLATFORM_TIERS:
            # Tier 3 and below is not a rule S-10 applies (§3). It is not lost:
            # the register routes it to the stage on its own terms.
            continue
        influences = tuple(
            influence
            for influence in loaded.record.influences
            if influence.stage == STAGE
        )
        if not influences:
            continue
        statement = loaded.routed_text.strip()
        if not statement:
            raise DestinationRulesError(
                f"{loaded.record.path}: `## Statement` is empty, and the "
                "statement is what reaches adaptation as the rule"
            )
        try:
            rule = PlatformRule(
                rule_id=loaded.identity,
                text=statement,
                tier=loaded.tier,
                compliant_variant=_COMPLIANT_VARIANT,
                knowledge=loaded.ref(),
            )
        except (PlanError, ValueError) as exc:
            raise DestinationRulesError(f"{loaded.record.path}: {exc}") from exc
        bound.append(
            BoundRule(
                rule=rule,
                destination=destination,
                fixes=_fixes(loaded, influences),
                source=loaded.record.path,
                weak=loaded.is_weak,
            )
        )
    return tuple(bound), tuple(unbound)


def _binding(loaded: LoadedRecord) -> Optional[Destination]:
    """The one destination this record binds to, or ``None`` when it binds none.

    Exactly one ``destination is …`` term and nothing else. A negation, a
    disjunction or ``always`` is not a destination binding — each of them is true
    of destinations the record never named — and a prefix is not a binding at
    all.
    """

    condition = loaded.condition
    if not isinstance(condition, Atom) or condition.family != DESTINATION:
        return None
    try:
        return Destination(condition.name)
    except ValueError as exc:  # pragma: no cover - the vocabulary mirrors the enum
        raise DestinationRulesError(
            f"{loaded.record.path}: applies when `{condition.text}`, and "
            f"{condition.name!r} is not one of the six destinations this engine "
            "has"
        ) from exc


def _fixes(
    loaded: LoadedRecord, influences: tuple[Influence, ...]
) -> tuple[Fixed, ...]:
    """The values this record's S-10 influence entries fix, read exactly."""

    fixed: dict[str, FixedValue] = {}
    for influence in influences:
        text = influence.text
        fields = influence.fields
        clauses = _FIXES.findall(text)
        if not clauses:
            # An entry that shapes a field without stating a value fixes
            # nothing, and that is a normal record: `K-DST-FB-02` constrains
            # what a caption's hashtags may say without deciding the policy.
            continue
        if len(clauses) > 1:
            raise DestinationRulesError(
                f"{loaded.record.path}: the `## Influences` entry {text[:50]!r} "
                "carries two `[fixes: …]` clauses; one entry fixes one value"
            )
        named = [name for name in fields if name in FIXED_FIELDS]
        if len(named) != 1:
            raise DestinationRulesError(
                f"{loaded.record.path}: the `## Influences` entry {text[:50]!r} "
                f"fixes a value and names {len(named)} of "
                + ", ".join(FIXED_FIELDS)
                + "; a fixed value belongs to exactly one of them"
            )
        field = named[0]
        value = parse_value(field, clauses[0], where=loaded.record.path)
        held = fixed.setdefault(field, value)
        if held != value:
            raise DestinationRulesError(
                f"{loaded.record.path}: fixes `{field}` twice, as {held!r} and "
                f"{value!r}; two values for one field fix neither"
            )
    return tuple(Fixed(field=name, value=item) for name, item in fixed.items())


# ----------------------------------------------------------------------
# The contract side
# ----------------------------------------------------------------------


def _contract_rules(path: Path) -> tuple[BoundRule, ...]:
    """The client's own tier-2 rules, one row per value it fixes."""

    if not path.is_file():
        raise DestinationRulesError(
            f"{path}: this client has no contract, and twelve of the eighteen "
            "values a destination needs are the client's to state"
        )
    try:
        document = load_document(path)
    except DocumentError as exc:
        raise DestinationRulesError(str(exc)) from exc

    body = document.section(CONTRACT_SECTION)
    if body is None:
        raise DestinationRulesError(
            f"{path}: no `## {CONTRACT_SECTION}` section; that is where the "
            "client states the lengths, formats and hashtag policies no "
            "destination record fixes"
        )
    try:
        rows = parse_table(
            _without_comments(body, str(path)),
            path=str(path),
            section=CONTRACT_SECTION,
            columns=_CONTRACT_COLUMNS,
        )
    except DocumentError as exc:
        raise DestinationRulesError(str(exc)) from exc

    bound: list[BoundRule] = []
    seen: dict[str, str] = {}
    claimed: dict[tuple[str, str], str] = {}
    for rule_id, destination, field, value, statement in rows:
        if not rule_id or not statement:
            raise DestinationRulesError(
                f"{path}: a `## {CONTRACT_SECTION}` row is named by its rule id "
                f"and states what it fixes; got {rule_id!r} and {statement!r}"
            )
        if rule_id.startswith(DESTINATION_PREFIX):
            raise DestinationRulesError(
                f"{path}: the client rule {rule_id} carries a "
                f"`{DESTINATION_PREFIX}` id, which is the register's. A contract "
                f"rule citing one would claim the authority of a record in "
                f"{DESTINATION_RECORDS}/ that the contract does not own"
            )
        if rule_id in seen:
            raise DestinationRulesError(
                f"{path}: {rule_id} names two rows; a finding cites the rule "
                "that made it, and a name two rules answer to names neither"
            )
        seen[rule_id] = statement
        try:
            target = Destination(destination)
        except ValueError:
            raise DestinationRulesError(
                f"{path}: {rule_id} names the destination {destination!r}; the "
                "six surfaces are "
                + ", ".join(item.value for item in Destination)
            ) from None
        if field not in FIXED_FIELDS:
            raise DestinationRulesError(
                f"{path}: {rule_id} fixes {field!r}; a client rule of this table "
                f"fixes one of {', '.join(FIXED_FIELDS)}"
            )
        owner = claimed.setdefault((destination, field), rule_id)
        if owner != rule_id:
            raise DestinationRulesError(
                f"{path}: {owner} and {rule_id} both fix `{field}` for "
                f"{destination}; two rules of the client's own authority fixing "
                "one field fix neither"
            )
        try:
            rule = ClientRule(
                rule_id=rule_id,
                text=statement,
                tier=KnowledgeTier.APPROVED_CLIENT_RULE,
                compliant_variant=_COMPLIANT_VARIANT,
            )
        except PlanError as exc:
            raise DestinationRulesError(f"{path}: {exc}") from exc
        bound.append(
            BoundRule(
                rule=rule,
                destination=target,
                fixes=(
                    Fixed(
                        field=field,
                        value=parse_value(field, value, where=str(path)),
                    ),
                ),
                source=str(path),
            )
        )
    return tuple(bound)


# ----------------------------------------------------------------------
# Composition
# ----------------------------------------------------------------------


def _compose(
    destination: Destination, bound: tuple[BoundRule, ...]
) -> DestinationRules:
    """Resolve the three values, and keep everything else that reached here."""

    chosen: dict[str, tuple[BoundRule, FixedValue]] = {}
    lost: dict[str, FixingRule] = {}
    for field in FIXED_FIELDS:
        winner, value, losers = _resolve(destination, field, bound)
        chosen[field] = (winner, value)
        for rule in losers:
            lost.setdefault(rule.rule_id, rule)

    # A rule that lost one field may have won another; it is already one of the
    # three, so it is not repeated among the rules that only shaped the plan.
    fixing = {item.rule.rule_id for item, _ in chosen.values()}
    rest: dict[str, FixingRule] = {
        rule_id: rule for rule_id, rule in lost.items() if rule_id not in fixing
    }
    for item in bound:
        if item.rule.rule_id not in fixing:
            rest.setdefault(item.rule.rule_id, item.rule)

    plan_format = chosen[FORMAT_FIELD][1]
    length = chosen[LENGTH_FIELD][1]
    hashtags = chosen[HASHTAG_FIELD][1]
    # Each parser only ever produces its own field's type. Checked rather than
    # asserted, because `python -O` removes an assert and a value of the wrong
    # type here would reach S-11 as the rule a plan is checked against.
    if not isinstance(plan_format, PlanFormat):  # pragma: no cover - guaranteed
        raise _mistyped(destination, FORMAT_FIELD, plan_format)
    if not isinstance(length, LengthTarget):  # pragma: no cover - guaranteed
        raise _mistyped(destination, LENGTH_FIELD, length)
    if not isinstance(hashtags, HashtagPolicy):  # pragma: no cover - guaranteed
        raise _mistyped(destination, HASHTAG_FIELD, hashtags)
    try:
        return DestinationRules(
            destination=destination,
            format=plan_format,
            format_rule=chosen[FORMAT_FIELD][0].rule,
            length=length,
            length_rule=chosen[LENGTH_FIELD][0].rule,
            hashtags=hashtags,
            hashtag_rule=chosen[HASHTAG_FIELD][0].rule,
            other_rules=tuple(rest[rule_id] for rule_id in sorted(rest)),
        )
    except PlanError as exc:
        raise DestinationRulesError(f"{destination.value}: {exc}") from exc


def _mistyped(
    destination: Destination, field: str, value: FixedValue
) -> DestinationRulesError:
    """The refusal for a value that is not of its own field's type."""

    return DestinationRulesError(
        f"{destination.value}: `{field}` was fixed at {value!r}, which is a "
        f"{type(value).__name__} and not the type that field carries"
    )


def _resolve(
    destination: Destination, field: str, bound: tuple[BoundRule, ...]
) -> tuple[BoundRule, FixedValue, tuple[FixingRule, ...]]:
    """Which rule fixes this field, and which lost it.

    The ladder is ``arp.tier_rank()`` and nothing else. Two rules of equal
    authority refuse: neither is entitled to decide, and picking either would be
    this module inventing a tie-break the architecture does not have. Nothing
    inside a tier separates them — not review freshness, not confidence, not
    file order.
    """

    offers: list[tuple[BoundRule, FixedValue]] = []
    for item in bound:
        value = item.value_for(field)
        if value is not None:
            offers.append((item, value))
    if not offers:
        raise DestinationRulesError(
            f"{destination.value}: nothing fixes `{field}`. A destination record "
            f"under {DESTINATION_RECORDS}/ at tier "
            f"{' or '.join(tier.value for tier in PLATFORM_TIERS)}, or a tier-"
            f"{KnowledgeTier.APPROVED_CLIENT_RULE.value} rule in the client's "
            f"`## {CONTRACT_SECTION}`, has to state it — the three values are "
            "mandatory, so an absent one is a configuration failure and never a "
            "default this producer may pick"
        )

    ranked = sorted(offers, key=lambda offer: _authority(offer[0]))
    best = _authority(ranked[0][0])
    tied = [item for item, _ in ranked if _authority(item) == best]
    if len(tied) > 1:
        raise DestinationRulesError(
            f"{destination.value}: "
            + " and ".join(sorted(item.rule.rule_id for item in tied))
            + f" fix `{field}` at the same authority. Two equal authorities "
            "fixing one field fix neither, and choosing between them is the "
            "keeper's decision rather than a tie-break this producer invents"
        )
    winner, value = ranked[0]
    return winner, value, tuple(item.rule for item, _ in ranked[1:])


def _authority(item: BoundRule) -> int:
    """Where this rule sits on the existing ladder. Smaller is stronger.

    ``arp.tier_rank()`` and nothing else. An earlier version of this function
    also ranked a lapsed record below a current one at the same tier, which
    quietly made review freshness a second precedence dimension: a weak tier-4
    rule and a current tier-4 rule fixing one field stopped being equal, so the
    current one won instead of the pair refusing. #363 authorizes one ordering,
    and ``weak`` is register metadata that does not decide a field here.
    """

    rank = tier_rank(item.rule.tier)
    if rank is None:  # pragma: no cover - both rule types refuse such a tier
        raise DestinationRulesError(
            f"{item.rule.rule_id} is tier {item.rule.tier.value}, which the map "
            "§5 ladder does not place; a rule nobody can rank cannot win or lose "
            "a field"
        )
    return rank


# ----------------------------------------------------------------------
# Values, read exactly
# ----------------------------------------------------------------------


def parse_value(field: str, spec: str, *, where: str) -> FixedValue:
    """One ``[fixes: …]`` or contract cell, as the value it states.

    Raises :class:`DestinationRulesError` on anything it cannot read exactly.
    A parser that guessed would produce a wrong length or a wrong policy
    silently, and a plan checked against it would be approved against a rule
    nobody wrote.
    """

    stated = " ".join(spec.split())
    if field == FORMAT_FIELD:
        return _format(stated, where=where)
    if field == HASHTAG_FIELD:
        return _hashtags(stated, where=where)
    if field == LENGTH_FIELD:
        return _length(stated, where=where)
    raise DestinationRulesError(
        f"{where}: `{field}` is not one of the three values a destination fixes "
        f"({', '.join(FIXED_FIELDS)})"
    )


def _format(stated: str, *, where: str) -> PlanFormat:
    try:
        return PlanFormat(stated)
    except ValueError:
        raise DestinationRulesError(
            f"{where}: `{FORMAT_FIELD}` is fixed at {stated!r}, which is not one "
            "of " + ", ".join(member.value for member in PlanFormat)
        ) from None


def _hashtags(stated: str, *, where: str) -> HashtagPolicy:
    try:
        return HashtagPolicy(stated)
    except ValueError:
        raise DestinationRulesError(
            f"{where}: `{HASHTAG_FIELD}` is fixed at {stated!r}, which is not "
            "one of " + ", ".join(member.value for member in HashtagPolicy)
        ) from None


def _length(stated: str, *, where: str) -> LengthTarget:
    match = _RANGE.match(stated)
    if match is None:
        raise DestinationRulesError(
            f"{where}: `{LENGTH_FIELD}` is fixed at {stated!r}; a length target "
            "is a range and a unit, written `250–400 words`. Both ends are the "
            "rule, so a ceiling alone states no target"
        )
    try:
        unit = LengthUnit(match.group("unit"))
    except ValueError:
        raise DestinationRulesError(
            f"{where}: `{LENGTH_FIELD}` is counted in "
            f"{match.group('unit')!r}; the engine counts "
            + ", ".join(member.value for member in LengthUnit)
        ) from None
    try:
        return LengthTarget(
            minimum=int(match.group("minimum")),
            maximum=int(match.group("maximum")),
            unit=unit,
        )
    except PlanError as exc:
        raise DestinationRulesError(f"{where}: {exc}") from exc


def _without_comments(body: str, path: str) -> str:
    """People-only notes removed; an unclosed one is refused rather than read."""

    stripped = _COMMENT.sub("", body)
    if "<!--" in stripped or "-->" in stripped:
        raise DestinationRulesError(
            f"{path}: an HTML comment is not closed (`<!--` … `-->`), so what is "
            "a note for a person and what is a rule cannot be told apart"
        )
    return stripped
