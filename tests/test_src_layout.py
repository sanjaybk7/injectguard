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
import sys
from pathlib import Path

import pytest

from agentic_guard.engine import Scanner

FIXTURES = Path(__file__).parent / "fixtures" / "src_layout"


def _rule_ids(target: Path) -> set[str]:
    return {f.rule_id for f in Scanner(include_tests=True).scan(target).findings}


# -------- §4.1-§4.5 happy-path layout fixtures ----------------------------


def test_pure_src_resolves_cross_module() -> None:
    """§4.1 — ``src/my_pkg/`` imported as ``my_pkg``."""
    assert "IG002" not in _rule_ids(FIXTURES / "case_pure_src"), (
        "§4.1 pure-src cross-module resolution regressed"
    )


def test_pure_flat_remains_resolvable() -> None:
    """§4.2 — Fix 1's existing flat-layout behavior must not regress."""
    assert "IG002" not in _rule_ids(FIXTURES / "case_pure_flat"), (
        "§4.2 flat-layout regression — Fix 1's existing behavior changed"
    )


def test_mixed_layout_resolves_both_roots() -> None:
    """§4.3 — both src-layout and flat-layout agents resolve in one scan."""
    assert "IG002" not in _rule_ids(FIXTURES / "case_mixed"), (
        "§4.3 mixed-layout dual-root resolution regressed"
    )


def test_namespace_package_resolves_under_src_layout() -> None:
    """§4.4 — PEP 420 namespace package under ``src/`` (top-level)."""
    assert "IG002" not in _rule_ids(FIXTURES / "case_namespace_pkg"), (
        "§4.4 top-level PEP 420 namespace package resolution regressed"
    )


def test_multi_pkg_src_layout_resolves_both_packages() -> None:
    """§4.5 — ``src/pkg_a/`` and ``src/pkg_b/`` resolve independently."""
    assert "IG002" not in _rule_ids(FIXTURES / "case_multi_pkg_src"), (
        "§4.5 multi-package src-layout resolution regressed"
    )


# -------- §4.6 cross-contamination negative test --------------------------


def test_cross_contamination_does_not_silently_resolve() -> None:
    """§4.6 — bidirectional cross-contam (review item #3).

    Two agents, each importing a name that exists *only in the other
    package*. Either direction silently resolving would be a bug.
    The count check distinguishes "both directions fired IG002" from
    "only one direction fired, the other silently resolved through a
    fallback we don't want."
    """
    findings = Scanner(include_tests=True).scan(
        FIXTURES / "case_cross_contamination"
    ).findings
    ig002 = [f for f in findings if f.rule_id == "IG002"]
    assert len(ig002) == 2, (
        f"§4.6 expected IG002 to fire in both directions "
        f"(main_pkg→helpers and helpers→main_pkg); got {len(ig002)} IG002 "
        f"findings: {[str(f.location.file) for f in ig002]}"
    )


# -------- Review-item fixtures --------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="symlink creation requires SeCreateSymbolicLinkPrivilege on Windows",
)
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

    # The symlinked external file should be skipped with a debug message
    # matching the §1.2 format: log.debug("skipping %s: not under package_root %s", ...)
    # We match strictly on "not under package_root" so a future regression that
    # breaks symlink-escape (while leaving the orphan __init__.py skip working)
    # still fails this test instead of catching the orphan log incidentally.
    matching = [r for r in caplog.records if "not under package_root" in r.message]
    assert matching, (
        "expected debug log matching §1.2 'not under package_root' format "
        "for symlink-escape skip"
    )

    # The matched record must reference the actual symlinked file or the
    # external target; a generic "not under package_root" log against an
    # unrelated path would silently pass without this check.
    assert any(
        "linked_external" in r.message
        or "leaked.py" in r.message
        or "external_pkg" in r.message
        for r in matching
    ), (
        "symlink-skip log must reference the symlinked file path or external "
        "target; got messages: " + repr([r.message for r in matching])
    )


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
    assert "IG002" not in _rule_ids(FIXTURES / "case_nested_namespace"), (
        "§2.4 nested PEP 420 namespace package resolution regressed"
    )


