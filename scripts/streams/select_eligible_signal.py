#!/usr/bin/env python3
"""Select the first unused, role-eligible signal for a stream run (#142).

The naive selection — first unused signal in queue order — assumes every
signal is a legitimate starting point for every stream. Once a role declares
eligibility criteria that assumption is false: the queue's first candidate can
be exactly the class the role must refuse.

This selector walks the unused candidates in queue order, asks the role's
eligibility judgment about each, and stops at the first eligible one. It
writes an audit record of every disposition it made, because "why did the stream
pick this signal and skip that one" must be answerable from evidence, not from
a rerun.

Exit codes:
  0  — an eligible candidate was selected (its SIGNAL_ID is on stdout's last
       ``selected=`` line, and in the audit record)
  3  — EVERY available unused candidate was evaluated, every judgment
       completed, and all were genuinely ineligible. Only this complete search
       may claim a clean "publish nothing" outcome.
  5  — no eligible candidate among the evaluated candidates, but unevaluated
       candidates remain beyond ``--max-candidates``. An INCOMPLETE search:
       candidate N+1 may be eligible, so this must fail visibly rather than
       masquerade as a healthy empty run — "no eligible candidate in the
       evaluated window" is not "no eligible candidate in the queue".
  4  — no candidate was selected AND at least one eligibility judgment failed.
       This is infrastructure failure, not a clean empty result: unattended
       automation must fail visibly rather than report "nothing to publish"
       over judgments that never completed.
  1  — the selection itself failed (bad role, unreadable queue)

Rejected candidates are only ever *skipped*. Nothing here writes the
published-signals marker; consumption stays where it always was — after a
successful publication.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.editorial.editorial_role import EditorialRoleError, resolve_editorial_role
from src.editorial.source_eligibility import (
    LlmChatSourceEligibilityTransport,
    SourceEligibilityError,
    judge_source_eligibility,
)
from src.strategy.business_config import load_business_strategy_configuration


NO_ELIGIBLE = 3
ELIGIBILITY_FAILURE = 4
SEARCH_TRUNCATED = 5

#: Judging a candidate costs a model call, so a single selection bounds how far
#: down the queue it will look. Recorded in the audit when the cap is reached —
#: a truncated search must never read as "nothing in the queue was eligible".
DEFAULT_MAX_CANDIDATES = 15

#: Hard Release 1 bound on one eligibility sweep (#171 correction): the
#: selector is the largest pre-run call multiplier, and the per-run text
#: budget does not cover this separate process — so the bound must be
#: enforced here, not merely defaulted. Matches the scheduled default.
MAX_CANDIDATES_CEILING = 15


def _load_candidates(active_path: Path, published_path: Path) -> list[dict]:
    published = (
        set(published_path.read_text().splitlines()) if published_path.exists() else set()
    )
    candidates = []
    for line in active_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            signal = json.loads(line)
        except json.JSONDecodeError:
            continue
        signal_id = str(signal.get("SIGNAL_ID", "") or "").strip()
        if signal_id and signal_id not in published:
            candidates.append(signal)
    return candidates


def main(argv: list[str] | None = None, *, transport=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editorial-role", required=True)
    parser.add_argument(
        "--signal-id", default="",
        help="Judge only this signal (explicit dispatch); ineligible means exit 3",
    )
    parser.add_argument("--audit-out", default="",
                        help="Where to write the selection audit JSON")
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--active-path", default="data/research/signals_active.jsonl")
    parser.add_argument("--published-path", default="data/research/published_signal_ids.txt")
    args = parser.parse_args(argv)

    # #171 correction: the bound is enforced, not merely defaulted. Refused
    # before any queue is read and before any model call — never clamped.
    if not 1 <= args.max_candidates <= MAX_CANDIDATES_CEILING:
        print(
            f"ERROR: --max-candidates must be between 1 and "
            f"{MAX_CANDIDATES_CEILING} for Release 1; got {args.max_candidates}"
        )
        return 1

    try:
        configuration = load_business_strategy_configuration()
        _, role = resolve_editorial_role(configuration, args.editorial_role)
    except (EditorialRoleError, Exception) as exc:  # noqa: BLE001 — CLI boundary
        print(f"ERROR: {exc}")
        return 1
    if not role.eligibility_criteria:
        print(f"ERROR: role {role.role_id!r} declares no eligibility criteria")
        return 1

    candidates = _load_candidates(Path(args.active_path), Path(args.published_path))
    if args.signal_id:
        candidates = [
            signal for signal in candidates
            if str(signal.get("SIGNAL_ID", "")) == args.signal_id
        ]
        if not candidates:
            print(f"ERROR: signal {args.signal_id!r} is not an unused queue candidate")
            return 1

    judge = transport or LlmChatSourceEligibilityTransport()
    audit = {
        "role_id": role.role_id,
        "requested_signal_id": args.signal_id or None,
        "max_candidates": args.max_candidates,
        "candidates_available": len(candidates),
        "truncated": len(candidates) > args.max_candidates,
        "dispositions": [],
        "selected_signal_id": None,
    }
    selected = None
    for signal in candidates[: args.max_candidates]:
        signal_id = str(signal.get("SIGNAL_ID", ""))
        try:
            verdict = judge_source_eligibility(signal, role, judge)
        except SourceEligibilityError as exc:
            if exc.scope == "provider":
                # Circuit breaker (#170): the provider refused this call, so
                # every remaining candidate would fail identically — and each
                # further attempt makes a rate limit worse. Stop the sweep on
                # the first provider-scope failure; the honest evaluated/
                # remaining counts below record how far the search got.
                #
                # #188: the sanitized normalized diagnostic is persisted so
                # the evidence can distinguish throttling from exhausted
                # quota from auth/connection/outage — run 32607277008 could
                # only say "RateLimitError" while the true condition was
                # 429 insufficient_quota / credit_balance_exhausted.
                _diag = exc.diagnostic
                audit["dispositions"].append(
                    {"signal_id": signal_id,
                     "disposition": "provider_unavailable",
                     "detail": str(exc)[:300],
                     "provider_failure": (
                         _diag.as_audit_dict() if _diag is not None else None
                     )}
                )
                print(f"  ✗  {signal_id}: provider unavailable — {exc}")
                if _diag is not None:
                    print(
                        f"     provider failure: {_diag.normalized_reason}"
                        + (f" (http {_diag.http_status}" if _diag.http_status else " (")
                        + (f", type={_diag.provider_error_type}" if _diag.provider_error_type else "")
                        + (f", code={_diag.provider_error_code}" if _diag.provider_error_code else "")
                        + ")"
                    )
                print(
                    "Provider-wide failure: stopping the eligibility sweep "
                    "without evaluating further candidates."
                )
                break
            # Fail closed per candidate: a judgment that could not complete is
            # a rejection, recorded as its own disposition so it can never be
            # confused with a real ineligibility finding.
            audit["dispositions"].append(
                {"signal_id": signal_id, "disposition": "judgment_failed",
                 "detail": str(exc)[:300]}
            )
            print(f"  ✗  {signal_id}: judgment failed — {exc}")
            continue
        if verdict.eligible:
            audit["dispositions"].append(
                {"signal_id": signal_id, "disposition": "eligible",
                 "reason": verdict.reason}
            )
            print(f"  ✓  {signal_id}: eligible — {verdict.reason}")
            selected = signal_id
            break
        audit["dispositions"].append(
            {"signal_id": signal_id, "disposition": "ineligible",
             "reason": verdict.reason}
        )
        print(f"  ✗  {signal_id}: ineligible — {verdict.reason}")

    audit["selected_signal_id"] = selected
    failures = sum(
        1 for item in audit["dispositions"]
        if item["disposition"] in ("judgment_failed", "provider_unavailable")
    )
    evaluated = len(audit["dispositions"])
    audit["evaluated"] = evaluated
    audit["remaining"] = max(0, audit["candidates_available"] - evaluated)
    if selected is not None:
        audit["outcome"] = "selected"
    elif failures:
        # One or more judgments never completed — a per-candidate failure, or
        # a provider-wide stop that left candidates unevaluated. Either way,
        # "no eligible candidate" would be a claim the evidence does not
        # support, and this branch is checked before the truncation branch so
        # a provider stop can never surface as search_truncated.
        audit["outcome"] = "eligibility_failure"
    elif audit["truncated"]:
        audit["outcome"] = "search_truncated"
    else:
        audit["outcome"] = "no_eligible_complete"
    if args.audit_out:
        out = Path(args.audit_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")

    if selected is not None:
        print(f"selected={selected}")
        return 0
    if failures:
        print(
            f"Eligibility infrastructure failure: {failures} of {evaluated} "
            "judgments did not complete and no eligible candidate was selected. "
            "This is not a clean nothing-to-publish outcome."
        )
        return ELIGIBILITY_FAILURE
    if audit["truncated"]:
        print(
            f"Incomplete eligibility search: no eligible candidate among the "
            f"{evaluated} evaluated, but {audit['remaining']} unused "
            "candidates remain unevaluated beyond the search bound. One of "
            "them may be eligible, so this is NOT a clean nothing-to-publish "
            "outcome — it needs an operator (raise --max-candidates, dispatch "
            "an explicit signal, or curate the queue)."
        )
        return SEARCH_TRUNCATED
    print(
        f"All {evaluated} unused candidates were judged ineligible — "
        "publishing nothing is the correct outcome."
    )
    return NO_ELIGIBLE


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
