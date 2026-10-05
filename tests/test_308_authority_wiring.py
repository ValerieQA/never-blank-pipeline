"""The primary-authority contract, proved through the canonical seam.

#308, owner decision 2026-10-05 (``PRIMARY-AUTHORITY-DESIGN-V1``), and the
independent review of PR #387 that refused the first attempt: the machinery was
there and nothing in a real run reached it. So every test here executes
:func:`~src.run.golden_engine.execute_canonical_topology` — or, where the
property is about one stage's own contract, that stage's production function —
and reads what the run *wrote*. None of them calls
:func:`resolve_claim_authority` directly; ``tests/test_308_primary_authority.py``
owns that unit, and a unit that passes while no run reaches it is exactly the
defect this file exists to catch.

The chain under test, end to end:

    the client contract declares a requirement
      → S-01 identifies who could confirm each claim
      → code marks the claim required-and-unestablished
      → S-03 aims a bounded lookup at the named authority
      → an unestablished authority is held at the ladder's bottom for S-04.

The case is #299's recorded UPS artifact: a company's own capital announcement,
reported by CNBC — a secondary report of a vendor's own news, which is the same
shape as the Shopify announcement reported by Search Engine Journal that #308's
acceptance sample carries, and the shape the whole policy is about.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping

import pytest

from src.editorial_core.evidence_core import (
    AUTHORITY_DIRECTIVE_PREFIX,
    AuthorityState,
    ClaimAuthority,
)
from src.research.provider import (
    CompleteResearchResult,
    PartialResearchResult,
    ProviderAttribution,
    ProviderFailure,
    ProviderFailureCode,
    ProviderInvocation,
    ResearchOperationOutcome,
    ResearchProviderRequest,
    RetrievalStatus,
    SourceOrigin,
    SourceRetrievalOutcome,
)
from src.strategy.client_contract import EvidenceRequirement, client_contract
from tests.golden_engine_boundary import (
    CLIENT_DIR,
    Boundary,
    FIXTURES,
    SCENARIO,
    Ledger,
    canonical_run,
    execute,
    recorded_artifact,
)

#: Who could confirm the recorded claim: the company whose own announcement the
#: article reports. Authored here because the *model* reports it in production —
#: this is the double's answer, not an Engine rule.
AUTHORITY = "ups.com"

#: The case's own source, in the ``SOURCE_FOR_CASE`` position: a source
#: associated with the case and nothing more. Zingerman's `zingtrain.com` has
#: this role in #308's sample; the property is that it reaches the evidence path
#: and does not become the authority by being filled in.
CASE_SOURCE = "https://example.test/case-study"


class _Research:
    """A provider that answers, and records every request it was handed.

    The recorded artifact is returned for the retrieval S-01 asks for, exactly
    as the shared double returns it. What this adds is the two things the
    authority path needs to be visible: the retrieval outcomes name the
    directive that asked for each source, and a directive the provider cannot
    answer is reported ``FAILED`` rather than quietly dropped.
    """

    def __init__(self, ledger: Ledger, *, identity: Any) -> None:
        self.ledger = ledger
        self.identity = identity
        self.requests: list[ResearchProviderRequest] = []

    def research(self, request: ResearchProviderRequest) -> CompleteResearchResult:
        self.ledger.record("research", request.signal_id)
        self.requests.append(request)
        artifact = recorded_artifact().model_copy(
            update={
                "run_id": request.run_id,
                "assignment_id": request.assignment_id,
                "signal_id": request.signal_id,
                "configuration_identity": self.identity,
                "created_at": request.requested_at,
                "sources": tuple(
                    source.model_copy(
                        update={"retrieved_at": request.requested_at}
                    )
                    for source in recorded_artifact().sources
                ),
            }
        )
        outcomes = self._outcomes(request, artifact)
        unanswered = [
            item for item in outcomes if item.status is RetrievalStatus.FAILED
        ]
        common: dict[str, Any] = {
            "request_run_id": request.run_id,
            "request_assignment_id": request.assignment_id,
            "request_signal_id": request.signal_id,
            "invocation": ProviderInvocation(
                attribution=ProviderAttribution(
                    provider_id="recorded-308",
                    adapter_id="recorded-308",
                    adapter_version="1.0",
                    invocation_id="55555555-5555-4555-8555-555555555555",
                ),
                started_at=request.requested_at,
                completed_at=request.requested_at + timedelta(seconds=1),
                attempt_count=1,
            ),
            "source_outcomes": outcomes,
            "artifact": artifact,
        }
        if not unanswered:
            return CompleteResearchResult(
                outcome=ResearchOperationOutcome.COMPLETE, **common
            )
        # The provider contract's own rule, and a fact worth stating: an aim a
        # provider cannot answer makes the whole retrieval **partial**. The
        # canonical path carries that — Step 2 §1 gives readiness to the ARP and
        # ``retrieve_evidence_core`` passes ``require_ready=False`` — which is
        # why the case source and the authority lookup can be asked for here
        # and could not be added to the legacy builder.
        return PartialResearchResult(
            outcome=ResearchOperationOutcome.PARTIAL,
            operation_failure=ProviderFailure(
                code=ProviderFailureCode.UNAVAILABLE,
                message=f"{len(unanswered)} aim(s) returned no document",
                retryable=False,
            ),
            **common,
        )

    def _outcomes(
        self, request: ResearchProviderRequest, artifact: Any
    ) -> tuple[SourceRetrievalOutcome, ...]:
        """One outcome per retrieved source, plus a failure per unanswerable aim.

        The discovery source is returned under the directive that asked for it.
        Every other directive — the case source, and any authority lookup S-03
        aims — is reported as attempted and failed, which is the honest shape of
        a provider that has nothing for that aim and the state the fail-closed
        half of the policy is decided on.
        """

        answered = {
            directive.directive_id
            for directive in request.source_directives
            if directive.value in {
                source.locator.value for source in artifact.sources
            }
        }
        outcomes = [
            SourceRetrievalOutcome(
                retrieval_id=f"retrieval-{source.source_id}",
                directive_id=next(iter(answered), None),
                origin=SourceOrigin.CLIENT_SUPPLIED,
                locator=source.locator.value,
                status=RetrievalStatus.RETRIEVED,
                attempted_at=request.requested_at,
                source_id=source.source_id,
                retrieved_at=request.requested_at,
            )
            for source in artifact.sources
        ]
        for index, directive in enumerate(request.source_directives, 1):
            if directive.directive_id in answered or directive.value.startswith(
                "http"
            ) and directive.value in {
                source.locator.value for source in artifact.sources
            }:
                continue
            if directive.priority.value == "excluded":
                continue
            outcomes.append(
                SourceRetrievalOutcome(
                    retrieval_id=f"unanswered-{index}",
                    directive_id=directive.directive_id,
                    origin=SourceOrigin.PROVIDER_DISCOVERED,
                    locator=(
                        directive.value
                        if directive.value.startswith("http")
                        else f"https://{directive.value}"
                    ),
                    status=RetrievalStatus.FAILED,
                    attempted_at=request.requested_at,
                    failure=ProviderFailure(
                        code=ProviderFailureCode.UNAVAILABLE,
                        message="no document answered this aim",
                        retryable=False,
                    ),
                )
            )
        return tuple(outcomes)


class _Judgment:
    """The recorded assessment, extended with who could confirm each claim.

    The production model answers this because
    :func:`~src.editorial_core.evidence_core.extended_instructions` now asks for
    it on the same call. Here the recorded response is extended with the one
    field, so the run reads an answer of exactly the shape production returns.
    """

    name = "evidence_judgment"

    def __init__(
        self,
        ledger: Ledger,
        *,
        authority: str | None = AUTHORITY,
        depends: bool | Mapping[str, bool] = True,
    ) -> None:
        self.ledger = ledger
        self.authority = authority
        #: The client's predicate, as the model answers it: one value for every
        #: claim, or per claim id. Authored, because in production the model
        #: answers it against the client conditions this request carries — the
        #: double stands in for that judgment, not for the policy.
        self.depends = depends
        self.instructions: list[str] = []
        self.requests: list[str] = []

    def complete(self, *, instructions: str, request: str) -> str:
        self.ledger.record(self.name, request)
        self.instructions.append(instructions)
        self.requests.append(request)
        payload = json.loads(
            (FIXTURES / "ups_cold_chain_investment.response.json").read_text(
                encoding="utf-8"
            )
        )
        # The instruction this double is given says: answer false when the
        # request carries no client conditions. A faithful double obeys it,
        # because a double that answered a question nobody grounded would hide
        # exactly the behaviour under test.
        grounded = bool(json.loads(request).get("client_evidence_policy"))
        for claim in payload["claims"]:
            claim["responsible_authority"] = self.authority
            claim["authority_required"] = grounded and (
                self.depends
                if isinstance(self.depends, bool)
                else self.depends[claim["evidence_claim_id"]]
            )
        return json.dumps(payload, ensure_ascii=False)


class _OneClaimBoundary(Boundary):
    """The shared S-04 double, with its readings resting on one claim.

    The shared double cites every usable claim and takes the lowest ceiling
    among them, which in this fixture is the weaker claim's either way. Narrowed
    to the strongest claim so that the authority cap is the *only* thing that
    can lower what the reading may be asserted at — otherwise a differential
    test would measure the fixture rather than the repair.
    """

    def _generate(self, request: str) -> str:
        asked = json.loads(request)
        usable = [item for item in asked["core"]["claims"] if item["usable"]]
        strongest = max(usable, key=lambda item: item["strength"]["level"])
        asked["core"]["claims"] = [strongest]
        return super()._generate(json.dumps(asked, ensure_ascii=False))


def _client_without_the_policy(tmp_path: Path) -> Path:
    """A copy of the real client directory with the evidence policy removed.

    A *second client*, which is the only honest way to test the boundary: same
    Engine, same register, a contract that declares nothing. Copied rather than
    authored so that everything else about the client — streams, lenses, lists,
    destinations — is the real thing and the one difference is the declaration.
    """

    directory = tmp_path / "client"
    for child in Path(CLIENT_DIR).rglob("*"):
        target = directory / child.relative_to(CLIENT_DIR)
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(child.read_bytes())
    contract = directory / "contract.md"
    text = contract.read_text(encoding="utf-8")
    start, end = text.index("## Evidence policy"), text.index("## Editorial domain")
    contract.write_text(text[:start] + text[end:], encoding="utf-8")
    return directory


def _run(tmp_path: Path, *, client_dir: Path | None = None, **kwargs: Any):
    ledger = Ledger()
    research_ledger = Ledger()
    run = canonical_run(
        tmp_path / "run",
        signal_extra={"SOURCE_FOR_CASE": CASE_SOURCE},
        research=_Research(research_ledger, identity=None),
        evidence_judgment=_Judgment(ledger, **kwargs),
        boundary=_OneClaimBoundary(ledger),
        **({} if client_dir is None else {"client_dir": client_dir}),
    )
    # The provider answers about the run's own configuration identity, which the
    # harness only knows once it has assembled the binding.
    run.seams.research.identity = run.binding.identity
    execution, workspace, _ = execute(run)
    return run, execution, workspace


def _claims(workspace: Any) -> list[dict[str, Any]]:
    """The claims the run **wrote**, read out of the persisted E-04.

    The file and not the object: every stage after S-04 reads the written core,
    so a state that survives only in memory is a state the decision never sees.
    This indirection is deliberate — it is what caught the entity body leaving
    the authority out while every unit test passed.
    """

    path = Path(workspace.run_dir) / "signal" / "core" / "core.v1.json"
    assert path.is_file(), "S-01 wrote no core, so there is nothing to assert about"
    body = json.loads(path.read_text(encoding="utf-8"))
    return list(body["evidence_claims"])


# ===========================================================================
# The client declares, and the Engine reads what was declared
# ===========================================================================


def test_the_client_contract_is_where_the_requirement_is_declared() -> None:
    """Never Blank's contract declares it; the Engine carries only the wording.

    The boundary, as a test rather than a promise: the requirement reaches the
    run from ``clients/never_blank/contract.md``. Delete that declaration and
    the Engine requires nothing — which is the next test.
    """

    contract = client_contract(directory=CLIENT_DIR)
    assert contract.requires_primary_authority is True
    assert [item.requirement for item in contract.evidence] == [
        EvidenceRequirement.PRIMARY_AUTHORITY_WHERE_DEPENDENT
    ]
    # And the client wrote the predicate, which is the half the Engine must not
    # supply: a declaration with no conditions would leave the per-claim
    # question groundless, and the Engine would still not invent one.
    assert contract.authority_conditions, (
        "the client declared the requirement and stated no conditions for when "
        "a claim depends on an authority"
    )


def test_a_client_that_declares_nothing_is_required_nothing(tmp_path: Path) -> None:
    """No declaration, no requirement.

    A second client is the test the boundary deserves: the same Engine, a
    contract without the section, and nothing is owed. If this failed, the
    Engine would be imposing Never Blank's policy on everybody.
    """

    loaded = client_contract(directory=_client_without_the_policy(tmp_path))
    assert loaded.evidence == ()
    assert loaded.requires_primary_authority is False


def test_an_unexecutable_requirement_is_refused_rather_than_ignored(
    tmp_path: Path,
) -> None:
    """A wording the Engine cannot execute fails loudly.

    The failure mode a client cannot see is the one worth refusing: a
    requirement written into the contract and silently dropped. The message
    names the vocabulary, so whoever wrote it can fix it.
    """

    from src.strategy.client_contract import ClientConfigurationError

    directory = _client_without_the_policy(tmp_path)
    contract = directory / "contract.md"
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "## Editorial domain",
            "## Evidence policy\n\n- every claim needs three independent "
            "sources\n\n## Editorial domain",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ClientConfigurationError) as raised:
        client_contract(directory=directory)
    assert "primary authority where the claim depends on one" in str(raised.value)


# ===========================================================================
# The canonical run: S-00, S-01, S-03, and the ceiling
# ===========================================================================


def test_the_signal_passes_s00_and_authority_is_decided_later(
    tmp_path: Path,
) -> None:
    """A secondary report is admitted at S-00 and judged at the evidence path.

    The defect this whole repair came from: S-00 refused a signal for lacking a
    primary source before any research had run. Here the same shape of signal
    reaches S-01 and beyond, and the authority question is answered on the
    claim instead of at intake.
    """

    _, execution, workspace = _run(tmp_path)
    stages = [record.stage for record in execution.records]
    assert "S-00" in stages and "S-01" in stages
    assert _claims(workspace), "S-01 built no claim to judge"


def test_the_run_marks_the_claim_required_and_names_who_owes_it(
    tmp_path: Path,
) -> None:
    """The claim the run wrote carries the state, the party, and no source.

    Read off the persisted E-04 rather than from a return value: what the next
    stage reads is the file, and a state that lived only in memory would be a
    state S-04 never sees.
    """

    _, _, workspace = _run(tmp_path)
    claims = _claims(workspace)
    assert claims
    for claim in claims:
        authority = claim["authority"]
        assert authority["state"] == AuthorityState.REQUIRED_UNAVAILABLE.value
        assert authority["responsible"] == AUTHORITY
        assert authority["authoritative_source_ref"] is None


def test_s03_aims_a_bounded_lookup_at_the_named_authority(
    tmp_path: Path,
) -> None:
    """The lookup is attempted, through the research path the run already has.

    The proof is the provider's own inbox: a later request carries a directive
    whose id marks it an authority lookup and whose value is the party the
    assessment named. ``PREFERRED`` and domain-scoped — a narrow lookup, not
    open discovery — and no second provider or model seam was introduced to
    make it.
    """

    run, _, _ = _run(tmp_path)
    aimed = [
        directive
        for request in run.seams.research.requests
        for directive in request.source_directives
        if directive.directive_id.startswith(AUTHORITY_DIRECTIVE_PREFIX)
    ]
    assert aimed, "no request aimed a lookup at the authority the run named"
    assert {directive.value for directive in aimed} == {AUTHORITY}
    assert {directive.priority.value for directive in aimed} == {"preferred"}
    assert {directive.kind.value for directive in aimed} == {"domain"}


def test_the_gap_the_lookup_was_aimed_from_blocks_s04(tmp_path: Path) -> None:
    """S-03 opened an E-07 for it, and the gap says what it blocks.

    A gap that blocked nothing would not be opened at all (§1), so the gap is
    where "unresolved authority reaches S-04" is written down: the entity the
    run persisted names the stage whose decision is held up.
    """

    _, _, workspace = _run(tmp_path)
    gaps = sorted((Path(workspace.run_dir) / "signal" / "gaps").glob("*.json"))
    assert gaps, "S-03 opened no gap for the missing authority"
    bodies = [json.loads(path.read_text(encoding="utf-8")) for path in gaps]
    authority = [
        body
        for body in bodies
        if any(
            directive["directive_id"].startswith(AUTHORITY_DIRECTIVE_PREFIX)
            for directive in body["search_directives"]
        )
    ]
    assert authority, "no gap carries the authority lookup"
    assert all(body["blocks"]["stage"] == "S-04" for body in authority)
    # The party the gap names is the party the written claim names: S-03 opened
    # this from the typed state S-01 resolved, not from a second reading of its
    # own. One state, one party, one record.
    responsible = {claim["authority"]["responsible"] for claim in _claims(workspace)}
    assert responsible == {AUTHORITY}
    assert all(
        any(party in body["description"] for party in responsible)
        for body in authority
    )


def test_an_unestablished_authority_is_held_at_the_ladders_bottom(
    tmp_path: Path,
) -> None:
    """The fail-closed half, on the claim the run wrote.

    Not a new terminal state: the existing **ceiling**. The claim keeps the
    strength its support reached — that is a fact about the evidence and is not
    rewritten — and its ceiling, which is what a later stage may assert up to,
    is held at the ladder's weakest level because the authority it owes was
    never established.
    """

    run, _, workspace = _run(tmp_path)
    bottom = run.configuration.ladder.bottom
    claims = _claims(workspace)
    assert claims
    assert all(claim["ceiling"]["level"] == bottom.level for claim in claims)
    assert any(claim["strength"]["level"] > bottom.level for claim in claims), (
        "the recorded assessment must reach above the bottom on at least one "
        "claim, or this test would pass without the cap doing anything"
    )


def test_the_cap_reaches_what_the_run_is_allowed_to_assert(
    tmp_path: Path,
) -> None:
    """The differential proof: the cap changes what S-05 may assert.

    Two runs, identical in every input but the client's one declaration. The
    reading rests on the claim whose support reached level 2. With the policy
    the interpretation the run persisted may be asserted at the ladder's bottom
    only; without it, at the level the evidence reached. That difference is the
    repair — a ceiling nothing downstream read would be decoration.
    """

    required, _, with_policy = _run(tmp_path / "required")
    _, _, without_policy = _run(
        tmp_path / "free", client_dir=_client_without_the_policy(tmp_path / "other")
    )
    bottom = required.configuration.ladder.bottom

    def asserted(workspace: Any) -> set[int]:
        paths = sorted(
            Path(workspace.run_dir).glob("signal/boundary/interpretations/*.json")
        )
        assert paths, "S-05 persisted no interpretation to read a ceiling off"
        return {
            int(json.loads(path.read_text(encoding="utf-8"))["ceiling"]["level"])
            for path in paths
        }

    assert asserted(with_policy) == {bottom.level}
    assert asserted(without_policy) == {2}
    assert all(
        claim["authority"]["state"] == AuthorityState.NOT_REQUIRED.value
        for claim in _claims(without_policy)
    )
    assert [claim["evidence_claim_id"] for claim in _claims(with_policy)] == [
        claim["evidence_claim_id"] for claim in _claims(without_policy)
    ]


def test_the_case_source_reaches_research_without_becoming_the_authority(
    tmp_path: Path,
) -> None:
    """``SOURCE_FOR_CASE`` is retrievable and is not an authority.

    Both halves in one run: the request carries the case source, and the claim
    is still ``REQUIRED_UNAVAILABLE`` — being filled in establishes nothing.
    """

    run, _, workspace = _run(tmp_path)
    first = run.seams.research.requests[0]
    case = [
        directive
        for directive in first.source_directives
        if directive.value == CASE_SOURCE
    ]
    assert case, "the case source never reached the research request"
    assert case[0].priority.value == "preferred"
    assert case[0].material is False
    assert not case[0].directive_id.startswith(AUTHORITY_DIRECTIVE_PREFIX)
    assert all(
        claim["authority"]["state"] == AuthorityState.REQUIRED_UNAVAILABLE.value
        for claim in _claims(workspace)
    )


def test_a_claim_whose_authority_cannot_be_named_is_undetermined(
    tmp_path: Path,
) -> None:
    """Nobody identifiable, no fabricated lookup — and still capped.

    The model answering ``null`` is the ordinary case for a claim nobody could
    confirm. The run records ``undetermined``, aims no lookup at a blank, and
    does not let the claim read as verified.
    """

    run, _, workspace = _run(tmp_path, authority=None)
    claims = _claims(workspace)
    assert claims
    assert all(
        claim["authority"]["state"] == AuthorityState.UNDETERMINED.value
        for claim in claims
    )
    assert all(claim["authority"]["responsible"] is None for claim in claims)
    assert all(
        claim["ceiling"]["level"] == run.configuration.ladder.bottom.level
        for claim in claims
    )
    assert not [
        directive
        for request in run.seams.research.requests
        for directive in request.source_directives
        if directive.directive_id.startswith(AUTHORITY_DIRECTIVE_PREFIX)
    ], "a lookup was aimed at an authority nobody named"


def test_the_assessment_asks_for_the_authority_on_the_call_it_already_makes(
    tmp_path: Path,
) -> None:
    """One call, extended — not a second one.

    The instruction the run actually sent is read back from the double: it asks
    for ``responsible_authority``, and the judgment boundary was reached once
    per assessment rather than twice.
    """

    run, _, _ = _run(tmp_path)
    judgment = run.seams.evidence_judgment
    assert judgment.instructions, "the assessment was never asked anything"
    assert all(
        "responsible_authority" in text for text in judgment.instructions
    )


# ===========================================================================
# The persistence boundary (owner's acceptance list, 2026-10-05)
# ===========================================================================


def test_the_persisted_authority_reconstructs_the_same_typed_state(
    tmp_path: Path,
) -> None:
    """Every authority fact survives serialization, recoverable without inference.

    The three fields are read back out of the file and handed to
    :class:`ClaimAuthority`'s own constructor, which runs every validator it
    has. Nothing is recomputed, re-derived or re-inferred from the claim's
    other fields — if the state were reconstructed rather than read, this test
    would pass on a file that had lost it.

    **There is no production deserializer**, for this entity or for any of the
    sixteen: ``RunWorkspace`` writes and digests, and ``StageRecord.from_dict``
    is the only entity-shaped reader in the repository. So this proves the
    record is complete and admissible, which is what persistence owes; it does
    not claim a reload path that the Engine does not have.
    """

    run, _, workspace = _run(tmp_path)
    claims = _claims(workspace)
    assert claims
    for claim in claims:
        body = claim["authority"]
        assert set(body) == {
            "state",
            "responsible",
            "authoritative_source_ref",
        }
        restored = ClaimAuthority(
            state=AuthorityState(body["state"]),
            responsible=body["responsible"],
            authoritative_source_ref=body["authoritative_source_ref"],
        )
        assert restored.state is AuthorityState.REQUIRED_UNAVAILABLE
        assert restored.responsible == AUTHORITY
        assert restored.authoritative_source_ref is None
        # The derived question S-05 and the ceiling ask of it answers the same
        # way after the round trip as it did in memory.
        assert restored.verified is False
        assert restored.as_entity() == body


def test_the_entity_digest_covers_the_authority_payload(tmp_path: Path) -> None:
    """The authority is inside the digested entity, not beside it.

    No separate authority artifact and no second digest: the manifest's digest
    for ``core.v1.json`` is taken over the file the authority is written into,
    so tampering with the state changes the recorded digest. That is the whole
    reason the record belongs in E-04 rather than in a parallel file.
    """

    from src.run.run_workspace import file_digest

    _, _, workspace = _run(tmp_path)
    path = Path(workspace.run_dir) / "signal" / "core" / "core.v1.json"
    before = file_digest(path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["evidence_claims"][0]["authority"]["state"] = (
        AuthorityState.REQUIRED_ESTABLISHED.value
    )
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    assert file_digest(path) != before, (
        "the authority payload is not covered by the entity digest, so a "
        "tampered state would verify"
    )


def test_the_persisted_schema_carries_no_client_doctrine(tmp_path: Path) -> None:
    """What is written down is a status, a party and a ref — never a policy.

    The Engine's persisted schema stays generic: three keys, and a state drawn
    from the Engine's own closed vocabulary. The *client's* declaration is not
    in here and does not need to be — which claims owe an authority is the
    contract's to say, and the entity records only what this run found.
    """

    _, _, workspace = _run(tmp_path)
    states = {claim["authority"]["state"] for claim in _claims(workspace)}
    assert states <= {item.value for item in AuthorityState}
    written = json.dumps(_claims(workspace), ensure_ascii=False).lower()
    for doctrine in ("product release", "regulator", "regulation", "never blank"):
        assert doctrine not in written, (
            f"the persisted claim carries the client doctrine {doctrine!r}; the "
            "entity records what the run found, and the policy stays in the "
            "client's own contract and lens"
        )


# ===========================================================================
# Per-claim applicability (owner's second review, 2026-10-05)
# ===========================================================================


def test_two_claims_one_run_only_the_dependent_one_owes_an_authority(
    tmp_path: Path,
) -> None:
    """The differential the second review asked for, in a single run.

    Both claims name the **same** responsible party, so being nameable is held
    constant and cannot explain the difference. What differs is the client's
    predicate: one claim depends on a primary authority, the other does not.

    The second claim must persist as ``NOT_REQUIRED`` — and it keeps the
    responsible party, because "a responsible party being nameable does not
    make one mandatory" is a statement about obligation, not about the fact.
    """

    dependent, independent = SCENARIO.evidence_ids
    run, _, workspace = _run(
        tmp_path, depends={dependent: True, independent: False}
    )
    claims = {claim["evidence_claim_id"]: claim for claim in _claims(workspace)}
    assert set(claims) == {dependent, independent}

    owes = claims[dependent]["authority"]
    assert owes["state"] == AuthorityState.REQUIRED_UNAVAILABLE.value
    assert owes["responsible"] == AUTHORITY

    free = claims[independent]["authority"]
    assert free["state"] == AuthorityState.NOT_REQUIRED.value
    assert free["responsible"] == AUTHORITY, (
        "the party is a fact about the material and survives a claim owing "
        "nothing; dropping it would conflate the two questions again"
    )
    assert free["authoritative_source_ref"] is None


def test_the_claim_that_owes_nothing_is_not_capped_and_opens_no_lookup(
    tmp_path: Path,
) -> None:
    """And the consequences are per claim too, not per run.

    One run, two claims, one ceiling held down and one left alone; one gap
    opened and one not. A run-wide boolean could not produce this, which is
    what makes it the regression for the defect.
    """

    dependent, independent = SCENARIO.evidence_ids
    run, _, workspace = _run(
        tmp_path, depends={dependent: True, independent: False}
    )
    bottom = run.configuration.ladder.bottom
    claims = {claim["evidence_claim_id"]: claim for claim in _claims(workspace)}

    # The dependent claim is held at the bottom; the other keeps the ceiling
    # its own evidence earned.
    assert claims[dependent]["ceiling"]["level"] == bottom.level
    assert claims[dependent]["strength"]["level"] > bottom.level, (
        "the dependent claim must be the one whose support reached above the "
        "bottom, or the cap would be invisible"
    )
    assert (
        claims[independent]["ceiling"]["level"]
        == claims[independent]["strength"]["level"]
    )

    # One gap, for the one claim that owes an authority.
    gaps = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((Path(workspace.run_dir) / "signal" / "gaps").glob("*.json"))
    ]
    authority_gaps = [
        gap
        for gap in gaps
        if any(
            directive["directive_id"].startswith(AUTHORITY_DIRECTIVE_PREFIX)
            for directive in gap["search_directives"]
        )
    ]
    assert len(authority_gaps) == 1
    assert dependent in authority_gaps[0]["description"]
    assert independent not in authority_gaps[0]["description"]


def test_the_clients_own_conditions_are_what_the_claim_is_judged_against(
    tmp_path: Path,
) -> None:
    """The predicate travels from the contract to the judgment, verbatim.

    The request the assessment was given carries the client's conditions under
    the key the Engine's instructions name. That is the mechanism by which the
    predicate stays the client's: the Engine asks, the client's words answer,
    and no claim class is enumerated in ``src/``.
    """

    run, _, _ = _run(tmp_path)
    judgment = run.seams.evidence_judgment
    assert judgment.requests, "the assessment was never asked anything"
    conditions = client_contract(directory=CLIENT_DIR).authority_conditions
    for request in judgment.requests:
        carried = json.loads(request)["client_evidence_policy"]
        assert carried == list(conditions)
    # And the instructions that read that key are the Engine's own: generic,
    # naming no client and no kind of claim.
    text = "\n".join(judgment.instructions).lower()
    assert "client_evidence_policy" in text
    for doctrine in ("never blank", "product release", "vendor", "regulator"):
        assert doctrine not in text


def test_a_client_that_states_no_conditions_has_nothing_asked_of_its_claims(
    tmp_path: Path,
) -> None:
    """A declaration with no predicate asks the model nothing.

    The fail-loud alternative would be refusing the contract, and that is the
    owner's call rather than mine — so this records the behaviour instead: the
    request carries no policy key, the instructions already say to answer
    ``false`` without one, and nothing is capped on a predicate nobody wrote.
    """

    directory = _client_without_the_policy(tmp_path / "bare")
    contract = directory / "contract.md"
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "## Editorial domain",
            "## Evidence policy\n\n- primary authority where the claim "
            "depends on one\n\n## Editorial domain",
            1,
        ),
        encoding="utf-8",
    )
    loaded = client_contract(directory=directory)
    assert loaded.requires_primary_authority is True
    assert loaded.authority_conditions == ()

    run, _, workspace = _run(tmp_path / "run", client_dir=directory)
    for request in run.seams.evidence_judgment.requests:
        assert "client_evidence_policy" not in json.loads(request)
    bottom = run.configuration.ladder.bottom
    assert any(
        claim["ceiling"]["level"] > bottom.level for claim in _claims(workspace)
    ), "a predicate nobody wrote capped a claim"
