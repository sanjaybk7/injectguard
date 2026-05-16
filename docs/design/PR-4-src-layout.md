# PR #4 — src-layout symbol-table normalization: design

**Status:** DRAFT. Awaiting review. No fixtures or implementation will land
until §§1–4 below are confirmed or amended.

This document exists because the path-normalization choice in
`PackageSymbolTable.build()` is load-bearing for the cross-module resolver,
and once the wrong choice is locked in by fixtures, untangling it is
expensive. Per the same gating pattern as PR #5, this design is a stand-alone
commit; fixtures and code follow only after review.

---

## 0. Background and problem statement

Fix 1 (PR #1) introduced `PackageSymbolTable`, which indexes every `.py`
file in the scan root under a *dotted module path*. The path is computed by:

```python
def file_to_module_path(file: Path, scan_root: Path) -> str | None:
    rel = file.resolve().relative_to(scan_root.resolve())
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None
```

This works for *flat-layout* projects:

```
my_project/
├── pyproject.toml
└── my_pkg/
    ├── __init__.py
    └── prompts.py        # indexed as my_pkg.prompts
```

User code `from my_pkg.prompts import X` resolves correctly.

It fails silently for *src-layout* projects:

```
my_project/
├── pyproject.toml
└── src/
    └── my_pkg/
        ├── __init__.py
        └── prompts.py    # indexed as src.my_pkg.prompts
```

User code `from my_pkg.prompts import X` does not match the indexed
`src.my_pkg.prompts` → resolver falls through → IG002 fires spuriously.

This was caught during PR #2's corpus validation: it surfaced 6 typed
agents in `openai-agents-python/examples/customer_service/main.py` whose
prompts use `f"{RECOMMENDED_PROMPT_PREFIX}..."` from
`src/agents/extensions/handoff_prompt.py`. None resolve. All 6 fire IG002.

PEP 517/518-era packaging (hatchling, poetry, flit, pdm, modern setuptools)
*recommends* src-layout. The current OpenAI Agents SDK uses it. Any
production-quality modern Python codebase the analyzer encounters is likely
to use it.

---

## 1. Path normalization scheme

### 1.1 Detection

**Proposal:** treat `<scan_root>/src/` as a package root whenever it
contains at least one subdirectory that *itself* contains one or more
`.py` files (at any depth, but checked one level deep for performance).

The presence of `__init__.py` is **not** required for detection — PEP 420
namespace packages exist and are increasingly common (typed-pkg projects,
ML libraries). The "subdirectory contains .py files" check is the most
permissive correct rule.

Cases the detection covers:
- `src/<pkg>/__init__.py` — classic single-package src-layout
- `src/<pkg>/*.py` (no `__init__.py`) — PEP 420 namespace package
- `src/<pkg_a>/`, `src/<pkg_b>/` — multi-package src-layout
- `src/<pkg>/<sub>/` with deeply-nested .py files — still detected via the
  one-level scan

Cases the detection rejects:
- `src/` is empty
- `src/scripts/build.sh` (no `.py` files) — not a package
- The scan root *is* `src/<pkg>/` (user already scoped to a package)

### 1.2 Normalization

**Proposal:** introduce the concept of a `package_root` — the directory
from which module paths are computed.

```python
# new function in symbol_table.py
def discover_package_roots(scan_root: Path) -> list[Path]:
    """Return the list of directories from which module paths are computed.

    For pure flat-layout: [scan_root].
    For pure src-layout:  [scan_root / "src"].
    For mixed layout:     [scan_root, scan_root / "src"] in that order.
    """
```

`file_to_module_path` then takes the *package root that contains the file*
instead of the scan root:

```python
def file_to_module_path(file: Path, package_root: Path) -> str | None:
    # identical body, just keyed off package_root instead of scan_root
```

`PackageSymbolTable.build()` discovers package roots once, then iterates
files and picks the most-specific package root that contains each file
(`max(roots, key=lambda r: len(r.parts) if file is_relative_to r else -1)`).

### 1.3 Worked examples

| Filesystem path | scan_root | Layout | Indexed as |
|---|---|---|---|
| `proj/my_pkg/prompts.py` | `proj/` | flat | `my_pkg.prompts` |
| `proj/src/my_pkg/prompts.py` | `proj/` | src | `my_pkg.prompts` |
| `proj/src/my_pkg/prompts.py` | `proj/src/` | (no detection — root is below `src`) | `my_pkg.prompts` |
| `proj/src/pkg_a/foo.py` | `proj/` | src, multi-pkg | `pkg_a.foo` |
| `proj/src/pkg_b/bar.py` | `proj/` | src, multi-pkg | `pkg_b.bar` |
| `proj/helpers/util.py` AND `proj/src/main/app.py` both present | `proj/` | mixed | `helpers.util` AND `main.app` |
| `proj/src/scripts/build.sh` | `proj/` | (no `.py` under `src/scripts` → not a package root) | not indexed |

---

## 2. Handling multiple layouts

Per the review: enumerate the layouts and propose default behavior for each.

### 2.1 Pure src-layout — `src/<pkg>/...`

**Proposal: detect and normalize.** This is the primary case. Single
package root at `scan_root/src`. All modules under it indexed under
`<pkg>.*`.

### 2.2 Pure flat-layout — `<pkg>/...` at root

**Proposal: existing Fix 1 behavior, unchanged.** Single package root at
`scan_root`. All modules indexed by path relative to scan root. No
detection needed.

### 2.3 Mixed — some packages in `src/`, some flat

**Proposal: support, with both roots active simultaneously.**

`discover_package_roots()` returns `[scan_root, scan_root/src]` (in that
order) when both have packages. Each file is indexed under the
most-specific containing root.

This is rare (real cases: a project with `src/main_pkg/` but also a
top-level `tests/` directory containing scaffolding modules, or a
monorepo with a vendored sub-package alongside src/). The implementation
cost of supporting it is one extra root in a list; the cost of *not*
supporting it is a class of false positives we'd have to explain. Just
support it.

**Decision required:** if a name resolves to *both* a flat-layout module
*and* an src-layout module (e.g. `proj/helpers.py` and
`proj/src/helpers.py` both exist), which wins? **Proposal: src-layout
wins, because that's what `pyproject.toml` typically configures as the
distributable package.** Document in a comment; surface as a
"low-confidence" mark in symbol-table if we later add confidence levels.

### 2.4 PEP 420 namespace packages — no `__init__.py`

**Proposal: support transparently.** Detection rule in §1.1 already
permits this — we look for `.py` files, not `__init__.py`. The
indexing logic is unchanged because `file_to_module_path` doesn't read
`__init__.py` either; it just collapses paths.

**Caveat:** in real PEP 420 codebases, you can have the *same* dotted
module path split across multiple physical directories on `sys.path`.
We don't model this — we index whatever is under the scan root. If a
project relies on PEP 420 multi-root namespace packages (rare in agent
code), some imports won't resolve. **Defer; document as a limitation.**

### 2.5 Multiple top-level packages under `src/` — `src/pkg_a/`, `src/pkg_b/`

**Proposal: support transparently.** `discover_package_roots()` returns
`[scan_root/src]` (one root), and indexing walks every file under it.
`src/pkg_a/foo.py` becomes `pkg_a.foo`; `src/pkg_b/bar.py` becomes
`pkg_b.bar`. The OpenAI Agents SDK actually uses this internally (one
package, but the pattern generalizes).

### 2.6 Layouts NOT covered (deferred)

- **`pyproject.toml`-driven custom layouts** (e.g.
  `[tool.setuptools.package-dir] my_pkg = "lib/source"`). Parsing
  `pyproject.toml` introduces a new dependency (`tomllib` is stdlib in
  3.11+, but the schema handling for hatchling/poetry/setuptools/pdm/flit
  is non-trivial). **Deferred to v0.3.**
- **Editable installs / `*.pth` files.** Same reasoning — out of scope for
  static analysis.
- **Implicit relative imports under Python 2 semantics.** Python 3 doesn't
  support these; the analyzer is Python-3-only.
- **PEP 420 multi-root namespace packages** (§2.4 caveat). Deferred.

---

## 3. Scope discipline

Estimated line counts for the implementation:

| Component | LOC (est.) |
|---|---|
| `discover_package_roots(scan_root)` | ~12 |
| Modified `file_to_module_path(file, package_root)` | ~3 (rename param + signature) |
| Modified `PackageSymbolTable.build()` to iterate roots + pick most-specific | ~10 |
| Conflict-resolution comment (src-layout wins per §2.3) | ~3 |
| **Subtotal** | **~28** |

This is within the ~30-line budget the review set. If the implementation
exceeds 35 lines before tests, **I will pause and surface why before
continuing.** The most likely overrun source is multi-root conflict
resolution; if that grows, I'll consider dropping it in favor of
single-root-wins-by-precedence and surface the simplification.

**Out-of-scope guard:** this PR does NOT touch
`CrossModuleResolver` or `build_resolver`. Per-file import resolution is
unchanged; the only thing changing is *how the global table is keyed*.
That isolation is what keeps the line count down.

---

## 4. Test strategy

Five fixture sub-packages under `tests/fixtures/src_layout/`, each scanned
as a unit. Plus one real-world re-scan assertion.

### 4.1 `case_pure_src/`

```
case_pure_src/
└── src/
    └── my_pkg/
        ├── __init__.py
        ├── agent.py        # from my_pkg.prompts import SYSTEM_PROMPT
        └── prompts.py      # SYSTEM_PROMPT = "..."
```

Assert: IG002 does NOT fire on `agent.py`'s Agent definition.

### 4.2 `case_pure_flat/` — regression test for Fix 1's behavior

```
case_pure_flat/
└── my_pkg/
    ├── __init__.py
    ├── agent.py            # from my_pkg.prompts import SYSTEM_PROMPT
    └── prompts.py          # SYSTEM_PROMPT = "..."
```

Assert: IG002 does NOT fire. This must continue to work — PR #4 must not
regress flat-layout resolution.

### 4.3 `case_mixed/` — both layouts in one scan

```
case_mixed/
├── src/
│   └── main_pkg/
│       ├── __init__.py
│       ├── agent.py        # from main_pkg.prompts import P1
│       └── prompts.py      # P1 = "..."
└── helpers/
    ├── __init__.py
    ├── agent.py            # from helpers.prompts import P2
    └── prompts.py          # P2 = "..."
```

Assert: IG002 does NOT fire on either agent. Both resolution chains
work; no cross-contamination (i.e., `from main_pkg.prompts import P2`
must NOT resolve, because P2 only exists in `helpers/`).

### 4.4 `case_namespace_pkg/` — PEP 420, no `__init__.py`

```
case_namespace_pkg/
└── src/
    └── my_pkg/                # no __init__.py
        ├── agent.py           # from my_pkg.prompts import SYSTEM_PROMPT
        └── prompts.py         # SYSTEM_PROMPT = "..."
```

Assert: IG002 does NOT fire. Confirms namespace-package support per §2.4
(the non-deferred subset).

### 4.5 `case_multi_pkg_src/` — multiple packages under `src/`

```
case_multi_pkg_src/
└── src/
    ├── pkg_a/
    │   ├── __init__.py
    │   ├── agent.py          # from pkg_a.prompts import P
    │   └── prompts.py
    └── pkg_b/
        ├── __init__.py
        ├── agent.py          # from pkg_b.prompts import P
        └── prompts.py
```

Assert: IG002 does NOT fire on either agent. Names don't bleed between
`pkg_a` and `pkg_b`.

### 4.6 Cross-contamination negative test

In `case_mixed/`, add a fixture where `src/main_pkg/agent.py` imports
`from helpers.prompts import P2`. P2 exists in `helpers/prompts.py` but
should NOT resolve when imported via the wrong package path (this is
correct Python semantics — `from helpers.prompts import P2` only works if
`helpers` is reachable via `sys.path`, which in a properly-configured
src-layout project it isn't unless explicitly added). Assert: IG002 fires
here. Conservative-on-doubt principle.

Actually, this is subtler — re-read §2.3. If `helpers/` is at the scan
root and is detected as a package root, then `from helpers.prompts import
P2` *should* resolve. The cross-contamination guard is different: from
`src/main_pkg/agent.py`, an import of `from main_pkg.prompts import
NONEXISTENT` should not silently match `helpers.prompts.NONEXISTENT`
even though we know about the latter. **The conservative default already
covers this** — we look up by exact module path, not by name-anywhere.
This test confirms that, and prevents future regressions if anyone
"helpfully" adds a fallback lookup.

### 4.7 Real-world A/B re-scan

Re-run the 9-repo corpus from PR #1/PR #2 validation. Expected per-repo
deltas (PR #2 baseline → PR #4 applied):

| Repo | PR #2 IG002 | Predicted | Δ |
|---|---:|---:|---:|
| openai-agents-python | 13 | 7 | **−6** |
| every other repo | unchanged | unchanged | 0 |

If the openai-agents-python delta isn't −6, the implementation has a bug
and we don't ship.

---

## 5. Open questions

I don't believe any of the above hinges on a Python language-spec
ambiguity. The closest things to genuinely open questions:

- **`src/` *that isn't* a package marker.** Some projects have a top-level
  `src/` containing non-Python source (Rust crate, JS bundle) and *also*
  have flat-layout Python packages at root. The §1.1 detection rule
  ("`src/<X>/` contains `.py` files") handles this: if `src/` has no
  Python files anywhere inside, we don't detect src-layout. Worth a
  fixture (`case_src_is_not_python/` with `src/rust_crate/lib.rs`).
- **Confidence levels in the symbol table.** When `helpers.X` is reachable
  via *both* a flat-layout and a src-layout indexing, §2.3 says
  "src-layout wins." But we could also record a "this name is ambiguous"
  flag and downgrade resolved-to-static to resolved-with-low-confidence.
  Not proposed for v0.2; flagged for v0.3 if precision data shows it
  matters.

---

## 6. Sign-off

This document does not commit any code beyond itself. The first
behavioral commit on this branch will not land until the reviewer
confirms or amends §§1–4.

Once the design is locked, the implementation order is:
1. Fixtures + failing tests (one commit)
2. `discover_package_roots()` + `file_to_module_path` signature change +
   `PackageSymbolTable.build()` modification (one commit)
3. Corpus A/B re-scan, results in PR description (one commit if needed
   for results data; otherwise inline in PR body)

Stopping here.
