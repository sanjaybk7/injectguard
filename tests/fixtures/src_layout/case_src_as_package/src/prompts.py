"""Multiple files alongside this one (``agent_a.py``, ``agent_b.py``) so we
can verify the user-named-src warning fires *once* per scan, not once
per file under ``src/``.
"""

SYSTEM_PROMPT = "I live inside a package literally named `src`."
