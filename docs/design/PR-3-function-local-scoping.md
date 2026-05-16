# PR #5 — function-local literal binding: scoping design

**Status:** Decisions locked per review. Branch paused pending PR #4
(src-layout) merge. No fixtures or implementation will land on this branch
until PR #4 is in and the corpus baseline is re-established against it.

This document exists because scoping rules are where static analyzers die.
Fixtures encode design decisions silently; writing fixtures before the
design is locked produces a system whose behavior is described by its tests
rather than its intent.

> **PR renumbering:** This branch was originally proposed as PR #3. Per the
> §0 decision below, the src-layout fix (formerly issue #2) was promoted to
> PR #4, and this work was renumbered to PR #5. The branch name
> (`fix-3-function-local-binding`) is preserved for git history continuity;
> the *PR number* is what changed.

---

## 0. Opening question — should issue #2 (src-layout) come first?

**Final decision: YES — issue #2 promoted ahead of this branch. This branch
is paused pending PR #4 merge.**

After PR #4 lands and the corpus baseline is re-measured (the projected
−6 delta from PR #2 should materialize), this branch will rebase onto
the new main and proceed with fixtures + implementation.

### Original recommendation (for the audit trail)

> **My recommendation: yes, promote issue #2 ahead of PR #3.**
>
> #### Argument for promotion
>
> - **src-layout is the dominant modern Python packaging convention.** PEP 517/518
>   ushered in `pyproject.toml`-based packaging; every modern build backend
>   (hatchling, poetry, flit, modern setuptools, pdm) defaults to or recommends
>   `src/<pkg>/` layout. Any agent codebase started after ~2021 will almost
>   certainly use it. The OpenAI Agents SDK itself uses it.
> - **The resolver is structurally broken on this layout.** Fix 1's symbol table
>   indexes modules by path-relative-to-scan-root, so a file at
>   `src/agents/extensions/handoff_prompt.py` is stored as
>   `src.agents.extensions.handoff_prompt`, while user code imports it as
>   `agents.extensions.handoff_prompt`. These never match. The cross-module
>   resolver silently degrades to v0.1 behavior on every src-layout project.
> - **The corpus eval will keep producing misleading numbers until it's fixed.**
>   PR #2 already demonstrated this: it surfaced 6 typed agents whose prompts
>   *should* resolve cross-module but don't, because src-layout breaks the
>   lookup. PR #3's measurement will suffer the same distortion.
> - **The fix is small.** Issue #2 sketches three options; option 3 (dual-index
>   every module under both `src.<pkg>.<mod>` and `<pkg>.<mod>` when an `src/`
>   ancestor is present) is roughly 10–15 lines in `symbol_table.py`. A focused
>   PR with a corpus A/B that finally shows the projected −6 delta from PR #2.
> - **PR #3 lands cleaner on a stable foundation.** Function-local binding is a
>   conceptual contribution; src-layout is plumbing. Reviewing the conceptual
>   contribution against numbers that are still wrong because of plumbing is
>   noisy.
>
> #### Argument against promotion
>
> - Function-local binding was the originally-planned next step; reordering
>   introduces scope thrash.
> - The src-layout fix is more "polish" than "conceptual contribution"; PR #3
>   is the more interesting piece intellectually.
> - We've already committed the order publicly (in PR #2's description).

---

## How to read §§1–4 below

Each numbered subsection corresponds to a flat decision number (§1 through
§26) in the original review. Every decision is tagged **Status: Confirmed**
or **Status: Amended**. For amendments, the original proposal is preserved
verbatim; the final rule follows under **Final rule**. The git diff is the
audit trail — original prose is never rewritten in place.

---

## 1. Scoping primitives — what counts as "function-local scope"?

### 1.1 Plain function bodies (`def`) — §1

**Status: Confirmed.**

**Decision: in scope.** This is the whole point of the PR.

Implementation: when the parser's visitor enters an `ast.FunctionDef`, push a
`FunctionScope` onto a stack, populated by a pre-pass over the function body's
top-level statements (mirroring `collect_module_context`). Pop on exit.

