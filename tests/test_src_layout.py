"""Tests for PR #4 — src-layout symbol-table normalization.

This file is the **red half** of TDD for PR #4: every assertion below
fails on the current branch (which has neither Fix 1's symbol table nor
PR #4's normalization). The expected post-merge state is:

* Fix 1 + PR #4 together: cross-module tests under src-layout pass.
* Cross-contamination / case-sensitivity / same-name-isolation tests
  pass — these verify the analyzer *does not* over-resolve and remain
  conservative on doubt.
* The two warning tests (``test_src_as_package_warns_once_per_scan``
  and ``test_src_orphan_init_emits_warning``) verify the logging
  behavior added by review items #5a + #5b.

Fixture layout under ``tests/fixtures/src_layout/`` mirrors §§4.1-4.6 of
the PR #4 design doc plus the additional review-item fixtures
enumerated in the fixture-matrix sequencing message.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest

from agentic_guard.engine import Scanner

FIXTURES = Path(__file__).parent / "fixtures" / "src_layout"


def _rule_ids(target: Path) -> set[str]:
    return {f.rule_id for f in Scanner(include_tests=True).scan(target).findings}


# -------- §4.1-§4.5 happy-path layout fixtures ----------------------------


def test_pure_src_resolves_cross_module() -> None:
    """§4.1 — ``src/my_pkg/`` imported as ``my_pkg``."""
    assert "IG002" not in _rule_ids(FIXTURES / "case_pure_src")


def test_pure_flat_remains_resolvable() -> None:
    """§4.2 — Fix 1's existing flat-layout behavior must not regress."""
    assert "IG002" not in _rule_ids(FIXTURES / "case_pure_flat")


def test_mixed_layout_resolves_both_roots() -> None:
    """§4.3 — both src-layout and flat-layout agents resolve in one scan."""
    assert "IG002" not in _rule_ids(FIXTURES / "case_mixed")


def test_namespace_package_resolves_under_src_layout() -> None:
    """§4.4 — PEP 420 namespace package under ``src/`` (top-level)."""
    assert "IG002" not in _rule_ids(FIXTURES / "case_namespace_pkg")


def test_multi_pkg_src_layout_resolves_both_packages() -> None:
    """§4.5 — ``src/pkg_a/`` and ``src/pkg_b/`` resolve independently."""
    assert "IG002" not in _rule_ids(FIXTURES / "case_multi_pkg_src")


# -------- §4.6 cross-contamination negative test --------------------------


def test_cross_contamination_does_not_silently_resolve() -> None:
    """§4.6 — name exists in another package; must NOT bleed via fallback.

    ``main_pkg/agent.py`` imports a name that exists only in ``helpers/``;
    we treat the lookup as unresolved and IG002 fires. If this test
    starts passing (IG002 silent), someone added a name-anywhere fallback
    and that's a real bug.
    """
    assert "IG002" in _rule_ids(FIXTURES / "case_cross_contamination")


# -------- Review-item fixtures --------------------------------------------


