"""The client's own rule records, loaded into a run (Step 4 §1, §2.3).

Issue #368, slice SL-6.47. The `K-NB-*` records have existed since NB-02c and
have been validated in CI since then, and until now nothing read them into a
run: ``clients/never_blank/rules/README.md`` said so in as many words, and
``src/knowledge/loader.py`` said the loader for them "arrives with its own
slice". This is that loader.

Two halves, not one
-------------------
Wiring the registry means both of these, and doing either alone leaves the other
gap open:

1. **The run-start gate gets a caller.** ``validate_at_run_start`` had none at
   all, so §8's ten rules ran in CI and never again — and CI checked the tree at
   the time of a commit, not the working tree a run reads. :func:`client_rules`
   calls it first, and a refused register is a refused load: nothing is returned
   and the run does not start, which is the `SKIP` at signal scope §8 describes.
2. **The records get a load path.** Every record is parsed with the register's
   own parser and its condition with the register's own grammar, so a client
   rule reaches a producer as the same :class:`~src.knowledge.loader.LoadedRecord`
   a universal record does. A file this cannot read is a refusal and never a
   record left out: silently skipping one would make a missing rule look exactly
   like a client that never wrote it, which is the whole defect #368 closes one
   layer up. The folder's own `README.md` is the one named exception — it is the
   documentation of the format, not a rule written in it — and it is named
   (:data:`DOCUMENTATION`) rather than detected, so nothing else can be skipped
   by looking unparseable.

What this does not do
---------------------
It does not merge the client's records into the universal register. §1 keeps them
in the client folder because the Client Contract is already the authority for a
client's rules and a shared register would create a second one, and copying them
into ``knowledge/`` would be exactly that. It hands back a set a producer reads
by id.

It also does not decide anything editorial. Which record fixes which value is
the producer's reading of the record's own ``## Influences`` entries — see
``src/strategy/adaptation_contract.py``.

Sources: `docs/editorial/architecture/05_STEP4_KNOWLEDGE_REGISTER.md` §1, §2.3,
§5, §8; `clients/never_blank/rules/README.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Optional

from src.editorial_core.arp import KnowledgeStatus, KnowledgeTier
from src.knowledge import records as record_format
from src.knowledge.grammar import ConditionError, parse_condition
from src.knowledge.loader import LoadedRecord, LoaderError, loaded_record
from src.knowledge.markdown import DocumentError, load_document
from src.knowledge.records import RecordError
from src.knowledge.run_start import validate_at_run_start
from src.knowledge.vocabulary import VocabularyError, load_vocabularies
from src.strategy.client_contracts import client_dir

#: The register, relative to the repository root, as the CI caller spells it.
REGISTER_DIR: Final[Path] = Path("knowledge")

#: Where a client's rule records live, relative to the client directory (§1).
RULES_DIRECTORY: Final[str] = "rules"

#: The one file a rules directory holds that is not a rule: the folder's own
#: README, which is what tells a person the format the files beside it are in.
#: It is named rather than detected, and it is the whole exception — every other
#: `.md` in the directory must read as a record, so a rule file that cannot be
#: parsed is still a refusal and never a record left out.
DOCUMENTATION: Final[frozenset[str]] = frozenset({"README.md"})

#: Where a client's stream contracts live. They are what the register validator
#: means by ``client_rule_paths``: a stream contract may declare the client's own
#: strength ladder, which §8 rule 9 measures against the universal one.
STREAMS_DIRECTORY: Final[str] = "streams"

#: The (status, tier) pairs a client's own record may carry (§2.3): an approved
#: client rule is tier 2, an unapproved one is a tier-3 candidate. Tier 1 is hard
#: platform policy and is not something a client writes, so a client folder
#: claiming it is refused here rather than obeyed.
CLIENT_PAIRS: Final[tuple[tuple[KnowledgeStatus, KnowledgeTier], ...]] = (
    (KnowledgeStatus.APPROVED_RULE, KnowledgeTier.APPROVED_CLIENT_RULE),
    (KnowledgeStatus.CANDIDATE, KnowledgeTier.EDITORIAL),
)


class ClientRulesError(ValueError):
    """The client's rules cannot be loaded into a run, so the run does not start."""


@dataclass(frozen=True, slots=True)
class ClientRuleSet:
    """Every rule record of one client, as it counts on the day of this run."""

    records: tuple[LoadedRecord, ...]
    #: The directory the records were read from, for a message that says where.
    path: str

    def record(self, identity: str) -> LoadedRecord:
        """The loaded record with this id. Raises :class:`ClientRulesError`.

        A named record that is not there is a refusal and never ``None``: the
        producers ask for a record by id because a record is the authority for a
        value, and a lookup that answered "nothing" would hand the caller an
        absent authority to fall back from.
        """

        for loaded in self.records:
            if loaded.identity == identity:
                return loaded
        held = ", ".join(item.identity for item in self.records) or "none at all"
        raise ClientRulesError(
            f"{self.path}: {identity} is not one of this client's rules, which "
            f"are {held}"
        )


