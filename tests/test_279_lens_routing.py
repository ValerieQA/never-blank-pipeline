"""#279: a standing client lens reaches the stages that BUILD the argument.

Forensic #278 on live run `e8d37c94` found the defect these tests exist to
catch. Never Blank's structure lens was loaded, versioned and present in
contract lineage — and the spine, hook and voice stages never received it,
because standing obligations travelled to the composer alone. The article
obeyed the ending rule (a plan slot, which did reach those stages) and ignored
the opening rule (lens text, which did not).

Every assertion below is on a message a model actually receives, or on the
routing record the run persists. The canaries belong to a fixture client's
documents; no Engine module knows them.

No network, no model.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from src.editorial.editorial_plan import (
    Claim,
    build_editorial_plan,
    plan_block,
)
from src.editorial.pipeline import ARGUMENT_STAGES
from src.run import stage_routing
from src.strategy.client_contracts import contracts_for_role
from tests import test_generate_and_publish as legacy
from tests.test_monday_stream import MONDAY_ROLE
from tests.test_no_mandatory_thesis import _run_real_prompt_path

FIXTURE = Path("tests/fixtures/client_gearworks")
SIG = legacy._SIGNAL_ID

#: The stages that shape the argument before anything is composed.
BUILDERS = ("narrative_spine", "hook_engine", "never_blank_voice")

#: A standing writing lens in the fixture client, and one phrase from it.
BENCH_LENS = "gearworks-bench/1"
BENCH_CANARY = "Write to a shop owner standing at a bench"


def _plan(directory: Path = FIXTURE, **overrides):
    contracts = contracts_for_role(MONDAY_ROLE, directory)
    assert contracts is not None, "the fixture client governs this role"
    arguments: dict[str, Any] = {
        "central_claim": Claim(text="The manufacturer published a 14-week lead time."),
        "claim_strength_ceiling": "confirmed by the manufacturer",
        "activation_evidence": {"manufacturer_recall": "Recall R-114, 2026-09-15."},
    }
    arguments.update(overrides)
    return build_editorial_plan(contracts, **arguments)


# ── 1-2. the standing lens reaches every stage that builds the argument ─────


def test_a_standing_writing_lens_reaches_the_real_argument_stages(monkeypatch):
    """The defect from #278, as a test: spine, hook and voice each receive the
    client's standing obligation, in the client's own words."""
    calls, _ = _run_real_prompt_path(
        monkeypatch, MONDAY_ROLE, "lead-time", "A published figure moved first.",
        editorial_plan=_plan(),
    )

    for stage in BUILDERS:
        message = "\n".join(calls[stage])
        assert BENCH_CANARY in message, stage
        assert BENCH_LENS in message, stage


def test_the_composer_keeps_its_existing_route_untouched():
    """#279 changes what the ARGUMENT stages receive and nothing else: the
    composer still gets standing obligations the way it already did, through
    the role's rendered rules."""
    from src.editorial.editorial_role import (
        render_editorial_role_rules,
        resolve_editorial_role,
    )
    from src.strategy.business_config import load_business_strategy_configuration

    contracts = contracts_for_role(MONDAY_ROLE, FIXTURE)
    _, role = resolve_editorial_role(
        load_business_strategy_configuration(), MONDAY_ROLE, contracts=contracts
    )

    for surface in ("wix", "linkedin"):
        rendered = render_editorial_role_rules(
            role, surface=surface, lenses=contracts.for_stage("writing")
        )
        assert BENCH_CANARY in rendered, surface


def test_an_activated_conditional_lens_reaches_them_too_and_only_once(monkeypatch):
    calls, _ = _run_real_prompt_path(
        monkeypatch, MONDAY_ROLE, "lead-time", "A published figure moved first.",
        editorial_plan=_plan(),
    )

    for stage in BUILDERS:
        message = "\n".join(calls[stage])
        assert "GEARWORKS-LENS-CANARY" in message, stage
        assert message.count("GEARWORKS-LENS-CANARY") == 1, stage
        assert "Recall R-114" in message, stage


