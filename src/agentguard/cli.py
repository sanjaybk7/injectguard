"""agentguard command-line interface."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from agentguard import __version__
from agentguard.engine import Scanner
from agentguard.output import format_json, format_pretty, format_sarif

app = typer.Typer(
    name="agentguard",
    help="Static analyzer for prompt-injection and confused-deputy risks in LLM agent code.",
    no_args_is_help=True,
    add_completion=False,
)


class OutputFormat(StrEnum):
    pretty = "pretty"
    sarif = "sarif"
    json = "json"


@app.command()
def scan(
    target: Annotated[
        Path,
        typer.Argument(exists=True, readable=True, help="File or directory to scan."),
    ],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format."),
    ] = OutputFormat.pretty,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write output to a file instead of stdout."),
    ] = None,
    fail_on: Annotated[
        str,
        typer.Option(
            "--fail-on",
            help="Minimum severity that causes a non-zero exit. One of: critical, high, medium, low, info, none.",
        ),
    ] = "high",
    include_tests: Annotated[
        bool,
        typer.Option(
            "--include-tests/--no-include-tests",
            help="Include test files (test_*.py, *_test.py, conftest.py, files under tests/). Skipped by default to reduce noise from intentionally-vulnerable test fixtures.",
        ),
    ] = False,
) -> None:
    """Scan a path for AI-agent security issues."""
    scanner = Scanner(include_tests=include_tests)
    result = scanner.scan(target)

    if output_format == OutputFormat.pretty:
        console = Console(file=output.open("w") if output else None)
        format_pretty(result, console=console)
    else:
        text = format_sarif(result) if output_format == OutputFormat.sarif else format_json(result)
        if output:
            output.write_text(text, encoding="utf-8")
        else:
            typer.echo(text)

    raise typer.Exit(code=_exit_code(result, fail_on))


@app.command()
def version() -> None:
    """Print the installed agentguard version."""
    typer.echo(f"agentguard {__version__}")


def _exit_code(result: object, fail_on: str) -> int:
    from agentguard.engine import ScanResult
    from agentguard.ir import Severity

    if not isinstance(result, ScanResult):
        return 0

    threshold = fail_on.lower()
    if threshold == "none":
        return 0

    order = ["info", "low", "medium", "high", "critical"]
    if threshold not in order:
        return 0
    threshold_idx = order.index(threshold)
    sev_to_idx = {s.value: order.index(s.value) for s in Severity}
    for f in result.findings:
        if sev_to_idx.get(f.severity.value, -1) >= threshold_idx:
            return 1
    return 0


if __name__ == "__main__":
    app()
