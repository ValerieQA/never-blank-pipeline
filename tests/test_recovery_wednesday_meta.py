"""Issue #247: the one-off Wednesday Meta recovery is bound, inert and narrow.

No network, no model, no provider: publishers are replaced by fakes, and the
evidence fixtures are the exact files run 35102307491 uploaded.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.recovery import publish_saved_wednesday_meta as recovery
from src.publishing import threads as _threads_module
from src.publishing.result import PublishResult, PublishStatus

#: The genuine provider call, captured before any fixture replaces it.
_REAL_PUBLISH_CONTAINER = _threads_module._publish_container

FIXTURE_ROOT = Path("tests/fixtures/recovery_247")
RUN_DIR = FIXTURE_ROOT / recovery.RUN_ID
WORKFLOW = Path(".github/workflows/recovery_wednesday_meta_247.yml")
SCRIPT = Path("scripts/recovery/publish_saved_wednesday_meta.py")


def _saved() -> dict:
    return json.loads((RUN_DIR / "generated.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_threads_network(monkeypatch):
    """Fake Threads publishes go through the module's publish call, like the
    real publisher does, so the recovery's post counter sees them."""
    import src.publishing.threads as threads_module
    counter = iter(range(1, 1000))
    monkeypatch.setattr(threads_module, "_publish_container",
                        lambda token, user_id, container_id: (f"m-{next(counter)}", ""))


def _fake_registry(calls: list, status=PublishStatus.PUBLISHED):
    def make(channel):
        class Fake:
            def publish(self, draft, mode):
                calls.append((channel, draft, mode))
                if channel == "threads" and status is PublishStatus.PUBLISHED:
                    import src.publishing.threads as threads_module
                    for _ in draft.threads_sequence:
                        threads_module._publish_container("tok", "user", "container")
                return PublishResult(platform=channel, status=status,
                                     external_id=f"{channel}-id", url=f"https://x/{channel}")
        return Fake
    return {name: make(name) for name in recovery.PUBLISHABLE}


def _run(tmp_path, *extra, publishers=None, evidence=FIXTURE_ROOT, checked=True):
    out = tmp_path / "result.json"
    if "live" in extra and checked:
        extra = (*extra, "--prior-live-checked")
    # The pytest process has usually loaded the model client through other
    # modules; real isolation is proven in a clean subprocess below.
    code = recovery.main(
        ["--evidence-dir", str(evidence), "--result-out", str(out), *extra],
        publishers=publishers, forbidden_modules=(),
    )
    return code, (json.loads(out.read_text()) if out.exists() else None)


# ── evidence binding ────────────────────────────────────────────────────────


def test_the_exact_saved_evidence_verifies():
    generated, asset = recovery.load_verified_evidence(RUN_DIR)

    assert generated["run_id"] == recovery.RUN_ID
    assert generated["signal_id"] == recovery.SIGNAL_ID
    assert asset == recovery.EXPECTED_WIX_ASSET


def test_a_changed_payload_fails_closed_before_any_publisher(tmp_path):
    copy = tmp_path / "evidence" / recovery.RUN_ID
    shutil.copytree(RUN_DIR, copy)
    saved = _saved()
    saved["facebook_post"] += " edited"
    (copy / "generated.json").write_text(json.dumps(saved), encoding="utf-8")
    calls: list = []

    code, record = _run(tmp_path, "--mode", "live",
                        publishers=_fake_registry(calls), evidence=tmp_path / "evidence")

    assert code == 3
    assert calls == []
    assert record is None


def test_missing_evidence_fails_closed(tmp_path):
    calls: list = []
    code, _ = _run(tmp_path, "--mode", "live",
                   publishers=_fake_registry(calls), evidence=tmp_path / "nothing")

    assert code == 3
    assert calls == []


# ── payloads are passed through untouched ───────────────────────────────────


def test_the_draft_carries_the_saved_text_byte_for_byte():
    generated, asset = recovery.load_verified_evidence(RUN_DIR)
    draft = recovery.build_draft(generated, asset)
    saved = _saved()

    assert draft.facebook_text == saved["facebook_post"]
    assert draft.instagram_text == saved["instagram_caption"]
    assert draft.threads_sequence == saved["threads_sequence"]


