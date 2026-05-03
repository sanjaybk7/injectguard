# How InjectGuard works

A technical deep-dive into the architecture, design choices, and limitations
of `injectguard`. Written for engineers and security researchers who want to
understand what the tool does, why, and where its sharp edges are.

---

## TL;DR

InjectGuard reads Python files (and Jupyter notebooks) statically, identifies
LLM agent definitions and the tools attached to them, classifies each tool as
a *source* (returns untrusted data) or *sink* (causes side effects) using a
YAML taxonomy of name patterns, and runs a small set of rules over the
resulting graph. The novel piece is treating the LLM itself as an
adversarially-controlled edge in a taint-analysis graph: if a tainted source
and a privileged sink coexist in the same agent's toolbox, we flag the agent
as a confused-deputy risk regardless of whether any code path explicitly wires
them together.

No code is executed. No data leaves the user's machine. No LLM calls are made.

---

## The pipeline in one diagram

```
   Source files (.py + .ipynb)
              │
              ▼
   ┌──────────────────────┐    ┌──────────────────────┐
   │ Per-framework parser │───▶│  Framework-agnostic  │
   │  (LangGraph,         │    │  IR: Tool, Agent,    │
   │   OpenAI Agents)     │    │  Finding             │
   └──────────────────────┘    └──────────┬───────────┘
                                          │
                                          ▼
                               ┌──────────────────────┐
                               │ Source/Sink taxonomy │
                               │       (YAML)         │
                               └──────────┬───────────┘
                                          │
                                          ▼
                               ┌──────────────────────┐
                               │  Detection rules     │
                               │  (IG001, IG002, ...) │
                               └──────────┬───────────┘
                                          │
                                          ▼
                          Pretty / SARIF / JSON output
```

Each box maps to a real module:
- Per-framework parsers: `src/injectguard/parsers/`
- IR types: `src/injectguard/ir.py`
- Taxonomy: `src/injectguard/taxonomy.py` + `taxonomy.yaml`
- Rules: `src/injectguard/rules/`
- Engine that wires it all together: `src/injectguard/engine.py`
- Output formatters: `src/injectguard/output/`

---

## Step 1 — discovery

`Scanner._iter_scannable_files()` (in `engine.py`) walks the target path and
yields candidate files. By default it picks up `.py` and `.ipynb`, and skips:

- `.git/`, `.venv/`, `node_modules/`, `__pycache__/`, build outputs, cache
  directories
- Anything matching `tests/`, `test/`, `__tests__/`, `test_*.py`, `*_test.py`,
  `conftest.py` — test fixtures intentionally encode vulnerable patterns to
  exercise framework behavior, and flagging them as production findings was
  ~55% of the noise in our first round of real-world scans.

`--include-tests` opts back in.

For notebooks, `notebook.load_notebook()` reads the file with `nbformat`,
extracts only the *code* cells, sanitizes IPython magics (`%pip`) and shell
escapes (`!ls`) by replacing them with blank lines (preserving line numbers
for AST parsing), and concatenates the result into one virtual Python source
string. A line-to-cell map is retained so findings can be reported as
`notebook.ipynb cell[N] line M`.

---

## Step 2 — parse

For each scannable file, `ast.parse()` produces an Abstract Syntax Tree. This
is Python's built-in static representation of source code; nothing executes.

We then run *every* registered parser against the tree, but each parser
short-circuits via `matches_file()` if the file's imports don't reference its
framework. So a file importing `langgraph` is processed only by `LangGraphParser`,
and a generic `class Agent:` in unrelated code triggers nothing.

This is important: the OpenAI Agents SDK exports a class named `Agent`, which
is a generic name. Without import-based gating, we'd false-positive on every
codebase that happens to have an `Agent` class. See
`OpenAIAgentsParser.matches_file()` for the gate.

---

## Step 3 — extract Tools and Agents

Each parser walks its file's AST looking for two things:

### Tools

Functions decorated with `@tool` (LangGraph) or `@function_tool` (OpenAI Agents
SDK). For each, we capture the function name, an optional name override from
the decorator (`@function_tool(name_override="foo")`), and the docstring.

We then ask the **taxonomy** to classify the tool. The taxonomy is a YAML file
(`src/injectguard/taxonomy.yaml`) with three sections — `sources`, `sinks`, and
`both` — where each entry is a name-pattern + privilege level + reversibility +
`trust_of_output`. Matching is case-insensitive substring against the tool name
*and* the docstring; longest-match wins, so `send_email` beats `send`.

```yaml
sources:
  - pattern: read_email
    privilege: 1
    trust_of_output: untrusted
    rationale: "Email body is attacker-controllable text."

sinks:
  - pattern: send_email
    privilege: 2
    reversible: false
```

The taxonomy is intentionally **data, not code** — the same playbook that
made Semgrep extensible. Anyone can add a tool pattern without writing Python.

### Agents

For LangGraph: calls to `create_react_agent(...)` or sibling factories. For
OpenAI Agents SDK: `Agent(...)` constructor calls.

