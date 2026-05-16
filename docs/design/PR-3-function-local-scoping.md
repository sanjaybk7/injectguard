# PR #3 — function-local literal binding: scoping design

**Status:** DRAFT. Awaiting review. No fixtures or implementation will land
until each decision below is confirmed or amended.

This document exists because scoping rules are where static analyzers die.
Fixtures encode design decisions silently; writing fixtures before the
design is locked produces a system whose behavior is described by its tests
rather than its intent.

---

## 0. Opening question — should issue #2 (src-layout) come first?

**My recommendation: yes, promote issue #2 ahead of PR #3.**

### Argument for promotion

- **src-layout is the dominant modern Python packaging convention.** PEP 517/518
  ushered in `pyproject.toml`-based packaging; every modern build backend
  (hatchling, poetry, flit, modern setuptools, pdm) defaults to or recommends
  `src/<pkg>/` layout. Any agent codebase started after ~2021 will almost
  certainly use it. The OpenAI Agents SDK itself uses it.
- **The resolver is structurally broken on this layout.** Fix 1's symbol table
  indexes modules by path-relative-to-scan-root, so a file at
  `src/agents/extensions/handoff_prompt.py` is stored as
  `src.agents.extensions.handoff_prompt`, while user code imports it as
  `agents.extensions.handoff_prompt`. These never match. The cross-module
  resolver silently degrades to v0.1 behavior on every src-layout project.
- **The corpus eval will keep producing misleading numbers until it's fixed.**
  PR #2 already demonstrated this: it surfaced 6 typed agents whose prompts
  *should* resolve cross-module but don't, because src-layout breaks the
  lookup. PR #3's measurement will suffer the same distortion.
- **The fix is small.** Issue #2 sketches three options; option 3 (dual-index
  every module under both `src.<pkg>.<mod>` and `<pkg>.<mod>` when an `src/`
  ancestor is present) is roughly 10–15 lines in `symbol_table.py`. A focused
  PR with a corpus A/B that finally shows the projected −6 delta from PR #2.
- **PR #3 lands cleaner on a stable foundation.** Function-local binding is a
  conceptual contribution; src-layout is plumbing. Reviewing the conceptual
  contribution against numbers that are still wrong because of plumbing is
  noisy.

### Argument against promotion

- Function-local binding was the originally-planned next step; reordering
  introduces scope thrash.
- The src-layout fix is more "polish" than "conceptual contribution"; PR #3
  is the more interesting piece intellectually.
- We've already committed the order publicly (in PR #2's description).

### Net

Strongly recommend promoting issue #2 to be the next PR (call it PR #2.5 or
PR #3, with the current function-local work pushed to PR #4). If you'd
rather stick to the announced sequence, the design below is ready to
execute regardless; the corpus measurement just stays noisy until issue #2
lands.

**Decision required before any of this design ships.**

---

## 1. Scoping primitives — what counts as "function-local scope"?

### 1.1 Plain function bodies (`def`)

**Decision: in scope.** This is the whole point of the PR.

Implementation: when the parser's visitor enters an `ast.FunctionDef`, push a
`FunctionScope` onto a stack, populated by a pre-pass over the function body's
top-level statements (mirroring `collect_module_context`). Pop on exit.

---

### 1.2 Async function bodies (`async def`)

**Decision: in scope, identical handling to plain `def`.**

`ast.AsyncFunctionDef` has the same body structure as `ast.FunctionDef`;
nothing about `async` changes name binding (PEP 492). Treat them through a
single code path that accepts either node type.

---

### 1.3 Methods inside classes

**Decision: method bodies *are* in scope as function scopes; `self.x = "..."`
attribute assignments are *not*.**

A method is just a function; its body has local scope and obeys the same
rules as a top-level function. `def __init__(self): prompt = "lit"; Agent(
instructions=prompt, ...)` should resolve.

`self.x = "..."` is `ast.Assign(targets=[ast.Attribute(value=ast.Name("self"),
attr="x")])` — attribute assignment on the instance, not a local name binding.
Treating instance attributes as resolvable would require flow analysis across
methods (does some other method reassign `self.x`?), inheritance, and class
hierarchies. **Out of scope for this PR;** filed as a separate enhancement
when there's demand.

