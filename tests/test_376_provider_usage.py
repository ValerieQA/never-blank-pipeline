"""Issue #376 (NB-07a1): the provider's own token usage, in the canonical trace.

Why this slice exists: `golden_engine.py` wrote `tokens_in=0, tokens_out=0` as a
literal for every stage record, and `llm_client.chat` returned the message
content while discarding `response.usage`. So the trace promised a measurement
nothing measured, and #309's baseline report would have published zeros as
numbers. Usage is reported per response and cannot be reconstructed afterwards,
which is why this had to land before #308's three paid runs.

The three states these tests keep apart are the owner's (2026-10-03), and they
follow #308's E-16 convention rather than a second one: **measured non-zero**,
**measured zero**, and **unavailable because the provider did not report**. A
fourth case the owner's wording does not name is settled here and stated in the
issue: an execution that made no call sent no tokens, which is knowable, so it
is a measured zero rather than an absence.

No provider call is made anywhere below. The boundary tests fake the OpenAI
client with the `#279` idiom; the engine tests use the deterministic doubles in
`tests/golden_engine_boundary.py`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from src.run import stage_routing
from src.run.call_budget import RunCallBudget, activate_call_budget
from src.run.run_summary import stage_call_totals
from src.run.stage_routing import ProviderUsage, UsageAbsence, UsageTotals
from src.utils import llm_client
from tests.golden_engine_boundary import canonical_run, execute


def _answer(usage: object | None) -> SimpleNamespace:
    """One provider response, with whatever usage the case is about."""

    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="answered"))],
        usage=usage,
    )


def _usage(prompt: int, completion: int) -> SimpleNamespace:
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)


def _run(responses, *, stage: str = "S-03") -> stage_routing.StageRouting:
    """Make one `chat` call per response, inside a recording run."""

    replies = iter(responses)
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: next(replies))
        )
    )
    routing = stage_routing.StageRouting(run_id="r-376")
    with (
        mock.patch.object(llm_client, "_get_client", return_value=fake),
        stage_routing.recording(routing),
        stage_routing.stage(stage),
    ):
        for _ in responses:
            llm_client.chat(system="s", user="u")
    return routing


# ===========================================================================
# 1–3 · the three states, at the provider boundary
# ===========================================================================


def test_a_response_that_reports_usage_records_those_exact_tokens():
    """The provider's number, unrounded and unaggregated."""

    routing = _run([_answer(_usage(137, 42))])

    (entry,) = routing.usage
    assert (entry.stage, entry.tokens_in, entry.tokens_out) == ("S-03", 137, 42)
    assert entry.measured and entry.absent is None
    assert UsageTotals.of(routing.take_usage("S-03"), calls=1).as_calls(1) == {
        "count": 1,
        "usage_reports": 1,
        "silent_reports": 0,
        "tokens_in": 137,
        "tokens_out": 42,
    }


def test_a_response_without_usage_is_unavailable_and_never_zero():
    """The defect this slice removes, in one assertion.

    `tokens_in: 0` was the old literal. A reader could not tell it from a stage
    that genuinely sent nothing, and #309's min/median/max would have averaged
    the two together.
    """

    routing = _run([_answer(None)])

    (entry,) = routing.usage
    assert entry.absent is UsageAbsence.NOT_REPORTED
    assert entry.tokens_in is None and entry.tokens_out is None

    recorded = UsageTotals.of(routing.take_usage("S-03"), calls=1).as_calls(1)
    assert recorded["tokens_absent"] == "not_reported"
    assert "tokens_in" not in recorded, "an absent measurement carries no number"
    assert recorded["silent_reports"] == 1


def test_a_genuine_zero_is_measured_and_distinguishable_from_unavailable():
    """A provider may legitimately report zero. That is a measurement."""

    measured = UsageTotals.of(
        [ProviderUsage.of("S-03", "sig", _usage(0, 0))], calls=1
    ).as_calls(1)
    unavailable = UsageTotals.of(
        [ProviderUsage.of("S-03", "sig", None)], calls=1
    ).as_calls(1)

    assert measured["tokens_in"] == 0 and measured["tokens_out"] == 0
    assert "tokens_absent" not in measured
    assert "tokens_in" not in unavailable
    assert measured != unavailable, (
        "the whole slice is that these two serialize differently"
    )

    # And the same distinction survives into the public summary, which is where
    # #309 reads it: one is a number, the other is a closed category.
    assert UsageTotals.of([], calls=0).as_calls(0)["tokens_in"] == 0
    assert (
        UsageTotals.of([], calls=1).as_calls(1)["tokens_absent"]
        == "no_response_reported"
    ), "calls made and nothing reported is its own category, not NOT_REPORTED"


