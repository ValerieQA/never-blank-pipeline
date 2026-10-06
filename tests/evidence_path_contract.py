"""Does an ``upload-artifact`` path input stay inside the canonical namespace?

#326, second review of PR #388. The first attempt checked this lexically — the
value had to *contain* ``reports/content_packages/`` and ``/runs/`` and not
contain ``..``, ``~``, ``*`` or ``.env``. That is not the invariant.
``upload-artifact`` accepts a **newline-separated list** of paths, so a value
can satisfy every one of those substring checks and still upload a second,
unrelated tree:

    reports/content_packages/${{ ... }}/runs/
    reports/

So this module parses instead of matching, and **fails closed**: a shape it does
not recognise is a rejection, never a pass. The forms it recognises are the ones
the surviving publishing workflows actually use, and nothing more:

* a **literal** entry — ``reports/content_packages/<segment>/runs/`` or
  ``reports/content_packages/<segment>_generated.json``, where ``<segment>`` is
  one path segment: a GitHub expression, or a plain token with no separator;
* a whole-entry **expression**, whose ``||`` alternatives are each either a
  ``format('<template>', …)`` whose template is one of those literal forms, or a
  **step output that this repository proves emits only those forms**. An output
  nobody proved is a rejection — the alternative's value is not knowable from
  the workflow, so the proof has to live beside its emitter.

What containment means here, exactly, and its one limit: every entry resolves
under ``reports/content_packages/`` and names a single signal's run namespace or
its generated package. It does **not** prove that a *signal id* is itself free of
traversal — ``scripts/streams/run_first_valid.py`` interpolates ids without a
charset guard, which is production code this slice may not change.
:func:`tests.test_story21_hosted_evidence.test_the_evidence_emitter_builds_only_canonical_entries`
pins the guarantee that does hold, and the gap is reported on #326 rather than
hidden behind a test that would read as proving more than it does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Where every content package lives. Nothing may be uploaded from outside it.
PACKAGES_ROOT = "reports/content_packages"

#: One path segment, and it must be **derived from the run**: a GitHub
#: expression — which cannot contain ``/`` or ``}``, so it can never silently
#: become two segments — or a ``format`` placeholder.
#:
#: A plain token is deliberately **not** accepted here, and that is the second
#: review's own example caught: ``reports/content_packages/other/runs/`` is
#: canonical in shape while naming a signal this run never attempted. A signal
#: id fixed when the workflow was written cannot be this run's, so a literal
#: segment is a widening even though it looks like a containment.
_SEGMENT = r"(?:\$\{\{[^}/]*\}\}|\{\d+\})"

#: The two canonical entry forms, anchored. A run namespace, or the generated
#: package beside it — the two things a publishing workflow preserves.
_RUN_NAMESPACE = re.compile(rf"^{PACKAGES_ROOT}/{_SEGMENT}/runs/?$")
_GENERATED_PACKAGE = re.compile(rf"^{PACKAGES_ROOT}/{_SEGMENT}_generated\.json$")

#: Characters that make a path mean more than one place, or another place.
_DANGEROUS = ("..", "~", "*", "?", "[", "$(", "`", ".env", "//")

#: A whole-entry expression: ``${{ … }}`` and nothing else around it.
_WHOLE_EXPRESSION = re.compile(r"^\$\{\{(?P<body>.+)\}\}$", re.S)

#: ``format('template', arg, …)`` — the template is what must be canonical.
_FORMAT = re.compile(r"^format\(\s*'(?P<template>[^']*)'\s*(?:,.*)?\)$", re.S)

#: ``steps.<id>.outputs.<name>``.
_STEP_OUTPUT = re.compile(r"^steps\.(?P<step>[A-Za-z0-9_-]+)\.outputs\.(?P<name>[A-Za-z0-9_-]+)$")

#: Step outputs whose emitter this repository proves canonical, and where the
#: proof is. An output absent from here is rejected: a value the workflow cannot
#: state must be proved where it is produced, or it is not proved at all.
PROVEN_OUTPUTS = {
    "evidence_paths": "scripts/streams/run_first_valid.py::_emit_evidence_paths",
}


class PathContractError(AssertionError):
    """The path input is not provably inside the canonical namespace."""


@dataclass(frozen=True, slots=True)
class Accepted:
    """What a parsed path input was found to consist of."""

    literals: tuple[str, ...]
    formats: tuple[str, ...]
    proven_outputs: tuple[str, ...]

    @property
    def total(self) -> int:
        return len(self.literals) + len(self.formats) + len(self.proven_outputs)


def assert_contained(value: str, *, where: str) -> Accepted:
    """Prove every path ``value`` can yield is inside the canonical namespace.

    Raises :class:`PathContractError` naming ``where`` and the offending entry.
    Returns what was accepted, so a caller can assert it was not nothing.
    """

    entries = [line.strip() for line in str(value).splitlines()]
    entries = [entry for entry in entries if entry]
    if not entries:
        raise PathContractError(f"{where}: uploads no path at all")

    literals: list[str] = []
    formats: list[str] = []
    outputs: list[str] = []

    for entry in entries:
        for token in _DANGEROUS:
            if token in entry:
                raise PathContractError(
                    f"{where}: entry {entry!r} contains {token!r}, which can "
                    "name a place other than this run's own"
                )
        expression = _WHOLE_EXPRESSION.match(entry)
        if expression is None:
            if not _canonical(entry):
                raise PathContractError(
                    f"{where}: literal entry {entry!r} is not a canonical run "
                    f"namespace or generated package under {PACKAGES_ROOT}/"
                )
            literals.append(entry)
            continue
        for alternative in _alternatives(expression.group("body"), where=where):
            kind, text = alternative
            (formats if kind == "format" else outputs).append(text)

    return Accepted(tuple(literals), tuple(formats), tuple(outputs))


def _canonical(entry: str) -> bool:
    return bool(_RUN_NAMESPACE.match(entry) or _GENERATED_PACKAGE.match(entry))


def _alternatives(body: str, *, where: str) -> list[tuple[str, str]]:
    """Each ``||`` alternative of an expression, classified or rejected."""

    found: list[tuple[str, str]] = []
    for raw in body.split("||"):
        alternative = raw.strip()
        if not alternative:
            raise PathContractError(f"{where}: empty expression alternative")

        matched = _FORMAT.match(alternative)
        if matched is not None:
            template = matched.group("template")
            if not _canonical(template):
                raise PathContractError(
                    f"{where}: format template {template!r} is not a canonical "
                    f"entry under {PACKAGES_ROOT}/"
                )
            found.append(("format", template))
            continue

        output = _STEP_OUTPUT.match(alternative)
        if output is not None:
            name = output.group("name")
            if name not in PROVEN_OUTPUTS:
                raise PathContractError(
                    f"{where}: alternative {alternative!r} is a step output "
                    "whose entries nothing in this repository proves canonical. "
                    "Prove it beside its emitter and add it to PROVEN_OUTPUTS, "
                    "or upload a literal path"
                )
            found.append(("output", name))
            continue

        raise PathContractError(
            f"{where}: alternative {alternative!r} is a shape this contract "
            "does not recognise, so nothing about where it points is proved"
        )
    return found
