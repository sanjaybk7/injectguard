# PR #4 — fixture inventory

Generated artifact: concatenates every fixture file and the test file
into one document for review. Regenerable from disk; commit on the PR #4
branch as a permanent reference for fixture-matrix sign-off.

---

## tests/test_src_layout.py

```python
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
```

---

## Fixture directory tree (tests/fixtures/src_layout/)

```
.
case_case_sensitive
    src
        Agents
            __init__.py
            agent.py
            prompts.py
case_cross_contamination
    helpers
        __init__.py
        prompts.py
    src
        main_pkg
            __init__.py
            agent.py
case_mixed
    helpers
        __init__.py
        agent.py
        prompts.py
    src
        main_pkg
            __init__.py
            agent.py
            prompts.py
case_multi_pkg_src
    src
        pkg_a
            __init__.py
            agent.py
            prompts.py
        pkg_b
            __init__.py
            agent.py
            prompts.py
case_namespace_pkg
    src
        my_pkg
            agent.py
            prompts.py
case_nested_namespace
    src
        my_pkg
            __init__.py
            agent.py
            sub
                prompts.py
case_pure_flat
    my_pkg
        __init__.py
        agent.py
        prompts.py
case_pure_src
    src
        my_pkg
            __init__.py
            agent.py
            prompts.py
case_same_name_isolation
    src
        pkg_a
            __init__.py
            agent.py
            shared_name.py
        pkg_b
            __init__.py
            agent.py
            shared_name.py
case_src_as_package
    src
        __init__.py
        agent_a.py
        agent_b.py
        prompts.py
case_src_orphan
    src
        __init__.py
        my_pkg
            __init__.py
            agent.py
            prompts.py
case_tests_subpkg
    src
        my_pkg
            __init__.py
            main.py
            tests
                __init__.py
                utils.py
```

---

## Every fixture .py file

### `tests/fixtures/src_layout/case_case_sensitive/src/Agents/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_case_sensitive/src/Agents/agent.py`

```python
"""§1.2.2 — case sensitivity (review item #2).

The package on disk is ``src/Agents/`` (capital A). The import below uses
lowercase ``agents``. Python's import system would NOT match this on any
platform, regardless of filesystem case-sensitivity. Our analyzer must
behave the same way: ``Agents`` and ``agents`` are different modules.

Expected: IG002 fires (SYSTEM_PROMPT does not resolve, because the
indexed key is ``Agents.prompts`` but the import asks for
``agents.prompts``).

If this fixture starts passing (IG002 not firing), the implementation
has case-folded somewhere — that's a silent semantics change away from
Python's import model.
"""

from agents import Agent, function_tool

# Lowercase import, capital-A directory. Will not resolve.
from agents.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="case-sensitive-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_case_sensitive/src/Agents/prompts.py`

```python
SYSTEM_PROMPT = "I am inside the capital-A `Agents` package."
```

### `tests/fixtures/src_layout/case_cross_contamination/helpers/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_cross_contamination/helpers/prompts.py`

```python
"""The name MAIN_PROMPT exists here — but it is not importable via
``main_pkg.prompts``. The cross-contamination guard asserts the analyzer
does NOT resolve ``from main_pkg.prompts import MAIN_PROMPT`` by reaching
into this file.
"""

MAIN_PROMPT = "This belongs to helpers, not main_pkg."
```

### `tests/fixtures/src_layout/case_cross_contamination/src/main_pkg/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_cross_contamination/src/main_pkg/agent.py`

```python
"""§4.6 — cross-contamination negative test.

``main_pkg/agent.py`` tries to import ``MAIN_PROMPT`` from its own
``prompts`` module, which does NOT exist. The name ``MAIN_PROMPT`` *does*
exist over in ``helpers/prompts.py``, but a name-anywhere fallback
lookup would be a bug: imports are resolved by exact module path, not by
name presence. IG002 must fire here.

If someone "helpfully" adds a fallback that searches every module for the
name, this fixture catches it.
"""

from agents import Agent, function_tool

from main_pkg.prompts import MAIN_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="cross-contam-agent",
    instructions=MAIN_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_mixed/helpers/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_mixed/helpers/agent.py`

```python
"""§4.3 — mixed layout: this agent lives at flat-layout root. Imports from
helpers.prompts (its own sibling). Both this agent and the src-layout one
must resolve in the same scan.
"""

from agents import Agent, function_tool

from helpers.prompts import P2


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="mixed-helpers-agent",
    instructions=P2,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_mixed/helpers/prompts.py`

```python
P2 = "Helpers package prompt — lives flat at root."
```

### `tests/fixtures/src_layout/case_mixed/src/main_pkg/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_mixed/src/main_pkg/agent.py`

```python
"""§4.3 — mixed layout: this agent lives under src/. Both src/ and the
flat-layout helpers/ are scanned in the same run; this one imports from
its sibling under src.
"""

from agents import Agent, function_tool

from main_pkg.prompts import P1


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="mixed-main-agent",
    instructions=P1,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_mixed/src/main_pkg/prompts.py`

