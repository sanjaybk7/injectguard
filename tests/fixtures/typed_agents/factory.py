"""Pattern 4: nested ``return Agent[T](...)`` inside a factory function.

Mirrors ``examples/sandbox/healthcare_support/support_agents.py`` line 136
(``return Agent[HealthcareSupportContext](...)``) and the SDK pattern of
encapsulating agent construction in a factory for testability.

The agent is defined *inside* a function body, not at module top level.
The visitor walks into function bodies (via ``generic_visit``), so the
subscripted call must still be recognized when nested.
"""

from agents import Agent, function_tool
from pydantic import BaseModel


class WorkflowContext(BaseModel):
    workflow_id: str


@function_tool
def lookup(key: str) -> str:
    return ""


def build_orchestrator() -> Agent[WorkflowContext]:
    return Agent[WorkflowContext](
        name="orchestrator",
        instructions="Coordinate workflow steps.",
        tools=[lookup],
        model="gpt-4o",
    )
