"""Canonical orchestration boundary for the run-scoped Decision Lens verdict.

The Decision Lens verdict is the mandatory Release 1 business gate between
research and all narrative/editorial/downstream work. A run may proceed beyond
the Decision Lens only when one canonical, strictly validated
``DecisionLensDecisionArtifact`` exists for that exact run and its disposition
is ``PROCEED``. Every other outcome — a legitimate non-``PROCEED`` business
decision, or an evaluator/system failure where no valid decision artifact
exists — is an explicit stop.

Lifecycle (fresh generation run):

1. the caller supplies the validated current-run research artifact and typed
   context (strategy view, audience, configuration identity, expected lens
   profile, exact run/assignment/signal identity);
2. the Issue #59 production evaluator is invoked exactly once;
3. a successful canonical decision result is required — evaluator failure is a
   typed stop and is never mapped into a synthetic decision artifact;
4. immutable run-scoped ``decision.json`` is created atomically (create-once);
5. the persisted artifact is strict-reloaded and revalidated against the same
   current-run research, configuration, audience, and lens profile identity;
6. the persisted-and-reloaded artifact — not the in-memory pre-write object —
   is the final gate: only ``PROCEED`` may enter downstream generation.

Reuse (``--from-package``) loads the original generation run's immutable
``decision.json``, never re-runs the Decision Lens, never rewrites the
artifact, and revalidates it against that run's immutable research and exact
lineage. A retry after a failed or blocked generation follows new-run
semantics; the original decision artifact is never mutated.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from src.artifacts import load_decision_json, write_decision_json
from src.editorial.decision_contract import (
    DecisionContractError,
    DecisionDisposition,
    DecisionLensDecisionArtifact,
    DecisionLensProfileIdentity,
)
from src.editorial.decision_lens_evaluator import (
    DecisionLensEvaluator,
    EvaluationOutcome,
)
from src.research.evidence import NormalizedResearchArtifact
from src.strategy.execution_context import (
    AudienceSelection,
    ConfigurationIdentity,
    DecisionLensEditorialStrategyView,
)


# The Release 1 lens profile identity this orchestration expects. Changing the
# maintained instruction profile requires updating this expectation in a
# reviewed commit; a mismatch is a business stop, not a fallback.
RELEASE1_LENS_PROFILE = DecisionLensProfileIdentity(
    lens_profile_id="never-blank-editorial-lens",
    lens_profile_version="1.1",
)


class DecisionGateError(RuntimeError):
    """The Decision Lens verdict blocks this run from any downstream work."""


def evaluate_and_persist_decision(
    evaluator: DecisionLensEvaluator,
    *,
    research: NormalizedResearchArtifact,
    strategy_view: DecisionLensEditorialStrategyView,
    audience: AudienceSelection,
    configuration_identity: ConfigurationIdentity,
    lens_profile: DecisionLensProfileIdentity,
    run_id: str,
    assignment_id: str,
    signal_id: str,
    run_dir: Path,
) -> DecisionLensDecisionArtifact:
    """Invoke the Decision Lens exactly once, persist, strict-reload, revalidate.

    Returns the persisted-and-reloaded canonical artifact (any disposition).
    Raises ``DecisionGateError`` when no valid canonical decision exists, and
    ``ArtifactCollisionError``/``OSError`` on persistence collision or write
    failure. Disposition enforcement is ``require_proceed()``.
    """

    result = evaluator.evaluate(
        research=research,
        strategy_view=strategy_view,
        audience=audience,
        configuration_identity=configuration_identity,
        lens_profile=lens_profile,
        run_id=run_id,
        assignment_id=assignment_id,
        signal_id=signal_id,
    )
    if result.outcome is not EvaluationOutcome.DECISION or result.decision is None:
        failure = result.failure
        raise DecisionGateError(
            "Decision Lens evaluation failed "
            f"({failure.kind.value}): {failure.detail}"
        )

    write_decision_json(run_dir, result.decision.canonical_bytes())

    # Strict-reload the persisted file directly from the run directory:
    # storage addressing (the run namespace) is deliberately independent of
    # the execution signal identity carried inside the artifact.
    return _validate_decision_bytes(
        (run_dir / "decision.json").read_bytes(),
        research=research,
        audience=audience,
        configuration_identity=configuration_identity,
        lens_profile=lens_profile,
        expected_run_id=run_id,
    )


def load_decision_artifact(
    packages_dir: Path,
    signal_id: str,
    source_run_id: str,
    *,
    research: NormalizedResearchArtifact,
    audience: AudienceSelection,
    configuration_identity: ConfigurationIdentity,
    lens_profile: DecisionLensProfileIdentity,
) -> DecisionLensDecisionArtifact:
    """Strict-reload one immutable run-scoped decision and revalidate its lineage.

    ``signal_id`` here is the run-namespace address component only; the
    execution signal identity inside the artifact is validated independently
    against the supplied research lineage. Never re-runs the Decision Lens and
    never rewrites the artifact. Fails closed for missing, corrupt,
    non-canonical, cross-run, configuration, audience, lens-profile,
    research-digest, and citation-lineage mismatch.
    """

    try:
        raw = load_decision_json(packages_dir, signal_id, source_run_id)
    except FileNotFoundError as exc:
        raise DecisionGateError(str(exc)) from exc
    return _validate_decision_bytes(
        raw,
        research=research,
        audience=audience,
        configuration_identity=configuration_identity,
        lens_profile=lens_profile,
        expected_run_id=source_run_id,
    )


def _validate_decision_bytes(
    raw: bytes,
    *,
    research: NormalizedResearchArtifact,
    audience: AudienceSelection,
    configuration_identity: ConfigurationIdentity,
    lens_profile: DecisionLensProfileIdentity,
    expected_run_id: str,
) -> DecisionLensDecisionArtifact:
    try:
        artifact = DecisionLensDecisionArtifact.validate_json_for_research(
            raw,
            research=research,
            audience=audience,
            configuration_identity=configuration_identity,
            lens_profile=lens_profile,
        )
    except DecisionContractError as exc:
        raise DecisionGateError(
            f"decision.json failed contextual revalidation: {exc}"
        ) from exc
    except (ValidationError, ValueError) as exc:
        raise DecisionGateError(
            "decision.json is malformed or violates the strict contract"
        ) from exc

    if raw != artifact.canonical_bytes():
        raise DecisionGateError("decision.json is not canonical")
    if artifact.run_id != expected_run_id:
        raise DecisionGateError(
            "decision.json run identity does not match the requested run: "
            f"artifact run_id={artifact.run_id!r} requested={expected_run_id!r}"
        )
    return artifact


def require_proceed(artifact: DecisionLensDecisionArtifact) -> None:
    """Allow downstream work only for a canonical ``PROCEED`` decision.

    A non-``PROCEED`` disposition is a legitimate, persisted business decision
    and an explicit stop — distinct from evaluator failure, where no artifact
    exists at all.
    """

    if artifact.disposition is not DecisionDisposition.PROCEED:
        raise DecisionGateError(
            f"Decision Lens disposition is {artifact.disposition.value!r} — "
            "the run stops before any narrative, editorial, visual, package, "
            "or publisher work"
        )
