"""Why a canonical run stopped before S-14, durably (#308).

The gap this closes. #308's first attempted acceptance run stopped at S-00
after one model call with ``SKIP / source_not_eligible``. The state code
reached the committed ``RunSummary``; the **reason** — the model's own words,
already on ``OutcomeRecord.reason`` — stayed in the run workspace and died with
the runner. A measurement slice cannot have a stop nobody can review, and
#308's acceptance asks for verified evidence rather than a status code.

Why a record of its own rather than a wider summary. ``RunSummary`` refuses
free text by design: §3.3 says a reason is a ``StateCode`` and a closed
category, and its public-safety guard enforces that because the summary is
committed to a public repository. Widening it to hold prose would break the
rule that makes it safe to publish. So this is a separate durable record, in
the same shape and the same ledger as the E-16 fingerprints (§3.2) — those
already carry free-form entity content, and the mechanism is proven.

**It never invents a rationale.** A seam that produced no reasoning leaves
``rationale`` absent with a stated reason, the measured-or-stated-absent
convention PO-DECISION-V1 settled for E-16's ``text_profile`` and NB-07a1's
token counts. "The seam said nothing" and "nobody recorded what it said" are
different facts, and a reader has to be able to tell them apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

#: Where early-stop records live under the durable ledger root.
EARLY_STOPS_DIRECTORY = "early_stops"

#: The decision seam produced no reasoning for this stop.
NO_RATIONALE_PRODUCED = "the deciding seam returned no rationale"

#: The stop was decided by code rather than by a model, so no model identity
#: applies — not an unknown one.
NO_MODEL_INVOLVED = "the stop was decided in code, not by a model"


class EarlyStopError(RuntimeError):
    """An early-stop record cannot be written truthfully."""


@dataclass(frozen=True, slots=True)
class EarlyStop:
    """One canonical run's stop before S-14, with enough to review it.

    ``stage`` is where the run stopped, ``outcome`` / ``state_code`` /
    ``category`` are the ARP facts the trace already carries, ``model`` is the
    identity that rendered the judgment, and ``rationale`` is what the seam
    said. The last two are **measured or stated absent**: a code-decided stop
    names no model, and a silent seam leaves no rationale, and neither is
    filled in with a guess.
    """

    run_id: str
    signal_id: str
    stage: str
    outcome: str
    state_code: Optional[str] = None
    category: Optional[str] = None
    model: Optional[str] = None
    model_absent_reason: Optional[str] = None
    rationale: Optional[str] = None
    rationale_absent_reason: Optional[str] = None

    def __post_init__(self) -> None:
        for value, reason, name in (
            (self.model, self.model_absent_reason, "model"),
            (self.rationale, self.rationale_absent_reason, "rationale"),
        ):
            if value is not None and reason is not None:
                raise EarlyStopError(
                    f"{name} is both recorded and stated absent; one of them "
                    "is not true"
                )
            if value is None and reason is None:
                raise EarlyStopError(
                    f"{name} is neither recorded nor stated absent — a reader "
                    "would have to guess which, and guessing is what this "
                    "record exists to prevent"
                )
        if not self.run_id or not self.stage or not self.outcome:
            raise EarlyStopError(
                "an early-stop record names the run, the stage and the outcome"
            )

    @property
    def stop_id(self) -> str:
        """``stop-<run_id>-<stage>``. One stop per run, named by where."""

        return f"stop-{self.run_id}-{self.stage}"

    def as_entity(self) -> dict[str, Any]:
        """The record as the durable ledger stores it: flat and serializable."""

        return {
            "stop_id": self.stop_id,
            "run_id": self.run_id,
            "signal_id": self.signal_id,
            "stage": self.stage,
            "outcome": self.outcome,
            "state_code": self.state_code,
            "category": self.category,
            "model": self.model,
            "model_absent_reason": self.model_absent_reason,
            "rationale": self.rationale,
            "rationale_absent_reason": self.rationale_absent_reason,
        }


def early_stop_from_outcome(
    *,
    run_id: str,
    signal_id: str,
    stage: str,
    outcome: Mapping[str, Any],
    model: Optional[str],
) -> EarlyStop:
    """Build the record from the outcome the trace already holds.

    Read off the ARP outcome rather than re-derived: the stage recorded why it
    stopped, and this copies that answer instead of forming a second opinion
    about it. ``model`` is ``None`` for a stop no model decided.
    """

    reason = outcome.get("reason")
    reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
    return EarlyStop(
        run_id=run_id,
        signal_id=signal_id,
        stage=stage,
        outcome=str(outcome.get("outcome") or ""),
        state_code=outcome.get("state_code"),
        category=outcome.get("category"),
        model=model,
        model_absent_reason=None if model else NO_MODEL_INVOLVED,
        rationale=reason,
        rationale_absent_reason=None if reason else NO_RATIONALE_PRODUCED,
    )


def early_stop_ledger_path(stop: EarlyStop, *, client: str, month: str) -> str:
    """``early_stops/<client>/<yyyy-mm>/<stop_id>.json``, like a fingerprint."""

    return f"{EARLY_STOPS_DIRECTORY}/{client}/{month}/{stop.stop_id}.json"


def write_early_stop_to_ledger(
    stop: EarlyStop, *, client: str, month: str, root: Optional[Any] = None
) -> Any:
    """Commit one early-stop record to the durable ledger, create-once."""

    from src.run.ledger import write_record

    return write_record(
        early_stop_ledger_path(stop, client=client, month=month),
        stop.as_entity(),
        root=root,
    )