For each agent, we extract:
- The list of tools passed in
- The system prompt (`prompt=` for LangGraph, `instructions=` for OpenAI)
- Any human-approval gates (`interrupt_before=[...]`,
  `tool_use_behavior="stop_on_first_tool"`, `StopAtTools(...)`)

Both parsers produce the same IR types (`Tool`, `Agent`) defined in `ir.py`.
This is the framework-agnostic intermediate representation: rules operate on
it without knowing which framework the code came from.

### Module-level context

Before walking for tools and agents, each parser first runs
`collect_module_context()` (in `parsers/base.py`) to record:

- **String constants** assigned at module scope: `MY_PROMPT = "..."`
- **Function definitions** at module scope

When evaluating whether a system prompt is "dynamic," we use this context. If
`instructions=MY_PROMPT` and `MY_PROMPT` resolves to a string literal, we treat
it as static. If it resolves to a function definition (the canonical
OpenAI SDK pattern for context-aware prompts), we also treat it as safe. This
single change collapsed ~17% of the false positives we saw in our first
real-world scan round.

We *don't* follow imports across modules — that's a documented v0 limitation.

---

## Step 4 — rule evaluation

Two rules ship in v0:

### IG001 — Confused deputy

For every agent, find pairs `(source, sink)` from its toolbox where:
- The sink has `privilege >= 1`
- The sink is *not* gated (no `interrupt_before` for it, no
  `tool_use_behavior` global gate, no `requires_approval=True`)

If both conditions hold, emit a finding with severity scored as:

```
sink.privilege == 3 and not reversible  →  CRITICAL
sink.privilege >= 2 and not reversible  →  HIGH
sink.privilege >= 2                     →  MEDIUM
otherwise                               →  LOW

(if source.trust_of_output == UNTRUSTED, bump one band where applicable)
```

The intuition: an LLM with `read_email` and `send_email` in its toolbox can be
coerced — via a prompt-injection payload buried in an incoming email — into
sending email on the user's behalf. The LLM is the **confused deputy**: it
acts with the user's authority on the attacker's instructions. This pattern
has shipped publicly at major companies (Bing Chat, Slack AI, Microsoft
Copilot, ChatGPT plugins).

### IG002 — Dynamic system prompt

If the agent's system prompt is anything other than a static string literal
(or a Name resolving to one in the same module), flag it. Severity is bumped
to HIGH if the interpolated variable name looks user-controlled (`request`,
`user_input`, `body`, `query`, `payload`, etc.).

The intuition: the system prompt is the highest-trust slot in any LLM call.
If it's built at runtime from data that may be attacker-controllable, an
attacker can rewrite the agent's instructions.

---

## Step 5 — output

Three formats, all from the same `ScanResult`:

- **Pretty terminal** (`output/pretty.py`) — Rich-styled bordered panels, color
  by severity, OWASP IDs, fix hints. Notebook locations render as
  `notebook.ipynb cell[N] line M`.
- **SARIF v2.1.0** (`output/sarif.py`) — the OASIS-standard interchange format
  consumed by GitHub code scanning, JetBrains IDEs, VS Code's SARIF Viewer,
  Sonar, and most other modern code-review surfaces. Includes
  `security-severity` numeric scores (CVSS-like) so GitHub renders proper
  Critical/High badges in the Security tab.
- **JSON** (`output/json_out.py`) — machine-readable, including a `cell` field
  for notebook findings.

Exit code is driven by `--fail-on` (default `high`): non-zero if any finding
meets or exceeds the threshold.

---

## Why static analysis is the right primitive

A reasonable question: why not analyze prompts at runtime, like Lakera or
NeMo Guardrails do?

Runtime defenses are valuable and complementary, but they have a structural
blind spot: **they can't see the architecture**. A runtime tool inspecting an
in-flight prompt has no way to know that the agent it's protecting also has a
`send_email` tool registered. It can't tell you "this agent is structurally
dangerous." It can only react to specific payloads it recognizes.

Static analysis catches the *design* of the agent. It says: "you've built an
agent that combines an attacker-controlled input source with a high-privilege
side effect, with nothing between them. If the LLM ever gets a clever prompt,
you lose." That's the kind of architectural risk you want to surface at PR
time, not at incident-response time.

Both approaches have their place. InjectGuard fills the static gap.

---

## Adapting taint analysis for LLM agents

This is the conceptual move worth understanding deeply, because it's the part
that makes InjectGuard's approach defensible.

**Classical taint analysis** (used in tools like Pysa, CodeQL, Semgrep) tracks
data flowing through *variables*. If untrusted data reaches a sink without
sanitization, that's a vulnerability. SQL injection, XSS, command injection
— all caught this way.

**Why classical taint analysis doesn't fit LLM agents:** there is no static
data flow from source tools to sink tools in the source code. The LLM decides
at runtime which tool to call next. There is no `send_email(read_email(id))`
line for a static analyzer to follow.

**The reframe:** treat the LLM itself as a **fully-connected, untrusted edge**
in the taint graph. If an agent has both a tainted source and a privileged
sink in its toolbox, assume the LLM can be coerced into routing data from
one to the other. The agent's *toolbox* becomes the data-flow graph; the
LLM is the propagator.

