"""Primary authority is an evidence responsibility, not an S-00 gate (#308/#286).

Owner decision 2026-10-05, after `SOURCE-AUTHORITY-AUDIT-V1` found **D —
contract mismatch**: S-00 was enforcing a source-authority requirement through
a request shape that could not carry one, so any product/feature claim
discovered secondhand was refused before the model read anything, on any model.

The repair moves enforcement to the stage that can actually go and look, and
keeps the requirement itself untouched.

**The Engine/Client boundary is the thing these tests guard hardest.** The
Engine may know the *concept* — four authority statuses, the transition, the
lineage, the bounded lookup, the strength cap. It must not know the *doctrine*:
which kinds of claim owe an authority is editorial policy and lives in a client
contract. A test below greps the Engine module for that doctrine.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from src.editorial_core.evidence_core import (
    AUTHORITY_DIRECTIVE_PREFIX,
    AuthorityPolicy,
    AuthorityState,
    ClaimAssessment,
    ClaimAuthority,
    EvidenceCoreError,
    resolve_claim_authority,
)
from src.research.lifecycle import (
    authority_directives,
    build_source_directives,
    case_source_directives,
)
from src.research.provider import SourceDirectiveKind, SourcePriority

QUEUE = pathlib.Path("data/research/signals_active.jsonl")
SHOPIFY = "6a72b2abcc466aab"
ZINGERMAN = "7965169a1ae121c5"


def _signal(signal_id: str) -> dict:
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line).get("SIGNAL_ID") == signal_id:
            return json.loads(line)
    raise AssertionError(f"{signal_id} is not in the queue")


#: A client that declared the mechanism and wrote one condition. Authored here
#: because it is the *client's* value: these unit tests exercise the Engine's
#: transition, and the predicate they stand in for is NB's own in its contract.
POLICY = AuthorityPolicy(
    declared=True,
    conditions=("The claim states what a company announced about itself.",),
)


def _assessment(*, depends: bool = True, **kwargs) -> ClaimAssessment:
    """One claim's assessment. ``depends`` is the client's predicate, applied.

    Defaulted to ``True`` so that each test below reads as being about the
    transition it names. The case where a party is nameable and the claim does
    **not** depend on one has its own test, because that distinction is the
    whole of #387's second review.
    """

    return ClaimAssessment(
        evidence_claim_id="c1",
        scope="small business",
        strength_level=3,
        authority_required=depends,
        **kwargs,
    )


# ===========================================================================
# 1–2 · S-00 stops asking, and discovery provenance is untouched
# ===========================================================================


def test_s00_no_longer_judges_source_authority():
    """Regression 1: the lens left `selection`.

    S-00's own contract says it *"decides fit and relevance only"*, and the
    contract loader states why this could never have worked there: `selection`
    *"chooses the candidate before any research is done"*.
    """

    from src.editorial.editorial_role import resolve_editorial_role
    from src.strategy.business_config import load_business_strategy_configuration
    from src.strategy.client_contracts import load_lens

    lens = load_lens(pathlib.Path("clients/never_blank/lenses/evidence.md"))
    assert lens.stages == ("writing",), lens.stages

    _, role = resolve_editorial_role(
        load_business_strategy_configuration(), "never-blank-monday-documented-case"
    )
    criteria = " ".join(str(item).lower() for item in role.eligibility_criteria)
    assert "source integrity" not in criteria
    assert "primary authority" not in criteria
    # And the requirement itself is not weakened — it still exists, at writing.
    text = pathlib.Path("clients/never_blank/lenses/evidence.md").read_text()
    assert "responsible primary authority" in text
    assert "does not replace the authoritative source" in text


def test_discovery_provenance_is_unchanged_for_the_shopify_signal():
    """Regression 2: SEJ remains the discovery source, as a required one."""

    directives = build_source_directives(_signal(SHOPIFY))
    required = [d for d in directives if d.priority is SourcePriority.REQUIRED]
    assert len(required) == 1
    assert "searchenginejournal.com" in required[0].value
    assert required[0].material is True
    # Nothing was added that pretends to be Shopify's own source.
    assert all("shopify.com" not in d.value for d in directives)


# ===========================================================================
# 3–5 · the authority is identified, linked, or fails closed
# ===========================================================================


def test_the_responsible_authority_is_identified_without_fabricating_a_url():
    """Regression 3: a name produces a bounded lookup; no name produces none."""

    (directive,) = authority_directives(["shopify.com"])
    assert directive.directive_id.startswith(AUTHORITY_DIRECTIVE_PREFIX)
    assert directive.kind is SourceDirectiveKind.DOMAIN
    assert directive.priority is SourcePriority.PREFERRED
    assert directive.value == "shopify.com"

    # Nothing identified → nothing invented.
    assert authority_directives([]) == ()
    assert authority_directives(["", "   "]) == ()

    state = resolve_claim_authority(
        _assessment(), source_refs=("s-sej",), authoritative_source_ids=(),
        policy=POLICY,
    )
    assert state.state is AuthorityState.UNDETERMINED
    assert state.responsible is None
    assert state.authoritative_source_ref is None


def test_an_established_authority_is_linked_separately_from_discovery():
    """Regression 4: two different facts, two different fields."""

    authority = resolve_claim_authority(
        _assessment(responsible_authority="shopify.com"),
        source_refs=("s-sej", "s-shopify"),
        authoritative_source_ids={"s-shopify"},
        policy=POLICY,
    )

    assert authority.state is AuthorityState.REQUIRED_ESTABLISHED
    assert authority.responsible == "shopify.com"
    assert authority.authoritative_source_ref == "s-shopify"
    # The discovery source is still an evidence source of the claim, and is not
    # the authority — the claim keeps both, distinguishably.
    assert authority.authoritative_source_ref != "s-sej"
    assert authority.verified is True


def test_an_unestablished_authority_fails_closed_through_the_existing_ceiling():
    """Regression 5: the cap is the ladder, not a new terminal state."""

    from src.editorial_core.evidence_core import StrengthLadder, _claim_ceiling

    ladder = StrengthLadder("nb-ladder", ("may", "appears to", "does"))
    evidence_strength = ladder.at(3)

    for state in (
        AuthorityState.REQUIRED_UNAVAILABLE,
        AuthorityState.UNDETERMINED,
    ):
        authority = ClaimAuthority(
            state,
            responsible=(
                "shopify.com"
                if state is AuthorityState.REQUIRED_UNAVAILABLE
                else None
            ),
        )
        capped = _claim_ceiling(
            evidence_strength, client_ceiling=None, ladder=ladder, authority=authority
        )
        assert capped == ladder.bottom, state
        assert authority.verified is False

    # And a claim that owes nothing, or whose authority was established, is
    # untouched by this rule.
    for authority in (
        ClaimAuthority(AuthorityState.NOT_REQUIRED),
        ClaimAuthority(
            AuthorityState.REQUIRED_ESTABLISHED,
            responsible="shopify.com",
            authoritative_source_ref="s-shopify",
        ),
    ):
        assert _claim_ceiling(
            evidence_strength, client_ceiling=None, ladder=ladder, authority=authority
        ) == evidence_strength


def test_the_unavailable_state_still_requires_a_named_party():
    """"Required but unavailable" means known-who, unknown-where.

    A claim that cannot name the party is `UNDETERMINED`, so the two states
    stay distinguishable instead of collapsing into "something went wrong".
    """

    with pytest.raises(EvidenceCoreError, match="UNDETERMINED"):
        ClaimAuthority(AuthorityState.REQUIRED_UNAVAILABLE)

    with pytest.raises(EvidenceCoreError, match="only an established"):
        ClaimAuthority(
            AuthorityState.UNDETERMINED, authoritative_source_ref="s-shopify"
        )


# ===========================================================================
# 6 · Zingerman's: reachable, and not promoted
# ===========================================================================


def test_the_case_source_reaches_the_evidence_path_without_being_authoritative():
    """Regression 6: visible, and not labelled.

    `SOURCE_FOR_CASE` for this signal is `zingtrain.com` — genuinely the
    company's own site. The audit found it was withheld from the judge
    entirely. It is now offered to retrieval at PREFERRED, and it is still not
    an authority until an authority lookup establishes one.
    """

    case = case_source_directives(_signal(ZINGERMAN))
    assert len(case) == 1
    assert "zingtrain.com" in case[0].value
    assert case[0].priority is SourcePriority.PREFERRED
    assert case[0].material is False
    assert not case[0].directive_id.startswith(AUTHORITY_DIRECTIVE_PREFIX)

    # Present-and-non-empty establishes nothing by itself.
    assert resolve_claim_authority(
        _assessment(responsible_authority="zingermans.com"),
        source_refs=("s-entrepreneur", "s-zingtrain"),
        authoritative_source_ids=(),
        policy=POLICY,
    ).state is AuthorityState.REQUIRED_UNAVAILABLE


def test_a_case_source_equal_to_the_discovery_url_adds_no_directive():
    """For the two secondhand signals it is the discovery URL repeated.

    A string comparison against the discovery URL would have been the obvious
    way to classify "primary", and it would have promoted a duplicate.
    """

    assert case_source_directives(_signal(SHOPIFY)) == ()
    # And the shared builder every existing caller uses is untouched, so no
    # legacy run's outcome classification changed.
    assert [d.directive_id for d in build_source_directives(_signal(SHOPIFY))] == [
        "required-source-1"
    ]


# ===========================================================================
# 7–8 · the distinctions that must not collapse
# ===========================================================================


def test_third_party_assertion_stays_distinct_from_authority_status():
    """Regression 7: one is a property of an observation, one of a claim."""

    from src.editorial_core.evidence_core import EvidenceClaim, ObservationAssessment

    observation = ObservationAssessment(
        observation_id="o1", kind="quote", is_third_party_assertion=True
    )
    assert observation.is_third_party_assertion is True

    fields = {f.name for f in __import__("dataclasses").fields(EvidenceClaim)}
    assert "authority" in fields
    assert "is_third_party_assertion" not in fields

    # Neither derives from the other: a third-party observation says nothing
    # about whether an authority was established, and vice versa.
    source = ast.parse(pathlib.Path("src/editorial_core/evidence_core.py").read_text())
    body = ast.unparse(
        next(
            node for node in ast.walk(source)
            if isinstance(node, ast.FunctionDef)
            and node.name == "resolve_claim_authority"
        )
    )
    assert "is_third_party_assertion" not in body


def test_no_additional_model_or_provider_call_is_introduced():
    """Regression 8: the two authority facts ride the call that already runs."""

    # Both authority fields are on the claim assessment, which means they ride
    # the one extended call S-01 already makes rather than a call of their own.
    assert "authority_required" in ClaimAssessment.model_fields
    assert "responsible_authority" in ClaimAssessment.model_fields

    from src.editorial_core.evidence_core import extended_instructions

    import inspect

    assert inspect.signature(extended_instructions).parameters == {}
    # Nothing in the authority path calls a transport.
    text = pathlib.Path("src/editorial_core/evidence_core.py").read_text()
    for function in ("resolve_claim_authority", "_claim_ceiling"):
        start = text.index(f"def {function}(")
        chunk = text[start : text.index("\ndef ", start + 1)]
        for forbidden in ("complete(", "chat(", "transport"):
            assert forbidden not in chunk, f"{function}: {forbidden}"


# ===========================================================================
# The Engine / Client boundary
# ===========================================================================


def test_the_engine_holds_the_concept_and_not_the_editorial_doctrine():
    """The boundary the owner said she would check the diff for.

    The Engine may know that an authority can be required, established or not.
    It must not know *which kinds of claim* require one — that enumeration is
    editorial policy and belongs in a client contract. So the Engine takes
    the policy as an input it is given — including, after #387's second review,
    the per-claim predicate — and the only mention of the doctrine in the
    module is the sentence forbidding it.
    """

    import inspect

    from src.editorial_core import evidence_core

    # The policy is an argument, never a decision taken here.
    assert (
        "policy"
        in inspect.signature(evidence_core.resolve_claim_authority).parameters
    )
    assert (
        inspect.signature(evidence_core.build_evidence_core)
        .parameters["policy"]
        .default
        == evidence_core.AuthorityPolicy()
    ), "no client asked by default, so nothing is owed and nothing is capped"
    assert evidence_core.AuthorityPolicy().declared is False
    assert evidence_core.AuthorityPolicy().conditions == ()

    # Executable code carries no client doctrine: comments and docstrings are
    # stripped, so the sentence that *forbids* the doctrine is not read as it.
    tree = ast.parse(inspect.getsource(evidence_core))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body.pop(0)
    code = ast.unparse(tree).lower()
    for doctrine in ("product release", "regulator", "vendor", "never blank", "shopify"):
        assert doctrine not in code, doctrine


def test_no_engine_module_in_the_authority_path_names_a_client_rule():
    """The same check over every Engine module this repair touched.

    One module staying clean is not the boundary; the path is. The client's
    requirement reaches the Engine as a **closed vocabulary of mechanisms** and
    a boolean, so none of these modules has any reason to name a kind of claim,
    an industry or a client — and the test says so for all of them rather than
    for the one that happened to be reviewed.
    """

    import inspect

    from src.editorial_core import enrichment, evidence_core
    from src.research import lifecycle
    from src.run import golden_engine
    from src.strategy import client_contract

    for module in (
        evidence_core,
        enrichment,
        lifecycle,
        golden_engine,
        client_contract,
    ):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body.pop(0)
        code = ast.unparse(tree).lower()
        for doctrine in ("product release", "regulator", "vendor", "shopify"):
            assert doctrine not in code, f"{module.__name__}: {doctrine}"


def test_the_client_lens_still_owns_when_an_authority_is_required():
    """And the doctrine is where it belongs, unchanged."""

    lens = pathlib.Path("clients/never_blank/lenses/evidence.md").read_text()
    # Line-wrapped in the document, so the assertion is on the wording and not
    # on the line breaks.
    assert "vendor or company's official source for a" in lens
    assert "product release or feature" in lens
    assert "official government or regulatory source" in lens
