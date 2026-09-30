"""S-08's contract material in production: positions, prohibitions, preferences.

Issue #368, slice SL-6.47. ``StrategyContract`` is a **required** input at
thirteen call sites across S-08 and S-09 and was constructed nowhere outside
``tests/test_304_candidate_strategies_and_selection.py`` — sixteen of those as a
bare ``StrategyContract()``. This is the producer, and it exists to keep apart
two things that used to construct the same object.

Declared empty is an answer; absent is not
------------------------------------------
Never Blank's three sets **are** empty, by owner decision of 2026-09-30. That is
not the defect. The defect was that the absence of configuration looked exactly
like the decision, and on one of the three axes that difference is invisible and
harmful:

* ``positions`` empty **fails closed** — S-08 raises for any
  ``client_position_ref`` the contract did not approve;
* ``prohibitions`` empty is **permissive and silent** — S-09 has no other source
  of ``ExclusionReason.CONTRACT_PROHIBITION``, so nothing is ever excluded and
  the trace shows nothing was consulted;
* ``preferences`` empty is **inert** — §7.3's fifth rung stops discriminating and
  no ``PrecedenceApplication`` is recorded.

So the document states each of the three, and ``none`` is how a person writes
"this client has none of those". A section that is simply missing is a contract
that did not answer, and this producer raises and names it. There is no fallback
to ``()`` anywhere on this path: restoring one would make the missing case pass
as the configured case, which is the one outcome the slice exists to prevent.

A hard input, following #337
----------------------------
``client_contract()`` refuses a missing contract because "there is no honest
default". The same holds here with more force: the contract bounds what a
strategy may claim on the client's behalf, and an engine that picked a value for
it would be deciding the client's positions for them.

Sources: `docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md` §1 (S-08,
S-09); `docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md` §4 (E-13, E-06);
`docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md` §5, §7.3.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final, Optional, Sequence

from src.editorial_core.arp import KnowledgeTier
from src.editorial_core.candidate_strategies import (
    ClientPosition,
    ContractRule,
    FocalSubjectKind,
    RevealKind,
    StrategyContract,
    StrategyError,
)
from src.knowledge.markdown import (
    Document,
    DocumentError,
    load_document,
    parse_table,
)
from src.strategy.client_contract import CONTRACT_FILE
from src.strategy.client_contracts import client_dir

#: The three sections, in the order §1 lists the three inputs.
POSITIONS_SECTION: Final[str] = "Client positions"
PROHIBITIONS_SECTION: Final[str] = "Client prohibitions"
PREFERENCES_SECTION: Final[str] = "Client preferences"
DECLARED_SECTIONS: Final[tuple[str, ...]] = (
    POSITIONS_SECTION, PROHIBITIONS_SECTION, PREFERENCES_SECTION,
)

#: How a person writes "this client has none of those". It is a *declaration*,
#: which is the whole point: the empty tuple it produces is the client's answer
#: and not the absence of one.
DECLARED_EMPTY: Final[str] = "none"

#: A structural column with nothing in it, written the way the register writes
#: it (``records.ROUTE_NONE``): an em dash is how a person says "this row has
#: none of that", and an empty cell is how a person leaves a row unfinished.
NONE_CELL: Final[str] = "—"

_POSITION_COLUMNS: Final[tuple[str, ...]] = ("position_id", "rule_id", "statement")

#: A prohibition and a preference are the same shape — both are ``ContractRule``
#: — and they differ only in which section declares them. ``tier`` is not a
#: column: a rule written in the client's own contract carries the client's own
#: authority, and a contract that could name its own tier could promote itself to
#: hard platform policy.
_RULE_COLUMNS: Final[tuple[str, ...]] = (
    "rule_id", "focal_subjects", "reveals", "statement",
)

#: The tier a rule declared in the client's contract carries (Step 4 §2.3, and
#: Step 1 §4's "the contract (tier 2)").
CONTRACT_TIER: Final[KnowledgeTier] = KnowledgeTier.APPROVED_CLIENT_RULE

_COMMENT = re.compile(r"<!--.*?-->", re.S)


class StrategyContractError(ValueError):
    """The client's configuration cannot be read as S-08's contract material."""


def strategy_contract(*, directory: Optional[Path] = None) -> StrategyContract:
    """The active client's positions, prohibitions and preferences.

    A **hard** input. Raises :class:`StrategyContractError` when the contract is
    absent, when any one of the three declarations is absent, or when one of them
    cannot be read exactly. Nothing here degrades to an empty set: only the
    document may say the set is empty.
    """

    root = directory if directory is not None else client_dir()
    path = root / CONTRACT_FILE
    if not path.is_file():
        raise StrategyContractError(
            f"{path}: this client has no contract; the positions a strategy may "
            "take, the prohibitions S-09 excludes on and the preferences that "
            "order what is left are the client's to state, and none of them has a "
            "default the engine may pick"
        )
    return load_strategy_contract(path)


def load_strategy_contract(path: Path) -> StrategyContract:
    """Read one contract document as S-08's contract material."""

    try:
        document = load_document(path)
    except DocumentError as exc:
        raise StrategyContractError(str(exc)) from exc
    return parse_strategy_contract(document)


