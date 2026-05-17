"""The name MAIN_PROMPT exists here — but it is not importable via
``main_pkg.prompts``. The cross-contamination guard asserts the analyzer
does NOT resolve ``from main_pkg.prompts import MAIN_PROMPT`` by reaching
into this file.
"""

MAIN_PROMPT = "This belongs to helpers, not main_pkg."
