"""How often each conditional lens activated across a portfolio of runs (#268).

Reads the ``editorial_plan.json`` every run persists and reports, per condition,
how many runs were asked to decide it and how many its evidence met.

Observation only, by product decision. Nothing here refuses an activation, and
no threshold lives in this repository: a cap enforced in code would make the
next activation a way to satisfy a metric, which is the recurring tic a
conditional lens exists to avoid. What a rate means — and what to do about
one — is the client's to decide in its own documents.

    python3 scripts/editorial/portfolio_activation.py [--packages DIR] [--json]

Reads nothing else and writes nothing: safe to run against a live portfolio.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.editorial.editorial_plan import activation_rates

DEFAULT_PACKAGES_DIR = Path("reports/content_packages")


def packages_dir(supplied: str | None = None) -> Path:
    """The portfolio to read: the flag, then ``NB_PACKAGES_DIR``, then default."""
    if supplied:
        return Path(supplied)
    configured = os.environ.get("NB_PACKAGES_DIR", "").strip()
    return Path(configured) if configured else DEFAULT_PACKAGES_DIR


def plan_records(directory: Path) -> list[dict]:
    """Every persisted plan in the portfolio, oldest path first.

    A file that is missing, unreadable or not a JSON object is skipped rather
    than failing the report: one damaged run must not hide the other hundred.
    """
    records: list[dict] = []
    for path in sorted(directory.glob("*/runs/*/editorial_plan.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", default="", help="portfolio directory to read")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    directory = packages_dir(args.packages)
    records = plan_records(directory)
    observations = activation_rates(records)

    if args.json:
        print(json.dumps(
            {"packages_dir": str(directory), "runs_with_a_plan": len(records),
             "conditions": [o.as_evidence() for o in observations]},
            indent=2, ensure_ascii=False,
        ))
        return 0

    print(f"portfolio: {directory}  ({len(records)} run(s) with an editorial plan)")
    if not observations:
        print("  no conditional lens has been decided in this portfolio yet")
        return 0
    for observation in observations:
        print(
            f"  {observation.condition}: activated {observation.activated} of "
            f"{observation.eligible} eligible run(s) — {observation.rate:.0%}"
        )
        for run in observation.runs:
            print(f"      activated in {run}")
    print("\nObservation only: no threshold is enforced anywhere (#268).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
