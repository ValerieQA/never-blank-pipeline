"""#267: what a client's contract leaves to the run is decided in the run.

A stream contract may leave two things open: which conditional lenses apply
(``activates_on``), and which value a multi-value ``## Plan`` slot takes. Both
are decided from this run's research evidence by one decider, held to the
contract by the Engine, recorded in ``editorial_plan.json`` and — only then —
handed to the composer.

The first half tests the Engine's hold on the decider's answer. The second
half runs the REAL entrypoint — real research artifact, real plan, real
derivation seam and composer — under the Gearworks fixture client and under a
new stream introduced by documents alone, and reads the messages the composer
model receives.

No network, no model: the decider, the reviewer and the composer are fakes.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.editorial import platform_composer
from src.editorial.editorial_plan import (
    Claim,
    EditorialPlanError,
    EvidenceItem,
    EvidencePackage,
    build_editorial_plan,
)
from src.editorial.plan_decisions import (
    ModelPlanDecider,
    plan_decision_request,
    resolve_plan_decisions,
)
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.client_contracts import contracts_for_role
from tests import test_generate_and_publish as legacy
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_editorial_acceptance import (
    FakeReviewTransport,
    FakeRevisionTransport,
    _review_payload,
)
from tests.test_monday_stream import MONDAY_ROLE
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_social_derivation_invariant import (
    FINAL_ARTICLE,
    FaithfulComposer,
    RecordingJudge,
    _draft,
)
from tests.test_visual_contract import _pimgs

FIXTURE_CLIENT = Path("tests/fixtures/client_gearworks")
SIG = legacy._SIGNAL_ID
LADDER = (
    "observed on one shop floor",
    "confirmed by the manufacturer",
    "established across the trade",
)
#: The evidence id ReadyProvider's research artifact carries.
RUN_EVIDENCE = "evidence-1"


class ScriptedDecider:
    """A plan decider that answers from a script and records what it was asked."""

    identity = "test:scripted-decider"

    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.requests: list[dict] = []

    def decide(self, request):
        self.requests.append(json.loads(json.dumps(request)))
        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)


class ExplodingDecider:
    identity = "test:exploding"

    def decide(self, request):
        raise AssertionError("a contract that leaves nothing open must make no call")


def _activation(condition="manufacturer_recall", met=True, refs=("ev-1",), **extra):
    entry = {
        "condition": condition,
        "met": met,
        "finding": "Recall notice R-114 names the collet." if met else "",
        "evidence_refs": list(refs),
        "reason": "The notice is in the evidence.",
    }
    entry.update(extra)
    return entry


def _selection(slot="claim_strength_ceiling", value=LADDER[1], refs=("ev-1",), **extra):
    entry = {
        "slot": slot,
        "value": value,
        "evidence_refs": list(refs),
        "reason": "The manufacturer published the figure itself.",
    }
    entry.update(extra)
    return entry


def _answer(activations=None, selections=None) -> dict:
    return {
        "activations": activations
        if activations is not None
        else [
            _activation(),
            _activation("regulatory_change", met=False, refs=()),
        ],
        "selections": selections if selections is not None else [_selection()],
    }


def _evidence() -> EvidencePackage:
    return EvidencePackage(
        (
            EvidenceItem(
                item_id="ev-1",
                statement="Recall notice R-114 covers the 8mm collet.",
                support=("R-114 recalls the 8mm collet.",),
            ),
            EvidenceItem(
                item_id="ev-2",
                statement="A forum post says every collet is recalled.",
                usable=False,
                reason="an unattributed rumour",
            ),
        )
    )


def _contracts(directory: Path = FIXTURE_CLIENT, role: str = MONDAY_ROLE):
    contracts = contracts_for_role(role, directory)
    assert contracts is not None
    return contracts


def _resolve(answer, directory: Path = FIXTURE_CLIENT):
    return resolve_plan_decisions(
        _contracts(directory),
        central_claim=Claim(text="The collet was recalled."),
        evidence=_evidence(),
        decider=ScriptedDecider(answer),
    )


# ── what the decider is asked ───────────────────────────────────────────────


def test_the_decider_is_asked_only_what_the_contract_left_open():
    request = plan_decision_request(
        _contracts(),
        central_claim=Claim(text="The collet was recalled."),
        evidence=_evidence(),
    )

    assert [c["condition"] for c in request["conditions"]] == [
        "manufacturer_recall",
        "regulatory_change",
    ]
    # the condition comes with the client's own lens text, verbatim
    lens = request["conditions"][0]["lenses"][0]
    assert lens["lens"] == "gearworks-recall/1"
    assert "GEARWORKS-LENS-CANARY" in lens["text"]
    # only the slot the contract permits several values for — the others it decided
    assert request["slots"] == [
        {"slot": "claim_strength_ceiling", "permitted": list(LADDER)}
    ]
    # the run's evidence, including what it may not use and why
    assert [(e["id"], e["usable"]) for e in request["evidence"]] == [
        ("ev-1", True),
        ("ev-2", False),
    ]
    assert set(request) == {"central_claim", "conditions", "slots", "evidence"}


def test_a_contract_that_leaves_nothing_open_makes_no_call(tmp_path):
    client = tmp_path / "client"
    shutil.copytree(FIXTURE_CLIENT, client)
    (client / "lenses" / "recall.md").unlink()
    stream = client / "streams" / "weekly.md"
    stream.write_text(
        stream.read_text(encoding="utf-8").replace(
            "- observed on one shop floor\n- confirmed by the manufacturer\n"
            "- established across the trade\n",
            "- confirmed by the manufacturer\n",
        ),
        encoding="utf-8",
    )

    decisions = resolve_plan_decisions(
        _contracts(client),
        central_claim=Claim(text="c"),
        evidence=_evidence(),
        decider=ExplodingDecider(),
    )

    assert decisions.as_evidence()["decided_by"] == ""
    assert decisions.activation_evidence == {} and decisions.selected == {}


def test_the_production_decider_is_one_model_call_through_the_shared_client():
    calls = []

    def fake_chat(**kwargs):
        calls.append(kwargs)
        return json.dumps(_answer())

    with (
        mock.patch("src.utils.llm_client.chat", side_effect=fake_chat),
        mock.patch("src.utils.llm_client.model_enrich", return_value="m"),
    ):
        decisions = resolve_plan_decisions(
            _contracts(),
            central_claim=Claim(text="c"),
            evidence=_evidence(),
            decider=ModelPlanDecider(),
        )

    assert len(calls) == 1 and calls[0]["json_mode"] is True
    assert decisions.decided_by == "model:NB_ENRICH_MODEL"


# ── an activation is evidence the run holds, or it is refused ───────────────


def test_a_met_condition_carries_its_finding_and_evidence_into_the_plan():
    decisions = _resolve(_answer())
    plan = build_editorial_plan(
        _contracts(),
        central_claim=Claim(text="The collet was recalled."),
        evidence=_evidence(),
        decisions=decisions,
    )

    recall = [lens for lens in plan.active_lenses if not lens.is_standing]
    assert [lens.identity for lens in recall] == ["gearworks-recall/1"]
    assert recall[0].activation == "manufacturer_recall"
    assert recall[0].activation_evidence == (
        "Recall notice R-114 names the collet. [evidence: ev-1]"
    )
    record = plan.as_evidence()["run_decisions"]
    assert record["decided_by"] == "test:scripted-decider"
    assert record["contract"]["identity"] == "gearworks-weekly/2"
    assert record["activations"][0]["declared_by"] == ["gearworks-recall/1"]
    assert record["activations"][1] == {
        "condition": "regulatory_change",
        "met": False,
        "finding": "",
        "evidence_refs": [],
        "reason": "The notice is in the evidence.",
        "declared_by": ["gearworks-recall/1"],
        "stages": ["writing"],
    }
    # the writer is told what activated it
    assert "What activated it in this run's evidence: Recall notice R-114" in (
        plan.as_prompt_text()
    )


def test_a_condition_not_met_leaves_the_lens_out():
    decisions = _resolve(
        _answer(
            activations=[
                _activation(met=False, refs=()),
                _activation("regulatory_change", met=False, refs=()),
            ]
        )
    )
    plan = build_editorial_plan(
        _contracts(),
        central_claim=Claim(text="c"),
        evidence=_evidence(),
        decisions=decisions,
    )

    assert all(lens.is_standing for lens in plan.active_lenses)
    assert "GEARWORKS-LENS-CANARY" not in plan.as_prompt_text()


@pytest.mark.parametrize(
    "activation, match",
    [
        (_activation(refs=()), "applied on evidence or not at all"),
        (_activation(finding=""), "applied on evidence or not at all"),
        (_activation(refs=("ev-9",)), "does not hold"),
        (_activation(refs=("ev-2",)), "may not use"),
        (_activation(met="yes"), "true or false"),
    ],
    ids=["no-evidence-ids", "no-finding", "invented-id", "do-not-use-id", "not-a-bool"],
)
def test_an_activation_the_evidence_does_not_establish_stops_the_run(activation, match):
    with pytest.raises(EditorialPlanError, match=match):
        _resolve(
            _answer(
                activations=[
                    activation,
                    _activation("regulatory_change", met=False, refs=()),
                ]
            )
        )


@pytest.mark.parametrize(
    "activations, match",
    [
        ([_activation()], "undecided: regulatory_change"),
        (
            [
                _activation(),
                _activation("regulatory_change", met=False, refs=()),
                _activation("supplier_merger", met=False, refs=()),
            ],
            "nobody asked",
        ),
        (
            [
                _activation(),
                _activation(),
                _activation("regulatory_change", met=False, refs=()),
            ],
            "twice",
        ),
    ],
    ids=["unanswered", "unknown-condition", "answered-twice"],
)
def test_every_condition_is_answered_exactly_once(activations, match):
    with pytest.raises(EditorialPlanError, match=match):
        _resolve(_answer(activations=activations))


# ── a multi-value slot takes one permitted value, or the run stops ──────────


def test_the_chosen_value_and_its_lineage_are_recorded():
    decisions = _resolve(_answer())
    plan = build_editorial_plan(
        _contracts(),
        central_claim=Claim(text="c"),
        evidence=_evidence(),
        decisions=decisions,
    )

    assert plan.claim_strength_ceiling == LADDER[1]
    assert plan.strength_ladder == LADDER
    assert plan.as_evidence()["run_decisions"]["selections"] == [
        {
            "slot": "claim_strength_ceiling",
            "value": LADDER[1],
            "position": 1,
            "permitted": list(LADDER),
            "evidence_refs": ["ev-1"],
            "reason": "The manufacturer published the figure itself.",
        }
    ]


@pytest.mark.parametrize(
    "selection, match",
    [
        (_selection(value=""), "could not choose"),
        (_selection(value="   "), "could not choose"),
        (_selection(value=None), "must be a string"),
        (_selection(value=list(LADDER[:2])), "must be a string"),
        (_selection(value="proven beyond doubt"), "not a value the contract permits"),
        (
            _selection(value=f"{LADDER[0]} or {LADDER[1]}"),
            "not a value the contract permits",
        ),
        (_selection(refs=("ev-2",)), "may not use"),
    ],
    ids=[
        "empty",
        "blank",
        "null",
        "two-values",
        "not-permitted",
        "hedged",
        "do-not-use",
    ],
)
def test_an_ambiguous_or_foreign_choice_never_falls_back_to_the_first_value(
    selection, match
):
    with pytest.raises(EditorialPlanError, match=match):
        _resolve(_answer(selections=[selection]))


def test_a_slot_the_contract_decided_is_not_the_runs_to_choose():
    with pytest.raises(EditorialPlanError, match="nobody asked"):
        _resolve(
            _answer(
                selections=[
                    _selection(),
                    _selection(slot="ending_mode", value="anything"),
                ]
            )
        )


def test_whitespace_is_not_a_different_value():
    decisions = _resolve(
        _answer(
            selections=[
                _selection(value="  confirmed   by the manufacturer "),
            ]
        )
    )

    assert decisions.selected == {"claim_strength_ceiling": LADDER[1]}


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        json.dumps({"activations": []}),
        json.dumps({"activations": [], "selections": [], "extra": 1}),
        json.dumps({"activations": {}, "selections": []}),
    ],
)
def test_an_unreadable_answer_stops_the_run(raw):
    with pytest.raises(EditorialPlanError, match="plan decider"):
        _resolve(raw)


def test_a_decision_supplied_twice_is_refused():
    decisions = _resolve(_answer())

    with pytest.raises(EditorialPlanError, match="supplied twice"):
        build_editorial_plan(
            _contracts(),
            central_claim=Claim(text="c"),
            evidence=_evidence(),
            decisions=decisions,
            claim_strength_ceiling=LADDER[0],
        )
    with pytest.raises(EditorialPlanError, match="supplied twice"):
        build_editorial_plan(
            _contracts(),
            central_claim=Claim(text="c"),
            evidence=_evidence(),
            decisions=decisions,
            activation_evidence={"manufacturer_recall": "x"},
        )


def test_an_open_contract_with_no_decider_stops_the_run():
    with pytest.raises(EditorialPlanError, match="no decider"):
        resolve_plan_decisions(
            _contracts(),
            central_claim=Claim(text="c"),
            evidence=_evidence(),
            decider=None,
        )


# ── the production path: the real entrypoint, the real composer ─────────────


def _entrypoint(
    tmp_path,
    monkeypatch,
    *,
    client: Path,
    role: str,
    decider,
    configuration=None,
    reviewer=None,
    revisor=None,
):
    """Run the canonical entrypoint (dry run) under ``client``'s documents."""
    monkeypatch.setenv("NB_CLIENT_DIR", str(client))
    draft = _draft()
    draft["platforms"]["long"]["body"] = FINAL_ARTICLE
    argv, patches = _entry_patches(tmp_path)  # dry run
    argv = argv + ["--editorial-role", role, "--preview-fresh-images"]
    del patches["run_editorial_acceptance"]  # the REAL acceptance boundary
    del patches["recompose_platform"]  # the REAL derivation seam
    patches.pop("formatting", None)
    patches.pop("generate_hashtags", None)
    # the REAL research context, so the plan's central claim is the signal's own
    del patches["_build_legacy_research_context"]
    patches["generate_article"] = mock.MagicMock(return_value=draft)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    if configuration is not None:
        patches["load_business_strategy_configuration"] = mock.MagicMock(
            return_value=configuration
        )
    composer = FaithfulComposer()
    evaluator, _ = _evaluator(_model_output())
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch.multiple(gap, **patches),
        mock.patch.object(platform_composer, "chat", side_effect=composer),
        mock.patch(
            "scripts.research.prepare_content.prepare_content_packages",
            side_effect=lambda *a, **k: [
                {"images": {"platform_images": _pimgs(tmp_path)}}
            ],
        ),
    ):
        code = main(
            research_provider=ReadyProvider(),
            decision_evaluator=evaluator,
            editorial_reviewer=reviewer or FakeReviewTransport(_review_payload()),
            article_revisor=revisor or FakeRevisionTransport(FINAL_ARTICLE),
            derivation_judge=RecordingJudge(),
            plan_decider=decider,
        )
    plan_file = next(tmp_path.glob(f"{SIG}/runs/*/editorial_plan.json"), None)
    return (
        code,
        patches["generate_article"],
        composer,
        json.loads(plan_file.read_text()) if plan_file else None,
    )