def test_an_inactive_conditional_lens_reaches_none_of_them(monkeypatch):
    calls, _ = _run_real_prompt_path(
        monkeypatch, MONDAY_ROLE, "lead-time", "A published figure moved first.",
        editorial_plan=_plan(activation_evidence={}),
    )

    for stage in (*BUILDERS, "platform_composer"):
        assert "GEARWORKS-LENS-CANARY" not in "\n".join(calls[stage]), stage


# ── 3. stage relevance: no lens leaks where its contract did not send it ────


def test_a_revision_only_lens_never_reaches_a_writing_stage(tmp_path, monkeypatch):
    client = tmp_path / "client"
    shutil.copytree(FIXTURE, client)
    (client / "lenses" / "revision_only.md").write_text(
        "---\n"
        "lens_id: gearworks-revision-only\n"
        'version: "1"\n'
        "applies_to: [gearworks-weekly]\n"
        "stages: [revision]\n"
        "---\n\n"
        "GEARWORKS-REVISION-ONLY-CANARY: keep the part numbers when you revise.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NB_CLIENT_DIR", str(client))
    plan = _plan(client)

    calls, _ = _run_real_prompt_path(
        monkeypatch, MONDAY_ROLE, "lead-time", "A published figure moved first.",
        editorial_plan=plan,
    )

    for stage in (*BUILDERS, "platform_composer"):
        assert "GEARWORKS-REVISION-ONLY-CANARY" not in "\n".join(calls[stage]), stage
    # and it is exactly what the revision projection carries
    assert any("GEARWORKS-REVISION-ONLY-CANARY" in text
               for text in plan.lens_text_for("revision"))
    assert not any("GEARWORKS-REVISION-ONLY-CANARY" in text
                   for text in plan.lens_text_for("writing"))


def test_the_projection_is_stage_aware_in_both_directions():
    plan = _plan()

    writing = " ".join(plan.lens_text_for("writing"))
    revision = " ".join(plan.lens_text_for("revision"))

    # the bench lens declares writing AND revision; the recall lens writing only
    assert BENCH_CANARY in writing and BENCH_CANARY in revision
    assert "GEARWORKS-LENS-CANARY" in writing
    assert "GEARWORKS-LENS-CANARY" not in revision


# ── 4. the run can prove delivery afterwards, from what it persisted ────────


def test_the_pipeline_declares_the_routing_before_the_stages_run(monkeypatch):
    """The run writes down what it routed, per stage, from the contract."""
    routing = stage_routing.StageRouting(run_id="r-1", plan_stage="writing")

    with stage_routing.recording(routing):
        _run_real_prompt_path(
            monkeypatch, MONDAY_ROLE, "lead-time", "A published figure moved first.",
            editorial_plan=_plan(),
        )

    assert set(routing.routed) == set(BUILDERS)
    for stage in BUILDERS:
        routed = [lens.identity for lens in routing.routed[stage]]
        assert BENCH_LENS in routed, stage
        assert "gearworks-recall/1" in routed, stage
        assert all(lens.digest.startswith("sha256:") for lens in routing.routed[stage])


def test_the_shared_client_measures_what_actually_went_out(monkeypatch):
    """The probe lives in the real model client, so what is measured is the
    request itself — the fact #278 could not establish from any artifact."""
    from types import SimpleNamespace

    from src.utils import llm_client

    answer = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='{"ok": true}'))])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: answer)))
    routing = stage_routing.StageRouting(run_id="r-2", plan_stage="writing")
    routing.route("hook_engine", [stage_routing.RoutedLens(
        identity=BENCH_LENS, digest="sha256:abc", probe=BENCH_CANARY)])

    with (
        mock.patch.object(llm_client, "_get_client", return_value=fake),
        stage_routing.recording(routing),
        stage_routing.stage("hook_engine"),
    ):
        llm_client.chat(system="s", user=f"a prompt that carries {BENCH_CANARY}")
        llm_client.chat(system="s", user="a prompt that carries nothing")

    carried, absent = routing.requests
    assert carried.stage == "hook_engine" and carried.state == stage_routing.COMPLETE
    assert carried.contained == (BENCH_LENS,)
    assert absent.state == stage_routing.INCOMPLETE and absent.missing == (BENCH_LENS,)
    assert len({carried.request_sha256, absent.request_sha256}) == 2


