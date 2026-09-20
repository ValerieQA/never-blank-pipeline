"""#268: Never Blank Editorial Policy v2, as documents the run executes.

The policy itself is the owner's, written in `clients/never_blank/` and nowhere
else: the frame and its variable middle, the ending that stops at the Kicker,
the concession and portable-noun policies, the constructions Never Blank never
publishes, and the values the stream's `## Plan` states or leaves to the run.

What these tests prove is the only thing code can prove about a policy: that it
**arrives**. Each assertion below is on a message a model actually receives on
the real production path — the argument-building stages first, then the
composer — or on the reviser's request. And the last section replaces the
client whole: another client's documents produce another client's article, with
no Never Blank semantics anywhere and no Engine change.

No network, no model: every transport is a fake.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest import mock

import pytest

import scripts.generate_and_publish as gap
from scripts.generate_and_publish import main
from src.strategy.client_contracts import contracts_for_role, load_lens
from tests import test_generate_and_publish as legacy
from tests.test_263_fidelity_and_evidence_tension import ScriptedDecider, _article
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_editorial_acceptance import (
    FakeReviewTransport,
    FakeRevisionTransport,
    _review_payload,
)
from tests.test_monday_stream import MONDAY_ROLE
from tests.test_no_mandatory_thesis import _run_real_prompt_path
from tests.test_research_artifact_lifecycle import ReadyProvider

NB = Path("clients/never_blank")
SIG = legacy._SIGNAL_ID

#: One phrase from each v2 document, chosen to be unmistakably the client's.
POLICY_CANARIES = {
    "structure/frame": "Hook — one checkable thing",
    "structure/middle": "Choose one pattern for the middle before writing",
    "structure/obligations": "A moment of authorial risk",
    "concession": "the strongest honest objection to our own claim",
    "portable noun": "The cut test, for minting",
}


def _nb():
    return contracts_for_role(MONDAY_ROLE, NB)


def _decider(*, tension_met: bool = False, artifact_index: int = 0) -> ScriptedDecider:
    """The run's decisions: the condition, and the one slot the contract opens."""
    artifacts = _nb().stream.plan_values("reader_verifiable_artifact")
    return ScriptedDecider({
        "activations": [{
            "condition": "evidence_tension", "met": tension_met,
            "finding": "The source's own figures point the other way."
                       if tension_met else "",
            "evidence_refs": ["evidence-1"] if tension_met else [],
            "reason": "decided from the research evidence",
        }],
        "selections": [{
            "slot": "reader_verifiable_artifact", "value": artifacts[artifact_index],
            "evidence_refs": [], "reason": "what this run's evidence supports",
        }],
    })


def _run(tmp_path, *, decider=None, reviewer=None, revisor=None, client: Path | None = None,
         monkeypatch=None):
    """The canonical entrypoint, dry run, under a client's documents."""
    if client is not None and monkeypatch is not None:
        monkeypatch.setenv("NB_CLIENT_DIR", str(client))
    argv, patches = _entry_patches(tmp_path)
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    patches["generate_article"] = mock.MagicMock(return_value=_article())
    if reviewer is not None:
        del patches["run_editorial_acceptance"]          # the REAL acceptance boundary
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(
            research_provider=ReadyProvider(), decision_evaluator=evaluator,
            plan_decider=decider or _decider(),
            **({"editorial_reviewer": reviewer} if reviewer is not None else {}),
            **({"article_revisor": revisor} if revisor is not None else {}),
        )
    plan_file = next(tmp_path.glob(f"{SIG}/runs/*/editorial_plan.json"), None)
    return (code, patches["generate_article"],
            json.loads(plan_file.read_text()) if plan_file else None)


# ── the policy reaches the stages that build the argument ───────────────────


def test_every_v2_document_reaches_the_argument_stages_and_the_composer(
    tmp_path, monkeypatch
):
    """The chain #268 asks for: documents → plan and role rules → the real
    narrative spine, hook engine, voice and composer messages."""
    code, generate, _ = _run(tmp_path, decider=_decider())
    assert code == 0

    plan = generate.call_args.kwargs["editorial_plan"]
    calls, _ = _run_real_prompt_path(
        monkeypatch, MONDAY_ROLE, "price", "A published figure moved first.",
        editorial_plan=plan,
    )
    rules = generate.call_args.kwargs["editorial_role_rules"]

    for label, canary in POLICY_CANARIES.items():
        # the writing lenses travel with the role's rules, to both surfaces
        for surface in ("long", "medium"):
            assert canary in rules[surface], f"{label} → {surface}"
    # and the plan itself reaches every stage that shapes the argument
    for stage in ("narrative_spine", "hook_engine", "never_blank_voice",
                  "platform_composer"):
        message = "\n".join(calls[stage])
        assert "EDITORIAL PLAN" in message, stage
        assert plan.ending_mode in message, stage