def _run_answer(*, recall_met: bool, ceiling: str = LADDER[1]) -> dict:
    refs = (RUN_EVIDENCE,)
    return _answer(
        activations=[
            _activation(
                met=recall_met,
                refs=refs if recall_met else (),
                finding="The notice in the research names the part."
                if recall_met
                else "",
            ),
            _activation("regulatory_change", met=False, refs=()),
        ],
        selections=[_selection(value=ceiling, refs=refs)],
    )


def _medium_prompt(composer: FaithfulComposer) -> str:
    prompts = [
        p for p in composer.prompts if re.search(r"^FORMAT: medium$", p, re.MULTILINE)
    ]
    assert len(prompts) == 1
    return prompts[0]


def test_production_activates_a_client_lens_from_run_evidence_and_it_reaches_the_composer(
    tmp_path,
    monkeypatch,
):
    """run evidence → decision → plan → active lens → the composer's message.

    The lens is declared only in the fixture client's documents; the Engine
    reads the condition from them, the decider decides it on the research
    artifact the run produced, and the composer receives the lens.
    """
    decider = ScriptedDecider(_run_answer(recall_met=True))

    code, generate, composer, record = _entrypoint(
        tmp_path, monkeypatch, client=FIXTURE_CLIENT, role=MONDAY_ROLE, decider=decider
    )

    assert code == 0
    # the decider was asked once, on this run's research evidence
    assert len(decider.requests) == 1
    request = decider.requests[0]
    assert [e["id"] for e in request["evidence"]] == [RUN_EVIDENCE]
    assert "GEARWORKS-LENS-CANARY" in request["conditions"][0]["lenses"][0]["text"]
    # the decision is auditable in editorial_plan.json
    activated = [lens for lens in record["active_lenses"] if lens["activation"]]
    assert [(lens["identity"], lens["activation"]) for lens in activated] == [
        ("gearworks-recall/1", "manufacturer_recall"),
    ]
    assert RUN_EVIDENCE in activated[0]["activation_evidence"]
    assert record["run_decisions"]["activations"][0]["evidence_refs"] == [RUN_EVIDENCE]
    assert record["run_decisions"]["decided_by"] == "test:scripted-decider"
    # the multi-value slot the contract left open was chosen and recorded
    assert record["claim_strength_ceiling"] == LADDER[1]
    assert record["run_decisions"]["selections"][0]["position"] == 1
    # the same plan reached generation, and the lens reached the real composer
    assert (
        generate.call_args.kwargs["editorial_plan"].claim_strength_ceiling == LADDER[1]
    )
    medium = _medium_prompt(composer)
    assert "GEARWORKS-LENS-CANARY" in medium
    assert "The notice in the research names the part." in medium
    assert (
        f"Claim strength ceiling — never state the claim more strongly than this: "
        f"{LADDER[1]}" in medium
    )


