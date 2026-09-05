"""Issue #223: a missing config file says where it was looked for.

``load_yaml`` resolves a relative name against ``CONFIG_DIR`` before opening
it, so a caller who passed ``"no_such_file.yaml"`` used to see nothing but a
bare ``FileNotFoundError`` naming an absolute path they never wrote — the
resolution rule had to be inferred from the path shown. The failure now names
both what was asked for and where it was looked for, and claims a resolution
only when one actually happened.

The exception type is unchanged: every existing ``except FileNotFoundError``
still catches it. These scenarios assert on message content, never on exact
wording or punctuation.
"""

from __future__ import annotations

import pytest

from src.utils import config_loader
from src.utils.config_loader import load_yaml


def test_a_missing_relative_name_names_both_the_name_and_the_path(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config_loader, "CONFIG_DIR", tmp_path)

    with pytest.raises(FileNotFoundError) as excinfo:
        load_yaml("no_such_file.yaml")

    message = str(excinfo.value)
    assert "no_such_file.yaml" in message  # what was asked for
    assert str(tmp_path / "no_such_file.yaml") in message  # what was opened
    # and the rule that connects the two, which the caller could not see
    assert "configuration directory" in message.lower()
    assert str(tmp_path) in message


def test_a_missing_absolute_path_claims_no_resolution(tmp_path):
    missing = tmp_path / "elsewhere" / "absent.yaml"

    with pytest.raises(FileNotFoundError) as excinfo:
        load_yaml(missing)

    message = str(excinfo.value)
    # the caller's value and the opened path are the same string here
    assert str(missing) in message
    # nothing was resolved, so nothing may say it was
    assert "resolved" not in message.lower()
    assert "configuration directory" not in message.lower()


def test_an_existing_file_still_returns_its_parsed_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, "CONFIG_DIR", tmp_path)
    (tmp_path / "brand.yaml").write_text(
        "voice: plain\ntone:\n  - direct\n", encoding="utf-8"
    )

    assert load_yaml("brand.yaml") == {"voice": "plain", "tone": ["direct"]}


def test_an_empty_file_still_returns_an_empty_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, "CONFIG_DIR", tmp_path)
    (tmp_path / "empty.yaml").write_text("", encoding="utf-8")

    assert load_yaml("empty.yaml") == {}
