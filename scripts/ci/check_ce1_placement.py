#!/usr/bin/env python3
"""CE-1 placement rule: no weekday pipeline, no destination pipeline (Issue #290).

CE-1 says that neither weekday nor destination may define a separate Editorial
Core pipeline. The stage-topology registry (``src/editorial_core/topology.py``)
says there is one engine, and the topology digest in every RunManifest says
which engine a run executed. Neither of them stops a module from quietly
growing a second pipeline inside the first — an ``if`` on Monday here, a table
of stages per destination there — which is how the current engine acquired its
weekday branches in the first place. This check is what stops that.

Two rules, over every module of the editorial core (S-00 … S-13):

``CE1-CLOCK``
    No module may read the weekday or the clock. Weekday, rubric and lens are
    configuration and scheduling inputs: they are handed to the engine, and a
    stage that reads the calendar instead is deciding by the day. Renaming the
    clock on the way in does not move it out of the core, so an import alias
    or a local binding is followed back to what it stands for. Timestamps
    belong to the run harness (``src/run/``), which is outside the core and is
    not checked.

``CE1-DESTINATION``
    No module may select stages by destination: a branch on a destination, or
    a table keyed by destination, may not decide which stages run. The
    destination may be written out (``"telegram"``) or arrive as a value
    (``destination``, ``enabled_destinations``), and the stages may be named
    outright (``"S-10"``) or reached through a name that holds them
    (``stages``, ``CANONICAL_TOPOLOGY.stage_ids``); every pairing of the two
    is selection, and ``if destination in enabled_destinations: return
    stages[:2]`` — naming neither a destination nor a stage — is the breach in
    its plainest form rather than a way around the rule.
    Destination-specific *behaviour* is legitimate and untouched — it lives in
    destination knowledge (``K-DST-*``), in adaptation (S-10), in check
    records and in the publishers. What is forbidden is a destination choosing
    the topology.

Prose is not a breach: docstrings and other bare string expressions are
exempt, so a module may describe the rule it obeys.

Run it directly (``python3 scripts/ci/check_ce1_placement.py``) or through
``tests/test_290_ce1_placement.py``, which is what puts it in CI.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Optional

from src.publishing.release_scope import NON_R1_PUBLISH_CHANNELS, R1_PUBLISH_CHANNELS

#: The package that holds S-00 … S-13.
DEFAULT_ROOT = Path("src/editorial_core")

#: The six canonical destinations, taken from the one existing list rather
#: than copied beside it (#227: a duplicated list is a list that drifts).
#: ``blog`` is the Wix surface's other name in the current engine.
DESTINATION_NAMES = frozenset(
    {*R1_PUBLISH_CHANNELS, *NON_R1_PUBLISH_CHANNELS, "blog"}
)

#: Calls that read the clock or the weekday, by attribute (``datetime.now``)
#: or by bare name (``from time import time``).
_CLOCK_CALLS = frozenset({
    "now", "utcnow", "today", "fromtimestamp",
    "time", "time_ns", "localtime", "gmtime", "monotonic", "monotonic_ns",
    "weekday", "isoweekday",
})

#: Weekday vocabulary in a name or in a string the code uses as a value.
_WEEKDAY_WORDS = re.compile(
    r"(?i)(?:mon|tues|wednes|thurs|fri|satur|sun)day|weekday|weekend|day_name|%[aA]\b"
)

_STAGE_LITERAL = re.compile(r"^S-(?:0\d|1[0-5])$")
_STAGE_MEMBER = re.compile(r"^S_(?:0\d|1[0-5])$")

#: Identifiers that hold the stage sequence rather than one stage. A branch
#: returning ``stages[:2]`` selects stages exactly as one returning
#: ``("S-10", "S-12")`` does, and code is free to reach the topology through
#: an ordinary variable.
_STAGE_SEQUENCE = re.compile(
    r"(?i)(?:^|_)"
    r"(?:stages|stage_ids|stage_order|stage_sequence|topology|pipeline)"
    r"(?:_|$)"
)

#: Names a destination arrives and travels under. A branch need not write a
#: surface out to be a branch on one: ``if destination in enabled_destinations``
#: cuts the engine per destination while naming no destination at all.
_DESTINATION_VALUE = re.compile(
    r"(?i)(?:^|_)(?:destination|channel|surface|platform)s?(?:_|$)"
)


class Violation(NamedTuple):
    """One breach of the placement rule, at one line."""

    path: Path
    line: int
    rule: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.message}"


def editorial_core_modules(root: Path) -> list[Path]:
    """Every module under ``root``.

    A missing root is an error, not an empty result: a check that silently
    passes because it looked nowhere is worse than no check.
    """

    if not root.is_dir():
        raise FileNotFoundError(f"editorial-core root not found: {root}")
    return sorted(root.rglob("*.py"))


def check_tree(root: Path) -> list[Violation]:
    """Check every module under ``root``."""

    violations: list[Violation] = []
    for path in editorial_core_modules(root):
        violations.extend(check_module(path))
    return violations


def check_module(path: Path) -> list[Violation]:
    """Check one module."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _clock_violations(path, tree) + _destination_violations(path, tree)