def test_only_instagram_receives_an_image_and_it_is_the_runs_wix_asset():
    generated, asset = recovery.load_verified_evidence(RUN_DIR)
    draft = recovery.build_draft(generated, asset)

    assert draft.image_for("instagram") == recovery.EXPECTED_WIX_ASSET
    assert draft.image_for("facebook") is None
    assert draft.image_for("threads") is None


def test_no_wix_linkedin_or_telegram_payload_reaches_the_draft():
    generated, asset = recovery.load_verified_evidence(RUN_DIR)
    draft = recovery.build_draft(generated, asset)

    assert draft.blog_body == draft.linkedin_text == draft.telegram_text == ""


# ── channel scope ───────────────────────────────────────────────────────────


def test_live_publishes_exactly_the_three_channels_in_order(tmp_path):
    calls: list = []
    code, record = _run(tmp_path, "--mode", "live", publishers=_fake_registry(calls))

    assert code == 0
    assert [c for c, _, _ in calls] == ["facebook", "instagram", "threads"]
    assert {mode for _, _, mode in calls} == {"live"}
    assert record["results"]["telegram"]["status"] == "SKIPPED"
    assert "truncated" in record["results"]["telegram"]["error_message"]
    assert record["results"]["wix"]["status"] == "NOT_ATTEMPTED"
    assert record["results"]["linkedin"]["status"] == "NOT_ATTEMPTED"
    assert record["model_calls"] == 0
    assert record["signal_consumption_changed"] is False


def test_dry_run_is_the_default(tmp_path):
    calls: list = []
    code, record = _run(tmp_path, publishers=_fake_registry(calls, PublishStatus.SKIPPED))

    assert code == 0
    assert {mode for _, _, mode in calls} == {"dry_run"}
    assert record["mode"] == "dry_run"


def test_a_partial_retry_touches_only_the_named_channel(tmp_path):
    calls: list = []
    code, _ = _run(tmp_path, "--mode", "live", "--channels", "threads",
                   publishers=_fake_registry(calls))

    assert code == 0
    assert [c for c, _, _ in calls] == ["threads"]


@pytest.mark.parametrize("channels", ["telegram", "wix", "linkedin",
                                      "facebook,facebook", "", "facebook,wix"])
def test_any_channel_outside_the_recovery_is_refused(tmp_path, channels):
    calls: list = []
    code, _ = _run(tmp_path, "--mode", "live", "--channels", channels,
                   publishers=_fake_registry(calls))

    assert code == 2
    assert calls == []


def test_a_failed_live_channel_fails_the_run_without_stopping_the_others(tmp_path):
    calls: list = []
    code, record = _run(tmp_path, "--mode", "live",
                        publishers=_fake_registry(calls, PublishStatus.FAILED))

    assert code == 1
    assert len(calls) == 3
    assert record["results"]["facebook"]["status"] == "FAILED"


# ── no model, no consumption ────────────────────────────────────────────────


def test_loading_the_recovery_never_loads_the_model_client():
    probe = (
        "import sys, runpy; sys.argv=['x','--help']\n"
        "try:\n"
        f"    runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n"
        "except SystemExit:\n"
        "    pass\n"
        "print('src.utils.llm_client' in sys.modules, 'openai' in sys.modules)\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)

    assert out.stdout.strip().splitlines()[-1] == "False False"


def test_the_script_never_touches_consumption_or_other_publishers():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = {
        (node.module or "") + "." + alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
         for alias in node.names}
    docstring = ast.get_docstring(tree, clean=False)
    strings = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value != docstring
    }

    assert {name for name in imported if name.startswith("src.")} == {
        "src.publishing.base.DraftPackage",
        "src.publishing.facebook.FacebookPublisher",
        "src.publishing.instagram.InstagramPublisher",
        "src.publishing.result.PublishStatus",
        "src.publishing.threads.ThreadsPublisher",
        "src.publishing.threads",  # the counting wrapper around its publish call
    }
    assert not any("published_signal_ids" in s for s in strings)
    assert not any(name.startswith("scripts.") for name in imported)


# ── the workflow ────────────────────────────────────────────────────────────


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_is_manual_only():
    triggers = _workflow()[True]  # PyYAML reads the `on:` key as True

    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["mode"]["default"] == "dry_run"


