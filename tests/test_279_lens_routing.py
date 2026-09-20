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
    assert carried.stage == "hook_engine" and carried.complete is True
    assert carried.contained == (BENCH_LENS,)
    assert absent.complete is False and absent.missing == (BENCH_LENS,)
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
        routing.observe(stage, f"PROMPT {' '.join(l.probe for l in routed)}")
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
        assert request["complete"] is True


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

    carried = routing.observe("hook_engine", f"PROMPT… {BENCH_CANARY} …rest")
    absent = routing.observe("hook_engine", "PROMPT with no obligation in it")

    assert carried.complete is True and carried.contained == (BENCH_LENS,)
    assert absent.complete is False and absent.missing == (BENCH_LENS,)
    assert routing.as_evidence()["delivered"]["hook_engine"] == [BENCH_LENS]


def test_the_probe_is_inert_outside_a_recorded_run():
    """Nothing outside a recorded generation pays for the observability."""
    assert stage_routing.current() is None
    stage_routing.observe_request("anything at all")      # must not raise

    routing = stage_routing.StageRouting()
    with stage_routing.recording(routing), stage_routing.stage("hook_engine"):
        stage_routing.observe_request("inside")
    stage_routing.observe_request("outside again")

    assert len(routing.requests) == 1
    assert stage_routing.current() is None