def test_production_leaves_the_lens_out_when_run_evidence_does_not_meet_it(
    tmp_path,
    monkeypatch,
):
    decider = ScriptedDecider(_run_answer(recall_met=False, ceiling=LADDER[0]))

    code, _, composer, record = _entrypoint(
        tmp_path, monkeypatch, client=FIXTURE_CLIENT, role=MONDAY_ROLE, decider=decider
    )

    assert code == 0
    assert all(not lens["activation"] for lens in record["active_lenses"])
    assert record["run_decisions"]["activations"][0]["met"] is False
    medium = _medium_prompt(composer)
    assert "GEARWORKS-LENS-CANARY" not in medium
    assert "GEARWORKS-ENDING-CANARY" in medium
    assert record["claim_strength_ceiling"] == LADDER[0]


@pytest.mark.parametrize(
    "answer",
    [
        _run_answer(recall_met=True, ceiling=""),
        {"activations": [], "selections": []},
        "the model wrote prose",
    ],
    ids=["no-choice", "nothing-decided", "unreadable"],
)
def test_production_stops_before_writing_when_the_decision_is_not_made(
    tmp_path,
    monkeypatch,
    answer,
):
    code, generate, composer, record = _entrypoint(
        tmp_path,
        monkeypatch,
        client=FIXTURE_CLIENT,
        role=MONDAY_ROLE,
        decider=ScriptedDecider(answer),
    )

    assert code != 0
    assert not generate.called
    assert composer.prompts == []
    assert record is None