---

### 1.2 Async function bodies (`async def`) — §2

**Status: Confirmed.**

**Decision: in scope, identical handling to plain `def`.**

`ast.AsyncFunctionDef` has the same body structure as `ast.FunctionDef`;
nothing about `async` changes name binding (PEP 492). Treat them through a
single code path that accepts either node type.

---

### 1.3 Methods inside classes — §3

**Status: Confirmed.**

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

### 1.4 Nested functions (closures) — §4

**Status: Confirmed.**

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

### 1.5 Lambdas — §5

**Status: Confirmed.**

**Decision: out of scope by language semantics.** Lambdas are expressions and
cannot contain statements (`x = "..."` is a statement). Confirmed by
<https://docs.python.org/3/reference/expressions.html#lambda>.

A lambda body can *reference* outer-scope bindings — that's just a `Name`
node, handled by the LEGB walk above. We do not need to scan lambda bodies
for new bindings because none exist.

---

### 1.6 Comprehensions (list / dict / set / generator) — §6

**Status: Confirmed.**

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

### 1.7 Class bodies — §7

**Status: Confirmed.**

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

### 2.1 Plain `X = "..."` — §8

**Status: Confirmed.**

**Decision: in scope.** The baseline case. `ast.Assign` with
`targets=[ast.Name]` and `value=ast.Constant(str)` or
`value=ast.JoinedStr` that is constant-only (matches Fix 1's existing
`_value_to_symbol` logic).

### 2.2 Annotated assignment `X: str = "..."` — §9

**Status: Amended.**

**Original proposal:** in scope, same semantics. `ast.AnnAssign` with
`target=ast.Name` and `value=ast.Constant(str)`. Fix 1 already handles this
at module scope; the function-scope pre-pass copies the same logic.

**Final rule:** also handle `X: Final[str] = "..."` and `X: Final = "..."`
patterns (PEP 591 `typing.Final` declarations). These are the same shape
in the AST — `ast.AnnAssign` whose `annotation` is `ast.Subscript(value=
ast.Name("Final"))` or `ast.Name("Final")` — and they communicate even
stronger single-binding intent than a plain annotation. The annotation
form does not change the binding rule; we just need to make sure the
pre-pass doesn't get confused by the `Subscript`/`Name("Final")`
annotation node and skip the assignment. Pattern:

```python
from typing import Final

def make_agent():
    PROMPT: Final[str] = "You are a helpful assistant."
    OTHER: Final = "fallback"
    return Agent(instructions=PROMPT, ...)
```

Both `PROMPT` and `OTHER` are in scope. The `annotation` field of
`ast.AnnAssign` is parsed but ignored for binding-extraction purposes.

### 2.3 Augmented assignment `X += "..."` — §10

**Status: Confirmed.**

**Decision: out of scope.** Implies `X` was bound before this statement, so by
definition this is a multi-binding pattern. Falls into §3.7 below.

### 2.4 Walrus operator `(X := "...")` — §11

**Status: Amended.**

**Original proposal:** in scope as a single assignment within the
expression's enclosing function scope. Python 3.8+ (`ast.NamedExpr`).
Spec: <https://docs.python.org/3/reference/expressions.html#assignment-expressions>.

> Quirks worth noting:
> - A walrus inside a comprehension binds in the **enclosing function** scope,
>   not the comprehension scope (deliberate language choice in PEP 572). This
>   is the one place where comprehension scope rules are violated.
> - Implementation: when scanning a function body for bindings, walk
>   `ast.NamedExpr` nodes recursively (including inside comprehensions) and
>   treat them as if they were module-scope `ast.Assign` for the enclosing
>   function.

**Final rule:** resolve walrus bindings **only when they appear at statement
level** — i.e. an `ast.Expr` whose value is `ast.NamedExpr`, or as the
direct value of an `ast.Assign` / `ast.Return` / similarly unambiguous
context. **Do not resolve walrus bindings that appear inside complex
conditional expressions** (boolean short-circuits, ternary expressions,
`if`-comprehension filters), because in those cases the binding may or may
not execute depending on evaluation order and short-circuit semantics.

