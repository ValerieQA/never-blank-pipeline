"""Never Blank product-specific configuration consumers.

Modules in this package describe Never Blank product behaviour.  They are not
universal Engine contracts and must not be imported by generic engine code.
"""

from .wednesday_golden import (
    GoldenReference,
    GoldenReferenceKind,
    WednesdayGoldenProfile,
    load_golden_reference,
)

__all__ = [
    "GoldenReference",
    "GoldenReferenceKind",
    "WednesdayGoldenProfile",
    "load_golden_reference",
]
