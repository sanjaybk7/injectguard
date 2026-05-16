"""Pattern 1: ``Agent[UserContext](...)`` with a user-defined context type.

Mirrors openai-agents-python's ``docs/agents.md`` line 140
(``agent = Agent[UserContext](...)``) and ``examples/customer_service/main.py``
where every agent uses ``Agent[AirlineAgentContext](...)``. This is the
SDK's documented recommended form for type-safe agents.

This file is recognized as a v0.1 *miss* — the parser only matches
``ast.Call(func=ast.Name|ast.Attribute)``, so the subscripted call is
invisible. PR #2 adds ``ast.Subscript`` handling.
"""

from agents import Agent, function_tool
from pydantic import BaseModel


class UserContext(BaseModel):
    user_id: str


@function_tool
def lookup(key: str) -> str:
    """Look up a value."""
    return ""


agent = Agent[UserContext](
    name="typed-user-context-agent",
    instructions="You are a helpful assistant. Be concise.",
    tools=[lookup],
    model="gpt-4o",
)
