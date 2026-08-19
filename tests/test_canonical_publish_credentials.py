"""The canonical publish step must receive the credentials it needs (Story #21).

Live run 32259987125 reached `terminal_stage: research`, `disposition: failed`
with *"research provider outcome is failed, not complete"*. The repository held
`NB_EXA_API_KEY`, but the workflow never passed it to the step that runs the
canonical entrypoint, so the Exa adapter failed closed and the Story #11
research gate blocked generation — correctly, yet for a missing credential
rather than for missing evidence.

The gate is not the defect and is not touched here. What these tests hold is
the wiring: every credential the canonical path needs is supplied, supplied as
a secret rather than a literal, and none is quietly dropped later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "research_generate_and_publish.yml"
ENTRYPOINT_FRAGMENT = "scripts/generate_and_publish.py --signal-id"

#: Credentials the canonical Release 1 path cannot complete without.
REQUIRED_CREDENTIALS = (
    "NB_EXA_API_KEY",          # Story #11 research evidence
    "NB_OPENAI_API_KEY",       # generation
    "NB_WIX_API_KEY",          # Story #18 publication
    "NB_WIX_SITE_ID",
    "NB_WIX_POST_OWNER_ID",
    "NB_ZERNIO_API_KEY",       # Story #19 publication
    "NB_ZERNIO_LINKEDIN_ACCOUNT_ID",
    "NB_CLOUDINARY_CLOUD_NAME",  # Story #15 visuals
    "NB_CLOUDINARY_API_KEY",
    "NB_CLOUDINARY_API_SECRET",
)


@pytest.fixture(scope="module")
def publish_step() -> dict:
    spec = yaml.safe_load(WORKFLOW.read_text())
    steps = list(spec["jobs"].values())[0]["steps"]
    for step in steps:
        if ENTRYPOINT_FRAGMENT in str(step.get("run", "")):
            return step
    raise AssertionError("the canonical publish step is no longer in this workflow")


# ── 1–2. the credential is supplied, and supplied as a secret ────────────────

def test_the_research_credential_reaches_the_canonical_step(publish_step):
    """The exact omission that blocked run 32259987125."""

    assert "NB_EXA_API_KEY" in publish_step["env"]


@pytest.mark.parametrize("name", REQUIRED_CREDENTIALS)
def test_every_required_credential_is_supplied_from_secrets(publish_step, name):
    value = publish_step["env"][name]
    assert value == "${{ secrets.%s }}" % name
    # a literal would leak into the workflow file and into every log of it
    assert "${{ secrets." in value
    assert not value.strip().startswith(("sk-", "ghp_", "Bearer"))


# ── 3. nothing was dropped to make room ──────────────────────────────────────

def test_no_unrelated_credential_wiring_was_removed(publish_step):
    """The correction adds one entry; it does not tidy others away."""

    env = publish_step["env"]
    assert len(env) >= 21
    for name in (
        "NB_WIX_BLOG_CATEGORY_ID", "NB_WIX_BLOG_TAG_IDS", "NB_WIX_SITE_BASE_URL",
        "NB_META_FB_PAGE_ID", "NB_META_IG_USER_ID", "NB_TELEGRAM_BOT_TOKEN",
        "NB_THREADS_ACCESS_TOKEN", "NB_OPENAI_CHAT_MODEL",
        "NB_FORCE_REGENERATE_RESEARCH_IMAGES",
    ):
        assert name in env, f"{name} wiring disappeared"


# ── 4. the canonical invocation is untouched ─────────────────────────────────

def test_the_canonical_invocation_is_unchanged(publish_step):
    run = publish_step["run"]
    assert 'python scripts/generate_and_publish.py --signal-id "${{ steps.resolve.outputs.signal_id }}" $FLAGS' in run
    assert '[ "${{ inputs.dry_run }}"       = "true" ] && FLAGS="$FLAGS --dry-run"' in run


# ── 5. the research gate itself is not weakened ──────────────────────────────

def test_the_research_gate_still_blocks_and_the_adapter_still_fails_closed():
    """A credential fix must not become a way past Story #11.

    This asserts the guarantee rather than the wording. The gate's message
    changed under the authorized Issue #125 contract correction — it now
    declines on evidence readiness rather than on the retrieval outcome — and
    pinning that sentence would have made an accepted architectural change
    look like a regression.
    """

    entrypoint = (ROOT / "scripts" / "generate_and_publish.py").read_text()
    assert "research gate blocked generation" in entrypoint

    lifecycle = (ROOT / "src" / "research" / "lifecycle.py").read_text()
    assert "EvidenceReadiness.READY" in lifecycle          # readiness still required
    assert "ResearchGateError" in lifecycle

    adapter = (ROOT / "src" / "research" / "adapters" / "exa.py").read_text()
    assert 'os.getenv("NB_EXA_API_KEY", "")' in adapter
    assert 'raise EnvironmentError("NB_EXA_API_KEY is not set")' in adapter
