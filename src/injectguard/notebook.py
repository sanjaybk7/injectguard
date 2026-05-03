"""Jupyter notebook (.ipynb) source extraction.

A notebook is JSON; we only care about its `code` cells. We concatenate them
into one virtual Python source string so the existing AST-based parsers can
operate on them unchanged. We also build a line-to-cell map so findings can
be reported with their original cell index.

We skip cells that contain only IPython magics or shell escapes (lines
starting with `!` or `%`). Mixed cells keep the non-magic lines and replace
magic/shell lines with empty lines so AST line numbers stay aligned.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import nbformat


@dataclass
class NotebookSource:
    """Concatenated Python source from a notebook + line-to-cell mapping."""

    source: str
    # For each line in `source` (1-indexed), the (cell_index, line_in_cell) it came from.
    # Cell index is 0-based across code cells only (markdown cells are skipped).
    line_to_cell: dict[int, tuple[int, int]]


def load_notebook(path: Path) -> NotebookSource | None:
    """Load and flatten a notebook into Python source. Returns None on read failure."""
    try:
        nb = nbformat.read(str(path), as_version=4)  # type: ignore[no-untyped-call]
    except Exception:
        return None

    parts: list[str] = []
    line_map: dict[int, tuple[int, int]] = {}
    current_line = 1
    code_cell_idx = 0

    for cell in nb.cells:
        if cell.get("cell_type") != "code":
            continue

        cell_source = cell.get("source", "")
        if isinstance(cell_source, list):
            cell_source = "".join(cell_source)

        sanitized_lines: list[str] = []
        for cell_line_no, line in enumerate(cell_source.splitlines(), start=1):
            if _is_jupyter_magic(line):
                # Replace with blank line to preserve line numbering.
                sanitized_lines.append("")
            else:
                sanitized_lines.append(line)
            line_map[current_line] = (code_cell_idx, cell_line_no)
            current_line += 1

        parts.append("\n".join(sanitized_lines))
        # Cell separator — counts as one line in the merged source.
        parts.append("")
        line_map[current_line] = (code_cell_idx, len(sanitized_lines) + 1)
        current_line += 1
        code_cell_idx += 1

    return NotebookSource(source="\n".join(parts), line_to_cell=line_map)


def _is_jupyter_magic(line: str) -> bool:
    """A line is a Jupyter magic / shell escape if its first non-whitespace char is % or !.

    These don't parse as Python and would break the AST. Doc strings, regular
    comments, and code lines all pass through unchanged.
    """
    stripped = line.lstrip()
    if not stripped:
        return False
    return stripped[0] in ("%", "!")


def cell_location(line: int, line_to_cell: dict[int, tuple[int, int]]) -> tuple[int, int] | None:
    """Map a 1-indexed line in the merged source back to (cell_index, line_in_cell)."""
    return line_to_cell.get(line)
