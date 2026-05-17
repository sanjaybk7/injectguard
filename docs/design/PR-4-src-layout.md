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

**Merging this PR unblocks PR #5 (`fix-3-function-local-binding`), which
has been paused pending this work.**

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
  (see §2.4 for the resolution semantics that apply after detection)
- `src/<pkg_a>/`, `src/<pkg_b>/` — multi-package src-layout
- `src/<pkg>/<sub>/` with deeply-nested .py files — still detected via the
  one-level scan

Cases the detection rejects:
- `src/` is empty
- `src/scripts/build.sh` (no `.py` files) — not a package
- The scan root *is* `src/<pkg>/` (user already scoped to a package)

#### 1.1.1 Edge case: `src/` is itself a package

Rare but real: a project where `src/` is the actual package name and
contains `src/__init__.py`. Two subcases, handled per-rule:

- **Pure case** (`src/__init__.py` exists, no subdirectories with `.py`
  files): src-layout detection rejects (no qualifying subdir). Falls
  through to flat-layout. `src/__init__.py` is indexed as the package
  literally named `src` — the user got the package they asked for, even
  though the choice of name will confuse readers. **Defined behavior, but
  emit a one-time warning at `discover_package_roots` time:** *"flat-layout
  detected with top-level package literally named 'src'; this is unusual
  and may indicate a project misconfiguration"*. The warning fires once
  per scan regardless of how many `.py` files live under `src/`, so
  scanning a 50-file package doesn't produce 50 log lines. This is
  distinct from the orphan warning in §1.2 (which fires per-file when an
  orphan `__init__.py` is skipped under src-layout); the two warnings
  cover non-overlapping cases.
- **Mixed orphan case** (`src/__init__.py` AND `src/<pkg>/` with `.py`
  files both present): src-layout detection wins. The
  `src/__init__.py` becomes an *orphan* — under src-layout semantics it
  shouldn't be importable as a package at all, because `src/` itself is
  the package root rather than a containing package. The file is
  skipped with a warning rather than silently miscategorized as the
  empty-string module path. See §1.2 for the `file_to_module_path`
  branch that enforces this.

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
instead of the scan root, with two new guards (symlink containment + orphan
`__init__.py` detection):

```python
def file_to_module_path(file: Path, package_root: Path) -> str | None:
    # Resolve symlinks; if the resolved file points outside the resolved
    # package_root (symlink escape), skip — we don't index files that
    # physically live elsewhere on disk. Silent ValueError would otherwise
    # propagate from relative_to(); guarding it explicitly is clearer.
    try:
        rel = file.resolve().relative_to(package_root.resolve())
    except ValueError:
        log.debug("skipping %s: not under package_root %s", file, package_root)
        return None

    parts = list(rel.with_suffix("").parts)

    # Orphan __init__.py at the package root itself (parts == ["__init__"])
    # is the src-layout edge case from §1.1.1: src/__init__.py exists
    # alongside src/<pkg>/ subdirectories. Without this branch the function
    # would silently return None (empty parts after dropping __init__), which
    # is correct behavior dressed up as a bug. Log it explicitly.
    if parts == ["__init__"]:
        log.warning("orphan __init__.py at package root %s; skipping", file)
        return None

    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None
```

`PackageSymbolTable.build()` discovers package roots once, then iterates
files and picks the most-specific package root that contains each file
(`max(roots, key=lambda r: len(r.parts) if file is_relative_to r else -1)`).

#### 1.2.1 Symlink policy

The `.resolve()` call follows symlinks. A symlink at `src/pkg` pointing
into `/elsewhere/` will be resolved to its physical location; if that
location is outside every discovered package root, the file is rejected
during root-picking and a debug-level log fires naming the file and
reason. Rationale: indexing files that don't physically live under the
scan root makes module-path collision and de-duplication semantics
ambiguous, and the most common real-world reason for an outbound
symlink (a vendored package linked from elsewhere on disk) is precisely
the case where you do *not* want the analyzer to also walk that other
tree. If the user wants symlinked content scanned, they can run the
scan against the real location.

