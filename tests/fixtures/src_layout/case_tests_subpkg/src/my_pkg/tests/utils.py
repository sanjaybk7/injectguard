"""A genuine importable utility that happens to live under ``tests/``.

The Scanner's ``_is_test_path`` filter applies to vulnerability detection,
not to the symbol-table pre-pass — so this file gets indexed as
``my_pkg.tests.utils`` and the constant below is resolvable from
non-test code.
"""

UTIL_PROMPT = "Shared prompt utility that lives under my_pkg/tests/."