def test_the_article_ends_on_the_kicker_and_the_plan_says_so(tmp_path):
    code, _, record = _run(tmp_path, decider=_decider())

    assert code == 0
    ending = record["ending_mode"]
    assert ending.startswith("Close on the Kicker/Echo")
    assert "Nothing follows it" in ending
    # the retired ending is gone from the client's documents entirely
    for document in sorted(NB.glob("lenses/*.md")) + sorted(NB.glob("streams/*.md")):
        assert "Soft CTA" not in document.read_text(encoding="utf-8"), document


def test_the_run_chooses_the_verifiable_artifact_the_contract_offers(tmp_path):
    permitted = _nb().stream.plan_values("reader_verifiable_artifact")

    code, _, record = _run(tmp_path, decider=_decider(artifact_index=2))

    assert code == 0
    assert record["reader_verifiable_artifact"] == permitted[2]
    assert record["run_decisions"]["selections"][0]["position"] == 2
    assert len(permitted) == 3


def test_the_banned_constructions_reach_the_writers_as_the_clients_list(tmp_path):
    code, generate, record = _run(tmp_path, decider=_decider())

    assert code == 0
    entries = [entry["entry"] for entry in record["banned"]]
    assert "it's not about" in entries
    assert all(entry["list"] == "never-blank-machine-tells/1" for entry in record["banned"])
    plan_text = generate.call_args.kwargs["editorial_plan"].as_prompt_text()
    assert "Never write any of these, in any form" in plan_text
    assert "it's not about" in plan_text


def test_the_concession_and_portable_noun_policies_reach_the_reviser(tmp_path):
    reviewer = FakeReviewTransport(
        _review_payload(disposition="revise", failed=["unsupported-claims"],
                        guidance="Say only what the evidence supports."),
        _review_payload(),
    )
    revisor = FakeRevisionTransport(_article()["platforms"]["long"]["body"])

    code, _, _ = _run(tmp_path, decider=_decider(), reviewer=reviewer, revisor=revisor)

    assert code == 0
    lenses = "\n".join(json.loads(revisor.calls[0]["request"])["client_lenses"])
    assert POLICY_CANARIES["concession"] in lenses
    assert POLICY_CANARIES["portable noun"] in lenses
    # the writing-only structure lens is not the reviser's business
    assert POLICY_CANARIES["structure/middle"] not in lenses


# ── the policy is the client's, and the Engine knows none of it ─────────────


def test_no_engine_module_carries_never_blanks_editorial_policy():
    """The Engine holds slots; every value above is in a client document."""
    #: Phrases that only Never Blank's policy uses. Generic Engine vocabulary
    #: for the mechanisms themselves — a banned list, a plan slot, a lens — is
    #: not policy and is deliberately absent from this list.
    policy = (
        "Kicker", "authorial risk", "cut test", "Post-mortem", "Teardown",
        "portable noun of our own", "it's not about", "Front-loading",
        "one checkable thing", "strongest honest objection",
    )
    #: The canonical Editorial v2 path. ``src/quality/voice.py`` is deliberately
    #: not here: it belongs to the legacy ``scripts/generate.py`` path, which
    #: this architecture replaces, and it still carries a hard-coded Never Blank
    #: phrase list. Retiring it travels with that path, not with #268.
    engine = [
        *Path("src/editorial").rglob("*.py"),
        *Path("src/strategy").rglob("*.py"),
        *Path("src/artifacts").rglob("*.py"),
        *Path("src/research").rglob("*.py"),
        Path("scripts/generate_and_publish.py"),
    ]
    for module in engine:
        text = module.read_text(encoding="utf-8")
        for phrase in policy:
            assert phrase not in text, f"{module}: {phrase}"


