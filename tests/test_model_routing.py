"""Issue #173: stage-specific model routing is wired, not just supported.

The client has always resolved models per stage (NB_ENRICH_MODEL,
NB_ARTICLE_MODEL, NB_SOCIAL_MODEL, falling back to NB_OPENAI_CHAT_MODEL,
then gpt-4o) — but the Monday and Wednesday workflows passed only the
global variable, collapsing every stage onto one model. These scenarios
prove the resolvers route real production stages to different configured
models in one run, the fallback contract is exact (including GitHub
Actions' unset-secret-becomes-empty-string behaviour), and both canonical
workflows now carry the stage variables in the steps that use them.

No test names a real model id; routing stays configuration-driven.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.utils import llm_client


ENRICH, ARTICLE, SOCIAL, GLOBAL = (
    "test-enrich-model", "test-article-model", "test-social-model",
    "test-global-model",
)


def _route_all(monkeypatch):
    monkeypatch.setenv("NB_ENRICH_MODEL", ENRICH)
    monkeypatch.setenv("NB_ARTICLE_MODEL", ARTICLE)
    monkeypatch.setenv("NB_SOCIAL_MODEL", SOCIAL)
    monkeypatch.setenv("NB_OPENAI_CHAT_MODEL", GLOBAL)


class RecordingClient:
    """Captures the model of every request; answers with a scripted body."""

    def __init__(self, payload: dict) -> None:
        self.models: list[str] = []
        outer, body = self, json.dumps(payload)

        class _Response:
            class _Choice:
                class _Msg:
                    content = body
                message = _Msg()
            choices = [_Choice()]

        class _Completions:
            def create(self, **kwargs):
                outer.models.append(kwargs["model"])
                return _Response()

        self.chat = type("Chat", (), {"completions": _Completions()})()


# ===========================================================================
# 1–4. Real production stages resolve to different models in one run
# ===========================================================================


def test_the_eligibility_judgment_uses_the_enrich_model(monkeypatch):
    _route_all(monkeypatch)
    client = RecordingClient({"eligible": False, "reason": "Documented check."})
    monkeypatch.setattr(llm_client, "_client", client)

    from src.editorial.source_eligibility import (
        LlmChatSourceEligibilityTransport, judge_source_eligibility,
    )
    from src.strategy.business_config import EditorialRole

    role = EditorialRole(
        role_id="routing-proof", intent="i", structure=("s",), forbidden=("f",),
        eligibility_criteria=("Eligible: documented case.",),
    )
    judge_source_eligibility(
        {"SIGNAL_ID": "sig-route", "HEADLINE": "h", "CORE_FACT": "f"},
        role, LlmChatSourceEligibilityTransport(),
    )

    assert client.models == [ENRICH]


def test_the_wix_composition_uses_the_article_model(monkeypatch):
    _route_all(monkeypatch)
    body = "Evidence-led opening. " + " ".join(f"w{i}" for i in range(450))
    client = RecordingClient({"body": body, "echo_included": False, "title": None})
    monkeypatch.setattr(llm_client, "_client", client)

    from src.editorial.platform_composer import _compose_one

    _compose_one({"hook": "h", "discovery": {}}, "long")

    assert client.models == [ARTICLE]


def test_the_linkedin_composition_uses_the_social_model(monkeypatch):
    _route_all(monkeypatch)
    body = "Evidence-led opening. " + " ".join(f"w{i}" for i in range(160))
    client = RecordingClient({"body": body, "echo_included": False, "title": None})
    monkeypatch.setattr(llm_client, "_client", client)

    from src.editorial.platform_composer import _compose_one

    _compose_one({"hook": "h", "discovery": {}}, "medium")

    assert client.models == [SOCIAL]


def test_three_stages_resolve_to_three_models_in_one_run(monkeypatch):
    # one process, one environment, three categories — the collapse that
    # motivated #173 is structurally impossible once the variables are set
    _route_all(monkeypatch)
    assert (
        llm_client.model_enrich(),
        llm_client.model_article(),
        llm_client.model_social(),
    ) == (ENRICH, ARTICLE, SOCIAL)
    assert len({ENRICH, ARTICLE, SOCIAL}) == 3


def test_changing_one_stage_variable_does_not_affect_the_others(monkeypatch):
    _route_all(monkeypatch)
    monkeypatch.setenv("NB_ARTICLE_MODEL", "test-article-model-2")

    assert llm_client.model_article() == "test-article-model-2"
    assert llm_client.model_enrich() == ENRICH       # untouched
    assert llm_client.model_social() == SOCIAL       # untouched


# ===========================================================================
# 5. Monday and Wednesday both inherit the routing — shared infrastructure
# ===========================================================================

_WORKFLOWS = {
    "monday": (".github/workflows/monday_publish.yml",
               "Select eligible signal", "Monday — Generate + Publish"),
    # #211: Wednesday no longer has a model-calling selector step. It supplies
    # its own signal inside the entrypoint through the restored July research,
    # so there is no selector env to route — hence `None`.
    "wednesday": (".github/workflows/wednesday_golden.yml",
                  None, "Wednesday Golden — Generate + Publish"),
}


def _steps(path):
    data = yaml.safe_load(Path(path).read_text())
    job = next(iter(data["jobs"].values()))
    return {
        step.get("name", step.get("uses", "")): (step.get("env") or {})
        for step in job["steps"]
    }


@pytest.mark.parametrize("stream", ["monday", "wednesday"])
def test_the_workflows_carry_the_stage_variables_where_they_are_used(stream):
    path, selector_name, generate_prefix = _WORKFLOWS[stream]
    steps = _steps(path)

    generate_env = next(env for name, env in steps.items()
                        if name.startswith(generate_prefix))

    if selector_name is None:
        # Wednesday: no step outside generation may carry a model secret,
        # because no step outside generation makes a model call any more.
        for name, env in steps.items():
            if not name.startswith(generate_prefix):
                assert not [k for k in env if k.endswith("_MODEL")], name
    else:
        selector_env = next(env for name, env in steps.items()
                            if name.startswith(selector_name))
        # the selector judges eligibility via model_enrich — and needs no more
        assert selector_env["NB_ENRICH_MODEL"] == "${{ secrets.NB_ENRICH_MODEL }}"
    # generation carries all three categories, plus the global fallback
    for var in ("NB_ENRICH_MODEL", "NB_ARTICLE_MODEL", "NB_SOCIAL_MODEL",
                "NB_OPENAI_CHAT_MODEL"):
        assert generate_env[var] == "${{ secrets.%s }}" % var


def test_the_routing_is_identical_infrastructure_not_weekday_branching():
    monday = _steps(_WORKFLOWS["monday"][0])
    wednesday = _steps(_WORKFLOWS["wednesday"][0])

    def stage_vars(steps):
        return {
            name: sorted(k for k in env
                         if k in ("NB_ENRICH_MODEL", "NB_ARTICLE_MODEL",
                                  "NB_SOCIAL_MODEL"))
            for name, env in steps.items()
            if any(k.startswith("NB_") and k.endswith("_MODEL") for k in env)
        }

    # The generation step — the only stage both weekdays still share — routes
    # through identical infrastructure. #211 removed Wednesday's selector
    # stage entirely (it discovers its own signal in the entrypoint now), so
    # the comparison is between what both streams actually run, not between
    # a stage one of them no longer has.
    def generation_vars(steps, prefix):
        return next(sorted(v) for name, v in stage_vars(steps).items()
                    if name.startswith(prefix))

    assert generation_vars(monday, "Monday — Generate + Publish") == \
        generation_vars(wednesday, "Wednesday Golden — Generate + Publish")

    # and no weekday-specific MODEL variable exists on either side — the
    # scheduling variables (MONDAY_TIME, WEDNESDAY_TZ) are runtime config,
    # not routing
    for steps in (monday, wednesday):
        for name, env in steps.items():
            assert not [
                k for k in env
                if k.endswith("_MODEL") and ("MONDAY" in k or "WEDNESDAY" in k)
            ], name


def test_no_production_code_hardcodes_a_routed_model():
    # model choice is configuration; the only literal ids permitted are the
    # pre-existing defaults the inspection documented
    source = Path("src/utils/llm_client.py").read_text()
    for line in source.splitlines():
        if "gpt-" in line:
            assert "gpt-4o" in line or "gpt-image-1" in line, line


# ===========================================================================
# 6. The fallback contract, including GitHub Actions empty-string secrets
# ===========================================================================


def test_stage_set_beats_global(monkeypatch):
    monkeypatch.setenv("NB_ENRICH_MODEL", ENRICH)
    monkeypatch.setenv("NB_OPENAI_CHAT_MODEL", GLOBAL)
    assert llm_client.model_enrich() == ENRICH


def test_stage_absent_falls_back_to_global(monkeypatch):
    monkeypatch.delenv("NB_ENRICH_MODEL", raising=False)
    monkeypatch.setenv("NB_OPENAI_CHAT_MODEL", GLOBAL)
    assert llm_client.model_enrich() == GLOBAL


def test_neither_set_uses_the_preexisting_safe_default(monkeypatch):
    for var in ("NB_ENRICH_MODEL", "NB_ARTICLE_MODEL", "NB_SOCIAL_MODEL",
                "NB_OPENAI_CHAT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    assert llm_client.model_enrich() == "gpt-4o"
    assert llm_client._model() == "gpt-4o"


@pytest.mark.parametrize("empty", ["", "   "], ids=["empty", "whitespace"])
def test_an_unset_github_secret_renders_empty_and_means_absent(monkeypatch, empty):
    # GitHub Actions renders an unset secret as "" in env: — that must mean
    # "not configured", never a literal model id sent to the API
    monkeypatch.setenv("NB_ENRICH_MODEL", empty)
    monkeypatch.setenv("NB_OPENAI_CHAT_MODEL", GLOBAL)
    assert llm_client.model_enrich() == GLOBAL

    monkeypatch.setenv("NB_OPENAI_CHAT_MODEL", empty)
    assert llm_client.model_enrich() == "gpt-4o"


def test_explicit_model_argument_still_overrides_everything(monkeypatch):
    _route_all(monkeypatch)
    client = RecordingClient({"ok": True})
    monkeypatch.setattr(llm_client, "_client", client)

    llm_client.chat("s", "u", model="explicit-model")

    assert client.models == ["explicit-model"]


# ===========================================================================
# 7–9. The #170 / #171 / #172 contracts are untouched
# ===========================================================================


def test_routing_composes_with_the_call_budget(monkeypatch):
    from src.run.call_budget import (
        RunCallBudget, RunCallBudgetExceededError, activate_call_budget,
    )

    _route_all(monkeypatch)
    client = RecordingClient({"ok": True})
    monkeypatch.setattr(llm_client, "_client", client)

    budget = RunCallBudget(limit=1)
    with activate_call_budget(budget):
        llm_client.chat("s", "u", model=llm_client.model_enrich())
        with pytest.raises(RunCallBudgetExceededError):
            llm_client.chat("s", "u", model=llm_client.model_article())

    # the budget refused before transport; only the enrich call went out
    assert client.models == [ENRICH]


def test_routing_composes_with_the_retry_cap_and_api_guard(monkeypatch):
    # #170: the retry policy is independent of routing
    monkeypatch.delenv("NB_OPENAI_MAX_RETRIES", raising=False)
    assert llm_client.max_retries() == 1
    # #172: this very test runs with credentials stripped by the guard
    import os
    assert os.environ.get("NB_OPENAI_API_KEY") is None
    assert os.environ.get("OPENAI_API_KEY") is None
