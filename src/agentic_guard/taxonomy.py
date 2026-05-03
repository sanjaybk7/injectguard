"""Loader and matcher for the source/sink taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agentic_guard.ir import ToolClassification, TrustLevel

_DEFAULT_TAXONOMY_PATH = Path(__file__).parent / "taxonomy.yaml"


@dataclass(frozen=True)
class TaxonomyEntry:
    pattern: str
    classification: ToolClassification
    privilege: int = 0
    trust_of_output: TrustLevel = TrustLevel.TRUSTED
    reversible: bool = True
    rationale: str | None = None


@dataclass
class Taxonomy:
    """Catalog of tool-name patterns and their security classification."""

    entries: list[TaxonomyEntry]

    @classmethod
    def load(cls, path: Path | None = None) -> Taxonomy:
        """Load the taxonomy from YAML. Defaults to the bundled file."""
        target = path or _DEFAULT_TAXONOMY_PATH
        with target.open("r", encoding="utf-8") as f:
            raw: dict[str, list[dict[str, Any]]] = yaml.safe_load(f) or {}

        entries: list[TaxonomyEntry] = []
        for kind, classification in (
            ("sources", ToolClassification.SOURCE),
            ("sinks", ToolClassification.SINK),
            ("both", ToolClassification.BOTH),
        ):
            for item in raw.get(kind, []) or []:
                entries.append(
                    TaxonomyEntry(
                        pattern=str(item["pattern"]).lower(),
                        classification=classification,
                        privilege=int(item.get("privilege", 0)),
                        trust_of_output=TrustLevel(
                            item.get(
                                "trust_of_output",
                                "untrusted" if classification != ToolClassification.SINK else "trusted",
                            )
                        ),
                        reversible=bool(item.get("reversible", True)),
                        rationale=item.get("rationale"),
                    )
                )
        return cls(entries=entries)

    def classify(self, tool_name: str, description: str | None = None) -> TaxonomyEntry | None:
        """Return the best-matching entry for a given tool name and (optional) docstring.

        Matching strategy: lowercase substring match against tool_name first, then
        against the description if no name match is found. The longest matching
        pattern wins (so 'send_email' beats 'send').
        """
        haystacks = [tool_name.lower()]
        if description:
            haystacks.append(description.lower())

        best: TaxonomyEntry | None = None
        for entry in self.entries:
            for hay in haystacks:
                if entry.pattern in hay:
                    if best is None or len(entry.pattern) > len(best.pattern):
                        best = entry
                    break
        return best
