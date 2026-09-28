"""Issue #361: real implementations under the thirteen stage contracts.

SL-6.4's acceptance evidence. ``src/editorial_core/`` declares ten model-call
transports as ``Protocol``s and implements none of them; this suite is the
proof that the production layer beneath them is a layer and not a fixture:

1. **every Protocol has a production class with that Protocol's signature**,
   and the one construction point is annotated with the core's own Protocol
   types, so a signature that drifted stops the static check too;
2. **exactly one class performs the provider call** — patching it intercepts
   every one of the ten, and the ten share one core object;
3. **every call goes through ``src.utils.llm_client.chat``**, so the #171 run
   budget is charged exactly once per logical call, and no OpenAI client is
   constructed anywhere in the layer;
4. **the two strings are not touched**: ``instructions`` and ``request`` reach
   the client byte-identical, whitespace included;
5. **the ten are ten**, distinct and never one object under two names;
6. **the boundary holds**: the core reaches neither the shared text client nor
   this layer, and this branch changes no stage module;
7. **the model decision is enforced, not documented**:
   ``NB_GOLDEN_ENGINE_MODEL`` is the only source of the model, construction
   raises without it, and the configured value is what reaches ``chat``.

And one smoke, skipped unless explicitly enabled, that sends a real stage
request across the production seam and reads a real answer back. It costs a
paid provider call and is owner-gated; it proves the seam carries a request,
not that the thirteen stages compose.
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.editorial_core.anchor import AnchorTransport
from src.editorial_core.candidate_strategies import StrategyTransport
from src.editorial_core.evidence_core import (
    EvidenceClaim,
    EvidenceCore,
    ObservationKind,
    SourceObservation,
    StrengthLadder,
)
from src.editorial_core.executable_plan import SegmentationTransport
from src.editorial_core.interpretation_boundary import BoundaryTransport
from src.editorial_core.material_features import (
    MaterialDescription,
    MaterialTransport,
    describe_material,
)
from src.editorial_core.plan_check import BarrierTransport, PlanCheckTransport
from src.editorial_core.strategy_selection import RankingTransport
from src.editorial_core.text_check import TextCheckTransport
from src.editorial_core.writer import WriterTransport
from src.research.evidence import (
    EvidenceDisposition,
    EvidenceReadiness,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    SourceLocator,
    SourceLocatorKind,
)
from src.run.call_budget import (
    RunCallBudget,
    RunCallBudgetExceededError,
    activate_call_budget,
)
from src.run.transports import (
    MODEL_VAR,
    GoldenEngineAnchorTransport,
    GoldenEngineBarrierTransport,
    GoldenEngineBoundaryTransport,
    GoldenEngineMaterialTransport,
    GoldenEngineModelConfigurationError,
    GoldenEnginePlanCheckTransport,
    GoldenEngineProvider,
    GoldenEngineRankingTransport,
    GoldenEngineSegmentationTransport,
    GoldenEngineStrategyTransport,
    GoldenEngineTextCheckTransport,
    GoldenEngineTransports,
    GoldenEngineWriterTransport,
    golden_engine_transports,
)
from src.utils import llm_client

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: A model id no provider has. Every test but the smoke stops at a fake
#: client, so the value's only job is to be recognisable where it arrives.
_MODEL = "nb-golden-engine-test-model"

#: The layer, by bundle field, the stage it belongs to, the Protocol it must
#: satisfy and the production class that satisfies it. Ten rows: this table is
#: the slice.
TRANSPORTS: tuple[tuple[str, str, Any, Any], ...] = (
    ("material", "S-02", MaterialTransport, GoldenEngineMaterialTransport),
    ("boundary", "S-04", BoundaryTransport, GoldenEngineBoundaryTransport),
    ("anchor", "S-06", AnchorTransport, GoldenEngineAnchorTransport),
    ("strategy", "S-08", StrategyTransport, GoldenEngineStrategyTransport),
    ("ranking", "S-09", RankingTransport, GoldenEngineRankingTransport),
    ("segmentation", "S-10", SegmentationTransport, GoldenEngineSegmentationTransport),
    ("plan_check", "S-11", PlanCheckTransport, GoldenEnginePlanCheckTransport),
    ("barrier", "S-11", BarrierTransport, GoldenEngineBarrierTransport),
    ("writer", "S-12", WriterTransport, GoldenEngineWriterTransport),
    ("text_check", "S-13", TextCheckTransport, GoldenEngineTextCheckTransport),
)

_ROWS = [row[0] for row in TRANSPORTS]
_ROW_FIELDS = ("field", "stage", "protocol", "production")


# ===========================================================================
# A client that records instead of dispatching
# ===========================================================================


class _Completions:
    """``client.chat.completions``, recording what would have gone out."""

    def __init__(self, sent: list[dict[str, Any]], content: str) -> None:
        self._sent = sent
        self._content = content

    def create(self, **kwargs: Any) -> Any:
        self._sent.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


class _Client:
    """The shape ``llm_client`` uses of the OpenAI client, and no more."""

    def __init__(self, sent: list[dict[str, Any]], content: str) -> None:
        self.chat = SimpleNamespace(completions=_Completions(sent, content))


@pytest.fixture()
def model(monkeypatch):
    """The one configured model, as the owner decision defines configuration."""

    monkeypatch.setenv(MODEL_VAR, _MODEL)
    return _MODEL


@pytest.fixture()
def sent(monkeypatch):
    """Every request the shared client would have dispatched.

    The fake is installed at ``_get_client`` — below ``chat``, not in place of
    it — so the budget charge, the #279 measurement and the message assembly
    are all the real ones. A transport that reached past ``chat`` would leave
    this list empty.
    """

    requests: list[dict[str, Any]] = []
    client = _Client(requests, '{"answered": true}')
    monkeypatch.setattr(llm_client, "_get_client", lambda: client)
    return requests


def _signature(func: Any) -> tuple[tuple[tuple[str, Any, Any], ...], Any]:
    """One callable's shape: parameter names, kinds and annotations.

    ``eval_str`` resolves the annotations on both sides, so the comparison is
    between types rather than between two spellings of ``str``.
    """

    signature = inspect.signature(func, eval_str=True)
    return (
        tuple(
            (item.name, item.kind, item.annotation)
            for item in signature.parameters.values()
        ),
        signature.return_annotation,
    )


def _module_source(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imported_modules(tree: ast.Module) -> set[str]:
    """Every absolute module name this file imports, however it imports it."""

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add(node.module or "")
    return names


def _reaches(imported: set[str], package: str) -> bool:
    """Does any import name that package, or something inside it?

    Compared on dotted boundaries: ``src.editorial_core`` is not
    ``src.editorial``, and a prefix match would read the core as importing
    itself out of bounds.
    """

    return any(
        name == package or name.startswith(package + ".") for name in imported
    )


def _git(*args: str) -> tuple[int, str]:
    done = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), *args], capture_output=True, text=True
    )
    return done.returncode, done.stdout.strip()


# ===========================================================================
# 1. Ten Protocols, ten production implementations
# ===========================================================================


@pytest.mark.parametrize(_ROW_FIELDS, TRANSPORTS, ids=_ROWS)
def test_each_production_class_has_its_protocol_signature(
    field, stage, protocol, production
):
    """The signature, parameter for parameter, keyword-only marker included.

    Structural typing is what makes a production transport interchangeable
    with a test fake, and it is also what makes a drift invisible: a class
    whose ``complete`` took ``instruction`` instead of ``instructions``, or
    took the two positionally, would satisfy nothing and would fail only at
    the first real call. Compared here so it fails at the first test run.
    """

    assert _signature(production.complete) == _signature(protocol.complete)
    assert production.stage == stage


def test_the_construction_point_is_annotated_with_the_core_protocols():
    """The static half of conformance lives on the bundle's fields.

    The ten fields are typed as the core's own Protocols, so the type checker
    checks each production class against the contract its stage declares, at
    the one place they are all constructed. An annotation replaced by ``Any``
    or by the production class itself would keep the rest of this suite green
    and take the static check away, so the annotations are asserted.
    """

    annotations = GoldenEngineTransports.__annotations__

    assert tuple(annotations) == tuple(_ROWS)
    assert tuple(annotations.values()) == tuple(row[2].__name__ for row in TRANSPORTS)


# ===========================================================================
# 2. One call path, not ten
# ===========================================================================


def test_one_class_performs_the_provider_call_for_all_ten(model, monkeypatch):
    """Patching the one core intercepts every named transport.

    This is the test a second provider implementation fails: a named class
    given its own call would not appear here, and the list would be short.
    """

    seen: list[str] = []

    def _record(self, *, instructions: str, request: str) -> str:
        seen.append(instructions)
        return "{}"

    monkeypatch.setattr(GoldenEngineProvider, "complete", _record)
    bundle = golden_engine_transports()

    for field in _ROWS:
        getattr(bundle, field).complete(instructions=field, request="request")

    assert seen == _ROWS


def test_the_ten_bindings_share_one_provider_core(model):
    """One core object per bundle: one model, and one call path per run."""

    bundle = golden_engine_transports()
    cores = [getattr(bundle, field).core for field in _ROWS]

    assert len({id(core) for core in cores}) == 1
    assert isinstance(cores[0], GoldenEngineProvider)


# ===========================================================================
# 3. The budget is inherited, and charged once
# ===========================================================================


@pytest.mark.parametrize(_ROW_FIELDS, TRANSPORTS, ids=_ROWS)
def test_a_call_through_any_transport_charges_the_run_budget_once(
    field, stage, protocol, production, model, sent
):
    """One logical call, counted once against #171's active budget.

    A transport that reached an OpenAI client directly would charge nothing:
    the counter is inside ``chat``, before the provider request, and that is
    the only reason a runaway loop stops. ``used`` is also not two — a second
    charge would halve the run's real ceiling.
    """

    budget = RunCallBudget(limit=5)
    bundle = golden_engine_transports()

    with activate_call_budget(budget):
        answer = getattr(bundle, field).complete(
            instructions="instructions", request="request"
        )

    assert answer == '{"answered": true}'
    assert budget.used == 1
    assert len(sent) == 1


def test_an_exhausted_budget_refuses_the_call_before_the_provider(model, sent):
    """The refusal is the client's, and it happens before anything is sent.

    Inherited rather than implemented: this asserts the transport did not put
    itself in front of the guard, which a layer with its own retry or its own
    provider call would have done.
    """

    budget = RunCallBudget(limit=1)
    bundle = golden_engine_transports()

    with activate_call_budget(budget):
        bundle.writer.complete(instructions="i", request="r")
        with pytest.raises(RunCallBudgetExceededError):
            bundle.writer.complete(instructions="i", request="r")

    assert len(sent) == 1


def test_the_layer_constructs_no_provider_client_of_its_own():
    """Static: nothing in the transport layer names an OpenAI client.

    ``llm_client`` is the only module that may construct one — it is where the
    retry policy (#170), the budget charge (#171) and the routing measurement
    (#279) all live. A transport that imported ``openai`` would inherit none
    of them, and would be counted by nothing.
    """

    layer = sorted(_REPO_ROOT.glob("src/run/transports*.py")) + sorted(
        _REPO_ROOT.glob("src/run/transports/*.py")
    )
    assert layer, "the transport layer was not found under src/run/"

    for path in layer:
        tree = _module_source(path)
        imported = _imported_modules(tree)
        constructed = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

        assert not _reaches(imported, "openai"), f"{path.name} imports the SDK"
        assert "OpenAI" not in constructed, f"{path.name} names an OpenAI client"
        assert "src.utils.llm_client" in imported


# ===========================================================================
# 4. The strings are the stage's, not the transport's
# ===========================================================================


@pytest.mark.parametrize(_ROW_FIELDS, TRANSPORTS, ids=_ROWS)
def test_the_two_strings_reach_the_client_byte_identical(
    field, stage, protocol, production, model, sent
):
    """Whitespace included. A stage owns every character it sends.

    Any trimming, prefixing or template wrapping fails here — and it has to
    fail here, because a stage whose instructions were quietly reworded would
    keep passing every test it has and would decide something else.
    """

    instructions = "  You describe material.\n\n\tAnd nothing else.  \n"
    request = '{"core": "core-361", "claims": ["evidence-1"]}\n\n  '
    bundle = golden_engine_transports()

    with activate_call_budget(RunCallBudget(limit=5)):
        getattr(bundle, field).complete(instructions=instructions, request=request)

    messages = sent[0]["messages"]
    assert messages[0]["content"] == instructions
    assert messages[1]["content"] == request


# ===========================================================================
# 5. Ten names, ten boundaries
# ===========================================================================


def test_the_bundle_hands_each_stage_its_own_named_transport(model):
    """Ten members, ten objects, ten types — none reused under two names.

    The identical signature is not licence to pass one object everywhere:
    ``MaterialTransport`` carries its own name so that a stage which judges no
    evidence can never be handed the judgment boundary, and one object under
    two field names would put that back.
    """

    bundle = golden_engine_transports()
    members = [getattr(bundle, field) for field in _ROWS]

    assert len(members) == 10
    assert len({id(member) for member in members}) == 10
    assert len({type(member) for member in members}) == 10
    assert [type(member) for member in members] == [row[3] for row in TRANSPORTS]


# ===========================================================================
# 6. The boundary, in the direction this slice can hold
# ===========================================================================


def test_the_core_never_reaches_the_shared_text_client_itself():
    """``src/editorial_core/`` imports nothing from ``src/utils/``.

    This is the half of the import-direction rule that decides whether the
    transports are the harness's: a core module that could call
    ``llm_client`` itself would make a model call nobody handed it a boundary
    for, charged against nothing and measured by nothing.

    The acceptance criterion is worded more widely — no import of ``src/run``,
    ``src/utils``, ``src/publishing`` or ``src/editorial`` — and that wider
    form is **not true on main**, independently of this slice:
    ``destinations.py`` imports ``src.publishing.release_scope`` and
    ``src.run.run_manifest``, ``signal_selection.py`` imports
    ``src.editorial.source_eligibility``, and seven more modules import
    ``src.run.run_workspace`` or ``src.run.run_manifest``. Every one predates
    #361 and removing them means changing stage modules, which this slice is
    forbidden to do. So the assertion here is the part that is both true and
    this slice's to keep: ``src/utils`` clean, and the transport layer itself
    never imported by the core (below).
    """

    offending = {
        path.name
        for path in sorted(_REPO_ROOT.glob("src/editorial_core/*.py"))
        if _reaches(_imported_modules(_module_source(path)), "src.utils")
    }

    assert not offending, f"the core reached the shared client layer: {offending}"


def test_the_core_never_imports_the_transport_layer():
    """The dependency this slice adds points one way: harness to core.

    The core states what it needs of a boundary and the harness supplies it,
    which is the reason ``CallBudget`` is a Protocol too. One convenience
    import the other way would make a Golden Engine stage depend on the
    process that runs it.
    """

    offending = {
        path.name
        for path in sorted(_REPO_ROOT.glob("src/editorial_core/*.py"))
        if _reaches(_imported_modules(_module_source(path)), "src.run.transports")
    }

    assert not offending, f"the core imported its own transports: {offending}"


def test_this_branch_changes_no_stage_module():
    """The transport layer goes underneath the stages, never through them.

    #361's rule is stop-and-raise: a transport that could only be made to work
    by changing a stage is a decision to escalate, not a stage to adapt. The
    diff is the evidence, so the diff is what is asserted — and only when the
    branch touches the transport layer, so that later work on the stages is
    not held hostage by a check about transports.
    """

    if _git("rev-parse", "--git-dir")[0] != 0:
        pytest.skip("not a git checkout")

    base = ""
    for ref in ("origin/main", "main"):
        status, resolved = _git("merge-base", ref, "HEAD")
        if status == 0 and resolved:
            base = resolved
            break
    assert base, "no base revision to compare against; main is unreachable"

    status, listed = _git("diff", "--name-only", base)
    assert status == 0, "the diff against the base revision could not be read"
    changed = [line for line in listed.splitlines() if line]

    if not any(line.startswith("src/run/transports") for line in changed):
        return
    assert not [
        line for line in changed if line.startswith("src/editorial_core/")
    ], "a change to the transport layer came with a change to a stage module"


# ===========================================================================
# 7. The model decision, enforced
# ===========================================================================


@pytest.mark.parametrize("configured", [None, "", " ", "\t", "\n  \n"])
@pytest.mark.parametrize(
    "production", [row[3] for row in TRANSPORTS], ids=_ROWS
)
def test_construction_raises_when_the_model_is_missing_or_blank(
    production, configured, monkeypatch
):
    """No fallback, for any of the ten.

    Reintroducing ``or NB_OPENAI_CHAT_MODEL`` or ``or "gpt-4o"`` makes
    construction succeed and fails this test. An empty string is "not
    configured" and never a model id: GitHub Actions renders an unset secret
    as one (#173), and the Golden Engine must not fall back to the legacy
    pipeline's model because a secret name was misspelled.
    """

    monkeypatch.delenv(MODEL_VAR, raising=False)
    monkeypatch.setenv("NB_OPENAI_CHAT_MODEL", "gpt-4o")
    if configured is not None:
        monkeypatch.setenv(MODEL_VAR, configured)

    with pytest.raises(GoldenEngineModelConfigurationError):
        production()


def test_the_factory_raises_before_it_builds_a_single_transport(monkeypatch):
    """A half-built bundle would hand a caller transports it cannot use."""

    monkeypatch.delenv(MODEL_VAR, raising=False)

    with pytest.raises(GoldenEngineModelConfigurationError):
        golden_engine_transports()


def test_a_model_id_with_surrounding_whitespace_is_refused_not_trimmed(monkeypatch):
    """Refused for the reason ``NB_OPENAI_MAX_RETRIES`` refuses rather than
    clamps: silently repairing a configured value is how the mistake comes
    back, and trimming is also the only way the configured value and the value
    sent to the provider could ever differ.
    """

    monkeypatch.setenv(MODEL_VAR, f" {_MODEL} ")

    with pytest.raises(GoldenEngineModelConfigurationError):
        GoldenEngineProvider()


@pytest.mark.parametrize(_ROW_FIELDS, TRANSPORTS, ids=_ROWS)
def test_the_configured_model_is_what_reaches_the_client(
    field, stage, protocol, production, model, sent
):
    """Unaltered, and the same one for all ten (owner decision, 2026-09-28)."""

    bundle = golden_engine_transports()

    with activate_call_budget(RunCallBudget(limit=5)):
        getattr(bundle, field).complete(instructions="i", request="r")

    assert sent[0]["model"] == _MODEL


def test_the_golden_engine_variable_wins_over_the_legacy_one(monkeypatch, sent):
    """Both set: the Golden Engine's own variable is what is read.

    Together with the refusal above, this is the whole of criterion 7 — unset
    is a refusal, and set is never overridden by ``NB_OPENAI_CHAT_MODEL``.
    """

    monkeypatch.setenv(MODEL_VAR, _MODEL)
    monkeypatch.setenv("NB_OPENAI_CHAT_MODEL", "gpt-4o")
    bundle = golden_engine_transports()

    with activate_call_budget(RunCallBudget(limit=5)):
        bundle.writer.complete(instructions="i", request="r")

    assert sent[0]["model"] == _MODEL


# ===========================================================================
# The smoke: one real request across the production seam
# ===========================================================================

#: The owner's authorization for the one paid call this suite can make. It is
#: separate from ``NB_ALLOW_LIVE_API_TESTS`` on purpose: an authorized live
#: run of the whole suite still does not buy this call.
SMOKE_VAR = "NB_GOLDEN_ENGINE_SMOKE"

_NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

_LADDER = StrengthLadder(
    ladder_id="K-LAD-01",
    levels=(
        'Reported: "X says / reports …"',
        'Documented in a case: "in this case, …"',
        'Corroborated: "several independent sources show …"',
        'Established: "across … , …"',
    ),
)

_EXCERPT = "The filing records a recall of 12,000 units in March 2026."


def _smallest_core() -> EvidenceCore:
    """The smallest E-04 S-02 accepts: one source, one observation, one claim."""

    observation = SourceObservation(
        observation_id="obs-361-1",
        signal_id="signal-361",
        source_ref="source-361",
        kind=ObservationKind.QUOTE,
        excerpt=_EXCERPT,
        attribution=f"Example Press reports: {_EXCERPT}",
        is_third_party_assertion=False,
    )
    claim = EvidenceClaim(
        evidence_claim_id="evidence-361-1",
        statement=_EXCERPT,
        observation_refs=(observation.observation_id,),
        source_refs=("source-361",),
        verdict=EvidenceDisposition.ACCEPTED,
        verdict_rationale="The cited excerpt states it.",
        scope="The filing, as recorded.",
        strength=_LADDER.at(2),
        ceiling=_LADDER.at(2),
    )
    source = NormalizedSource(
        source_id="source-361",
        locator=SourceLocator(
            kind=SourceLocatorKind.URL, value="https://example.test/source-361"
        ),
        title="Recorded report",
        publisher="Example Press",
        publication_time=PublicationTime(
            status=PublicationTimeStatus.KNOWN, value=_NOW - timedelta(days=1)
        ),
        retrieved_at=_NOW,
    )
    return EvidenceCore(
        core_id="core-361",
        version=1,
        signal_ids=("signal-361",),
        research_artifact_refs=(("artifact-361", "sha256:" + "c" * 64),),
        sources=(source,),
        observations=(observation,),
        evidence_claims=(claim,),
        readiness=EvidenceReadiness.READY,
    )


@pytest.mark.live_api
@pytest.mark.skipif(
    os.environ.get(SMOKE_VAR) != "1",
    reason=(
        f"owner-gated: one real paid provider call. Set {SMOKE_VAR}=1 and "
        "NB_ALLOW_LIVE_API_TESTS=1 to run it."
    ),
)
def test_a_real_stage_request_crosses_the_production_seam():
    """One stage, its production transport, and a real answer parsed.

    It proves the seam carries a real request and that a stage can read a real
    answer back. It does **not** prove the thirteen stages compose: nothing
    here runs a second stage, and #351's risk that they do not is untouched.

    Default-skipped, and both authorizations are required: a run authorized
    for live API tests still does not buy this call without the owner's own
    variable. Nothing is published, and the budget is two so that a path
    which somehow called twice is stopped rather than measured.
    """

    transports = golden_engine_transports()
    budget = RunCallBudget(limit=2)

    with activate_call_budget(budget):
        description = describe_material(
            core=_smallest_core(), transport=transports.material
        )

    assert isinstance(description, MaterialDescription)
    assert description.continues, (
        "the production transport returned something S-02 could not read as a "
        f"description; outcomes: {description.outcomes}"
    )
    assert description.features is not None
    assert budget.used == 1
