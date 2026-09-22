#!/usr/bin/env python3
"""Validate the knowledge register in CI (Issue #294, Step 4 §8).

§8 says the validator runs "in CI on every change to `knowledge/` and to the client
folders' rule files, and again at run start". This is the CI half; the run-start
half is `src/knowledge/run_start.py`, and both call the same
`validate_register` — one validator, two callers, no rule that only one of them
applies.

Run it directly::

    python3 scripts/ci/check_knowledge_register.py
    python3 scripts/ci/check_knowledge_register.py --baseline-ref origin/main

or through `tests/test_294_knowledge_register.py`, which is what puts it in CI.

**The baseline.** Rule 7 has a half that no single tree can answer: whether
`version` went up when the body changed. That needs the tree as it was, so the
script reads it from git — every record in `<ref>:knowledge/`, by id, with the
digest of the surface a version bump has to cover. Without a usable ref that half
is **skipped and said to be skipped**: a check that quietly compared a record with
itself would report a clean tree it never examined.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from src.knowledge.markdown import DocumentError, parse_document
from src.knowledge.validator import (
    CHECKS_DIR_NAME,
    LADDERS_DIR_NAME,
    RECORDS_DIR_NAME,
    RULES,
    Finding,
    RecordBaseline,
    validate_register,
)

#: The register, and the client directories whose rule files carry a ladder.
DEFAULT_REGISTER = Path("knowledge")
DEFAULT_CLIENTS = Path("clients")

#: Where an identified record can live inside the register.
_IDENTIFIED_DIRS = (RECORDS_DIR_NAME, CHECKS_DIR_NAME, LADDERS_DIR_NAME)


def client_rule_paths(clients_dir: Path) -> tuple[Path, ...]:
    """Every client stream contract: the file a client ladder is declared in."""

    if not clients_dir.is_dir():
        return ()
    return tuple(sorted(clients_dir.glob("*/streams/*.md")))


def build_baseline(
    ref: str, register_dir: Path
) -> Optional[dict[str, RecordBaseline]]:
    """Each record in `<ref>:<register_dir>`, by id. ``None`` when git cannot."""

    listing = _git("ls-tree", "-r", "--name-only", ref, "--", str(register_dir))
    if listing is None:
        return None
    baseline: dict[str, RecordBaseline] = {}
    for name in listing.splitlines():
        path = Path(name.strip())
        if path.suffix != ".md" or not _is_identified(path, register_dir):
            continue
        blob = _git("show", f"{ref}:{path}")
        if blob is None:
            continue
        try:
            document = parse_document(blob, str(path))
        except DocumentError:
            # It did not parse then either. Whatever is wrong with it now is the
            # current tree's business, and the ten rules will say so.
            continue
        identity = document.field("id")
        version = document.field("version")
        if not identity or version is None or not version.isdigit():
            continue
        baseline[identity] = RecordBaseline(
            version=int(version),
            version_surface_digest=document.version_surface_digest(),
        )
    return baseline


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--register", type=Path, default=DEFAULT_REGISTER,
        help="the knowledge register (default: knowledge)",
    )
    parser.add_argument(
        "--clients", type=Path, default=DEFAULT_CLIENTS,
        help="the client directories whose stream contracts declare a ladder",
    )
    parser.add_argument(
        "--baseline-ref", default="",
        help=(
            "a git ref holding the register before this change, for rule 7's "
            "version-increase half (for example origin/main)"
        ),
    )
    arguments = parser.parse_args(argv)

    baseline = None
    if arguments.baseline_ref:
        baseline = build_baseline(arguments.baseline_ref, arguments.register)
        if baseline is None:
            print(
                f"note: {arguments.baseline_ref} is not readable here, so rule 7's "
                "version-increase half was NOT checked. Every other rule was.",
                file=sys.stderr,
            )

    findings = validate_register(
        arguments.register,
        client_rule_paths=client_rule_paths(arguments.clients),
        baseline=baseline,
    )
    return report(findings, register=arguments.register)


def report(findings: Sequence[Finding], *, register: Path) -> int:
    """Print what was found, and return the exit status."""

    if not findings:
        print(f"{register}: the knowledge register is valid.")
        return 0

    rules = dict(RULES)
    print(f"{register}: the knowledge register is REFUSED.\n", file=sys.stderr)
    for finding in findings:
        print(finding.render(), file=sys.stderr)
    print("", file=sys.stderr)
    for rule in sorted({finding.rule for finding in findings}):
        print(f"{rule}: {rules.get(rule, '')}", file=sys.stderr)
    print(
        "\nFix the file, not the check: a run started on this register would "
        "SKIP at signal scope with the reason knowledge_register_invalid.",
        file=sys.stderr,
    )
    return 1


def _is_identified(path: Path, register_dir: Path) -> bool:
    try:
        relative = path.relative_to(register_dir)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] in _IDENTIFIED_DIRS


def _git(*arguments: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", *arguments], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


if __name__ == "__main__":
    raise SystemExit(main())
