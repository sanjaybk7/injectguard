"""Sibling module that owns a static system prompt.

This is the dominant real-world pattern (openai-cookbook, langgraph examples,
production agents): prompts live in a `prompts.py` and are imported.
"""

SYSTEM_PROMPT = (
    "You are a helpful assistant focused on customer-support workflows. "
    "Be concise. Refuse anything outside the documented scope."
)