ACME_STREAM = """---
stream_id: acme-weekly
version: "1"
role_id: never-blank-monday-documented-case
selection: first_valid
---

## Purpose

Help an independent bakery decide what to bake this week.

## Selection

### Useful

- The signal concerns a bakery's own costs, suppliers or customers.

## Plan

### ending_mode

- ACME-ENDING: close on the one batch to change on Monday morning.

### reader_verifiable_artifact

- ACME-ARTIFACT: the delivery note the bakery already files.
"""
ACME_LENS = """---
lens_id: acme-voice
version: "1"
applies_to: [acme-weekly]
stages: [writing]
---

ACME-LENS: write to a baker at 5am, in short sentences, about one decision.
"""


def _acme(tmp_path: Path) -> Path:
    client = tmp_path / "acme"
    (client / "streams").mkdir(parents=True)
    (client / "lenses").mkdir(parents=True)
    (client / "streams" / "weekly.md").write_text(ACME_STREAM, encoding="utf-8")
    (client / "lenses" / "voice.md").write_text(ACME_LENS, encoding="utf-8")
    return client


def test_replacing_the_client_replaces_the_whole_policy(tmp_path, monkeypatch):
    """Another client's documents, the same Engine, no code change: its values
    reach the writers and none of Never Blank's do."""
    code, generate, record = _run(
        tmp_path / "run", decider=_decider(), client=_acme(tmp_path),
        monkeypatch=monkeypatch,
    )

    assert code == 0
    assert record["lineage"]["stream"]["identity"] == "acme-weekly/1"
    assert record["ending_mode"].startswith("ACME-ENDING")
    assert record["reader_verifiable_artifact"].startswith("ACME-ARTIFACT")
    assert record["banned"] == []                       # Acme keeps no list
    rules = generate.call_args.kwargs["editorial_role_rules"]
    plan_text = generate.call_args.kwargs["editorial_plan"].as_prompt_text()
    for surface in ("long", "medium"):
        assert "ACME-LENS" in rules[surface], surface
        for canary in POLICY_CANARIES.values():
            assert canary not in rules[surface], canary
    for canary in POLICY_CANARIES.values():
        assert canary not in plan_text, canary


def test_a_client_whose_contract_decides_everything_costs_no_decision(
    tmp_path, monkeypatch
):
    """Acme states one value per slot and declares no conditional lens, so its
    run has nothing to decide — and makes no decider call at all."""
    decider = ScriptedDecider({"activations": [], "selections": []})

    code, _, record = _run(
        tmp_path / "run", decider=decider, client=_acme(tmp_path), monkeypatch=monkeypatch
    )

    assert code == 0
    assert decider.requests == []
    assert record["run_decisions"]["decided_by"] == ""
    assert record["run_decisions"]["activations"] == []
    assert record["active_lenses"][0]["identity"] == "acme-voice/1"
    # the contract decided both slots by stating one value each
    assert record["ending_mode"].startswith("ACME-ENDING")
    assert record["reader_verifiable_artifact"].startswith("ACME-ARTIFACT")


@pytest.mark.parametrize("mutation", [
    lambda text: text.replace("### ending_mode", "### ending_style"),
    lambda text: text.replace("### ending_mode", "### central_claim"),
], ids=["slot-the-engine-does-not-carry", "value-only-the-run-can-find"])
def test_a_broken_client_plan_stops_the_run_rather_than_guessing(
    tmp_path, monkeypatch, mutation
):
    client = _acme(tmp_path)
    stream = client / "streams" / "weekly.md"
    stream.write_text(mutation(stream.read_text(encoding="utf-8")), encoding="utf-8")
    monkeypatch.setenv("NB_CLIENT_DIR", str(client))

    argv, patches = _entry_patches(tmp_path / "run")
    argv = argv + ["--editorial-role", MONDAY_ROLE]
    patches["generate_article"] = mock.MagicMock(return_value=_article())
    evaluator, _ = _evaluator(_model_output())
    with mock.patch.object(sys, "argv", argv), mock.patch.multiple(gap, **patches):
        code = main(research_provider=ReadyProvider(), decision_evaluator=evaluator,
                    plan_decider=_decider())

    assert code == 1
    assert not patches["generate_article"].called


def test_the_client_documents_are_the_only_place_the_policy_lives(tmp_path):
    """Edit the document, and the model's message changes with it."""
    client = tmp_path / "client"
    shutil.copytree(NB, client)
    structure = client / "lenses" / "structure.md"
    structure.write_text(
        structure.read_text(encoding="utf-8").replace(
            "A moment of authorial risk", "A REWRITTEN OBLIGATION"
        ),
        encoding="utf-8",
    )

    writing = contracts_for_role(MONDAY_ROLE, client).for_stage("writing")

    assert any("A REWRITTEN OBLIGATION" in text for text in writing)
    assert not any("A moment of authorial risk" in text for text in writing)
    assert load_lens(client / "lenses" / "structure.md").version == "2"


