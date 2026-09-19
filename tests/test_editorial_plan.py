"""#267: a human editorial contract, executed as an EditorialPlan.

The disease this epic treats is documents that exist and are never read. So the
first tests here are not about plan semantics at all: they put canary strings in
a fixture client's contract, run the **real** production prompt path, and prove
the canaries are in the exact messages the composer model receives. Only after
that do the mechanics get tested — because mechanics nothing reads are the bug.

Every test below drives a second client (`tests/fixtures/client_gearworks`)
supplied only as documents: different topic, different audience, a ceiling on
how strongly a claim may be stated, a conditional obligation and a banned-phrase
list Never Blank does not have. No Engine code knows any of it. That is the
Replace-the-client test (#240 D12 addendum), run over the #267 mechanics.

No network, no model: every transport is a deterministic fake.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.editorial import platform_composer
from src.editorial.editorial_plan import (
    CLAIM_STRENGTH_ESCALATION,
    DO_NOT_USE_EVIDENCE,
    INVENTED_ENTITY_ATTRIBUTION,
    UNSUPPORTED_INFERENCE,
    UNTRACEABLE_NUMBER,
    Claim,
    EditorialPlanError,
    EvidenceItem,
    EvidencePackage,
    PortableNoun,
    build_editorial_plan,
    check_claims,
    portfolio_regularity,
)
from src.editorial.editorial_role import render_editorial_role_rules, resolve_editorial_role
from src.strategy.business_config import load_business_strategy_configuration
from src.strategy.client_contracts import (
    DEFAULT_CLIENT_DIR,
    ClientContractError,
    contracts_for_role,
    load_stream_contract,
)
from tests.test_no_mandatory_thesis import _run_real_prompt_path

FIXTURE_CLIENT = Path("tests/fixtures/client_gearworks")
MONDAY_ROLE = "never-blank-monday-documented-case"

CANARIES = (
    "GEARWORKS-ENDING-CANARY",       # ## Plan → ending_mode
    "GEARWORKS-ARTIFACT-CANARY",     # ## Plan → reader_verifiable_artifact
    "GEARWORKS-RESTRICTION-CANARY",  # ## Plan → factual_restrictions
    "GEARWORKS-LENS-CANARY",         # a conditional lens this run activated
    "GEARWORKS-BANNED-CANARY",       # a shared banned-phrase list
)

RECALL_EVIDENCE = "The manufacturer published recall notice R-114 on 2026-09-15."


def _evidence() -> EvidencePackage:
    return EvidencePackage((
        EvidenceItem(
            item_id="ev-1",
            statement="The manufacturer's own notice states a 14-week lead time.",
            provenance=("src-1",),
            support=("Lead time for the 8mm collet is now 14-week from order.",),
        ),
        EvidenceItem(
            item_id="ev-2",
            statement="A forum post says six months.",
            usable=False,
            reason="an unattributed forum rumour, not the manufacturer",
        ),
    ))


def _claim(**overrides) -> Claim:
    fields = {
        "text": "The manufacturer published a 14-week lead time for the 8mm collet.",
        "strength": "confirmed by the manufacturer",
        "evidence_refs": ("ev-1",),
        "numbers": ("14-week",),
    }
    fields.update(overrides)
    return Claim(**fields)


def _plan(directory: Path = FIXTURE_CLIENT, **overrides):
    contracts = contracts_for_role(MONDAY_ROLE, directory)
    assert contracts is not None, "the fixture client governs the Monday role"
    arguments = {
        "central_claim": _claim(),
        "evidence": _evidence(),
        "claim_strength_ceiling": "confirmed by the manufacturer",
        "activation_evidence": {"manufacturer_recall": RECALL_EVIDENCE},
    }
    arguments.update(overrides)
    return build_editorial_plan(contracts, **arguments)


def _compose(monkeypatch, directory: Path = FIXTURE_CLIENT, plan=None) -> list[str]:
    """Run the real prompt path under a client and return the composer messages."""
    monkeypatch.setenv("NB_CLIENT_DIR", str(directory))
    calls, _ = _run_real_prompt_path(
        monkeypatch, MONDAY_ROLE, "lead-time",
        "A published lead time moved before any shop requalified the part.",
        editorial_plan=plan,
    )
    return calls["platform_composer"]


# ── the loader assertion, first: does any of this reach a model at all? ─────


def test_every_canary_in_the_client_contract_reaches_the_composer_messages(monkeypatch):
    """human contract → loaded snapshot → EditorialPlan → the model's message.

    Nothing here asserts that a file exists or that a document parses. The
    messages below are the ones ``src.editorial.platform_composer`` builds and
    hands to ``chat``; if the plan stops being wired into them, every canary
    disappears and this fails.
    """
    messages = _compose(monkeypatch, plan=_plan())

    composed = "\n".join(messages)
    for canary in CANARIES:
        assert canary in composed, canary
    assert platform_composer.compose_platforms.__module__ == (
        "src.editorial.platform_composer"
    )


def test_the_plan_reaches_both_published_surfaces(monkeypatch):
    messages = _compose(monkeypatch, plan=_plan())

    for format_key in ("long", "medium"):
        carrying = [m for m in messages if f"FORMAT: {format_key}" in m]
        assert len(carrying) == 1, format_key
        for canary in CANARIES:
            assert canary in carrying[0], f"{format_key}: {canary}"


def test_removing_the_plan_from_the_run_removes_every_canary(monkeypatch):
    """The mutation proof: unwire the plan and the assertion above fails.

    The same client, the same contract, the same run — only the plan is not
    passed. If the canaries survived that, they would be reaching the model
    through something other than the plan, and the test above would be proving
    nothing.
    """
    messages = _compose(monkeypatch, plan=None)

    assert "GEARWORKS" not in "\n".join(messages)


def test_a_canary_comes_from_the_document_and_never_from_the_engine(
    monkeypatch, tmp_path
):
    """Edit the document, and the model's message changes with it."""
    client = tmp_path / "client"
    shutil.copytree(FIXTURE_CLIENT, client)
    stream = client / "streams" / "weekly.md"
    stream.write_text(
        stream.read_text(encoding="utf-8").replace(
            "GEARWORKS-ENDING-CANARY", "REWRITTEN-ENDING-CANARY"
        ),
        encoding="utf-8",
    )

    composed = "\n".join(_compose(monkeypatch, client, plan=_plan(client)))

    assert "REWRITTEN-ENDING-CANARY" in composed
    assert "GEARWORKS-ENDING-CANARY" not in composed


