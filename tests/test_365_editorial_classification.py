"""Editorial domain and risk on the intake record.

Issue #365, slice SL-6.46. #363 produced S-00's ``ContractFitRules`` and #351
then stopped on the third blocker: the two E-01 fields those rules read exist
on no production record. ``SelectionCandidate.signal`` is "the intake record
itself, spelled as intake spells it", so seam 1 may not invent them — they have
to be produced upstream, and Stage 4 enrichment is where the record is written.

What these tests are for
------------------------
Each one runs the real chain — **contract document → S-00's producer → the
rendered prompt → the answer → the record → S-00** — with the provider replaced
and nothing else, and each is written so that a bypass fails it:

* a literal vocabulary in the prompt or in ``enrich.py`` fails the two tests
  that edit the contract or read those files;
* persisting the model's own string fails the invented-category test;
* reading an invented category as a deliberate "outside the vocabulary" fails
  that same test, which is where the two are held apart;
* normalising case or whitespace before admitting fails the respelling test;
* restoring the bare ``except Exception: enriched = {}`` fails the failure test,
  because ``cannot_answer`` would collapse into silence;
* any default, ``or`` or ``setdefault`` for an absent classification fails the
  S-00 refusal test;
* a backfill of the historical records fails the pre-slice test.

The one distinction being held
------------------------------
S-00 refuses ``outside_admitted`` and ``cannot_answer`` alike — it cannot tell
them apart and does not need to. The record must: a signal deliberately
classified outside the client's vocabulary and a classifier that failed are two
different facts about the run, and reading the second as the first is the
``cannot_answer`` defect this repository names as a quality class.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import scripts.research.enrich as enrich
from scripts.research.enrich import (
    ADMITTED,
    CANNOT_ANSWER,
    DOMAIN_FIELD,
    DOMAIN_OUTCOME_FIELD,
    OUTSIDE_ADMITTED,
    RISK_FIELD,
    RISK_OUTCOME_FIELD,
    enrich_signal,
)
from src.editorial_core.signal_selection import (
    SelectionCandidate,
    SignalFit,
    select_signal,
)
from src.lifecycle.signal_lifecycle import _KNOWN_JSONL_KEYS, ResearchContext
from src.strategy.client_contract import CONTRACT_FILE
from src.strategy.contract_fit import contract_fit_rules
from tests.test_298_signal_selection import _Transport, _role

_REPO_ROOT = Path(__file__).resolve().parents[1]

NEVER_BLANK = _REPO_ROOT / "clients" / "never_blank"
CONTRACT = NEVER_BLANK / CONTRACT_FILE
PROMPT = _REPO_ROOT / "config" / "prompts" / "research" / "enrich.yaml"
ENRICH_SOURCE = Path(enrich.__file__)
SIGNALS_ACTIVE = _REPO_ROOT / "data" / "research" / "signals_active.jsonl"

#: The four keys #365 adds to the record. Two values and, beside each, what
#: became of the classification that would have produced it.
CLASSIFICATION_KEYS = (
    DOMAIN_FIELD, DOMAIN_OUTCOME_FIELD, RISK_FIELD, RISK_OUTCOME_FIELD,
)

#: A category no client contract lists, used where a test needs an answer the
#: contract does not admit. It is never written to any record — that is what
#: the tests below assert.
UNADMITTED = "celebrity_gossip"

#: The classifier protocol token, owner-approved 2026-09-29, spelled here as
#: the literal the owner approved rather than read from `enrich`. A constant
#: compared against itself agrees with whatever it was changed to, and this
#: token is the owner's decision and not the implementation's to restate.
NONE_OF_THESE = "none_of_these"


# ── the provider, replaced ───────────────────────────────────────────────────

class _Answer:
    """The enrichment call answered without a provider, keeping its prompts."""

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.prompts: list[tuple[str, str]] = []

    def __call__(
        self,
        system: str,
        user: str,
        json_mode: bool = False,
        model: str | None = None,
    ) -> str:
        self.prompts.append((system, user))
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload)


def _unavailable(*args: Any, **kwargs: Any) -> str:
    """A provider that does not answer at all."""

    raise RuntimeError("the enrichment model did not answer")


class _UncalledTransport:
    """A source-eligibility transport the fit rules never get past."""

    def complete(self, *, instructions: str, request: str) -> str:
        raise AssertionError(
            "the fit rules refused the signal, so no judgment was to be paid for"
        )


# ── helpers ──────────────────────────────────────────────────────────────────

def _signal(**overrides: Any) -> dict:
    """One discovered signal as Stage 4 receives it, classified by nothing."""

    signal: dict[str, Any] = {
        "SIGNAL_ID": "sig-365",
        "HEADLINE": "A small agency rebuilt its intake in a week",
        "SOURCE_NAME": "Example Trade Press",
        "SOURCE_URL": "https://example.invalid/intake",
        "SOURCE_DATE": "2026-09-01",
        "SIGNAL_TYPE": "trend",
        "REGION": "Global",
        "INDUSTRY": "Professional services",
        "raw_summary": "The agency replaced a manual intake form.",
    }
    signal.update(overrides)
    return signal


def _payload(**overrides: Any) -> dict:
    """What the enrichment model answers, beside the classification."""

    payload: dict[str, Any] = {
        "CORE_FACT": "The agency rebuilt its intake in five days.",
        "SOURCE_FOR_CASE": "https://example.invalid/intake",
        "REAL_COMPANY_EXAMPLE": "Example Agency",
        "CONFIDENCE": "high",
        "BUSINESS_LESSON": "Intake is a process, not a form.",
    }
    payload.update(overrides)
    return payload


def _copied(tmp_path: Path) -> Path:
    """The real contract, copied so a test may edit it and see the difference."""

    directory = tmp_path / "client"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CONTRACT_FILE).write_text(
        CONTRACT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return directory


def _edited(tmp_path: Path, old: str, new: str) -> Path:
    """The real contract with one exact substitution, as a keeper would edit it."""

    directory = _copied(tmp_path)
    path = directory / CONTRACT_FILE
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} is not one place in the contract"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return directory


def _fit_rules():
    """S-00's production fit table, bound to the fields this slice produces."""

    return contract_fit_rules(
        domain_field=DOMAIN_FIELD, risk_field=RISK_FIELD, directory=NEVER_BLANK
    )


