"""#269: the plan is executed, and what is not true to it is refused.

#267 built an ``EditorialPlan`` and proved it reaches the composer. This suite
is about the other half: the run that *executes* it. Three things have to be
true at once, and each is proven against the real production path rather than
described.

* **Reachability.** The selected plan and this run's active lenses reach the
  Composer, the Factual Reviewer and the Reviser — one run, canary strings
  planted in a fixture client's own documents, read back out of the exact
  messages each of those models receives. Every one has its mutation twin: cut
  the wiring and the canaries disappear.
* **Factual integrity is separate, and it rejects.** The factual boundary is
  reviewed against the plan — the claim, the ceiling, the evidence package,
  the restrictions — never against a rubric, and a finding blocks rather than
  annotating. It fails closed on an unreadable verdict.
* **Execution is not a template.** The editorial reviewer is told, in its own
  request, the six things it may not mechanically enforce.

Plus the mechanical gate, whose evidence tiers are not flattened into one hard
rule, and the accepted article, which records the plan and contract lineage it
ran under.

The client here is ``tests/fixtures/client_gearworks``, supplied only as
documents (#240 D12). No Engine code knows any of it, and no network or model
is involved: every transport is a deterministic fake.
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
from src.editorial import platform_composer
from src.editorial.editorial_acceptance import (
    EXECUTION_REVIEW_SCOPE,
    EditorialAcceptanceRubric,
)
from src.editorial.editorial_plan import EditorialPlan
from src.editorial.factual_review import (
    FACTUAL_FINDING_KINDS,
    UNSUPPORTED_CLAIM,
    FactualReviewError,
    parse_factual_findings,
)
from src.editorial.machine_tells import (
    DEFAULT_MACHINE_TELLS_PATH,
    GATE,
    OWNER_REVIEW,
    SUGGESTION,
    TIER_OUTCOMES,
    UNTRACEABLE_FIGURE,
    WARNING,
    MachineTellList,
    scan,
    untraceable_figures,
)
from tests.test_decision_lifecycle import _entry_patches, _evaluator, _model_output
from tests.test_editorial_acceptance import (
    FakeReviewTransport,
    FakeRevisionTransport,
    _review_payload,
)
from tests.test_monday_stream import MONDAY_ROLE
from tests.test_plan_decisions import (
    FIXTURE_CLIENT,
    ScriptedDecider,
    _revision_client,
    _run_answer,
)
from tests.test_research_artifact_lifecycle import ReadyProvider
from tests.test_social_derivation_invariant import (
    FINAL_ARTICLE,
    FaithfulComposer,
    RecordingJudge,
    _draft,
)
from tests.test_visual_contract import _pimgs

#: The proven end-to-end article with its one untraceable figure removed. The
#: evidence package this run carries states no number at all, so "28%" is a
#: figure that traces to nothing — which is the point of the gated twin below.
TRACEABLE_ARTICLE = FINAL_ARTICLE.replace("rose 28%", "rose in the same period")

#: Every canary the fixture client's own documents carry into this run.
PLAN_CANARIES = (
    "GEARWORKS-ENDING-CANARY",       # ## Plan → ending_mode
    "GEARWORKS-ARTIFACT-CANARY",     # ## Plan → reader_verifiable_artifact
    "GEARWORKS-RESTRICTION-CANARY",  # ## Plan → factual_restrictions
    "GEARWORKS-LENS-CANARY",         # the conditional lens this run activated
)


class FakeFactualReviewer:
    """Returns scripted answers in sequence; records every request.

    The last answer repeats, so a test that scripts one verdict gets it for
    the recheck too without restating it.
    """

    def __init__(self, *payloads: object) -> None:
        self.payloads = list(payloads) or [{"findings": []}]
        self.calls: list[dict] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.calls.append({"instructions": instructions, "request": request})
        payload = (
            self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0]
        )
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return payload
        return json.dumps(payload)


def _finding(kind: str = UNSUPPORTED_CLAIM, quote: str = "rose in the same period") -> dict:
    return {
        "findings": [
            {"kind": kind, "quote": quote,
             "detail": "the evidence package does not contain it"}
        ]
    }


def _entrypoint(
    tmp_path,
    monkeypatch,
    *,
    client: Path | None = None,
    article: str | None = None,
    decider=None,
    reviewer=None,
    revisor=None,
    factual=None,
):
    """Drive the canonical entrypoint under ``client``'s documents.

    The REAL acceptance boundary, the REAL derivation seam and composer, and —
    unlike every other suite — the REAL factual gate: the harness patch that
    switches it off is deleted here, which is the only place it is.
    """
    monkeypatch.setenv("NB_CLIENT_DIR", str(client or FIXTURE_CLIENT))
    draft = _draft()
    draft["platforms"]["long"]["body"] = article or TRACEABLE_ARTICLE
    argv, patches = _entry_patches(tmp_path)  # dry run
    argv = argv + ["--editorial-role", MONDAY_ROLE, "--preview-fresh-images"]
    del patches["run_editorial_acceptance"]  # the REAL acceptance boundary
    del patches["recompose_platform"]  # the REAL derivation seam
    del patches["_build_factual_gate"]  # the REAL factual boundary (#269)
    patches.pop("formatting", None)
    patches.pop("generate_hashtags", None)
    del patches["_build_legacy_research_context"]  # the REAL research context
    patches["generate_article"] = mock.MagicMock(return_value=draft)
    patches["WixPublisher"] = mock.MagicMock()
    patches["LinkedInPublisher"] = mock.MagicMock()
    composer = FaithfulComposer()
    factual = factual if factual is not None else FakeFactualReviewer()
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
            editorial_reviewer=reviewer or FakeReviewTransport(
                _review_payload(), _review_payload()
            ),
            article_revisor=revisor or FakeRevisionTransport(TRACEABLE_ARTICLE),
            derivation_judge=RecordingJudge(),
            plan_decider=decider or ScriptedDecider(_run_answer(recall_met=True)),
            factual_reviewer=factual,
        )
    return code, composer, factual


def _artifact(tmp_path, name: str) -> dict | None:
    found = next(tmp_path.glob(f"*/runs/*/{name}"), None)
    return None if found is None else json.loads(found.read_text())


def _request(transport) -> dict:
    assert transport.calls, "the run never reached this model"
    return json.loads(transport.calls[0]["request"])


# ── 1. reachability: the plan reaches composer, reviewer and reviser ────────


def test_the_selected_plan_and_active_lenses_reach_the_composer(tmp_path, monkeypatch):
    code, composer, _ = _entrypoint(tmp_path, monkeypatch)

    assert code == 0
    composed = "\n".join(composer.prompts)
    for canary in PLAN_CANARIES:
        assert canary in composed, canary


def test_the_selected_plan_reaches_the_factual_reviewer(tmp_path, monkeypatch):
    """The factual boundary judges against the plan, not against a rubric."""
    code, _, factual = _entrypoint(tmp_path, monkeypatch)

    assert code == 0
    request = _request(factual)
    assert request["article"] == TRACEABLE_ARTICLE
    assert any(
        "GEARWORKS-RESTRICTION-CANARY" in restriction
        for restriction in request["factual_restrictions"]
    )
    # the ceiling this run chose, on the ladder the client's contract declares
    assert request["claim_strength_ceiling"] == "confirmed by the manufacturer"
    assert request["claim_strength_ladder"][0] == "observed on one shop floor"
    # the evidence boundaries, both sides of them
    assert [item["evidence_id"] for item in request["evidence_package"]] == [
        "evidence-1"
    ]
    assert "do_not_use" in request


def test_the_selected_plan_and_findings_reach_the_reviser(tmp_path, monkeypatch):
    """A reviser fixing a factual finding sees the plan it may fix it with."""
    revisor = FakeRevisionTransport(TRACEABLE_ARTICLE)

    code, _, _ = _entrypoint(
        tmp_path, monkeypatch,
        client=_revision_client(tmp_path),
        revisor=revisor,
        factual=FakeFactualReviewer(_finding(), {"findings": []}),
    )

    assert code == 0
    request = _request(revisor)
    for canary in PLAN_CANARIES:
        assert canary in request["editorial_plan"], canary
    # the conditional lens this run activated for revision, and the finding
    assert any(
        "GEARWORKS-REVISION-CANARY" in lens for lens in request["client_lenses"]
    )
    assert request["factual_findings"] == [
        f"{UNSUPPORTED_CLAIM}: rose in the same period — "
        "the evidence package does not contain it"
    ]
    assert "Every factual finding in this request must be resolved" in request["note"]


def test_the_reviser_is_told_to_stay_surgical(tmp_path, monkeypatch):
    revisor = FakeRevisionTransport(TRACEABLE_ARTICLE)

    _entrypoint(
        tmp_path, monkeypatch, revisor=revisor,
        factual=FakeFactualReviewer(_finding(), {"findings": []}),
    )

    note = _request(revisor)["note"]
    assert "Revision is surgical" in note
    assert "explicitly requires the article to be written again" in note


def test_unwiring_the_plan_removes_it_from_every_stage(tmp_path, monkeypatch):
    """The mutation twin: the plan is the only route to any of the three.

    Same client, same contract, same run — only ``as_prompt_text`` stops
    producing the plan. If a canary survived that, it would be reaching a
    model by some route this suite is not watching.
    """
    monkeypatch.setattr(EditorialPlan, "as_prompt_text", lambda self: "")
    revisor = FakeRevisionTransport(TRACEABLE_ARTICLE)

    code, composer, _ = _entrypoint(
        tmp_path, monkeypatch, revisor=revisor,
        factual=FakeFactualReviewer(_finding(), {"findings": []}),
    )

    assert code == 0
    assert "GEARWORKS-ENDING-CANARY" not in "\n".join(composer.prompts)
    assert not _request(revisor).get("editorial_plan")


def test_without_the_gate_no_factual_review_happens(tmp_path, monkeypatch):
    """The other mutation twin: the gate is the factual reviewer's only route."""
    factual = FakeFactualReviewer()

    with mock.patch.object(gap, "_build_factual_gate", return_value=None):
        code, _, _ = _entrypoint(tmp_path, monkeypatch, factual=factual)

    assert code == 0
    assert factual.calls == []
    assert _artifact(tmp_path, "editorial_acceptance.json")["factual_review"] is None