def test_a_conditional_lens_reaches_the_model_only_when_this_run_activated_it(
    monkeypatch,
):
    composed = "\n".join(_compose(
        monkeypatch, plan=_plan(activation_evidence={})
    ))

    assert "GEARWORKS-LENS-CANARY" not in composed
    # everything the contract states unconditionally is still there
    assert "GEARWORKS-ENDING-CANARY" in composed


def test_no_engine_module_knows_this_client():
    """The Replace-the-client proof: the mechanics above are in Python, the
    policy they executed is in documents, and the two never meet."""
    for module in Path("src").rglob("*.py"):
        text = module.read_text(encoding="utf-8")
        assert "earworks" not in text.casefold(), module
        for canary in CANARIES:
            assert canary not in text, module


# ── the plan slots: Engine names, client values ─────────────────────────────


def test_the_contract_decides_a_slot_it_permits_one_value_for():
    plan = _plan()

    assert plan.ending_mode.startswith("GEARWORKS-ENDING-CANARY")
    assert plan.audience_currency == "machine hours a shop loses per week"
    assert plan.reader_verifiable_artifact.startswith("GEARWORKS-ARTIFACT-CANARY")


def test_a_slot_the_contract_permits_several_values_for_must_be_chosen():
    with pytest.raises(EditorialPlanError, match="chose none"):
        _plan(claim_strength_ceiling="")


def test_a_value_the_contract_does_not_permit_stops_the_run():
    with pytest.raises(EditorialPlanError, match="not a `claim_strength_ceiling`"):
        _plan(central_claim=_claim(strength=""),
              claim_strength_ceiling="proven beyond doubt")


def test_a_list_slot_carries_the_contract_then_what_the_run_adds():
    plan = _plan(acknowledged_limits=("The notice covers one product line.",))

    assert plan.acknowledged_limits == (
        "One shop's bench is not the trade.",
        "The notice covers one product line.",
    )
    assert any("GEARWORKS-RESTRICTION-CANARY" in r for r in plan.factual_restrictions)


