"""The RunSummary: what a run says it did, in public (Issue #293, slice SL-1).

Step 3 §3.2 gives the durable ledger one record per run, written by the run
harness after S-14, and §3.3 says what it holds: enough to compute every map
§11 indicator without the workspace, which expires in 90 days. Skip and degrade
rates by state code, counter usage, calls and tokens, first-pass rates,
fingerprints, publication results — the numbers that say whether the engine is
operating autonomously and what it costs to do so.

Public-safe **by construction** (patch S3-R1, P9)
-------------------------------------------------
The ledger is committed to a public repository, so §3.3 lists what a RunSummary
never contains: text, excerpts or interpretations; money amounts or prices;
raw provider or publisher error messages; free-text reasons; client-internal
detail beyond a closed category. Free text, raw errors and client specifics
stay in the 90-day workspace trace, where a reader with access can find them.

That rule is enforced twice, deliberately:

1. **The shape.** Every field here is an identifier, a count, a flag, a
   timestamp, a digest, a public URL or a member of a closed vocabulary, and
   each is declared with the alphabet it is drawn from — so a field that takes
   an identifier takes an identifier and not a phrase that happens to have no
   space in it. A reason is a :class:`~src.editorial_core.arp.StateCode` and a
   :class:`ReasonCategory` derived from it, never a sentence — which is what
   keeps the main indicator of autonomous operation countable (map §6.3).
2. **The validator.** :func:`verify_public_safe` reads a serialized summary and
   refuses free text, money and raw errors, whatever field they arrived in. It
   runs over every RunSummary at construction, and a reader can run it over a
   record loaded from the ledger. The shape alone would only be a promise about
   the fields that exist today; the validator is the one that still holds when
   a later slice adds a field, and it is why a caller cannot smuggle an error
   message through an identifier.

The three mechanical rules the validator applies are in :func:`verify_public_safe`.

Sources: ``docs/editorial/architecture/04_STEP3_STORAGE_AND_RUN_TRACE.md`` §3.2,
§3.3 and §6; ``docs/editorial/CANONICAL_EDITORIAL_MAP_v1.md`` §6.2 and §11.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic import ValidationError as _PydanticValidationError

from src.editorial_core.arp import (
    ArpOutcome,
    OutcomeRecord,
    OutcomeScope,
    StateCode,
    outcome_log,
)
from src.editorial_core.topology import CANONICAL_TOPOLOGY
from src.run.code_identity import CodeIdentity
from src.run.ledger import LedgerCommitStatus, write_record
from src.run.run_context import RunContext
from src.run.run_manifest import RunManifest
from src.run.run_workspace import StageRecord
from src.strategy.execution_context import ConfigurationIdentity

#: Schema version of this contract shape.
SCHEMA_VERSION = "1.0"

#: ``data/editorial/runs/<client>/<yyyy-mm>/<run_id>.json`` (§3.2). The month
#: is the run's own start month, so the ledger partitions by when the run
#: happened rather than by when somebody read it.
RUNS_DIRECTORY = "runs"

#: The keys a StageRecord's ``calls`` block uses (§4.2: count, tokens in and
#: out). Named here because this is the reader; the stages that make the calls
#: write them.
CALL_COUNT_KEY = "count"
TOKENS_IN_KEY = "tokens_in"
TOKENS_OUT_KEY = "tokens_out"

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_STAGE_ID_PATTERN = r"^S-(?:0\d|1[0-5])$"

#: What an identifier the ledger takes is made of: ASCII letters and digits,
#: joined by the characters this repository's own IDs already use — a UUID run
#: ID, ``never_blank``, ``L_strategy``, ``fp-unit-a-wix``, a publication key.
#: A closed alphabet and not "no whitespace", because a sentence in a script
#: that writes without spaces is still a sentence: the field an identifier
#: arrives in is the only place that knows an identifier was what belonged
#: there, so that is where it is said.
_IDENTIFIER_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9._+-]*$"

#: A scope key is identifiers joined by ``/`` (``unit-a/wix``, §0.3). The
#: separator is deliberately outside the identifier alphabet, so a client or a
#: run ID cannot carry one into the path its record is written at.
_SCOPE_KEY_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)*$"

#: The provider's own ID for a published post, whose shape belongs to the
#: provider and not to us — a LinkedIn URN is colon-separated. Still a token.
_EXTERNAL_ID_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9._:+-]*$"

#: An absolute http(s) URL, which is the only kind of URL §6 admits: the URL
#: of a published post is public because the post is. A string that is not one
#: is not made public by being put in this field.
_URL_PATTERN = (
    r"^https?://[A-Za-z0-9.-]+(?::[0-9]+)?"
    r"(?:/[A-Za-z0-9._~:/?#@!&'()*+,;=%-]*)?$"
)

#: The patterns above as the types the models declare. As types rather than as
#: ``Field(pattern=...)`` so that a tuple of identifiers is checked element by
#: element, which is where a ``fingerprint_ids`` entry would otherwise slip in.
_Identifier = Annotated[str, StringConstraints(pattern=_IDENTIFIER_PATTERN)]
_ScopeKey = Annotated[str, StringConstraints(pattern=_SCOPE_KEY_PATTERN)]
_ExternalId = Annotated[str, StringConstraints(pattern=_EXTERNAL_ID_PATTERN)]
_PublicUrl = Annotated[str, StringConstraints(pattern=_URL_PATTERN)]


class RunSummaryError(ValueError):
    """The summary was asked for something its contract refuses."""


class PublicSafetyError(RunSummaryError):
    """A record carries something the public ledger does not take (§3.3)."""


# ===========================================================================
# Closed vocabularies
# ===========================================================================


class ReasonCategory(str, Enum):
    """The coarse reason a scope ended as it did (§3.3).

    §3.3 asks for "a **reason category** from a closed vocabulary" beside the
    machine state code, and gives ``contract_risk`` as its example of the thing
    a category must replace: the client-internal reason itself. These
    categories therefore **group the map §6.2 state codes** rather than adding
    anything to them — a category is derived from the state, never chosen
    beside it (:func:`reason_category`), so the two can never disagree and a
    caller has nowhere to put a reason of its own.
    """

    CONTRACT_FIT = "contract_fit"
    CONTRACT_RISK = "contract_risk"
    EVIDENCE = "evidence"
    CLIENT_POSITION = "client_position"
    BOUNDARY = "boundary"
    STRATEGY = "strategy"
    COORDINATION = "coordination"
    PLAN = "plan"
    TEXT = "text"
    KNOWLEDGE = "knowledge"
    BUDGET = "budget"
    #: Not an editorial reason at all. A provider — a model provider or a
    #: research retrieval provider — refused, could not be reached, or returned
    #: nothing the engine may use, so no judgment was made about the material.
    #: It sits beside `BUDGET` because that is the other category naming a
    #: condition of the machinery rather than of the text, and it exists so that
    #: a provider outage is never counted as contract fit, as a source the role
    #: turned away or as thin evidence — the indicators would otherwise read an
    #: outage as editorial selectivity.
    PROVIDER = "provider"
    #: The calendar, not the material: per-destination cadence and portfolio
    #: pressure deferred a destination for this unit (AD-02 §2, the reason AD-02
    #: names `cadence`). Its own category because a cadence deferral is an
    #: *intended* gap in the calendar, while every other skip is one the engine
    #: would rather not have had — and map §6.3 reads the skip rate precisely to
    #: tell a system that has become too permissive from one whose calendar is
    #: emptying. Counting a deferral as contract fit would blur the two.
    CADENCE = "cadence"


#: Every state code, in its category. Total on purpose: a state with no
#: category would be a skip the indicators could not group, so a new member of
#: :class:`~src.editorial_core.arp.StateCode` is a new row here, reviewed with
#: the contract that produces it.
_REASON_CATEGORIES: Mapping[StateCode, ReasonCategory] = {
    StateCode.SIGNAL_OUTSIDE_CONTRACT: ReasonCategory.CONTRACT_FIT,
    # The role's own source-class criteria turned the signal away (Step 2 §1,
    # S-00). That is the contract deciding what it may start from, which is the
    # same question ``contract_fit`` groups, asked of the source rather than of
    # the topic.
    StateCode.SOURCE_NOT_ELIGIBLE: ReasonCategory.CONTRACT_FIT,
    StateCode.NO_ASSET_OR_ADMISSIBLE_INTERPRETATION: ReasonCategory.EVIDENCE,
    StateCode.CLIENT_POSITION_MISSING: ReasonCategory.CLIENT_POSITION,
    StateCode.EVIDENCE_CONFLICT_OUTSIDE_ANCHOR: ReasonCategory.EVIDENCE,
    StateCode.EVIDENCE_CONFLICT_IN_ANCHOR: ReasonCategory.EVIDENCE,
    StateCode.HIGH_STAKES_OUTSIDE_RISK_LEVEL: ReasonCategory.CONTRACT_RISK,
    StateCode.CLIENT_RULES_CONFLICT: ReasonCategory.CLIENT_POSITION,
    StateCode.SEVERAL_EQUAL_STRATEGIES: ReasonCategory.STRATEGY,
    StateCode.NO_ADMISSIBLE_STRATEGY: ReasonCategory.STRATEGY,
    StateCode.PROMISE_WIDER_THAN_BOUNDARY: ReasonCategory.BOUNDARY,
    StateCode.DESTINATIONS_CONTRADICT: ReasonCategory.COORDINATION,
    StateCode.PLAN_DOES_NOT_HOLD: ReasonCategory.PLAN,
    StateCode.STRUCTURAL_TEXT_FAILURE: ReasonCategory.TEXT,
    StateCode.INVENTED_OR_INADMISSIBLE_INTERPRETATION: ReasonCategory.BOUNDARY,
    StateCode.FACT_OR_PHRASING_FAILURE: ReasonCategory.TEXT,
    StateCode.PLATFORM_KNOWLEDGE_EXPIRED: ReasonCategory.KNOWLEDGE,
    # The mandatory set alone is over the request capacity (Step 4 §9.6). A
    # knowledge refusal, not a budget one: no call was made and no allowance was
    # spent — what did not fit is knowledge the stage may not go without.
    StateCode.MANDATORY_KNOWLEDGE_EXCEEDS_CAPACITY: ReasonCategory.KNOWLEDGE,
    StateCode.BUDGET_EXHAUSTED: ReasonCategory.BUDGET,
    # A provider failure, not a verdict: `source_eligibility.py` fails closed
    # without producing one, so nothing here describes the source.
    StateCode.PROVIDER_UNAVAILABLE: ReasonCategory.PROVIDER,
    StateCode.BOUNDARY_REENTRY_EXHAUSTED: ReasonCategory.BOUNDARY,
    # S-01 (Step 2 §1). Three of its states are conditions of the machinery:
    # retrieval delivered no artifact, the assessment produced no judgment, the
    # relevance screen produced no judgment. None of them says anything about
    # the material, and counting them as `evidence` would make a dead provider
    # read as thin material — the mirror of what `PROVIDER` was added for.
    StateCode.RESEARCH_FAILED: ReasonCategory.PROVIDER,
    StateCode.EVIDENCE_ASSESSMENT_FAILED: ReasonCategory.PROVIDER,
    StateCode.RELEVANCE_SCREEN_FAILED: ReasonCategory.PROVIDER,
    # These three are about the material and the audience, which is why they are
    # the ones a client may read as editorial. The core held nothing usable, or
    # the screen could not yet establish relevance, or it could not establish it
    # on the evidence it was shown.
    StateCode.NO_USABLE_EVIDENCE_CLAIM: ReasonCategory.EVIDENCE,
    StateCode.RELEVANCE_NOT_ESTABLISHED: ReasonCategory.EVIDENCE,
    StateCode.RELEVANCE_EVIDENCE_INSUFFICIENT: ReasonCategory.EVIDENCE,
    # The configured audience is the contract's, so a signal the screen refused
    # for that audience is the same question `contract_fit` groups for S-00 —
    # asked of the material rather than of the topic or the source.
    StateCode.SIGNAL_NOT_RELEVANT: ReasonCategory.CONTRACT_FIT,
    # S-02 (Step 2 §1). The one call producing no description is a condition of
    # the machinery, counted where S-01's three are; an item the reference check
    # dropped is about the material, and the material is the core.
    StateCode.MATERIAL_DESCRIPTION_FAILED: ReasonCategory.PROVIDER,
    StateCode.MATERIAL_WITHOUT_REFERENCE: ReasonCategory.EVIDENCE,
    # S-04 (Step 2 §1). Neither model call answering is a condition of the
    # machinery, counted where S-01's and S-02's are; a boundary that admits
    # only what the ladder's weakest level allows is about the boundary, and
    # `boundary` is where a client reads what the texts may mean.
    StateCode.BOUNDARY_GENERATION_FAILED: ReasonCategory.PROVIDER,
    StateCode.BOUNDARY_PROBE_FAILED: ReasonCategory.PROVIDER,
    StateCode.ONLY_LOW_STRENGTH_INTERPRETATION: ReasonCategory.BOUNDARY,
    # S-06 (Step 2 §1). The one call producing no usable answer is a condition of
    # the machinery, counted where S-01's, S-02's and S-04's are. "No provable
    # anchor" is not here because it is not a state of its own: S-06 records it
    # with `no_asset_or_admissible_interpretation`, which is already `evidence`.
    StateCode.ANCHOR_SELECTION_FAILED: ReasonCategory.PROVIDER,
    # S-07 (Step 2 §1, AD-02). Three exclusions and one unit-level state, each
    # grouped by whose rule refused: the contract's own table, a tier-1 platform
    # record, the calendar. A unit with nowhere to go is a fact about its
    # destinations as a set, which is what `coordination` groups.
    StateCode.DESTINATION_OUTSIDE_CONTRACT: ReasonCategory.CONTRACT_FIT,
    StateCode.HARD_PLATFORM_POLICY_FORBIDS: ReasonCategory.KNOWLEDGE,
    StateCode.DESTINATION_DEFERRED_BY_CADENCE: ReasonCategory.CADENCE,
    StateCode.NO_ELIGIBLE_DESTINATION: ReasonCategory.COORDINATION,
    # S-08 (Step 2 §1). The one call producing no candidate set is a condition
    # of the machinery, counted where S-01's, S-02's, S-04's and S-06's are.
    # `no_admissible_strategy` is not here because it is already `strategy`:
    # that state is candidates the engine produced and then refused, which is
    # an editorial fact, and keeping the two apart is what stops a provider
    # outage from reading as a destination nothing could be said on.
    StateCode.STRATEGY_GENERATION_FAILED: ReasonCategory.PROVIDER,
}


def reason_category(state_code: StateCode) -> ReasonCategory:
    """The category one state code is counted under."""

    try:
        return _REASON_CATEGORIES[state_code]
    except KeyError:
        raise RunSummaryError(
            f"state {state_code!r} has no reason category; every state the map "
            "defines is counted under one, or the indicators cannot group it"
        ) from None


class ErrorCategory(str, Enum):
    """Why a publication did not succeed, as a closed category (§3.3).

    The raw provider or publisher message stays in the 90-day workspace. What
    the ledger keeps is which kind of failure it was, because that is what a
    rate is computed over and it carries no payload.
    """

    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    VALIDATION = "validation"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNCLASSIFIED = "unclassified"


# ===========================================================================
# The public-safety validator
# ===========================================================================

#: A money amount, however it is spelled: a currency symbol, a currency code
#: however it is joined to its digits (``USD12``, ``12.40USD``), or the words a
#: price is written in. §3.3 allows call and token counts and nothing else that
#: is denominated.
#:
#: The codes are bounded by letters rather than by ``\b`` so that a code stuck
#: to a number is still a code, and every one of them contains a letter that is
#: not a hex digit — which is what keeps a 64-character digest from reading as
#: a currency by accident.
_MONEY_VALUE = re.compile(
    r"[$€£¥₽]"
    r"|(?i:(?<![a-z])(?:usd|eur|gbp|rub|aud)(?![a-z]))"
    r"|(?i:\d+(?:[.,]\d+)?\s*(?:dollars?|euros?|cents?|pounds?)\b)"
)

#: Field names that hold money. A count named ``tokens_in`` is a count; a
#: number named ``cost`` is not, whatever its units say.
_MONEY_FIELD = re.compile(
    r"(?i)(?:^|_)(?:cost|costs|price|prices|spend|amount|amounts|money|fee|"
    r"fees|charge|charges|billing|invoice|usd|eur)(?:_|$)"
)

#: What a raw provider or publisher error looks like. The vocabulary of a
#: traceback and of an exception rendering, which is exactly what a caller
#: reaches for when it wants to be helpful in the wrong file.
_RAW_ERROR = re.compile(
    r"(?i)traceback|stack ?trace|exception|errno|"
    r"at 0x[0-9a-f]+|File \"|[A-Za-z_][A-Za-z0-9_.]*Error\b"
)

#: Anything that is not printable ASCII, whitespace and control characters
#: included. The blunt free-text rule (see :func:`verify_public_safe`) is an
#: alphabet rather than a separator: "it has a space in it" would let a
#: sentence written in a script that needs no spaces straight through.
_NOT_A_TOKEN = re.compile(r"[^!-~]")


def verify_public_safe(payload: Mapping[str, Any]) -> None:
    """Raise unless this record is one the public ledger takes (§3.3, P9).

    Three mechanical rules over every value in the record, however deeply
    nested, because a rule that only covers today's fields stops covering the
    record the moment somebody adds one:

    **Free text.** Every string value must be a bare printable-ASCII token: no
    whitespace, and no character outside that alphabet. Every legitimate value
    in a RunSummary is such a token — an identifier, a state code, a category,
    an ISO timestamp, a digest, a URL — and prose is not. Whitespace alone
    would not do it: a sentence in a script that writes without spaces is
    still a sentence. It is a crude rule on purpose: it cannot be argued with,
    and a stage that wants to explain itself has the workspace trace for it.
    What it cannot know is which *kind* of token a field wanted, so the fields
    say that themselves (``_IDENTIFIER_PATTERN`` and the patterns beside it).

    **Money.** No currency symbol, currency code or price wording in a value;
    no field named for an amount; and no fractional number anywhere. Counts and
    tokens are whole; a decimal is what a price looks like.

    **Raw errors.** No traceback or exception vocabulary in a value. An error
    is recorded as an :class:`ErrorCategory`.

    Refuses rather than redacting: a record that had to be edited before it
    could be published is a record whose producer should be fixed.
    """

    for path, value in _walk(payload, ()):
        where = ".".join(path) or "<record>"
        key = path[-1] if path else ""
        if _MONEY_FIELD.search(key):
            raise PublicSafetyError(
                f"{where} is a money field; the ledger carries call and token "
                "counts and no amount (§3.3)"
            )
        if isinstance(value, bool):
            continue
        if isinstance(value, float):
            raise PublicSafetyError(
                f"{where} is the fractional number {value!r}; a RunSummary "
                "counts calls and tokens, and a decimal is what a price looks "
                "like (§3.3)"
            )
        if not isinstance(value, str):
            continue
        if _RAW_ERROR.search(value):
            raise PublicSafetyError(
                f"{where} reads as a raw provider or publisher error; the "
                "ledger carries an error category and the message stays in the "
                "90-day workspace (§3.3)"
            )
        if _MONEY_VALUE.search(value):
            raise PublicSafetyError(
                f"{where} states a money amount; the ledger carries call and "
                "token counts and no money (§3.3)"
            )
        if _NOT_A_TOKEN.search(value):
            raise PublicSafetyError(
                f"{where} is free text; a RunSummary records a state code and a "
                "closed reason category, and the words stay in the 90-day "
                "workspace trace (§3.3)"
            )


def _walk(
    value: Any, path: tuple[str, ...]
) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Every (path, value) pair in a record, containers included.

    A container is yielded with a ``None`` value so that the field-name rules
    see it: ``costs: [1, 2]`` reaches its leaves under the keys ``0`` and
    ``1``, and a check that only ever saw leaf keys would never see the word
    ``costs`` at all.
    """

    if isinstance(value, Mapping):
        yield path, None
        for key, item in value.items():
            yield from _walk(item, path + (str(key),))
        return
    if isinstance(value, (list, tuple)):
        yield path, None
        for index, item in enumerate(value):
            yield from _walk(item, path + (str(index),))
        return
    yield path, value