Concretely:

| Pattern | Walrus resolves? |
|---|---|
| `(prompt := "lit"); Agent(instructions=prompt, ...)` | yes (statement-level) |
| `if (prompt := load()) and prompt: Agent(instructions=prompt, ...)` | no (inside boolean expression) |
| `x = (prompt := "lit") if cond else None` | no (inside ternary) |
| `[Agent(instructions=p) for x in items if (p := build(x))]` | no (inside `if`-comprehension filter) |

Reason: the "single deterministic binding" guarantee that justifies
resolution is broken once short-circuit / ternary / filter semantics enter
the picture. The conservative path is to refuse rather than reason about
evaluation order.

**Implementation:** during the function-scope pre-pass, walk for
`ast.NamedExpr` only in positions where the parent is `ast.Expr` (the
statement-level wrapper) or directly the RHS of an `ast.Assign` /
`ast.Return` / `ast.AugAssign` (with AugAssign treated as §10 multi-bind
regardless). Skip walrus nodes nested deeper than that.

**Caveat:** I have not seen the walrus pattern used to bind prompts in any
agent codebase. Handling it for spec-conformance; the amended rule
specifically reduces implementation complexity by refusing the genuinely
ambiguous nested-conditional cases.

### 2.5 Tuple unpacking `X, Y = "a", "b"` — §12

**Status: Amended.**

**Original proposal:** in scope only when (a) all targets are simple
`ast.Name`s, (b) the value is an `ast.Tuple` (or `ast.List`) of equal
length, and (c) every element of that tuple/list resolves to a string
literal. Position-wise matching.

> Examples:
> - `X, Y = "a", "b"` → resolves: `X="a"`, `Y="b"`. ✓
> - `X, Y = ("a", "b")` → parsed the same as above. ✓
> - `X, Y = func()` → cannot statically determine RHS. ✗ (out of scope)
> - `X, (Y, Z) = "a", ("b", "c")` → nested unpacking; out of scope (rare,
>   edge case). ✗
> - `X = Y, Z = "a", "b"` → multiple-targets-with-tuple. Already handled by
>   §2.6 chained-assignment plus tuple-unpacking; just be careful in the
>   implementation.

**Final rule:** **if any RHS element is not a string literal, skip the
entire tuple unpacking — no partial resolution.** Either every name in the
unpacking resolves, or none of them do.

Reason: partial resolution introduces an asymmetry that's surprising and
hard to test. If `X, Y = "a", build_at_runtime()` resolved `X` but not
`Y`, downstream rule output would be inconsistent in a way that's
difficult to explain. The "all or nothing" rule is simpler to reason
about and to test, and the cost (a missed `X` resolution in a rare
pattern) is negligible.

Concretely:

| Pattern | Resolves? |
|---|---|
| `X, Y = "a", "b"` | yes — both `X` and `Y` |
| `X, Y = "a", func()` | **no** — skip entire unpacking (both `X` and `Y`) |
| `X, Y = func(), "b"` | **no** — skip entire unpacking |
| `X, Y = func(), other()` | no — skip entire unpacking |
| `X, Y = ("a", "b")` | yes — same as the first case |
| `X, (Y, Z) = "a", ("b", "c")` | no — nested unpacking, out of scope |
| `X, *Y = "a", "b", "c"` | no — starred unpacking, see §14 |

### 2.6 Multiple assignment `X = Y = "..."` — §13

**Status: Confirmed.**

**Decision: in scope.** All targets bind to the same value. `ast.Assign.targets`
is a list; iterate over each `ast.Name` and bind. Fix 1's loop already does
this at module scope; identical logic for function scope.

### 2.7 Starred unpacking `X, *Y = ...` — §14

**Status: Confirmed.**

**Decision: out of scope.** When `ast.Starred` appears in a target list, the
starred name becomes a list, not a string. Consistent with the §12
amendment (no partial resolution): the entire unpacking is skipped, so
neither `X` nor `Y` resolves.