def test_a_plan_slot_the_engine_does_not_carry_fails_closed(tmp_path):
    path = _stream_with(tmp_path, "### ending_mode", "### endng_mode")

    with pytest.raises(ClientContractError, match="not a plan slot the Engine carries"):
        load_stream_contract(path)


def test_a_contract_may_not_state_a_value_the_run_must_find(tmp_path):
    path = _stream_with(tmp_path, "### ending_mode", "### central_claim")

    with pytest.raises(ClientContractError, match="decided by the run"):
        load_stream_contract(path)


def test_a_plan_line_outside_a_slot_group_fails_closed(tmp_path):
    path = _stream_with(tmp_path, "## Plan\n", "## Plan\n\n- A loose rule.\n")

    with pytest.raises(ClientContractError, match="belongs to a `### <slot>` group"):
        load_stream_contract(path)


def test_a_slot_declared_twice_fails_closed(tmp_path):
    path = _stream_with(
        tmp_path, "### audience_currency", "### ending_mode\n\n- Something else.\n"
    )

    with pytest.raises(ClientContractError, match="declared twice"):
        load_stream_contract(path)


def _stream_with(root: Path, old: str, new: str) -> Path:
    path = root / "weekly.md"
    path.write_text(
        (FIXTURE_CLIENT / "streams" / "weekly.md")
        .read_text(encoding="utf-8").replace(old, new, 1),
        encoding="utf-8",
    )
    return path


# ── standing obligations and conditional lenses ─────────────────────────────


def test_a_standing_obligation_is_active_without_any_evidence():
    plan = _plan(activation_evidence={})

    standing = [lens for lens in plan.active_lenses if lens.is_standing]
    assert [lens.identity for lens in standing] == ["gearworks-bench/1"]


def test_an_activated_lens_records_what_activated_it():
    plan = _plan()

    activated = [lens for lens in plan.active_lenses if not lens.is_standing]
    assert len(activated) == 1
    assert activated[0].identity == "gearworks-recall/1"
    assert activated[0].activation == "manufacturer_recall"
    assert activated[0].activation_evidence == RECALL_EVIDENCE


def test_activation_evidence_for_a_condition_no_lens_declares_fails_closed():
    with pytest.raises(EditorialPlanError, match="no lens declares"):
        _plan(activation_evidence={"supplier_merger": "Two suppliers merged."})


def test_a_lens_may_not_be_activated_without_evidence():
    with pytest.raises(EditorialPlanError, match="applied on evidence or not at all"):
        _plan(activation_evidence={"manufacturer_recall": "   "})


def test_a_conditional_lens_never_reaches_a_stage_outside_a_plan():
    contracts = contracts_for_role(MONDAY_ROLE, FIXTURE_CLIENT)

    writing = contracts.for_stage("writing")
    assert all("GEARWORKS-LENS-CANARY" not in text for text in writing)
    assert [lens.lens_id for lens in contracts.conditional_for_stage("writing")] == [
        "gearworks-recall"
    ]


# ── evidence integrity: universal, never editorial ──────────────────────────


def test_a_claim_that_cites_nothing_is_an_unsupported_inference():
    findings = check_claims(
        (_claim(evidence_refs=(), numbers=()),), evidence=_evidence()
    )

    assert [f.kind for f in findings] == [UNSUPPORTED_INFERENCE]


def test_a_claim_that_cites_evidence_the_package_does_not_have_is_unsupported():
    findings = check_claims(
        (_claim(evidence_refs=("ev-9",), numbers=()),), evidence=_evidence()
    )

    assert [f.kind for f in findings] == [UNSUPPORTED_INFERENCE]
    assert "ev-9" in findings[0].detail


def test_a_claim_may_not_rest_on_a_do_not_use_item():
    findings = check_claims(
        (_claim(evidence_refs=("ev-2",), numbers=()),), evidence=_evidence()
    )

    assert [f.kind for f in findings] == [DO_NOT_USE_EVIDENCE]
    assert "unattributed forum rumour" in findings[0].detail


def test_the_plan_refuses_a_central_claim_built_on_a_do_not_use_item():
    with pytest.raises(EditorialPlanError, match="does not survive its own evidence"):
        _plan(central_claim=_claim(evidence_refs=("ev-2",)))


def test_a_claim_stated_above_the_ceiling_is_an_escalation():
    """The ladder is the client's, in the client's own words and order."""
    findings = check_claims(
        (_claim(strength="established across the trade"),),
        evidence=_evidence(),
        ceiling="confirmed by the manufacturer",
        strength_ladder=_ladder(),
    )

    assert [f.kind for f in findings] == [CLAIM_STRENGTH_ESCALATION]