The log message preserves the substring `"not under package_root"` and
includes the symlinked file path so the §4-test matcher (and any
operator grep) keeps working regardless of which call site emits it.

##### 1.2.1.0 Python 3.13 default `rglob` behavior — directory vs file symlinks

This design's escape-check covers files that **reach** our code via the
`rglob("*.py")` iteration in `Scanner._build_scan_context`. Python's
`rglob` semantics for symlinks changed across versions:

* **Python 3.12 and earlier:** `rglob` walked into directory symlinks
  by default. A symlink `pkg/linked → /elsewhere/` would surface every
  `.py` file under `/elsewhere/` in the iteration, and our
  escape-check would reject each at file-resolution time.
* **Python 3.13:** `rglob` skips directory symlinks by default. The
  `recurse_symlinks=True` parameter was added in 3.13
  (<https://docs.python.org/3/library/pathlib.html#pathlib.Path.rglob>)
  to opt back into 3.12 behavior. We do **not** opt in: walking into
  directory symlinks risks infinite-loop on self-referential links and
  needlessly indexes vendored code the user didn't intend to scan.

The end-user-observable invariant — *outbound symlinks of any kind do
not contribute files to the symbol table* — holds via two distinct
mechanisms that compose:

| Symlink kind | Skipped by | Escape-check log fires? |
|---|---|---|
| Directory symlink, outbound | Python 3.13 default `rglob` (iteration layer) | No (no code is invoked) |
| File symlink, outbound | Our `_pick_package_root_for` escape-check | Yes |
| Directory symlink, inbound (under scan root) | Walked normally | N/A (resolves under root) |
| File symlink, inbound | Walked normally | N/A (resolves under root) |

The §4-fixtures in `test_src_layout.py` test both mechanisms with two
separate tests: one fixture uses a file symlink to verify the
escape-check log (the mechanism), the other uses a directory symlink
to verify the broader invariant (the policy outcome). Either test
alone would have a blind spot for one mechanism.

##### 1.2.1.1 Architecture amendment — log call-site relocation

The original §1.2 code block showed `log.debug("skipping %s: not under
package_root %s", file, package_root)` inside `file_to_module_path`'s
`except ValueError` branch. Implementation revealed that
`file_to_module_path(file, package_root: Path)` — by virtue of its
single-root signature — cannot cleanly express "this file matches no
root at all"; the path-computation function takes one root in and
returns one module path out. Splitting root-discovery from
path-computation produced a cleaner pipeline (`_pick_package_root_for`
→ `file_to_module_path`), and the natural location for the
symlink-escape log is the filter step where the rejection actually
happens. The log substring and information content are preserved; only
the call site moved. `file_to_module_path` retains the `except
ValueError` branch (with its own debug log) for defensive reasons but
no longer carries the symlink-policy contract.

#### 1.2.2 Case sensitivity

Module path matching is case-sensitive in both directions: the
filesystem-derived path and the import-statement string are compared
verbatim. This mirrors Python's import system, which is case-sensitive
on every platform regardless of the underlying filesystem (macOS
HFS+/APFS and Windows NTFS are case-insensitive case-preserving by
default; Python imports them case-sensitively anyway). A file at
`src/Agents/__init__.py` is indexed as `Agents`; `from agents import X`
does not match it. **Do not case-fold either side, even on
case-insensitive filesystems.** This is a deliberate choice; a future
"helpful" normalization PR would silently change semantics.

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

**Proposal: support transparently** at both the top-level (src-layout
detection) and nested (within-package) levels.

**Top-level:** detection rule in §1.1 looks for `.py` files, not
`__init__.py` (see §1.1's "Cases the detection covers" enumeration, the
``src/<pkg>/*.py (no __init__.py)`` bullet). `src/<pkg>/foo.py` with no
`__init__.py` anywhere triggers src-layout normally. §2.4 governs the
*resolution semantics* (runtime-vs-strict-mode) that apply once §1.1's
detection has picked the layout up; the two sections are deliberately
split between detection (§1.1) and resolution (§2.4).

**Nested:** a directory at `src/pkg/sub/` containing `.py` files but no
`__init__.py` resolves as `pkg.sub` — `file_to_module_path` never reads
`__init__.py`, it just collapses paths. So `from pkg.sub.foo import X`
resolves whether or not `pkg/sub/__init__.py` exists. This matches
Python's runtime import system (PEP 420).

Rationale: **we analyze what will import at runtime, not what should be
importable by convention.** This is a deliberate position. Strict
static-analysis tools differ here — mypy's default rejects implicit
namespace packages and requires `--namespace-packages` to opt in;
pylint/flake8 historically warned against missing `__init__.py`. Our
choice aligns with the runtime, not with strict-mode conventions,
because mismatching the runtime would produce false negatives (real
imports that resolve in production but not in our analyzer).

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

### 2.7 `tests/` directories inside packages

The symbol-table pre-pass indexes **every** `.py` file under any package
root, including files under `tests/`, `test/`, `testing/`, `__tests__/`
directories. This is deliberate: `tests/foo.py` is a valid Python module
that could be imported by another module, and if a non-test file does
`from tests.foo import PROMPT_CONSTANT`, we want that constant to
resolve.

The Scanner's `_is_test_path` filter (which skips test files from
vulnerability detection per `_iter_scannable_files`) applies **only** to
the rule-evaluation phase, not to the symbol-table pre-pass. The two
concerns are kept separate and the design preserves that distinction:

- **Symbol table (PR #4 + Fix 1):** indexes everything that could be a
  Python import target. Includes `tests/` content.
- **Rule evaluation (existing Fix 1 behavior):** ignores fixture files
  that intentionally encode vulnerable patterns to test the analyzer
  itself.

A future ergonomic improvement (`--include-tests`) could opt symbol-table
behavior into matching rule-evaluation behavior, but for v0.2 the
separation is what we want. **Specifically:** under src-layout, a
`src/pkg/tests/` directory is *not* promoted to a package root and is
indexed as `pkg.tests.*` like any normal sub-package. The package-root
discovery in §1.1 only considers the literal `<scan_root>/src/`; no
other directory name (`tests`, `vendor`, etc.) is special-cased.

### 2.8 Multi-root scans (future consideration)

`agentic-guard scan repo_a repo_b` is **not supported in v0.2.** The CLI
(`cli.py:scan`) takes a single `Path` argument; `Scanner.scan(target)`
builds one `PackageSymbolTable` per call. Two separate `Scanner.scan`
calls produce two independent tables that do not cross-contaminate.

If multi-target scanning is added in the future, **each scan root MUST
maintain its own `PackageSymbolTable`.** Merging tables across unrelated
repos would silently collide on package names — every `agents` package
in every project would land in the same key, and `from agents.foo import
X` in repo A could resolve to repo B's `agents.foo.X`. Documenting this
here so a future implementer doesn't reach for a single shared table as
an "optimization."

---

## 3. Scope discipline

Estimated line counts for the implementation, after the review-feedback
additions in §1.1.1, §1.2.1, and §1.2.2:

| Component | LOC (est.) |
|---|---|
| `discover_package_roots(scan_root)` | ~12 |
| Modified `file_to_module_path(file, package_root)` with symlink guard + orphan-`__init__.py` check | ~10 |
| Modified `PackageSymbolTable.build()` to iterate roots + pick most-specific | ~10 |
| Conflict-resolution comment (src-layout wins per §2.3) | ~3 |
| Module-level `log = logging.getLogger(__name__)` + `import logging` | ~2 |
| **Subtotal** | **~37** |

### 3.1 Budget revision

Original estimate: ~28 LOC against a 30-LOC budget. Items #1
(symlink containment guard) and #5b (explicit orphan-`__init__.py`
handling) from the review feedback together added ~8–10 LOC. The
updated estimate of ~36–38 LOC **crosses the original 30-LOC trigger.**

This is logged here as an explicit budget revision rather than scope
creep. Both additions guard against silent miscategorization that would
be hard to debug in the field:

- The symlink guard prevents `relative_to()` from raising a `ValueError`
  that, under the original implementation, would have been silently
  caught by an upstream `try` and produced an unindexed file with no
  log signal.
- The orphan-`__init__.py` check prevents an empty-parts return value
  that would be syntactically valid (`return None`) but semantically a
  bug (the file *should* have been logged as skipped, not silently
  dropped).

If the implementation as actually written exceeds ~42 LOC, **I will
pause and surface why before continuing.** The most likely overrun
source remains multi-root conflict resolution per §2.3; if that grows,
single-root-wins-by-precedence is the fallback.

##### 3.1.1 Implementation outcome — pause-trigger fired, trimmed, accepted

Implementation came in at ~54 LOC on the first pass, exceeding the ~42
LOC pause-trigger. The overage was surfaced for explicit decision
rather than absorbed silently. Trims (inline `_is_under` into its sole
caller; compress the §2.3 in-code comment from 7 lines to 3 with a
pointer back to this design doc; tighten `discover_package_roots`
comprehensions) brought the final count to ~44 LOC. The remaining ~2
LOC excess is attributed to multi-layout discovery (§4.3 `case_mixed`)
and warning emission (§1.1.1 user-named-src + §1.2 orphan-init), both
spec-required and non-removable without scope reduction.

The pause-trigger functioned as designed: it surfaced the overshoot
for explicit acceptance with documented rationale rather than letting
scope creep accrue silently. Future PRs should treat this pattern as
reusable — a trigger that produces a recorded decision is healthier
than a trigger that produces a fight over rounding.

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

### 4.7 Real-world A/B re-scan — directional prediction only

Re-run the 9-repo corpus from PR #1/PR #2 validation. We commit to a
**directional prediction only**: `openai-agents-python`'s IG002 count
drops by approximately 6 (from PR #2's baseline of 13) because the typed
agents in `customer_service/main.py` — surfaced but unresolved by PR #2 —
now resolve cross-module through the src-layout-aware symbol table. No
other repo's count should change.

| Repo | PR #2 IG002 | Predicted post-PR-#4 | Δ |
|---|---:|---:|---:|
| openai-agents-python | 13 | ~7 | **−6 (directional)** |
| every other repo | unchanged | unchanged | 0 |

**The residual count (~7) is not claimed to be fully true-positive.**
Per spot-inspection during PR #2's analysis, the residual breaks down
approximately as:

- **~1 confirmed true positive** — the `{repo}` f-string interpolation in
  `examples/hosted_mcp/simple.py`, which interpolates a function
  parameter directly into the system prompt. Real dynamic-prompt risk;
  IG002 firing here is correct.
- **Several function-local-literal-binding false positives** that PR #5
  explicitly targets. The dominant pattern is
  ```python
  instructions = (
      "You assist support agents. ..."
      "...keep responses under three sentences."
  )
  agent = Agent(name="...", instructions=instructions, ...)
  ```
  where `instructions` is a function-local variable bound to an
  implicit-concat string literal. PR #4 has nothing to say about this;
  PR #5 does.
- **A small number requiring re-inspection** with the post-PR-#4 numbers
  in hand to judge whether they're TPs, function-local FPs, or
  something else (e.g. `prompt_server/main.py:63`'s
  `instructions=instructions` where `instructions` is set above as a
  function call result — TP under our current rule, but the function
  call returns an MCP-server-provided prompt that may or may not be
  attacker-influenced depending on the MCP server's trust posture).

**Per-finding TP/FP/AMBIGUOUS labels belong to a future precision
measurement, not to this PR's acceptance.** Full corpus precision will
be re-measured after PR #5 and reported in the v0.2 release notes, with
the per-finding breakdown surfaced there.

### 4.8 Acceptance criterion

The openai-agents-python IG002 delta is approximately −6 (±2 to
accommodate minor measurement variance from re-cloning the corpus on a
different day). Other repos' IG002 counts must not change. If either
condition fails, the implementation has a bug and we do not ship — we
investigate before merging.

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
