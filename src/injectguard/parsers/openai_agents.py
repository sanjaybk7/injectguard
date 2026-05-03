"""OpenAI Agents SDK parser.

Recognizes:
  - Functions decorated with `@function_tool` from the `agents` package
  - `Agent(...)` constructor calls (when the file imports from `agents`)
  - System prompts via `instructions=` arg
  - Human-approval gates:
      * `tool_use_behavior="stop_on_first_tool"` — gates ALL sinks (loop halts after one call)
      * `tool_use_behavior=StopAtTools(stop_at_tool_names=[...])` — gates the named tools
      * `is_enabled=False` on a `@function_tool(...)` — tool effectively disabled

Note: the SDK exports `Agent`, which is a generic name. To avoid false matches,
this parser only fires when the file imports from `agents` (or `openai_agents`).
"""

from __future__ import annotations

import ast
from pathlib import Path

from injectguard.ir import Agent, SourceLocation, Tool, ToolClassification
from injectguard.parsers.base import (
    FrameworkParser,
    ModuleContext,
    call_base_name,
    classify_prompt_expr,
    collect_imports,
    collect_module_context,
    decorator_base_name,
)

_TOOL_DECORATOR_NAMES = {"function_tool", "FunctionTool"}
_AGENT_CLASS_NAMES = {"Agent"}
_RELEVANT_IMPORT_PREFIXES = ("agents", "openai_agents")


