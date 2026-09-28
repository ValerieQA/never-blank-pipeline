"""The production transports under the thirteen stage contracts (#361).

``src/editorial_core/`` declares ten model-call transports as ``Protocol``s —
one per stage that talks to a model — and implements none of them. The core
states what it needs of a boundary and the harness supplies it, exactly as
``CallBudget`` says of a budget. This module is that supply and nothing above
it: it wires no stage, composes no chain, and publishes nothing. Whether the
thirteen stages compose is #351's question and stays open.

**One provider core, ten named bindings.** All ten Protocols carry the
identical signature, and that is not licence to ship one object and pass it
everywhere. ``MaterialTransport`` exists under its own name so that a stage
which judges no evidence can never be handed the evidence judgment boundary,
and ``BoundaryTransport`` is one protocol for S-04's two calls because what
separates generate from probe is the instructions each carries. The named type
is the unit of routing and of per-stage configuration. Exactly one class —
:class:`GoldenEngineProvider` — performs a provider call; the ten named classes
are names over that one call path.

**Accounting is inherited, never re-implemented.** Both budget layers already
exist above this seam. ``RunCallBudget`` (#171) is charged inside
``src.utils.llm_client.chat`` before the provider request, and the #279
stage-routing measurement is taken there too; the editorial ``CallBudget`` is
spent by the stage itself before it invokes a transport at all. The transport's
whole accounting obligation is therefore one thing: go through ``chat``. A
transport that reached an OpenAI client directly would count nothing and would
silently defeat the runaway guard #171 installed.

**One model, configured once.** ``NB_GOLDEN_ENGINE_MODEL`` is the only source
of the model for all ten (owner decision, 2026-09-28). It has no fallback:
inheriting ``NB_OPENAI_CHAT_MODEL`` or the ``gpt-4o`` default would run the
canonical stages on whatever the legacy pipeline happens to be set to, and
would do it without anybody choosing it. Construction fails loudly instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import ClassVar, Final, Optional

from src.editorial_core.anchor import AnchorTransport
from src.editorial_core.candidate_strategies import StrategyTransport
from src.editorial_core.executable_plan import SegmentationTransport
from src.editorial_core.interpretation_boundary import BoundaryTransport
from src.editorial_core.material_features import MaterialTransport
from src.editorial_core.plan_check import BarrierTransport, PlanCheckTransport
from src.editorial_core.strategy_selection import RankingTransport
from src.editorial_core.text_check import TextCheckTransport
from src.editorial_core.writer import WriterTransport
from src.utils.llm_client import chat


#: The one variable that decides the model for every Golden Engine transport.
#: Deliberately not one variable per stage: splitting reasoning, checking and
#: writing models is a decision for measured evidence from the canonical
#: shadow runs, not for the slice that first makes a real call possible.
MODEL_VAR: Final[str] = "NB_GOLDEN_ENGINE_MODEL"


class GoldenEngineModelConfigurationError(RuntimeError):
    """``NB_GOLDEN_ENGINE_MODEL`` does not name a model."""


def configured_golden_engine_model() -> str:
    """The Golden Engine model, or a refusal. There is no fallback.

    Missing, empty and whitespace-only are all "not configured": GitHub
    Actions renders an unset secret as an empty string in ``env:`` (#173), so
    an empty value must never become a literal model id sent to the API. A
    value that is not already its own stripped form is refused rather than
    trimmed, for the reason ``NB_OPENAI_MAX_RETRIES`` refuses rather than
    clamps — the model that reaches the provider is the configured value
    character for character, or the run does not start.
    """

    raw = os.environ.get(MODEL_VAR)
    if raw is None or not raw.strip():
        raise GoldenEngineModelConfigurationError(
            f"{MODEL_VAR} is not set to a model id (got {raw!r}). The Golden "
            "Engine transports have no fallback: they must not inherit "
            "NB_OPENAI_CHAT_MODEL or the gpt-4o default, because a canonical "
            "run on whatever the legacy pipeline happens to be set to is a "
            "run nobody chose. Refusing to construct a transport."
        )
    if raw != raw.strip():
        raise GoldenEngineModelConfigurationError(
            f"{MODEL_VAR} is {raw!r}, which carries surrounding whitespace. "
            "Refused, never trimmed: silently repairing this one would hide "
            "the next mistake, and the model sent to the provider is the "
            "configured value exactly."
        )
    return raw


# ===========================================================================
# The one provider call
# ===========================================================================


class GoldenEngineProvider:
    """The one class in this layer that performs a provider call.

    It holds the model and nothing else. There is deliberately no ``model``
    argument: the only source of the model is ``NB_GOLDEN_ENGINE_MODEL``, and
    a constructor that accepted one would be a second source — the first thing
    a caller in a hurry would reach for, and the end of the guarantee that
    every canonical call names the model somebody configured.
    """

    def __init__(self) -> None:
        self._model = configured_golden_engine_model()

    @property
    def model(self) -> str:
        return self._model

    def complete(self, *, instructions: str, request: str) -> str:
        """One logical call, through the shared text client and nothing else.

        ``instructions`` and ``request`` reach ``chat`` exactly as the stage
        wrote them. A transport that trimmed, prefixed or templated either
        would change what a stage decided while every test of that stage still
        passed, and nothing downstream could see that it had.

        ``json_mode`` is an adapter-internal choice and it is the same for all
        ten: every one of these stages parses a JSON object out of the string
        it is returned. A stage whose parser could not be satisfied from here
        would be a stop-and-raise, not a stage to adapt or a parser to loosen.
        """

        return chat(
            system=instructions,
            user=request,
            json_mode=True,
            model=self._model,
        )


# ===========================================================================
# Ten names over that one call
# ===========================================================================


class _NamedTransport:
    """A named binding over the one provider core.

    Named, because the type is what keeps a stage from being handed another
    stage's boundary. A binding, because it adds nothing to the call: it
    forwards the two strings and returns the answer. ``stage`` is identity,
    not routing — the model is shared by owner decision, and nothing here
    reads ``stage`` to choose a model, a client or an instruction.
    """

    #: The stage this binding belongs to, as §6.2 names it.
    stage: ClassVar[str]

    def __init__(self, core: Optional[GoldenEngineProvider] = None) -> None:
        self._core = GoldenEngineProvider() if core is None else core

    @property
    def core(self) -> GoldenEngineProvider:
        return self._core

    def complete(self, *, instructions: str, request: str) -> str:
        return self._core.complete(instructions=instructions, request=request)


class GoldenEngineMaterialTransport(_NamedTransport):
    """S-02's ``MaterialTransport``: the one call that describes material."""

    stage: ClassVar[str] = "S-02"


class GoldenEngineBoundaryTransport(_NamedTransport):
    """S-04's ``BoundaryTransport``: both the generate and the probe call."""

    stage: ClassVar[str] = "S-04"


class GoldenEngineAnchorTransport(_NamedTransport):
    """S-06's ``AnchorTransport``: the call that chooses a unit's anchor."""

    stage: ClassVar[str] = "S-06"


class GoldenEngineStrategyTransport(_NamedTransport):
    """S-08's ``StrategyTransport``: the call that proposes whole strategies."""

    stage: ClassVar[str] = "S-08"


class GoldenEngineRankingTransport(_NamedTransport):
    """S-09's ``RankingTransport``: the call that ranks what survived."""

    stage: ClassVar[str] = "S-09"


class GoldenEngineSegmentationTransport(_NamedTransport):
    """S-10's ``SegmentationTransport``: segments, and the first line."""

    stage: ClassVar[str] = "S-10"


class GoldenEnginePlanCheckTransport(_NamedTransport):
    """S-11's ``PlanCheckTransport``: V-P01's semantic half and V-P04."""

    stage: ClassVar[str] = "S-11"


class GoldenEngineBarrierTransport(_NamedTransport):
    """S-11's ``BarrierTransport``: V-P03, one call per unit per round.

    Its own name beside the plan check's because it is its own question: a
    barrier round asks about the unit, not about one destination's plan.
    """

    stage: ClassVar[str] = "S-11"


class GoldenEngineWriterTransport(_NamedTransport):
    """S-12's ``WriterTransport``: the plan, executed in prose."""

    stage: ClassVar[str] = "S-12"


class GoldenEngineTextCheckTransport(_NamedTransport):
    """S-13's ``TextCheckTransport``: both of the text check's calls."""

    stage: ClassVar[str] = "S-13"


# ===========================================================================
# The one construction point
# ===========================================================================


@dataclass(frozen=True, slots=True)
class GoldenEngineTransports:
    """The ten bindings, as the one thing a harness is handed.

    One seam to wire rather than ten, and frozen because which transport a
    stage is given is decided once, at construction, by the code that built
    them — never swapped underneath a run.

    The fields are typed as the core's own Protocols, so this is where each
    production class is checked against the contract its stage declares: a
    signature that drifted stops the type check here, at construction, rather
    than at the first real call.
    """

    material: MaterialTransport
    boundary: BoundaryTransport
    anchor: AnchorTransport
    strategy: StrategyTransport
    ranking: RankingTransport
    segmentation: SegmentationTransport
    plan_check: PlanCheckTransport
    barrier: BarrierTransport
    writer: WriterTransport
    text_check: TextCheckTransport


def golden_engine_transports() -> GoldenEngineTransports:
    """Build the ten named bindings over one core, from the one model.

    Raises before any transport exists when ``NB_GOLDEN_ENGINE_MODEL`` is not
    configured: an unconfigured Golden Engine has nothing to fall back to, and
    a bundle that half-built would hand a caller transports it could not use.
    """

    core = GoldenEngineProvider()
    return GoldenEngineTransports(
        material=GoldenEngineMaterialTransport(core),
        boundary=GoldenEngineBoundaryTransport(core),
        anchor=GoldenEngineAnchorTransport(core),
        strategy=GoldenEngineStrategyTransport(core),
        ranking=GoldenEngineRankingTransport(core),
        segmentation=GoldenEngineSegmentationTransport(core),
        plan_check=GoldenEnginePlanCheckTransport(core),
        barrier=GoldenEngineBarrierTransport(core),
        writer=GoldenEngineWriterTransport(core),
        text_check=GoldenEngineTextCheckTransport(core),
    )