```python
P1 = "Main package prompt — lives under src/."
```

### `tests/fixtures/src_layout/case_multi_pkg_src/src/pkg_a/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_multi_pkg_src/src/pkg_a/agent.py`

```python
"""§4.5 — multi-package src-layout. pkg_a's agent imports from its own
sibling. Must resolve as ``pkg_a.prompts``, not ``src.pkg_a.prompts``.
"""

from agents import Agent, function_tool

from pkg_a.prompts import PROMPT_A


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pkg-a-agent",
    instructions=PROMPT_A,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_multi_pkg_src/src/pkg_a/prompts.py`

```python
PROMPT_A = "Prompt from pkg_a."
```

### `tests/fixtures/src_layout/case_multi_pkg_src/src/pkg_b/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_multi_pkg_src/src/pkg_b/agent.py`

```python
"""§4.5 — multi-package src-layout. pkg_b's agent imports from its own
sibling. Names must not bleed between pkg_a and pkg_b.
"""

from agents import Agent, function_tool

from pkg_b.prompts import PROMPT_B


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pkg-b-agent",
    instructions=PROMPT_B,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_multi_pkg_src/src/pkg_b/prompts.py`

```python
PROMPT_B = "Prompt from pkg_b."
```

### `tests/fixtures/src_layout/case_namespace_pkg/src/my_pkg/agent.py`

```python
"""§4.4 — PEP 420 namespace package under src-layout. ``my_pkg`` has no
``__init__.py`` but contains ``.py`` files. Python's runtime treats this
as a namespace package; the analyzer must too.
"""

from agents import Agent, function_tool
from my_pkg.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="namespace-pkg-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_namespace_pkg/src/my_pkg/prompts.py`

```python
SYSTEM_PROMPT = "Implicit namespace package: no __init__.py at the package level."
```

### `tests/fixtures/src_layout/case_nested_namespace/src/my_pkg/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_nested_namespace/src/my_pkg/agent.py`

```python
"""§2.4 (nested branch) — review item #3.

``my_pkg`` has ``__init__.py`` but its sub-directory ``my_pkg/sub/`` does
not. Per PEP 420 the runtime resolves ``my_pkg.sub`` as an implicit
namespace package; our analyzer aligns with the runtime, not with
strict-mode static-analysis defaults (mypy without ``--namespace-packages``,
historical pylint).
"""

from agents import Agent, function_tool

from my_pkg.sub.prompts import NESTED_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="nested-namespace-agent",
    instructions=NESTED_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_nested_namespace/src/my_pkg/sub/prompts.py`

```python
"""``my_pkg/sub/`` has no ``__init__.py``. PEP 420 says ``my_pkg.sub`` is
a valid implicit namespace package. ``my_pkg.sub.prompts`` must resolve.
"""

NESTED_PROMPT = "I live in a nested implicit namespace package."
```

### `tests/fixtures/src_layout/case_pure_flat/my_pkg/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_pure_flat/my_pkg/agent.py`

```python
"""§4.2 — pure flat-layout regression test for Fix 1's existing behavior.

This must continue to resolve after PR #4 lands. If PR #4 accidentally
breaks flat-layout, this fixture is the canary.
"""

from agents import Agent, function_tool

from my_pkg.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pure-flat-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_pure_flat/my_pkg/prompts.py`

```python
SYSTEM_PROMPT = "You are a helpful assistant. Be concise."
```

### `tests/fixtures/src_layout/case_pure_src/src/my_pkg/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_pure_src/src/my_pkg/agent.py`

```python
"""§4.1 — pure src-layout. Agent imports from sibling module via the package
name (``my_pkg.prompts``), not via the filesystem-relative path
(``src.my_pkg.prompts``). PR #4 must normalize the symbol-table key so
the import resolves.
"""

from agents import Agent, function_tool

from my_pkg.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pure-src-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_pure_src/src/my_pkg/prompts.py`

```python
SYSTEM_PROMPT = "You are a helpful assistant. Be concise."
```

### `tests/fixtures/src_layout/case_same_name_isolation/src/pkg_a/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_same_name_isolation/src/pkg_a/agent.py`

```python
"""§4a (cross-function pollution, symbol-table edition) — review item #7.

Both ``pkg_a`` and ``pkg_b`` contain a module named ``shared_name`` that
exports a constant named ``PROMPT``. The two ``PROMPT`` values differ.
The symbol table must keep them isolated: ``pkg_a.shared_name.PROMPT``
must resolve to pkg_a's value, ``pkg_b.shared_name.PROMPT`` must resolve
to pkg_b's value, and neither must bleed into the other's lookup.

Expected: IG002 does NOT fire on either agent.

(Failure mode this guards against: a "helpful" lookup that searches all
modules with matching trailing names — which would resolve
``shared_name.PROMPT`` to whichever was indexed last.)
"""

from agents import Agent, function_tool

from pkg_a.shared_name import PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pkg-a-isolated-agent",
    instructions=PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_same_name_isolation/src/pkg_a/shared_name.py`