**Note on existing behavior:** `collect_module_context` only walks
`tree.body`, so methods inside `ast.ClassDef` are not currently visited for
module-scope facts. That's correct — they shouldn't be. PR #3's
function-scope pre-pass *will* walk method bodies when the visitor enters them
via `generic_visit`. That's the right behavior; verified by current LangGraph
and OpenAI parsers using `generic_visit` after `_maybe_register_tool`.

---

### 1.4 Nested functions (closures)

**Decision: yes, walk outward through enclosing function scopes; stop at the
module boundary.**

This matches Python's LEGB rule
(<https://docs.python.org/3/reference/executionmodel.html#resolution-of-names>).
An inner function that references an outer function's binding sees it via
closure capture. If the outer binding is a literal that the inner never
rebinds, the inner can treat it as resolved.

```python
def make_agent(name: str):
    prompt = "You are a helpful assistant."   # outer binding
    def build():
        return Agent(instructions=prompt, ...)   # inner reads outer
    return build
```

Stop the walk at the module boundary; module-scope resolution is already
handled by Fix 1's `ModuleContext`.

**Edge case:** the `nonlocal` declaration in the inner function. Without
`nonlocal`, the inner function can *read* the outer binding but cannot
*rebind* it; `inner_X = "..."` creates a new local. With `nonlocal X`,
assignments in the inner rebind the outer. See §3.9 below for handling.

**Implementation note:** the `FunctionScope` stack naturally supports this.
Walk from innermost outward; the first scope that owns the name wins.

---

### 1.5 Lambdas

**Decision: out of scope by language semantics.** Lambdas are expressions and
cannot contain statements (`x = "..."` is a statement). Confirmed by
<https://docs.python.org/3/reference/expressions.html#lambda>.

A lambda body can *reference* outer-scope bindings — that's just a `Name`
node, handled by the LEGB walk above. We do not need to scan lambda bodies
for new bindings because none exist.

---

### 1.6 Comprehensions (list / dict / set / generator)

**Decision: do not resolve names *bound* in comprehension scope. Do continue
to resolve names *referenced* by comprehensions via the enclosing scope.**

Python 3 introduced an implicit function scope for each comprehension
(<https://docs.python.org/3/reference/expressions.html#displays-for-lists-sets-and-dictionaries>):

> The iteration variables of comprehensions are local to that comprehension
> and not visible from the enclosing scope.

So:
- `[Agent(instructions=p) for p in PROMPTS]` — the `p` iteration variable is
  local to the comprehension; we cannot resolve it to a literal because it
  takes different values per iteration. IG002 should fire.
- `[Agent(instructions=PROMPT) for _ in range(3)]` — `PROMPT` is in the
  enclosing function/module scope; standard resolution applies.

Implementation: when we encounter `ast.ListComp` / `ast.SetComp` /
`ast.DictComp` / `ast.GeneratorExp`, do not extract bindings from its
generators or body. When a `Name` is encountered inside, the LEGB walk
naturally skips the comprehension scope (we never added bindings there) and
finds the outer-scope binding if any. No special-casing required.

**Walrus inside comprehensions** is a separate question — see §2.4.

---

### 1.7 Class bodies

**Decision: out of scope for this PR.** Class-level
`class Cfg: PROMPT = "..."` plus later
`Agent(instructions=Cfg.PROMPT, ...)` is genuinely useful, but:

- It introduces a new dimension (class-attribute lookup as `ast.Attribute`)
  that needs to be threaded through `classify_prompt_expr` and the LEGB walk.
- It interacts with inheritance, `@dataclass`, `@classmethod`, descriptors.
- Real-world agent code uses module-level prompts overwhelmingly more than
  class-attribute prompts.

Defer to a follow-up enhancement. File as a separate issue at PR-#3 merge time.

A class body's *methods*, however, are in scope per §1.3 above.

---

## 2. Assignment forms — what counts as a "literal binding"?

### 2.1 Plain `X = "..."`

**Decision: in scope.** The baseline case. `ast.Assign` with
`targets=[ast.Name]` and `value=ast.Constant(str)` or
`value=ast.JoinedStr` that is constant-only (matches Fix 1's existing
`_value_to_symbol` logic).

### 2.2 Annotated assignment `X: str = "..."`

**Decision: in scope, same semantics.** `ast.AnnAssign` with `target=ast.Name`
and `value=ast.Constant(str)`. Fix 1 already handles this at module scope; the
function-scope pre-pass copies the same logic.

### 2.3 Augmented assignment `X += "..."`

**Decision: out of scope.** Implies `X` was bound before this statement, so by
definition this is a multi-binding pattern. Falls into §3.7 below.

### 2.4 Walrus operator `(X := "...")`

**Decision: in scope as a single assignment within the expression's enclosing
function scope.**

Python 3.8+ (`ast.NamedExpr`). Spec:
<https://docs.python.org/3/reference/expressions.html#assignment-expressions>.

Quirks worth noting:
- A walrus inside a comprehension binds in the **enclosing function** scope,
  not the comprehension scope (deliberate language choice in PEP 572). This
  is the one place where comprehension scope rules are violated.
- Implementation: when scanning a function body for bindings, walk
  `ast.NamedExpr` nodes recursively (including inside comprehensions) and
  treat them as if they were module-scope `ast.Assign` for the enclosing
  function.

**Caveat:** I have not seen the walrus pattern used to bind prompts in any
agent codebase. We're handling it for spec-conformance, not corpus-driven
need. If the implementation cost is non-trivial we can drop it and document.

### 2.5 Tuple unpacking `X, Y = "a", "b"`

**Decision: in scope only when (a) all targets are simple `ast.Name`s, (b) the
value is an `ast.Tuple` (or `ast.List`) of equal length, and (c) every
element of that tuple/list resolves to a string literal. Position-wise
matching.**

Examples:
- `X, Y = "a", "b"` → resolves: `X="a"`, `Y="b"`. ✓
- `X, Y = ("a", "b")` → parsed the same as above. ✓
- `X, Y = func()` → cannot statically determine RHS. ✗ (out of scope)
- `X, (Y, Z) = "a", ("b", "c")` → nested unpacking; out of scope (rare, edge
  case). ✗
- `X = Y, Z = "a", "b"` → multiple-targets-with-tuple. Already handled by
  §2.6 chained-assignment plus tuple-unpacking; just be careful in the
  implementation.

### 2.6 Multiple assignment `X = Y = "..."`

**Decision: in scope.** All targets bind to the same value. `ast.Assign.targets`
is a list; iterate over each `ast.Name` and bind. Fix 1's loop already does
this at module scope; identical logic for function scope.

### 2.7 Starred unpacking `X, *Y = ...`

**Decision: out of scope.** When `ast.Starred` appears in a target list, the
starred name becomes a list, not a string. The non-starred names *could*
resolve under tighter analysis, but the pattern is rare for prompt bindings
and the rule complication isn't worth it. If `X, *Y = "a", "b", "c"` —
`X="a"`, `Y=["b","c"]` — we could resolve `X` only and skip `Y`. Defer.

---

## 3. Control flow — what reassignment patterns disqualify a name?

### 3.1 Single assignment in straight-line function body

**Decision: resolves.** Baseline. The function-scope pre-pass collects names
assigned exactly once at the function body's top level (analogous to Fix 1's
module-scope pre-pass).

### 3.2 Assignment inside `if` / `elif` / `else`

**Decision: do not resolve.** Matches module-scope policy from Fix 1. The
value is conditional on the branch taken; static analysis cannot know which.

Counter-argument considered: if *every* branch binds the name to the *same*
literal, we technically could resolve. Rejected: too much rule complexity for
a vanishingly rare pattern.

### 3.3 Assignment inside `try` / `except`

**Decision: do not resolve.** Matches module-scope policy and §3.2 reasoning.

Note: Fix 1 makes an exception at *module scope* for top-level `try` blocks
specifically because the optional-dependency pattern (`try: from x import Y;
except ImportError: Y = "fallback"`) is extremely common at module scope.
That justification doesn't transfer to function scope — try/except inside a
function body almost always wraps a runtime operation, not an optional
binding. So no exception for function-scope `try`.

### 3.4 Assignment inside `with` block

**Decision: do not resolve.**

Reasoning: consistency with §3.2 / §3.3. The pattern `with open(p) as f:
prompt = "lit"; Agent(instructions=prompt, ...)` is rare; engineers writing
that code are usually inside the `with` to load the prompt from `f`, not to
bind a literal. Conservatively skipping `with` simplifies the rule.

If a corpus pattern emerges that requires this, revisit in v0.3.

### 3.5 Assignment inside `for` loop body

**Decision: do not resolve.** Rebound on each iteration. Even if the RHS is a
literal, the name's lifetime spans multiple iterations and the analyzer
shouldn't assert a single value.

### 3.6 Assignment inside `while` loop body

**Decision: do not resolve.** Same reasoning as §3.5.

### 3.7 Reassignment anywhere later in the same function scope

**Decision: do not resolve.** Matches Fix 1's "multi-assigned names are
dropped" policy. Counter `assign_count[name]`; on second occurrence, evict.

### 3.8 Function parameter shadowing

**Decision: do not resolve.**

Case: `def f(X="default"): X = "literal"; Agent(instructions=X)`.

Reasoning: this is just §3.7 (reassignment of an already-bound name). The
parameter `X` is established at function entry; the assignment `X = "literal"`
is the second binding; per multi-assign policy, drop.

Bonus argument: even if we tried to resolve, the parameter could have been
called with a non-string value, the resulting type would be ambiguous at the
Agent-call site, etc. Don't even try.

### 3.9 `nonlocal` and `global` declarations

**Decision:** when the function declares `nonlocal X`, look up `X` in the
nearest enclosing *function* scope (skipping `X` in the current function's
binding set). When it declares `global X`, look up `X` in `ModuleContext`,
not in any function scope.

This matches Python's name resolution:
<https://docs.python.org/3/reference/simple_stmts.html#the-global-statement>
<https://docs.python.org/3/reference/simple_stmts.html#the-nonlocal-statement>.

If a function has `nonlocal X` and then assigns `X = "literal"`, that
assignment writes to the outer function's `X`. We should *not* register it as
a local binding in the current function's scope, and we should *not*
override the outer scope's record of `X` (which may be multi-assigned). Mark
the outer scope's `X` as "potentially-modified-by-inner" → demote to
dynamic. (Same logic as multi-assign.)

**Implementation:** before the function-scope pre-pass, collect all
`ast.Nonlocal.names` and `ast.Global.names` declared anywhere in the
function body. Exclude those names from the local binding set; route reads
to the appropriate outer scope; route writes outward and demote.

### 3.10 Exception variables

**Decision: out of scope.** `except Exception as e:` binds `e` to the
exception object (an instance of `BaseException`), never a string. We never
want to resolve `e` to a literal.

`ast.ExceptHandler.name` is the bound name. Skip when scanning.

---

## 4. Interaction with module-level / imported names

### 4.1 Function-local shadows module-level

**Decision: function-local wins.** LEGB rule.

```python
PROMPT = "module-level"   # Fix 1's ModuleContext sees this
def make():
    PROMPT = "function-local"   # PR #3's FunctionScope sees this
    return Agent(instructions=PROMPT, ...)  # resolves to "function-local"
```

### 4.2 Function-local shadows imported name

**Decision: function-local wins.** Same reasoning.

```python
from prompts import PROMPT   # Fix 1's CrossModuleResolver sees this
def make():
    PROMPT = "local override"
    return Agent(instructions=PROMPT, ...)  # resolves to "local override"
```

Implementation: the resolution chain becomes
**FunctionScope stack (innermost first) → ModuleContext (local) →
CrossModuleResolver (imports)**. First hit wins.

---

## 5. Implementation sketch (informational, not part of decision)

### 5.1 New types

```python
# analysis/function_scope.py
@dataclass
class FunctionScope:
    function_name: str
    string_constants: dict[str, Symbol]  # single-binding literals
    function_defs: set[str]              # nested function definitions
    nonlocal_names: set[str]             # routed to enclosing FunctionScope
    global_names: set[str]               # routed to ModuleContext
    parent: FunctionScope | None         # for LEGB walk
```

### 5.2 ModuleContext extension

Add a current-function-stack reference, or pass the stack as a separate
parameter to `classify_prompt_expr`. I lean toward extending
`ModuleContext.function_stack: list[FunctionScope]` and updating
`name_resolves_to_static` to walk it innermost-first before falling through
to module-local then cross-module.

### 5.3 Visitor changes

Both `parsers/langgraph.py` and `parsers/openai_agents.py` `_Visitor`
classes gain:

```python
def visit_FunctionDef(self, node):
    scope = build_function_scope(node, parent=self._current_function_scope())
    self.module_ctx.function_stack.append(scope)
    try:
        self._maybe_register_tool(node)
        self.generic_visit(node)
    finally:
        self.module_ctx.function_stack.pop()

visit_AsyncFunctionDef = visit_FunctionDef
```

`build_function_scope` does a single pass over `node.body` collecting bindings
per §3 control-flow rules.

### 5.4 Estimated size

~80–120 LOC of new code, ~20 LOC of changes to existing parsers (the visitor
hooks). Plus ~25–30 fixtures and ~30–40 test assertions per §6.

---

## 6. Fixture matrix

Once §0 is decided and §§1–4 are confirmed/amended, the next step is the
fixture matrix. Each decision below gets at least one fixture; many decisions
share a fixture. Every "in scope" decision needs both a **positive** test
(resolves correctly, no IG002) and a **negative** test of a *similar* pattern
that should *not* resolve (IG002 fires). Every "out of scope" decision needs
a confirmation test (IG002 fires).

I will not author the fixture matrix until §0 is decided and §§1–4 are
confirmed/amended. The matrix below is a *projection*, not a commitment.

| § | Decision | Fixtures (projected) |
|---|---|---|
| 1.1 | plain `def` body in scope | `func_local_basic.py` (+), `func_local_reassigned.py` (−) |
| 1.2 | `async def` identical | `func_local_async.py` (+) |
| 1.3 | method bodies in scope; `self.x` not | `method_local.py` (+), `self_attribute_not_resolved.py` (−) |
| 1.4 | closures walk outward | `closure_outer_binding.py` (+), `closure_inner_rebinds.py` (−) |
| 1.5 | lambdas: no bindings | (covered structurally; one test confirming we don't crash) |
| 1.6 | comprehensions: no scope, outer visible | `comp_iter_var_not_resolved.py` (−), `comp_uses_outer.py` (+) |
| 1.7 | class bodies: out of scope | `class_body_attr_not_resolved.py` (−) |
| 2.1 | plain `X = "..."` | covered by 1.1 fixtures |
| 2.2 | `X: str = "..."` | `func_local_annotated.py` (+) |
| 2.3 | augmented assignment | covered by 3.7 |
| 2.4 | walrus | `walrus_basic.py` (+), `walrus_in_comprehension.py` (+) |
| 2.5 | tuple unpacking | `tuple_unpack_literal.py` (+), `tuple_unpack_call.py` (−) |
| 2.6 | chained assignment | `chained_assignment.py` (+) |
| 2.7 | starred unpacking | `starred_unpack_not_resolved.py` (−) |
| 3.1 | straight-line single binding | covered by 1.1 |
| 3.2 | `if` branch assignment | `if_branch_not_resolved.py` (−) |
| 3.3 | `try`/`except` assignment | `try_branch_not_resolved.py` (−) |
| 3.4 | `with` block assignment | `with_block_not_resolved.py` (−) |
| 3.5 | `for` body assignment | `for_loop_not_resolved.py` (−) |
| 3.6 | `while` body assignment | `while_loop_not_resolved.py` (−) |
| 3.7 | reassignment later | covered by 1.1 negative |
| 3.8 | parameter shadowing | `param_shadow_not_resolved.py` (−) |
| 3.9 | `nonlocal` / `global` | `nonlocal_routes_outward.py`, `global_routes_to_module.py` |
| 3.10 | exception variables | `except_var_not_resolved.py` (−) |
| 4.1 | shadow module-level | `func_shadows_module.py` (+) |
| 4.2 | shadow import | `func_shadows_import.py` (+) |

Projected total: ~22–25 fixture files, ~30 test assertions.

---

## 7. Open questions / acknowledged ambiguities

I do not believe any of the above are ambiguous in the Python language spec.
Citations have been provided where decisions hinge on a language semantics
point. The closest things to genuine ambiguities are:

- **Walrus inside a method's `__init__`** — I believe this behaves the same
  as walrus in any function body (binds in the enclosing function scope, which
  for a method is the method itself). Will verify when implementing.
- **`__class__` and zero-argument `super()`** — closure-magic in methods.
  Not relevant to string-literal binding; ignoring.

---

## 8. Sign-off

This document does not commit any code beyond itself. The first behavioral
commit on this branch will not land until the reviewer either:

1. Decides §0 (promote issue #2 first, or proceed with PR #3).
2. Confirms / amends each of §§1–4.

Until both are done, no fixtures, no implementation, no test file. Stopping
here.