def parse_strategy_contract(document: Document) -> StrategyContract:
    """The three declarations, typed. Raises :class:`StrategyContractError`."""

    path = document.path
    positions = _positions(document)
    prohibitions = _rules(document, PROHIBITIONS_SECTION)
    preferences = _rules(document, PREFERENCES_SECTION)
    try:
        # Passed by keyword and all three together: the type refuses an unspoken
        # contract, and this producer is the one caller that has read all three.
        return StrategyContract(
            positions=positions,
            prohibitions=prohibitions,
            preferences=preferences,
        )
    except StrategyError as exc:
        raise StrategyContractError(f"{path}: {exc}") from exc


def declared_rows(
    document: Document, section: str, *, columns: tuple[str, ...]
) -> tuple[tuple[str, ...], ...]:
    """The rows of one declaration, or ``()`` when the client declared none.

    The refusal that matters is the first one: a section that is not there at all
    is a declaration nobody made, and it is named in the message so a keeper is
    told which of the three to write rather than which file to search.
    """

    body = document.section(section)
    if body is None:
        raise StrategyContractError(
            f"{document.path}: no `## {section}` section. S-08 requires the "
            f"declaration, and a client with none of those writes "
            f"`{DECLARED_EMPTY}` under the heading — an absent section is not an "
            "empty set, it is a contract that did not answer"
        )
    stated = without_comments(body, path=document.path, section=section)
    lines = [line.strip() for line in stated.splitlines() if line.strip()]
    says_none = any(line.casefold() == DECLARED_EMPTY for line in lines)
    tabled = any(line.startswith("|") for line in lines)
    if says_none and len(lines) > 1:
        raise StrategyContractError(
            f"{document.path}: `## {section}` declares `{DECLARED_EMPTY}` and "
            "states something else as well; one of the two is what the client "
            "meant and nothing here chooses between them"
        )
    if says_none:
        return ()
    if not tabled:
        raise StrategyContractError(
            f"{document.path}: `## {section}` states neither `{DECLARED_EMPTY}` nor "
            f"a table of {' | '.join(columns)}; those are the two answers this "
            "declaration has"
        )
    try:
        return parse_table(
            stated, path=document.path, section=section, columns=columns
        )
    except DocumentError as exc:
        raise StrategyContractError(str(exc)) from exc


def without_comments(body: str, *, path: str, section: str) -> str:
    """People-only notes removed; an unclosed one is refused rather than read."""

    stripped = _COMMENT.sub("", body)
    if "<!--" in stripped or "-->" in stripped:
        raise StrategyContractError(
            f"{path}: an HTML comment in `## {section}` is not closed (`<!--` … "
            "`-->`), so what is a note for a person and what is a declaration "
            "cannot be told apart"
        )
    return stripped


