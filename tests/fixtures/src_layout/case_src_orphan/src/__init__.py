"""§1.1.1 (mixed orphan case) — review item #5b.

This ``src/__init__.py`` becomes an *orphan* under src-layout: ``src/``
is detected as the package root because ``src/my_pkg/`` contains ``.py``
files, so this file shouldn't be importable as a package at all. The
``file_to_module_path`` orphan branch (§1.2 code block) must skip it
with a warning rather than silently returning the empty-string module
path.
"""

ORPHAN_CONSTANT = "I should be invisible to the symbol table."