class OpenAIAgentsParser(FrameworkParser):
    """Parse a Python source file into OpenAI Agents SDK IR."""

    framework = "openai-agents"

    def matches_file(self, source: str, tree: ast.Module) -> bool:
        imports = collect_imports(tree)
        # Require an explicit import from the agents package; `Agent` is too
        # common a name to assume otherwise.
        for imp in imports:
            for prefix in _RELEVANT_IMPORT_PREFIXES:
                if imp == prefix or imp.startswith(prefix + "."):
                    return True
        return False

    def extract(self, path: Path, source: str, tree: ast.Module) -> tuple[list[Tool], list[Agent]]:
        module_ctx = collect_module_context(tree)
        visitor = _Visitor(path=path, taxonomy=self.taxonomy, module_ctx=module_ctx)
        visitor.visit(tree)
        return visitor.tools, visitor.agents


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path, taxonomy: object, module_ctx: ModuleContext) -> None:
        from injectguard.taxonomy import Taxonomy

        assert isinstance(taxonomy, Taxonomy)
        self.path = path
        self.taxonomy = taxonomy
        self.module_ctx = module_ctx
        self.tools: list[Tool] = []
        self.agents: list[Agent] = []
        self._tools_by_name: dict[str, Tool] = {}

    # -- tools ------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._maybe_register_tool(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._maybe_register_tool(node)
        self.generic_visit(node)

    def _maybe_register_tool(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        decorator = self._find_tool_decorator(node)
        if decorator is None:
            return

        tool_name = self._tool_name_override(decorator) or node.name
        description = self._tool_description_override(decorator) or ast.get_docstring(node)
        entry = self.taxonomy.classify(tool_name, description)
        is_enabled = self._tool_is_enabled(decorator)

        loc = SourceLocation(
            file=self.path,
            line=node.lineno,
            column=node.col_offset,
            end_line=getattr(node, "end_lineno", None),
            end_column=getattr(node, "end_col_offset", None),
        )

        if entry is None:
            tool = Tool(
                name=tool_name,
                location=loc,
                classification=ToolClassification.NEUTRAL,
                description=description,
                raw_decorator=self._decorator_repr(decorator),
                requires_approval=not is_enabled,
            )
        else:
            tool = Tool(
                name=tool_name,
                location=loc,
                classification=entry.classification,
                privilege=entry.privilege,
                trust_of_output=entry.trust_of_output,
                reversible=entry.reversible,
                description=description,
                raw_decorator=self._decorator_repr(decorator),
                matched_pattern=entry.pattern,
                requires_approval=not is_enabled,
            )
        self.tools.append(tool)
        self._tools_by_name[tool_name] = tool

    def _find_tool_decorator(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> ast.expr | None:
        for dec in node.decorator_list:
            if decorator_base_name(dec) in _TOOL_DECORATOR_NAMES:
                return dec
        return None

    def _tool_name_override(self, decorator: ast.expr) -> str | None:
        if not isinstance(decorator, ast.Call):
            return None
        for kw in decorator.keywords:
            if kw.arg in ("name_override", "name") and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    return kw.value.value
        return None

    def _tool_description_override(self, decorator: ast.expr) -> str | None:
        if not isinstance(decorator, ast.Call):
            return None
        for kw in decorator.keywords:
            if kw.arg in ("description_override", "description") and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    return kw.value.value
        return None

    def _tool_is_enabled(self, decorator: ast.expr) -> bool:
        if not isinstance(decorator, ast.Call):
            return True
        for kw in decorator.keywords:
            if kw.arg == "is_enabled" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, bool):
                    return kw.value.value
        return True

    def _decorator_repr(self, decorator: ast.expr) -> str:
        try:
            return ast.unparse(decorator)
        except Exception:
            return decorator_base_name(decorator) or "function_tool"

    # -- agents -----------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        if call_base_name(node) in _AGENT_CLASS_NAMES:
            self._register_agent(node)
        self.generic_visit(node)

    def _register_agent(self, node: ast.Call) -> None:
        loc = SourceLocation(
            file=self.path,
            line=node.lineno,
            column=node.col_offset,
            end_line=getattr(node, "end_lineno", None),
            end_column=getattr(node, "end_col_offset", None),
        )

        tool_names = self._extract_tool_names(node)
        agent_tools = [self._tools_by_name[n] for n in tool_names if n in self._tools_by_name]

        prompt_loc, prompt_dynamic, prompt_taint = self._analyze_prompt(node)
        gates_all_sinks, gated_tool_names = self._analyze_tool_use_behavior(node)

        # Apply per-agent gates back onto the tool objects so rules can read them.
        if gates_all_sinks:
            for t in agent_tools:
                if t.is_sink:
                    t.requires_approval = True
        for name in gated_tool_names:
            if name in self._tools_by_name:
                self._tools_by_name[name].requires_approval = True

        agent_name = self._extract_string(node, "name") or "Agent"
        agent = Agent(
            name=agent_name,
            location=loc,
            framework="openai-agents",
            tools=agent_tools,
            system_prompt_location=prompt_loc,
            system_prompt_is_dynamic=prompt_dynamic,
            system_prompt_taint_sources=prompt_taint,
            interrupts_before=list(gated_tool_names) if not gates_all_sinks else [t.name for t in agent_tools if t.is_sink],
        )
        self.agents.append(agent)

    def _extract_tool_names(self, node: ast.Call) -> list[str]:
        tools_arg: ast.expr | None = None
        for kw in node.keywords:
            if kw.arg == "tools":
                tools_arg = kw.value
                break
        if not isinstance(tools_arg, (ast.List, ast.Tuple, ast.Set)):
            return []
        names: list[str] = []
        for elt in tools_arg.elts:
            if isinstance(elt, ast.Name):
                names.append(elt.id)
            elif isinstance(elt, ast.Attribute):
                names.append(elt.attr)
        return names

    def _extract_string(self, node: ast.Call, kw_name: str) -> str | None:
        for kw in node.keywords:
            if kw.arg == kw_name and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    return kw.value.value
        return None

    def _analyze_prompt(
        self, node: ast.Call
    ) -> tuple[SourceLocation | None, bool, list[str]]:
        prompt_arg: ast.expr | None = None
        for kw in node.keywords:
            if kw.arg in ("instructions", "system_instructions"):
                prompt_arg = kw.value
                break
        if prompt_arg is None:
            return None, False, []
        loc = SourceLocation(
            file=self.path,
            line=prompt_arg.lineno,
            column=prompt_arg.col_offset,
            end_line=getattr(prompt_arg, "end_lineno", None),
            end_column=getattr(prompt_arg, "end_col_offset", None),
        )
        dynamic, sources = classify_prompt_expr(prompt_arg, module=self.module_ctx)
        return loc, dynamic, sources

    def _analyze_tool_use_behavior(self, node: ast.Call) -> tuple[bool, list[str]]:
        """Return (gates_all_sinks, list_of_specifically_gated_tool_names)."""
        for kw in node.keywords:
            if kw.arg != "tool_use_behavior":
                continue
            value = kw.value
            if isinstance(value, ast.Constant) and value.value == "stop_on_first_tool":
                return True, []
            if isinstance(value, ast.Call) and call_base_name(value) == "StopAtTools":
                return False, _stop_at_tools_names(value)
        return False, []


def _stop_at_tools_names(call: ast.Call) -> list[str]:
    """Pull tool names out of a `StopAtTools(stop_at_tool_names=[...])` call."""
    target: ast.expr | None = None
    for kw in call.keywords:
        if kw.arg in ("stop_at_tool_names", "tool_names", "names"):
            target = kw.value
            break
    if target is None and call.args:
        target = call.args[0]
    if not isinstance(target, (ast.List, ast.Tuple, ast.Set)):
        return []
    out: list[str] = []
    for elt in target.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            out.append(elt.value)
    return out
