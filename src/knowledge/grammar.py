"""The `Applies when` controlled grammar (Step 4 §4).

A condition is one short line of controlled English that code parses and a person
reads::

    always
    destination is linkedin
    feature documented_case is yes and not (destination is telegram)
    boundary has at least 2 admissible_interpretations
    strategy reveal is delayed or strategy concession is present

Term families, each drawing its names and values from `knowledge/vocab/`:

===============================================  =========================
`feature <name> is <value>`                      E-05 material features
`boundary has <fact>`                            E-09 facts code computes
`boundary has at least <n> <fact>`               the countable ones
`destination is <name>`                          E-12
`format is <name>`                               E-14
`strategy <field> is <value>`                    E-13, S-09…S-13 only
`audience <attribute> is <value>`                the Audience Profile
`always`                                         —
===============================================  =========================

Connectives are `and`, `or`, `not` and parentheses. `and` binds tighter than
`or`, so `a or b and c` is `a or (b and c)`; a condition that means something else
says so with parentheses.

**Two things this grammar cannot express, on purpose.**

*Labels.* There is no term for a label, so no record can be conditioned on one.
That is how Q4 / I-10 is enforced at the source rather than promised: the parser
refuses every term in `knowledge/vocab/labels.md`, however it is spelt, and says
which term did it.

*Free text.* Anything outside the grammar is a parse error. A condition nobody can
evaluate is worse than no condition, because it would be quietly true or quietly
false at the stage that reads it.

**Who evaluates it.** Code, at the stage the record influences, against the entity
versions that stage reads — never a model (§4, "Time of evaluation"). This module
parses; the loader that evaluates arrives with the stage that reads it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Optional

from src.knowledge.vocabulary import Term, Vocabularies, Vocabulary

#: Term families, as they are written.
FEATURE: Final[str] = "feature"
BOUNDARY: Final[str] = "boundary"
DESTINATION: Final[str] = "destination"
FORMAT: Final[str] = "format"
STRATEGY: Final[str] = "strategy"
AUDIENCE: Final[str] = "audience"

#: Which vocabulary each family draws on.
_FAMILY_VOCABULARY: Final[dict[str, str]] = {
    FEATURE: "features",
    BOUNDARY: "boundary_facts",
    DESTINATION: "destinations",
    FORMAT: "formats",
    STRATEGY: "strategy_fields",
    AUDIENCE: "audience_attributes",
}

#: The stages a strategy term may be read at (§4). Before S-09 no strategy has
#: been chosen, so a condition on one could only ever be false.
STRATEGY_TERM_STAGES: Final[tuple[str, ...]] = (
    "S-09", "S-10", "S-11", "S-12", "S-13",
)

_WORD = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.]*")
_INTEGER = re.compile(r"^\d+$")

_CONNECTIVES: Final[frozenset[str]] = frozenset({"and", "or", "not"})


class ConditionError(ValueError):
    """The condition does not parse, or uses a term it may not use."""


class Condition:
    """One parsed `Applies when` line, or a part of one."""

    def atoms(self) -> tuple["Atom", ...]:
        """Every term in this condition, in the order they were written."""

        raise NotImplementedError  # pragma: no cover - abstract


@dataclass(frozen=True)
class Always(Condition):
    """`always`: the record applies wherever it is eligible."""

    def atoms(self) -> tuple["Atom", ...]:
        return ()


@dataclass(frozen=True)
class Atom(Condition):
    """One term: a family, the vocabulary term, and what it is compared to."""

    family: str
    name: str
    value: Optional[str] = None
    #: Set for `boundary has at least <n> <fact>`.
    minimum: Optional[int] = None
    #: How the term was written, for an error message a person can act on.
    text: str = ""

    def atoms(self) -> tuple["Atom", ...]:
        return (self,)


@dataclass(frozen=True)
class Not(Condition):
    operand: Condition

    def atoms(self) -> tuple["Atom", ...]:
        return self.operand.atoms()


@dataclass(frozen=True)
class And(Condition):
    operands: tuple[Condition, ...]

    def atoms(self) -> tuple["Atom", ...]:
        return tuple(atom for operand in self.operands for atom in operand.atoms())


@dataclass(frozen=True)
class Or(Condition):
    operands: tuple[Condition, ...]

    def atoms(self) -> tuple["Atom", ...]:
        return tuple(atom for operand in self.operands for atom in operand.atoms())


def parse_condition(line: str, vocabularies: Vocabularies) -> Condition:
    """Parse one `Applies when` line. Raises :class:`ConditionError`."""

    condition = " ".join(line.split())
    if not condition:
        raise ConditionError(
            "`## Applies when` is empty; a record that applies everywhere says "
            "`always`"
        )

    label = _label_term_used(condition, vocabularies.get("labels"))
    if label is not None:
        raise ConditionError(
            f"the condition uses the label `{label}`. No record may be "
            "conditioned on a label (I-10): labels are written after the "
            "decision and never reach S-00…S-13. Condition on the features in "
            "features.md or the strategy fields in strategy_fields.md instead"
        )

    parser = _Parser(_tokenize(condition), vocabularies)
    parsed = parser.parse()
    if isinstance(parsed, Always):
        return parsed
    if any(isinstance(part, Always) for part in _walk(parsed)):
        raise ConditionError(
            "`always` is the whole condition or none of it; it cannot be joined "
            "to a term"
        )
    return parsed


def strategy_atoms(condition: Condition) -> tuple[Atom, ...]:
    """The strategy terms in a condition, which only S-09…S-13 may read."""

    return tuple(atom for atom in condition.atoms() if atom.family == STRATEGY)


class _Parser:
    """Recursive descent over the token list. Small grammar, small parser."""

    def __init__(self, tokens: tuple[str, ...], vocabularies: Vocabularies) -> None:
        self._tokens = tokens
        self._vocabularies = vocabularies
        self._at = 0

    def parse(self) -> Condition:
        condition = self._or()
        if self._at != len(self._tokens):
            raise ConditionError(
                f"{self._tokens[self._at]!r} is left over at the end of the "
                "condition; `and`, `or` and `not` are the only ways to join terms"
            )
        return condition

    def _or(self) -> Condition:
        operands = [self._and()]
        while self._peek() == "or":
            self._advance()
            operands.append(self._and())
        return operands[0] if len(operands) == 1 else Or(tuple(operands))

    def _and(self) -> Condition:
        operands = [self._unary()]
        while self._peek() == "and":
            self._advance()
            operands.append(self._unary())
        return operands[0] if len(operands) == 1 else And(tuple(operands))

    def _unary(self) -> Condition:
        if self._peek() == "not":
            self._advance()
            return Not(self._unary())
        if self._peek() == "(":
            self._advance()
            inner = self._or()
            if self._peek() != ")":
                raise ConditionError("a `(` in the condition is never closed")
            self._advance()
            return inner
        return self._term()

    def _term(self) -> Condition:
        head = self._take("a term")
        if head == "always":
            return Always()
        if head == BOUNDARY:
            return self._boundary_term()
        if head in (DESTINATION, FORMAT):
            self._expect("is", head)
            value = self._take(f"a {head} after `{head} is`")
            self._known_term(head, value)
            return Atom(family=head, name=value, text=f"{head} is {value}")
        if head in (FEATURE, STRATEGY, AUDIENCE):
            name = self._take(f"a name after `{head}`")
            self._expect("is", f"{head} {name}")
            value = self._take(f"a value after `{head} {name} is`")
            term = self._known_term(head, name)
            if value not in term.values:
                raise ConditionError(
                    f"`{head} {name}` cannot be {value!r}; "
                    f"{self._vocabulary(head).path} declares "
                    f"{' / '.join(term.values) or 'no values for it'}"
                )
            return Atom(
                family=head, name=name, value=value, text=f"{head} {name} is {value}"
            )
        raise ConditionError(
            f"{head!r} starts no term the grammar has. Terms start with "
            f"{', '.join(sorted(_FAMILY_VOCABULARY))} or `always`"
        )

    def _boundary_term(self) -> Condition:
        self._expect("has", BOUNDARY)
        minimum: Optional[int] = None
        if self._peek() == "at":
            self._take()
            self._expect("least", "boundary has at")
            count = self._take("a number after `boundary has at least`")
            if not _INTEGER.match(count):
                raise ConditionError(
                    f"`boundary has at least {count}` needs a whole number, not "
                    f"{count!r}"
                )
            minimum = int(count)
            if minimum < 1:
                raise ConditionError(
                    "`boundary has at least 0 …` is true of every boundary; say "
                    "what the boundary must actually have"
                )
        fact = self._take("a boundary fact after `boundary has`")
        term = self._known_term(BOUNDARY, _singular(fact))
        if minimum is not None and not term.countable:
            raise ConditionError(
                f"`{term.name}` is a fact the boundary has or has not, so it "
                f"cannot be counted; {self._vocabulary(BOUNDARY).path} marks the "
                "countable facts `<count>`"
            )
        text = (
            f"boundary has at least {minimum} {fact}"
            if minimum is not None
            else f"boundary has {fact}"
        )
        return Atom(family=BOUNDARY, name=term.name, minimum=minimum, text=text)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _vocabulary(self, family: str) -> Vocabulary:
        return self._vocabularies.get(_FAMILY_VOCABULARY[family])

    def _known_term(self, family: str, name: str) -> Term:
        vocabulary = self._vocabulary(family)
        term = vocabulary.term(name)
        if term is None:
            raise ConditionError(
                f"`{name}` is not a term of {vocabulary.path}. A new term and "
                "the code that gives it meaning ship together (§10)"
            )
        return term

    def _peek(self) -> Optional[str]:
        return self._tokens[self._at] if self._at < len(self._tokens) else None

    def _advance(self) -> str:
        """Consume the token `_peek` has already identified.

        Connectives and parentheses are structure, not words of a term, so they
        are consumed here rather than through :meth:`_take`, which exists to
        refuse exactly them where a term's own words were needed.
        """

        token = self._tokens[self._at]
        self._at += 1
        return token

    def _take(self, expected: str = "another word") -> str:
        token = self._peek()
        if token is None:
            raise ConditionError(f"the condition ends where {expected} was needed")
        if token in _CONNECTIVES or token in ("(", ")"):
            raise ConditionError(
                f"{token!r} appears where {expected} was needed"
            )
        self._at += 1
        return token

    def _expect(self, word: str, after: str) -> None:
        token = self._peek()
        if token != word:
            got = repr(token) if token is not None else "the end of the condition"
            raise ConditionError(f"`{after}` must be followed by `{word}`; got {got}")
        self._at += 1


def _walk(condition: Condition) -> tuple[Condition, ...]:
    if isinstance(condition, Not):
        return (condition, *_walk(condition.operand))
    if isinstance(condition, (And, Or)):
        return (
            condition,
            *(part for operand in condition.operands for part in _walk(operand)),
        )
    return (condition,)


def _tokenize(condition: str) -> tuple[str, ...]:
    tokens: list[str] = []
    at = 0
    while at < len(condition):
        character = condition[at]
        if character.isspace():
            at += 1
            continue
        if character in "()":
            tokens.append(character)
            at += 1
            continue
        match = _WORD.match(condition, at)
        if match is None:
            raise ConditionError(
                f"{character!r} is not part of the condition grammar; a "
                "condition is words, numbers and parentheses only"
            )
        tokens.append(match.group(0))
        at = match.end()
    if not tokens:
        raise ConditionError("the condition has no terms")
    return tuple(tokens)


def _singular(fact: str) -> str:
    """`admissible_interpretations` and `…interpretation` are one fact.

    The vocabulary declares countable facts in the singular; a person counting
    them writes the plural, and both spell the same term.
    """

    if fact.endswith("ies"):
        return fact[:-3] + "y"
    if fact.endswith("s") and not fact.endswith("ss"):
        return fact[:-1]
    return fact


def _label_term_used(condition: str, labels: Vocabulary) -> Optional[str]:
    """The label term this condition uses, if any — however it is spelt.

    `material_label`, `Material Label` and `material label` are one term, and so
    are `Post-mortem` and `post_mortem`. The words have to be there, in order,
    separated by nothing but spaces, underscores or hyphens — which is why
    `feature real_scene is yes` is not the label `Scene`.
    """

    for term in labels.terms:
        words = [part for part in re.split(r"[^A-Za-z0-9]+", term.name) if part]
        if not words:
            continue
        pattern = r"\b" + r"[\s_\-]+".join(re.escape(word) for word in words) + r"\b"
        if re.search(pattern, condition, re.IGNORECASE):
            return term.name
    return None
