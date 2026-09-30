"""Seam 1: the research signal intake wrote, as the input S-00 reads (#351).

The Golden Engine's first stage takes a
:class:`~src.editorial_core.signal_selection.SelectionCandidate`, whose
``signal`` is "the intake record itself, spelled as intake spells it"
(``signal_selection.py:310``). The research pipeline writes those records to
``data/research/signals_active.jsonl``. Nothing joined the two, and this module
is that join and nothing else: it lifts the two facts portfolio pressure
compares, binds the contract's fit rules to the fields the record carries, and
hands the record on **unchanged**.

What it must not do, and how it cannot
--------------------------------------
``EDITORIAL_DOMAIN`` and ``EDITORIAL_RISK`` are #365's, persisted by the Stage 4
enrichment before S-00 ever sees the record. This seam must not populate,
infer, default, append or synthesise either of them, so it does not write into
the record at all: what reaches the candidate is a
:class:`~types.MappingProxyType` over a copy, which is read-only by
construction. A later caller that wanted to add the classification cannot, and
a caller that mutates the dict it passed in cannot change what S-00 read.

**A record lacking either field is refused by S-00, and that refusal is
correct.** ``FitRule.check`` is a strict allow-list — "silence is not
admission" — so an unclassified record produces a ``SKIP`` citing
``FIT-NB-TOPIC-01`` or ``FIT-NB-RISK-01`` with ``stated`` empty. This module
therefore does not pre-screen for the fields and does not raise on their
absence: raising would take the refusal away from the rule that owns it and
leave the trace unable to say which rule decided. The same holds for a record
whose ``*_OUTCOME`` says ``cannot_answer``: the value field is absent, the
outcome field is carried across untouched, and "nobody could classify it" stays
readable beside "the classifier admitted nothing" rather than collapsing into
one silence.

The 134 historical signals carry none of these fields by #365's deliberate
decision, so the first real run needs a fresh research run. That is a state of
the data, not a defect for this seam to repair.

The field binding #363 left open
--------------------------------
``contract_fit_rules`` takes ``domain_field`` and ``risk_field`` as required
keyword arguments with no default, because "the E-01 spelling comes from the
intake normalisation (#351), not from this producer". This module is where that
spelling is decided, once: the names below are the intake record's own, from
``_KNOWN_JSONL_KEYS`` in ``src/lifecycle/signal_lifecycle.py``.

Sources: ``docs/editorial/architecture/03_STEP2_STAGE_CONTRACTS.md`` §1 (S-00);
``docs/editorial/architecture/01_STEP1_TYPED_ENTITIES.md`` §2 (E-01).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional

from src.editorial_core.signal_selection import (
    ContractFitRules,
    SelectionCandidate,
)
from src.strategy.contract_fit import contract_fit_rules

#: The intake record's identity field. The scope key every outcome of S-00 is
#: recorded against, which is why a record without one is refused here rather
#: than given a generated id: an outcome nobody can trace back to a signal is
#: not evidence about that signal.
SIGNAL_ID_FIELD: Final[str] = "SIGNAL_ID"

#: The one locator the record states as a locator. ``SOURCE_FOR_CASE`` is not a
#: second one: it holds a publisher and a URL in one sentence ("CNBC Business —
#: https://…"), and a locator parsed out of prose is a locator this seam
#: invented. U-2 rule 4.2 compares locators exactly, so a fabricated one would
#: manufacture a resemblance the portfolio never recorded.
SOURCE_URL_FIELD: Final[str] = "SOURCE_URL"

#: The two fields the Client Contract's fit rules read (#365 writes them).
DOMAIN_FIELD: Final[str] = "EDITORIAL_DOMAIN"
RISK_FIELD: Final[str] = "EDITORIAL_RISK"


class SignalAdapterError(ValueError):
    """An intake record cannot honestly be offered to S-00 as a candidate."""


def golden_engine_fit_rules(
    *, directory: Optional[Path] = None
) -> ContractFitRules:
    """The active client's fit rules, bound to the fields intake spells.

    The one place the binding is made. A second caller that spelled the fields
    itself would be a second answer to the question #363 deliberately left to
    this seam, and the two would drift the moment intake renamed a field.
    """

    return contract_fit_rules(
        domain_field=DOMAIN_FIELD,
        risk_field=RISK_FIELD,
        directory=directory,
    )


def selection_candidate(record: Mapping[str, Any]) -> SelectionCandidate:
    """One intake record, as the candidate S-00 evaluates.

    ``record`` is a parsed ``signals_active.jsonl`` line — the record as intake
    wrote it, not a :class:`~src.lifecycle.signal_lifecycle.ResearchContext`
    round trip. ``from_dict`` normalises absence into ``""`` for most of its
    fields, and a fit rule handed ``""`` reads a signal that stated something
    empty rather than one that stated nothing. The two are the same refusal
    today and would stop being so the day a contract admitted a blank value, so
    the unnormalised record is what is carried.

    Raises :class:`SignalAdapterError` only for a record that cannot be
    identified. Every other refusal belongs to S-00's rules.
    """

    identity = record.get(SIGNAL_ID_FIELD)
    if not isinstance(identity, str) or not identity.strip():
        raise SignalAdapterError(
            f"the intake record states {SIGNAL_ID_FIELD}={identity!r}; a "
            "candidate is identified by its signal ID, which is the scope key "
            "every outcome of S-00 is recorded against, and a record without "
            "one cannot be skipped in a way anybody can trace back to it"
        )
    return SelectionCandidate(
        signal_id=identity,
        # A copy, so the record S-00 read cannot change under it; read-only, so
        # nothing between here and the stage can add the classification #365
        # did not write.
        signal=MappingProxyType(dict(record)),
        topic_key=_topic_key(record),
        source_locators=_source_locators(record),
    )


# ----------------------------------------------------------------------
# The two facts portfolio pressure compares (U-2 rule 4.2)
# ----------------------------------------------------------------------


def _topic_key(record: Mapping[str, Any]) -> Optional[str]:
    """The topic identity the record carries, or ``None`` when it carries none.

    The client's editorial domain, in the client's own spelling, because it is
    the only topic identity the record holds that the portfolio also holds —
    ``HEADLINE`` and ``INDUSTRY`` are prose and a sector, and neither is a key
    two signals can be equal on. Reading the field is not classifying with it:
    S-00's fit rule reads the same field for its own question, and nothing here
    writes, defaults or widens it.

    ``None`` for a record that states nothing, and also for one that states
    several domains: portfolio pressure is an exact match on one normalized
    value, and a composite key made of two domains would match nothing in the
    portfolio while looking like a key that could.
    """

    return _single_value(record.get(DOMAIN_FIELD))


def _source_locators(record: Mapping[str, Any]) -> tuple[str, ...]:
    """The locators the record states, or none.

    Soft input either way: an empty tuple means S-00 records no same-source
    resemblance, which is what a record that points nowhere honestly supports.
    """

    locator = _single_value(record.get(SOURCE_URL_FIELD))
    return () if locator is None else (locator,)


def _single_value(raw: Any) -> Optional[str]:
    """The one non-empty string this field states, or ``None``.

    A list of one states that one; a list of several states no single value,
    and neither does a list holding anything this cannot read. Mirrors
    ``signal_selection._stated_values``' posture — an unreadable member makes
    the whole field state nothing — because the alternative is to keep the
    members that parsed and compare on a value the record never stated alone.
    """

    if isinstance(raw, str):
        value = raw.strip()
        return value or None
    if isinstance(raw, Sequence) and len(raw) == 1:
        return _single_value(raw[0])
    return None
