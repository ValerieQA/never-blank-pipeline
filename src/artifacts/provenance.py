"""Deterministic whole-run provenance verification (Issue #98 / Story #16).

Given the evidence folder for one run, answer: *do these records genuinely
describe one internally consistent execution?* The verifier is strictly
read-only — it never regenerates content, calls models or publishers, or
mutates artifacts — and it verifies the **relationships** between the
canonical run-scoped artifacts, not merely each JSON in isolation.

Lifecycle-stage semantics: a run may legitimately stop at an earlier gate
(Decision Lens non-``PROCEED``, editorial non-accept, a blocked LinkedIn
composition or visual gate, or a dry run that never publishes). "Valid
provenance" therefore never means "every artifact exists". The verifier fails
only when an artifact required by the stage the run actually reached is
missing, an artifact belongs to another run/source/configuration, a
digest/reference is inconsistent, a later artifact exists without its valid
upstream chain, or an artifact is malformed — a blocked business outcome is
not corrupted provenance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.artifacts import resolve_run_dir
from src.editorial.decision_contract import (
    DecisionDisposition,
    DecisionLensDecisionArtifact,
    research_artifact_digest,
)
from src.editorial.linkedin_composition import LinkedInCompositionRecord
from src.intake.assignment_record import AssignmentRecord
from src.research.provider import ResearchResultEnvelope
from src.strategy.business_config import BusinessStrategyConfiguration
from src.strategy.execution_context import ConfigurationIdentity
from src.visual.contract import VisualAssetsRecord


class ProvenanceError(RuntimeError):
    """The run evidence does not describe one internally consistent execution."""


class RunProvenanceReport(BaseModel):
    """Result of one successful verification: what was proven, where it stopped."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    run_kind: str                       # "generation" | "reuse-publication"
    verified_artifacts: tuple[str, ...]
    stopped_after: str                  # last verified lifecycle stage


def _load(run_dir: Path, name: str) -> dict | None:
    path = run_dir / name
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ProvenanceError(f"{name} is malformed: {exc}") from exc
    if not isinstance(data, dict):
        raise ProvenanceError(f"{name} is not a JSON object")
    return data