def client_rules(
    *,
    directory: Optional[Path] = None,
    register: Optional[Path] = None,
    today: Optional[date] = None,
) -> ClientRuleSet:
    """The active client's rule records, after the run-start gate has passed.

    A **hard** input. Every path out of here is either a complete
    :class:`ClientRuleSet` or a :class:`ClientRulesError`: there is no partial
    set and no empty one standing in for a set nobody could read, because a
    producer that received a smaller set would build a contract missing a rule
    and nothing downstream could tell.
    """

    root = directory if directory is not None else client_dir()
    register_dir = register if register is not None else REGISTER_DIR

    decision = validate_at_run_start(
        register_dir, client_rule_paths=stream_contracts(root)
    )
    if not decision.may_start:
        raise ClientRulesError(
            f"{register_dir}: the run does not start on this register "
            f"({decision.reason}) — {decision.summary()}"
        )

    rules_dir = root / RULES_DIRECTORY
    if not rules_dir.is_dir():
        raise ClientRulesError(
            f"{rules_dir}: this client has no rules directory; the tier-2 rules a "
            "run applies are the client's to write, and an absent directory is a "
            "client nobody configured rather than a client with no rules"
        )

    try:
        vocabularies = load_vocabularies(register_dir)
    except VocabularyError as exc:
        raise ClientRulesError(str(exc)) from exc

    loaded: list[LoadedRecord] = []
    seen: dict[str, str] = {}
    when = today or date.today()
    for path in sorted(rules_dir.glob("*.md")):
        if path.name in DOCUMENTATION:
            continue
        try:
            record = record_format.parse_knowledge_record(load_document(path))
        except (DocumentError, RecordError) as exc:
            raise ClientRulesError(
                f"{path}: this client's rules cannot be read, so the run does not "
                f"start — {exc}"
            ) from exc
        if record.status == KnowledgeStatus.RETIRED.value:
            # §9.2: a retired record is kept for traceability and never loaded.
            continue
        try:
            condition = parse_condition(record.applies_when, vocabularies)
        except ConditionError as exc:
            raise ClientRulesError(f"{path}: {exc}") from exc
        try:
            item = loaded_record(record, condition, when)
        except LoaderError as exc:
            raise ClientRulesError(str(exc)) from exc
        _client_authority(item)
        first = seen.setdefault(item.identity, str(path))
        if first != str(path):
            raise ClientRulesError(
                f"{item.identity} is declared by both {first} and {path}; a "
                "finding cites the record that made it, and a name two records "
                "answer to names neither"
            )
        loaded.append(item)

    return ClientRuleSet(records=tuple(loaded), path=str(rules_dir))


def stream_contracts(directory: Path) -> tuple[Path, ...]:
    """This client's stream contracts, as ``client_rule_paths`` for the validator.

    The same glob ``scripts/ci/check_knowledge_register.py`` uses, so the run-start
    gate reads exactly the files CI reads: one validator, two callers, and no rule
    that only one of them applies.

    An absent directory **raises** rather than answering ``()``. §8 rule 9 is
    checked against these files — a client may declare its own strength ladder in
    one — so handing the gate an empty sequence would skip that rule while looking
    like a client that declared nothing. CI can answer ``()`` for a whole
    ``clients/`` tree that is not there; a run reading one named client cannot.
    """

    streams = directory / STREAMS_DIRECTORY
    if not streams.is_dir():
        raise ClientRulesError(
            f"{streams}: this client has no stream contracts. A client's own "
            "strength ladder is declared in one, and §8 rule 9 measures it against "
            "the universal ladder, so a run with none of them to read has skipped "
            "that check rather than passed it"
        )
    return tuple(sorted(streams.glob("*.md")))


def _client_authority(loaded: LoadedRecord) -> None:
    """A client's own record carries a client's own authority (§2.3)."""

    if (loaded.file_status, loaded.tier) in CLIENT_PAIRS:
        return
    raise ClientRulesError(
        f"{loaded.record.path}: {loaded.identity} is `{loaded.file_status.value}` "
        f"at tier {loaded.tier.value}. A client's own record is an approved rule "
        f"at tier {KnowledgeTier.APPROVED_CLIENT_RULE.value} or a candidate at "
        f"tier {KnowledgeTier.EDITORIAL.value}; the stronger tiers are the "
        "register's, and a client folder is not where hard platform policy or an "
        "invariant is written"
    )
