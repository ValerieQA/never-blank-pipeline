#!/usr/bin/env python3
"""Fail-closed comparator between a pytest run and the accepted failure baseline.

Purpose
-------
CI runs the complete pytest suite and persists its terminal output to a file.
This script compares the exact set of failed test node IDs observed in that
output against a version-controlled baseline of accepted failures
(``tests/accepted_full_suite_failures.txt``). The GitHub check is green only
when the two sets are strictly equal.

Why terminal output parsing
---------------------------
pytest's built-in machine-readable format (``--junitxml``) emits only dotted
``classname``/``name`` attributes, from which exact pytest node IDs cannot be
reconstructed unambiguously (the module-path/class boundary is lossy), and
JSON report output requires an extra plugin dependency. The short test summary
(``-rfE``) lines are therefore parsed instead, with the following fail-closed
guarantees:

- the persisted output must contain a final pytest summary counts line;
  otherwise the run is treated as unparseable and the script exits non-zero;
- the number of parsed FAILED/ERROR node IDs must equal the failed/error
  counts declared by that summary line; any mismatch exits non-zero;
- an empty or unreadable output file is never interpreted as a successful
  zero-failure run;
- a pytest exit status indicating interruption, internal error, usage error,
  or no-tests-collected (anything other than 0 or 1) must be handled by the
  workflow before this script runs; this script additionally rejects output
  that contains no summary line at all.

Baseline semantics
------------------
- one exact pytest node ID per line; blank lines are ignored;
- duplicate entries are rejected, not silently normalized;
- no wildcards, prefixes, counts, regex allowances, or failure classes;
- NEW failures (observed, not in baseline) and RESOLVED failures (in
  baseline, not observed) are reported separately; either exits non-zero.

Any baseline modification requires explicit review — never edit the baseline
merely to make CI green.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Final pytest summary line, e.g.:
#   "16 failed, 1194 passed, 17 skipped, 2 warnings in 47.98s"
#   "1200 passed in 45.12s"
#   "5 failed, 3 errors in 1.20s"
_SUMMARY_TOKEN = re.compile(r"(\d+) (failed|passed|skipped|error|errors|warning|warnings|deselected|xfailed|xpassed)\b")
_SUMMARY_LINE = re.compile(
    r"^=*\s*(?:\x1b\[[0-9;]*m)*\s*"
    r"(?P<body>\d+ (?:failed|passed|error|errors)\b[^=]*?in [0-9.]+s(?: \([^)]*\))?)"
)
_RESULT_LINE = re.compile(r"^(FAILED|ERROR) (?P<rest>.+)$")


def parse_baseline(path: Path) -> set[str]:
    if not path.is_file():
        sys.exit(f"baseline file not found: {path}")
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        entries.append(line)
    duplicates = sorted({entry for entry in entries if entries.count(entry) > 1})
    if duplicates:
        sys.exit(
            "baseline contains duplicate entries (rejected, not normalized):\n  "
            + "\n  ".join(duplicates)
        )
    return set(entries)


def parse_pytest_output(path: Path) -> set[str]:
    if not path.is_file():
        sys.exit(f"pytest output file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        sys.exit("pytest output file is empty; refusing to treat as zero failures")

    observed: set[str] = set()
    for raw in text.splitlines():
        match = _RESULT_LINE.match(raw.strip())
        if not match:
            continue
        # "FAILED <nodeid>" or "FAILED <nodeid> - <short reason>"
        node_id = match.group("rest").split(" - ", 1)[0].strip()
        if node_id:
            observed.add(node_id)

    summary_counts: dict[str, int] | None = None
    for raw in reversed(text.splitlines()):
        line = raw.strip()
        match = _SUMMARY_LINE.match(line)
        if match:
            summary_counts = {}
            for count, kind in _SUMMARY_TOKEN.findall(match.group("body")):
                summary_counts[kind.rstrip("s")] = summary_counts.get(kind.rstrip("s"), 0) + int(count)
            break
    if summary_counts is None:
        sys.exit(
            "no pytest summary counts line found in output; "
            "refusing to interpret the run (fail closed)"
        )

    declared = summary_counts.get("failed", 0) + summary_counts.get("error", 0)
    if declared != len(observed):
        sys.exit(
            f"summary line declares {declared} failed/error tests but "
            f"{len(observed)} FAILED/ERROR node IDs were parsed; "
            "output cannot be interpreted reliably (fail closed)"
        )
    return observed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="persisted pytest terminal output")
    args = parser.parse_args()

    baseline = parse_baseline(args.baseline)
    observed = parse_pytest_output(args.output)

    new_failures = sorted(observed - baseline)
    resolved = sorted(baseline - observed)

    print(f"baseline accepted failures: {len(baseline)}")
    print(f"observed failures:          {len(observed)}")

    if new_failures:
        print(f"\nNEW failures ({len(new_failures)}) — not in the accepted baseline:")
        for node_id in new_failures:
            print(f"  {node_id}")
    if resolved:
        print(
            f"\nRESOLVED baseline failures ({len(resolved)}) — no longer failing; "
            "remove them from tests/accepted_full_suite_failures.txt in a reviewed commit:"
        )
        for node_id in resolved:
            print(f"  {node_id}")

    if new_failures or resolved:
        print("\nresult: FAILURE SET MISMATCH")
        return 1

    print("\nresult: observed failures exactly match the accepted baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