def _selection(record: dict, transport: Any):
    """The record as S-00 reads it: the intake record itself, unaltered."""

    return select_signal(
        SelectionCandidate(signal_id=record.get("SIGNAL_ID") or "sig", signal=record),
        fit_rules=_fit_rules(),
        role=_role(),
        transport=transport,
    )


def _enriched(monkeypatch, transport: Any, signal: dict | None = None) -> dict:
    monkeypatch.setattr(enrich, "chat", transport)
    return enrich_signal(signal if signal is not None else _signal())


def _git(*args: str) -> tuple[int, str]:
    done = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), *args], capture_output=True, text=True
    )
    return done.returncode, done.stdout.strip()


# ===========================================================================
# 1. The vocabulary is the contract's
# ===========================================================================


def test_the_rendered_prompt_offers_the_contracts_admitted_values(monkeypatch):
    """Acceptance 1: what the classifier is offered is what S-00 will admit."""

    domains, risks = enrich.admitted_vocabularies()
    answer = _Answer(_payload())

    _enriched(monkeypatch, answer)

    system = answer.prompts[0][0]
    for value in (*domains, *risks):
        assert value in system, f"{value!r} is admitted but was never offered"


def test_editing_the_contract_changes_what_the_prompt_offers(monkeypatch, tmp_path):
    """Acceptance 1, the other direction: the document is the source.

    A literal list in the prompt or in `enrich.py` passes the test above and
    fails this one.
    """

    directory = _edited(
        tmp_path, "- adjacent_business\n", "- adjacent_business\n- weeknight_cooking\n"
    )
    monkeypatch.setenv("NB_CLIENT_DIR", str(directory))
    answer = _Answer(_payload())

    _enriched(monkeypatch, answer)

    assert "weeknight_cooking" in answer.prompts[0][0]


