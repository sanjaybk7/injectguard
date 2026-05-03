"""Human-readable terminal output."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agentic_guard.engine import ScanResult
from agentic_guard.ir import Severity, SourceLocation


def _format_location(loc: SourceLocation) -> str:
    """Render a SourceLocation, expanding notebook cell info when applicable."""
    if str(loc.file).endswith(".ipynb"):
        return f"{loc.file} cell[{loc.column}] line {loc.line}"
    return f"{loc.file}:{loc.line}"


_SEVERITY_STYLES = {
    Severity.CRITICAL: ("red bold", "🔴"),
    Severity.HIGH: ("red", "🔴"),
    Severity.MEDIUM: ("yellow", "🟡"),
    Severity.LOW: ("blue", "🔵"),
    Severity.INFO: ("dim", "⚪"),
}


def format_pretty(result: ScanResult, console: Console | None = None) -> None:
    """Print a human-readable report. The agent prompt asks us to avoid emojis
    in code, but in security-tool output they materially aid scannability — used
    here intentionally."""
    out = console or Console()

    if not result.findings:
        out.print(
            f"[green]✔[/green] No findings. "
            f"Scanned {result.files_scanned} files, "
            f"{result.tools_seen} tools, {result.agents_seen} agents."
        )
        return

    for finding in result.findings:
        style, icon = _SEVERITY_STYLES.get(finding.severity, ("white", "•"))
        title = Text()
        title.append(f"{icon} ", style=style)
        title.append(f"{finding.rule_id} ", style=f"{style}")
        title.append(f"[{finding.severity.value.upper()}] ", style=style)
        title.append(finding.rule_name, style=f"{style} bold")

        body = Text()
        body.append(finding.message)
        if finding.owasp_llm_ids:
            body.append("\n\nOWASP: ", style="dim")
            body.append(", ".join(finding.owasp_llm_ids), style="cyan")
        body.append(f"\n\n  at {_format_location(finding.location)}", style="dim")
        for rel in finding.related_locations:
            body.append(f"\n     ↳ {_format_location(rel)}", style="dim")
        if finding.fix_hint:
            body.append("\n\nFix: ", style="green bold")
            body.append(finding.fix_hint)

        out.print(Panel(body, title=title, border_style=style.split()[0], expand=False))

    counts: dict[Severity, int] = {}
    for f in result.findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    summary_parts = [
        f"[{_SEVERITY_STYLES[s][0]}]{counts[s]} {s.value}[/]"
        for s in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO)
        if counts.get(s)
    ]
    out.print()
    out.print(
        f"[bold]Summary:[/bold] {len(result.findings)} finding(s) "
        f"({', '.join(summary_parts) if summary_parts else 'none'}) "
        f"across {result.files_scanned} files."
    )