def _record(tmp_path) -> dict:
    """A populated routing record, persisted the way a run persists it."""
    routing = stage_routing.StageRouting(run_id="r-3", plan_stage="writing")
    plan = _plan()
    routed = [
        stage_routing.RoutedLens(identity=lens.identity, digest=lens.digest,
                                 probe=" ".join(lens.text.split())[:80])
        for lens in plan.lenses_for("writing")
    ]
    for stage in BUILDERS:
        routing.route(stage, routed)
        routing.observe(stage, user=f"PROMPT {' '.join(l.probe for l in routed)}")
    gap._persist_stage_routing(tmp_path, routing)
    return json.loads((tmp_path / "stage_routing.json").read_text())


def test_the_run_persists_a_record_that_proves_stage_delivery(tmp_path):
    record = _record(tmp_path)

    assert record["artifact_kind"] == "stage_routing"
    assert record["publishable"] is False
    assert record["run_id"] == "r-3" and record["plan_stage"] == "writing"
    for stage in BUILDERS:
        routed = [entry["lens"] for entry in record["routed"][stage]]
        assert BENCH_LENS in routed, stage
        assert all(entry["digest"].startswith("sha256:") for entry in record["routed"][stage])
        assert BENCH_LENS in record["delivered"][stage], stage
    for request in record["requests"]:
        assert len(request["request_sha256"]) == 64
        assert request["routed"] is True
        assert request["state"] == stage_routing.COMPLETE


def test_the_record_stores_no_prompt_and_no_secret(tmp_path):
    flattened = json.dumps(_record(tmp_path))

    assert BENCH_CANARY not in flattened          # the lens text itself is not stored
    assert "PROMPT" not in flattened
    assert "api_key" not in flattened.casefold() and "sk-" not in flattened


def test_a_run_that_routed_nothing_writes_no_record(tmp_path):
    gap._persist_stage_routing(tmp_path, stage_routing.StageRouting())

    assert not (tmp_path / "stage_routing.json").exists()


# ── 5-6. the mechanism is the contract's, and the Engine knows no client ────


def test_replacing_the_client_replaces_what_the_argument_stages_receive(
    tmp_path, monkeypatch
):
    client = tmp_path / "client"
    shutil.copytree(FIXTURE, client)
    lens = client / "lenses" / "bench.md"
    lens.write_text(
        lens.read_text(encoding="utf-8").replace(BENCH_CANARY, "REPLACED-CLIENT-CANARY"),
        encoding="utf-8",
    )
    monkeypatch.setenv("NB_CLIENT_DIR", str(client))

    calls, _ = _run_real_prompt_path(
        monkeypatch, MONDAY_ROLE, "lead-time", "A published figure moved first.",
        editorial_plan=_plan(client),
    )

    for stage in BUILDERS:
        message = "\n".join(calls[stage])
        assert "REPLACED-CLIENT-CANARY" in message, stage
        assert BENCH_CANARY not in message, stage


def test_no_engine_module_names_a_client_a_stream_or_a_weekday_as_the_mechanism():
    routing = Path("src/run/stage_routing.py").read_text(encoding="utf-8")
    plan = Path("src/editorial/editorial_plan.py").read_text(encoding="utf-8")
    pipeline = Path("src/editorial/pipeline.py").read_text(encoding="utf-8")

    for forbidden in ("gearworks", "invisalign", "never-blank-article-structure",
                      "monday", "tuesday", "wednesday", "thursday", "friday"):
        for name, text in (("stage_routing", routing), ("editorial_plan", plan)):
            assert forbidden not in text.casefold(), f"{name}: {forbidden}"
    # the pipeline names its own stages, which are Engine stages, not clients
    assert "gearworks" not in pipeline.casefold()
    assert "invisalign" not in pipeline.casefold()
    assert ARGUMENT_STAGES == BUILDERS