```
classical:    untrusted_var ──flows-via-code──▶ sink(untrusted_var)
ours:         tainted_tool() ──flows-via-LLM──▶ sink_tool()
              (graph edge inferred from co-membership in agent.tools)
```

The mitigation primitive — human-in-the-loop gates (`interrupt_before`,
`tool_use_behavior`, `requires_approval`) — corresponds to a sanitizer in
classical-taint terms: it breaks the edge.

This framing is conservative by design. If an LLM *could* route the data, we
assume it *will*. That's the right default when the routing function is
non-deterministic and adversarially probable.

---

## The architectural payoff: framework-agnostic rules

A practical consequence of the IR design: detection rules are written **once**,
against the IR, and don't know which framework produced the input. Adding
support for Microsoft Agent Framework, MCP servers, or AutoGen will be
purely a parser-level change — the rules stay the same.

This is the same pattern LLVM uses for compilers (any source language → LLVM
IR → any target machine). It's why adding a new language to LLVM gets every
CPU target for free, and it's why adding a framework to InjectGuard gets every
rule for free.

---

## Severity scoring

Severity is computed per finding, never per rule. Every tool entry in the
taxonomy carries a `privilege` (0–3) and `reversible` (bool). When a rule
emits a finding, those properties combine with the source's
`trust_of_output` (`untrusted`/`mixed`/`trusted`) to produce one of five
qualitative bands (`critical`/`high`/`medium`/`low`/`info`).

Those bands map cleanly into SARIF's numeric `security-severity` field, which
is what GitHub uses to display "Critical/High" badges in the Security tab.
The mapping (in `output/sarif.py`):

```
CRITICAL  →  9.5
HIGH      →  8.0
MEDIUM    →  5.0
LOW       →  3.0
INFO      →  1.0
```

This is loosely CVSS-inspired but tuned for agent-specific concerns. We
deliberately keep the model small — engineers can read the formula in a
single page of code — rather than building an opaque scoring engine.

---

## Honest limitations

These are the sharp edges. Knowing them is what separates real engineers
from people selling magic.

### Names are the contract

The taxonomy classifies tools by their *names* and *docstrings*, not by what
their function bodies do. A tool named `process(payload)` whose body
internally calls `smtplib.send_message(...)` will be classified as `NEUTRAL`
and will not fire any rule.

This is a deliberate trade-off, shared by every static analyzer in production
(Bandit, ESLint, Semgrep, even CodeQL all rely on naming-based models for
sources/sinks). It's also more defensible for agent code than for normal code,
because the LLM itself only sees the tool's name and docstring — not the
body — when deciding when to call it. So well-written agent code has
descriptive names by necessity.

The roadmap item to close this gap is **IG003 — library-call rule**, which
will walk inside tool function bodies for known-dangerous library calls
(`smtplib.send_*`, `subprocess.run`, `requests.post`, `boto3.client('ses')`,
etc.). Deferred until v0 launch generates real demand signal.

### Cross-module imports are not resolved

We resolve `instructions=NAME` where `NAME = "..."` lives in the same module.
We don't follow imports. So if a project does:

```python
from prompts import SYSTEM_PROMPT

agent = Agent(instructions=SYSTEM_PROMPT, ...)
```

…we'll currently flag `IG002` because we can't see `SYSTEM_PROMPT`'s
definition in the imported module. This is the most common residual false
positive after the v0.1 fixes; it's documented as a v0 limitation. Closing
it requires whole-package analysis, which is a meaningful jump in
complexity.

### LLM-as-instructions callable bodies are not analyzed

The OpenAI Agents SDK supports `instructions=callable_function` for context-
aware prompts. We treat this as safe (the documented SDK pattern). But the
callable's body could itself build a prompt from untrusted input — we don't
walk into it. A v1 enhancement could.

### Python-only

No support for TypeScript-based agent frameworks at v0.

### Notebook line numbers are 1:1 within a cell

Notebook findings report `cell[N] line M` where M is the line within that
specific cell. We don't currently render multi-line ranges that span cells
— in practice agent definitions are confined to single cells, so this hasn't
mattered.

---

## What you can extend

The most impactful contributions, in order:

1. **Add taxonomy entries** in `src/injectguard/taxonomy.yaml`. Each entry is
   one YAML block; no Python required. If you've seen a sink-y tool name
   in the wild that we don't recognize, add it.

2. **Write a new rule** by subclassing `Rule` in `src/injectguard/rules/`.
   See `rules/confused_deputy.py` for the template.

3. **Add a new framework parser** by subclassing `FrameworkParser` in
   `src/injectguard/parsers/`. See `parsers/openai_agents.py` for a complete
   example. The pattern: implement `matches_file()` (import gate) and
   `extract()` (produce IR Tools and Agents).

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full contribution flow.

---

## Further reading

- **OWASP LLM Top 10** — https://genai.owasp.org/llm-top-10/
- **The original "Confused Deputy" paper** — Norm Hardy, 1988
- **Semgrep's rule design** — the closest analog for "rules as data"
- **Simon Willison's prompt-injection writing** — the canonical primer on the
  attack class this tool defends against