# ===========================================================================
# The record
# ===========================================================================


class _Record(BaseModel):
    """Every part of a summary is immutable and rejects fields it does not know."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RunScope(_Record):
    """One scope the run had: a signal, a unit, a destination, a publication.

    Handed to :meth:`RunSummary.for_run` by the harness, which is the only
    thing that knows what the run set out to do. A scope that recorded no
    outcome still appears in the summary, as a ``RESOLVE``: "six destinations
    were attempted and none was skipped" and "one destination was attempted"
    are different runs, and a summary built only from the outcomes could not
    tell them apart.
    """

    scope: OutcomeScope
    scope_key: _ScopeKey


class ScopeOutcome(_Record):
    """How one scope ended (§3.3): the outcome, the state code, the category."""

    scope: OutcomeScope
    scope_key: _ScopeKey
    outcome: ArpOutcome
    #: Absent when nothing was left unresolved — a scope that simply completed
    #: has no §6.2 state, and inventing one would make the indicators count it.
    state_code: Optional[StateCode] = None
    category: Optional[ReasonCategory] = None

    @model_validator(mode="after")
    def _final_and_categorised(self) -> "ScopeOutcome":
        if self.outcome is ArpOutcome.REPLAN:
            raise ValueError(
                f"{self.scope_key} is recorded as ending in a REPLAN; a REPLAN "
                "is a route to another attempt, so the final state of a scope "
                "is where those attempts ended"
            )
        if self.outcome is not ArpOutcome.RESOLVE and self.state_code is None:
            raise ValueError(
                f"{self.scope_key} ends in {self.outcome.value} with no state "
                "code; a skip or a degrade is counted by the state that caused "
                "it (map §6.3)"
            )
        expected = (
            None if self.state_code is None else reason_category(self.state_code)
        )
        if self.category != expected:
            raise ValueError(
                f"{self.scope_key} records category {self.category!r} for state "
                f"{self.state_code!r}; the category is derived from the state "
                "and is not a second opinion about it"
            )
        return self


class CounterUsage(_Record):
    """One attempt counter, spent against its limit (§3.3)."""

    counter: _Identifier
    #: Summed across the scope keys that spent it: a counter is counted per
    #: scope, and what the indicator wants is what the run spent in total.
    used: int = Field(ge=0)
    limit: int = Field(ge=1)


class StageCalls(_Record):
    """Model calls and tokens for one stage, across its executions (§3.3)."""

    stage: str = Field(pattern=_STAGE_ID_PATTERN)
    calls: int = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)


class DestinationFirstPass(_Record):
    """First-pass flags for one destination (§3.3).

    Plan approved on attempt 1, text accepted on version 1. The rate over these
    is what says whether the engine is getting it right the first time, which
    is why they are per destination and not per run.
    """

    destination: _Identifier
    plan_first_pass: bool
    text_first_pass: bool


class PublicationResult(_Record):
    """What happened at one destination's publication (§3.3, §6).

    The URL and external ID of a published post are public by definition — the
    post is public — which is why §6 lists them among what the ledger takes.
    """

    destination: _Identifier
    published: bool
    external_id: Optional[_ExternalId] = None
    url: Optional[_PublicUrl] = None
    #: Present only for a failure, and always a category (§3.3).
    error_category: Optional[ErrorCategory] = None

    @model_validator(mode="after")
    def _result_is_one_thing(self) -> "PublicationResult":
        if self.published and self.error_category is not None:
            raise ValueError(
                f"{self.destination} is recorded as published and as having "
                f"failed with {self.error_category.value}"
            )
        if not self.published and (self.external_id or self.url):
            raise ValueError(
                f"{self.destination} did not publish but carries an external "
                "reference; a post that does not exist has no ID and no URL"
            )
        return self


class WorkspaceRef(_Record):
    """Where the run's 90-day workspace is, and until when (§3.3).

    The summary outlives the workspace, so it says where the detail was and
    when it stopped being there. A reader that finds a state code here and
    wants the reason it stands for needs both.
    """

    artifact_name: _Identifier
    retention_days: int = Field(ge=1)
    expires_on: date
    manifest_digest: str = Field(pattern=_DIGEST_PATTERN)


class RunSummary(_Record):
    """One run, as the durable ledger keeps it (§3.2, §3.3)."""

    schema_version: str = SCHEMA_VERSION
    run_id: _Identifier
    client: _Identifier
    started_at: datetime
    signal_ids: tuple[_Identifier, ...] = Field(min_length=1)
    unit_ids: tuple[_Identifier, ...] = ()
    #: Absent when the run could not resolve its own code identity: a
    #: fabricated one would be worse than none (``src/run/code_identity.py``).
    code_identity: Optional[CodeIdentity] = None
    configuration_identity: Optional[ConfigurationIdentity] = None
    #: Which engine the run executed (CE-1), copied from its manifest so a
    #: reader with the ledger alone can still refuse a foreign topology.
    topology_digest: str = Field(pattern=_DIGEST_PATTERN)
    scope_outcomes: tuple[ScopeOutcome, ...] = ()
    counters: tuple[CounterUsage, ...] = ()
    stage_calls: tuple[StageCalls, ...] = ()
    calls_total: int = Field(ge=0)
    call_budget_limit: int = Field(ge=1)
    first_pass: tuple[DestinationFirstPass, ...] = ()
    fingerprint_ids: tuple[_Identifier, ...] = ()
    publications: tuple[PublicationResult, ...] = ()
    #: The AD-03 observation: a unit that looked like two (§3.3).
    split_candidate: bool = False
    #: V-T02 findings that matched no recorded interpretation — the U-1
    #: feedback signal. The findings themselves go to the knowledge queue.
    vt02_unmatched_findings: int = Field(default=0, ge=0)
    workspace: WorkspaceRef
    ledger_commit: LedgerCommitStatus
    #: Publication keys whose marker could not be made durable (§3.6 point 5).
    publication_unconfirmed: tuple[_Identifier, ...] = ()

    @field_validator("schema_version", mode="after")
    @classmethod
    def _schema_version_known(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {SCHEMA_VERSION!r}; got {value!r}"
            )
        return value

    @field_validator("started_at", mode="after")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _public_safe_and_consistent(self) -> "RunSummary":
        if self.calls_total > self.call_budget_limit:
            raise ValueError(
                f"the run records {self.calls_total} model calls against a "
                f"budget of {self.call_budget_limit}; RunCallBudget refuses the "
                "call that would exceed it, so a run cannot have made more"
            )
        counted = sum(entry.calls for entry in self.stage_calls)
        if self.stage_calls and counted != self.calls_total:
            raise ValueError(
                f"the per-stage calls add up to {counted} but the total is "
                f"{self.calls_total}; the total is the sum, not a second count"
            )
        # Public-safe by construction: the shape of this record allows no
        # sentence, but a caller can still put one in an identifier, and this
        # is the last place before the ledger where that is refusable.
        verify_public_safe(self.model_dump(mode="json"))
        return self

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def for_run(
        cls,
        *,
        run_context: RunContext,
        manifest: RunManifest,
        records: Sequence[StageRecord],
        scopes: Sequence[RunScope],
        client: str,
        signal_ids: Sequence[str],
        workspace: WorkspaceRef,
        call_budget_limit: int,
        ledger_commit: LedgerCommitStatus,
        unit_ids: Sequence[str] = (),
        code_identity: Optional[CodeIdentity] = None,
        first_pass: Sequence[DestinationFirstPass] = (),
        fingerprint_ids: Sequence[str] = (),
        publications: Sequence[PublicationResult] = (),
        split_candidate: bool = False,
        vt02_unmatched_findings: int = 0,
        publication_unconfirmed: Sequence[str] = (),
        counter_limits: Optional[Mapping[str, int]] = None,
    ) -> "RunSummary":
        """Summarize one finished run from its own trace.

        The three things an indicator is computed from — how each scope ended,
        what the counters cost and what the calls cost — are **derived from the
        StageRecords**, not supplied. A summary that took them as arguments
        would be a second, optimistic description of the run beside the trace,
        and §4.4 makes the trace the thing that answers "why was this
        destination skipped?".
        """

        calls = stage_call_totals(records)
        return cls(
            run_id=run_context.run_id,
            client=client,
            started_at=run_context.started_at,
            signal_ids=tuple(signal_ids),
            unit_ids=tuple(unit_ids),
            code_identity=code_identity,
            configuration_identity=run_context.configuration_identity,
            topology_digest=manifest.topology_digest,
            scope_outcomes=final_states(scopes, records),
            counters=counter_usage(records, limits=counter_limits),
            stage_calls=calls,
            calls_total=sum(entry.calls for entry in calls),
            call_budget_limit=call_budget_limit,
            first_pass=tuple(first_pass),
            fingerprint_ids=tuple(fingerprint_ids),
            publications=tuple(publications),
            split_candidate=split_candidate,
            vt02_unmatched_findings=vt02_unmatched_findings,
            workspace=workspace,
            ledger_commit=ledger_commit,
            publication_unconfirmed=tuple(publication_unconfirmed),
        )

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def relative_path(self) -> str:
        """``runs/<client>/<yyyy-mm>/<run_id>.json`` (§3.2)."""

        month = f"{self.started_at.year:04d}-{self.started_at.month:02d}"
        return f"{RUNS_DIRECTORY}/{self.client}/{month}/{self.run_id}.json"

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible: enums as values, timestamps as ISO-8601 UTC."""

        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunSummary":
        """Strictly reload one summary (P7), or say what is wrong with it.

        A record that is not public-safe fails here too, as a
        :class:`RunSummaryError` carrying the refusal: the construction-time
        check is a pydantic validator, so its :class:`PublicSafetyError` is
        wrapped on the way out. :func:`verify_public_safe` is the direct form,
        for a reader that wants the refusal itself.
        """

        if not isinstance(data, Mapping):
            raise RunSummaryError(
                f"RunSummary.from_dict expects a mapping; got {type(data).__name__}"
            )
        try:
            return cls.model_validate(dict(data))
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            loc = " -> ".join(str(x) for x in first["loc"]) if first["loc"] else "value"
            raise RunSummaryError(
                f"RunSummary field '{loc}': {first['msg']}"
            ) from exc


