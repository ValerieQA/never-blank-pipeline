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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.strategy.execution_context import ConfigurationIdentity, VisualStrategyView


@dataclass
class VisualArtifactRequest:
    """
    Typed boundary adapter for visual artifact preparation.

    Constructed by the canonical entry point before image preparation.
    Since Issue #96 the canonical Release 1 path is active
    (``blocked=False``): the resulting derivatives are validated and
    persisted through ``src.visual.contract`` (the fail-closed visual gate),
    while rendering continues to use the existing image pipeline.
    Identity assertion still runs so run_id mismatch is caught immediately.

    Deferred: full image routing and provider abstraction (post-R1).
    """
    run_id:         str
    signal_id:      str
    design_version: str
    strategy_view: "VisualStrategyView | None" = None
    blocked:        bool = False
    blocked_reason: str  = ""

    def assert_identity(self, expected_run_id: str) -> None:
        """Fail closed if this request's run_id does not match the expected value."""
        if self.run_id != expected_run_id:
            raise RuntimeError(
                f"VisualArtifactRequest run_id mismatch: "
                f"request={self.run_id!r} expected={expected_run_id!r}"
            )

    def assert_configuration_identity(
        self, expected: "ConfigurationIdentity"
    ) -> None:
        """Require the controlled path's declared visual strategy view."""

        from src.strategy.execution_context import (
            StrategyExecutionError,
            require_configuration_identity,
        )

        if self.strategy_view is None:
            raise StrategyExecutionError(
                "visual strategy view is missing at visual-artifact boundary"
            )
        require_configuration_identity(
            expected, self.strategy_view.identity, "visual-artifact"
        )
