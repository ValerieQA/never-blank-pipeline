"""
Run-scoped artifact addressing for Release 1.

Directory layout:
    <packages_dir>/<signal_id>/runs/<run_id>/research.json
    <packages_dir>/<signal_id>/runs/<run_id>/decision.json
    <packages_dir>/<signal_id>/runs/<run_id>/editorial_acceptance.json
    <packages_dir>/<signal_id>/runs/<run_id>/generated.json
    <packages_dir>/<signal_id>/runs/<run_id>/business_strategy.json
    <packages_dir>/<signal_id>/runs/<run_id>/publication_results.json

Contract:
  Every committed artifact is create-once; existing files cause ArtifactCollisionError.
  Atomic writes use a unique tmp file in the target directory (same filesystem),
  fsync and close, then an atomic create-once hard link that cannot overwrite.
  signal_id and run_id are validated before any path is constructed:
    - non-blank string;
    - not an absolute path;
    - no path separators or traversal components.

Deferred:
  Full provenance repository, retention, migration, lineage search → Issue #16.
  Legacy-artifact migration and storage abstraction → Issue #16.
  Transport-neutral intake adapter removal → Issue #29.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class ArtifactCollisionError(Exception):
    """Raised when a committed artifact already exists at the target path."""


def _validate_path_component(value: str, name: str) -> None:
    """
    Reject unsafe path components before constructing any artifact path.

    Raises ValueError for:
      - blank or non-string values;
      - absolute paths;
      - path separators (/ or \\);
      - traversal components (..);
      - filesystem-special characters.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string, got {value!r}")
    if os.path.isabs(value):
        raise ValueError(f"{name} must not be an absolute path: {value!r}")
    if "/" in value or "\\" in value:
        raise ValueError(f"{name} must not contain path separators: {value!r}")
    for part in value.replace("\\", "/").split("/"):
        if part == "..":
            raise ValueError(f"{name} must not contain traversal components: {value!r}")
    for ch in (":", "*", "?", "<", ">", "|", "\x00"):
        if ch in value:
            raise ValueError(f"{name} contains invalid character {ch!r}: {value!r}")


def resolve_run_dir(packages_dir: Path, signal_id: str, run_id: str) -> Path:
    """
    Return the canonical run directory path for (signal_id, run_id).
    Validates both components. Does NOT create the directory.
    """
    _validate_path_component(signal_id, "signal_id")
    _validate_path_component(run_id, "run_id")
    return packages_dir / signal_id / "runs" / run_id


