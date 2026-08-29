"""Wednesday's restored July editorial package (#207).

An isolated, literal restoration of the 2026-07-06 editorial path that
produced the Versant / Full Swing specimen (forensics: #206). It exists
because the shared ``src/editorial/`` stages have evolved under Monday-driven
work in ways that change Wednesday's editorial behaviour — most decisively
``pattern_extractor``, which did not exist in July and which asserts an
owner protagonist and rejects large-company-strategy signals.

This package is a **customer-package component** in the sense of #205: it
carries Never Blank's Wednesday editorial philosophy and must not be
refactored into the generic engine, reconciled with Monday, or "kept in sync"
with ``src/editorial/``.
"""

from src.never_blank.wednesday_july.pipeline import (
    DELIBERATELY_ABSENT_STAGES,
    JULY_STAGE_ORDER,
    WednesdayGenerationError,
    generate_wednesday_article,
)

__all__ = [
    "DELIBERATELY_ABSENT_STAGES",
    "JULY_STAGE_ORDER",
    "WednesdayGenerationError",
    "generate_wednesday_article",
]