def _article_digest(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProvenanceError(message)


def verify_run_provenance(
    packages_dir: Path, signal_id: str, run_id: str
) -> RunProvenanceReport:
    """Verify the complete applicable provenance chain of one run.

    ``signal_id`` is the storage namespace component; identity consistency is
    proven from the artifacts themselves.
    """

    run_dir = resolve_run_dir(Path(packages_dir), signal_id, run_id)
    _require(run_dir.is_dir(), f"run directory does not exist: {run_dir}")

    verified: list[str] = []

    # ── assignment: the anchor of the chain ──────────────────────────────────
    raw = _load(run_dir, "assignment.json")
    _require(raw is not None, "assignment.json is missing — the intake anchor is required")
    try:
        assignment_record = AssignmentRecord.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise ProvenanceError(f"assignment.json violates the strict contract: {exc}") from exc
    _require(
        assignment_record.run_id == run_id,
        "assignment.json belongs to a different run "
        f"(record={assignment_record.run_id!r}, expected={run_id!r})",
    )
    config: ConfigurationIdentity = assignment_record.configuration_identity
    assignment_id = assignment_record.assignment.assignment_id
    verified.append("assignment")

    # ── business strategy snapshot: recomputable configuration identity ─────
    raw = _load(run_dir, "business_strategy.json")
    _require(raw is not None, "business_strategy.json is missing")
    try:
        snapshot = BusinessStrategyConfiguration.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise ProvenanceError(
            f"business_strategy.json violates the strict contract: {exc}"
        ) from exc
    snapshot_identity = config.from_configuration(snapshot)
    _require(
        snapshot_identity == config,
        "business strategy snapshot does not reproduce the run's configuration identity",
    )
    verified.append("business_strategy")

    # ── publication results are read early only to classify the run kind ────
    publication = _load(run_dir, "publication_results.json")
    if publication is not None:
        _require(
            publication.get("run_id") == run_id,
            "publication_results.json belongs to a different run "
            f"(record={publication.get('run_id')!r}, expected={run_id!r})",
        )
        # publication evidence declares which configuration produced it; a
        # declared configuration is part of the proven chain, never ignored
        # metadata (applies to generation AND reuse publication runs)
        try:
            publication_config = ConfigurationIdentity.model_validate(
                publication.get("configuration_identity")
            )
        except Exception as exc:  # noqa: BLE001
            raise ProvenanceError(
                "publication_results.json carries no valid configuration identity"
            ) from exc
        _require(
            publication_config == config,
            "publication result claims a configuration different from the "
            "run's authoritative configuration identity",
        )
    visual_raw = _load(run_dir, "visual_assets.json")
    visual: VisualAssetsRecord | None = None
    if visual_raw is not None:
        try:
            visual = VisualAssetsRecord.model_validate(visual_raw)
        except Exception as exc:  # noqa: BLE001
            raise ProvenanceError(
                f"visual_assets.json violates the strict contract: {exc}"
            ) from exc
        _require(
            visual.run_id == run_id,
            "visual_assets.json belongs to a different run "
            f"(record={visual.run_id!r}, expected={run_id!r})",
        )

    reuse_run = bool(
        (visual is not None and visual.reused)
        or (publication is not None and publication.get("source_run_id") != run_id)
    )

    if reuse_run:
        return _verify_reuse_publication_run(
            run_id, verified, visual, publication, packages_dir=Path(packages_dir),
            signal_id=signal_id, config=config,
        )

    # ═══════════════════════════ generation run ═════════════════════════════
    research_raw = _load(run_dir, "research.json")
    decision_raw = _load(run_dir, "decision.json")
    editorial = _load(run_dir, "editorial_acceptance.json")
    linkedin_raw = _load(run_dir, "linkedin_composition.json")
    generated = _load(run_dir, "generated.json")

    # later evidence without its upstream chain is corruption, not a stop
    ladder = [
        ("research", research_raw), ("decision", decision_raw),
        ("editorial_acceptance", editorial),
        ("linkedin_composition", linkedin_raw),
        ("visual_assets", visual_raw), ("generated", generated),
        ("publication_results", publication),
    ]
    seen_gap: str | None = None
    for name, item in ladder:
        if item is None:
            seen_gap = seen_gap or name
        elif seen_gap is not None:
            raise ProvenanceError(
                f"{name} exists although the run has no {seen_gap} — a later "
                "artifact cannot exist without its upstream chain"
            )

    if research_raw is None:
        return RunProvenanceReport(
            run_id=run_id, run_kind="generation",
            verified_artifacts=tuple(verified), stopped_after="business_strategy",
        )
    try:
        envelope = ResearchResultEnvelope.model_validate(research_raw)
    except Exception as exc:  # noqa: BLE001
        raise ProvenanceError(f"research.json violates the strict contract: {exc}") from exc
    _require(
        envelope.request.run_id == run_id,
        "research.json belongs to a different run",
    )
    _require(
        envelope.request.assignment_id == assignment_id,
        "research assignment identity does not match the persisted assignment",
    )
    research = getattr(envelope.result, "artifact", None)
    research_ready = (
        research is not None
        and getattr(research.readiness, "value", None) == "ready"
        and getattr(envelope.result.outcome, "value", None) == "complete"
    )
    if not research_ready:
        # Honestly persisted failed/partial/non-ready research is a
        # legitimate research-stage stop — but nothing may exist downstream.
        _require(
            decision_raw is None and editorial is None and generated is None
            and linkedin_raw is None and visual_raw is None and publication is None,
            "downstream artifacts exist although research did not reach READY",
        )
        verified.append("research")
        return RunProvenanceReport(
            run_id=run_id, run_kind="generation",
            verified_artifacts=tuple(verified), stopped_after="research",
        )
    _require(research.run_id == run_id, "research artifact belongs to a different run")
    _require(
        research.assignment_id == assignment_id,
        "research artifact assignment identity does not match the persisted assignment",
    )
    _require(
        research.configuration_identity == config,
        "research configuration identity does not match the run configuration",
    )
    verified.append("research")

    if decision_raw is None:
        return RunProvenanceReport(
            run_id=run_id, run_kind="generation",
            verified_artifacts=tuple(verified), stopped_after="research",
        )
    try:
        decision = DecisionLensDecisionArtifact.model_validate(decision_raw)
    except Exception as exc:  # noqa: BLE001
        raise ProvenanceError(f"decision.json violates the strict contract: {exc}") from exc
    _require(decision.run_id == run_id, "decision.json belongs to a different run")
    _require(
        decision.assignment_id == assignment_id,
        "decision assignment identity does not match the persisted assignment",
    )
    _require(
        decision.signal_id == research.signal_id,
        "decision signal identity does not match the research artifact",
    )
    _require(
        decision.configuration_identity == config,
        "decision configuration identity does not match the run configuration",
    )
    _require(
        decision.research_digest == research_artifact_digest(research),
        "decision.json does not reference this run's research state "
        "(research digest mismatch)",
    )
    verified.append("decision")

    if decision.disposition is not DecisionDisposition.PROCEED:
        _require(
            editorial is None and generated is None and linkedin_raw is None
            and visual_raw is None and publication is None,
            "downstream artifacts exist although the Decision Lens did not PROCEED",
        )
        return RunProvenanceReport(
            run_id=run_id, run_kind="generation",
            verified_artifacts=tuple(verified), stopped_after="decision",
        )

    if editorial is None:
        return RunProvenanceReport(
            run_id=run_id, run_kind="generation",
            verified_artifacts=tuple(verified), stopped_after="decision",
        )
    _require(
        editorial.get("run_id") == run_id,
        "editorial_acceptance.json belongs to a different run",
    )
    accepted = editorial.get("accepted") is True
    verified.append("editorial_acceptance")

    if not accepted:
        _require(
            generated is None and linkedin_raw is None
            and visual_raw is None and publication is None,
            "downstream artifacts exist although editorial acceptance did not accept",
        )
        return RunProvenanceReport(
            run_id=run_id, run_kind="generation",
            verified_artifacts=tuple(verified), stopped_after="editorial_acceptance",
        )

    linkedin: LinkedInCompositionRecord | None = None
    if linkedin_raw is not None:
        try:
            linkedin = LinkedInCompositionRecord.model_validate(linkedin_raw)
        except Exception as exc:  # noqa: BLE001
            raise ProvenanceError(
                f"linkedin_composition.json violates the strict contract: {exc}"
            ) from exc
        _require(
            linkedin.run_id == run_id,
            "linkedin_composition.json belongs to a different run",
        )
        _require(
            linkedin.configuration_identity == config,
            "linkedin composition configuration identity mismatch",
        )
        verified.append("linkedin_composition")

    if visual is not None:
        _require(
            not visual.reused and visual.origin_run_id == run_id,
            "a generation run cannot carry a reused visual passport",
        )
        if linkedin is not None:
            _require(
                visual.source_article_digest == linkedin.source_article_digest,
                "visual and LinkedIn records reference different article states",
            )
        verified.append("visual_assets")

    if generated is None:
        return RunProvenanceReport(
            run_id=run_id, run_kind="generation",
            verified_artifacts=tuple(verified),
            stopped_after=verified[-1],
        )
    _require(generated.get("run_id") == run_id, "generated.json belongs to a different run")
    _require(
        linkedin is not None and visual is not None,
        "generated.json exists without its LinkedIn composition or visual passport",
    )
    article = generated.get("blog_article")
    _require(
        isinstance(article, str) and bool(article.strip()),
        "generated.json carries no article body",
    )
    digest = _article_digest(article)
    _require(
        linkedin.source_article_digest == digest,
        "linkedin composition does not derive from this run's accepted article",
    )
    _require(
        visual.source_article_digest == digest,
        "visual passport does not derive from this run's accepted article",
    )
    _require(
        generated.get("linkedin_post") == linkedin.linkedin_body,
        "generated LinkedIn body does not match the accepted LinkedIn composition",
    )
    verified.append("generated")

    if publication is None:
        return RunProvenanceReport(
            run_id=run_id, run_kind="generation",
            verified_artifacts=tuple(verified), stopped_after="generated",
        )
    _require(
        publication.get("run_id") == run_id,
        "publication_results.json belongs to a different run",
    )
    _require(
        publication.get("source_run_id") == run_id
        and publication.get("generation_run_id") == run_id,
        "publication result of a generation run must reference itself as source",
    )
    verified.append("publication_results")

    return RunProvenanceReport(
        run_id=run_id, run_kind="generation",
        verified_artifacts=tuple(verified), stopped_after="publication_results",
    )


def _verify_reuse_publication_run(
    run_id: str,
    verified: list[str],
    visual: VisualAssetsRecord | None,
    publication: dict | None,
    *,
    packages_dir: Path,
    signal_id: str,
    config: ConfigurationIdentity,
) -> RunProvenanceReport:
    """Verify a --from-package publication run: its evidence references the
    originating generation run instead of duplicating it."""

    source_run_id: str | None = None
    if visual is not None:
        _require(
            visual.reused and visual.origin_run_id != run_id,
            "reuse-publication run carries a non-reuse visual passport",
        )
        source_run_id = visual.origin_run_id
        verified.append("visual_assets")
    if publication is not None:
        _require(
            publication.get("run_id") == run_id,
            "publication_results.json belongs to a different run",
        )
        pub_source = publication.get("source_run_id")
        pub_generation = publication.get("generation_run_id")
        _require(
            isinstance(pub_source, str) and pub_source != run_id,
            "reuse publication must reference its source generation run",
        )
        _require(
            pub_generation == pub_source,
            "reuse publication source and generation identities disagree",
        )
        if source_run_id is not None:
            _require(
                pub_source == source_run_id,
                "publication source run does not match the visual origin run",
            )
        source_run_id = pub_source
        verified.append("publication_results")

    _require(
        source_run_id is not None,
        "reuse-publication run has no verifiable source-run reference",
    )
    _require(
        publication is None or visual is not None,
        "reuse publication exists without its reuse visual passport",
    )

    # The originating generation run must itself be a VALID canonical
    # generation provenance chain — a filename in the source directory is not
    # provenance. The existing verifier is reused (no second source
    # verifier); a source that is itself a reuse run is rejected, which also
    # bounds the recursion at depth one.
    try:
        source_report = verify_run_provenance(packages_dir, signal_id, source_run_id)
    except ProvenanceError as exc:
        raise ProvenanceError(
            f"source generation run {source_run_id} failed provenance "
            f"verification: {exc}"
        ) from exc
    _require(
        source_report.run_kind == "generation",
        f"source run {source_run_id} is not a generation run — a reuse "
        "publication cannot chain to another reuse run",
    )
    _require(
        "generated" in source_report.verified_artifacts,
        f"source generation run {source_run_id} never reached the generated "
        "stage — there is no accepted content to reuse",
    )

    source_dir = resolve_run_dir(packages_dir, signal_id, source_run_id)
    source_generated = _load(source_dir, "generated.json")
    _require(
        source_generated is not None,
        f"originating generation run {source_run_id} has no generated.json",
    )
    # the reused article/visual state must be the state actually proven by A
    if visual is not None:
        source_article = source_generated.get("blog_article")
        _require(
            isinstance(source_article, str) and bool(source_article.strip()),
            "source generated.json carries no article body",
        )
        _require(
            visual.source_article_digest == _article_digest(source_article),
            "reused visual passport does not match the source run's actual "
            "accepted article state",
        )
    # the publication run must use the source generation's configuration
    source_assignment_raw = _load(source_dir, "assignment.json")
    _require(
        source_assignment_raw is not None,
        f"source generation run {source_run_id} has no assignment.json",
    )
    try:
        source_assignment = AssignmentRecord.model_validate(source_assignment_raw)
    except Exception as exc:  # noqa: BLE001
        raise ProvenanceError(
            "source assignment.json violates the strict contract"
        ) from exc
    _require(
        source_assignment.configuration_identity == config,
        "reuse publication configuration does not match the source "
        "generation configuration",
    )

    return RunProvenanceReport(
        run_id=run_id, run_kind="reuse-publication",
        verified_artifacts=tuple(verified),
        stopped_after=verified[-1],
    )