# ── decided every time, and "none" is a real answer ─────────────────────────


def test_the_obligations_that_may_be_none_say_so_where_the_writer_reads_them():
    """Review of 6c68678: one document may not say "every article" while
    another says "none is a valid decision" — the model receives both."""
    structure = " ".join(load_lens(NB / "lenses" / "structure.md").text.split())
    portable = " ".join(load_lens(NB / "lenses" / "portable_noun.md").text.split())

    # the portable noun and the moment of authorial risk are decided, not owed
    assert (
        "Two are decided every time, and the decision may be that this article "
        "has none"
    ) in structure
    assert "mint, reuse, or none" in structure
    assert "Never invent one to fill the slot." in structure
    assert "Where the material gives the writer nothing to risk, write none" in structure
    # and the portable-noun lens still says the same thing
    assert "None is a legitimate outcome" in portable
    # what is genuinely always there is stated separately
    assert "**Always present**" in structure
    assert "Something the reader can check or touch" in structure
    # no text tells the writer every article must carry a portable noun
    assert "portable noun" not in structure.split("**Always present**")[1].split(
        "**Always decided"
    )[0]


def test_activation_conditions_are_decidable_before_the_article_exists():
    """Review of 6c68678: condition 3 required something "visible in the
    finished article", which does not exist when activation is decided."""
    lens = " ".join(load_lens(NB / "lenses" / "evidence_tension_lens.md").text.split())
    conditions, behaviour = lens.split("What to do when it is active")

    # the precondition is about the evidence, which exists now
    assert "The mismatch survives the most charitable reading of the evidence." in (
        conditions
    )
    assert "using the research evidence alone" in conditions
    assert "The condition is met only if that attempt was actually made" in conditions
    assert "finished article" not in conditions
    # showing the attempt is an obligation of the article, once active
    assert "Show the charitable reading that failed." in behaviour
    assert "the article is where the reader sees it" in behaviour


# ── the portfolio record: counted, never enforced ───────────────────────────


def test_the_portfolio_counts_activations_across_real_runs(tmp_path):
    """Three real runs, two with the condition met: the count comes from the
    editorial_plan.json each run persisted, not from a test fixture."""
    from scripts.portfolio_activation import plan_records
    from src.editorial.editorial_plan import activation_rates

    for index, met in enumerate((True, False, True)):
        code, _, _ = _run(tmp_path / f"run{index}", decider=_decider(tension_met=met))
        assert code == 0

    records = [record for index in range(3)
               for record in plan_records(tmp_path / f"run{index}")]
    observed = activation_rates(records)

    assert len(records) == 3
    assert [o.condition for o in observed] == ["evidence_tension"]
    assert observed[0].eligible == 3 and observed[0].activated == 2
    assert round(observed[0].rate, 2) == 0.67
    assert len(observed[0].runs) == 2            # traceable to the runs themselves


def test_the_engine_holds_no_activation_threshold_anywhere():
    """Observation, by product decision: a cap in code would make the next
    activation a way to satisfy a metric."""
    from src.editorial.editorial_plan import ActivationObservation

    source = Path("src/editorial/editorial_plan.py").read_text(encoding="utf-8")
    report = Path("scripts/portfolio_activation.py").read_text(encoding="utf-8")

    assert "no threshold" in ActivationObservation.__doc__.casefold().replace(
        "no rate threshold", "no threshold"
    )
    for forbidden in ("max_activation", "activation_limit", "MAX_RATE", "threshold ="):
        assert forbidden not in source, forbidden
        assert forbidden not in report, forbidden
    # and the report reads the portfolio without writing to it
    assert "write_text" not in report and "mkdir" not in report


def test_a_portfolio_with_no_decisions_reports_nothing_rather_than_failing(tmp_path):
    from scripts.portfolio_activation import plan_records
    from src.editorial.editorial_plan import activation_rates

    assert plan_records(tmp_path / "empty") == []
    assert activation_rates([]) == ()
    # a damaged record is skipped, not fatal
    broken = tmp_path / "p" / "sig" / "runs" / "r1"
    broken.mkdir(parents=True)
    (broken / "editorial_plan.json").write_text("{not json", encoding="utf-8")
    assert plan_records(tmp_path / "p") == []