def test_never_blank_leaves_exactly_one_condition_to_its_run(tmp_path, monkeypatch):
    """Never Blank's contract decided its ending and left one condition and one
    slot to the run (#263, #268)."""
    artifacts = contracts_for_role(
        MONDAY_ROLE, Path("clients/never_blank")
    ).stream.plan_values("reader_verifiable_artifact")
    decider = ScriptedDecider(
        {
            "activations": [
                {
                    "condition": "evidence_tension",
                    "met": False,
                    "finding": "",
                    "evidence_refs": [],
                    "reason": "no tension in this evidence",
                }
            ],
            "selections": [
                {
                    "slot": "reader_verifiable_artifact",
                    "value": artifacts[1],
                    "evidence_refs": [],
                    "reason": "the source publishes the figures itself",
                }
            ],
        }
    )

    code, generate, _, record = _entrypoint(
        tmp_path,
        monkeypatch,
        client=Path("clients/never_blank"),
        role=MONDAY_ROLE,
        decider=decider,
    )

    assert code == 0
    assert [c["condition"] for c in decider.requests[0]["conditions"]] == [
        "evidence_tension"
    ]
    assert [slot["slot"] for slot in decider.requests[0]["slots"]] == [
        "reader_verifiable_artifact"
    ]
    assert record["run_decisions"]["activations"][0]["met"] is False
    assert record["run_decisions"]["selections"][0]["value"] == artifacts[1]
    assert generate.call_args.kwargs["editorial_plan"] is not None


