"""Vulnerable (post v0.2): last-import-wins matches Python semantics.

Both ``a`` and ``b`` export ``SYSTEM_PROMPT``. Python rebinds ``SYSTEM_PROMPT``
to whichever name was imported last — here, ``b.SYSTEM_PROMPT``, which is a
function-call result, not a literal. We must follow Python's semantics and
treat the resolved value as ``b``'s (dynamic) export.
"""

from a import SYSTEM_PROMPT
from agents import Agent, function_tool
from b import SYSTEM_PROMPT  # noqa: F811


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="last-wins-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