def test_tests_subpkg_dual_concern_symbol_table_indexes_rule_eval_skips(
    tmp_path: Path,
) -> None:
    """Review item #4 — both halves of §2.7's dual-concern.

    §2.7 makes two claims about ``tests/`` directories:
      1. The symbol-table pre-pass indexes ``.py`` files under ``tests/``
         so production code can ``from my_pkg.tests.utils import X`` and
         have it resolve.
      2. The Scanner's ``_iter_scannable_files`` filter skips ``tests/``
         from *rule evaluation* (independent of (1)).

    Why this test builds the fixture in ``tmp_path`` instead of using a
    committed fixture under ``tests/fixtures/``:

    * The other ``test_*`` fixtures live under ``tests/fixtures/`` and
      so the existing ``test_*`` calls pass ``include_tests=True`` to
      bypass the outer ``tests/`` filter. But ``include_tests=True``
      also bypasses the inner ``my_pkg/tests/`` filter that this test
      needs to assert claim (2) on. A committed fixture cannot exercise
      claim (2) under any flag combination.
    * Building in ``tmp_path`` puts the fixture under a path with no
      ``tests/`` ancestor, so ``include_tests=False`` (the default)
      filters only the inner ``my_pkg/tests/`` content, exactly what
      §2.7 describes.

    Both claims are asserted on the same scan:
      (1) ``main.py`` imports ``my_pkg.tests.utils.UTIL_PROMPT``; the
          import must resolve cross-module (no IG002 on main.py).
      (2) ``my_pkg/tests/vulnerable_fixture.py`` defines a real
          confused-deputy agent (read_email source + send_email sink,
          no gate). It must NOT fire IG001 because rule evaluation skips
          ``tests/`` paths.
    """
    proj = tmp_path / "proj"
    pkg = proj / "src" / "my_pkg"
    tests_dir = pkg / "tests"
    tests_dir.mkdir(parents=True)
    (pkg / "__init__.py").touch()
    (tests_dir / "__init__.py").touch()

    # Test-tree utility module that production code imports from.
    (tests_dir / "utils.py").write_text(
        'UTIL_PROMPT = "Shared prompt utility that lives under my_pkg/tests/."\n'
    )

    # Production-path agent. Single tool (no source/sink pairing), so
    # IG001 cannot fire here on its own; we are testing IG002 silence.
    (pkg / "main.py").write_text(
        "from agents import Agent, function_tool\n"
        "from my_pkg.tests.utils import UTIL_PROMPT\n"
        "@function_tool\n"
        "def lookup(key: str) -> str:\n    return ''\n"
        "agent = Agent(name='m', instructions=UTIL_PROMPT, tools=[lookup], model='gpt-4o')\n"
    )

    # Deliberate confused-deputy under tests/. Rule evaluation MUST skip
    # this file; if it doesn't, IG001 will fire and the second assertion
    # below will catch it.
    (tests_dir / "vulnerable_fixture.py").write_text(
        "from agents import Agent, function_tool\n"
        "@function_tool\n"
        "def read_email(message_id: str) -> str:\n    return ''\n"
        "@function_tool\n"
        "def send_email(to: str, body: str) -> str:\n    return ''\n"
        "agent = Agent(\n"
        "    name='vuln',\n"
        "    instructions='static prompt',\n"
        "    tools=[read_email, send_email],\n"
        "    model='gpt-4o',\n"
        ")\n"
    )

    # Default include_tests=False — the whole point of this test.
    result = Scanner().scan(proj)
    rule_ids = {f.rule_id for f in result.findings}

    # Claim (1): cross-module resolution via the indexed tests/-subpkg.
    assert "IG002" not in rule_ids, (
        "§2.7 claim 1 regressed: symbol-table pre-pass must index files "
        "under my_pkg/tests/ so that 'from my_pkg.tests.utils import "
        "UTIL_PROMPT' resolves. IG002 firing here means the pre-pass "
        "skipped tests/ along with rule evaluation, conflating the two "
        "concerns."
    )

    # Claim (2): rule-evaluation skip on the deliberate vulnerable fixture.
    assert "IG001" not in rule_ids, (
        "§2.7 claim 2 regressed: rule evaluation must skip "
        "my_pkg/tests/vulnerable_fixture.py because it sits under a "
        "tests/ directory. IG001 firing here means the scanner is "
        "evaluating tests/ content as production code."
    )


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
    """Review item #7 — symbol-table isolation across sibling packages,
    verified by content (review item #4 amendment).

    Two packages (``pkg_a`` and ``pkg_b``) each contain a module named
    ``shared_name`` exporting a name called ``PROMPT``. The values
    differ in *kind*:

    * ``pkg_a.shared_name.PROMPT`` is a dynamic f-string → symbol table
      does NOT index it → cross-module lookup returns unresolved →
      IG002 fires on ``pkg_a/agent.py``.
    * ``pkg_b.shared_name.PROMPT`` is a plain literal → symbol table
      indexes it normally → cross-module lookup resolves → IG002 stays
      silent on ``pkg_b/agent.py``.

    The split assertions catch the precise failure mode that the
    presence-only check would have missed: if isolation breaks and the
    analyzer returns pkg_b's literal for pkg_a's lookup, IG002 would
    silently disappear from pkg_a; conversely, returning pkg_a's
    dynamic for pkg_b's lookup would flip pkg_b to firing. The two
    counts catch both directions independently.
    """
    findings = Scanner(include_tests=True).scan(
        FIXTURES / "case_same_name_isolation"
    ).findings
    ig002 = [f for f in findings if f.rule_id == "IG002"]
    pkg_a_findings = [f for f in ig002 if "pkg_a" in str(f.location.file)]
    pkg_b_findings = [f for f in ig002 if "pkg_b" in str(f.location.file)]
    assert len(pkg_a_findings) == 1, (
        f"pkg_a's agent must fire IG002 (its PROMPT is a dynamic f-string). "
        f"0 findings here would mean isolation is broken — the analyzer "
        f"returned pkg_b's literal in response to pkg_a's lookup. "
        f"Got {len(pkg_a_findings)} pkg_a findings."
    )
    assert len(pkg_b_findings) == 0, (
        f"pkg_b's agent must NOT fire IG002 (its PROMPT is a plain literal). "
        f"1 finding here would mean isolation is broken — the analyzer "
        f"returned pkg_a's dynamic value in response to pkg_b's lookup. "
        f"Got {len(pkg_b_findings)} pkg_b findings."
    )