---

## 3. Control flow — what reassignment patterns disqualify a name?

### 3.1 Single assignment in straight-line function body — §15

**Status: Confirmed.**

**Decision: resolves.** Baseline. The function-scope pre-pass collects names
assigned exactly once at the function body's top level (analogous to Fix 1's
module-scope pre-pass).

### 3.2 Assignment inside `if` / `elif` / `else` — §16

**Status: Amended.**

**Original proposal:** do not resolve. Matches module-scope policy from
Fix 1. The value is conditional on the branch taken; static analysis cannot
know which.

> Counter-argument considered: if *every* branch binds the name to the
> *same* literal, we technically could resolve. Rejected: too much rule
> complexity for a vanishingly rare pattern.

**Final rule:** do not resolve. **Explicitly noted: the "all branches assign
literals" enhancement was considered and deferred.** The pattern in
question is:

```python
def make_agent():
    if some_flag:
        prompt = "literal A"
    else:
        prompt = "literal B"
    return Agent(instructions=prompt, ...)
```

In principle, since *both* branches bind `prompt` to a string literal, we
could resolve `prompt` as "either of two known literals" and treat the
resulting Agent prompt as static (both alternatives are LLM-safe literals).
This is sound but introduces:

- a branch-equivalence walker that must descend `ast.If`, `ast.Match`,
  `ast.Try`'s handler list, etc.
- a "set of possible literal values" representation in `Symbol`
- the question of what to do when only *some* branches bind (the `else`
  branch is missing → behaviorally `prompt` is `UnboundLocalError` if the
  condition is false, which is a different bug)
- a corresponding rule complication for IG002

Deferred to a follow-up enhancement. **For PR #5, conditional binding of
any kind → unresolved → IG002 fires.**

### 3.3 Assignment inside `try` / `except` — §17

**Status: Confirmed.**

**Decision: do not resolve.** Matches module-scope policy and §3.2 reasoning.

Note: Fix 1 makes an exception at *module scope* for top-level `try` blocks
specifically because the optional-dependency pattern (`try: from x import Y;
except ImportError: Y = "fallback"`) is extremely common at module scope.
That justification doesn't transfer to function scope — try/except inside a
function body almost always wraps a runtime operation, not an optional
binding. So no exception for function-scope `try`.

### 3.4 Assignment inside `with` block — §18

**Status: Amended.**

**Original proposal (from the spec):** resolve if it's a single assignment
to a literal and the `with` block doesn't reassign it. Edge case.

**Final rule: do not resolve.** Simpler than the original spec proposal and
consistent with the §16 / §17 treatment of control-flow-bounded
assignments. The pattern `with open(p) as f: prompt = "lit"; Agent(
instructions=prompt, ...)` is rare; engineers writing that code are
usually inside the `with` to load the prompt from `f`, not to bind a
literal. The implementation cost of the original "resolve if single
assignment" rule (track whether reassignment happens elsewhere in the
function, distinguish `with` from `with X as Y:` shadowing, etc.) is not
worth the marginal corpus benefit.

If a corpus pattern emerges that requires this, revisit in v0.3.

### 3.5 Assignment inside `for` loop body — §19

**Status: Confirmed.**

**Decision: do not resolve.** Rebound on each iteration. Even if the RHS is a
literal, the name's lifetime spans multiple iterations and the analyzer
shouldn't assert a single value.

### 3.6 Assignment inside `while` loop body — §20

**Status: Confirmed.**

**Decision: do not resolve.** Same reasoning as §3.5.

### 3.7 Reassignment anywhere later in the same function scope — §21

**Status: Confirmed.**

**Decision: do not resolve.** Matches Fix 1's "multi-assigned names are
dropped" policy. Counter `assign_count[name]`; on second occurrence, evict.

### 3.8 Function parameter shadowing — §22

**Status: Amended.**

**Original proposal:** do not resolve. Case: `def f(X="default"): X =
"literal"; Agent(instructions=X)`. This is just §3.7 (reassignment of an
already-bound name).

