# Audit inputs (mechanical, generated)

Deterministic facts for #233, generated from `main` at `58afe47`. No judgment, no
classification: these are inputs a person or a builder can classify against.

## Files

- `TRACKED_FILE_MANIFEST.csv` — every tracked path (`git ls-files`), 8380 rows,
  with top-level directory, extension and byte size.
- `PY_REACHABILITY.json` — static import-graph reachability for Python.

## Method and its limits

Entrypoints are the scripts a workflow actually invokes: every `python <script>` or
`python -m <module>` in `.github/workflows/*.yml`, 16 in total. Reachability walks
`import` and `from ... import` statements with `ast`, resolving each to a tracked
file. It is a **static** result:

- dynamic imports, plugin lookup and `importlib` are not followed;
- a module reachable only from tests is reported unreachable here, which is not the
  same as dead — `tests/` is excluded from the counts on purpose;
- reachable means "importable from an entrypoint", not "executed"; a module can be
  imported and never called.

Treat every row as evidence to check, not as a verdict.

## What it shows

| Fact | Value |
|---|---|
| Tracked files | 8380 |
| Under `reports/` | 7954 (94.9%) |
| `.json` files | 7932 |
| Everything outside `reports/` | 426 |
| Non-test Python files | 163 |
| Reachable from a workflow entrypoint | 134 |
| Not reachable | 14 (listed in `PY_REACHABILITY.json`) |
