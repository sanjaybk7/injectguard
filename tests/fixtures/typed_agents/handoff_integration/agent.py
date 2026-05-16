"""Pattern 3: integration — multi-agent typed handoff with source + sink + cross-module prompt.

This fixture is the linchpin: it validates that Fix 1 (cross-module
constant resolution) and PR #2 (``Agent[T](...)`` subscript handling)
compose correctly. On v0.1 + Fix 1 the parser doesn't see ``Agent[T]``
calls, so neither rule fires here. With PR #2:

* IG001 **fires** on ``support_agent`` (which has both ``read_email``
  source and ``send_email`` sink in its toolbox, no human-approval gate).
* IG002 **does not fire** on either agent — both instructions are
  module-level literals imported from ``prompts.py``, and Fix 1's
  cross-module resolver now resolves them through the
  parser-recognized typed agent call.

This mirrors the openai-agents-python customer_service example structure
while compressing it to the minimum surface needed to exercise both rules.
"""

from agents import Agent, function_tool
from prompts import SUPPORT_PROMPT, TRIAGE_PROMPT
from pydantic import BaseModel


class CustomerContext(BaseModel):
    customer_id: str


@function_tool
def read_email(message_id: str) -> str:
    """Read an email by id."""
    return ""


@function_tool
def send_email(to: str, body: str) -> str:
    """Send an email."""
    return ""


@function_tool
def lookup(key: str) -> str:
    """Look up a value."""
    return ""


support_agent = Agent[CustomerContext](
    name="support-agent",
    instructions=SUPPORT_PROMPT,
    tools=[read_email, send_email],
    model="gpt-4o",
)


triage_agent = Agent[CustomerContext](
    name="triage-agent",
    instructions=TRIAGE_PROMPT,
    tools=[lookup],
    handoffs=[support_agent],
    model="gpt-4o",
)