# ── 2. the factual reviewer rejects, and fails closed ───────────────────────


def test_a_factual_finding_blocks_the_article_rather_than_annotating_it(
    tmp_path, monkeypatch
):
    code, _, _ = _entrypoint(
        tmp_path, monkeypatch,
        factual=FakeFactualReviewer(_finding()),  # still found after the revision
    )

    assert code == 1
    audit = _artifact(tmp_path, "editorial_acceptance.json")
    assert audit["accepted"] is False
    # the editorial reviewer accepted it; the factual one did not, and that
    # is not a trade the editorial verdict gets to win
    assert audit["final_disposition"] == "accept"
    assert audit["final_factual_review"]["findings"][0]["kind"] == UNSUPPORTED_CLAIM
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_a_resolved_finding_costs_exactly_one_revision(tmp_path, monkeypatch):
    factual = FakeFactualReviewer(_finding(), {"findings": []})

    code, _, _ = _entrypoint(tmp_path, monkeypatch, factual=factual)

    assert code == 0
    assert len(factual.calls) == 2  # the draft, then the revision. No loop.
    audit = _artifact(tmp_path, "editorial_acceptance.json")
    assert audit["revised"] is True
    assert audit["factual_review"]["passed"] is False
    assert audit["final_factual_review"]["passed"] is True