def test_a_partial_usage_report_is_absent_rather_than_half_counted():
    """Half a measurement summed with whole ones is a number nobody can read."""

    for broken in (
        SimpleNamespace(prompt_tokens=10),
        SimpleNamespace(prompt_tokens=10, completion_tokens=None),
        SimpleNamespace(prompt_tokens=-1, completion_tokens=2),
        SimpleNamespace(prompt_tokens=True, completion_tokens=2),
    ):
        entry = ProviderUsage.of("S-03", "sig", broken)
        assert entry.absent is UsageAbsence.INCOMPLETE, broken

    with pytest.raises(ValueError, match="states why"):
        ProviderUsage(stage="S-03", scope_key="k")
    with pytest.raises(ValueError, match="no absent category"):
        ProviderUsage(
            stage="S-03",
            scope_key="k",
            tokens_in=1,
            tokens_out=1,
            absent=UsageAbsence.NOT_REPORTED,
        )


# ===========================================================================
# 4 · the temperature fallback: two charged calls, one paid request
# ===========================================================================


def test_the_temperature_fallback_charges_twice_and_reports_usage_once():
    """#171 charges the fallback like any other call. The provider does not.

    The rejected request is a 400 — it carries no usage and is not billed — so
    the divergence between the logical call count and the billable one is real.
    It is recorded, not reconciled: §0.3's ceiling bounds logical calls, and
    #309's cost report reads the usage reports.
    """

    from openai import BadRequestError

    rejected = BadRequestError(
        message="temperature is not supported",
        response=SimpleNamespace(status_code=400, headers={}, request=None),
        body=None,
    )
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise rejected
        return _answer(_usage(90, 10))

    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    routing = stage_routing.StageRouting(run_id="r-376")
    budget = RunCallBudget(10)
    with (
        mock.patch.object(llm_client, "_get_client", return_value=fake),
        activate_call_budget(budget),
        stage_routing.recording(routing),
        stage_routing.stage("S-13"),
    ):
        llm_client.chat(system="s", user="u")

    assert len(calls) == 2, "the fallback retried once, without temperature"
    assert "temperature" not in calls[1]
    assert budget.used == 2, "#171 charges the fallback as a second logical call"

    totals = UsageTotals.of(routing.take_usage("S-13"), calls=2)
    assert totals.usage_reports == 1, "only one response ever came back"
    assert (totals.tokens_in, totals.tokens_out) == (90, 10)
    recorded = totals.as_calls(2)
    assert recorded["count"] == 2 and recorded["usage_reports"] == 1, (
        "both numbers are kept so the divergence stays readable"
    )


# ===========================================================================
# 5–6 · the canonical run: attribution, and the budget identity
# ===========================================================================


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    """One clean six-destination canonical run, with usage-reporting doubles."""

    run = canonical_run(tmp_path_factory.mktemp("usage"))
    execution, workspace, budget = execute(run)
    return execution, budget


def test_usage_is_attributable_per_stage_and_per_scope_from_the_trace(measured):
    """The per-destination dimension #309 needs, without a per-destination field.

    Owner decision, 2026-10-03: no `destination_calls` aggregate in the durable
    summary. `StageRecord` is the canonical trace authority and already names
    its `scope_key`, so the destination numbers are derived from the records —
    which is what the acceptance "reproducible from stored traces" asks for.
    """

    execution, _ = measured
    by_scope: dict[tuple[str, str], int] = {}
    for record in execution.records:
        calls = record.calls or {}
        if "tokens_in" not in calls or not calls["count"]:
            continue
        key = (record.stage, record.scope_key)
        by_scope[key] = by_scope.get(key, 0) + calls["tokens_in"]

    lanes = {
        scope for stage, scope in by_scope if stage in {"S-08", "S-09", "S-10"}
    }
    assert len(lanes) == 6, (
        f"six destinations, each attributable on its own scope key; got {lanes}"
    )
    # Every lane paid for its own planning, and no two lanes share a total.
    for destination in lanes:
        assert by_scope[("S-09", destination)] > 0

    # And no record carries the old literal zero alongside a call it made.
    for record in execution.records:
        calls = record.calls or {}
        if calls.get("count"):
            assert calls.get("tokens_in") != 0 or "tokens_absent" in calls


