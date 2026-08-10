"""
src/controlled_run/artifact_store.py
Abstract artifact store interface and isolated concrete implementation.

The controlled run writes ALL artifacts to a single isolated run directory.
Nothing is written outside that directory during a controlled run.

## Usage

    store = IsolatedRunArtifactStore(run_dir)
    store.write("signal.json", json.dumps(signal).encode())
    data = store.read("signal.json")

## Dependency injection

The controlled run orchestrator creates an IsolatedRunArtifactStore and
passes it to any component that needs to write artifacts. This replaces
direct Path(...).write_text() calls in critical paths.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class ArtifactStore(ABC):
    """Abstract interface for reading and writing named artifacts."""

    @abstractmethod
    def write(self, name: str, data: bytes | str) -> Path:
        """
        Write `data` to artifact `name`.

        Args:
            name:  Artifact filename (no directory components).
            data:  Content to write (bytes or str).

        Returns:
            Absolute path where the artifact was written.
        """

    @abstractmethod
    def read(self, name: str) -> Optional[bytes]:
        """
        Read artifact `name`.

        Returns:
            Content as bytes, or None if not present.
        """

    @abstractmethod
    def artifact_path(self, name: str) -> Path:
        """Return the path where artifact `name` would be stored."""


class IsolatedRunArtifactStore(ArtifactStore):
    """
    Concrete artifact store that writes exclusively to `run_dir`.

    Guaranteed to write ONLY inside `run_dir` — no escaping via relative
    paths. Any `name` with directory separators is rejected.

    Usage:
        store = IsolatedRunArtifactStore(run_dir)
        path = store.write("result.json", json.dumps(data).encode())
        assert path.parent == run_dir
    """

    def __init__(self, run_dir: Path):
        if not run_dir.is_absolute():
            raise ValueError(f"run_dir must be absolute: {run_dir}")
        self._run_dir = run_dir.resolve()
        self._run_dir.mkdir(parents=True, exist_ok=True)

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    def artifact_path(self, name: str) -> Path:
        if "/" in name or "\\" in name or ".." in name:
            raise ValueError(f"Artifact name must be a plain filename: {name!r}")
        return self._run_dir / name

    def write(self, name: str, data: bytes | str) -> Path:
        path = self.artifact_path(name)
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8")
        else:
            path.write_bytes(data)
        return path

    def write_json(self, name: str, obj: object) -> Path:
        """Convenience: serialize `obj` to JSON and write."""
        return self.write(name, json.dumps(obj, indent=2, ensure_ascii=False))

    def read(self, name: str) -> Optional[bytes]:
        path = self.artifact_path(name)
        if not path.exists():
            return None
        return path.read_bytes()

    def list_artifacts(self) -> list[str]:
        """Return names of all files currently in run_dir."""
        return [f.name for f in self._run_dir.iterdir() if f.is_file()]