# ── a new stream/day policy, introduced by documents alone ──────────────────

NEW_ROLE = "gearworks-friday-desk"
NEW_STREAM = """---
stream_id: gearworks-friday
version: "1"
role_id: gearworks-friday-desk
selection: first_valid
---

# Friday desk — CLIENT: GEARWORKS SUPPLY

## Purpose

Tell a shop owner, before the weekend, which one order to place or hold on
Monday morning.

## Selection

### Usable

- The signal names a part, a price or a lead time a small shop orders.

## Plan

### ending_mode

- FRIDAY-ENDING-HOLD-CANARY close on the one order to hold until the figure is
  confirmed
- FRIDAY-ENDING-PLACE-CANARY close on the one order to place before the
  supplier's next price list

### audience_currency

- FRIDAY-CURRENCY-CANARY dollars tied up in stock on the shelf
"""
NEW_LENS = """---
lens_id: gearworks-friday-desk
version: "1"
applies_to: [gearworks-friday]
stages: [writing]
---

FRIDAY-LENS-CANARY: write the note as the shop's own order desk would read it
on a Friday afternoon — one order, one figure, one date.
"""


def _new_stream_client(tmp_path: Path) -> Path:
    client = tmp_path / "client"
    shutil.copytree(FIXTURE_CLIENT, client)
    (client / "streams" / "friday.md").write_text(NEW_STREAM, encoding="utf-8")
    (client / "lenses" / "friday_desk.md").write_text(NEW_LENS, encoding="utf-8")
    return client


def _configuration_with_new_role():
    """The business configuration, declaring one more editorial role.

    Configuration data, as a client would declare it — copied from an existing
    role and renamed. No Engine Python learns the role exists.
    """
    real = load_business_strategy_configuration()
    template = next(r for r in real.editorial_roles if r.role_id == MONDAY_ROLE)
    new_role = template.model_copy(
        update={
            "role_id": NEW_ROLE,
            "intent": "Owned by clients/gearworks/streams/friday.md.",
        }
    )
    return real.model_copy(
        update={"editorial_roles": (*real.editorial_roles, new_role)}
    )


