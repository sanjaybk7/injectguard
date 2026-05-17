"""Asymmetric pair for review item #4: this module's ``PROMPT`` is a
plain string literal. Fix 1's symbol-table indexes it normally.

The companion ``src/pkg_a/shared_name.py`` defines ``PROMPT`` as a
dynamic f-string. The test asserts that ``pkg_b.shared_name.PROMPT``
resolves to this literal (IG002 stays silent on ``pkg_b/agent.py``),
demonstrating isolation by content rather than only by presence.
"""

PROMPT = "Plain literal from pkg_b — must resolve to this exact value."
