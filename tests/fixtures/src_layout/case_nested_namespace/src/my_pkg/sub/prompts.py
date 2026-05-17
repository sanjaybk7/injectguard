"""``my_pkg/sub/`` has no ``__init__.py``. PEP 420 says ``my_pkg.sub`` is
a valid implicit namespace package. ``my_pkg.sub.prompts`` must resolve.
"""

NESTED_PROMPT = "I live in a nested implicit namespace package."