def test_a_new_stream_day_policy_is_documents_only_and_reaches_the_composer(
    tmp_path,
    monkeypatch,
):
    """Introduce a Friday-like stream with its own plan values and lens.

    Everything new is a document (a stream contract, a lens) plus one role in
    the business configuration. The run goes contract → run decision →
    EditorialPlan → composer, and the new stream's own canaries — including
    the ending the run chose between two the new contract permits — are in the
    model's message, while the other stream's are not.
    """
    client = _new_stream_client(tmp_path)
    decider = ScriptedDecider(
        {
            "activations": [],
            "selections": [
                {
                    "slot": "ending_mode",
                    "value": "FRIDAY-ENDING-PLACE-CANARY close on the one order to place before "
                    "the supplier's next price list",
                    "evidence_refs": [RUN_EVIDENCE],
                    "reason": "The price list date is in the evidence.",
                }
            ],
        }
    )

    code, generate, composer, record = _entrypoint(
        tmp_path / "run",
        monkeypatch,
        client=client,
        role=NEW_ROLE,
        decider=decider,
        configuration=_configuration_with_new_role(),
    )

    assert code == 0
    assert record["lineage"]["stream"]["identity"] == "gearworks-friday/1"
    assert record["ending_mode"].startswith("FRIDAY-ENDING-PLACE-CANARY")
    assert record["run_decisions"]["selections"][0]["permitted"][0].startswith(
        "FRIDAY-ENDING-HOLD-CANARY"
    )
    assert [s["slot"] for s in decider.requests[0]["slots"]] == ["ending_mode"]
    medium = _medium_prompt(composer)
    for canary in (
        "FRIDAY-ENDING-PLACE-CANARY",
        "FRIDAY-CURRENCY-CANARY",
        "FRIDAY-LENS-CANARY",
    ):
        assert canary in medium, canary
    # the value the run did not choose, and the other stream's policy, are absent
    for absent in (
        "FRIDAY-ENDING-HOLD-CANARY",
        "GEARWORKS-ENDING-CANARY",
        "GEARWORKS-LENS-CANARY",
    ):
        assert absent not in medium, absent
    assert generate.call_args.kwargs["editorial_plan"].ending_mode.startswith(
        "FRIDAY-ENDING-PLACE-CANARY"
    )


def test_the_same_weekly_stream_still_runs_beside_the_new_one(tmp_path, monkeypatch):
    client = _new_stream_client(tmp_path)

    code, _, composer, record = _entrypoint(
        tmp_path / "run",
        monkeypatch,
        client=client,
        role=MONDAY_ROLE,
        decider=ScriptedDecider(_run_answer(recall_met=False)),
        configuration=_configuration_with_new_role(),
    )

    assert code == 0
    assert record["lineage"]["stream"]["identity"] == "gearworks-weekly/2"
    medium = _medium_prompt(composer)
    assert "GEARWORKS-ENDING-CANARY" in medium
    assert "FRIDAY-" not in medium


def test_no_engine_module_knows_the_new_stream_or_any_weekday_policy():
    """The new stream needed no Engine edit: nothing in ``src`` names it, and
    the plan, its decisions, the contracts loader and the composer name no
    day of the week."""
    for module in Path("src").rglob("*.py"):
        text = module.read_text(encoding="utf-8")
        for name in (NEW_ROLE, "gearworks-friday", "FRIDAY-"):
            assert name not in text, (module, name)
    days = re.compile(
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE
    )
    for module in (
        "src/editorial/editorial_plan.py",
        "src/editorial/plan_decisions.py",
        "src/editorial/platform_composer.py",
        "src/strategy/client_contracts.py",
    ):
        assert not days.search(Path(module).read_text(encoding="utf-8")), module


# ── a conditional lens needs no ``## Plan`` to be executable ────────────────


def _planless_client(tmp_path: Path) -> Path:
    """The fixture client with its ``## Plan`` removed; its conditional lens stays."""
    client = tmp_path / "client"
    shutil.copytree(FIXTURE_CLIENT, client)
    stream = client / "streams" / "weekly.md"
    stream.write_text(
        stream.read_text(encoding="utf-8").split("## Plan")[0], encoding="utf-8"
    )
    contracts = _contracts(client)
    assert contracts.stream.plan_slots == ()
    assert contracts.requires_plan
    return client


def _recall_only(*, met: bool) -> dict:
    return {
        "activations": [
            _activation(
                met=met,
                refs=(RUN_EVIDENCE,) if met else (),
                finding="The notice in the research names the part." if met else "",
            ),
            _activation("regulatory_change", met=False, refs=()),
        ],
        "selections": [],
    }