def atomic_write_json(path: Path, data: dict) -> None:
    """
    Write data as pretty-printed JSON to path atomically.

    Steps:
      1. Create a unique tmp file in path.parent (same filesystem).
      2. Write JSON, flush, fsync, close.
      3. Atomically link tmp to the final create-once name.
      4. Remove tmp after the link succeeds.

    On any failure before step 4, the tmp file is cleaned up.
    Raises ArtifactCollisionError when the final path already exists.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: "Path | None" = None
    fd: "int | None" = None
    try:
        fd, tmp_str = tempfile.mkstemp(
            dir=path.parent,
            prefix=".tmp_",
            suffix=".json",
        )
        tmp_path = Path(tmp_str)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = None  # fdopen takes ownership; do not double-close
            fh.write(json.dumps(data, indent=2, ensure_ascii=False))
            fh.flush()
            os.fsync(fh.fileno())
        # link(2) is atomic and, unlike os.replace(), cannot overwrite an
        # existing destination.  This closes the check-then-replace race where
        # two writers could both observe a missing final path.
        try:
            os.link(tmp_path, path)
        except FileExistsError as exc:
            raise ArtifactCollisionError(
                f"Artifact already exists at {path} — "
                "each run_id may write an artifact only once."
            ) from exc
        tmp_path.unlink()
        tmp_path = None
        # Make the directory entry durable as well as the file contents.
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically commit exact bytes once, with no overwrite or partial target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: "Path | None" = None
    fd: "int | None" = None
    try:
        fd, tmp_str = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".json")
        tmp_path = Path(tmp_str)
        with os.fdopen(fd, "wb") as fh:
            fd = None
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp_path, path)
        except FileExistsError as exc:
            raise ArtifactCollisionError(
                f"Artifact already exists at {path} — each run_id may write an artifact only once."
            ) from exc
        tmp_path.unlink()
        tmp_path = None
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def write_research_json(run_dir: Path, canonical_bytes: bytes) -> None:
    """Commit the complete canonical research envelope exactly once."""
    atomic_write_bytes(run_dir / "research.json", canonical_bytes)


def load_research_json(packages_dir: Path, signal_id: str, source_run_id: str) -> bytes:
    """Load the exact immutable source-run research envelope bytes."""
    path = resolve_run_dir(packages_dir, signal_id, source_run_id) / "research.json"
    if not path.exists():
        raise FileNotFoundError(f"No research.json at {path}. Research lineage is required.")
    return path.read_bytes()


def write_decision_json(run_dir: Path, canonical_bytes: bytes) -> None:
    """Commit the exact canonical Decision Lens decision artifact exactly once."""
    atomic_write_bytes(run_dir / "decision.json", canonical_bytes)


def load_decision_json(packages_dir: Path, signal_id: str, source_run_id: str) -> bytes:
    """Load the exact immutable run-scoped decision artifact bytes."""
    path = resolve_run_dir(packages_dir, signal_id, source_run_id) / "decision.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No decision.json at {path}. A validated Decision Lens decision "
            "is required before any downstream work."
        )
    return path.read_bytes()


def write_decision_policy_json(run_dir: Path, data: dict) -> None:
    """Commit the run's explicit decision-policy record exactly once (#152).

    Written when a configured editorial role's declared decision policy —
    not the Decision Lens — authorized continuation past READY research. The
    record is the auditable chain link ``decision.json`` would otherwise be:
    a run that skipped the lens silently would be indistinguishable from a
    corrupted one, and Story #16 provenance would rightly refuse it.
    """
    atomic_write_json(run_dir / "decision_policy.json", data)


def write_editorial_acceptance_json(run_dir: Path, data: dict) -> None:
    """Commit the run's editorial acceptance audit record exactly once.

    Written for every run that reaches editorial acceptance — accepted or
    blocked — so the editorial decision history stays auditable even when the
    run stops before a publishable generated package exists.
    """
    atomic_write_json(run_dir / "editorial_acceptance.json", data)


#: Marks the review-only record as what it is, in the artifact itself rather
#: than only in its filename. Anything reading this file sees the disclaimer
#: before it sees the prose.
REVIEW_ONLY_KIND = "editorial_review_content"
REVIEW_ONLY_NOTICE = (
    "Produced content preserved for human inspection. NOT approved for "
    "publication: editorial acceptance blocked this run. This artifact is "
    "never a packaging or publication input."
)


def write_editorial_review_content_json(run_dir: Path, data: dict) -> None:
    """Preserve what a blocked run produced, for human review only (Issue #134).

    Editorial acceptance blocks before packaging, so a blocked run writes no
    ``generated.json`` and its article, LinkedIn body and visuals were being
    destroyed with the runner — leaving reviewers' prose *about* an article
    nobody can read.

    This record exists so that content can be inspected. It is deliberately
    **not** ``generated.json``: that name means "an accepted article, ready to
    package", and reusing it for refused content would make the canonical
    vocabulary lie. Nothing loads this file — ``--from-package`` reads
    ``generated.json`` and only ``generated.json`` — so preserving evidence
    cannot become a route to publishing what the gate refused.
    """

    atomic_write_json(
        run_dir / "editorial_review_content.json",
        {"artifact_kind": REVIEW_ONLY_KIND, "publishable": False,
         "notice": REVIEW_ONLY_NOTICE, **data},
    )


ACCEPTED_COMPOSITION_KIND = "accepted_composition"
ACCEPTED_COMPOSITION_NOTICE = (
    "Editorially accepted compositions preserved at the moment of acceptance, "
    "for diagnosis and product review only. NOT publishable and never a "
    "packaging or publication input: acceptance is one gate, not the last — "
    "transparency, image, visual, preflight and publication gates may still "
    "block this run, and this record says nothing about whether they did."
)


def write_accepted_composition_json(run_dir: Path, data: dict) -> None:
    """Preserve accepted compositions before the remaining gates (Issue #196).

    Editorial acceptance used to be the last moment the accepted article and
    LinkedIn body were guaranteed to exist: a run blocked by any LATER gate
    (source transparency, images, visuals, preflight) wrote no
    ``generated.json`` and its accepted content died with the runner. Live
    run 32666861632 accepted an article and lost it exactly this way — the
    only route to reading it again was paying for a full regeneration.

    This record is written immediately after acceptance returns ACCEPT, so
    accepted content survives whatever happens next. It is deliberately
    **not** ``generated.json`` and must never move earlier in its place: that
    name means "accepted AND ready to package", and nothing loads this file —
    ``--from-package`` reads ``generated.json`` and only ``generated.json`` —
    so preservation cannot become a route past any gate. Deliberately absent
    from ``CANONICAL_ARTIFACTS``: it is evidence, not authority.
    """

    atomic_write_json(
        run_dir / "accepted_composition.json",
        {"artifact_kind": ACCEPTED_COMPOSITION_KIND, "publishable": False,
         "notice": ACCEPTED_COMPOSITION_NOTICE, **data},
    )


PREVIEW_COMPOSITIONS_KIND = "preview_compositions"
PREVIEW_COMPOSITIONS_NOTICE = (
    "Preview surfaces composed before this run stopped, preserved for "
    "diagnosis only. NOT publishable and never a packaging or publication "
    "input: the run never reached a complete preview, and a surface missing "
    "here is simply one that was never composed."
)


def write_preview_compositions_json(run_dir: Path, data: dict) -> None:
    """Preserve the preview surfaces a stopped run had already composed (#260).

    ``accepted_composition.json`` holds the canonical article and its
    LinkedIn derivative; the remaining preview surfaces are composed after
    it, one format at a time. Controlled live run 35417616416 composed
    LinkedIn and Facebook, failed at Instagram, and left nothing of either
    to read — the cost of diagnosing a preview was another preview.

    Diagnostic evidence only, like every record beside it: publishable=false,
    absent from ``CANONICAL_ARTIFACTS``, and read by nothing —
    ``--from-package`` reads ``generated.json`` and only ``generated.json``.
    """

    atomic_write_json(
        run_dir / "preview_compositions.json",
        {"artifact_kind": PREVIEW_COMPOSITIONS_KIND, "publishable": False,
         "notice": PREVIEW_COMPOSITIONS_NOTICE, **data},
    )


FIDELITY_CHECK_KIND = "fidelity_check"
DIAGNOSTIC_ONLY_NOTICE = (
    "Diagnostic evidence only. NOT publishable and never a packaging or "
    "publication input; nothing reads it back."
)


def write_fidelity_check_json(run_dir: Path, sequence: int, surface: str, data: dict) -> Path:
    """Record one social-fidelity check (#263), create-once, one file per check.

    One file per check rather than one growing file: every check survives a
    run that stops at the next one, and nothing is ever overwritten.
    Diagnostic only; read by nothing — never a publication input.
    """
    safe_surface = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in surface)
    path = run_dir / "fidelity" / f"{sequence:03d}-{safe_surface}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {"artifact_kind": FIDELITY_CHECK_KIND, "publishable": False,
         "notice": DIAGNOSTIC_ONLY_NOTICE, **data},
    )
    return path


REJECTED_COMPOSITION_KIND = "rejected_composition"
REJECTED_COMPOSITION_NOTICE = (
    "Composition rejected by local validation and preserved for diagnosis "
    "only. NOT publishable and never a packaging or publication input: this "
    "text failed the composer's own contract and no gate ever accepted it."
)


def append_rejected_composition(run_dir: Path, entry: dict) -> None:
    """Preserve a composition our own validator refused (Issue #191).

    A deterministic contract failure used to be undiagnosable: the composer
    raised a message-only ``ValueError`` and both the rejected body and its
    retry were garbage-collected, so the only way to learn what the model
    actually wrote was to pay for another live run. Live run 32611137648 lost
    two bodies exactly this way.

    Every attempt is appended, so a stage that fails twice preserves both.
    Unlike the create-once canonical artifacts this file legitimately grows
    within one run — it is diagnostic evidence, not an authority, and it is
    deliberately absent from ``CANONICAL_ARTIFACTS``.

    Contains generated text and our own validation message only: no provider
    transport data, no headers, no authorization material, no provider prose.
    """

    path = run_dir / "rejected_composition.json"
    if path.exists():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Could not read {path}: {exc}") from exc
        attempts = record.get("attempts", [])
    else:
        record, attempts = {}, []
    attempts.append(entry)
    payload = {
        "artifact_kind": REJECTED_COMPOSITION_KIND,
        "publishable": False,
        "notice": REJECTED_COMPOSITION_NOTICE,
        **{k: v for k, v in record.items()
           if k not in ("artifact_kind", "publishable", "notice", "attempts")},
        "attempts": attempts,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def write_assignment_json(run_dir: Path, data: dict) -> None:
    """Commit the run's canonical intake assignment record exactly once."""
    atomic_write_json(run_dir / "assignment.json", data)


def load_assignment_json(packages_dir: Path, signal_id: str, source_run_id: str) -> dict:
    """Load the exact immutable run-scoped assignment record."""
    path = resolve_run_dir(packages_dir, signal_id, source_run_id) / "assignment.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No assignment.json at {path}. The intake assignment anchors the "
            "run provenance chain."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Assignment record at {path} is not a JSON object")
    return data


def write_visual_assets_json(run_dir: Path, data: dict) -> None:
    """Commit the run's visual assets passport exactly once."""
    atomic_write_json(run_dir / "visual_assets.json", data)


def load_visual_assets_json(packages_dir: Path, signal_id: str, source_run_id: str) -> dict:
    """Load the exact immutable source-run visual passport."""
    path = resolve_run_dir(packages_dir, signal_id, source_run_id) / "visual_assets.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No visual_assets.json at {path}. Reused visuals must prove their "
            "originating run; origin is never inferred from signal_id."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Visual passport at {path} is not a JSON object")
    return data


def write_linkedin_composition_json(run_dir: Path, data: dict) -> None:
    """Commit the run's LinkedIn composition traceability record exactly once."""
    atomic_write_json(run_dir / "linkedin_composition.json", data)


def load_linkedin_composition_json(
    packages_dir: Path, signal_id: str, source_run_id: str
) -> dict:
    """Load the exact immutable source-run LinkedIn composition record."""
    path = (
        resolve_run_dir(packages_dir, signal_id, source_run_id)
        / "linkedin_composition.json"
    )
    if not path.exists():
        raise FileNotFoundError(
            f"No linkedin_composition.json at {path}. The canonical LinkedIn "
            "body must come from the source run's accepted composition record."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"LinkedIn composition at {path} is not a JSON object")
    return data


def write_generated_json(run_dir: Path, data: dict) -> None:
    """
    Write generated.json under run_dir exactly once.
    Raises ArtifactCollisionError if generated.json already exists.
    """
    atomic_write_json(run_dir / "generated.json", data)


#: Marks a file as evidence about a run rather than a product of it. Present
#: on every diagnostic artifact so a reader — or a future loader — can tell in
#: one field that the content was never accepted and must never be published.
DIAGNOSTIC_MARKERS = {
    "canonical": False,
    "publishable": False,
    "stage": "pre_acceptance",
}


def _diagnostic(data: dict) -> dict:
    """Stamp a payload as non-canonical, unpublishable pre-acceptance evidence.

    The markers lead the object so they are the first thing anyone reading the
    file sees, and they overwrite rather than defer to the payload: a
    diagnostic file cannot describe itself as canonical no matter what it was
    handed.
    """
    return {**DIAGNOSTIC_MARKERS, **data, **DIAGNOSTIC_MARKERS}


def write_signal_snapshot_json(run_dir: Path, signal: dict) -> None:
    """Preserve the exact signal that entered generation (#215).

    Diagnostic only. Written before editorial acceptance so a run blocked at
    acceptance still shows which case was chosen and on what evidence — run
    33283836847 generated a complete article and left nothing to inspect,
    because the canonical artifact is written after the gate that stopped it.

    The object is persisted as production held it. Nothing is recomputed,
    filled in or normalized: a snapshot that differs from what generation
    actually consumed would be worse than no snapshot.
    """
    atomic_write_json(run_dir / "signal_snapshot.json", _diagnostic({"signal": signal}))


def write_generated_pre_acceptance_json(run_dir: Path, data: dict) -> None:
    """Preserve generation's complete output before acceptance judges it (#215).

    Diagnostic only, and deliberately named so it can never be mistaken for
    ``generated.json``: it is not an accepted package, it does not authorize
    publication, and no loader reads it. A blocked article stays blocked — the
    only change is that it can be read afterwards.
    """
    atomic_write_json(
        run_dir / "generated_pre_acceptance.json", _diagnostic(data)
    )


def write_business_strategy_snapshot(run_dir: Path, data: dict) -> None:
    """Commit the validated business strategy snapshot exactly once."""
    atomic_write_json(run_dir / "business_strategy.json", data)


def load_business_strategy_snapshot(
    packages_dir: Path, signal_id: str, source_run_id: str
) -> dict:
    """Load exactly one run-scoped strategy snapshot; never fall back to current."""
    run_dir = resolve_run_dir(packages_dir, signal_id, source_run_id)
    path = run_dir / "business_strategy.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No business_strategy.json at {path}. Historical configuration "
            "snapshots are required for package reuse."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Business strategy snapshot at {path} is not a JSON object")
    return data


def write_preflight_result_json(run_dir: Path, data: dict) -> None:
    """Commit the run's publication preflight verdict exactly once.

    Written before any allowed external publisher call, so the preserved
    authorization always precedes the side effect it authorizes.
    """
    atomic_write_json(run_dir / "preflight_result.json", data)


def load_preflight_result_json(
    packages_dir: Path, signal_id: str, source_run_id: str
) -> dict:
    """Load the exact immutable preflight verdict of one run."""
    path = (
        resolve_run_dir(packages_dir, signal_id, source_run_id)
        / "preflight_result.json"
    )
    if not path.exists():
        raise FileNotFoundError(f"No preflight_result.json at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Preflight result at {path} is not a JSON object")
    return data


def write_run_report_json(run_dir: Path, data: dict) -> None:
    """Commit the run's authoritative report exactly once (Issue #112)."""
    atomic_write_json(run_dir / "run_report.json", data)


def load_run_report_json(
    packages_dir: Path, signal_id: str, source_run_id: str
) -> dict:
    """Load the exact immutable run report of one run."""
    path = resolve_run_dir(packages_dir, signal_id, source_run_id) / "run_report.json"
    if not path.exists():
        raise FileNotFoundError(f"No run_report.json at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Run report at {path} is not a JSON object")
    return data


def write_linkedin_final_preflight_json(run_dir: Path, data: dict) -> None:
    """Persist the final exact-package LinkedIn authorization (Issue #196).

    The trust contract is: exact frozen package → exact-package ALLOW →
    external side effect. The canonical-URL enrichment derives a NEW frozen
    package after the run's preflight verdict was issued, so that package
    must receive — and this artifact preserves — its own ALLOW, bound to its
    own digest, before the LinkedIn publisher is called. Written exactly
    once; a collision fails closed like every other run artifact.
    """

    atomic_write_json(run_dir / "linkedin_final_preflight.json", data)


def write_publication_results_json(run_dir: Path, data: dict) -> None:
    """
    Write publication_results.json under run_dir exactly once.
    Raises ArtifactCollisionError if publication_results.json already exists.
    """
    atomic_write_json(run_dir / "publication_results.json", data)


def load_run_generated(packages_dir: Path, signal_id: str, source_run_id: str) -> dict:
    """
    Load generated.json for exactly (signal_id, source_run_id).

    Never searches by signal_id alone or selects by directory order.
    Raises FileNotFoundError if the artifact does not exist.
    Raises ValueError on JSON parse failure.
    """
    run_dir = resolve_run_dir(packages_dir, signal_id, source_run_id)
    path = run_dir / "generated.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No generated.json at {path}. "
            f"Verify signal_id={signal_id!r} and source_run_id={source_run_id!r}."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc
