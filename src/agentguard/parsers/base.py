"""Common base for framework-specific parsers."""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from agentguard.ir import Agent, Tool
from agentguard.taxonomy import Taxonomy

# Functions exported by agent SDKs that wrap a prompt without introducing taint.
# Example: openai-agents-python's `prompt_with_handoff_instructions(prompt)` —
# documented helper that prepends boilerplate; trust passes through to the arg.
SAFE_PROMPT_HELPERS: frozenset[str] = frozenset({
    "prompt_with_handoff_instructions",
})


class FrameworkParser(ABC):
    """Base class for parsers that translate one framework's code into IR."""

    framework: str

    def __init__(self, taxonomy: Taxonomy | None = None) -> None:
        self.taxonomy = taxonomy or Taxonomy.load()

    @abstractmethod
    def matches_file(self, source: str, tree: ast.Module) -> bool:
        """Return True if this file looks like it uses this framework.

        Implementations typically check for relevant imports.
        """
        raise NotImplementedError

    @abstractmethod
    def extract(self, path: Path, source: str, tree: ast.Module) -> tuple[list[Tool], list[Agent]]:
        """Extract tools and agents from an already-parsed file."""
        raise NotImplementedError

    def parse_file(self, path: Path) -> tuple[list[Tool], list[Agent]]:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return [], []
        return self.parse_source(path, source)

    def parse_source(self, path: Path, source: str) -> tuple[list[Tool], list[Agent]]:
        """Parse already-loaded source. Used by notebook flow which extracts source first."""
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            return [], []
        if not self.matches_file(source, tree):
            return [], []
        return self.extract(path, source, tree)


def collect_imports(tree: ast.Module) -> set[str]:
    """Return the set of dotted module names imported by a file.

    `from foo.bar import baz` contributes both `foo.bar` and `foo.bar.baz`.
    """
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
                for alias in node.names:
                    imports.add(f"{node.module}.{alias.name}")
    return imports


def decorator_base_name(dec: ast.expr) -> str | None:
    """Return the simple name of a decorator, regardless of call/attribute form."""
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Call):
        return decorator_base_name(dec.func)
    return None


def call_base_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def names_in(expr: ast.expr) -> list[str]:
    names: list[str] = []
    for n in ast.walk(expr):
        if isinstance(n, ast.Name):
            names.append(n.id)
    return names


@dataclass
class ModuleContext:
    """Module-level facts a parser collects up-front, used to disambiguate prompts.

    Knowing whether a Name resolves to a string constant, a function definition,
    or something unknown is the difference between flagging a real dynamic
    prompt and flagging a perfectly safe `instructions=PROMPT_CONSTANT`.
    """

    string_constants: dict[str, ast.Constant] = field(default_factory=dict)
    function_defs: set[str] = field(default_factory=set)


def collect_module_context(tree: ast.Module) -> ModuleContext:
    """Walk top-level statements to record string-constant assignments and function defs.

    We only look at module-scope assignments, since constants used as prompts are
    overwhelmingly defined at module scope. Walking deeper introduces noise.
    """
    ctx = ModuleContext()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ctx.function_defs.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            value = stmt.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        ctx.string_constants[target.id] = value
            elif isinstance(value, ast.JoinedStr) and _joined_str_is_constant(value):
                # Implicit-concat string literals show up as JoinedStr with no
                # FormattedValue children; treat them as effectively constant.
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        # Safe placeholder — we don't need the actual Constant node downstream.
                        ctx.string_constants[target.id] = ast.Constant(value="")
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            ann_value = stmt.value
            if isinstance(ann_value, ast.Constant) and isinstance(ann_value.value, str):
                ctx.string_constants[stmt.target.id] = ann_value
    return ctx


def _joined_str_is_constant(expr: ast.JoinedStr) -> bool:
    """An f-string with no FormattedValue children is just a multi-part literal."""
    return all(isinstance(v, ast.Constant) for v in expr.values)


def classify_prompt_expr(
    expr: ast.expr,
    module: ModuleContext | None = None,
) -> tuple[bool, list[str]]:
    """Return (is_dynamic, list_of_taint_source_names) for a prompt expression.

    When `module` is provided, Name nodes that resolve to string constants or
    function definitions in that module are treated as static. This collapses
    the most common false-positive class observed in real-world agent code:
    `instructions=MY_PROMPT` where `MY_PROMPT = "..."` lives at module scope.
    """
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return False, []

    if isinstance(expr, ast.JoinedStr):  # f-string
        if _joined_str_is_constant(expr):
            return False, []
        sources: list[str] = []
        for value in expr.values:
            if isinstance(value, ast.FormattedValue):
                inner_names = names_in(value.value)
                # If every interpolated name is a known string constant, treat as static.
                if module and all(n in module.string_constants for n in inner_names):
                    continue
                sources.extend(
                    n for n in inner_names if not module or n not in module.string_constants
                )
        if not sources:
            return False, []
        return True, sources

    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        all_names = names_in(expr)
        if module and all(n in module.string_constants for n in all_names):
            return False, []
        return True, [n for n in all_names if not module or n not in module.string_constants]

    if isinstance(expr, ast.Call):
        # Safe SDK helpers: trust passes through to the wrapped argument.
        func_name = call_base_name(expr)
        if func_name and func_name in SAFE_PROMPT_HELPERS:
            if expr.args:
                return classify_prompt_expr(expr.args[0], module)
            return False, []
        # str.format(...) — if the template is a known string constant
        # AND every interpolated value is a known constant, it's static.
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "format":
            arg_names = names_in(expr)
            if module and all(n in module.string_constants for n in arg_names):
                return False, []
            return True, [
                n for n in arg_names if not module or n not in module.string_constants
            ]
        all_names = names_in(expr)
        return True, [
            n for n in all_names if not module or n not in module.string_constants
        ]

    if isinstance(expr, ast.Name):
        if module and expr.id in module.string_constants:
            return False, []
        # Function reference (callable-as-instructions) is the canonical SDK
        # pattern for context-aware prompts in OpenAI Agents SDK; treat as safe.
        if module and expr.id in module.function_defs:
            return False, []
        return True, [expr.id]

    return True, names_in(expr)