def test_a_conditional_lens_activates_in_production_without_a_plan_section(
    tmp_path, monkeypatch
):
    client = _planless_client(tmp_path)
    decider = ScriptedDecider(_recall_only(met=True))

    code, _, composer, record = _entrypoint(
        tmp_path / "run", monkeypatch, client=client, role=MONDAY_ROLE, decider=decider
    )

    assert code == 0
    assert decider.requests[0]["slots"] == []
    activated = [lens for lens in record["active_lenses"] if lens["activation"]]
    assert [lens["identity"] for lens in activated] == ["gearworks-recall/1"]
    assert record["ending_mode"] == ""  # no plan values were declared
    medium = _medium_prompt(composer)
    assert "GEARWORKS-LENS-CANARY" in medium
    assert "The notice in the research names the part." in medium


def test_a_conditional_lens_without_a_plan_section_stays_out_when_not_met(
    tmp_path, monkeypatch
):
    client = _planless_client(tmp_path)

    code, _, composer, record = _entrypoint(
        tmp_path / "run",
        monkeypatch,
        client=client,
        role=MONDAY_ROLE,
        decider=ScriptedDecider(_recall_only(met=False)),
    )

    assert code == 0
    assert record["run_decisions"]["activations"][0]["met"] is False
    assert all(not lens["activation"] for lens in record["active_lenses"])
    assert "GEARWORKS-LENS-CANARY" not in _medium_prompt(composer)


# ── stage-aware activation: writing and revision, never selection ───────────

REVISION_LENS = """---
lens_id: gearworks-recall-revision
version: "1"
applies_to: [gearworks-weekly]
stages: [revision]
activates_on: [manufacturer_recall]
---

GEARWORKS-REVISION-CANARY: when revising a recall note, keep the affected part
numbers and the effective date in the first paragraph, whatever else moves.
"""


def _revision_client(tmp_path: Path) -> Path:
    """The fixture client plus a conditional lens routed to revision only."""
    client = tmp_path / "client"
    shutil.copytree(FIXTURE_CLIENT, client)
    (client / "lenses" / "recall_revision.md").write_text(
        REVISION_LENS, encoding="utf-8"
    )
    return client


def _revising():
    """A reviewer that asks for one revision, then accepts; and the reviser."""
    reviewer = FakeReviewTransport(
        _review_payload(
            disposition="revise",
            failed=["unsupported-claims"],
            guidance="Tighten the claim to what the source states.",
        ),
        _review_payload(),
    )
    return reviewer, FakeRevisionTransport(FINAL_ARTICLE)


def _reviser_lenses(revisor: FakeRevisionTransport) -> list[str]:
    assert len(revisor.calls) == 1, "the reviewer asked for exactly one revision"
    return json.loads(revisor.calls[0]["request"]).get("client_lenses", [])


def test_a_conditional_revision_lens_reaches_the_real_reviser_when_met(
    tmp_path, monkeypatch
):
    reviewer, revisor = _revising()
    decider = ScriptedDecider(_run_answer(recall_met=True))

    code, _, composer, record = _entrypoint(
        tmp_path / "run",
        monkeypatch,
        client=_revision_client(tmp_path),
        role=MONDAY_ROLE,
        decider=decider,
        reviewer=reviewer,
        revisor=revisor,
    )

    assert code == 0
    # one decision for the condition, serving every stage its lenses name
    recall = decider.requests[0]["conditions"][0]
    assert recall["condition"] == "manufacturer_recall"
    assert [lens["lens"] for lens in recall["lenses"]] == [
        "gearworks-recall/1",
        "gearworks-recall-revision/1",
    ]
    decision = record["run_decisions"]["activations"][0]
    assert decision["met"] is True
    assert decision["stages"] == ["writing", "revision"]
    assert {
        "identity": "gearworks-recall-revision/1",
        "activation": "manufacturer_recall",
    } in record["active_by_stage"]["revision"]
    # the reviser receives it, with what activated it — and the writer does not
    lenses = "\n".join(_reviser_lenses(revisor))
    assert "GEARWORKS-REVISION-CANARY" in lenses
    assert "The notice in the research names the part." in lenses
    assert "GEARWORKS-REVISION-CANARY" not in "\n".join(composer.prompts)
    # the writing-only lens stays out of the reviser; the standing one is there
    assert "GEARWORKS-LENS-CANARY" not in lenses
    assert "Write to a shop owner standing at a bench" in lenses


def test_a_conditional_revision_lens_is_recorded_inactive_and_absent_when_unmet(
    tmp_path, monkeypatch
):
    reviewer, revisor = _revising()

    code, _, _, record = _entrypoint(
        tmp_path / "run",
        monkeypatch,
        client=_revision_client(tmp_path),
        role=MONDAY_ROLE,
        decider=ScriptedDecider(_run_answer(recall_met=False)),
        reviewer=reviewer,
        revisor=revisor,
    )

    assert code == 0
    decision = record["run_decisions"]["activations"][0]
    assert decision["met"] is False and decision["stages"] == ["writing", "revision"]
    assert all(not lens["activation"] for lens in record["active_by_stage"]["revision"])
    lenses = "\n".join(_reviser_lenses(revisor))
    assert "GEARWORKS-REVISION-CANARY" not in lenses
    assert "Write to a shop owner standing at a bench" in lenses  # standing stays


