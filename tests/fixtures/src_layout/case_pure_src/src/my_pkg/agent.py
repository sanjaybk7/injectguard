"""§4.1 — pure src-layout. Agent imports from sibling module via the package
name (``my_pkg.prompts``), not via the filesystem-relative path
(``src.my_pkg.prompts``). PR #4 must normalize the symbol-table key so
the import resolves.
"""

from agents import Agent, function_tool

from my_pkg.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pure-src-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