def test_the_workflow_cannot_write_to_the_repository():
    workflow = _workflow()
    text = WORKFLOW.read_text(encoding="utf-8")

    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    assert "git push" not in text and "git commit" not in text


def test_the_workflow_downloads_the_bound_artifact():
    steps = _workflow()["jobs"]["recover"]["steps"]
    download = next(s for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact"))

    assert download["with"]["run-id"] == 35102307491
    assert download["with"]["name"] == "wednesday-run-evidence-f9c2f40f85d82da3"


def test_only_meta_credentials_exist_in_the_publish_step():
    steps = _workflow()["jobs"]["recover"]["steps"]
    publish = next(s for s in steps if s.get("name") == "Publish saved payloads")
    secrets = {k for k, v in publish["env"].items() if "secrets." in str(v)}

    assert secrets == {"NB_META_FB_PAGE_ID", "NB_META_FB_PAGE_TOKEN",
                       "NB_META_IG_USER_ID", "NB_THREADS_ACCESS_TOKEN"}
    text = WORKFLOW.read_text(encoding="utf-8")
    for absent in ("NB_OPENAI", "NB_WIX", "NB_ZERNIO", "NB_TELEGRAM"):
        assert absent not in text, absent


# ── review findings (#249): partial Threads, replay, interruption ───────────


class _ThreadsHTTP:
    """Stand-in for the Threads Graph API, driven through the real publisher."""

    def __init__(self, fail_publish_at: int | None = None):
        self.fail_publish_at = fail_publish_at
        self.published: list[str] = []
        self.containers = 0

    def fetch(self, url, method="GET", headers=None, body=None):
        if url.endswith("/me?fields=id&access_token=tok") or "/me?" in url:
            return 200, {"id": "user-1"}, b""
        if url.endswith("/threads"):
            self.containers += 1
            return 200, {"id": f"container-{self.containers}"}, b""
        if url.endswith("/threads_publish"):
            index = len(self.published)
            if self.fail_publish_at is not None and index == self.fail_publish_at:
                return 500, {"error": {"message": "boom"}}, b""
            media = f"media-{index + 1}"
            self.published.append(media)
            return 200, {"id": media}, b""
        raise AssertionError(f"unexpected request {url}")


def _real_threads(monkeypatch, http: _ThreadsHTTP):
    import src.publishing.threads as threads_module
    monkeypatch.setattr(threads_module, "_publish_container", _REAL_PUBLISH_CONTAINER)
    monkeypatch.setattr(threads_module, "_fetch", http.fetch)
    monkeypatch.setattr(threads_module.time, "sleep", lambda _s: None)
    monkeypatch.setenv("NB_THREADS_ACCESS_TOKEN", "tok")
    return {"threads": threads_module.ThreadsPublisher}


def test_a_partial_real_thread_is_reported_partial_not_published(tmp_path, monkeypatch):
    http = _ThreadsHTTP(fail_publish_at=1)
    code, record = _run(tmp_path, "--mode", "live", "--channels", "threads",
                        publishers=_real_threads(monkeypatch, http))

    threads = record["results"]["threads"]
    assert http.published == ["media-1"]
    assert threads["status"] == "PARTIAL"
    assert threads["posted_ids"] == ["media-1"]
    assert threads["expected_posts"] == 4
    assert code == 1


def test_a_complete_real_thread_is_published_with_every_post(tmp_path, monkeypatch):
    http = _ThreadsHTTP()
    code, record = _run(tmp_path, "--mode", "live", "--channels", "threads",
                        publishers=_real_threads(monkeypatch, http))

    threads = record["results"]["threads"]
    assert code == 0
    assert threads["status"] == "PUBLISHED"
    assert threads["posted_ids"] == ["media-1", "media-2", "media-3", "media-4"]


def test_the_counting_wrapper_is_removed_after_the_call(tmp_path, monkeypatch):
    import src.publishing.threads as threads_module
    publishers = _real_threads(monkeypatch, _ThreadsHTTP())
    before = threads_module._publish_container
    _run(tmp_path, "--mode", "live", "--channels", "threads", publishers=publishers)

    assert threads_module._publish_container is before


def test_live_without_the_single_shot_check_is_refused(tmp_path):
    calls: list = []
    code, record = _run(tmp_path, "--mode", "live", publishers=_fake_registry(calls), checked=False)

    assert code == 5
    assert calls == []
    assert record is None


def test_an_interrupted_call_is_recorded_as_an_unknown_outcome(tmp_path):
    calls: list = []

    class Exploding:
        def publish(self, draft, mode):
            calls.append("instagram")
            raise TimeoutError("socket timed out after the request was sent")

    registry = _fake_registry(calls)
    registry["instagram"] = Exploding
    code, record = _run(tmp_path, "--mode", "live", publishers=registry)

    assert code == 1
    assert record["results"]["instagram"]["status"] == "UNKNOWN_OUTCOME"
    assert record["results"]["facebook"]["status"] == "PUBLISHED"


def test_the_record_says_attempting_while_a_call_is_in_flight(tmp_path):
    seen: list = []
    out = tmp_path / "result.json"

    class Watching:
        def publish(self, draft, mode):
            seen.append(json.loads(out.read_text())["results"]["facebook"]["status"])
            return PublishResult(platform="facebook", status=PublishStatus.PUBLISHED)

    registry = _fake_registry([])
    registry["facebook"] = Watching
    _run(tmp_path, "--mode", "live", "--channels", "facebook", publishers=registry)

    assert seen == ["ATTEMPTING"]


def test_a_full_run_changes_no_consumption_state(tmp_path):
    marker = Path("data/research/published_signal_ids.txt")
    index = Path("strategy/published_content_index.jsonl")
    before = (marker.read_bytes(), index.read_bytes())

    code, _ = _run(tmp_path, "--mode", "live", publishers=_fake_registry([]))

    assert code == 0
    assert (marker.read_bytes(), index.read_bytes()) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["result.json"]


def test_a_real_dry_run_never_loads_the_model_client(tmp_path):
    probe = (
        "import sys, runpy\n"
        f"sys.argv=['x','--evidence-dir',{str(FIXTURE_ROOT)!r},'--mode','dry_run',"
        f"'--result-out',{str(tmp_path / 'r.json')!r}]\n"
        "try:\n"
        f"    runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n"
        "except SystemExit as exc:\n"
        "    code = exc.code\n"
        "print('CODE', code, 'src.utils.llm_client' in sys.modules, 'openai' in sys.modules)\n"
    )
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("NB_")}
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         check=True, env=env)
    last = out.stdout.strip().splitlines()[-1].split()

    # No credentials here, so the publishers report missing env and the run
    # exits 1 — but the guard ran for real and nothing loaded a model client.
    assert last[0] == "CODE" and last[1] in {"0", "1"}
    assert last[2:] == ["False", "False"]
    assert json.loads((tmp_path / "r.json").read_text())["mode"] == "dry_run"


