"""
Never Blank — Release 1 run-report boundary (Task #27 stub).

R1RunReport is the typed record for the outcome of one complete Release 1
canonical run.  It carries run_id so every post-run consumer (analytics,
audit trail, ops tooling) can correlate back to the originating RunContext
without re-reading logs.

Full evidence provenance, persistent storage, and run-scoped artifact naming
are deferred to Issue #16.  This stub establishes the contract shape so
callers can import and construct it; no storage or transport is implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class R1RunReport:
    """
    Minimal typed outcome record for one Release 1 canonical run.

    Deferred to Issue #16: persistent storage, artifact naming, evidence
    provenance, full analytics result, retry history.
    """

    run_id:         str
    signal_id:      str
    execution_mode: str                         # "dry-run" | "controlled-live"
    results:        Dict[str, Any] = field(default_factory=dict)
    errors:         List[str]      = field(default_factory=list)
    completed:      bool           = False
    notes:          Optional[str]  = None

    def ok(self) -> bool:
        """True when run completed with no errors."""
        return self.completed and not self.errors
