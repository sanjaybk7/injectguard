"""Top-level scanner: walks a path, parses files, runs rules, returns findings."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from agentguard.ir import Agent, Finding, SourceLocation, Tool
from agentguard.notebook import load_notebook
from agentguard.parsers import LangGraphParser, OpenAIAgentsParser
from agentguard.parsers.base import FrameworkParser
from agentguard.rules import all_rules
from agentguard.rules.base import Rule, RuleContext
from agentguard.taxonomy import Taxonomy

_PYTHON_EXTENSIONS = {".py"}
_NOTEBOOK_EXTENSIONS = {".ipynb"}
_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
}
_TEST_DIR_NAMES = {"tests", "test", "testing", "__tests__"}
_TEST_FILE_PREFIXES = ("test_",)
_TEST_FILE_SUFFIXES = ("_test.py",)
_TEST_FILE_EXACT = {"conftest.py"}


def _is_test_path(path: Path) -> bool:
    """Heuristic: does this path look like test code?

    Matches files in conventional test directories (tests/, test/, testing/),
    files named like pytest test modules (test_*.py, *_test.py, conftest.py).
    Test fixtures intentionally encode vulnerable patterns to exercise
    framework behavior; flagging them as production findings is noise.
    """
    if any(part in _TEST_DIR_NAMES for part in path.parts):
        return True
    name = path.name
    if name in _TEST_FILE_EXACT:
        return True
    if name.startswith(_TEST_FILE_PREFIXES):
        return True
    if name.endswith(_TEST_FILE_SUFFIXES):
        return True
    return False


@dataclass
class ScanResult:
    """Aggregate result of scanning one or more files."""

    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    tools_seen: int = 0
    agents_seen: int = 0

    @property
    def has_blocking(self) -> bool:
        from agentguard.ir import Severity

        blocking = {Severity.HIGH, Severity.CRITICAL}
        return any(f.severity in blocking for f in self.findings)


class Scanner:
    """Coordinates parsing and rule evaluation across a target path."""

    def __init__(
        self,
        taxonomy: Taxonomy | None = None,
        rules: Iterable[Rule] | None = None,
        parsers: Iterable[FrameworkParser] | None = None,
        include_tests: bool = False,
    ) -> None:
        self.taxonomy = taxonomy or Taxonomy.load()
        self.parsers: list[FrameworkParser] = (
            list(parsers)
            if parsers is not None
            else [
                LangGraphParser(taxonomy=self.taxonomy),
                OpenAIAgentsParser(taxonomy=self.taxonomy),
            ]
        )
        self.rules: list[Rule] = list(rules) if rules is not None else list(all_rules())
        self.include_tests = include_tests

    def scan(self, target: Path) -> ScanResult:
        result = ScanResult()
        all_tools: list[Tool] = []
        all_agents: list[Agent] = []
        # Notebook line-remap context, keyed by file path (only .ipynb files appear).
        notebook_line_maps: dict[Path, dict[int, tuple[int, int]]] = {}

        for file in self._iter_scannable_files(target):
            result.files_scanned += 1
            if file.suffix in _NOTEBOOK_EXTENSIONS:
                notebook = load_notebook(file)
                if notebook is None:
                    continue
                notebook_line_maps[file] = notebook.line_to_cell
                for parser in self.parsers:
                    tools, agents = parser.parse_source(file, notebook.source)
                    all_tools.extend(tools)
                    all_agents.extend(agents)
            else:
                for parser in self.parsers:
                    tools, agents = parser.parse_file(file)
                    all_tools.extend(tools)
                    all_agents.extend(agents)

        result.tools_seen = len(all_tools)
        result.agents_seen = len(all_agents)

        ctx = RuleContext(tools=all_tools, agents=all_agents, taxonomy=self.taxonomy)
        for rule in self.rules:
            for finding in rule.check(ctx):
                result.findings.append(_remap_notebook_lines(finding, notebook_line_maps))

        result.findings.sort(
            key=lambda f: (
                _severity_rank(f.severity),
                str(f.location.file),
                f.location.line,
            )
        )
        return result

    def _iter_scannable_files(self, target: Path) -> Iterable[Path]:
        if target.is_file():
            if target.suffix in _PYTHON_EXTENSIONS or target.suffix in _NOTEBOOK_EXTENSIONS:
                yield target
            return

        for ext in (*_PYTHON_EXTENSIONS, *_NOTEBOOK_EXTENSIONS):
            for path in target.rglob(f"*{ext}"):
                if any(part in _SKIP_DIRS for part in path.parts):
                    continue
                if not self.include_tests and _is_test_path(path):
                    continue
                yield path


def _remap_notebook_lines(
    finding: Finding,
    notebook_line_maps: dict[Path, dict[int, tuple[int, int]]],
) -> Finding:
    """If the finding is in a notebook, rewrite its location.line to encode cell info.

    We embed cell info into the SourceLocation by using the cell-relative line as
    the visible `line`, and the cell index as the `column`. Output formatters check
    file extension and render `notebook.ipynb:cell[3]:line 5` accordingly.
    """
    line_map = notebook_line_maps.get(finding.location.file)
    if line_map is None:
        return finding
    new_loc = _remap_location(finding.location, line_map)
    new_related = [_remap_location(loc, line_map) for loc in finding.related_locations]
    finding.location = new_loc
    finding.related_locations = new_related
    return finding


def _remap_location(
    loc: SourceLocation,
    line_map: dict[int, tuple[int, int]],
) -> SourceLocation:
    cell_info = line_map.get(loc.line)
    if cell_info is None:
        return loc
    cell_idx, cell_line = cell_info
    return SourceLocation(
        file=loc.file,
        line=cell_line,
        column=cell_idx,  # repurposed: notebook cell index
        end_line=None,
        end_column=None,
    )


def _severity_rank(severity: object) -> int:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return order.get(getattr(severity, "value", str(severity)), 99)