def test_the_workflow_checks_history_before_publishing():
    workflow = _workflow()
    steps = workflow["jobs"]["recover"]["steps"]
    names = [s.get("name") for s in steps]
    check = steps[names.index("Refuse if an earlier live recovery reached publication")]
    publish = steps[names.index("Publish saved payloads")]

    assert workflow["run-name"] == "Recovery #247 (${{ inputs.mode }})"
    assert names.index(check["name"]) < names.index("Publish saved payloads")
    assert check["if"] == "inputs.mode == 'live'"
    assert "scripts/recovery/check_prior_live_runs.py" in check["run"]
    assert '--current-run-id "${{ github.run_id }}"' in check["run"]
    assert '$([ "$MODE" = live ] && echo --prior-live-checked)' in publish["run"]
    assert "ledger" not in WORKFLOW.read_text(encoding="utf-8")
    upload = next(s for s in steps if s.get("name") == "Preserve recovery result")
    assert upload["if"] == "always()"


def test_a_rerun_attempt_can_never_go_live():
    guard = _workflow()["jobs"]["recover"]["steps"][0]

    assert "github.run_attempt != '1'" in guard["if"]
    assert "inputs.confirm != '35102307491'" in guard["if"]
    assert guard["if"].startswith("inputs.mode == 'live' && (")
    assert "exit 1" in guard["run"]


# ── the single-shot history check ───────────────────────────────────────────

from scripts.recovery import check_prior_live_runs as history  # noqa: E402

REPO = "ValerieQA/never-blank-pipeline"
CURRENT = "900"


