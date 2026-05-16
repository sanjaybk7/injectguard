"""Imported module reassigns SYSTEM_PROMPT — treat as dynamic.

The first assignment is a literal but the second isn't. We can't know
statically which value is bound when the importer reads it; conservative
default is to refuse to resolve.
"""

SYSTEM_PROMPT = "You are a helpful assistant."

# Some later code path overrides it.
SYSTEM_PROMPT = SYSTEM_PROMPT + " Always reply in JSON."