def test_the_vocabulary_is_written_in_no_second_place():
    """Acceptance 1: the values live in the contract and are substituted.

    The risk vocabulary is checked by its placeholder rather than its values:
    `low` is also how this prompt spells a confidence, and a test asserting
    that the word is absent would be asserting something else.
    """

    domains, _ = enrich.admitted_vocabularies()
    prompt = PROMPT.read_text(encoding="utf-8")
    source = ENRICH_SOURCE.read_text(encoding="utf-8")

    for value in domains:
        assert value not in prompt, f"{value!r} is duplicated into the prompt"
        assert value not in source, f"{value!r} is duplicated into enrich.py"
    assert "{editorial_domains}" in prompt
    assert "{editorial_risk_levels}" in prompt


# ===========================================================================
# 2. An unadmitted answer does not become a value
# ===========================================================================


def test_an_invented_category_is_cannot_answer_and_never_a_value(monkeypatch):
    """Acceptance 2: the field is left absent, and the outcome is not a verdict.

    An answer naming something the contract does not list is not persisted, and
    it is not read as a deliberate "outside the vocabulary" either — only the
    sanctioned token is that. Recording ``outside_admitted`` here would launder
    an unusable answer into a decision about the signal, which is exactly the
    ``cannot_answer`` defect this slice exists to hold apart.
    """

    record = _enriched(
        monkeypatch,
        _Answer(_payload(EDITORIAL_DOMAIN=UNADMITTED, EDITORIAL_RISK="extreme")),
    )

    assert DOMAIN_FIELD not in record
    assert RISK_FIELD not in record
    assert record[DOMAIN_OUTCOME_FIELD] == CANNOT_ANSWER
    assert record[RISK_OUTCOME_FIELD] == CANNOT_ANSWER
    assert UNADMITTED not in json.dumps(record), (
        "the model's own category reached the record under some other key"
    )


def test_the_prompt_offers_the_owner_approved_token_and_only_that(monkeypatch):
    """Owner decision 4: the classifier chooses only among configured values.

    A deliberate "outside the admitted set" is offered explicitly, so no answer
    has to be an invented category. The token is asserted as the owner's exact
    literal rather than through ``enrich.OUTSIDE_ADMITTED_TOKEN``, which would
    agree with whatever that constant was changed to. It has one definition, in
    ``enrich.py``, and the prompt is rendered with it rather than spelling it a
    second time — a literal in the document fails the last assertion.
    """

    answer = _Answer(_payload())

    _enriched(monkeypatch, answer)

    assert enrich.OUTSIDE_ADMITTED_TOKEN == NONE_OF_THESE
    assert NONE_OF_THESE in answer.prompts[0][0]
    assert NONE_OF_THESE not in PROMPT.read_text(encoding="utf-8")


def test_the_offered_token_is_an_outcome_and_never_a_value(monkeypatch):
    """The sanctioned "none of these" is recorded as `outside_admitted`.

    It is not a category, so it reaches no value field and no record — the
    contract stays an allow-list and gains no inadmissible token.
    """

    record = _enriched(
        monkeypatch,
        _Answer(
            _payload(
                EDITORIAL_DOMAIN=NONE_OF_THESE,
                EDITORIAL_RISK=NONE_OF_THESE,
            )
        ),
    )

    assert DOMAIN_FIELD not in record
    assert RISK_FIELD not in record
    assert record[DOMAIN_OUTCOME_FIELD] == OUTSIDE_ADMITTED
    assert record[RISK_OUTCOME_FIELD] == OUTSIDE_ADMITTED
    assert NONE_OF_THESE not in json.dumps(record)
    assert NONE_OF_THESE not in CONTRACT.read_text(encoding="utf-8")


def test_an_exactly_listed_answer_is_persisted_as_the_contracts_value(monkeypatch):
    """The value a record states is one configured value, not the answer's prose."""

    domains, risks = enrich.admitted_vocabularies()
    record = _enriched(
        monkeypatch,
        _Answer(_payload(EDITORIAL_DOMAIN=domains[0], EDITORIAL_RISK=risks[0])),
    )

    assert record[DOMAIN_FIELD] == domains[0]
    assert record[RISK_FIELD] == risks[0]
    assert record[DOMAIN_OUTCOME_FIELD] == ADMITTED
    assert record[RISK_OUTCOME_FIELD] == ADMITTED