```python
PROMPT = "I belong to pkg_a, not pkg_b."
```

### `tests/fixtures/src_layout/case_same_name_isolation/src/pkg_b/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_same_name_isolation/src/pkg_b/agent.py`

```python
"""§4a paired fixture — see ``pkg_a/agent.py`` for the full rationale.

This agent must resolve ``PROMPT`` to pkg_b's value, not pkg_a's.
"""

from agents import Agent, function_tool

from pkg_b.shared_name import PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pkg-b-isolated-agent",
    instructions=PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_same_name_isolation/src/pkg_b/shared_name.py`

```python
PROMPT = "I belong to pkg_b, not pkg_a."
```

### `tests/fixtures/src_layout/case_src_as_package/src/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_src_as_package/src/agent_a.py`

```python
"""§1.1.1 (pure case) — review item #5a + user-named-src warning.

The user genuinely named their top-level package ``src``. No
subdirectory under ``src/`` contains ``.py`` files, so src-layout
detection rejects this layout and falls through to flat-layout. The
package is indexed as ``src``; ``src.prompts.SYSTEM_PROMPT`` resolves.

This file is one of two agents under the same package. The
discover-time warning ("flat-layout detected with top-level package
literally named 'src'...") must fire exactly once per scan, regardless
of how many files live under ``src/``.
"""

from agents import Agent, function_tool

from src.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent_a = Agent(
    name="src-as-package-agent-a",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_src_as_package/src/agent_b.py`

```python
"""Second file under the same user-named-src package. Exists to verify
that the discover-time warning fires *once* per scan, not once per file.
"""

from agents import Agent, function_tool

from src.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent_b = Agent(
    name="src-as-package-agent-b",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_src_as_package/src/prompts.py`

```python
"""Multiple files alongside this one (``agent_a.py``, ``agent_b.py``) so we
can verify the user-named-src warning fires *once* per scan, not once
per file under ``src/``.
"""

SYSTEM_PROMPT = "I live inside a package literally named `src`."
```

### `tests/fixtures/src_layout/case_src_orphan/src/__init__.py`

```python
"""§1.1.1 (mixed orphan case) — review item #5b.

This ``src/__init__.py`` becomes an *orphan* under src-layout: ``src/``
is detected as the package root because ``src/my_pkg/`` contains ``.py``
files, so this file shouldn't be importable as a package at all. The
``file_to_module_path`` orphan branch (§1.2 code block) must skip it
with a warning rather than silently returning the empty-string module
path.
"""

ORPHAN_CONSTANT = "I should be invisible to the symbol table."
```

### `tests/fixtures/src_layout/case_src_orphan/src/my_pkg/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_src_orphan/src/my_pkg/agent.py`

```python
"""§1.1.1 (mixed orphan case) — review item #5b.

The src-layout detection wins because ``src/my_pkg/`` qualifies. The
orphan ``src/__init__.py`` is skipped with a warning at
``file_to_module_path`` time. This agent's cross-module import of
``SYSTEM_PROMPT`` still resolves normally via the package-relative path
``my_pkg.prompts``.

Expected:
* IG002 does NOT fire on this agent (normal resolution still works).
* A warning matching ``orphan __init__.py at package root`` is emitted
  exactly once for the scan (one orphan file).
"""

from agents import Agent, function_tool
from my_pkg.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="src-orphan-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_src_orphan/src/my_pkg/prompts.py`

```python
SYSTEM_PROMPT = "Normal package prompt. Lives at src/my_pkg/prompts.py."
```

### `tests/fixtures/src_layout/case_tests_subpkg/src/my_pkg/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_tests_subpkg/src/my_pkg/main.py`

```python
"""§2.7 — review item #4.

Production-path module imports from ``my_pkg.tests.utils`` — a real
Python pattern (shared helpers happen to live under a ``tests`` namespace).
The symbol table must index ``my_pkg.tests.utils`` even though
rule-evaluation would skip ``my_pkg/tests/utils.py`` if it contained
agent code.

Expected: IG002 does NOT fire on this agent (cross-module resolution
finds UTIL_PROMPT under the indexed tests-subpkg path).
"""

from agents import Agent, function_tool

from my_pkg.tests.utils import UTIL_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="tests-subpkg-agent",
    instructions=UTIL_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
```

### `tests/fixtures/src_layout/case_tests_subpkg/src/my_pkg/tests/__init__.py`

_(empty file)_

### `tests/fixtures/src_layout/case_tests_subpkg/src/my_pkg/tests/utils.py`

```python
"""A genuine importable utility that happens to live under ``tests/``.

The Scanner's ``_is_test_path`` filter applies to vulnerability detection,
not to the symbol-table pre-pass — so this file gets indexed as
``my_pkg.tests.utils`` and the constant below is resolvable from
non-test code.
"""

UTIL_PROMPT = "Shared prompt utility that lives under my_pkg/tests/."
```