def test_a_claim_at_or_below_the_ceiling_is_not_an_escalation():
    findings = check_claims(
        (_claim(strength="observed on one shop floor"),),
        evidence=_evidence(),
        ceiling="confirmed by the manufacturer",
        strength_ladder=_ladder(),
    )

    assert findings == ()


def test_a_strength_that_is_not_on_the_ladder_cannot_be_compared():
    with pytest.raises(EditorialPlanError, match="not on the contract's ladder"):
        check_claims(
            (_claim(strength="self-evident"),), evidence=_evidence(),
            ceiling="confirmed by the manufacturer", strength_ladder=_ladder(),
        )


def test_an_entity_the_cited_evidence_never_names_is_invented():
    findings = check_claims(
        (_claim(entities=("Brenner Tooling GmbH",)),), evidence=_evidence()
    )

    assert [f.kind for f in findings] == [INVENTED_ENTITY_ATTRIBUTION]


def test_a_number_the_cited_evidence_never_states_is_untraceable():
    findings = check_claims((_claim(numbers=("14-week", "62%")),), evidence=_evidence())

    assert [f.kind for f in findings] == [UNTRACEABLE_NUMBER]
    assert "62%" in findings[0].detail


def test_an_evidence_item_may_not_be_withdrawn_without_a_reason():
    with pytest.raises(EditorialPlanError, match="says no reason"):
        EvidencePackage((EvidenceItem(item_id="ev-1", statement="A claim.", usable=False),))


def _ladder() -> tuple[str, ...]:
    return contracts_for_role(MONDAY_ROLE, FIXTURE_CLIENT).stream.plan_values(
        "claim_strength_ceiling"
    )


# ── shared machine-tell and ban lists ───────────────────────────────────────


def test_a_shared_list_is_matched_whatever_the_spacing_and_case():
    plan = _plan()

    matched = plan.forbidden_in(
        "In Today's   Fast-Paced\nManufacturing Landscape, this is a game changer."
    )

    assert [entry for entry, _ in matched] == [
        "in today's fast-paced manufacturing landscape", "game changer",
    ]
    assert {source for _, source in matched} == {"gearworks-machine-tells/1"}


def test_clean_text_matches_nothing():
    assert _plan().forbidden_in("The collet ships in fourteen weeks.") == ()


def test_a_list_declared_for_another_stream_is_not_loaded(tmp_path):
    client = tmp_path / "client"
    shutil.copytree(FIXTURE_CLIENT, client)
    shared = client / "lists" / "machine_tells.md"
    shared.write_text(
        shared.read_text(encoding="utf-8").replace(
            "applies_to: [gearworks-weekly]", "applies_to: [some-other-stream]"
        ),
        encoding="utf-8",
    )

    assert contracts_for_role(MONDAY_ROLE, client).banned_entries == ()


def test_one_list_id_in_two_documents_fails_the_run(tmp_path):
    client = tmp_path / "client"
    shutil.copytree(FIXTURE_CLIENT, client)
    shutil.copy(
        client / "lists" / "machine_tells.md", client / "lists" / "copy.md"
    )

    with pytest.raises(ClientContractError, match="list id"):
        contracts_for_role(MONDAY_ROLE, client)


# ── portfolio-level regularity is evidence, never a rule ────────────────────


def test_regularity_counts_a_value_across_the_portfolio_and_says_nothing_more():
    records = [
        {"run_id": "run-1", "ending_mode": "a measurement at the bench"},
        {"run_id": "run-2", "ending_mode": "a measurement at the bench"},
        {"run_id": "run-3", "ending_mode": "an open question"},
    ]

    observed = portfolio_regularity(records, "ending_mode")

    assert [(o.value, o.occurrences) for o in observed] == [
        ("a measurement at the bench", 2), ("an open question", 1),
    ]
    assert observed[0].runs == ("run-1", "run-2")


def test_regularity_counts_every_entry_of_a_list_slot():
    records = [
        {"run_id": "run-1", "acknowledged_limits": ["One bench is not the trade."]},
        {"run_id": "run-2", "acknowledged_limits": ["One bench is not the trade.",
                                                    "The notice covers one line."]},
    ]

    observed = portfolio_regularity(records, "acknowledged_limits")

    assert observed[0].value == "One bench is not the trade."
    assert observed[0].occurrences == 2