def test_symlink_escape_does_not_index_outside_scan_root(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Review item #1 — symlink containment.

    Construct a temporary scan root containing a normal package and a
    symlink whose target is *outside* the scan root. The symlinked file
    must not appear in the symbol table, and a debug log line records
    the skip. The fixture is built at test time because committed
    symlinks pointing to absolute or never-existing paths are fragile.
    """
    proj = tmp_path / "proj"
    pkg = proj / "src" / "my_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").touch()
    (pkg / "prompts.py").write_text('LOCAL_PROMPT = "inside the scan root"\n')
    (pkg / "agent.py").write_text(
        "from agents import Agent, function_tool\n"
        "from my_pkg.prompts import LOCAL_PROMPT\n"
        "@function_tool\n"
        "def lookup(key: str) -> str:\n    return ''\n"
        "agent = Agent(name='sl', instructions=LOCAL_PROMPT, tools=[lookup], model='gpt-4o')\n"
    )

    # External directory and a symlink into it from within the scan root.
    external = tmp_path / "external_pkg"
    external.mkdir()
    (external / "leaked.py").write_text('LEAKED = "must not be indexed"\n')
    (pkg / "linked_external").symlink_to(external)

    with caplog.at_level(logging.DEBUG, logger="agentic_guard.analysis.symbol_table"):
        result = Scanner(include_tests=True).scan(proj)

    # The in-tree agent must still resolve its in-tree literal.
    assert "IG002" not in {f.rule_id for f in result.findings}, (
        "in-scan-root literal should resolve; symlink-escape should not affect it"
    )

    # The symlinked external file should be skipped with a debug message.
    skip_msgs = [
        r for r in caplog.records
        if "not under package_root" in r.message or "skipping" in r.message
    ]
    assert skip_msgs, "expected debug log for symlink-escape skip"


def test_case_sensitivity_does_not_match_across_case() -> None:
    """Review item #2 — ``src/Agents/...`` does not match ``from agents import ...``.

    Python's import system is case-sensitive on every platform; if this
    fixture stops firing IG002, the analyzer has begun case-folding
    silently — a semantics regression against Python's import model.
    """
    assert "IG002" in _rule_ids(FIXTURES / "case_case_sensitive")


def test_nested_namespace_package_resolves_pep_420() -> None:
    """Review item #3 — ``src/my_pkg/sub/`` with no ``__init__.py`` resolves.

    Aligns with Python's runtime import system (PEP 420); contrasts with
    strict mypy / historical pylint. See §2.4 (nested branch).
    """
    assert "IG002" not in _rule_ids(FIXTURES / "case_nested_namespace")


def test_tests_subpkg_resolves_when_imported_from_production_code() -> None:
    """Review item #4 — symbol-table pre-pass indexes ``my_pkg/tests/utils.py``.

    The Scanner's ``_is_test_path`` filter applies to rule evaluation, not
    to symbol resolution. ``from my_pkg.tests.utils import UTIL_PROMPT``
    must resolve cross-module.
    """
    assert "IG002" not in _rule_ids(FIXTURES / "case_tests_subpkg")


def test_src_as_package_warns_once_per_scan(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Review item #5a + the discover-time warning added per review.

    The user genuinely named their top-level package ``src``. The pure
    case (``src/__init__.py`` with no qualifying subdirectory) falls
    through to flat-layout; the user-named-src warning fires *once* per
    scan no matter how many files live under ``src/``. Fixture has two
    agent files alongside ``prompts.py`` so the one-shot property is
    actually tested.
    """
    with caplog.at_level(logging.WARNING, logger="agentic_guard.analysis.symbol_table"):
        result = Scanner(include_tests=True).scan(FIXTURES / "case_src_as_package")

    # Both agents should resolve their cross-module prompt — IG002 silent.
    assert "IG002" not in {f.rule_id for f in result.findings}

    # The one-time warning fires exactly once, not once-per-file.
    warnings_about_src_name = [
        r for r in caplog.records
        if "literally named 'src'" in r.message or "literally named `src`" in r.message
    ]
    assert len(warnings_about_src_name) == 1, (
        f"expected exactly one user-named-src warning per scan, got {len(warnings_about_src_name)}"
    )


def test_src_orphan_init_emits_warning_and_package_still_resolves(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Review item #5b — orphan ``src/__init__.py`` under src-layout.

    src-layout detection wins (``src/my_pkg/`` qualifies). The orphan
    ``src/__init__.py`` is skipped with a warning; the real package
    ``my_pkg`` resolves normally so the agent's IG002 stays silent.
    """
    with caplog.at_level(logging.WARNING, logger="agentic_guard.analysis.symbol_table"):
        result = Scanner(include_tests=True).scan(FIXTURES / "case_src_orphan")

    assert "IG002" not in {f.rule_id for f in result.findings}, (
        "my_pkg.prompts.SYSTEM_PROMPT must still resolve under src-layout"
    )
    orphan_warnings = [r for r in caplog.records if "orphan __init__.py" in r.message]
    assert len(orphan_warnings) == 1, (
        f"expected exactly one orphan-__init__.py warning, got {len(orphan_warnings)}"
    )


def test_same_name_isolation_across_top_level_packages() -> None:
    """Review item #7 — symbol-table isolation across sibling packages.

    Two packages (``pkg_a`` and ``pkg_b``) each contain a module named
    ``shared_name`` exporting a constant named ``PROMPT`` with different
    values. Each agent must resolve its own package's constant; neither
    must see the other.

    Failure mode this guards against: a "helpful" name-anywhere lookup
    that resolves ``shared_name.PROMPT`` to whichever was indexed last.
    """
    assert "IG002" not in _rule_ids(FIXTURES / "case_same_name_isolation")


# -------- Cleanup helpers -------------------------------------------------


@pytest.fixture(autouse=True)
def _scrub_pycache() -> None:
    """Prevent ``__pycache__`` directories from accumulating in fixture trees.

    Running these fixtures through ``ast.parse`` doesn't create bytecode
    caches, but if a future test ever imports a fixture as a real
    package, ``__pycache__`` could appear. Clean defensively.
    """
    yield
    for cache in FIXTURES.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
