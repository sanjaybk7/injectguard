"""Tests for Jupyter notebook (.ipynb) scanning."""

from __future__ import annotations

from pathlib import Path

from agentguard.engine import Scanner
from agentguard.notebook import load_notebook
from agentguard.output import format_json, format_pretty

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_notebook_extracts_code_cells() -> None:
    nb = load_notebook(FIXTURES / "vulnerable" / "notebook_confused_deputy.ipynb")
    assert nb is not None
    # Markdown cells should not appear in the source.
    assert "Email assistant agent" not in nb.source
    # Code from all 3 code cells should appear.
    assert "from langgraph.prebuilt import create_react_agent" in nb.source
    assert "def read_email" in nb.source
    assert "def send_email" in nb.source
    assert "create_react_agent" in nb.source


def test_load_notebook_sanitizes_magics_and_shell_escapes() -> None:
    nb = load_notebook(FIXTURES / "vulnerable" / "notebook_with_magics.ipynb")
    assert nb is not None
    # Magic + shell lines stripped (line numbering preserved by blank replacement).
    assert "%pip install" not in nb.source
    assert '!echo "setting up"' not in nb.source
    # Real Python code preserved.
    assert "from langchain_core.tools import tool" in nb.source


def test_notebook_findings_remap_to_cell_index() -> None:
    result = Scanner(include_tests=True).scan(
        FIXTURES / "vulnerable" / "notebook_confused_deputy.ipynb"
    )
    rule_ids = {f.rule_id for f in result.findings}
    assert "IG001" in rule_ids
    ig001 = [f for f in result.findings if f.rule_id == "IG001"]
    # The agent definition is in the 3rd code cell (index 2).
    assert any(f.location.column == 2 for f in ig001), (
        f"expected IG001 to point at code cell index 2 (the agent definition), "
        f"got cells: {[f.location.column for f in ig001]}"
    )


def test_notebook_with_magics_still_finds_issues() -> None:
    result = Scanner(include_tests=True).scan(
        FIXTURES / "vulnerable" / "notebook_with_magics.ipynb"
    )
    assert "IG001" in {f.rule_id for f in result.findings}


def test_safe_notebook_with_interrupt_no_findings() -> None:
    result = Scanner(include_tests=True).scan(FIXTURES / "safe" / "notebook_gated.ipynb")
    assert "IG001" not in {f.rule_id for f in result.findings}


def test_pretty_output_renders_cell_info() -> None:
    """Smoke test: pretty formatter doesn't crash on notebook locations."""
    result = Scanner(include_tests=True).scan(
        FIXTURES / "vulnerable" / "notebook_confused_deputy.ipynb"
    )
    # Capture rich output to a buffer to check the cell rendering.
    from io import StringIO

    from rich.console import Console

    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False)
    format_pretty(result, console=console)
    text = buf.getvalue()
    assert "cell[" in text, f"expected cell[N] in pretty output, got:\n{text}"


def test_json_output_includes_cell_field_for_notebooks() -> None:
    import json

    result = Scanner(include_tests=True).scan(
        FIXTURES / "vulnerable" / "notebook_confused_deputy.ipynb"
    )
    payload = json.loads(format_json(result))
    assert payload["findings"]
    for f in payload["findings"]:
        assert f["location"]["file"].endswith(".ipynb")
        assert "cell" in f["location"]
        assert isinstance(f["location"]["cell"], int)


def test_directory_scan_picks_up_notebooks() -> None:
    """When scanning a directory, both .py and .ipynb files are picked up."""
    result = Scanner(include_tests=True).scan(FIXTURES / "vulnerable")
    notebook_findings = [
        f for f in result.findings if str(f.location.file).endswith(".ipynb")
    ]
    py_findings = [f for f in result.findings if str(f.location.file).endswith(".py")]
    assert notebook_findings, "expected at least one finding from .ipynb files"
    assert py_findings, "expected at least one finding from .py files"
