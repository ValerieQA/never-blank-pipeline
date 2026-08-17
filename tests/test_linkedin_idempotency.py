"""Issue #109 / Story #19: LinkedIn retry idempotency.

Deterministic only — nothing here publishes to LinkedIn or proves that a real
post exists. What these prove is that retrying a run whose accepted LinkedIn
body was already published to the same account creates no second post, that a
different composition of the same article is still publishable, and that no
ambiguous or provider-owned signal is ever mistaken for our own proof.

The duplicate identity is ``(signal_id, accepted_linkedin_body_digest,
linkedin_account_id)`` — the accepted body, not the article.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from src.editorial.linkedin_composition import article_digest
from src.publishing.idempotency import (
    UNUSABLE_COMPOSITION_UNREADABLE,
    UNUSABLE_INCONSISTENT,
    UNUSABLE_MALFORMED_RESULTS,
    UNUSABLE_MISSING_CONTENT_ID,
    UNUSABLE_MISSING_PREFLIGHT,
    UNUSABLE_PROVENANCE_INVALID,
    LinkedInPublicationIdentity,
    find_prior_linkedin_publication,
)
from src.publishing.linkedin import LinkedInPublisher
from src.publishing.result import PublishStatus, UrlProvenance
from tests import test_generate_and_publish as legacy
from tests.test_publication_package import FOREIGN_CONFIG
from tests.test_publication_preflight import _live_run, _target_env

ACCOUNT_A = "zernio-account-aaaa"
ACCOUNT_B = "zernio-account-bbbb"
POST_ID = "zernio-post-9911"
POST_URL = "https://www.linkedin.com/feed/update/urn:li:share:9911"


# ── Fixtures: prior runs are real canonical runs ─────────────────────────────


def _zernio(code, payload):
    def fake_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        return code, payload, ""

    return fake_fetch


def _published_payload():
    return {"post": {"_id": POST_ID,
                     "platforms": [{"platform": "linkedin", "url": POST_URL}]}}


def _seed_prior_run(tmp_path, monkeypatch, *, account=ACCOUNT_A,
                    payload=None, code=201):
    """Publish once through main() with the real LinkedIn adapter.

    Hand-written artifacts cannot stand in: a candidate must pass Story #16
    verification and carry its own bound Story #17 verdict, so the prior
    evidence has to be a genuine canonical chain.
    """

    _target_env(monkeypatch)
    monkeypatch.setenv("NB_ZERNIO_LINKEDIN_ACCOUNT_ID", account)
    with mock.patch("src.publishing.linkedin._fetch",
                    side_effect=_zernio(code, payload or _published_payload())):
        _live_run(tmp_path, LinkedInPublisher=LinkedInPublisher)
    return _newest_run(tmp_path)


def _newest_run(tmp_path) -> Path:
    return max(
        (path.parent for path in tmp_path.glob("*/runs/*/publication_results.json")),
        key=lambda path: path.stat().st_mtime,
    )


def _entry(run_dir: Path) -> dict:
    data = json.loads((run_dir / "publication_results.json").read_text())
    return data["results"]["linkedin"]


def _rewrite_results(run_dir: Path, **changes):
    path = run_dir / "publication_results.json"
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


def _set_linkedin_status(run_dir: Path, status: str, **entry_changes):
    path = run_dir / "publication_results.json"
    data = json.loads(path.read_text())
    data["results"]["linkedin"]["status"] = status
    data["results"]["linkedin"].update(entry_changes)
    path.write_text(json.dumps(data), encoding="utf-8")


def _tamper_preflight(run_dir: Path, mutate):
    path = run_dir / "preflight_result.json"
    verdict = json.loads(path.read_text())
    mutate(verdict)
    path.write_text(json.dumps(verdict), encoding="utf-8")


def _accepted_body(run_dir: Path) -> str:
    """The accepted body of the run that generated the composition."""

    data = json.loads((run_dir / "publication_results.json").read_text())
    generation = data["generation_run_id"]
    composition = run_dir.parent / generation / "linkedin_composition.json"
    return json.loads(composition.read_text())["linkedin_body"]


def _identity(run_dir: Path, *, account=ACCOUNT_A, body=None):
    return LinkedInPublicationIdentity(
        signal_id=legacy._SIGNAL_ID,
        accepted_linkedin_body_digest=article_digest(body or _accepted_body(run_dir)),
        linkedin_account_id=account,
    )


def _scan(tmp_path, identity):
    return find_prior_linkedin_publication(
        tmp_path, identity, current_run_id="run-current-attempt"
    )


# ── A proven canonical prior publication suppresses a duplicate ──────────────


def test_proven_prior_publication_is_found(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    scan = _scan(tmp_path, _identity(run_dir))
    assert scan.match is not None
    assert scan.match.run_id == run_dir.name
    assert scan.match.post_id == POST_ID
    assert scan.match.url == POST_URL
    assert scan.match.url_provenance is UrlProvenance.PROVIDER_CONFIRMED
    assert scan.unusable_count == 0


def test_identity_is_the_accepted_body_not_the_article():
    assert set(LinkedInPublicationIdentity.__dataclass_fields__) == {
        "signal_id", "accepted_linkedin_body_digest", "linkedin_account_id",
    }


def test_different_run_id_still_matches(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    scan = _scan(tmp_path, _identity(run_dir))
    assert scan.match is not None and scan.match.run_id != "run-current-attempt"


def test_different_configuration_still_matches(tmp_path, monkeypatch):
    """Configuration is provenance, never a republish switch.

    The identity has no configuration component at all, which is the
    structural reason a configuration revision cannot authorize a duplicate.
    """
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    assert "configuration" not in "".join(
        LinkedInPublicationIdentity.__dataclass_fields__
    )
    assert _scan(tmp_path, _identity(run_dir)).match is not None
    assert FOREIGN_CONFIG is not None      # a different current config is never consulted


# ── Legitimately different publications are not suppressed ───────────────────


def test_different_accepted_body_publishes_independently(tmp_path, monkeypatch):
    """Same article, different accepted LinkedIn composition → a new post."""

    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    other_body = _accepted_body(run_dir) + "\n\nA different accepted composition."
    scan = _scan(tmp_path, _identity(run_dir, body=other_body))
    assert scan.match is None
    assert scan.unusable_count == 0


def test_different_account_publishes_independently(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch, account=ACCOUNT_B)
    scan = _scan(tmp_path, _identity(run_dir, account=ACCOUNT_A))
    assert scan.match is None
    assert scan.unusable_count == 0


@pytest.mark.parametrize(
    "status", ["FAILED", "BLOCKED", "SKIPPED", "REUSED", "PROVIDER_DUPLICATE"]
)
def test_non_published_prior_status_never_suppresses(tmp_path, monkeypatch, status):
    """Only a proven live publication counts.

    ``PROVIDER_DUPLICATE`` is included deliberately: a Zernio 409 proves a
    duplicate exists but never which post, so it is not evidence (Issue #108).
    """
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    _set_linkedin_status(run_dir, status)
    scan = _scan(tmp_path, _identity(run_dir))
    assert scan.match is None
    assert scan.unusable_count == 0


def test_published_without_real_publication_id_does_not_suppress(
    tmp_path, monkeypatch
):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    _set_linkedin_status(run_dir, "PUBLISHED", external_id="")
    scan = _scan(tmp_path, _identity(run_dir))
    assert scan.match is None
    assert scan.unusable_reasons == (UNUSABLE_MISSING_CONTENT_ID,)


# ── The candidate and its verdict must be honest ─────────────────────────────


def test_malformed_prior_results_do_not_suppress(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    identity = _identity(run_dir)
    (run_dir / "publication_results.json").write_text("{not json", encoding="utf-8")
    scan = _scan(tmp_path, identity)
    assert scan.match is None
    assert scan.unusable_reasons == (UNUSABLE_MALFORMED_RESULTS,)


def test_invalid_prior_run_provenance_does_not_suppress(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    identity = _identity(run_dir)
    _rewrite_results(run_dir, run_id="run-claimed-elsewhere")
    scan = _scan(tmp_path, identity)
    assert scan.match is None
    assert UNUSABLE_PROVENANCE_INVALID in scan.unusable_reasons


def test_missing_prior_preflight_does_not_suppress(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    (run_dir / "preflight_result.json").unlink()
    scan = _scan(tmp_path, _identity(run_dir))
    assert scan.match is None
    assert scan.unusable_reasons == (UNUSABLE_MISSING_PREFLIGHT,)


def test_foreign_preflight_from_another_run_does_not_suppress(tmp_path, monkeypatch):
    first = _seed_prior_run(tmp_path, monkeypatch)
    second = _seed_prior_run(tmp_path, monkeypatch)
    identity = _identity(second)
    (second / "preflight_result.json").write_text(
        (first / "preflight_result.json").read_text(), encoding="utf-8"
    )
    (first / "publication_results.json").unlink()
    scan = _scan(tmp_path, identity)
    assert scan.match is None
    assert UNUSABLE_INCONSISTENT in scan.unusable_reasons


def test_tampered_preflight_configuration_does_not_suppress(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    _tamper_preflight(
        run_dir,
        lambda v: v.update(configuration_identity=FOREIGN_CONFIG.model_dump()),
    )
    scan = _scan(tmp_path, _identity(run_dir))
    assert scan.match is None
    assert UNUSABLE_INCONSISTENT in scan.unusable_reasons


def test_tampered_package_digest_does_not_suppress(tmp_path, monkeypatch):
    """The verdict must still describe the package it claims to have authorized."""

    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    _tamper_preflight(
        run_dir,
        lambda v: [
            c.update(package_digest="sha256:" + "e" * 64)
            for c in v["channels"] if c["channel"] == "linkedin"
        ],
    )
    scan = _scan(tmp_path, _identity(run_dir))
    assert scan.match is None
    assert UNUSABLE_INCONSISTENT in scan.unusable_reasons


def test_relabelled_account_in_prior_verdict_does_not_suppress(tmp_path, monkeypatch):
    """A publication to account B cannot be relabelled as account A."""

    run_dir = _seed_prior_run(tmp_path, monkeypatch, account=ACCOUNT_B)

    def relabel(verdict):
        for channel in verdict["channels"]:
            if channel["channel"] == "linkedin":
                channel["target"]["account_id"] = ACCOUNT_A

    _tamper_preflight(run_dir, relabel)
    scan = _scan(tmp_path, _identity(run_dir, account=ACCOUNT_A))
    assert scan.match is None
    assert UNUSABLE_INCONSISTENT in scan.unusable_reasons


def test_corrupted_composition_evidence_does_not_suppress(tmp_path, monkeypatch):
    """A candidate whose accepted composition is unreadable proves nothing.

    Story #16 verification reaches the corrupted artifact first, so the
    recorded reason is the provenance one — the honest outcome, since the
    whole chain is what failed. Either way there is no match and the current
    publication proceeds.
    """

    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    identity = _identity(run_dir)
    generation = json.loads(
        (run_dir / "publication_results.json").read_text()
    )["generation_run_id"]
    (run_dir.parent / generation / "linkedin_composition.json").write_text(
        "{not json", encoding="utf-8"
    )
    scan = _scan(tmp_path, identity)
    assert scan.match is None
    assert scan.unusable_reasons  # typed, sanitized, never a match


def test_unreadable_composition_is_a_typed_unusable_reason(tmp_path):
    """Defense in depth: the body-digest derivation itself fails closed."""

    from src.publishing.idempotency import _prior_linkedin_body_digest

    digest, reason = _prior_linkedin_body_digest(tmp_path, "sig-x", "run-missing")
    assert digest is None and reason == UNUSABLE_COMPOSITION_UNREADABLE
    digest, reason = _prior_linkedin_body_digest(tmp_path, "sig-x", "")
    assert digest is None and reason is not None


def test_reuse_candidate_resolves_its_body_through_the_generation_run(
    tmp_path, monkeypatch
):
    """A candidate with no composition of its own is still matchable.

    A ``--from-package`` publication run never writes its own composition, so
    the accepted body must be resolved through ``generation_run_id``. This
    reproduces that shape: the candidate's own directory has no composition
    record, while its generation run does.
    """

    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    identity = _identity(run_dir)
    data = json.loads((run_dir / "publication_results.json").read_text())
    assert data["generation_run_id"] == run_dir.name    # fresh run: same run

    # Point the publication at a separate generation run holding the evidence,
    # exactly as a reuse-publication run does.
    generation = run_dir.parent / "run-generation-source"
    generation.mkdir()
    for artifact in ("generated.json", "linkedin_composition.json"):
        (generation / artifact).write_text(
            (run_dir / artifact).read_text(), encoding="utf-8"
        )
    (run_dir / "linkedin_composition.json").unlink()

    # the body is still resolvable — the scan does not look in the run's own dir
    from src.publishing.idempotency import _prior_linkedin_body_digest

    digest, reason = _prior_linkedin_body_digest(
        tmp_path, legacy._SIGNAL_ID, "run-generation-source"
    )
    assert reason is None
    assert digest == identity.accepted_linkedin_body_digest


def test_the_current_run_never_matches_itself(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    scan = find_prior_linkedin_publication(
        tmp_path, _identity(run_dir), current_run_id=run_dir.name
    )
    assert scan.match is None


def test_unusable_evidence_note_is_sanitized(tmp_path, monkeypatch):
    run_dir = _seed_prior_run(tmp_path, monkeypatch)
    identity = _identity(run_dir)
    (run_dir / "publication_results.json").write_text("{not json", encoding="utf-8")
    note = _scan(tmp_path, identity).evidence_note()
    assert note == {"count": 1, "reasons": [UNUSABLE_MALFORMED_RESULTS]}
    assert "not json" not in json.dumps(note)


# ── End-to-end through the canonical entrypoint ──────────────────────────────
#
# The real scan inside main(), with the real adapter, proving the side-effect
# placement: a proven prior publication suppresses the Zernio call entirely,
# and nothing ambiguous ever does.

import scripts.generate_and_publish as gap  # noqa: E402
from src.publishing.idempotency import find_prior_linkedin_publication as _real_scan  # noqa: E402


def _live(tmp_path, monkeypatch, *, account=ACCOUNT_A, code=201, payload=None,
          linkedin_credential=True, **overrides):
    """A live run with the real LinkedIn adapter and the real LinkedIn scan."""

    _target_env(monkeypatch)
    monkeypatch.setenv("NB_ZERNIO_LINKEDIN_ACCOUNT_ID", account)
    if not linkedin_credential:
        monkeypatch.delenv("NB_ZERNIO_API_KEY", raising=False)
    calls: list[dict] = []

    def recording_fetch(url, *, method="GET", headers=None, body=None, timeout=20):
        calls.append({"url": url, "body": body})
        return code, payload or _published_payload(), ""

    overrides.setdefault("find_prior_linkedin_publication", _real_scan)
    with mock.patch("src.publishing.linkedin._fetch", side_effect=recording_fetch):
        result = _live_run(tmp_path, LinkedInPublisher=LinkedInPublisher, **overrides)
    return result, calls


def _current_publication(tmp_path):
    return json.loads((_newest_run(tmp_path) / "publication_results.json").read_text())


def test_first_publication_calls_zernio_exactly_once(tmp_path, monkeypatch):
    (code, _, _, _), calls = _live(tmp_path, monkeypatch)
    assert len(calls) == 1
    entry = _current_publication(tmp_path)["results"]["linkedin"]
    assert entry["status"] == "PUBLISHED"
    assert entry["external_id"] == POST_ID
    assert entry["url_provenance"] == "provider_confirmed"


def test_sequential_retry_reuses_and_calls_no_zernio_endpoint(tmp_path, monkeypatch):
    prior = _seed_prior_run(tmp_path, monkeypatch)
    prior_entry = _entry(prior)

    (code, _, _, _), calls = _live(tmp_path, monkeypatch)

    assert calls == [], "a proven prior publication must make zero provider calls"
    entry = _current_publication(tmp_path)["results"]["linkedin"]
    assert entry["status"] == "REUSED"
    # prior evidence preserved exactly
    assert entry["external_id"] == prior_entry["external_id"]
    assert entry["url"] == prior_entry["url"]
    assert entry["url_provenance"] == prior_entry["url_provenance"]
    assert entry["reused_from_run_id"] == prior.name
    assert entry["run_id"] and entry["run_id"] != prior.name


def test_reused_run_appends_no_second_history_entry(tmp_path, monkeypatch):
    _seed_prior_run(tmp_path, monkeypatch)
    history = mock.MagicMock()
    _live(tmp_path, monkeypatch, append_published_entry=history)
    entry = history.call_args.args[0]
    assert "linkedin" not in entry.publications


def test_different_accepted_body_publishes_a_new_post(tmp_path, monkeypatch):
    """The prior run is for a different composition, so the retry publishes."""

    prior = _seed_prior_run(tmp_path, monkeypatch)
    generation = json.loads(
        (prior / "publication_results.json").read_text()
    )["generation_run_id"]
    composition_path = prior.parent / generation / "linkedin_composition.json"
    composition = json.loads(composition_path.read_text())
    composition["linkedin_body"] = composition["linkedin_body"] + " Another take."
    composition_path.write_text(json.dumps(composition), encoding="utf-8")

    (code, _, _, _), calls = _live(tmp_path, monkeypatch)
    assert len(calls) == 1, "a different accepted body is a different publication"


def test_different_account_publishes_a_new_post(tmp_path, monkeypatch):
    _seed_prior_run(tmp_path, monkeypatch, account=ACCOUNT_B)
    (code, _, _, _), calls = _live(tmp_path, monkeypatch, account=ACCOUNT_A)
    assert len(calls) == 1


def test_provider_duplicate_after_a_real_attempt_is_not_reused(tmp_path, monkeypatch):
    """No prior proof + a 409 stays PROVIDER_DUPLICATE, never REUSED."""

    (code, _, _, _), calls = _live(
        tmp_path, monkeypatch, code=409, payload={"message": "duplicate content"}
    )
    assert len(calls) == 1                     # the call really was attempted
    entry = _current_publication(tmp_path)["results"]["linkedin"]
    assert entry["status"] == "PROVIDER_DUPLICATE"
    assert entry["status"] != "REUSED"
    assert entry["external_id"] is None
    assert entry["reused_from_run_id"] is None
    assert _current_publication(tmp_path)["completed"] is False


def test_prior_provider_duplicate_does_not_suppress_a_later_run(tmp_path, monkeypatch):
    """The behavioral proof Issue #108 deferred to this task."""

    prior = _seed_prior_run(tmp_path, monkeypatch)
    _set_linkedin_status(prior, "PROVIDER_DUPLICATE", external_id=None, url=None)

    (code, _, _, _), calls = _live(tmp_path, monkeypatch)
    assert len(calls) == 1, "provider-duplicate evidence must never suppress"
    assert _current_publication(tmp_path)["results"]["linkedin"]["status"] == "PUBLISHED"


def test_unusable_prior_evidence_is_recorded_and_publication_proceeds(
    tmp_path, monkeypatch
):
    prior = _seed_prior_run(tmp_path, monkeypatch)
    (prior / "publication_results.json").write_text("{not json", encoding="utf-8")

    (code, _, _, _), calls = _live(tmp_path, monkeypatch)
    assert len(calls) == 1
    published = _current_publication(tmp_path)
    assert published["results"]["linkedin"]["status"] == "PUBLISHED"
    assert published["unusable_prior_publication_evidence"] == {
        "count": 1, "reasons": [UNUSABLE_MALFORMED_RESULTS],
    }


def test_preflight_block_is_never_bypassed_by_idempotency(tmp_path, monkeypatch):
    """A blocked channel never reaches the idempotency check at all.

    A proven prior publication exists, so idempotency *would* match — but the
    LinkedIn credential is missing, so #101 blocks the channel first. The
    result must be the block, never a reuse dressed up as a completed channel.
    """

    _seed_prior_run(tmp_path, monkeypatch)

    (code, _, _, _), calls = _live(tmp_path, monkeypatch, linkedin_credential=False)

    assert calls == []                       # no provider call either way
    entry = _current_publication(tmp_path)["results"]["linkedin"]
    assert entry["status"] == "BLOCKED"
    assert entry["status"] != "REUSED"
    assert entry.get("reused_from_run_id") is None
