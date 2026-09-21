"""The one canonical Editorial Core: stages S-00 … S-13 (Issue #290, slice SL-1).

Everything in this package is editorial-core code, and the CE-1 placement rule
(``scripts/ci/check_ce1_placement.py``) is enforced over every module in it:
no module here may read the weekday or the clock, and none may select stages
by destination. Weekday, rubric and lens are configuration and scheduling
inputs handed to the engine; destination affects strategy, adaptation,
validation and publication capability, and lives in destination knowledge
(``K-DST-*``), in adaptation (S-10), in check records and in the publishers —
never in a pipeline of its own.

Publication (S-14) and observation (S-15) are outside the core and outside
this package: they are where destination capability legitimately decides what
happens.
"""