@pytest.mark.parametrize(
    "respell",
    [
        lambda value: value.upper(),
        lambda value: value.capitalize(),
        lambda value: f"  {value} ",
    ],
    ids=["uppercase", "capitalized", "padded"],
)
def test_a_respelling_of_a_listed_value_is_not_admitted(monkeypatch, respell):
    """Only an exactly configured value is admitted; a near miss is no answer.

    `FitRule.check` folds case and collapses whitespace, so a stage that
    normalised before admitting would write a value S-00 goes on to accept.
    It is still not the value the contract lists, and treating it as one is
    this stage deciding what the contract meant. Restoring the normalisation
    fails here, and fails it for a reason no later stage could recover.
    """

    domains, _ = enrich.admitted_vocabularies()
    record = _enriched(
        monkeypatch, _Answer(_payload(EDITORIAL_DOMAIN=respell(domains[0])))
    )

    assert DOMAIN_FIELD not in record
    assert record[DOMAIN_OUTCOME_FIELD] == CANNOT_ANSWER


# ===========================================================================
# 3. A failure is recorded, not inferred
# ===========================================================================


@pytest.mark.parametrize(
    ("transport", "what"),
    [
        (_unavailable, "the provider raised"),
        (_Answer("not json at all"), "the answer did not parse"),
        (_Answer([1, 2]), "the answer was not an object"),
        (_Answer(_payload()), "the answer carried no classification"),
    ],
    ids=["provider", "unparsable", "not_an_object", "no_field"],
)
def test_a_failed_classification_is_recorded_as_cannot_answer(
    monkeypatch, transport, what
):
    """Acceptance 3: distinguishable in the record, not only in the log.

    Restoring the bare `except Exception: enriched = {}` collapses this into
    silence — no outcome key at all — and fails here.
    """

    record = _enriched(monkeypatch, transport)

    assert record[DOMAIN_OUTCOME_FIELD] == CANNOT_ANSWER, what
    assert record[RISK_OUTCOME_FIELD] == CANNOT_ANSWER, what
    assert DOMAIN_FIELD not in record
    assert RISK_FIELD not in record


def test_cannot_answer_and_outside_admitted_are_two_records_not_one(monkeypatch):
    """The two refusals S-00 cannot tell apart are told apart upstream."""

    failed = _enriched(monkeypatch, _unavailable)
    outside = _enriched(
        monkeypatch,
        _Answer(
            _payload(
                EDITORIAL_DOMAIN=NONE_OF_THESE,
                EDITORIAL_RISK=NONE_OF_THESE,
            )
        ),
    )

    assert failed[DOMAIN_OUTCOME_FIELD] == CANNOT_ANSWER
    assert outside[DOMAIN_OUTCOME_FIELD] == OUTSIDE_ADMITTED
    assert failed[DOMAIN_OUTCOME_FIELD] != outside[DOMAIN_OUTCOME_FIELD]
    assert failed[RISK_OUTCOME_FIELD] != outside[RISK_OUTCOME_FIELD]


def test_a_refused_classification_keeps_the_rest_of_the_enrichment(monkeypatch):
    """Risk 1: the classification rides an existing call and does not own it.

    Validating the two classifications strictly must not reject the answer they
    arrived in: the other enrichment fields are the same call's.
    """

    record = _enriched(
        monkeypatch, _Answer(_payload(EDITORIAL_DOMAIN=UNADMITTED))
    )

    assert record["CORE_FACT"] == _payload()["CORE_FACT"]
    assert record["ARTICLE_READY"] == "true"


def test_no_vocabulary_to_classify_against_is_cannot_answer(monkeypatch, tmp_path):
    """A contract that cannot be read classifies nothing; it admits nothing either.

    An unreadable contract is the one state where the stage has no vocabulary
    to offer. Recording `outside_admitted` would be a verdict on the signal for
    something that happened to the configuration.
    """

    domains, risks = enrich.admitted_vocabularies()  # the real ones, for the answer
    monkeypatch.setenv("NB_CLIENT_DIR", str(tmp_path / "no-such-client"))

    record = _enriched(
        monkeypatch,
        _Answer(_payload(EDITORIAL_DOMAIN=domains[0], EDITORIAL_RISK=risks[0])),
    )

    assert record[DOMAIN_OUTCOME_FIELD] == CANNOT_ANSWER
    assert record[RISK_OUTCOME_FIELD] == CANNOT_ANSWER
    assert DOMAIN_FIELD not in record
    assert RISK_FIELD not in record


