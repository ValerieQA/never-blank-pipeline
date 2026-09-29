"""The Client Contract's fit rules: what this client takes as a topic and a risk.

Issue #363, slice SL-6.45. ``ContractFitRules`` is a **required** input of S-00
(``signal_selection.py``), it refuses an empty table by design — "an empty table
admits every signal and records that as a fit" — and until now nothing outside
the tests built one. This is the producer, following #337's ``client_contract()``
pattern exactly: a human-editable document, a loader, a typed runtime value, and
a raise where the document is missing rather than a default the engine picked.

Two rules, and no more
----------------------
The grammar is deliberately minimal — ``FitRule(rule_id, fit, field, admits)``,
where "a rule reads one field of the signal and admits a listed set of values".
Never Blank's contract needs exactly two of them:

======================  =====================  =================================
``FIT-NB-TOPIC-01``     ``OUTSIDE_TOPICS``     the five admitted domains
``FIT-NB-RISK-01``      ``OUTSIDE_RISK_LEVEL`` ``low``
======================  =====================  =================================

Three consequences of that grammar this module respects rather than works
around:

* **There is no deny construct.** The out-of-domain list — personalised medical,
  legal and financial advice, political advocacy, explicit sexual content,
  materially harmful instructions — is enforced by its *absence* from ``admits``
  and is written in the contract as a note for a person. A "forbidden topics"
  table would be new grammar, and inventing grammar is out of this slice.
* **A refusal cannot say which forbidden category applied.** It carries a
  ``rule_id`` and one of three :class:`SignalFit` codes, not "refused because it
  was medical advice". That is a real expressive limit of the canonical design.
  It is noted here and :class:`SignalFit` is not extended.
* **``adjacent_business`` is load-bearing.** ``FitRule.check`` computes
  ``passed = bool(stated) and all(value in admits)`` — a strict allow-list over
  every value the signal states. The owner's decision says the domain is
  explicitly not to be read as a narrow allow-list that rejects legitimate
  adjacent SMB material for a missing noun, and the fifth admitted value is
  where that adjacency lands. Dropping it from the contract silently converts
  the owner's decision into the thing the owner forbade.

The field binding is unresolved, and says so
--------------------------------------------
``FitRule.field`` is "the E-01 field the rule reads, **spelled as the intake
record spells it**". The real intake record (``data/research/signals_active.jsonl``)
carries neither a domain field nor a risk field, and ``knowledge/vocab/`` declares
no E-01 fields at all — so a rule reading a name invented here would refuse every
real signal, silently and forever, because ``bool(stated)`` would be false.

Normalising a real research signal into the fields S-00 reads is seam 1, which
#351 owns and resolves against the actual adapter and schema. So this module
**never names those fields**: :func:`contract_fit_rules` takes them as required
keyword arguments with no default, and a caller with no binding gets a
``TypeError`` rather than a table built on a guess. The unresolvedness is
structural, not a placeholder string, and no synthetic field is added to any
signal to make a fit test pass.

What the contract therefore stores is the owner-approved *semantics* only — the
admitted domain vocabulary and the admitted risk level, as client configuration
carrying no intake spelling.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final, Optional

from src.editorial_core.signal_selection import (
    ContractFitRules,
    FitRule,
    SignalFit,
    SignalSelectionError,
)
from src.knowledge.markdown import Document, DocumentError, load_document
from src.strategy.client_contract import (
    CONTRACT_FILE,
    ClientConfigurationError,
)
from src.strategy.client_contracts import client_dir

#: The section listing the domains this client takes as an editorial topic.
DOMAIN_SECTION: Final[str] = "Editorial domain"

#: The section listing the risk levels this client takes.
RISK_SECTION: Final[str] = "Risk level"

#: The rule IDs a ``SKIP`` at S-00 is recorded with. They are the contract's, not
#: the register's: no ``K-`` prefix, because a client's fit rule is not a
#: universal knowledge record and a trace that cited one as if it were would send
#: a reader to a file that does not exist.
TOPIC_RULE_ID: Final[str] = "FIT-NB-TOPIC-01"
RISK_RULE_ID: Final[str] = "FIT-NB-RISK-01"

_COMMENT = re.compile(r"<!--.*?-->", re.S)


def parse_contract_fit_rules(
    document: Document, *, domain_field: str, risk_field: str
) -> ContractFitRules:
    """Read one contract document's fit configuration.

    Raises :class:`ClientConfigurationError` for anything missing, empty or
    malformed. There is no path through this function that returns a table
    built from less than the contract states: a partially read contract admits
    signals the client never agreed to, and S-00 records that as a fit.
    """

    admits = _values(document, DOMAIN_SECTION)
    risk = _values(document, RISK_SECTION)
    try:
        return ContractFitRules(
            rules=(
                FitRule(
                    rule_id=TOPIC_RULE_ID,
                    fit=SignalFit.OUTSIDE_TOPICS,
                    field=domain_field,
                    admits=admits,
                ),
                FitRule(
                    rule_id=RISK_RULE_ID,
                    fit=SignalFit.OUTSIDE_RISK_LEVEL,
                    field=risk_field,
                    admits=risk,
                ),
            )
        )
    except SignalSelectionError as exc:
        raise ClientConfigurationError(f"{document.path}: {exc}") from exc


def load_contract_fit_rules(
    path: Path, *, domain_field: str, risk_field: str
) -> ContractFitRules:
    """Read the contract at this path as S-00's fit table."""

    if not path.is_file():
        raise ClientConfigurationError(
            f"{path}: this client has no contract, so nothing states which topics "
            "it takes or what risk it accepts; S-00 with no fit table would "
            "select every signal it was handed and record that the contract "
            "agreed"
        )
    try:
        document = load_document(path)
    except DocumentError as exc:
        raise ClientConfigurationError(str(exc)) from exc
    return parse_contract_fit_rules(
        document, domain_field=domain_field, risk_field=risk_field
    )


