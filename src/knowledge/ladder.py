"""The strength ladder: the universal one, and what a client's may do (§7).

The universal ladder is `knowledge/ladders/default.md` — a knowledge record with a
`## Levels` table, worded as what the evidence shows rather than as a score, so
that a writer can phrase a claim at the strength its evidence actually reaches
(U-4).

A **client** may declare its own ladder in its contract, as
`claim_strength_ceiling`. Patch S4-R1 constrains it: a client ladder may rename
the universal levels and may restrict them further, and it may never permit a
stronger assertion than the universal ladder allows for the same evidence. To make
that last part checkable rather than hoped for, every client level declares which
universal level it maps to::

    ### claim_strength_ceiling

    - observed on one shop floor → universal level 2
    - confirmed by the manufacturer → universal level 3

The effective ceiling is then the lower of the client level and the universal level
the evidence actually reached, so a client level can never lift a claim above what
the universal ladder allows. Three things make that hold, and the validator refuses
a ladder that breaks any of them:

1. **every level is mapped.** An unmapped level has no ceiling to be the lower of;
2. **the mappings increase.** The ladder is written weakest first, so its levels
   must map to strictly increasing universal levels. Two client levels mapping to
   one universal level are not two strengths;
3. **no mapping is above the universal top.** With 1 and 2 this also fixes each
   level's position: the top client level may map to level 4, the one below it to
   at most 3, and a ladder with more levels than the universal one cannot be
   written at all — a client restricts this ladder, it does not extend it.

An **unannotated** ladder is a ladder from before this format. `level_names` passes
it through untouched, so the engine keeps reading exactly what the contract says;
the validator is what requires the mappings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Optional, Sequence

from src.knowledge.markdown import DocumentError, parse_table
from src.knowledge.records import KnowledgeRecord

#: The plan slot a client declares its ladder in (AD-10).
CLIENT_LADDER_SLOT: Final[str] = "claim_strength_ceiling"

#: How many levels the universal ladder has (§7). Mirrored against
#: `knowledge/ladders/default.md`, which is the authority a person edits.
UNIVERSAL_TOP_LEVEL: Final[int] = 4

#: A client ladder has at least two levels; one level is not a ladder.
MINIMUM_CLIENT_LEVELS: Final[int] = 2

_LEVEL_COLUMNS: Final[tuple[str, ...]] = (
    "Level", "Wording", "Evidence that reaches it",
)

_ANNOTATION = re.compile(
    r"^(?P<name>.+?)\s*(?:→|->)\s*universal\s+level\s*(?P<level>\d+)\s*$",
    re.IGNORECASE,
)


class LadderError(ValueError):
    """The universal ladder cannot be read."""


@dataclass(frozen=True, slots=True)
class LadderLevel:
    """One level of the universal ladder."""

    level: int
    wording: str
    evidence: str


@dataclass(frozen=True, slots=True)
class ClientLadderLevel:
    """One level of a client ladder, and the universal level it maps to."""

    name: str
    #: ``None`` when the level declares no mapping, which rule 9 refuses.
    universal_level: Optional[int]


def parse_universal_ladder(record: KnowledgeRecord) -> tuple[LadderLevel, ...]:
    """The levels of `ladders/default.md`. Raises :class:`LadderError`."""

    try:
        rows = parse_table(
            record.document.section("Levels") or "",
            path=record.path,
            section="Levels",
            columns=_LEVEL_COLUMNS,
        )
    except DocumentError as exc:
        raise LadderError(str(exc)) from exc

    levels: list[LadderLevel] = []
    for position, row in enumerate(rows, start=1):
        if not row[0].isdigit() or int(row[0]) != position:
            raise LadderError(
                f"{record.path}: the `## Levels` table is numbered from 1 upwards, "
                f"weakest first; row {position} is level {row[0]!r}"
            )
        levels.append(LadderLevel(level=position, wording=row[1], evidence=row[2]))
    return tuple(levels)


def parse_client_ladder(values: Sequence[str]) -> tuple[ClientLadderLevel, ...]:
    """A client ladder as declared, weakest first, mappings read where present."""

    levels: list[ClientLadderLevel] = []
    for value in values:
        match = _ANNOTATION.match(value.strip())
        if match is None:
            levels.append(ClientLadderLevel(name=value.strip(), universal_level=None))
            continue
        levels.append(
            ClientLadderLevel(
                name=" ".join(match.group("name").split()),
                universal_level=int(match.group("level")),
            )
        )
    return tuple(levels)


def level_names(values: Sequence[str]) -> tuple[str, ...]:
    """The client's own wording for each level, without the mapping.

    What the engine carries into a plan is the level a person reads — "confirmed
    by the manufacturer", never "confirmed by the manufacturer → universal level
    3". The mapping is a declaration about the level, not part of its name.
    """

    return tuple(level.name for level in parse_client_ladder(values))


def client_ladder_problems(
    values: Sequence[str], *, path: str, universal_top: int = UNIVERSAL_TOP_LEVEL
) -> tuple[str, ...]:
    """What §8 rule 9 has against this client ladder. Empty when it is sound."""

    where = f"{path}: `{CLIENT_LADDER_SLOT}`"
    if len(values) < MINIMUM_CLIENT_LEVELS:
        return (
            f"{where} declares {len(values)} level(s); a ladder has at least "
            f"{MINIMUM_CLIENT_LEVELS}, weakest first",
        )

    levels = parse_client_ladder(values)
    unmapped = [level.name for level in levels if level.universal_level is None]
    if unmapped:
        return (
            f"{where}: {', '.join(repr(name) for name in unmapped)} declares no "
            "universal level. Every client level says which universal level it "
            "maps to (`… → universal level 2`), because the effective ceiling is "
            "the lower of the two",
        )

    problems: list[str] = []
    above = [
        level
        for level in levels
        if level.universal_level is not None and level.universal_level > universal_top
    ]
    for level in above:
        problems.append(
            f"{where}: {level.name!r} maps to universal level "
            f"{level.universal_level}, and the universal ladder stops at "
            f"{universal_top}. A client ladder may restrict the universal ladder, "
            "never reach past it"
        )
    if len(levels) > universal_top:
        problems.append(
            f"{where} declares {len(levels)} levels, and the universal ladder has "
            f"{universal_top}. A client ladder may merge levels or stop lower, "
            "never add one"
        )
    for earlier, later in zip(levels, levels[1:]):
        if (
            earlier.universal_level is not None
            and later.universal_level is not None
            and later.universal_level <= earlier.universal_level
        ):
            problems.append(
                f"{where}: {later.name!r} is above {earlier.name!r} in the ladder "
                f"but maps to universal level {later.universal_level}, not above "
                f"{earlier.universal_level}. The ladder is ordered weakest first, "
                "so its mappings rise with it"
            )
    return tuple(problems)