def test_every_stage_reports_usage_for_every_call_it_was_charged_for(measured):
    """The accounting identity the instrument has to preserve (#351).

    `recorded == budget.used` was #351's measurement and stays exact: the hook
    reads a field of a response that has already come back, so it charges
    nothing. The new line is the second equality — every charged call produced
    exactly one usage report — which is what proves the attribution is not
    merely plausible but complete.
    """

    execution, budget = measured
    rows = stage_call_totals(execution.records)

    assert sum(row.calls for row in rows) == budget.used == 50
    assert sum(row.usage_reports for row in rows) == budget.used
    for row in rows:
        assert row.usage_reports == row.calls, (
            f"{row.stage} was charged {row.calls} and reported "
            f"{row.usage_reports}; a stage whose name is set after its calls "
            "has them attributed to its predecessor"
        )
        assert row.tokens_absent is None
        assert row.tokens_in == row.calls * 10
        assert row.tokens_out == row.calls * 4


def test_a_stage_that_made_no_call_records_a_measured_zero(measured):
    """Knowable, not unmeasured: nothing was sent, so nothing was spent.

    S-14 is in this set, and that is the point of including it: #308's
    "S-14 makes no model call" is now readable from the usage instrument rather
    than only from the stage's own call count. A slice that quietly gave S-14 a
    model call would change this set.
    """

    execution, _ = measured
    silent = [row for row in stage_call_totals(execution.records) if not row.calls]

    assert {row.stage for row in silent} == {"S-03", "S-05", "S-07", "S-14"}
    for row in silent:
        assert (row.tokens_in, row.tokens_out) == (0, 0)
        assert row.tokens_absent is None


# ===========================================================================
# 7 · outside a recorded run
# ===========================================================================


def test_observing_usage_outside_a_recorded_run_is_a_no_op():
    """The `observe_request` precedent: nothing outside a run pays for this."""

    assert stage_routing.current() is None
    stage_routing.observe_usage(_usage(1, 2))
    stage_routing.observe_usage(None)

    # Recording but unnamed is also a no-op: usage with no stage to carry it
    # would have to be attributed by guessing.
    routing = stage_routing.StageRouting(run_id="r-376")
    with stage_routing.recording(routing):
        stage_routing.observe_usage(_usage(1, 2))
    assert routing.usage == []

    assert stage_routing._STAGE.get() == "", (
        "recording restores the stage name, so it cannot outlive its run"
    )


def test_a_second_execution_of_a_stage_carries_only_its_own_cost():
    """Draining, not reading: the edit loop runs S-13 twice per destination."""

    routing = _run([_answer(_usage(5, 1)), _answer(_usage(7, 2))], stage="S-13")
    first = routing.take_usage("S-13")
    assert len(first) == 2
    assert routing.take_usage("S-13") == (), "drained, so nothing is counted twice"


# ===========================================================================
# 8 · the #279 evidence that was silently absent
# ===========================================================================


def test_the_canonical_run_now_produces_stage_routing_evidence(measured):
    """Wiring the seam was part of this slice, not a side effect.

    The engine never imported `stage_routing`, so `_STAGE` was empty for every
    canonical call and `observe_request` — wired into `chat` since #279 — was a
    silent no-op on the canonical path. The evidence did not exist; it was not
    merely unread. `routed=False` is the honest state for it: the canonical
    engine routes no lens through that mechanism, and #279's own schema has a
    state for exactly that.
    """

    execution, _ = measured
    with_routing = [
        record for record in execution.records if record.routing is not None
    ]

    assert with_routing, "a canonical run records request evidence now"
    stages = {record.stage for record in with_routing}
    assert {"S-00", "S-08", "S-13"} <= stages

    for record in with_routing:
        requests = record.routing["requests"]
        assert requests
        for item in requests:
            assert item["stage"] == record.stage, "no cross-stage attribution"
            assert item["request_sha256"] and "prompt" not in item
            assert item["state"] == stage_routing.NOT_ROUTED
            assert item["routed"] is False
            assert item["forbidden_present"] == []

    # The evidence is drained per execution, exactly like the usage, so a stage
    # that ran twice does not carry the other execution's requests.
    counted = sum(len(record.routing["requests"]) for record in with_routing)
    assert counted == 50


