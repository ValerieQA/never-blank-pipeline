"""NB-00a: the publication marker authority makes a double publication impossible.

The scenarios that matter are the ones a partial run creates, so they are
written as fault injection rather than as unit assertions about files: a
publishing path performs the whole transaction (lookup → durable intent →
external call → durable marker), one destination is made to fail, and a second
run of the same path has to leave the successful destination alone.

Everything is parametrised over all six destination names, because the store is
the authority for all six and a destination protected only by accident is not
protected at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.research.publish_packages as pp
import src.publishing.publication_markers as markers
from src.publishing.base import DraftPackage
from src.publishing.publication_markers import (
    AUTHORITY_UNAVAILABLE,
    DESTINATIONS,
    PUBLICATION_POSSIBLY_EXISTS,
    PUBLICATION_UNCONFIRMED,
    AuthorityState,
    MarkerStore,
    PublicationGuard,
    PublicationIdentity,
    PublicationIdentityError,
    content_digest,
    destination_text,
    draft_source_signal_ids,
    markers_root,
    proves_publication,
    refused_result,
)
from src.publishing.result import PublishResult, PublishStatus, UrlProvenance
from tests.test_publish_packages import _PACKAGE, _SIGNAL, _setup_common


def _store(tmp_path) -> MarkerStore:
    """A store that exists — a missing root is itself an answer, not an empty one."""

    root = tmp_path / "publication_markers"
    root.mkdir(parents=True, exist_ok=True)
    # The local transaction is what this suite is about; cross-runner
    # arbitration has its own suite (tests/test_287_marker_durability.py).
    return MarkerStore(root, require_shared_claim=False)


def _guard(store, *, signals=("sig-1",), run_id="run-1") -> PublicationGuard:
    return PublicationGuard(
        source_signal_ids=signals, run_id=run_id, client="acme", store=store
    )


def _identity(guard, destination) -> PublicationIdentity:
    identity = guard.identity(destination)
    assert identity is not None
    return identity


def _publish_once(guard, destinations, *, fails=()):
    """One run of a publishing path, performing the NB-00a transaction.

    Returns ``(results, calls)``: what each destination ended as, and which
    destinations the publisher was actually asked for. The second is what the
    fault-injection scenarios are about — a suppressed publication must not
    reach the publisher at all, not merely be relabelled afterwards.
    """

    results: dict[str, PublishResult] = {}
    calls: list[str] = []
    for destination in destinations:
        digest = content_digest(f"body for {destination}")
        decision = guard.check(destination)
        if decision.proceed:
            decision = guard.record_intent(destination, content_digest=digest)
        if not decision.proceed:
            results[destination] = refused_result(decision, run_id=guard.run_id)
            continue
        calls.append(destination)
        if destination in fails:
            results[destination] = PublishResult(
                platform=destination,
                status=PublishStatus.FAILED,
                error_message="injected failure",
            )
            continue
        result = PublishResult(
            platform=destination,
            status=PublishStatus.PUBLISHED,
            external_id=f"{destination}-post-1",
            url=f"https://example.test/{destination}",
            url_provenance=UrlProvenance.PROVIDER_CONFIRMED,
        )
        guard.record_marker(destination, result, content_digest=digest)
        results[destination] = result
    return results, calls


# ── The key ────────────────────────────────────────────────────────────────


def test_the_authority_covers_all_six_destinations():
    assert set(DESTINATIONS) == {
        "wix", "linkedin", "facebook", "instagram", "threads", "telegram",
    }


def test_the_key_does_not_depend_on_the_order_the_signals_arrive_in():
    ordered = PublicationIdentity("acme", "wix", ("b", "a", "c"))
    shuffled = PublicationIdentity("acme", "wix", ("c", "a", "b"))
    assert ordered.key == shuffled.key
    assert ordered.source_signal_ids == ("a", "b", "c")


def test_a_different_signal_set_is_a_different_publication():
    one = PublicationIdentity("acme", "wix", ("a",))
    two = PublicationIdentity("acme", "wix", ("a", "b"))
    assert one.key != two.key


def test_a_rewritten_article_is_still_the_same_publication(tmp_path):
    """No article digest in the key (Step 5 §1.1): the signal set is the identity."""

    store = _store(tmp_path)
    guard = _guard(store)
    identity = _identity(guard, "wix")
    store.record_intent(identity, run_id="run-1", content_digest=content_digest("v1"))
    store.record_marker(
        identity,
        external_id="post-1",
        content_digest=content_digest("v1"),
        run_id="run-1",
    )

    # a completely different body, same signal, same destination
    later = _guard(store, run_id="run-2")
    results, calls = _publish_once(later, ["wix"])
    assert calls == []
    assert results["wix"].status is PublishStatus.REUSED


@pytest.mark.parametrize("destination", DESTINATIONS)
def test_every_destination_gets_its_own_file(tmp_path, destination):
    """One publication, six independent transactions — one per destination."""

    store = _store(tmp_path)
    guard = _guard(store)
    path = store.marker_path(_identity(guard, destination))
    assert path.parent.name == destination
    assert path not in {
        store.marker_path(_identity(guard, other))
        for other in DESTINATIONS
        if other != destination
    }
    # the key is the same everywhere: it identifies the publication, not the file
    assert all(guard.key(other) == guard.key(destination) for other in DESTINATIONS)


def test_an_unknown_destination_has_no_identity():
    with pytest.raises(PublicationIdentityError):
        PublicationIdentity("acme", "mastodon", ("a",))


def test_a_publication_with_no_source_signal_has_no_identity():
    with pytest.raises(PublicationIdentityError):
        PublicationIdentity("acme", "wix", ("", "   "))


def test_the_store_root_is_redirectable(monkeypatch, tmp_path):
    """The redirect every test relies on to stay out of the tracked tree."""

    monkeypatch.setenv("NB_PUBLICATION_MARKERS_DIR", str(tmp_path / "elsewhere"))
    assert markers_root() == tmp_path / "elsewhere"
    monkeypatch.delenv("NB_PUBLICATION_MARKERS_DIR")
    assert markers_root() == markers.DEFAULT_MARKERS_DIR


def test_a_hostile_identity_cannot_address_anything_outside_the_store(tmp_path):
    store = _store(tmp_path)
    identity = PublicationIdentity("../../etc", "wix", ("../../../passwd",))
    marker = store.marker_path(identity).resolve()
    assert store.root.resolve() in marker.parents


# ── Fault injection: one destination succeeds, another fails ───────────────


@pytest.mark.parametrize("succeeds", DESTINATIONS)
def test_a_partial_failure_never_republishes_what_already_succeeded(
    tmp_path, succeeds
):
    """A succeeds, B fails → the second run publishes neither of them again."""

    fails = DESTINATIONS[(DESTINATIONS.index(succeeds) + 1) % len(DESTINATIONS)]
    store = _store(tmp_path)

    first, first_calls = _publish_once(
        _guard(store, run_id="run-1"), [succeeds, fails], fails=(fails,)
    )
    assert first_calls == [succeeds, fails]
    assert first[succeeds].status is PublishStatus.PUBLISHED
    assert first[fails].status is PublishStatus.FAILED

    second, second_calls = _publish_once(
        _guard(store, run_id="run-2"), [succeeds, fails]
    )
    assert second_calls == [], "a proven or possible publication was attempted again"
    # the proven one is reused with the evidence the first run recorded…
    assert second[succeeds].status is PublishStatus.REUSED
    assert second[succeeds].external_id == f"{succeeds}-post-1"
    assert second[succeeds].reused_from_run_id == "run-1"
    # …and the failed one is a skip, because a failed call can still have
    # reached the platform: at most once prefers a lost post to a duplicate.
    assert second[fails].status is PublishStatus.SKIPPED
    assert second[fails].error_message == PUBLICATION_POSSIBLY_EXISTS


# ── Fault injection: a crash between the intent and the marker ─────────────


@pytest.mark.parametrize("destination", DESTINATIONS)
def test_a_crash_after_the_intent_makes_the_next_run_skip(tmp_path, destination):
    """Intent written, run dies before the marker → possibly published, so skip."""

    store = _store(tmp_path)
    crashed = _guard(store, run_id="run-1")
    identity = _identity(crashed, destination)
    assert crashed.record_intent(destination, content_digest="sha256:x").proceed
    assert store.intent_path(identity).is_file()
    assert not store.marker_path(identity).is_file()

    results, calls = _publish_once(_guard(store, run_id="run-2"), [destination])
    assert calls == []
    assert results[destination].status is PublishStatus.SKIPPED
    assert results[destination].error_message == PUBLICATION_POSSIBLY_EXISTS


@pytest.mark.parametrize("destination", DESTINATIONS)
def test_the_transaction_writes_the_intent_before_the_marker(tmp_path, destination):
    store = _store(tmp_path)
    guard = _guard(store)
    identity = _identity(guard, destination)

    _publish_once(guard, [destination])

    intent = json.loads(store.intent_path(identity).read_text(encoding="utf-8"))
    marker = json.loads(store.marker_path(identity).read_text(encoding="utf-8"))
    assert intent["destination"] == destination == marker["destination"]
    assert intent["key"] == marker["key"] == identity.key
    assert marker["external_id"] == f"{destination}-post-1"
    assert marker["run_id"] == "run-1"
    assert marker["published_at"]
    # the intent is on disk no later than the marker
    assert (
        store.intent_path(identity).stat().st_mtime
        <= store.marker_path(identity).stat().st_mtime
    )


# ── Ambiguity resolves towards "possibly published" ────────────────────────


@pytest.mark.parametrize("destination", DESTINATIONS)
def test_an_unreadable_marker_never_becomes_a_licence_to_publish_again(
    tmp_path, destination
):
    store = _store(tmp_path)
    guard = _guard(store)
    identity = _identity(guard, destination)
    _publish_once(guard, [destination])
    store.marker_path(identity).write_text("{ truncated", encoding="utf-8")

    lookup = store.lookup(identity)
    assert lookup.state is AuthorityState.POSSIBLY_PUBLISHED
    results, calls = _publish_once(_guard(store, run_id="run-2"), [destination])
    assert calls == []
    assert results[destination].error_message == PUBLICATION_POSSIBLY_EXISTS


def test_a_store_that_is_not_in_this_checkout_is_unavailable_not_empty(tmp_path):
    """A missing answer is never "no": fail closed, and never wait for a human."""

    guard = _guard(
        MarkerStore(tmp_path / "never-checked-out", require_shared_claim=False)
    )
    results, calls = _publish_once(guard, ["wix"])
    assert calls == []
    assert results["wix"].status is PublishStatus.SKIPPED
    assert results["wix"].error_message == AUTHORITY_UNAVAILABLE


def test_an_intent_that_cannot_be_made_durable_forbids_the_call(tmp_path):
    store = _store(tmp_path)
    guard = _guard(store)
    blocked = store.destination_dir(_identity(guard, "wix"))
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("this is a file where a directory belongs", encoding="utf-8")

    results, calls = _publish_once(guard, ["wix"])
    assert calls == [], "the call was made without a durable intent"
    assert results["wix"].error_message == AUTHORITY_UNAVAILABLE


def test_a_marker_that_cannot_be_made_durable_leaves_the_key_suppressed(
    tmp_path, monkeypatch
):
    """§3.6 p5: the run ends normally, and the next run still does not republish."""

    store = _store(tmp_path)
    guard = _guard(store)
    assert guard.record_intent("wix", content_digest="sha256:x").proceed

    published = PublishResult(
        platform="wix", status=PublishStatus.PUBLISHED, external_id="post-1"
    )
    with monkeypatch.context() as unwritable:
        unwritable.setattr(markers, "_write_durably", lambda path, payload: False)
        assert guard.record_marker("wix", published) is None

    results, calls = _publish_once(_guard(store, run_id="run-2"), ["wix"])
    assert calls == []
    assert results["wix"].error_message == PUBLICATION_POSSIBLY_EXISTS


# ── Shapes the publishing paths consume ────────────────────────────────────


@pytest.mark.parametrize(
    "status,earns_a_marker",
    [
        (PublishStatus.PUBLISHED, True),
        (PublishStatus.DRAFT_CREATED, False),
        (PublishStatus.FAILED, False),
        (PublishStatus.SKIPPED, False),
        (PublishStatus.REUSED, False),
        (PublishStatus.PROVIDER_DUPLICATE, False),
    ],
)
def test_only_a_published_result_earns_a_marker(status, earns_a_marker):
    """A draft is not proof the article is live; a 409 never says which post."""

    result = PublishResult(platform="wix", status=status)
    assert proves_publication(result) is earns_a_marker


def test_a_reused_result_carries_the_evidence_the_earlier_run_recorded(tmp_path):
    store = _store(tmp_path)
    guard = _guard(store)
    identity = _identity(guard, "linkedin")
    store.record_marker(
        identity,
        external_id="urn:li:share:1",
        url="https://example.test/post",
        url_provenance=UrlProvenance.PROVIDER_CONFIRMED,
        run_id="run-1",
    )
    result = refused_result(_guard(store, run_id="run-2").check("linkedin"))
    assert result.status is PublishStatus.REUSED
    assert result.external_id == "urn:li:share:1"
    assert result.url == "https://example.test/post"
    assert result.url_provenance is UrlProvenance.PROVIDER_CONFIRMED
    assert result.reused_from_run_id == "run-1"


def test_a_marker_url_of_unknown_origin_is_never_promoted(tmp_path):
    store = _store(tmp_path)
    guard = _guard(store)
    identity = _identity(guard, "wix")
    store.record_marker(identity, external_id="post-1", run_id="run-1")
    path = store.marker_path(identity)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["url_provenance"] = "invented_by_a_later_edit"
    path.write_text(json.dumps(data), encoding="utf-8")

    result = refused_result(_guard(store, run_id="run-2").check("wix"))
    assert result.url_provenance is UrlProvenance.UNAVAILABLE


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({"signal_id": "sig-9"}, ("sig-9",)),
        ({"queue_item_id": "vi-4"}, ("vi-4",)),
        ({"manual_topic_id": "topic-2"}, ("topic-2",)),
        ({"source_signal_ids": ["b", "a"]}, ("b", "a")),
        ({}, ()),
    ],
)
def test_a_draft_names_the_source_its_key_is_made_of(metadata, expected):
    draft = DraftPackage(
        draft_dir=Path("."), blog_title="", blog_body="", blog_meta={},
        linkedin_text="", instagram_text="", facebook_text="",
        threads_sequence=[], telegram_text="", image_url=None, metadata=metadata,
    )
    assert draft_source_signal_ids(draft) == expected


def test_each_destination_records_the_text_it_actually_published():
    draft = DraftPackage(
        draft_dir=Path("."), blog_title="", blog_body="blog", blog_meta={},
        linkedin_text="li", instagram_text="ig", facebook_text="fb",
        threads_sequence=["one", "two"], telegram_text="tg", image_url=None,
    )
    assert destination_text(draft, "wix") == "blog"
    assert destination_text(draft, "linkedin") == "li"
    assert destination_text(draft, "facebook") == "fb"
    assert destination_text(draft, "instagram") == "ig"
    assert destination_text(draft, "threads") == "one\ntwo"
    assert destination_text(draft, "telegram") == "tg"


# ── The authority on a real publishing path ────────────────────────────────


class _FakePublisher:
    """A publisher that records whether it was reached at all."""

    def __init__(self, name: str, *, fails: bool = False) -> None:
        self.name = name
        self.fails = fails
        self.calls = 0

    def publish(self, draft, mode, **kwargs) -> PublishResult:
        self.calls += 1
        if self.fails:
            return PublishResult(
                platform=self.name,
                status=PublishStatus.FAILED,
                error_message="injected failure",
            )
        return PublishResult(
            platform=self.name,
            status=PublishStatus.PUBLISHED,
            external_id=f"{self.name}-post-1",
            url=f"https://example.test/{self.name}",
        )


def test_stage_11_partial_failure_does_not_republish_on_the_next_run(
    monkeypatch, tmp_path
):
    """The real research publishing path, run twice over the same signal."""

    # These paths build their own store. This suite is the single-filesystem
    # contract; the cross-runner arbiter is proven in
    # tests/test_287_marker_durability.py against two real clones.
    monkeypatch.setenv("NB_SHARED_CLAIM", "0")
    _setup_common(monkeypatch, tmp_path)

    first = [
        ("wix", _FakePublisher("wix")),
        ("linkedin", _FakePublisher("linkedin", fails=True)),
    ]
    monkeypatch.setattr(pp, "_PUBLISHERS", first)
    report = pp.publish_packages([_SIGNAL], [_PACKAGE])[0]
    assert report["results"]["wix"]["status"] == "PUBLISHED"
    assert report["results"]["linkedin"]["status"] == "FAILED"
    assert report[PUBLICATION_UNCONFIRMED] == []

    second = [
        ("wix", _FakePublisher("wix")),
        ("linkedin", _FakePublisher("linkedin")),
    ]
    monkeypatch.setattr(pp, "_PUBLISHERS", second)
    report = pp.publish_packages([_SIGNAL], [_PACKAGE])[0]

    assert [publisher.calls for _, publisher in second] == [0, 0], (
        "the second run reached a publisher for an already-attempted publication"
    )
    assert report["results"]["wix"]["status"] == "REUSED"
    assert report["results"]["wix"]["external_id"] == "wix-post-1"
    assert report["results"]["linkedin"]["status"] == "SKIPPED"
    assert report["results"]["linkedin"]["error_message"] == (
        PUBLICATION_POSSIBLY_EXISTS
    )


def test_the_canonical_entrypoint_does_not_republish_after_a_partial_failure(
    tmp_path, monkeypatch
):
    """The same fault injection, on the canonical ``generate_and_publish`` path.

    The legacy harness gives every run its own store (see
    ``tests.test_generate_and_publish._fake_publication_guard``), because the
    tests built on it seed prior publications by running this same entrypoint
    for real. Here the real, shared authority is wired back in — the way the
    Wix scan is in ``tests/test_wix_idempotency.py`` — so the one thing that
    can suppress the second run's Wix call is the marker written by the first.
    """

    # These paths build their own store. This suite is the single-filesystem
    # contract; the cross-runner arbiter is proven in
    # tests/test_287_marker_durability.py against two real clones.
    monkeypatch.setenv("NB_SHARED_CLAIM", "0")

    from unittest import mock

    from tests import test_generate_and_publish as legacy
    from tests.test_publication_preflight import _live_run, _target_env

    _target_env(monkeypatch)

    def _publication_results():
        paths = list(tmp_path.glob(f"{legacy._SIGNAL_ID}/runs/*/publication_results.json"))
        assert paths, "the run under test wrote no publication evidence"
        newest = max(paths, key=lambda path: path.stat().st_mtime)
        return json.loads(newest.read_text())["results"]

    def _failing_linkedin():
        publisher = mock.MagicMock()
        publisher.publish.return_value = PublishResult(
            platform="linkedin",
            status=PublishStatus.FAILED,
            error_message="injected failure",
        )
        return publisher

    # Run one: Wix succeeds, LinkedIn fails after its intent was made durable.
    failing = _failing_linkedin()
    _, wix_first, _, _ = _live_run(
        tmp_path,
        PublicationGuard=PublicationGuard,
        LinkedInPublisher=mock.MagicMock(return_value=failing),
    )
    assert wix_first.publish.call_count == 1
    assert failing.publish.call_count == 1
    first = _publication_results()
    assert first["wix"]["status"] == "PUBLISHED"
    assert first["linkedin"]["status"] == "FAILED"

    # Run two: neither destination may be called again.
    _, wix_second, linkedin_second, _ = _live_run(
        tmp_path, PublicationGuard=PublicationGuard
    )
    wix_second.publish.assert_not_called()
    linkedin_second.publish.assert_not_called()

    second = _publication_results()
    assert second["wix"]["status"] == "REUSED"
    assert second["wix"]["external_id"] == first["wix"]["external_id"]
    # LinkedIn left an intent and no marker: at most once means skip, not retry.
    assert second["linkedin"]["status"] == "SKIPPED"
    assert second["linkedin"]["error_message"] == PUBLICATION_POSSIBLY_EXISTS
