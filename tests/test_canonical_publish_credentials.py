"""The canonical publish step must receive its credentials safely (Story #21).

Live run 32259987125 reached `terminal_stage: research`, `disposition: failed`
with *"research provider outcome is failed, not complete"*. The repository held
`NB_EXA_API_KEY`, but the workflow never passed it to the step that runs the
canonical entrypoint, so the Exa adapter failed closed and the Story #11
research gate blocked generation — correctly, yet for a missing credential
rather than for missing evidence.

The gate is not the defect and is not touched here. What survives from that
investigation is two things, and #326 separates them:

* **generic.** Whatever credentials a publishing workflow supplies, it supplies
  them from GitHub secrets and never as literals. Parametrized over every
  workflow that can publish, because leaking a key is not one workflow's risk;
* **per path, and deliberately not generalized here.** *Which* credentials a
  given path needs differs by design. Monday needs `NB_EXA_API_KEY`; Wednesday
  must **not** have it (#213 — it retrieves through the restored July path, and
  ``tests/test_wednesday_live_fixes.py`` asserts no Exa secret reaches it at
  all). Monday's own required set lives in
  ``tests/test_monday_stream.py::test_the_execution_step_keeps_the_credentials_the_r1_path_needs``
  and its secret form in
  ``tests/test_wednesday_live_fixes.py::test_monday_still_receives_its_own_configuration_unchanged``.
  Asserting one shared list here would state a requirement no single path has.

Two assertions from the deleted `research_generate_and_publish.yml` were **not**
carried over, because they described that workflow rather than a safety
property:

* ``test_no_unrelated_credential_wiring_was_removed`` — it required at least 21
  env entries including `NB_META_*`, `NB_THREADS_*` and `NB_TELEGRAM_*`. That
  workflow was the legacy six-channel publisher. The surviving R1 paths publish
  to Wix and LinkedIn only, and
  ``tests/test_monday_stream.py::test_the_required_publish_secrets_are_wix_and_linkedin_only``
  asserts those very names are **absent** from Monday. Carrying it over would
  have asserted the opposite of a live invariant;
* the exact legacy invocation line, which is one workflow's shell rather than a
  publication guarantee.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.publishing_workflows import (
    entrypoint_step,
    job_steps,
    publishing_workflows,
)

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]

WORKFLOWS = publishing_workflows()

#: What a credential name looks like. Narrow on purpose: these are the prefixes
#: this repository's secrets use, so a non-credential setting passed to the step
#: is not dragged into a rule about secrets.
_CREDENTIAL = re.compile(
    r"^NB_.*(API_KEY|TOKEN|SECRET|ACCOUNT_ID|SITE_ID|OWNER_ID|PAGE_ID|USER_ID"
    r"|CHANNEL_ID|CLOUD_NAME)$"
)

#: The shape of a literal somebody pasted in by mistake.
_LITERAL_PREFIXES = ("sk-", "ghp_", "Bearer", "eyJ", "xox")


def _credentials(workflow: str) -> dict[str, str]:
    env = entrypoint_step(job_steps(workflow)).get("env", {})
    return {
        name: str(value)
        for name, value in env.items()
        if _CREDENTIAL.match(name)
    }


# ── 1. every credential a path supplies comes from a secret ──────────────────


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_the_publish_step_supplies_credentials_at_all(workflow):
    """Anti-vacuous: the rule below must have something to be about.

    A publishing workflow that passed no credential would make every
    `assert` in the next test pass over an empty dict — and it could not
    publish anything either, so this is a real failure, not a tautology.
    """

    assert _credentials(workflow), (
        f"{workflow} runs the canonical entrypoint and passes it no credential"
    )


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_every_supplied_credential_comes_from_github_secrets(workflow):
    """The invariant the deleted workflow actually held, now held for all.

    A literal would leak into the workflow file, into the repository history,
    and into every log that echoes the step. So each credential's value must be
    exactly its own ``secrets`` reference — not merely contain one, which a
    concatenation could.
    """

    for name, value in _credentials(workflow).items():
        assert value == "${{ secrets.%s }}" % name, f"{workflow}: {name} = {value!r}"
        assert not value.strip().startswith(_LITERAL_PREFIXES)


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_no_credential_is_hard_coded_anywhere_in_the_workflow(workflow):
    """And not only in the step that runs the entrypoint.

    The preflight steps that check a secret is set receive the same values, so
    a literal pasted into one of those would leak just as completely.
    """

    text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")

    for line in text.splitlines():
        if "NB_" not in line or "secrets." in line or line.strip().startswith("#"):
            continue
        for prefix in _LITERAL_PREFIXES:
            assert prefix not in line, f"{workflow}: {line.strip()[:70]}"


# ── 2. the research gate itself is not weakened ──────────────────────────────


def test_the_research_gate_still_blocks_and_the_adapter_still_fails_closed():
    """A credential fix must not become a way past Story #11.

    This asserts the guarantee rather than the wording. The gate's message
    changed under the authorized Issue #125 contract correction — it now
    declines on evidence readiness rather than on the retrieval outcome — and
    pinning that sentence would have made an accepted architectural change
    look like a regression.

    No workflow is its subject, so #326 leaves it exactly as it was.
    """

    entrypoint = (ROOT / "scripts" / "generate_and_publish.py").read_text()
    assert "research gate blocked generation" in entrypoint

    lifecycle = (ROOT / "src" / "research" / "lifecycle.py").read_text()
    assert "EvidenceReadiness.READY" in lifecycle          # readiness still required
    assert "ResearchGateError" in lifecycle

    adapter = (ROOT / "src" / "research" / "adapters" / "exa.py").read_text()
    assert 'os.getenv("NB_EXA_API_KEY", "")' in adapter
    assert 'raise EnvironmentError("NB_EXA_API_KEY is not set")' in adapter
