"""injectguard: static analyzer for prompt-injection and confused-deputy risks in LLM agent code."""

from injectguard.ir import (
    Agent,
    Finding,
    Severity,
    Tool,
    ToolClassification,
    TrustLevel,
)

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "Finding",
    "Severity",
    "Tool",
    "ToolClassification",
    "TrustLevel",
    "__version__",
]
