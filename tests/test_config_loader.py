"""Issue #223: a missing config file says where it was looked for.

``load_yaml`` resolves a relative name against ``CONFIG_DIR`` before opening
it, so the bare ``FileNotFoundError`` a caller used to get named an absolute
path they never wrote and said nothing about where that path came from. The
caller had to infer the resolution rule from the path they were shown.

These scenarios pin the failure — what was asked for, where it was looked
for, and whether any resolution happened — and pin that the success
behaviour it wraps did not move. They assert on values and on single words,
never on punctuation or on a whole sentence: rewording the message is
allowed, dropping a fact out of it is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.utils.config_loader import CONFIG_DIR, load_yaml


# ── the failure ──────────────────────────────────────────────────────────────

def test_a_missing_relative_name_names_the_name_and_the_path_opened():
    with pytest.raises(FileNotFoundError) as excinfo:
        load_yaml("no_such_file.yaml")

    message = str(excinfo.value)
    assert "no_such_file.yaml" in message                   # what was asked for
    assert str(CONFIG_DIR / "no_such_file.yaml") in message  # where it was opened


def test_a_missing_relative_name_says_the_config_directory_was_used():
    with pytest.raises(FileNotFoundError) as excinfo:
        load_yaml("no_such_file.yaml")

    message = str(excinfo.value).lower()
    assert "resolved" in message
    assert "directory" in message


def test_a_missing_absolute_path_does_not_claim_any_resolution(tmp_path: Path):
    missing = tmp_path / "absent.yaml"

    with pytest.raises(FileNotFoundError) as excinfo:
        load_yaml(missing)

    message = str(excinfo.value)
    assert str(missing) in message
    assert "resolved" not in message.lower()
    assert str(CONFIG_DIR) not in message


def test_the_exception_type_callers_already_catch_is_unchanged():
    """The contract is the built-in, not a new class of our own."""

    with pytest.raises(OSError) as excinfo:
        load_yaml("no_such_file.yaml")

    assert type(excinfo.value) is FileNotFoundError


# ── the success behaviour it wraps ───────────────────────────────────────────

def test_an_existing_file_still_returns_its_parsed_mapping(tmp_path: Path):
    config = tmp_path / "brand.yaml"
    config.write_text("voice: plain\nvalues:\n  - clarity\n", encoding="utf-8")

    assert load_yaml(config) == {"voice": "plain", "values": ["clarity"]}


def test_an_empty_file_still_returns_an_empty_mapping(tmp_path: Path):
    config = tmp_path / "empty.yaml"
    config.write_text("", encoding="utf-8")

    assert load_yaml(config) == {}


def test_a_relative_name_is_still_read_from_the_config_directory(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("src.utils.config_loader.CONFIG_DIR", tmp_path)
    (tmp_path / "brand.yaml").write_text("voice: plain\n", encoding="utf-8")

    assert load_yaml("brand.yaml") == {"voice": "plain"}
