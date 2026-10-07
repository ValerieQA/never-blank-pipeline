"""Fail-closed provider prohibition for ordinary tests (#172, widened 2026-10-06).

Ordinary unit/integration tests must never be able to make a real external
call merely because the developer's shell happens to export a credential.
Before this guard, CI was safe only because the test workflow happened not to
pass the key — an accident of configuration, not a guarantee.

#172 closed that for OpenAI. The cost-discipline decision of 2026-10-06 closed
it for the rest: the same sentence was still true of `NB_EXA_API_KEY` (billed
retrieval), Cloudinary, and the publishing credentials, where an accident is
not a refundable amount of money but a post the world can see. The mechanism
is unchanged — one list of variables got longer. See
:data:`_PROVIDER_KEY_VARS`.

The guard is one autouse fixture. A test may see real provider credentials
only when TWO independent explicit conditions hold together:

1. the test carries ``@pytest.mark.live_api`` — the per-test authorization,
   greppable and reviewable at the test site; and
2. the pytest run carries the run-level authorization
   ``NB_ALLOW_LIVE_API_TESTS=1`` — exactly the string ``"1"``, nothing
   else. ``true``, ``yes``, ``11`` and every other truthy-looking value do
   not authorize anything: an ambiguous authorization is no authorization.

Either condition alone blocks: a marked test in an ordinary run is stripped
like any other test, and an authorized run strips every unmarked test. For
every blocked test the OpenAI key variables are removed and the shared
client cache is cleared, so an accidental real client construction fails
visibly at ``_get_client()`` (``EnvironmentError: NB_OPENAI_API_KEY is not
set``) before any transport — and a client cached by an authorized test can
never be reused past its authorization. Tests that inject fakes, patch the
client, or set their own sentinel key values are unaffected: test-level
setup runs after this fixture.

This module is loaded only by pytest; production execution is untouched.
"""

from __future__ import annotations

import os
import sys

import pytest

from src.utils import llm_client

#: Every variable that could authenticate a billed call or an outward-facing
#: one. The bare OPENAI_API_KEY is included because the SDK reads it as a
#: default when no explicit key is passed.
#:
#: Extended beyond OpenAI by the cost-discipline decision of 2026-10-06. Until
#: then this tuple held two variables, and the suite was safe from every other
#: provider only because `pr_tests.yml` passes no secrets to the test job —
#: which is exactly the condition the module docstring above diagnoses as "an
#: accident of configuration, not a guarantee". A developer with
#: `NB_EXA_API_KEY` exported, the normal state for anyone who has run the
#: canonical path locally, could make real billed Exa calls by running the
#: tests.
#:
#: Two kinds, and the second is the one money does not measure:
#:
#:   billed    — a call that costs money: text generation, retrieval, image
#:               hosting.
#:   outward   — a call the world can see: a published post, a sent message.
#:               An accident here cannot be refunded.
#:
#: Every transport behind these reads its key at construction and fails closed
#: without it — `RequestsExaTransport` raises
#: `EnvironmentError("NB_EXA_API_KEY is not set")` — so removing the variable
#: turns a silent external call into a visible refusal, which is how the
#: OpenAI half has always worked.
_PROVIDER_KEY_VARS = (
    # billed · text
    "NB_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    # billed · retrieval
    "NB_EXA_API_KEY",
    # billed · image hosting
    "NB_CLOUDINARY_API_KEY",
    "NB_CLOUDINARY_API_SECRET",
    # outward · publishing
    "NB_WIX_API_KEY",
    "NB_ZERNIO_API_KEY",
    "NB_META_FB_PAGE_TOKEN",
    "NB_THREADS_ACCESS_TOKEN",
    "NB_TELEGRAM_BOT_TOKEN",
)

#: Run-level live authorization: exactly this variable, exactly "1".
_LIVE_OPT_IN_VAR = "NB_ALLOW_LIVE_API_TESTS"
_LIVE_OPT_IN_VALUE = "1"


def _run_authorizes_live_api() -> bool:
    """Strict run-level check: only the canonical value authorizes."""
    return os.environ.get(_LIVE_OPT_IN_VAR) == _LIVE_OPT_IN_VALUE


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_api: this test is deliberately allowed to see real provider "
        "credentials and may make billed or outward-facing calls — but only "
        "when the run itself is also authorized with "
        "NB_ALLOW_LIVE_API_TESTS=1. Either condition alone blocks; ordinary "
        "tests always have the credential variables stripped and fail closed "
        "at client or transport construction.",
    )