# ── 8. mutation: cut one argument stage out of the routing ──────────────────


def test_disconnecting_one_argument_stage_is_visible_in_the_prompt_and_record(
    monkeypatch
):
    """The twin. With the hook engine cut out of the stage projection, its
    prompt loses the obligation — and a run would record it as missing."""
    original = plan_block

    def without_hook(signal):
        rendered = original(signal)
        # simulate the pre-#279 world for one stage: plan yes, obligations no
        return rendered.split("The client's own obligations")[0]

    from src.editorial import hook_engine

    monkeypatch.setattr(hook_engine, "plan_block", without_hook)

    calls, _ = _run_real_prompt_path(
        monkeypatch, MONDAY_ROLE, "lead-time", "A published figure moved first.",
        editorial_plan=_plan(),
    )

    assert BENCH_CANARY not in "\n".join(calls["hook_engine"])
    # the stages still wired keep it, so the cut is visibly local
    assert BENCH_CANARY in "\n".join(calls["narrative_spine"])


def test_a_request_without_the_routed_lens_is_recorded_as_missing():
    """The record does not flatter the run: a request that never carried the
    obligation is written down as missing, not as routed-and-therefore-fine."""
    routing = stage_routing.StageRouting(run_id="r1", plan_stage="writing")
    routing.route("hook_engine", [stage_routing.RoutedLens(
        identity=BENCH_LENS, digest="sha256:abc", probe=BENCH_CANARY)])

    carried = routing.observe("hook_engine", user=f"PROMPT… {BENCH_CANARY} …rest")
    absent = routing.observe("hook_engine", user="PROMPT with no obligation in it")

    assert carried.state == stage_routing.COMPLETE
    assert carried.contained == (BENCH_LENS,)
    assert absent.state == stage_routing.INCOMPLETE and absent.missing == (BENCH_LENS,)
    assert routing.as_evidence()["delivered"]["hook_engine"] == [BENCH_LENS]


def test_the_probe_is_inert_outside_a_recorded_run():
    """Nothing outside a recorded generation pays for the observability."""
    assert stage_routing.current() is None
    stage_routing.observe_request(user="anything at all")      # must not raise

    routing = stage_routing.StageRouting()
    with stage_routing.recording(routing), stage_routing.stage("hook_engine"):
        stage_routing.observe_request(user="inside")
    stage_routing.observe_request(user="outside again")

    assert len(routing.requests) == 1
    assert stage_routing.current() is None


# ── #280 review repairs: the record only claims what it can support ─────────


def test_a_call_the_budget_refuses_is_never_recorded_as_sent(monkeypatch):
    """MEDIUM-1. The budget gate runs first, so a refused call reaches no
    provider — and must not appear in the record as one that went out."""
    from src.run.call_budget import (
        RunCallBudget,
        RunCallBudgetExceededError,
        activate_call_budget,
    )
    from src.utils import llm_client

    routing = stage_routing.StageRouting(run_id="r-budget", plan_stage="writing")
    routing.route("hook_engine", [stage_routing.RoutedLens(
        identity=BENCH_LENS, digest="sha256:abc", probe=BENCH_CANARY)])
    exploding = mock.MagicMock(side_effect=AssertionError("provider was reached"))

    with (
        mock.patch.object(llm_client, "_get_client", return_value=exploding),
        activate_call_budget(RunCallBudget(limit=1, hard_max=40)),
        stage_routing.recording(routing),
        stage_routing.stage("hook_engine"),
    ):
        answer = mock.MagicMock()
        answer.choices = [mock.MagicMock(message=mock.MagicMock(content="{}"))]
        exploding.chat.completions.create.side_effect = None
        exploding.chat.completions.create.return_value = answer
        llm_client.chat(system="s", user=f"first call {BENCH_CANARY}")
        with pytest.raises(RunCallBudgetExceededError):
            llm_client.chat(system="s", user=f"refused call {BENCH_CANARY}")

    assert len(routing.requests) == 1, "the refused call was recorded as sent"
    assert routing.requests[0].state == stage_routing.COMPLETE


