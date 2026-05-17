"""Cross-module symbol resolution for the scan root.

The most common false-positive class in v0.1 was ``instructions=NAME`` where
``NAME`` was imported from another module — the parser only resolved
module-local constants. This module owns the package-level pre-pass that
walks every .py file in the scan root, records module-scope ``NAME = "lit"``
and ``def NAME`` assignments, and lets per-file analysis resolve imported
names back to their definition.

Design rules (all conservative-on-doubt):

* Top-level statements only. Assignments inside ``if`` / ``while`` / function
  bodies are not exported. Top-level ``try`` blocks are an explicit exception
  — we descend one level so the ``try: import X; except ImportError: X = ...``
  pattern resolves.
* Re-exports are not followed across more than one hop. If module ``a``
  re-exports ``b.X``, importers of ``a.X`` will not see it resolved here.
  This bounds recursion and avoids subtle wrong answers.
* Multi-assignment is dynamic. If a name is bound more than once at module
  scope, it is dropped from the export set.
* Lookup failure falls through to caller. The caller decides what "unresolved"
  means in context (typically: keep treating the name as dynamic).
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

log = logging.getLogger(__name__)


class SymbolKind(StrEnum):
    STR_LITERAL = "str_literal"
    FUNCTION_DEF = "function_def"


@dataclass(frozen=True)
class Symbol:
    """A resolved module-level name.

    ``value`` is populated only for plain string-literal assignments; for
    implicit-concat literals (JoinedStr with no FormattedValue children) it
    is ``None`` but the kind is still STR_LITERAL.
    """

    kind: SymbolKind
    value: str | None = None


@dataclass
class ModuleSymbols:
    """Module-scope exports collected from one .py file."""

    file_path: Path
    module_path: str  # dotted, e.g. "myapp.prompts"
    exports: dict[str, Symbol] = field(default_factory=dict)
    star_imports_from: list[str] = field(default_factory=list)
    # Direct re-exports: name -> (other_module_path, original_name).
    # Followed at most one hop during resolution.
    re_exports: dict[str, tuple[str, str]] = field(default_factory=dict)


@dataclass
class PackageSymbolTable:
    """Symbol table for every .py file under a scan root."""

    scan_root: Path
    package_roots: list[Path] = field(default_factory=list)
    modules: dict[str, ModuleSymbols] = field(default_factory=dict)  # by dotted path
    by_file: dict[Path, ModuleSymbols] = field(default_factory=dict)

    @classmethod
    def build(cls, scan_root: Path, files: Iterable[Path]) -> PackageSymbolTable:
        roots = discover_package_roots(scan_root)
        table = cls(scan_root=scan_root, package_roots=roots)
        # Pre-compute most-specific package_root per file (single pass).
        file_to_root: dict[Path, Path] = {}
        for f in files:
            if f.suffix != ".py":
                continue
            best = _pick_package_root_for(f, roots)
            if best is not None:
                file_to_root[f] = best
        # §2.3 conflict resolution: iterate roots in low-to-high precedence
        # order; on key collision the src-layout entry overwrites the flat
        # one. See §2.3 in PR-4-src-layout.md for full rationale.
        for pkg_root in roots:
            for f, root in file_to_root.items():
                if root != pkg_root:
                    continue
                mod_path = file_to_module_path(f, pkg_root)
                if mod_path is None:
                    continue
                symbols = _scan_module(f, mod_path)
                if symbols is None:
                    continue
                table.modules[mod_path] = symbols
                table.by_file[f] = symbols
        return table

    def module_path_for(self, file: Path) -> str | None:
        """Dotted module path for ``file`` per the discovered package roots."""
        pkg_root = _pick_package_root_for(file, self.package_roots)
        return file_to_module_path(file, pkg_root) if pkg_root else None


@dataclass
class CrossModuleResolver:
    """Per-file resolver: maps in-file names to their cross-module definitions.

    Built from one file's AST imports and the global ``PackageSymbolTable``.
    Two query methods cover the two syntactic shapes that appear in prompt
    expressions: bare ``Name`` (``from prompts import X``) and ``Attribute``
    (``import prompts; prompts.X``).
    """

    file_module_path: str
    # alias-in-current-file -> (other_module_path, name-in-other-module)
    direct_imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    # alias-in-current-file -> other_module_path (for ``import X [as Y]``)
    module_aliases: dict[str, str] = field(default_factory=dict)
    # module paths starred (``from prompts import *``)
    star_imports: list[str] = field(default_factory=list)
    table: PackageSymbolTable | None = None

    def resolves_to_static(self, name: str) -> bool:
        """True if ``name`` resolves to a literal or function in another module."""
        if self.table is None:
            return False
        # Direct import path (last-import-wins semantics already baked in
        # by how we built direct_imports — see _build_resolver).
        target = self.direct_imports.get(name)
        if target is not None:
            mod_path, orig_name = target
            return self._lookup_in_module(mod_path, orig_name) is not None
        # Star imports: try each starred module in order.
        for mod_path in self.star_imports:
            if self._lookup_in_module(mod_path, name) is not None:
                return True
        return False

    def attribute_resolves_to_static(self, mod_alias: str, name: str) -> bool:
        """True for ``mod_alias.name`` where ``mod_alias`` is an imported module."""
        if self.table is None:
            return False
        mod_path = self.module_aliases.get(mod_alias)
        if mod_path is None:
            return False
        return self._lookup_in_module(mod_path, name) is not None

    def _lookup_in_module(self, mod_path: str, name: str) -> Symbol | None:
        if self.table is None:
            return None
        mod = self.table.modules.get(mod_path)
        if mod is None:
            return None
        sym = mod.exports.get(name)
        if sym is not None:
            return sym
        # One-hop re-export follow: if mod re-exports `name` from another
        # module, look there too. Bounded depth keeps cycles harmless.
        re_export = mod.re_exports.get(name)
        if re_export is not None:
            other_mod, other_name = re_export
            other = self.table.modules.get(other_mod)
            if other is not None:
                return other.exports.get(other_name)
        return None


# ---------- file-path / module-path helpers --------------------------------


def discover_package_roots(scan_root: Path) -> list[Path]:
    """Return the package roots from which module paths are computed.

    Pure flat → ``[scan_root]``. Pure src → ``[scan_root/src]``. Mixed →
    ``[scan_root, scan_root/src]`` in low-to-high precedence order so
    src-layout wins on key collisions per §2.3. Also emits §1.1.1's
    user-named-src warning when ``src/__init__.py`` exists but src-layout
    detection rejects (no subdir contains ``.py`` files).
    """
    src = scan_root / "src"
    def _has_py_pkg(d: Path) -> bool:
        return d.is_dir() and any(c.is_dir() and any(c.rglob("*.py")) for c in d.iterdir())
    if not _has_py_pkg(src):
        if (src / "__init__.py").exists():
            log.warning("flat-layout detected with top-level package literally named 'src'; this is unusual and may indicate a project misconfiguration")
        return [scan_root]
    has_root_pkg = any(
        c.is_dir() and c.name != "src" and any(c.rglob("*.py")) for c in scan_root.iterdir()
    )
    return [scan_root, src] if has_root_pkg else [src]


def _pick_package_root_for(file: Path, roots: list[Path]) -> Path | None:
    """Return the most-specific root containing ``file``; log+None on symlink-escape (§1.2.1)."""
    file_r = file.resolve()
    matching = []
    for r in roots:
        try:
            file_r.relative_to(r.resolve())
            matching.append(r)
        except ValueError:
            pass
    if not matching:
        log.debug("skipping %s: not under package_root %s", file, roots)
        return None
    return max(matching, key=lambda r: len(r.resolve().parts))


def file_to_module_path(file: Path, package_root: Path) -> str | None:
    """Return a dotted module path for ``file`` relative to ``package_root``.

    ``__init__.py`` collapses to its directory. Files whose resolved path
    escapes ``package_root`` (e.g. symlinks pointing outside the scan root,
    per §1.2.1) are skipped with a debug log. An orphan ``__init__.py``
    at the package root itself (parts == ["__init__"]) is skipped with a
    warning per §1.1.1 (mixed orphan case).

    Module-path comparison is case-sensitive in both directions, mirroring
    Python's import system regardless of filesystem case-sensitivity (§1.2.2).
    """
    try:
        rel = file.resolve().relative_to(package_root.resolve())
    except ValueError:
        log.debug("skipping %s: not under package_root %s", file, package_root)
        return None
    parts = list(rel.with_suffix("").parts)
    if parts == ["__init__"]:
        log.warning("orphan __init__.py at package root %s; skipping", file)
        return None
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def resolve_relative_module_path(
    file_module_path: str,
    level: int,
    module: str | None,
) -> str | None:
    """Resolve a ``from <dots><module> import ...`` to an absolute dotted path.

    ``level`` is ``ast.ImportFrom.level`` (0 = absolute, 1 = same package,
    2 = parent package, ...). ``module`` is ``ast.ImportFrom.module``
    (the bit after the dots, possibly None for ``from . import X``).
    """
    if level == 0:
        return module
    parts = file_module_path.split(".") if file_module_path else []
    # Step 1: drop the file's own module-name segment (we're now at the package).
    if parts:
        parts = parts[:-1]
    # Step 2: each dot beyond the first peels one more parent.
    extra = level - 1
    if extra > len(parts):
        return None  # going above the scan root — Python would raise too.
    if extra > 0:
        parts = parts[: len(parts) - extra]
    if module:
        parts.append(module)
    return ".".join(parts) if parts else None


# ---------- private: walk a module to extract exports ----------------------


def _scan_module(file: Path, module_path: str) -> ModuleSymbols | None:
    try:
        source = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        tree = ast.parse(source, filename=str(file))
    except SyntaxError:
        return None

    symbols = ModuleSymbols(file_path=file, module_path=module_path)
    exports: dict[str, Symbol] = {}
    assign_count: dict[str, int] = {}

    def record_assign(name: str, sym: Symbol | None) -> None:
        assign_count[name] = assign_count.get(name, 0) + 1
        if assign_count[name] > 1 or sym is None:
            exports.pop(name, None)
            return
        exports[name] = sym

    def visit_top_level(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                record_assign(stmt.name, Symbol(kind=SymbolKind.FUNCTION_DEF))
            elif isinstance(stmt, ast.Assign):
                sym = _value_to_symbol(stmt.value)
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        record_assign(target.id, sym)
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                sym = _value_to_symbol(stmt.value) if stmt.value is not None else None
                record_assign(stmt.target.id, sym)
            elif isinstance(stmt, ast.ImportFrom):
                # Track re-exports for one-hop resolution. Only handles
                # absolute imports here; relative ones would need the file's
                # own module_path which we have — but adding that complexity
                # for a 1-hop fallback isn't worth it yet.
                if stmt.level == 0 and stmt.module:
                    for alias in stmt.names:
                        if alias.name == "*":
                            symbols.star_imports_from.append(stmt.module)
                            continue
                        local = alias.asname or alias.name
                        symbols.re_exports[local] = (stmt.module, alias.name)
            elif isinstance(stmt, ast.Try):
                # ``try: from prompts import X; except: X = "..."`` is a common
                # optional-dependency pattern — treat both branches as if at
                # top level. To avoid the multi-assign-marks-dynamic rule
                # tripping when both branches define the same name, we use a
                # nested counter so each name counts once per branch combined.
                _scan_try_block(stmt, exports, assign_count, symbols)

    visit_top_level(tree.body)
    symbols.exports = exports
    return symbols


def _scan_try_block(
    node: ast.Try,
    exports: dict[str, Symbol],
    assign_count: dict[str, int],
    symbols: ModuleSymbols,
) -> None:
    """Descend into a top-level ``try`` so optional-import patterns resolve.

    We unify all branches: each name's count is incremented at most once for
    the whole block, even if both ``try.body`` and ``try.handlers[i].body``
    define it. If every branch defines the same literal-or-import, we keep
    it. If any branch makes it dynamic, the whole name becomes dynamic.
    """
    names_seen_in_block: set[str] = set()

    def record_in_block(name: str, sym: Symbol | None) -> None:
        if name in names_seen_in_block:
            # Same name in another branch of the same try. If the existing
            # export is static and the new branch also delivers a static
            # value, keep the existing one; otherwise demote.
            if sym is None:
                exports.pop(name, None)
            return
        names_seen_in_block.add(name)
        assign_count[name] = assign_count.get(name, 0) + 1
        if assign_count[name] > 1 or sym is None:
            exports.pop(name, None)
            return
        exports[name] = sym

    branches: list[list[ast.stmt]] = [node.body]
    for handler in node.handlers:
        branches.append(handler.body)
    if node.orelse:
        branches.append(node.orelse)
    if node.finalbody:
        branches.append(node.finalbody)

    for branch in branches:
        for stmt in branch:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                record_in_block(stmt.name, Symbol(kind=SymbolKind.FUNCTION_DEF))
            elif isinstance(stmt, ast.Assign):
                sym = _value_to_symbol(stmt.value)
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        record_in_block(target.id, sym)
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                sym = _value_to_symbol(stmt.value) if stmt.value is not None else None
                record_in_block(stmt.target.id, sym)
            elif isinstance(stmt, ast.ImportFrom):
                if stmt.level == 0 and stmt.module:
                    for alias in stmt.names:
                        if alias.name == "*":
                            symbols.star_imports_from.append(stmt.module)
                            continue
                        local = alias.asname or alias.name
                        symbols.re_exports[local] = (stmt.module, alias.name)
                        # Also treat as a static-resolvable export by way of
                        # the re-export hop. This is what lets ``try: from
                        # prompts import SYSTEM_PROMPT`` count as a defined
                        # export for that name.
                        record_in_block(local, Symbol(kind=SymbolKind.STR_LITERAL))


def _value_to_symbol(value: ast.expr) -> Symbol | None:
    """Map an assignment RHS to a Symbol, or None if not statically a literal."""
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return Symbol(kind=SymbolKind.STR_LITERAL, value=value.value)
    if isinstance(value, ast.JoinedStr) and _joined_is_constant(value):
        return Symbol(kind=SymbolKind.STR_LITERAL, value=None)
    return None


def _joined_is_constant(expr: ast.JoinedStr) -> bool:
    return all(isinstance(v, ast.Constant) for v in expr.values)


# ---------- build a per-file resolver from a parsed AST --------------------


def build_resolver(
    tree: ast.Module,
    file_module_path: str,
    table: PackageSymbolTable | None,
) -> CrossModuleResolver:
    """Inspect top-level imports in ``tree`` and produce a resolver for this file.

    Python's import semantics are last-binding-wins for the importing scope,
    so we walk top-level imports (and top-level ``try`` blocks) and overwrite
    earlier entries with later ones.
    """
    resolver = CrossModuleResolver(file_module_path=file_module_path, table=table)

    def _ingest_import(stmt: ast.Import) -> None:
        for alias in stmt.names:
            mod_path = alias.name
            local = alias.asname or alias.name.split(".")[0]
            resolver.module_aliases[local] = mod_path

    def _ingest_import_from(stmt: ast.ImportFrom) -> None:
        target_mod = resolve_relative_module_path(
            file_module_path,
            stmt.level or 0,
            stmt.module,
        )
        if target_mod is None:
            return
        for alias in stmt.names:
            if alias.name == "*":
                resolver.star_imports.append(target_mod)
                continue
            local = alias.asname or alias.name
            resolver.direct_imports[local] = (target_mod, alias.name)

    def _walk_top(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.Import):
                _ingest_import(stmt)
            elif isinstance(stmt, ast.ImportFrom):
                _ingest_import_from(stmt)
            elif isinstance(stmt, ast.Try):
                _walk_top(stmt.body)
                for handler in stmt.handlers:
                    _walk_top(handler.body)
                if stmt.orelse:
                    _walk_top(stmt.orelse)
                if stmt.finalbody:
                    _walk_top(stmt.finalbody)

    _walk_top(tree.body)
    return resolver
