"""§2.7 — review item #4.

Production-path module imports from ``my_pkg.tests.utils`` — a real
Python pattern (shared helpers happen to live under a ``tests`` namespace).
The symbol table must index ``my_pkg.tests.utils`` even though
rule-evaluation would skip ``my_pkg/tests/utils.py`` if it contained
agent code.

Expected: IG002 does NOT fire on this agent (cross-module resolution
finds UTIL_PROMPT under the indexed tests-subpkg path).
"""

from agents import Agent, function_tool

from my_pkg.tests.utils import UTIL_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="tests-subpkg-agent",
    instructions=UTIL_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