def test_an_unreadable_factual_verdict_stops_the_run(tmp_path, monkeypatch):
    code, _, _ = _entrypoint(
        tmp_path, monkeypatch, factual=FakeFactualReviewer("not json at all")
    )

    assert code == 1
    assert not list(tmp_path.glob("*/runs/*/generated.json"))


def test_a_factual_transport_failure_stops_the_run(tmp_path, monkeypatch):
    code, _, _ = _entrypoint(
        tmp_path, monkeypatch,
        factual=FakeFactualReviewer(RuntimeError("transport down")),
    )

    assert code == 1


@pytest.mark.parametrize(
    "answer",
    [
        '{"findings": {}}',
        '{"findings": [{"kind": "badly_written", "quote": "q", "detail": "d"}]}',
        '{"findings": [{"kind": "unsupported_claim", "quote": "", "detail": "d"}]}',
        '["unsupported_claim"]',
    ],
    ids=["not-a-list", "unknown-kind", "no-quote", "not-an-object"],
)
def test_every_unusable_verdict_shape_fails_closed(answer):
    with pytest.raises(FactualReviewError):
        parse_factual_findings(answer)


def test_the_enforced_kinds_are_the_ones_the_issue_names():
    assert FACTUAL_FINDING_KINDS == {
        "unsupported_claim", "invented_causality", "claim_strength_escalation",
        "invented_entity", "invented_attribution", "untraceable_number",
        "factual_restriction_breach", "provenance_breach",
    }


def test_the_reviewer_is_told_to_reject_and_to_judge_nothing_else():
    from src.editorial.factual_review import FACTUAL_REVIEW_INSTRUCTIONS

    instructions = FACTUAL_REVIEW_INSTRUCTIONS
    for kind in FACTUAL_FINDING_KINDS:
        assert kind in instructions, kind
    assert "You do NOT judge writing, structure, paragraph order" in instructions
    assert "Stating a number is not the same as tracing one" in instructions


# ── 3. the editorial reviewer evaluates execution, not a template ───────────

