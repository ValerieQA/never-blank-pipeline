"""Where does a Wednesday run's signal come from? (Issue #211, review round 2)

#211 restored July's research path but left it dormant: production Wednesday
still drew its signal from the *current* shared supply —

    scripts/streams/select_eligible_signal.py
      → data/research/{selected_signals,signals_active}.jsonl
      → written by scripts/research/run_daily_research.py

— which is the small-business feed set and the "ALWAYS REJECT … Large company
M&A" selector, i.e. the two 2026-07-21 changes that made the Versant specimen
unreachable in the first place (#206). Restoring July's discovery and then
feeding Wednesday from today's discovery leaves the regression exactly where
it was.

This module is the supply seam. For the Wednesday role only, the run's signal
is produced by the restored July research path and nothing else:

    run_wednesday_research()  →  the historical 46-field signal  →  the run

Monday and role-less runs never reach this module; they keep `_load_signal`
and the shared store unchanged.

**Publishing nothing stays a correct outcome.** July's own research returned
an empty list on a quiet day and nothing was published. When discovery finds
no unseen candidate this returns ``None`` and the caller stops the run
cleanly — it never falls back to the shared store, because a fallback would
silently reintroduce the very supply this exists to bypass.

Signals are appended to their own store, separate from the shared one, so a
Wednesday signal can be reloaded by identity later (a ``--from-package``
retry) without ever being offered to Monday's selector.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterable, Optional

from scripts.research.enrich import determine_article_readiness
from src.never_blank.wednesday_july.research import run_wednesday_research
from src.utils.logger import get_logger

log = get_logger("never_blank.wednesday_supply")

#: Wednesday's own signal store. Deliberately NOT one of the shared
#: `SIGNALS_FILES` that `run_daily_research.py` writes and Monday's selector
#: reads — the two supplies must not mix in either direction.
WEDNESDAY_SIGNALS_FILE = Path("data/research/wednesday_july_signals.jsonl")

#: The cross-stream consumption marker, shared with every other stream. A
#: signal published once is never eligible again, whichever stream published
#: it — that rule is canonical infrastructure and is not being restored to a
#: July state.
PUBLISHED_IDS_FILE = Path("data/research/published_signal_ids.txt")


class WednesdaySupplyError(RuntimeError):
    """Wednesday's supply could not be produced or is not usable."""


class WednesdayResearchInfrastructureError(WednesdaySupplyError):
    """A stage of the July research failed; its empty result means nothing.

    Distinct from an empty Wednesday. July's modules fail soft — every stage
    catches its own transport exception, logs it, and returns an empty result
    — which is the historical behaviour and stays untouched. But a caller who
    cannot tell "the selector considered 30 candidates and chose none" from
    "the selector never ran because the provider rejected the request" will
    report an outage as a quiet news day. Run 33281894748 did exactly that:
    HTTP 400 `invalid model ID`, zero candidates, exit 0, green workflow.
    """


#: The July research loggers. Every fail-soft site in those modules reports
#: its own failure through one of these before swallowing it, so the record
#: this needs already exists — it is simply never read by anything.
_JULY_RESEARCH_LOGGERS = (
    "research.discover",     # RSS parse, select_indices, candidate enrichment
    "research.score",
    "research.enrich",
    "research.angles",
)

#: Which stage a logger speaks for, for the error message.
_STAGE_OF = {
    "research.discover": "discovery/selection",
    "research.score": "scoring",
    "research.enrich": "enrichment",
    "research.angles": "angles",
}

_CREDENTIAL_SHAPED = re.compile(
    r"(?i)(?:authorization|cookie|x-api-key|api[_-]?key|access[_-]?token|"
    r"secret|password|bearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,})"
)

#: Configured model ids are secrets in this deployment, so a provider message
#: that echoes one must not reach a log line, an artifact or a GitHub summary.
_MODEL_ENV_VARS = (
    "NB_DISCOVERY_MODEL", "NB_SCORING_MODEL", "NB_ENRICH_MODEL",
    "NB_ARTICLE_MODEL", "NB_SOCIAL_MODEL", "NB_OPENAI_CHAT_MODEL",
)