> Bonus argument: even if we tried to resolve, the parameter could have
> been called with a non-string value, the resulting type would be
> ambiguous at the Agent-call site, etc. Don't even try.

**Final rule: the rule applies even when the parameter's default value is
itself a string literal.** That is:

```python
def f(X: str = "default literal"):
    X = "another literal"
    return Agent(instructions=X, ...)
```

Both `X = "default literal"` (the parameter default) and `X = "another
literal"` (the in-function assignment) are string-literal-typed bindings.
A naive multi-assign counter might be tempted to say "both are literals,
the second wins, the assignment is unambiguous → resolve." That reasoning
is wrong: the parameter default is the value bound at call sites that
*don't* pass `X`; the second assignment overwrites it; the value at the
Agent call site is `"another literal"`. So technically a resolver could
correctly resolve to `"another literal"`.

But — and this is the key point — the **same code shape** with a
non-literal default behaves identically at the second assignment:

```python
def f(X: str = build_default()):  # default is dynamic, not literal
    X = "another literal"
    return Agent(instructions=X, ...)
```

We don't want the rule to behave differently based on whether the
parameter default happens to be a literal. The rule should focus on the
fact that the function parameter establishes the first binding; any
in-function assignment to the same name is reassignment, regardless of
what the parameter default looks like.

**Concretely:** when scanning a function body for bindings, treat every
parameter name as if it already has one binding (count starts at 1). Any
in-function assignment to a parameter name is therefore the second
binding and triggers the multi-assign-drop rule.

### 3.9 `nonlocal` and `global` declarations — §23

**Status: Confirmed.**

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

### 3.10 Exception variables — §24

**Status: Confirmed.**

**Decision: out of scope.** `except Exception as e:` binds `e` to the
exception object (an instance of `BaseException`), never a string. We never
want to resolve `e` to a literal.

`ast.ExceptHandler.name` is the bound name. Skip when scanning.

---

## 4. Interaction with module-level / imported names

### 4.1 Function-local shadows module-level — §25

**Status: Confirmed.**

**Decision: function-local wins.** LEGB rule.

```python
PROMPT = "module-level"   # Fix 1's ModuleContext sees this
def make():
    PROMPT = "function-local"   # PR #5's FunctionScope sees this
    return Agent(instructions=PROMPT, ...)  # resolves to "function-local"
```

### 4.2 Function-local shadows imported name — §26

**Status: Confirmed.**

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

## 4a. Cross-function pollution prevention

**Status: Newly added per review. Implementation correctness requirement,
not a language-semantics decision.**

**Rule:** resolution inside function `foo` MUST return `foo`'s binding (or
an enclosing scope's binding via LEGB walk per §4 / §23), and MUST NOT
return `bar`'s binding even if both functions bind the same name to
different literals.

**Why this matters:** the cheapest possible implementation of function
scope is "one mutable dict per parser visitor, swap contents on visit
entry." That implementation silently breaks cross-function isolation if
the visitor walks `bar` before `foo` and the swap is incomplete. A more
common failure mode: storing function-scope bindings in
`ModuleContext.function_stack` (a shared list) and forgetting to pop on
exit means `bar`'s bindings leak into `foo`'s scope.

**Failure example to defend against:**

```python
def bar():
    PROMPT = "bar's prompt"        # bar's local
    return Agent(instructions=PROMPT, ...)   # must resolve to "bar's prompt"

def foo():
    return Agent(instructions=PROMPT, ...)   # must NOT resolve; must fire IG002
```

In `foo`, `PROMPT` is not bound locally and not bound at module scope. The
resolver must NOT find `bar`'s `PROMPT` even though both functions live
in the same file.

**Implementation requirements:**

1. `FunctionScope` is a new instance per function visit, never reused.
2. Push/pop discipline on `ModuleContext.function_stack` is bracketed by
   `try/finally` so a parser exception (e.g. a malformed nested node)
   doesn't leave a polluted stack.
3. The LEGB walk in `name_resolves_to_static` walks the stack
   innermost-to-outermost; on exit from a function, the popped scope is
   discarded, not retained.