# ===========================================================================
# 4. The invariant holds both ways
# ===========================================================================


@pytest.mark.parametrize("outcome", [ADMITTED, OUTSIDE_ADMITTED, CANNOT_ANSWER])
def test_a_value_is_present_exactly_when_the_outcome_is_admitted(
    monkeypatch, outcome
):
    """Acceptance 4: presence ⟺ `admitted`, and there is no third state."""

    domains, risks = enrich.admitted_vocabularies()
    transports = {
        ADMITTED: _Answer(
            _payload(EDITORIAL_DOMAIN=domains[0], EDITORIAL_RISK=risks[0])
        ),
        OUTSIDE_ADMITTED: _Answer(
            _payload(
                EDITORIAL_DOMAIN=NONE_OF_THESE,
                EDITORIAL_RISK=NONE_OF_THESE,
            )
        ),
        CANNOT_ANSWER: _unavailable,
    }

    record = _enriched(monkeypatch, transports[outcome])

    for value_field, outcome_field in (
        (DOMAIN_FIELD, DOMAIN_OUTCOME_FIELD),
        (RISK_FIELD, RISK_OUTCOME_FIELD),
    ):
        assert record[outcome_field] == outcome
        assert record[outcome_field] in {ADMITTED, OUTSIDE_ADMITTED, CANNOT_ANSWER}
        assert (value_field in record) is (outcome == ADMITTED)


def test_every_record_states_both_outcomes(monkeypatch):
    """The outcome is what the record always carries; the value is conditional."""

    record = _enriched(monkeypatch, _unavailable)

    assert DOMAIN_OUTCOME_FIELD in record
    assert RISK_OUTCOME_FIELD in record


# ===========================================================================
# 5. No default creeps in — S-00 on the real record
# ===========================================================================


def test_an_unclassified_record_is_refused_by_s00(monkeypatch):
    """Acceptance 5: silence is not admission, all the way to the stage.

    Any default, `or` or `setdefault` that gave the absent classification a
    value would make this signal pass, and fails here.
    """

    record = _enriched(monkeypatch, _unavailable)

    selection = _selection(record, _UncalledTransport())

    assert selection.selected is False
    assert selection.fit is SignalFit.OUTSIDE_TOPICS
    refused = selection.fit_rules[0]
    assert refused.passed is False
    assert refused.stated == ()


def test_an_unadmitted_record_is_refused_by_s00(monkeypatch):
    """The outcome field is beside the value and is read by no fit rule."""

    record = _enriched(
        monkeypatch,
        _Answer(_payload(EDITORIAL_DOMAIN=UNADMITTED, EDITORIAL_RISK="extreme")),
    )

    selection = _selection(record, _UncalledTransport())

    assert selection.selected is False
    assert selection.fit is SignalFit.OUTSIDE_TOPICS


def test_an_admitted_record_passes_the_contracts_fit_rules(monkeypatch):
    """The two spellings meet: what Stage 4 writes is what S-00 reads.

    Both halves are the production objects — the record is `enrich_signal`'s
    own output and the table is `contract_fit_rules`' — so a field name or a
    value that drifted between them fails here and nowhere else.
    """

    domains, risks = enrich.admitted_vocabularies()
    record = _enriched(
        monkeypatch,
        _Answer(_payload(EDITORIAL_DOMAIN=domains[0], EDITORIAL_RISK=risks[0])),
    )

    selection = _selection(record, _Transport())

    assert [result.passed for result in selection.fit_rules] == [True, True]
    assert selection.fit is SignalFit.FITS


# ===========================================================================
# 6. Historical records still load, and are still refused
# ===========================================================================