def _redacted(reason: str) -> str:
    """A bounded, audit-safe rendering of a provider failure reason."""
    text = " ".join(str(reason).split())
    for name in _MODEL_ENV_VARS:
        value = (os.environ.get(name) or "").strip()
        if value:
            text = text.replace(value, f"<{name}>")
    if _CREDENTIAL_SHAPED.search(text):
        return "[reason withheld: credential-shaped text]"
    return text[:300]


class _StageFailureRecorder(logging.Handler):
    """Records the failures July's modules log on their way to failing soft."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.failures: list[tuple[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        # ERROR only. A feed that 404s is logged at WARNING and is not an
        # infrastructure failure: July tolerated a dead feed and published
        # from the others, and this must keep doing the same.
        if record.levelno < logging.ERROR:
            return
        stage = _STAGE_OF.get(record.name, record.name)
        try:
            message = record.getMessage()
        except Exception:                       # a malformed record is still a failure
            message = "unrenderable log record"
        self.failures.append((stage, _redacted(message)))


@contextmanager
def _watching_july_research():
    """Attach the recorder for the duration of one research invocation.

    The watch is made independent of how logging happens to be configured.
    A raised level or a ``logging.disable()`` elsewhere in the process would
    otherwise stop the records reaching the recorder and silently restore the
    exact masking this exists to end — a safety check that can be switched off
    by an unrelated logging tweak is not a safety check. Both are forced for
    the duration and restored afterwards, including on the failure path.
    """
    recorder = _StageFailureRecorder()
    loggers = [logging.getLogger(name) for name in _JULY_RESEARCH_LOGGERS]
    previous_levels = [logger.level for logger in loggers]
    previous_disable = logging.root.manager.disable

    if previous_disable >= logging.ERROR:
        logging.disable(logging.ERROR - 1)
    for logger in loggers:
        logger.addHandler(recorder)
        if logger.level > logging.ERROR:
            logger.setLevel(logging.ERROR)
    try:
        yield recorder
    finally:
        for logger, level in zip(loggers, previous_levels):
            logger.removeHandler(recorder)
            logger.setLevel(level)
        logging.disable(previous_disable)


def published_signal_ids(path: Path = PUBLISHED_IDS_FILE) -> set[str]:
    """Signals already consumed by any stream."""
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def apply_current_readiness(signal: dict) -> dict:
    """Derive today's readiness fields from July's own enrichment.

    July's 46-field contract predates the readiness gate, so a restored
    signal reaches the lifecycle with no ``SOURCE_PREMISE_VERIFIED`` and is
    refused — correctly, since an absent field must never read as verified.

    ``determine_article_readiness`` is the current gate's own deterministic
    derivation: no model call, no side effects, no feed or selector policy.
    It reads exactly the fields July's ``enrich_signal`` already produces —
    ``REAL_COMPANY_EXAMPLE``, ``SOURCE_FOR_CASE``, ``CORE_FACT``,
    ``CONFIDENCE`` — and answers whether the claim has a verifiable source.

    So the gate is applied, not bypassed and not softened: a July signal
    whose evidence does not satisfy it is still refused downstream. This only
    stops a signal being rejected for lacking a field nobody had computed.
    """
    ready, reason = determine_article_readiness(signal)
    verified = (
        bool(signal.get("REAL_COMPANY_EXAMPLE")) and bool(signal.get("SOURCE_FOR_CASE"))
    ) or (
        bool(signal.get("SOURCE_FOR_CASE"))
        and signal.get("CONFIDENCE", "low") in ("high", "medium")
    )
    log.info(
        "Wednesday readiness %s: article_ready=%s premise_verified=%s (%s)",
        signal.get("SIGNAL_ID"), ready, verified, reason,
    )
    return {
        **signal,
        "SOURCE_PREMISE_VERIFIED": str(verified).lower(),
        "ARTICLE_READY": str(ready).lower(),
        "RECOMMENDED_FOR_ARTICLE": str(ready).lower(),
    }


def _persist(signals: Iterable[dict], store: Path) -> None:
    """Append newly discovered signals, skipping ids the store already holds.

    Append-only and id-deduplicated: a rerun on the same day must not create
    a second, divergent copy of a signal the run may later reload by identity.
    """
    signals = list(signals)
    if not signals:
        return
    known: set[str] = set()
    if store.exists():
        for line in store.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                known.add(json.loads(line).get("SIGNAL_ID", ""))
            except json.JSONDecodeError:
                continue
    fresh = [s for s in signals if s.get("SIGNAL_ID") not in known]
    if not fresh:
        return
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("a", encoding="utf-8") as handle:
        for signal in fresh:
            handle.write(json.dumps(signal, ensure_ascii=False) + "\n")
    log.info("Wednesday supply: persisted %d new signal(s) to %s", len(fresh), store)


def supply_wednesday_signal(
    requested_signal_id: str = "",
    *,
    seen_ids: Optional[set[str]] = None,
    research: Callable = run_wednesday_research,
    store: Path = WEDNESDAY_SIGNALS_FILE,
) -> Optional[dict]:
    """Produce this Wednesday run's signal from the restored July research.

    ``requested_signal_id`` selects among what discovery returned — it is a
    filter, never a bypass. Asking for a signal this run's discovery did not
    produce is an error rather than a silent fall-through to the shared
    store, so an operator cannot accidentally publish a Monday-supplied
    signal through the Wednesday path.

    Returns ``None`` when discovery found nothing new: an empty Wednesday.
    """

    seen = set(seen_ids) if seen_ids is not None else published_signal_ids()

    # July's stages swallow their own transport failures by design. Rather
    # than change them — they are a verbatim port and must stay one — watch
    # what they report on the way down, so an outage cannot be mistaken for a
    # quiet news day.
    with _watching_july_research() as recorder:
        try:
            signals = research(seen_ids=seen)
        except Exception as exc:                  # anything that did NOT fail soft
            raise WednesdayResearchInfrastructureError(
                f"restored July research failed to produce a Wednesday supply: "
                f"{_redacted(exc)}"
            ) from exc

    if recorder.failures:
        # Fail closed, with no fallback and no second candidate: the result
        # in hand is not a judgment about today's news, so acting on it —
        # publishing OR reporting an empty Wednesday — would be a fabrication.
        detail = "; ".join(
            f"{stage}: {reason}" for stage, reason in recorder.failures
        )
        raise WednesdayResearchInfrastructureError(
            f"restored July research reported {len(recorder.failures)} stage "
            f"failure(s), so its result is not a judgment about today's "
            f"candidates — {detail}"
        )

    if not signals:
        log.info("Wednesday supply: no unseen candidate — publishing nothing")
        return None

    signals = [apply_current_readiness(signal) for signal in signals]
    _persist(signals, store)

    if requested_signal_id:
        for signal in signals:
            if signal.get("SIGNAL_ID") == requested_signal_id:
                return signal
        raise WednesdaySupplyError(
            f"signal {requested_signal_id!r} was not produced by this run's "
            f"Wednesday research (discovered: "
            f"{[s.get('SIGNAL_ID') for s in signals]!r}). The Wednesday path "
            f"does not read the shared signal store."
        )

    # July's scoring stage already returns candidates highest-score first, so
    # first-is-best is July's own ordering, not an arbitrary pick. Among them,
    # take the best one today's readiness gate would actually accept: a
    # top-scored candidate whose evidence does not satisfy the gate would
    # otherwise block the run while a publishable case sat behind it. This
    # relaxes nothing — a candidate the gate refuses is still never chosen —
    # and if none qualifies the answer is an empty Wednesday, as it should be.
    ready = [s for s in signals if s.get("ARTICLE_READY") == "true"]
    if not ready:
        log.info(
            "Wednesday supply: %d candidate(s) discovered, none article-ready "
            "— publishing nothing", len(signals),
        )
        return None

    chosen = ready[0]
    log.info(
        "Wednesday supply: %s — %s",
        chosen.get("SIGNAL_ID"), str(chosen.get("HEADLINE", ""))[:70],
    )
    return chosen


__all__ = [
    "PUBLISHED_IDS_FILE",
    "WednesdayResearchInfrastructureError",
    "WEDNESDAY_SIGNALS_FILE",
    "WednesdaySupplyError",
    "published_signal_ids",
    "supply_wednesday_signal",
]