def test_one_lens_for_writing_and_revision_is_decided_once_and_reaches_both(
    tmp_path, monkeypatch
):
    client = tmp_path / "client"
    shutil.copytree(FIXTURE_CLIENT, client)
    lens = client / "lenses" / "recall.md"
    lens.write_text(
        lens.read_text(encoding="utf-8").replace(
            "stages: [writing]", "stages: [writing, revision]"
        ),
        encoding="utf-8",
    )
    reviewer, revisor = _revising()
    decider = ScriptedDecider(_run_answer(recall_met=True))

    code, _, composer, record = _entrypoint(
        tmp_path / "run",
        monkeypatch,
        client=client,
        role=MONDAY_ROLE,
        decider=decider,
        reviewer=reviewer,
        revisor=revisor,
    )

    assert code == 0
    # one decider call, one answer per condition — no second authority
    assert len(decider.requests) == 1
    assert [c["condition"] for c in decider.requests[0]["conditions"]] == [
        "manufacturer_recall",
        "regulatory_change",
    ]
    activated = [lens for lens in record["active_lenses"] if lens["activation"]]
    assert [lens["identity"] for lens in activated] == ["gearworks-recall/1"]
    assert activated[0]["stages"] == ["writing", "revision"]
    for stage in ("writing", "revision"):
        assert {
            "identity": "gearworks-recall/1",
            "activation": "manufacturer_recall",
        } in record["active_by_stage"][stage]
    # the same lens, on the same evidence, at both stages
    assert "GEARWORKS-LENS-CANARY" in _medium_prompt(composer)
    lenses = "\n".join(_reviser_lenses(revisor))
    assert "GEARWORKS-LENS-CANARY" in lenses
    assert lenses.count("GEARWORKS-LENS-CANARY") == 1


def test_disconnecting_revision_routing_removes_the_lens_from_the_reviser(
    tmp_path, monkeypatch
):
    """The mutation twin: cut the plan's route to revision and the canary is
    gone — the reviser has no other way to receive a conditional lens."""
    from src.editorial.editorial_plan import EditorialPlan

    original = EditorialPlan.activated_lens_texts

    def writing_only(self, stage):
        return () if stage == "revision" else original(self, stage)

    monkeypatch.setattr(EditorialPlan, "activated_lens_texts", writing_only)
    reviewer, revisor = _revising()

    code, _, _, record = _entrypoint(
        tmp_path / "run",
        monkeypatch,
        client=_revision_client(tmp_path),
        role=MONDAY_ROLE,
        decider=ScriptedDecider(_run_answer(recall_met=True)),
        reviewer=reviewer,
        revisor=revisor,
    )

    assert code == 0
    assert record["run_decisions"]["activations"][0]["met"] is True
    assert "GEARWORKS-REVISION-CANARY" not in "\n".join(_reviser_lenses(revisor))


SELECTION_LENS = """---
lens_id: gearworks-recall-selection
version: "1"
applies_to: [gearworks-weekly]
stages: [selection, writing]
activates_on: [manufacturer_recall]
---

Prefer a recall signal over any other this week.
"""


def test_a_conditional_selection_lens_is_refused_when_the_contract_loads(tmp_path):
    from src.strategy.client_contracts import ClientContractError, load_lens

    path = tmp_path / "selection.md"
    path.write_text(SELECTION_LENS, encoding="utf-8")

    with pytest.raises(ClientContractError, match="cannot route to selection"):
        load_lens(path)


def test_a_conditional_selection_lens_stops_the_production_run_before_any_work(
    tmp_path, monkeypatch
):
    client = tmp_path / "client"
    shutil.copytree(FIXTURE_CLIENT, client)
    (client / "lenses" / "recall_selection.md").write_text(
        SELECTION_LENS, encoding="utf-8"
    )

    code, generate, composer, record = _entrypoint(
        tmp_path / "run",
        monkeypatch,
        client=client,
        role=MONDAY_ROLE,
        decider=ExplodingDecider(),
    )

    assert code == 1
    assert not generate.called and composer.prompts == [] and record is None


def test_a_standing_selection_lens_is_still_accepted(tmp_path):
    from src.strategy.client_contracts import load_lens

    path = tmp_path / "selection.md"
    path.write_text(
        SELECTION_LENS.replace("activates_on: [manufacturer_recall]\n", ""),
        encoding="utf-8",
    )

    assert load_lens(path).stages == ("selection", "writing")
