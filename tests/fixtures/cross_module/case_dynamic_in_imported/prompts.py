"""The 'remote' module itself builds the prompt dynamically.

`user` is undefined at module scope here intentionally — in real code this
would either fail at import time, or `user` would come from somewhere we
can't see (a config import, a global injected by tests, etc.). What matters
for the analyzer: the export is not a literal, so it should NOT mask IG002.
"""

user = "placeholder"  # this is module-local, but the f-string is still dynamic-by-construction

SYSTEM_PROMPT = f"You are an assistant for {user}, follow their preferences."