def test_regularity_a_run_carries_reaches_its_plan():
    plan = _plan(regularity=portfolio_regularity(
        [{"run_id": "run-1", "ending_mode": "a measurement at the bench"}], "ending_mode"
    ))

    assert plan.as_evidence()["regularity"] == [
        {"slot": "ending_mode", "value": "a measurement at the bench",
         "occurrences": 1, "runs": ["run-1"]}
    ]


# ── what a run persists ─────────────────────────────────────────────────────


def test_the_plan_records_the_exact_contract_and_lens_versions_it_ran_on():
    contracts = contracts_for_role(MONDAY_ROLE, FIXTURE_CLIENT)

    record = _plan().as_evidence()

    assert record["lineage"] == contracts.provenance
    assert record["lineage"]["stream"]["identity"] == "gearworks-weekly/2"
    assert all(
        lens["digest"].startswith("sha256:") for lens in record["lineage"]["lenses"]
    )
    assert record["lineage"]["lists"][0]["identity"] == "gearworks-machine-tells/1"


def test_the_record_carries_every_slot_including_what_may_not_be_used():
    record = _plan(
        portable_noun=PortableNoun("requalification debt", "kept", "earned by the case")
    ).as_evidence()

    for slot in (
        "central_claim", "claim_strength_ceiling", "evidence_package",
        "factual_restrictions", "active_lenses", "reader_verifiable_artifact",
        "ending_mode", "audience_currency", "acknowledged_limits", "portable_noun",
        "lineage",
    ):
        assert slot in record, slot
    assert record["portable_noun"] == {
        "noun": "requalification debt", "decision": "kept",
        "rationale": "earned by the case",
    }
    withdrawn = [i for i in record["evidence_package"] if not i["usable"]]
    assert [i["item_id"] for i in withdrawn] == ["ev-2"]


def test_a_plan_needs_the_claim_the_run_is_built_on():
    with pytest.raises(EditorialPlanError, match="central claim"):
        _plan(central_claim=Claim(text="   "))


# ── the critical invariant: no editorial arc in the Engine ──────────────────


def test_the_plan_is_not_a_paragraph_outline():
    """It says what the article must be true to, never where anything goes."""
    text = _plan().as_prompt_text()

    assert "it is not a paragraph outline" in text
    for arc in ("paragraph 1", "Hook", "Recognition", "Reframe", "Echo",
                "Compound Presence", "step 1"):
        assert arc not in text, arc


def test_every_value_in_the_rendered_plan_is_the_clients_own_text():
    plan = _plan()
    document = (FIXTURE_CLIENT / "streams" / "weekly.md").read_text(encoding="utf-8")
    flattened = " ".join(document.split())

    for value in (plan.ending_mode, plan.audience_currency,
                  plan.reader_verifiable_artifact, plan.claim_strength_ceiling,
                  *plan.factual_restrictions, *plan.acknowledged_limits):
        assert value in flattened, value


# ── and Never Blank's own run is untouched until its contract says so ───────


def test_never_blank_declares_no_plan_and_therefore_runs_as_before():
    contracts = contracts_for_role(MONDAY_ROLE, DEFAULT_CLIENT_DIR)

    assert contracts.stream.plan_slots == ()
    assert contracts.banned_entries == ()
    assert all(lens.is_standing for lens in contracts.lenses)


def test_the_fixture_client_reaches_the_same_engine_stages_never_blank_does(monkeypatch):
    """Purpose, selection and lenses still route exactly as #240 D12 left them."""
    monkeypatch.setenv("NB_CLIENT_DIR", str(FIXTURE_CLIENT))
    configuration = load_business_strategy_configuration(
        Path("strategy/current/business_strategy.json")
    )
    contracts = contracts_for_role(MONDAY_ROLE)

    _, role = resolve_editorial_role(configuration, MONDAY_ROLE)
    rendered = render_editorial_role_rules(
        role, surface="wix", lenses=contracts.for_stage("writing")
    )

    assert role.intent.startswith("Help a machine shop owner decide")
    assert role.eligibility_criteria[0].startswith("The signal names a part")
    assert "Write to a shop owner standing at a bench" in rendered
    assert "GEARWORKS-LENS-CANARY" not in rendered
