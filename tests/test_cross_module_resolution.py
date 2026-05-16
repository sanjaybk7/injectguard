"""Cross-module string-constant resolution (Fix 1, v0.2).

Each fixture sub-package under ``tests/fixtures/cross_module/<case>/`` is
scanned as a unit so the engine's pre-pass can build a global symbol table
across the case's files. The agent file references a prompt name that lives
in a sibling/parent/aliased/relative/star-imported module; the assertions
check whether IG002 fires given how that name resolves.
"""

from __future__ import annotations

from pathlib import Path

from agentic_guard.engine import Scanner

CASES = Path(__file__).parent / "fixtures" / "cross_module"


def _rule_ids(case: str) -> set[str]:
    """Scan a case sub-package and return the set of rule IDs that fired."""
    result = Scanner(include_tests=True).scan(CASES / case)
    return {f.rule_id for f in result.findings}


# --- safe cases (no IG002) -------------------------------------------------


def test_basic_sibling_import_does_not_fire() -> None:
    """``from prompts import SYSTEM_PROMPT`` where prompts.py defines it as a literal."""
    assert "IG002" not in _rule_ids("case_basic")


def test_aliased_import_does_not_fire() -> None:
    """``from prompts import SYSTEM_PROMPT as SP`` — the alias must resolve."""
    assert "IG002" not in _rule_ids("case_aliased")


def test_relative_import_does_not_fire() -> None:
    """``from .prompts import SYSTEM_PROMPT`` inside a package."""
    assert "IG002" not in _rule_ids("case_relative")


def test_nested_package_import_does_not_fire() -> None:
    """``from myapp.common.prompts import SYSTEM_PROMPT`` (deep absolute)."""
    assert "IG002" not in _rule_ids("case_nested")


def test_star_import_does_not_fire() -> None:
    """``from prompts import *`` — names defined in the starred module are in scope."""
    assert "IG002" not in _rule_ids("case_star_import")


def test_module_attribute_access_does_not_fire() -> None:
    """``import prompts; instructions=prompts.SYSTEM_PROMPT``."""
    assert "IG002" not in _rule_ids("case_attribute")


def test_aliased_module_attribute_access_does_not_fire() -> None:
    """``import prompts as p; instructions=p.SYSTEM_PROMPT``."""
    assert "IG002" not in _rule_ids("case_attribute_aliased")


def test_try_import_with_literal_fallback_does_not_fire() -> None:
    """Top-level ``try: from prompts import X / except ImportError: X = '...'``."""
    assert "IG002" not in _rule_ids("case_try_import")


# --- vulnerable cases (IG002 must still fire) ------------------------------


def test_dynamic_value_in_imported_module_still_fires() -> None:
    """The exported name is built with an f-string in the imported module."""
    assert "IG002" in _rule_ids("case_dynamic_in_imported")


def test_missing_name_in_imported_module_still_fires() -> None:
    """Conservative default: unresolved name → treat as dynamic."""
    assert "IG002" in _rule_ids("case_missing")


def test_last_import_wins_dynamic_value_still_fires() -> None:
    """Two modules export the same name; the last-imported one is dynamic."""
    assert "IG002" in _rule_ids("case_last_wins")


def test_multi_assign_in_imported_module_still_fires() -> None:
    """Imported module assigns the name twice → analyzer cannot resolve."""
    assert "IG002" in _rule_ids("case_multi_assign")