def write_run_summary(
    summary: RunSummary, *, root: Optional[Path] = None
) -> Path:
    """Write one RunSummary into the durable ledger and return its path.

    One file per record (P4), create-once (P1). Committing it is a separate
    step, because a commit can fail and a written record must not depend on
    one (§3.1).
    """

    return write_record(summary.relative_path(), summary.to_dict(), root=root)


# ===========================================================================
# Derivation from the trace (§4.1, §4.4)
# ===========================================================================


def final_states(
    scopes: Sequence[RunScope], records: Sequence[StageRecord]
) -> tuple[ScopeOutcome, ...]:
    """How each scope of the run ended, in the order the harness declares them.

    The final state of a scope is its **last non-REPLAN outcome**: a REPLAN is
    a route to another attempt, and what a reader wants to know is where those
    attempts ended. A scope with no outcome at all resolved — nothing about it
    was ever unresolved.

    An outcome recorded for a scope the harness did not declare is appended
    rather than dropped. Budget exhaustion records SKIPs for destinations it
    never started (§0.4), and a skip missing from the summary is the one thing
    the skip rate must never lose.
    """

    latest: dict[tuple[OutcomeScope, str], OutcomeRecord] = {}
    for entry in outcome_log(records):
        outcome = entry.outcome
        if outcome.outcome is ArpOutcome.REPLAN:
            continue
        key = (outcome.scope, outcome.scope_key or entry.scope_key)
        latest[key] = outcome

    declared = [(scope.scope, scope.scope_key) for scope in scopes]
    ordered = declared + sorted(
        (key for key in latest if key not in declared),
        key=lambda key: (key[0].value, key[1]),
    )

    states: list[ScopeOutcome] = []
    seen: set[tuple[OutcomeScope, str]] = set()
    for key in ordered:
        if key in seen:
            continue
        seen.add(key)
        final = latest.get(key)
        if final is None:
            states.append(
                ScopeOutcome(
                    scope=key[0], scope_key=key[1], outcome=ArpOutcome.RESOLVE
                )
            )
            continue
        states.append(
            ScopeOutcome(
                scope=key[0],
                scope_key=key[1],
                outcome=final.outcome,
                state_code=final.state_code,
                category=reason_category(final.state_code),
            )
        )
    return tuple(states)