# ----------------------------------------------------------------------
# The three declarations
# ----------------------------------------------------------------------


def _positions(document: Document) -> tuple[ClientPosition, ...]:
    """E-06's approved positions: what ``client_position_ref`` may name."""

    rows = declared_rows(document, POSITIONS_SECTION, columns=_POSITION_COLUMNS)
    positions: list[ClientPosition] = []
    for position_id, rule_id, statement in rows:
        try:
            positions.append(
                ClientPosition(
                    position_id=position_id, text=statement, rule_id=rule_id
                )
            )
        except StrategyError as exc:
            raise StrategyContractError(
                f"{document.path}: `## {POSITIONS_SECTION}` row "
                f"{position_id or '(unnamed)'}: {exc}"
            ) from exc
    return tuple(positions)


def _rules(document: Document, section: str) -> tuple[ContractRule, ...]:
    """One section of ``ContractRule``s, at the client's own tier."""

    rows = declared_rows(document, section, columns=_RULE_COLUMNS)
    rules: list[ContractRule] = []
    for rule_id, subjects, reveals, statement in rows:
        try:
            rules.append(
                ContractRule(
                    rule_id=rule_id,
                    text=statement,
                    tier=CONTRACT_TIER,
                    focal_subjects=_focal_subjects(
                        subjects, path=document.path, section=section, rule=rule_id
                    ),
                    reveals=_reveals(
                        reveals, path=document.path, section=section, rule=rule_id
                    ),
                )
            )
        except StrategyError as exc:
            raise StrategyContractError(
                f"{document.path}: `## {section}` row {rule_id or '(unnamed)'}: "
                f"{exc}"
            ) from exc
    return tuple(rules)


def _focal_subjects(
    cell: str, *, path: str, section: str, rule: str
) -> tuple[FocalSubjectKind, ...]:
    kinds: list[FocalSubjectKind] = []
    for name in _terms(
        cell, path=path, section=section, rule=rule, column="focal_subjects"
    ):
        try:
            kinds.append(FocalSubjectKind(name))
        except ValueError:
            raise StrategyContractError(
                f"{path}: `## {section}` row {rule} names the focal subject "
                f"{name!r}; E-13's kinds are "
                + ", ".join(member.value for member in FocalSubjectKind)
            ) from None
    return tuple(kinds)


def _reveals(
    cell: str, *, path: str, section: str, rule: str
) -> tuple[RevealKind, ...]:
    kinds: list[RevealKind] = []
    for name in _terms(
        cell, path=path, section=section, rule=rule, column="reveals"
    ):
        try:
            kinds.append(RevealKind(name))
        except ValueError:
            raise StrategyContractError(
                f"{path}: `## {section}` row {rule} names the reveal {name!r}; "
                "E-13's reveals are "
                + ", ".join(member.value for member in RevealKind)
            ) from None
    return tuple(kinds)


def _terms(
    cell: str, *, path: str, section: str, rule: str, column: str
) -> Sequence[str]:
    """One structural column, as its comma-separated terms or none of them.

    An em dash is "this rule names none of those", which
    :meth:`ContractRule.applies_to` reads as text guidance matching nothing. An
    **empty** cell is not the same thing and is refused: a row a person did not
    finish would otherwise arrive as a deliberate "none".
    """

    stated = " ".join(cell.split())
    if stated == NONE_CELL:
        return ()
    if not stated:
        raise StrategyContractError(
            f"{path}: `## {section}` row {rule} leaves `{column}` blank; a rule "
            f"that names none of them says so with `{NONE_CELL}`, so that an "
            "unfinished row is not read as a decision"
        )
    return [part.strip() for part in stated.split(",") if part.strip()]
