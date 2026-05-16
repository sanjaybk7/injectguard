"""Pattern 2: ``Agent[None](...)`` — explicit None context.

Mirrors ``examples/agent_patterns/llm_as_a_judge.py``:
``evaluator = Agent[None](...)``. The subscript slice is a Constant(None)
rather than a Name, so AST handling must be slice-agnostic.
"""

from agents import Agent, function_tool


@function_tool
def lookup(key: str) -> str:
    return ""


evaluator = Agent[None](
    name="evaluator",
    instructions="You judge the quality of a response.",
    tools=[lookup],
    model="gpt-4o",
)