@pytest.fixture(autouse=True)
def _no_billed_or_outward_provider_calls(request, monkeypatch):
    """Strip provider credentials unless BOTH live authorizations hold.

    One fixture, one authorization model, one list of variables. The
    cost-discipline decision widened the list and changed nothing else: a
    second fixture would mean two places that can disagree about what
    "authorized" means.
    """

    if (
        request.node.get_closest_marker("live_api")
        and _run_authorizes_live_api()
    ):
        # Both independent authorizations present: the environment is left
        # exactly as the runner provided it.
        yield
        return

    for var in _PROVIDER_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    # A client cached by an earlier authorized test must never be reusable
    # past its authorization: the cache is cleared for every blocked test.
    # monkeypatch restores the previous value afterwards.
    monkeypatch.setattr(llm_client, "_client", None)
    yield


#: Every module that writes package or run records under one root. Each reads
#: NB_PACKAGES_DIR at import; a module already imported is redirected per test.
_PACKAGE_ROOT_MODULES = (
    "scripts.generate_and_publish",
    "scripts.generate_and_publish_visibility",
    "scripts.research.prepare_content",
    "scripts.research.publish_packages",
)


@pytest.fixture(autouse=True)
def _run_artifacts_stay_out_of_the_tracked_tree(tmp_path_factory, monkeypatch):
    """No test writes run records into ``reports/`` (#233 F-02).

    ``scripts/generate_and_publish.py`` used to hold the run-artifact root as a
    fixed relative path, so every test that drove the entrypoint without
    redirecting it wrote real directories into the repository — 7,796 tracked
    files, arriving on unrelated commits. The root now reads ``NB_PACKAGES_DIR``,
    and this fixture points it at a temporary directory for the whole suite.

    A test that redirects the root itself is unaffected: its own patch runs
    after this fixture and wins.
    """

    root = tmp_path_factory.mktemp("run-artifacts")
    monkeypatch.setenv("NB_PACKAGES_DIR", str(root))
    for name in _PACKAGE_ROOT_MODULES:
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "PACKAGES_DIR"):
            monkeypatch.setattr(module, "PACKAGES_DIR", root)
    yield


@pytest.fixture(autouse=True)
def _publication_markers_stay_out_of_the_tracked_tree(tmp_path_factory, monkeypatch):
    """No test writes publication idempotency evidence into the tracked tree.

    The publication marker store (NB-00a) is committed on purpose — losing a
    marker could cause a double publication — so an unredirected test run would
    leave real markers in ``data/editorial/publication_markers/`` and, worse,
    let one test's marker suppress another test's publication. Each test gets
    its own root, already created: a missing root is itself an answer (the
    authority is unavailable, so nothing publishes), which makes creating it
    here part of the redirection rather than an afterthought.

    A test that redirects the root itself is unaffected: its own patch runs
    after this fixture and wins.
    """

    monkeypatch.setenv(
        "NB_PUBLICATION_MARKERS_DIR", str(tmp_path_factory.mktemp("markers"))
    )
    yield


@pytest.fixture(autouse=True)
def _the_durable_ledger_stays_out_of_the_tracked_tree(tmp_path_factory, monkeypatch):
    """No test writes a durable learning record into the tracked tree.

    The ledger (NB-01d) is committed on purpose — the indicators a RunSummary
    carries must outlive the 90-day run workspace — so ``data/editorial/runs/``
    is deliberately un-ignored, and an unredirected test run leaves real
    RunSummary records there. ``run_golden_engine`` redirects the workspace it
    is handed a ``runs_root`` for, but the ledger has its own root and takes no
    default from it: two records for a fixture signal reached PR #372 that way.
    ``src/run/ledger.py`` names this variable for exactly this purpose.

    A test that redirects the root itself is unaffected: its own patch runs
    after this fixture and wins.
    """

    monkeypatch.setenv(
        "NB_EDITORIAL_LEDGER_DIR", str(tmp_path_factory.mktemp("ledger"))
    )
    yield


@pytest.fixture(autouse=True)
def _the_test_process_is_not_a_publishing_runner(monkeypatch):
    """No suite inherits cross-runner arbitration from the ambient environment.

    ``record_intent`` requires a claim both runners can see when it detects a
    hosted runner (``GITHUB_ACTIONS``), and CI runs the tests on exactly such a
    runner. Without this, every suite that drives a real publishing path in a
    ``tmp_path`` would fail closed in CI and pass locally — the same code
    behaving differently depending on where it runs, which is the one thing a
    test must never do.

    A test process is not a publishing runner. The suite that proves the
    cross-runner arbitration builds its runners explicitly
    (``tests/test_287_marker_durability.py``) and opts back in with
    ``require_shared_claim=True``, so it is unaffected by this.
    """

    monkeypatch.setenv("NB_SHARED_CLAIM", "0")
    yield
