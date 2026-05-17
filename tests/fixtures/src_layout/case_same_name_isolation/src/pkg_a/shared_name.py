"""Asymmetric pair for review item #4: this module's ``PROMPT`` is
*dynamic*. Fix 1's symbol-table treats it as non-resolvable (the
f-string with a FormattedValue is not a constant-only JoinedStr, so
``_value_to_symbol`` returns ``None`` and the name is dropped from
exports).

The companion ``src/pkg_b/shared_name.py`` defines ``PROMPT`` as a
literal. The test asserts that ``pkg_a.shared_name.PROMPT`` does NOT
resolve (IG002 fires on ``pkg_a/agent.py``) while
``pkg_b.shared_name.PROMPT`` DOES resolve (IG002 stays silent on
``pkg_b/agent.py``). This is the only fixture-level mechanism that
proves the symbol table is returning each package's own value rather
than a bag-of-names match: if isolation breaks and the analyzer returns
pkg_b's literal when asked for pkg_a's PROMPT, IG002 would silently
disappear on ``pkg_a/agent.py`` and the old presence-only assertion
would have missed it.
"""

# Module-local non-literal seed so the f-string below contains a real
# FormattedValue. The seed is itself a literal, but the f-string isn't
# constant-only: per Fix 1's _value_to_symbol, JoinedStr with any
# FormattedValue children is rejected as a literal.
_seed = "pkg_a"

PROMPT = f"dynamic-prefix-from-{_seed}"
