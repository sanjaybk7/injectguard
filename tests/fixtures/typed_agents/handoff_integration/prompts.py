"""Module-scope literals — must resolve cross-module after Fix 1 + PR #2."""

SUPPORT_PROMPT = (
    "You are a customer-support agent. Read the customer's most recent email, "
    "summarize the issue, and respond appropriately. Be concise and polite."
)

TRIAGE_PROMPT = (
    "You are a triage agent. Route the request to the right specialist. "
    "If unsure, ask for clarification."
)
