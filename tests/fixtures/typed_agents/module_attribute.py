"""Pattern 5: ``import agents; agents.Agent[T](...)`` — attribute on subscript.

This is the unwrapping case the reviewer asked us to cover specifically:
when the subscripted callable is itself an attribute access
(``ast.Subscript(value=ast.Attribute(value=ast.Name('agents'),
attr='Agent'))``), the resolver must extract ``Agent`` from the attribute
chain rather than returning the leftmost name.

Both forms are valid Python; both AST shapes need to land at the same
``call_base_name`` result of ``"Agent"``.
"""

import agents
from pydantic import BaseModel


class UserContext(BaseModel):
    user_id: str


@agents.function_tool
def lookup(key: str) -> str:
    return ""


agent = agents.Agent[UserContext](
    name="module-attr-agent",
    instructions="You are a helpful assistant.",
    tools=[lookup],
    model="gpt-4o",
)
