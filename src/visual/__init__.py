"""
Never Blank — Visual boundary stub (Task #27).

VisualArtifactRequest is the typed adapter for the visual-artifact boundary.
It carries run_id so every visual output can be correlated with the originating run.

Full implementation (image generation, design-version selection, Cloudinary upload)
is owned by the Visual System story and is deferred to that milestone.  In Release 1
this boundary always returns a blocked result; the canonical path constructs the
adapter, asserts identity, logs it, then calls the image pipeline directly.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VisualArtifactRequest:
    """
    Typed boundary adapter for visual artifact preparation.

    Constructed by the canonical entry point before image preparation.
    `blocked=True` until the Visual System story is implemented.
    The canonical path checks `blocked`, logs it, and falls through to
    the direct image pipeline — it does NOT raise when blocked.
    Identity assertion still runs so run_id mismatch is caught immediately.

    Deferred: full image routing, design-version locking, Cloudinary upload.
    """
    run_id:         str
    signal_id:      str
    design_version: str
    blocked:        bool = True
    blocked_reason: str  = (
        "Visual System story not yet implemented — image pipeline called directly"
    )

    def assert_identity(self, expected_run_id: str) -> None:
        """Fail closed if this request's run_id does not match the expected value."""
        if self.run_id != expected_run_id:
            raise RuntimeError(
                f"VisualArtifactRequest run_id mismatch: "
                f"request={self.run_id!r} expected={expected_run_id!r}"
            )
