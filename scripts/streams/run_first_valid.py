#!/usr/bin/env python3
"""ENGINE: first valid signal wins, through generation (#240 D8).

Selection judges a candidate from its metadata; the Pattern Extractor, the
pre-generation editorial suitability gate, judges it again with its evidence.
Before this driver, a candidate that passed selection and then failed that
gate ended the whole run — so "first valid signal wins" held only up to the
first stage that could disagree with selection.

This driver keeps the rule true through generation. For one stream run it:

1. generates the candidate the selection step already chose;
2. if the canonical entrypoint reports it editorially unsuitable (exit 6),
   records why, passes over it for the rest of this run only, asks the
   selector for the next candidate in queue order, and tries that one. The
   selector resumes where it stopped: candidates this run already judged
   ineligible are passed over too, never judged (and paid for) twice;
3. stops at the first candidate that completes, or when no candidate remains.

Nothing here consumes a signal: a rejected candidate is only passed over in this
run, and stays available to later runs. Every attempt is recorded. Any other
failure — infrastructure, a later gate, publication — ends the run exactly as
before, because only editorial unsuitability means "try the next candidate".

The driver knows no stream's meaning. It is given a role; the selector and the
entrypoint apply that role's client contracts.

Exit codes: 0 — a candidate completed, or no usable candidate remained (a clean
empty run; ``signal_id`` is then empty); anything else — the failing step's
code.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The canonical entrypoint's "editorially unsuitable" exit code.
EDITORIALLY_UNSUITABLE = 6
#: The selector's "every remaining candidate was judged ineligible" exit code.
NO_ELIGIBLE = 3

Runner = Callable[[list[str]], int]


def _run(argv: list[str]) -> int:
    return subprocess.run([sys.executable, *argv], cwd=REPO_ROOT, check=False).returncode


def _packages_root() -> Path:
    return Path(os.environ.get("NB_PACKAGES_DIR", "").strip() or "reports/content_packages")


def _rejection_records(signal_id: str) -> list[dict]:
    """The entrypoint's editorial_rejection.json records for this signal, if any."""
    records = []
    for path in sorted((_packages_root() / signal_id / "runs").glob("*/editorial_rejection.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            records.append({"unreadable": str(path)})
    return records


def _emit_output(name: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def _emit_evidence_paths(signal_ids: list[str]) -> None:
    """Every attempted candidate's canonical evidence, one path per line.

    Independent of ``signal_id``, which names only the candidate that
    completed: a candidate that was passed over, or that failed after an
    earlier one was passed over, is evidence too.
    """
    target = os.environ.get("GITHUB_OUTPUT")
    if not target or not signal_ids:
        return
    root = _packages_root()
    lines = []
    for signal_id in signal_ids:
        lines += [f"{root / signal_id / 'runs'}/", str(root / f"{signal_id}_generated.json")]
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("evidence_paths<<__NB_EVIDENCE__\n" + "\n".join(lines)
                     + "\n__NB_EVIDENCE__\n")


def main(argv: list[str] | None = None, *, run: Runner = _run) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editorial-role", required=True)
    parser.add_argument("--first-signal-id", required=True,
                        help="The candidate the selection step already chose")
    parser.add_argument("--audit-dir", required=True,
                        help="Where this run's attempt record and re-selection audits go")
    parser.add_argument("--selection-audit", default="",
                        help="The audit of the selection that chose --first-signal-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preview-fresh-images", action="store_true",
                        help="Passed through to every generation attempt")
    args = parser.parse_args(argv)

    audit_dir = Path(args.audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)
    excluded_path = audit_dir / "excluded_this_run.txt"
    attempts: list[dict] = []
    record_path = audit_dir / "first_valid_attempts.json"
    passed_over: list[str] = []

    def pass_over(signal_id: str) -> None:
        if signal_id and signal_id not in passed_over:
            passed_over.append(signal_id)

    def pass_over_judged(audit_path: Path) -> None:
        """Candidates a selection in this run already judged ineligible.

        Only completed "ineligible" judgments: a judgment that failed is not a
        finding, so that candidate may be judged again.
        """
        if not audit_path.is_file():
            return
        for item in json.loads(audit_path.read_text(encoding="utf-8")).get("dispositions", []):
            if item.get("disposition") == "ineligible":
                pass_over(str(item.get("signal_id", "")))

    if args.selection_audit:
        pass_over_judged(Path(args.selection_audit))

    def record(outcome: str, selected: str) -> None:
        _emit_evidence_paths([attempt["signal_id"] for attempt in attempts])
        record_path.write_text(json.dumps(
            {"role_id": args.editorial_role, "dry_run": args.dry_run,
             "outcome": outcome, "selected_signal_id": selected or None,
             "attempts": attempts}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")

    candidate = args.first_signal_id.strip()
    while candidate:
        generate = ["scripts/generate_and_publish.py", "--signal-id", candidate,
                    "--editorial-role", args.editorial_role]
        if args.dry_run:
            generate.append("--dry-run")
        if args.preview_fresh_images:
            generate.append("--preview-fresh-images")
        code = run(generate)
        attempts.append({"signal_id": candidate, "exit_code": code,
                         "outcome": ("completed" if code == 0 else
                                     "editorially_unsuitable" if code == EDITORIALLY_UNSUITABLE
                                     else "failed")})
        if code == 0:
            record("selected", candidate)
            _emit_output("signal_id", candidate)
            print(f"selected={candidate}")
            return 0
        if code != EDITORIALLY_UNSUITABLE:
            record("failed", "")
            _emit_output("signal_id", "")
            return code

        attempts[-1]["rejection"] = _rejection_records(candidate)
        print(f"  —  {candidate}: editorially unsuitable; passing over it for this run only")
        pass_over(candidate)
        excluded_path.write_text("".join(f"{item}\n" for item in passed_over), encoding="utf-8")
        selection_audit = audit_dir / f"reselection_{len(attempts)}.json"
        code = run(["scripts/streams/select_eligible_signal.py",
                    "--editorial-role", args.editorial_role,
                    "--exclude-path", str(excluded_path),
                    "--audit-out", str(selection_audit)])
        if code == NO_ELIGIBLE:
            break
        if code != 0:
            record("failed", "")
            _emit_output("signal_id", "")
            return code
        pass_over_judged(selection_audit)
        candidate = json.loads(selection_audit.read_text())["selected_signal_id"] or ""

    record("no_usable_candidate", "")
    _emit_output("signal_id", "")
    print("No usable candidate remained in this run — publishing nothing.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
