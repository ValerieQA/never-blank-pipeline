# src/controlled_run — centralized fail-closed publication guard and orchestrator.
#
# Story 1 (Policy foundation) scope only: this package currently contains
# ControlledRunPolicy, the dependency-injected policy object described in
# strategy/decision_log.md Часть 24, решение 104(1). Later stories
# (Publication boundary, Artifact Store, Controlled Research, ...) land in
# this package as their own, separately reviewed commits — see decision 103.