def test_the_digest_and_the_check_cover_the_same_request_surface():
    """MEDIUM-2. Both messages, one surface: a digest over less than what was
    checked would vouch for a request nobody measured."""
    routing = stage_routing.StageRouting(run_id="r-surface", plan_stage="writing")
    routing.route("hook_engine", [stage_routing.RoutedLens(
        identity=BENCH_LENS, digest="sha256:abc", probe=BENCH_CANARY)])

    in_system = routing.observe("hook_engine", system=f"rules: {BENCH_CANARY}", user="u")
    in_user = routing.observe("hook_engine", system="rules", user=f"u {BENCH_CANARY}")
    same_user_other_system = routing.observe("hook_engine", system="other", user="u")

    # routed material is found wherever it travels in the request
    assert in_system.state == stage_routing.COMPLETE
    assert in_user.state == stage_routing.COMPLETE
    # and the digest distinguishes requests that differ only in the system half
    assert in_system.request_sha256 != in_user.request_sha256
    assert same_user_other_system.request_sha256 != routing.observe(
        "hook_engine", system="rules", user="u").request_sha256


def test_the_record_says_not_routed_without_cross_referencing(tmp_path):
    """MEDIUM-3. A stage nothing was routed to reads as `not_routed`, not as a
    pass, and the reader needs no other section to see it."""
    routing = stage_routing.StageRouting(run_id="r-states", plan_stage="writing")
    routing.route("hook_engine", [stage_routing.RoutedLens(
        identity=BENCH_LENS, digest="sha256:abc", probe=BENCH_CANARY)])

    routing.observe("hook_engine", user=f"carries {BENCH_CANARY}")
    routing.observe("hook_engine", user="carries nothing")
    routing.observe("platform_composer", user="a stage with no routing")

    states = [r["state"] for r in routing.as_evidence()["requests"]]
    assert states == [
        stage_routing.COMPLETE, stage_routing.INCOMPLETE, stage_routing.NOT_ROUTED,
    ]
    unrouted = routing.as_evidence()["requests"][2]
    assert unrouted["routed"] is False
    assert unrouted["contained"] == [] and unrouted["missing"] == []


@pytest.mark.parametrize("entry", ["chat", "chat_qc", "chat_parsed"])
def test_every_provider_bound_entry_point_is_observed(entry):
    """LOW-1. One hook, called wherever a request reaches a provider."""
    from pydantic import BaseModel

    from src.utils import llm_client

    class Answer(BaseModel):
        ok: bool

    routing = stage_routing.StageRouting(run_id="r-entry", plan_stage="writing")
    routing.route("hook_engine", [stage_routing.RoutedLens(
        identity=BENCH_LENS, digest="sha256:abc", probe=BENCH_CANARY)])
    client = mock.MagicMock()
    plain = mock.MagicMock()
    plain.choices = [mock.MagicMock(message=mock.MagicMock(content='{"ok": true}'))]
    client.chat.completions.create.return_value = plain
    parsed = mock.MagicMock()
    parsed.choices = [mock.MagicMock(message=mock.MagicMock(parsed=Answer(ok=True)))]
    client.beta.chat.completions.parse.return_value = parsed

    with (
        mock.patch.object(llm_client, "_get_client", return_value=client),
        stage_routing.recording(routing),
        stage_routing.stage("hook_engine"),
    ):
        if entry == "chat_parsed":
            llm_client.chat_parsed(f"sys {BENCH_CANARY}", "user", Answer)
        else:
            getattr(llm_client, entry)(system=f"sys {BENCH_CANARY}", user="user")

    assert len(routing.requests) == 1, f"{entry} was not observed"
    assert routing.requests[0].state == stage_routing.COMPLETE


def test_one_observation_mechanism_not_three():
    """The seam is shared: each entry point calls the same hook once."""
    source = Path("src/utils/llm_client.py").read_text(encoding="utf-8")

    assert source.count("observe_request(system, user)") == 3
    assert source.count("def observe_request") == 0        # defined once, elsewhere
    assert "from src.run.stage_routing import observe_request" in source
