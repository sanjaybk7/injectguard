"""§4.4 — PEP 420 namespace package under src-layout (top-level).

``my_pkg`` has no ``__init__.py`` but contains ``.py`` files. Two design-
doc sections together establish this fixture's expected resolution path:

* §1.1 detection enumeration (bullet ``src/<pkg>/*.py (no __init__.py) —
  PEP 420 namespace package``): detection rule explicitly covers this
  case. ``discover_package_roots`` returns ``[scan_root/src]``.
* §2.4 "Top-level" subsection: delegates top-level namespace package
  handling to §1.1's detection rule. §2.4 is about resolution semantics
  (runtime-vs-strict-mode); §1.1 is about detection. Both apply here:
  detection picks up ``src/my_pkg/`` and resolution returns the right
  module path without reading ``__init__.py``.

After detection, ``file_to_module_path`` for ``src/my_pkg/prompts.py``
returns ``my_pkg.prompts`` (path-collapse alone; ``__init__.py`` is never
read). The runtime import ``from my_pkg.prompts import SYSTEM_PROMPT``
matches the indexed key, IG002 stays silent.
"""

from agents import Agent, function_tool
from my_pkg.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="namespace-pkg-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