def test_every_record_on_disk_keeps_the_invariant():
    """Acceptance 4, on the file rather than on one call.

    Written to survive the run #351 needs: a record classified by a later run
    satisfies this, and a record that acquired a value without the outcome that
    admits it — a backfill, a default, a hand edit — does not.
    """

    lines = SIGNALS_ACTIVE.read_text(encoding="utf-8").splitlines()
    assert lines, "the intake record file is empty"

    for line in lines:
        record = json.loads(line)
        for value_field, outcome_field in (
            (DOMAIN_FIELD, DOMAIN_OUTCOME_FIELD),
            (RISK_FIELD, RISK_OUTCOME_FIELD),
        ):
            assert (value_field in record) is (
                record.get(outcome_field) == ADMITTED
            ), f"{record.get('SIGNAL_ID')}: {value_field} and its outcome disagree"


def test_a_pre_slice_record_loads_and_is_refused_rather_than_repaired():
    """Acceptance 6: that refusal is correct behaviour, not a defect.

    The first record of an append-only file is the oldest one there is, so it
    is a record written before this slice for as long as the file exists.
    """

    record = json.loads(SIGNALS_ACTIVE.read_text(encoding="utf-8").splitlines()[0])
    for key in CLASSIFICATION_KEYS:
        assert key not in record, "the oldest record was back-filled"

    context = ResearchContext.from_dict(record)

    assert context.editorial_domain is None
    assert context.editorial_domain_outcome is None
    assert context.editorial_risk is None
    assert context.editorial_risk_outcome is None
    written = context.to_dict()
    for key in CLASSIFICATION_KEYS:
        assert key not in written, f"{key} was invented for a record without one"

    selection = _selection(record, _UncalledTransport())
    assert selection.selected is False
    assert selection.fit is SignalFit.OUTSIDE_TOPICS


def test_a_classified_record_survives_the_typed_lifecycle(monkeypatch):
    """What Stage 4 wrote is still there after the record has been read.

    `_KNOWN_JSONL_KEYS` is what decides whether a key is carried as a field or
    as passthrough; declaring the four without reading them would drop the
    classification on the way through.
    """

    domains, risks = enrich.admitted_vocabularies()
    record = _enriched(
        monkeypatch,
        _Answer(_payload(EDITORIAL_DOMAIN=domains[0], EDITORIAL_RISK=risks[0])),
    )

    context = ResearchContext.from_dict(record)

    assert context.editorial_domain == domains[0]
    assert context.editorial_domain_outcome == ADMITTED
    assert context.editorial_risk == risks[0]
    assert context.editorial_risk_outcome == ADMITTED
    assert context.to_dict()[DOMAIN_FIELD] == domains[0]


def test_the_schema_declares_all_four_keys():
    """Acceptance 7."""

    assert set(CLASSIFICATION_KEYS) <= _KNOWN_JSONL_KEYS


# ===========================================================================
# 7. Containment
# ===========================================================================


def test_this_branch_changes_nothing_the_slice_declared_out_of_scope():
    """Acceptance 8 and 9: the Client Contract, the core and July are untouched.

    The diff is the evidence, so the diff is what is asserted — and only when
    the branch touches the enrichment stage, so that later work elsewhere is
    not held hostage by a check about #365.
    """

    if _git("rev-parse", "--git-dir")[0] != 0:
        pytest.skip("not a git checkout")

    base = ""
    for ref in ("origin/main", "main"):
        status, resolved = _git("merge-base", ref, "HEAD")
        if status == 0 and resolved:
            base = resolved
            break
    assert base, "no base revision to compare against; main is unreachable"

    status, listed = _git("diff", "--name-only", base)
    assert status == 0, "the diff against the base revision could not be read"
    changed = [line for line in listed.splitlines() if line]

    if not any(line == "scripts/research/enrich.py" for line in changed):
        return
    forbidden = ("clients/", "src/editorial_core/", "src/never_blank/wednesday_july/")
    assert not [
        line for line in changed if line.startswith(forbidden)
    ], "the classification came with a change the slice put out of scope"
    # No backfill: the 134 historical signals are what #351 may not run on, and
    # a branch that classified them in place would show up here.
    assert "data/research/signals_active.jsonl" not in changed, (
        "the intake records were rewritten rather than newly classified"
    )
