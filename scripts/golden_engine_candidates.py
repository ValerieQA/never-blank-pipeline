#!/usr/bin/env python3
"""Which signals the Golden Engine can actually run, and which are cases (#308).

Read-only. No model call, no provider call, no write. It answers one question
a person otherwise answers by guessing:

    of the signals intake has written, which ones can reach S-04 at all, and
    which of those verified through the company-case evidence path?

Two independent gates, and the point is that they are independent — a signal
needs both, and the two runs so far each failed a different one:

* **S-00** — the client's own ``ContractFitRules``, evaluated through the
  engine's path (``golden_engine_fit_rules`` over ``selection_candidate``), so
  the answer here cannot drift from the answer the run gets. A signal without a
  stated ``EDITORIAL_DOMAIN``/``EDITORIAL_RISK`` is refused, which is 134 of
  the 138 records as this is written. Acceptance run 2 spent an authorization on
  a signal that failed exactly this, chosen on material alone.
* **The evidence path** — ``premise_path`` from Stage 4's own readiness
  derivation. ``company_case`` means the record has the shape of a company case
  — a named company with a source for it; ``research_data`` is legitimate
  material that is not a company case. Acceptance run 1 spent its authorization
  on a signal that passed S-00 and was ``research_data``, and S-04 refused it
  with ``no_asset_or_admissible_interpretation``.

**What this does not do.** It does not admit, score, rank or approve anything.
``company_case`` is an **evidence-path shape, not a verified business outcome**
and not a prediction that S-04 will pass: S-04 decides on an admissible
interpretation and a reader connection, and neither follows from a named
company. Nothing here reads ``EVIDENCE_OF_OUTCOME`` or judges whether a result
was actually established. This is a shortlist of what is *eligible*, so an
authorization is not spent on a signal that could never have reached the stage
under diagnosis.

``ARTICLE_READINESS_SCORE`` is deliberately not used. Measured over the queue it
is anti-correlated with documented-case material: the two S-00-eligible signals
scoring 10 carry none of it, and the one carrying 4 of 5 axes scores 5.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.research.enrich import COMPANY_CASE, premise_path  # noqa: E402
from src.run.signal_adapter import (  # noqa: E402
    golden_engine_fit_rules,
    selection_candidate,
)

#: The intake record S-00 reads, spelled as intake spells it.
ACTIVE_SIGNALS = REPO_ROOT / "data" / "research" / "signals_active.jsonl"

#: The client whose contract decides eligibility.
CLIENT_DIR = REPO_ROOT / "clients" / "never_blank"


def signals(path: Path = ACTIVE_SIGNALS) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def assess(record: dict, *, client_dir: Path = CLIENT_DIR) -> dict:
    """One signal's two verdicts, both deterministic."""

    verdicts = golden_engine_fit_rules(directory=client_dir).evaluate(
        selection_candidate(record).signal
    )
    refused = [v.rule_id for v in verdicts if not v.passed]
    return {
        "signal_id": str(record.get("SIGNAL_ID") or ""),
        "headline": str(record.get("HEADLINE") or ""),
        "source": str(record.get("SOURCE_NAME") or ""),
        "s00_passes": not refused,
        "refused_by": refused,
        "premise_path": premise_path(record),
    }


def candidates(
    records: list[dict], *, client_dir: Path = CLIENT_DIR
) -> list[dict]:
    """Every signal that clears S-00 *and* verified through the company-case path.

    A shortlist, not an approval: see the module docstring.
    """

    return [
        a
        for a in (assess(r, client_dir=client_dir) for r in records)
        if a["s00_passes"] and a["premise_path"] == COMPANY_CASE
    ]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all", action="store_true",
        help="also list the signals that clear S-00 but are not documented cases",
    )
    args = parser.parse_args(argv)

    records = signals()
    assessed = [assess(r) for r in records]
    eligible = [a for a in assessed if a["s00_passes"]]
    cases = [a for a in eligible if a["premise_path"] == COMPANY_CASE]

    print(f"  signals in the queue          {len(records)}")
    print(f"  clear S-00                    {len(eligible)}")
    print(f"  of those, company-case path   {len(cases)}")

    if cases:
        print("\n  runnable company-case candidates (shape, not a verified outcome):")
        for a in cases:
            print(f"    {a['signal_id']}  {a['source'][:22]:22} {a['headline'][:54]}")
    else:
        print(
            "\n  no runnable company-case candidate. Every S-00-eligible "
            "signal\n  verified through the research/data path, which is not a "
            "company case."
        )

    if args.all and eligible:
        print("\n  S-00-eligible but not on the company-case path:")
        for a in eligible:
            if a["premise_path"] != COMPANY_CASE:
                print(
                    f"    {a['signal_id']}  path={a['premise_path'] or 'unverified'}"
                    f"  {a['headline'][:48]}"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