def counter_usage(
    records: Sequence[StageRecord],
    *,
    limits: Optional[Mapping[str, int]] = None,
) -> tuple[CounterUsage, ...]:
    """What each attempt counter cost this run (§3.3).

    Read from the outcomes, which carry the attempt and the limit they were
    spent against (§0.3): per scope key the highest attempt is what that scope
    spent, and the counter's cost is those summed. Every counter the topology
    declares is reported, including the ones nothing spent, so that two runs'
    summaries compare row for row.

    The run-scoped ``RunCallBudget`` is not here: it is not an attempt counter,
    and ``calls_total`` against ``call_budget_limit`` is where it is reported.
    """

    declared = {
        counter.counter_id: counter.default_limit
        for counter in CANONICAL_TOPOLOGY.counters
    }
    for counter_id, limit in (limits or {}).items():
        if counter_id not in declared:
            raise RunSummaryError(
                f"unknown counter {counter_id!r}; the topology declares "
                f"{', '.join(sorted(declared))}"
            )
        declared[counter_id] = limit

    spent: dict[tuple[str, str], int] = {}
    recorded_limits: dict[str, int] = {}
    for entry in outcome_log(records):
        outcome = entry.outcome
        if outcome.counter is None or outcome.attempt is None:
            continue
        if outcome.counter not in declared:
            continue  # RunCallBudget, reported as calls rather than as a counter
        key = (outcome.counter, outcome.scope_key or entry.scope_key)
        spent[key] = max(spent.get(key, 0), outcome.attempt)
        if outcome.limit is not None:
            recorded_limits[outcome.counter] = outcome.limit

    return tuple(
        CounterUsage(
            counter=counter_id,
            used=sum(value for key, value in spent.items() if key[0] == counter_id),
            limit=recorded_limits.get(counter_id, limit_in_force),
        )
        for counter_id, limit_in_force in sorted(declared.items())
    )


def stage_call_totals(records: Sequence[StageRecord]) -> tuple[StageCalls, ...]:
    """Model calls and tokens per stage, across every execution of it (§3.3).

    A stage that recorded no ``calls`` block made none: the block is where a
    stage states what it spent, and its absence is zero rather than unknown. A
    value that is not a whole count is refused — the totals reach a public
    ledger, and a fractional one is how an amount would get there.
    """

    totals: dict[str, list[int]] = {}
    for record in records:
        calls = record.calls or {}
        row = totals.setdefault(record.stage, [0, 0, 0])
        row[0] += _count(calls, CALL_COUNT_KEY, record.stage)
        row[1] += _count(calls, TOKENS_IN_KEY, record.stage)
        row[2] += _count(calls, TOKENS_OUT_KEY, record.stage)
    return tuple(
        StageCalls(stage=stage, calls=row[0], tokens_in=row[1], tokens_out=row[2])
        for stage, row in sorted(totals.items())
    )


def _count(calls: Mapping[str, Any], key: str, stage: str) -> int:
    value = calls.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RunSummaryError(
            f"{stage} records {key}={value!r}; calls and tokens are whole "
            "counts, and the ledger carries no other kind of number (§3.3)"
        )
    return value