def contract_fit_rules(
    *, domain_field: str, risk_field: str, directory: Optional[Path] = None
) -> ContractFitRules:
    """The active client's fit rules, bound to the fields S-00 will read.

    A **hard** input, like ``client_contract()``: a missing or incomplete
    contract raises, because the one thing S-00 must never be able to do by
    omission is agree.

    ``domain_field`` and ``risk_field`` have no defaults on purpose. They are
    the E-01 field names of the *normalised* signal, and normalisation is seam 1
    — #351's, resolved there against the real adapter or stopped and raised.
    Calling this with no binding is a ``TypeError`` from the signature itself,
    which is the one refusal a caller cannot mistake for an empty table.
    """

    for name, value in (("domain_field", domain_field), ("risk_field", risk_field)):
        if not value.strip():
            raise ClientConfigurationError(
                f"`{name}` is {value!r}; a fit rule reads a named field of the "
                "signal, and a rule reading an unnamed one refuses every signal "
                "there is. The E-01 spelling comes from the intake normalisation "
                "(#351), not from this producer"
            )
    if domain_field.strip() == risk_field.strip():
        raise ClientConfigurationError(
            f"the topic rule and the risk rule would both read {domain_field!r}; "
            "they are two rules about two different things, and one field "
            "answering both means one of them was never bound"
        )

    root = directory if directory is not None else client_dir()
    return load_contract_fit_rules(
        root / CONTRACT_FILE, domain_field=domain_field, risk_field=risk_field
    )


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _values(document: Document, section: str) -> tuple[str, ...]:
    """The bullets of one configuration section, in the client's own spelling."""

    body = document.section(section)
    if body is None:
        raise ClientConfigurationError(
            f"{document.path}: no `## {section}` section; that is where the "
            "client states it, and a fit rule built without it would admit "
            "whatever the signal happened to say"
        )
    values: list[str] = []
    for line in _without_comments(body, document.path).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("- "):
            raise ClientConfigurationError(
                f"{document.path}: every entry of `## {section}` is a bullet "
                f"(`- `); got {stripped[:60]!r}"
            )
        value = stripped[2:].strip()
        if not value:
            raise ClientConfigurationError(
                f"{document.path}: `## {section}` has an empty bullet"
            )
        values.append(value)
    if not values:
        raise ClientConfigurationError(
            f"{document.path}: `## {section}` admits nothing. A rule that admits "
            "nothing refuses every signal, and a section left empty is a "
            "configuration nobody meant to write rather than a client that takes "
            "no topic at all"
        )
    repeated = sorted({value for value in values if values.count(value) > 1})
    if repeated:
        raise ClientConfigurationError(
            f"{document.path}: `## {section}` lists "
            + ", ".join(repeated)
            + " twice; saying a value twice admits no more than saying it once"
        )
    return tuple(values)


def _without_comments(body: str, path: str) -> str:
    """People-only notes removed; an unclosed one is refused rather than read."""

    stripped = _COMMENT.sub("", body)
    if "<!--" in stripped or "-->" in stripped:
        raise ClientConfigurationError(
            f"{path}: an HTML comment is not closed (`<!--` … `-->`), so what is "
            "a note for a person and what is configuration cannot be told apart"
        )
    return stripped