# ---------------------------------------------------------------------------
# CE1-CLOCK
# ---------------------------------------------------------------------------


def _clock_violations(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    reported: set[tuple[int, int]] = set()
    aliases = _clock_aliases(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node)
        if name is None:
            continue
        original = name if name in _CLOCK_CALLS else aliases.get(name)
        if original is None:
            continue
        bound = "" if original == name else f", which is bound to {original}()"
        reported.add((node.func.lineno, node.func.col_offset))
        violations.append(Violation(
            path, node.lineno, "CE1-CLOCK",
            f"editorial-core code calls {name}(){bound}: a stage is given its "
            "inputs. The weekday and the clock are scheduling inputs, and "
            "timestamps are stamped by the run harness in src/run/",
        ))

    prose = _prose_nodes(tree)
    for node in ast.walk(tree):
        found = _weekday_word(node, prose)
        if found is None:
            continue
        line, column, word = found
        if (line, column) in reported:
            continue  # already reported as a clock call
        violations.append(Violation(
            path, line, "CE1-CLOCK",
            f"editorial-core code uses the weekday vocabulary {word!r}: the "
            "day a run happens on is a scheduling input, not something a "
            "stage decides by",
        ))

    return sorted(violations, key=lambda violation: (violation.line, violation.message))


def _called_name(node: ast.Call) -> Optional[str]:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _clock_aliases(tree: ast.Module) -> dict[str, str]:
    """Local names that stand for a clock reader, as ``alias -> original``.

    A call site is a spelling, and a spelling can be chosen: ``from time
    import time as read_clock`` renames the clock on the way in and
    ``read_clock = time.time`` renames it afterwards, both leaving a call the
    vocabulary alone would not recognise. Following the binding is what makes
    the rule about what a name refers to rather than how it is typed.
    """

    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for imported in node.names:
                if imported.asname and imported.name in _CLOCK_CALLS:
                    aliases[imported.asname] = imported.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if node.value is None:
                continue
            original = _clock_reference(node.value, aliases)
            if original is None:
                continue
            targets: list[ast.expr] = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            for target in targets:
                if isinstance(target, ast.Name):
                    aliases[target.id] = original
    return aliases


def _clock_reference(node: ast.expr, aliases: dict[str, str]) -> Optional[str]:
    """The clock reader this expression names, directly or through an alias."""

    if isinstance(node, ast.Attribute) and node.attr in _CLOCK_CALLS:
        return node.attr
    if isinstance(node, ast.Name):
        if node.id in _CLOCK_CALLS:
            return node.id
        return aliases.get(node.id)
    return None


def _weekday_word(node: ast.AST, prose: set[int]) -> Optional[tuple[int, int, str]]:
    """The weekday token this node carries, with its position, if any."""

    text: Optional[str] = None
    position: Optional[tuple[int, int]] = None
    if isinstance(node, ast.Name):
        text, position = node.id, (node.lineno, node.col_offset)
    elif isinstance(node, ast.Attribute):
        text, position = node.attr, (node.lineno, node.col_offset)
    elif isinstance(node, ast.arg):
        text, position = node.arg, (node.lineno, node.col_offset)
    elif (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in prose
    ):
        text, position = node.value, (node.lineno, node.col_offset)
    if text is None or position is None:
        return None
    match = _WEEKDAY_WORDS.search(text)
    if match is None:
        return None
    return position[0], position[1], match.group(0)


def _prose_nodes(tree: ast.Module) -> set[int]:
    """String constants that are bare expressions: docstrings and the like.

    A module that explains the rule it obeys must be able to name the weekday
    while doing so.
    """

    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


# ---------------------------------------------------------------------------
# CE1-DESTINATION
# ---------------------------------------------------------------------------


def _destination_violations(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    values = _destination_values(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            violations.extend(_branch_violations(
                path, node.test, [node.body, node.orelse], values))
        elif isinstance(node, ast.IfExp):
            violations.extend(_branch_violations(
                path, node.test, [[node.body], [node.orelse]], values))
        elif isinstance(node, ast.Match):
            subject = _destination_name(node.subject, values)
            for case in node.cases:
                discriminator = subject or _destination_name(case.pattern, values)
                if discriminator is None:
                    continue
                violations.extend(_selection_violations(
                    path, discriminator, [case.body]))
        elif isinstance(node, ast.Dict):
            violations.extend(_table_violations(path, node, values))

    return sorted(violations, key=lambda violation: (violation.line, violation.message))


def _branch_violations(
    path: Path, test: ast.AST, branches: Iterable[list[Any]], values: set[str]
) -> list[Violation]:
    destination = _destination_name(test, values)
    if destination is None:
        return []
    return _selection_violations(path, destination, branches)


def _selection_violations(
    path: Path, destination: str, branches: Iterable[list[Any]]
) -> list[Violation]:
    violations: list[Violation] = []
    for branch in branches:
        found = _first_stage_reference(branch)
        if found is None:
            continue
        line, reference = found
        violations.append(Violation(
            path, line, "CE1-DESTINATION",
            f"a branch on {destination} selects {reference}: "
            "a destination may not decide which stages run. "
            "Destination-specific behaviour belongs in destination knowledge "
            "(K-DST-*), adaptation (S-10), check records and the publishers",
        ))
    return violations


def _table_violations(path: Path, node: ast.Dict, values: set[str]) -> list[Violation]:
    violations: list[Violation] = []
    for key, value in zip(node.keys, node.values):
        if key is None:  # a ``**other`` entry has no key
            continue
        destination = _destination_name(key, values)
        if destination is None:
            continue
        found = _first_stage_reference([value])
        if found is None:
            continue
        line, stage = found
        violations.append(Violation(
            path, line, "CE1-DESTINATION",
            f"a table keyed by {destination} names {stage}: "
            "the stages a run executes come from the topology registry, not "
            "from a per-destination table",
        ))
    return violations


def _destination_values(tree: ast.Module) -> set[str]:
    """Local names that hold a destination, as parameters or by binding.

    The destination reaches a module as a value, and a value can be renamed:
    ``def plan(destination)`` brings one in and ``chosen = destination`` passes
    it on, each leaving a branch that selects per destination without a
    destination appearing anywhere in it. Following the value is to the
    destination rule what :func:`_clock_aliases` is to the clock — it makes
    the rule about what is branched on rather than how it is spelled.
    """

    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            if _DESTINATION_VALUE.search(node.arg):
                values.add(node.arg)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if node.value is None or _destination_name(node.value, values) is None:
                continue
            targets: list[ast.expr] = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            for target in targets:
                if isinstance(target, ast.Name):
                    values.add(target.id)
    return values


def _destination_name(node: Optional[ast.AST], values: set[str]) -> Optional[str]:
    """How this expression names a destination, if it does.

    Three spellings, one branch: the destination written out (``"telegram"``,
    ``Channel.TELEGRAM``), a name the destination travels under
    (``destination``, ``enabled_destinations``), and a name bound to one of
    those. Without the last two, a branch that selects stages per destination
    passes untouched as long as it never mentions a surface — which is the
    easiest way to write the breach, not the hardest.

    Returns the phrase a violation message reads the branch back as, so that
    every spelling says what was branched on. A written-out destination wins,
    because naming the surface says more than naming the variable it sits in.
    """

    if node is None:
        return None
    named = _named_destination(node)
    if named is not None:
        return f"the destination {named!r}"
    holder = _destination_holder(node, values)
    if holder is not None:
        return f"the destination in {holder!r}"
    return None


def _named_destination(node: ast.AST) -> Optional[str]:
    """The destination this expression writes out, if it writes one out."""

    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            candidate = child.value.strip().lower()
            if candidate in DESTINATION_NAMES:
                return candidate
        elif isinstance(child, ast.Attribute) and child.attr.lower() in DESTINATION_NAMES:
            return child.attr.lower()
    return None


def _destination_holder(node: ast.AST, values: set[str]) -> Optional[str]:
    """The value this expression reads a destination out of, if any.

    Only a lower-case name counts as the vocabulary: ``destination`` and
    ``plan.enabled_destinations`` are values in flight, while
    ``StageScope.DESTINATION`` and ``TerminalOutcome.SKIP_DESTINATION`` are
    the registry's own words for a scope and an outcome, and reading the
    topology is the opposite of branching around it. A destination written
    into an enum member (``Channel.TELEGRAM``) is caught before this, by name.
    """

    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            if not child.attr.isupper() and _DESTINATION_VALUE.search(child.attr):
                return child.attr
        elif isinstance(child, ast.Name):
            if child.id in values:
                return child.id
            if not child.id.isupper() and _DESTINATION_VALUE.search(child.id):
                return child.id
    return None


def _first_stage_reference(nodes: Iterable[Any]) -> Optional[tuple[int, str]]:
    """The first stage selection in these nodes, as (line, what it named).

    Either a stage named outright (``"S-10"``, ``Stage.S_10``) or a name that
    holds the stage sequence (``stages``, ``CANONICAL_TOPOLOGY.stage_ids``).
    Reaching the topology through a variable is still reaching the topology:
    ``return stages[:2]`` under a destination branch cuts the engine in two as
    surely as a list of stage identifiers does.
    """

    for root in nodes:
        for child in ast.walk(root):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if _STAGE_LITERAL.match(child.value):
                    return child.lineno, child.value
            elif isinstance(child, ast.Attribute):
                if _STAGE_MEMBER.match(child.attr):
                    return child.lineno, child.attr.replace("_", "-")
                if _STAGE_SEQUENCE.search(child.attr):
                    return child.lineno, child.attr
            elif isinstance(child, ast.Name):
                if _STAGE_MEMBER.match(child.id):
                    return child.lineno, child.id.replace("_", "-")
                if _STAGE_SEQUENCE.search(child.id):
                    return child.lineno, child.id
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root", action="append", type=Path,
        help=f"editorial-core root to check; repeatable (default: {DEFAULT_ROOT})",
    )
    args = parser.parse_args(argv)
    roots: list[Path] = args.root or [DEFAULT_ROOT]

    violations: list[Violation] = []
    checked = 0
    for root in roots:
        try:
            modules = editorial_core_modules(root)
        except FileNotFoundError as exc:
            print(str(exc))
            print("\nresult: CE-1 PLACEMENT RULE NOT CHECKED")
            return 1
        checked += len(modules)
        for module in modules:
            violations.extend(check_module(module))

    print(f"CE-1 placement rule: {checked} editorial-core module(s) checked")

    if violations:
        print(f"\n{len(violations)} violation(s):")
        for violation in violations:
            print(f"  {violation.render()}")
        print("\nresult: CE-1 PLACEMENT VIOLATION")
        return 1

    print("result: no weekday or destination pipeline in the editorial core")
    return 0


if __name__ == "__main__":
    sys.exit(main())