def _api(runs: list[dict], jobs: dict[str, list[dict]], fail: set[str] = frozenset()):
    """A fake `gh api --paginate --slurp`: a list of pages per path."""
    def fetch(path: str):
        if any(marker in path for marker in fail):
            raise history.LedgerError(f"HTTP 502 for {path}")
        if "/workflows/" in path:
            return [{"total_count": len(runs), "workflow_runs": runs}]
        run_id = path.split("/runs/")[1].split("/")[0]
        return [{"total_count": 1, "jobs": jobs.get(run_id, [])}]
    return fetch


def _run_row(run_id, mode):
    return {"id": int(run_id), "display_title": f"Recovery #247 ({mode})"}


def _job(publish_status, publish_conclusion):
    return [{"steps": [
        {"name": "Refuse an unconfirmed or repeated live run", "status": "completed", "conclusion": "skipped"},
        {"name": "Publish saved payloads", "status": publish_status, "conclusion": publish_conclusion},
    ]}]


def _check(fetch):
    return history.main(["--repo", REPO, "--current-run-id", CURRENT], fetch=fetch)


def test_no_earlier_runs_allows_the_first_live_run():
    assert _check(_api([_run_row(CURRENT, "live")], {})) == 0


def test_dry_runs_never_block():
    runs = [_run_row("1", "dry_run"), _run_row(CURRENT, "live")]
    assert _check(_api(runs, {"1": _job("completed", "success")})) == 0


@pytest.mark.parametrize("status, conclusion", [
    ("completed", "success"), ("completed", "failure"), ("completed", "cancelled"),
    ("in_progress", None), ("queued", None),
])
def test_an_earlier_live_publish_step_that_was_not_skipped_blocks(status, conclusion):
    runs = [_run_row("1", "live"), _run_row(CURRENT, "live")]
    assert _check(_api(runs, {"1": _job(status, conclusion)})) == 1


def test_an_earlier_live_run_stopped_before_publishing_does_not_block():
    runs = [_run_row("1", "live"), _run_row(CURRENT, "live")]
    assert _check(_api(runs, {"1": _job("completed", "skipped")})) == 0


def test_an_earlier_live_run_that_never_got_a_job_does_not_block():
    runs = [_run_row("1", "live"), _run_row(CURRENT, "live")]
    assert _check(_api(runs, {"1": []})) == 0


def test_the_current_run_is_not_its_own_blocker():
    runs = [_run_row(CURRENT, "live")]
    assert _check(_api(runs, {CURRENT: _job("in_progress", None)})) == 0


def test_an_unclassifiable_run_blocks():
    runs = [{"id": 1, "display_title": "Recovery — Wednesday"}, _run_row(CURRENT, "live")]
    assert _check(_api(runs, {})) == 1


@pytest.mark.parametrize("broken", ["/workflows/", "/runs/1/"])
def test_an_api_failure_refuses_to_publish(broken):
    runs = [_run_row("1", "live"), _run_row(CURRENT, "live")]
    assert _check(_api(runs, {"1": _job("completed", "skipped")}, fail={broken})) == 2


@pytest.mark.parametrize("payload", [{}, [{"unexpected": []}], "nonsense", [[]]])
def test_an_unexpected_response_shape_refuses_to_publish(payload):
    assert _check(lambda path: payload) == 2


def test_a_job_without_readable_steps_refuses_to_publish():
    runs = [_run_row("1", "live"), _run_row(CURRENT, "live")]
    assert _check(_api(runs, {"1": [{"name": "recover"}]})) == 2


def test_every_page_of_runs_is_read():
    pages = [
        {"workflow_runs": [_run_row(CURRENT, "live")]},
        {"workflow_runs": [_run_row("1", "live")]},
    ]

    def fetch(path):
        if "/workflows/" in path:
            return pages
        return [{"jobs": _job("completed", "success")}]

    assert _check(fetch) == 1


def test_the_real_fetcher_asks_github_for_every_page(monkeypatch):
    seen = {}

    class Done:
        returncode = 0
        stdout = "[]"
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return Done()

    monkeypatch.setattr(history.subprocess, "run", fake_run)
    history.gh_api("repos/x/y")

    assert seen["cmd"] == ["gh", "api", "--paginate", "--slurp", "repos/x/y"]
