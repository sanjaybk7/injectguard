"""Bidirectional cross-contam: defines ``HELPER_PROMPT`` *only*.

``helpers/agent.py`` will try to import ``HELPER_PROMPT`` from
``helpers.prompts`` — but ``helpers.prompts`` defines ``MAIN_PROMPT``,
not ``HELPER_PROMPT``. The name ``HELPER_PROMPT`` exists *here* (in
``main_pkg.prompts``) and must NOT bleed into ``helpers.prompts``'s
lookup via any name-anywhere fallback.

Note this file deliberately does NOT define ``MAIN_PROMPT``; that
preserves the original direction of the cross-contam test, where
``main_pkg/agent.py`` imports ``MAIN_PROMPT`` from ``main_pkg.prompts``
and must fail to find it (the name only exists in ``helpers.prompts``).
"""

HELPER_PROMPT = "This belongs to main_pkg, not helpers."
