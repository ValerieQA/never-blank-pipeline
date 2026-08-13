"""
Run-scoped artifact addressing for Release 1.

Directory layout:
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


def write_generated_json(run_dir: Path, data: dict) -> None:
    """
    Write generated.json under run_dir exactly once.
    Raises ArtifactCollisionError if generated.json already exists.
    """
    atomic_write_json(run_dir / "generated.json", data)


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