TEMPLATE_MOVES = (
    "the order its paragraphs or sections appear in",
    "whether it contains a portable noun",
    "whether it contains an authorial-risk moment",
    "whether it contains a Turn",
    "whether it concedes something, when no real objection exists",
    "which middle pattern it used",
)


def test_the_reviewer_is_forbidden_from_enforcing_the_template():
    for move in TEMPLATE_MOVES:
        assert move in EXECUTION_REVIEW_SCOPE, move
    assert "possible template defect" in EXECUTION_REVIEW_SCOPE
    assert "Factual integrity is reviewed separately" in EXECUTION_REVIEW_SCOPE


def test_the_scope_reaches_the_real_editorial_reviewer(tmp_path, monkeypatch):
    reviewer = FakeReviewTransport(_review_payload(), _review_payload())

    code, _, _ = _entrypoint(tmp_path, monkeypatch, reviewer=reviewer)

    assert code == 0
    assert _request(reviewer)["review_scope"] == EXECUTION_REVIEW_SCOPE


def test_no_rubric_criterion_asks_for_a_structural_element():
    """The rubric judges execution too: nothing in it is a checklist item."""
    rubric = EditorialAcceptanceRubric.load()
    described = " ".join(c.description for c in rubric.criteria).casefold()

    for banned in ("portable noun", "paragraph order", "the turn",
                   "authorial risk", "middle pattern"):
        assert banned not in described, banned


# ── 4. the mechanical gate, in tiers that are not flattened ─────────────────


def test_the_shared_list_is_versioned_and_engine_owned():
    tells = MachineTellList.load()

    assert tells.identity == "engine-machine-tells/1"
    assert DEFAULT_MACHINE_TELLS_PATH.name == "shared.yaml"
    assert all(entry.tier in TIER_OUTCOMES for entry in tells.entries)


@pytest.mark.parametrize(
    "tier,outcome",
    [("hard_evidence", GATE), ("directional", WARNING),
     ("observed_practice", SUGGESTION), ("owner_judgement", OWNER_REVIEW)],
)
def test_each_evidence_tier_keeps_its_own_outcome(tier, outcome):
    assert TIER_OUTCOMES[tier] == outcome


def test_only_hard_evidence_can_block():
    """One text carrying all four tiers; only the hard one stops anything."""
    tells = MachineTellList.load()
    text = (
        "Moreover, the shop sees it. "
        "At the end of the day the bench decides. "
        "One. Two. Three. Four. Five. Six. "
        "A change — a real one — and another — also real — and a third — "
        "again — follows."
    )

    found = scan(text, tells=tells)

    assert {tell.kind for tell in found.gated} == {"transition"}
    assert found.blocks is True
    assert [tell.entry_id for tell in found.warnings] == ["at-the-end-of-the-day"]
    assert "three-beat-fragments" in [tell.entry_id for tell in found.suggestions]
    assert [tell.entry_id for tell in found.owner_review] == ["em-dash-aside"]


def test_a_directional_tell_alone_never_stops_an_article():
    found = scan(
        "At the end of the day the bench decides.", tells=MachineTellList.load()
    )

    assert found.findings and found.blocks is False


def test_a_lede_move_is_only_a_lede_move_in_the_lede():
    tells = MachineTellList.load()

    assert scan("Imagine a shop floor at six.", tells=tells).blocks is True
    assert scan(
        "The notice landed on Tuesday morning.\n\nImagine a shop floor at six.",
        tells=tells,
    ).blocks is False


def test_a_repeated_pattern_is_a_finding_only_when_it_repeats():
    tells = MachineTellList.load()
    once = "It is not just the tolerance but the sheet behind it."

    assert scan(once, tells=tells).findings == ()
    assert [tell.entry_id for tell in scan(f"{once} {once}", tells=tells).findings] == [
        "not-just-but"
    ]


def test_a_client_extends_the_shared_list_and_its_own_entries_gate():
    found = scan(
        "This tool is a game changer for the bench.",
        tells=MachineTellList.load(),
        client_entries=(("game changer", "gearworks-machine-tells/1"),),
    )

    assert [tell.source for tell in found.gated] == ["gearworks-machine-tells/1"]
    assert found.as_evidence()["lists"] == [
        "engine-machine-tells/1", "gearworks-machine-tells/1",
    ]


def test_a_client_list_entry_is_matched_whatever_the_spacing_and_case():
    found = scan(
        "In Today's   Fast-Paced\nManufacturing Landscape, this ships.",
        client_entries=(
            ("in today's fast-paced manufacturing landscape",
             "gearworks-machine-tells/1"),
        ),
    )

    assert len(found.gated) == 1


# ── 5. consequence traceability: a number traces, or it does not ────────────


def test_a_number_the_evidence_package_never_states_is_untraceable():
    assert untraceable_figures(
        "Form submissions rose 28% in the same period.", "A verified claim"
    ) == ("28",)


def test_a_number_the_evidence_states_traces():
    assert untraceable_figures(
        "The notice states a 14-week lead time.",
        "Lead time for the 8mm collet is now 14-week from order.",
    ) == ()


def test_an_address_is_not_a_quantity():
    """A Sources line citing a dated URL states no figure."""
    assert untraceable_figures(
        "Source: Verified report (https://source.example/2026/07/report).",
        "A verified claim",
    ) == ()


def test_presence_of_a_number_is_not_compliance(tmp_path, monkeypatch):
    """The end-to-end twin: the same article, gated on its one figure.

    Nothing in this run's evidence package contains 28, and the factual
    reviewer here reports nothing at all — the figure is refused mechanically,
    so a reviewer that overlooks it cannot let it through.
    """
    code, _, factual = _entrypoint(
        tmp_path, monkeypatch,
        article=FINAL_ARTICLE,
        revisor=FakeRevisionTransport(FINAL_ARTICLE),
    )

    assert code == 1
    assert len(factual.calls) == 2  # the draft, then the one revision
    audit = _artifact(tmp_path, "editorial_acceptance.json")
    assert audit["final_factual_review"]["findings"] == []  # the model saw nothing
    gated = audit["final_factual_review"]["mechanical"]["findings"]
    assert [found["kind"] for found in gated] == [UNTRACEABLE_FIGURE]
    assert gated[0]["quote"] == "28"
    assert audit["accepted"] is False


# ── 6. the accepted article records what it was executed under ──────────────


def test_the_accepted_article_records_its_plan_and_contract_lineage(
    tmp_path, monkeypatch
):
    code, _, _ = _entrypoint(tmp_path, monkeypatch)

    assert code == 0
    record = _artifact(tmp_path, "accepted_composition.json")
    plan = record["editorial_plan"]
    assert plan["lineage"]["stream"]["identity"] == "gearworks-weekly/2"
    assert plan["lineage"]["stream"]["digest"].startswith("sha256:")
    assert plan["lineage"]["lists"][0]["identity"] == "gearworks-machine-tells/1"
    assert plan["claim_strength_ceiling"] == "confirmed by the manufacturer"
    assert {
        "identity": "gearworks-recall/1", "activation": "manufacturer_recall",
    } in plan["active_by_stage"]["writing"]
    assert plan["run_decisions"]["activations"][0]["met"] is True
    assert record["editorial"]["factual_review"]["passed"] is True


def test_a_blocked_run_still_records_the_factual_verdict(tmp_path, monkeypatch):
    code, _, _ = _entrypoint(
        tmp_path, monkeypatch, factual=FakeFactualReviewer(_finding())
    )

    assert code == 1
    preserved = _artifact(tmp_path, "editorial_review_content.json")
    assert preserved["editorial"]["factual_findings"] == [UNSUPPORTED_CLAIM]
    assert preserved["publishable"] is False


# ── 7. and none of it taught the Engine a client ────────────────────────────


def test_no_engine_module_and_no_shared_list_knows_this_client():
    shared = DEFAULT_MACHINE_TELLS_PATH.read_text(encoding="utf-8")

    assert "earworks" not in shared.casefold()
    for module in Path("src").rglob("*.py"):
        text = module.read_text(encoding="utf-8")
        assert "earworks" not in text.casefold(), module
        for canary in PLAN_CANARIES:
            assert canary not in text, module


def test_never_blank_keeps_the_shared_list_and_adds_none_of_its_own():
    """Never Blank ships no banned list; the shared one still applies to it."""
    from src.strategy.client_contracts import DEFAULT_CLIENT_DIR, contracts_for_role

    contracts = contracts_for_role(MONDAY_ROLE, DEFAULT_CLIENT_DIR)

    assert contracts.banned_entries == ()
    assert MachineTellList.load().entries


def test_the_fixture_client_is_still_only_documents(tmp_path):
    """Edit the document, and what the gate refuses changes with it."""
    client = tmp_path / "client"
    shutil.copytree(FIXTURE_CLIENT, client)
    shared = client / "lists" / "machine_tells.md"
    shared.write_text(
        shared.read_text(encoding="utf-8").replace("game changer", "paradigm shift"),
        encoding="utf-8",
    )
    from src.strategy.client_contracts import contracts_for_role

    entries = contracts_for_role(MONDAY_ROLE, client).banned_entries

    assert scan("A real paradigm shift.", client_entries=entries).blocks is True
    assert scan("A real game changer.", client_entries=entries).blocks is False