4. **Tests must include** a fixture with two sibling functions binding
   the same name to different literals, asserting that each Agent call
   resolves to its own function's binding (and neither sees the other).
   This is the §4a regression test.

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

The matrix below is a *projection*, not a commitment. It will be authored
as the second commit on this branch (after PR #4 lands and this branch
rebases). Amendments from review have added rows; nothing has been removed.

| § | Decision | Fixtures (projected) |
|---|---|---|
| 1 (§1.1) | plain `def` body in scope | `func_local_basic.py` (+), `func_local_reassigned.py` (−) |
| 2 (§1.2) | `async def` identical | `func_local_async.py` (+) |
| 3 (§1.3) | method bodies in scope; `self.x` not | `method_local.py` (+), `self_attribute_not_resolved.py` (−) |
| 4 (§1.4) | closures walk outward | `closure_outer_binding.py` (+), `closure_inner_rebinds.py` (−) |
| 5 (§1.5) | lambdas: no bindings | (covered structurally; one test confirming we don't crash) |
| 6 (§1.6) | comprehensions: no scope, outer visible | `comp_iter_var_not_resolved.py` (−), `comp_uses_outer.py` (+) |
| 7 (§1.7) | class bodies: out of scope | `class_body_attr_not_resolved.py` (−) |
| 8 (§2.1) | plain `X = "..."` | covered by §1 fixtures |
| 9 (§2.2) | `X: str = "..."` + `Final[str]` + `Final` | `func_local_annotated.py` (+), `func_local_final.py` (+) |
| 10 (§2.3) | augmented assignment | covered by §21 |
| 11 (§2.4) | walrus, statement-level only | `walrus_statement_level.py` (+), `walrus_in_boolean_expr.py` (−), `walrus_in_ternary.py` (−) |
| 12 (§2.5) | tuple unpacking, all-or-nothing | `tuple_unpack_all_literals.py` (+), `tuple_unpack_mixed.py` (−), `tuple_unpack_call_rhs.py` (−) |
| 13 (§2.6) | chained assignment | `chained_assignment.py` (+) |
| 14 (§2.7) | starred unpacking | `starred_unpack_not_resolved.py` (−) |
| 15 (§3.1) | straight-line single binding | covered by §1 |
| 16 (§3.2) | `if` branch assignment | `if_branch_not_resolved.py` (−), `if_all_branches_same_literal_still_not_resolved.py` (−, documents deferred enhancement) |
| 17 (§3.3) | `try`/`except` assignment | `try_branch_not_resolved.py` (−) |
| 18 (§3.4) | `with` block assignment | `with_block_not_resolved.py` (−) |
| 19 (§3.5) | `for` body assignment | `for_loop_not_resolved.py` (−) |
| 20 (§3.6) | `while` body assignment | `while_loop_not_resolved.py` (−) |
| 21 (§3.7) | reassignment later | covered by §1 negative |
| 22 (§3.8) | parameter shadowing (incl. literal default) | `param_shadow_not_resolved.py` (−), `param_shadow_with_literal_default.py` (−) |
| 23 (§3.9) | `nonlocal` / `global` | `nonlocal_routes_outward.py`, `global_routes_to_module.py` |
| 24 (§3.10) | exception variables | `except_var_not_resolved.py` (−) |
| 25 (§4.1) | shadow module-level | `func_shadows_module.py` (+) |
| 26 (§4.2) | shadow import | `func_shadows_import.py` (+) |
| **4a** | **cross-function pollution prevention** | **`sibling_functions_isolated.py` (one + and one − assertion in the same file) — required** |

Projected total: ~28 fixture files, ~35 test assertions.

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
commit on this branch will not land until:

1. PR #4 (src-layout) merges to main and the corpus baseline is
   re-measured against it.
2. This branch rebases onto the new main.

Decisions §0 (issue #2 promoted) and §§1–4 + §4a (scoping rules) are
locked per review. No further design changes without an explicit
amendment commit on this branch.
