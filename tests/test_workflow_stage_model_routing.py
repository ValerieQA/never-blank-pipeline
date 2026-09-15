"""Issue #236: Visibility Intelligence and Research fell back to the global model.

Both workflows passed only ``NB_OPENAI_CHAT_MODEL``. Every model call on their
paths is stage-routed (``model_article()``, ``model_enrich()``, ...), and with
the stage secrets absent ``_model()`` fell back to the global value, which the
provider rejects with HTTP 400 ``invalid model ID``. Wednesday hit the same
defect in #213 and fixed it by passing the stage secrets.

These tests pin both halves of the fix, statically — no network, no model:

1. the step that runs each entry script passes every stage model secret;
2. every model call reachable from each entry script names its model, so no
   call on these paths can still depend on the global fallback.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(".github/workflows")
STAGE_MODELS = (
    "NB_DISCOVERY_MODEL",
    "NB_SCORING_MODEL",
    "NB_ENRICH_MODEL",
    "NB_ARTICLE_MODEL",
    "NB_SOCIAL_MODEL",
)
LLM_CALLS = {"chat", "chat_json", "chat_qc", "chat_qc_json", "chat_parsed"}

CASES = [
    ("visibility_publish.yml", "scripts/generate_and_publish_visibility.py"),
    ("research_generate_and_publish.yml", "scripts/generate_and_publish.py"),
]


def _entry_step_env(workflow: str, entry: str) -> dict:
    document = yaml.safe_load((WORKFLOWS / workflow).read_text())
    steps = [
        step
        for job in document["jobs"].values()
        for step in job.get("steps", [])
        if f"python {entry}" in step.get("run", "")
    ]
    assert len(steps) == 1, f"{workflow}: expected one step running {entry}"
    return steps[0].get("env", {})


@pytest.mark.parametrize("workflow, entry", CASES)
def test_the_entry_step_passes_every_stage_model_secret(workflow, entry):
    env = _entry_step_env(workflow, entry)

    for name in STAGE_MODELS:
        assert env.get(name) == f"${{{{ secrets.{name} }}}}", f"{workflow}: {name}"


def _module_path(module: str) -> Path | None:
    base = Path(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.exists():
            return candidate
    return None


def _imported_modules(path: Path, tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                package = path.parent.parts[: len(path.parent.parts) - (node.level - 1)]
                base = ".".join(package + tuple((node.module or "").split(".") if node.module else ()))
            else:
                base = node.module or ""
            modules.add(base)
            modules.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def _reachable(entry: str) -> dict[Path, ast.AST]:
    seen: dict[Path, ast.AST] = {}
    pending = [Path(entry)]
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        tree = ast.parse(path.read_text())
        seen[path] = tree
        for module in _imported_modules(path, tree):
            found = _module_path(module)
            if found is not None and found not in seen:
                pending.append(found)
    return seen


@pytest.mark.parametrize("workflow, entry", CASES)
def test_every_reachable_model_call_names_its_model(workflow, entry):
    unrouted = []
    calls = 0
    for path, tree in _reachable(entry).items():
        if path == Path("src/utils/llm_client.py"):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in LLM_CALLS:
                continue
            calls += 1
            model = next((k.value for k in node.keywords if k.arg == "model"), None)
            # A literal None or "" is the global fallback under another name.
            if model is None or (isinstance(model, ast.Constant) and not model.value):
                unrouted.append(f"{path}:{node.lineno} {name}()")

    assert calls, f"{entry}: the reachability walk found no model calls at all"
    assert not unrouted, f"{workflow}: calls fall back to NB_OPENAI_CHAT_MODEL: {unrouted}"
