"""§4a (cross-function pollution, symbol-table edition) — review item #7.

Both ``pkg_a`` and ``pkg_b`` contain a module named ``shared_name`` that
exports a constant named ``PROMPT``. The two ``PROMPT`` values differ.
The symbol table must keep them isolated: ``pkg_a.shared_name.PROMPT``
must resolve to pkg_a's value, ``pkg_b.shared_name.PROMPT`` must resolve
to pkg_b's value, and neither must bleed into the other's lookup.

Expected: IG002 does NOT fire on either agent.

(Failure mode this guards against: a "helpful" lookup that searches all
modules with matching trailing names — which would resolve
``shared_name.PROMPT`` to whichever was indexed last.)
"""

from agents import Agent, function_tool

from pkg_a.shared_name import PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pkg-a-isolated-agent",
    instructions=PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
