"""#233 F-02: run records never land in the tracked tree by accident.

Four modules write package or run records under one root. Each held that root
as a fixed relative path resolved at import, so any test that drove them without
redirecting it wrote real directories into ``reports/`` — 7,796 tracked files,
arriving in bulk on commits about something else, and re-entering on every
rebase that followed a local test run.

The root now reads ``NB_PACKAGES_DIR``. Production is unchanged: with the
variable unset, every module resolves exactly the path it did before. These
tests pin both halves — the default, and the redirect — because a silent return
to a fixed path is precisely what nothing noticed the first time.

No network, no model: these tests only import modules and read paths.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

MODULES = (
    "scripts.generate_and_publish",
    "scripts.generate_and_publish_visibility",
    "scripts.research.prepare_content",
    "scripts.research.publish_packages",
)
DEFAULT = Path("reports/content_packages")


@pytest.mark.parametrize("name", MODULES)
def test_the_production_default_is_unchanged(name, monkeypatch):
    monkeypatch.delenv("NB_PACKAGES_DIR", raising=False)

    module = importlib.reload(importlib.import_module(name))

    assert module.PACKAGES_DIR == DEFAULT


@pytest.mark.parametrize("name", MODULES)
def test_the_root_follows_the_environment(name, tmp_path, monkeypatch):
    redirected = tmp_path / "elsewhere"
    monkeypatch.setenv("NB_PACKAGES_DIR", str(redirected))

    module = importlib.reload(importlib.import_module(name))

    assert module.PACKAGES_DIR == redirected


@pytest.mark.parametrize("name", MODULES)
def test_a_blank_setting_is_not_a_root(name, monkeypatch):
    """An empty or whitespace value means "unset", never a path of its own."""
    monkeypatch.setenv("NB_PACKAGES_DIR", "   ")

    module = importlib.reload(importlib.import_module(name))

    assert module.PACKAGES_DIR == DEFAULT


def test_the_entrypoint_writes_its_run_directory_under_the_redirected_root(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NB_PACKAGES_DIR", str(tmp_path / "runs"))
    entrypoint = importlib.reload(importlib.import_module("scripts.generate_and_publish"))
    from src.artifacts import resolve_run_dir

    run_dir = resolve_run_dir(entrypoint.PACKAGES_DIR, "sig-1", "run-1")

    assert (tmp_path / "runs") in run_dir.parents
    assert Path("reports/content_packages/sig-1") not in run_dir.parents


def test_every_module_that_writes_records_is_covered_here():
    """A fifth writer added later must be added to the fixture too.

    ``tests/conftest.py`` redirects exactly these modules for every test. If a
    new module starts writing under the same root without joining that list, the
    residue returns quietly — so the two lists are pinned to each other.
    """
    from tests.conftest import _PACKAGE_ROOT_MODULES

    assert set(_PACKAGE_ROOT_MODULES) == set(MODULES)


def test_no_module_binds_the_root_to_a_fixed_path_again():
    """The root is resolved from the environment, never assigned a bare literal.

    The canonical entrypoint keeps the default under its own name
    (``DEFAULT_PACKAGES_DIR``), which is the documented default and not a second
    binding: what must never return is ``PACKAGES_DIR = Path("reports/...")``.
    """
    fixed = re.compile(r'^PACKAGES_DIR\s*=\s*Path\("reports/content_packages"\)', re.M)
    for name in MODULES:
        source = Path(name.replace(".", "/") + ".py").read_text(encoding="utf-8")

        assert not fixed.search(source), f"{name} binds the root to a fixed path"
        assert 'os.environ.get("NB_PACKAGES_DIR"' in source, name