# ===========================================================================
# 9 · nothing about the call itself changed
# ===========================================================================


def test_the_hook_changes_nothing_about_the_request_or_the_answer():
    """Observation only: same kwargs out, same content back, one call made."""

    seen: list[dict] = []

    def create(**kwargs):
        seen.append(kwargs)
        return _answer(_usage(3, 4))

    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    routing = stage_routing.StageRouting(run_id="r-376")
    with (
        mock.patch.object(llm_client, "_get_client", return_value=fake),
        stage_routing.recording(routing),
        stage_routing.stage("S-12"),
    ):
        answered = llm_client.chat(system="sys", user="usr", model="m-1")

    assert answered == "answered"
    assert len(seen) == 1
    assert seen[0]["model"] == "m-1"
    assert seen[0]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert "response_format" not in seen[0]


def test_an_unreadable_usage_object_does_not_fail_the_run():
    """By the time this is read the call has been made and paid for.

    So a provider that changes its usage shape makes the measurement
    unavailable. Raising here would turn a reporting change into a run failure
    after the money was already spent.
    """

    routing = _run([_answer(object()), _answer("not a usage")])

    assert [entry.absent for entry in routing.usage] == [
        UsageAbsence.INCOMPLETE,
        UsageAbsence.INCOMPLETE,
    ]


# ===========================================================================
# The summary keeps the states apart, and refuses prose
# ===========================================================================


def test_the_summary_refuses_a_sentence_where_it_wants_a_category():
    """§3.3: a reason is a closed category; the words stay in the workspace."""

    from src.run.run_summary import RunSummaryError, StageCalls
    from src.run.run_workspace import StageRecord

    with pytest.raises(ValueError, match="no token measurement and no reason"):
        StageCalls(stage="S-03", calls=1)
    with pytest.raises(ValueError, match="not true"):
        StageCalls(
            stage="S-03",
            calls=1,
            tokens_in=1,
            tokens_out=1,
            tokens_absent=UsageAbsence.NOT_REPORTED,
        )
    with pytest.raises(ValueError, match="half measurement"):
        StageCalls(stage="S-03", calls=1, tokens_in=1)

    record = StageRecord.model_construct(
        stage="S-03",
        calls={"count": 1, "tokens_absent": "the provider was quiet today"},
    )
    with pytest.raises(RunSummaryError, match="closed category"):
        stage_call_totals([record])


def test_one_absent_execution_makes_the_stage_total_absent():
    """A measured stage summed with an unmeasured one would publish a short total."""

    from src.run.run_workspace import StageRecord

    def record(stage: str, calls: dict) -> StageRecord:
        return StageRecord.model_construct(stage=stage, calls=calls)

    totals = stage_call_totals([
        record("S-13", {"count": 1, "usage_reports": 1, "tokens_in": 9, "tokens_out": 3}),
        record("S-13", {"count": 1, "silent_reports": 1, "tokens_absent": "not_reported"}),
    ])

    (row,) = totals
    assert row.calls == 2
    assert row.tokens_in is None and row.tokens_absent is UsageAbsence.NOT_REPORTED
    assert row.usage_reports == 1 and row.silent_reports == 1

    mixed = stage_call_totals([
        record("S-13", {"count": 1, "tokens_absent": "not_reported"}),
        record("S-13", {"count": 1, "tokens_absent": "incomplete"}),
    ])
    assert mixed[0].tokens_absent is UsageAbsence.MIXED

    # And a stage that made calls while stating neither is told so, not zeroed.
    silent = stage_call_totals([record("S-13", {"count": 2})])
    assert silent[0].tokens_absent is UsageAbsence.NOT_RECORDED
