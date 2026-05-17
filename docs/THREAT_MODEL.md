# `agentic-guard` threat model

**Version:** v0.2 (2026-05). Updated alongside the analyzer; semver-tracked.
**Audience:** security researchers, OWASP GenAI contributors, and engineers
deciding whether `agentic-guard` belongs in their AI-security toolchain.
**Position:** static-analysis / design-time defense, complementary to
runtime guards (Lakera, NeMo Guardrails, Prompt Armor, LlamaFirewall).

This document is the contract between what we claim to defend against and
what we ask our users to defend themselves against. Honesty about coverage
gaps is more valuable than coverage breadth — a defender who knows what we
don't catch can wrap us with what does. A defender who thinks we catch
everything ships broken architectures.

---

## 1. Scope

`agentic-guard` is a **static analyzer** that inspects Python source code
defining LLM agents (LangGraph, OpenAI Agents SDK; CrewAI / MCP planned)
and flags architectural patterns that admit prompt-injection and
confused-deputy attacks. It runs at build time / PR time; it does not
intercept prompts at runtime, does not execute code, does not call LLMs,
and does not send data anywhere.

This threat model covers what attacks the analyzer **claims to catch**,
what attacks it **explicitly does not catch**, the **attacker capability
set** the analyzer assumes, and the **coverage limitations** the
implementation inherits from its design choices.

---

## 2. Position in the agent-security ecosystem

| Layer | Examples | What it catches | Where `agentic-guard` fits |
|---|---|---|---|
| Static analysis (design-time) | `agentic-guard`, GitHub CodeQL custom packs | Architectural patterns: source+sink toolboxes, dynamic prompts, unprotected privileged sinks | **This is us.** |
| Runtime classifier (in-band) | Lakera, NeMo Guardrails, Prompt Armor | Specific payloads in inbound or outbound prompts | Complementary; we surface designs that *can* be attacked, they block specific attacks at the moment |
| Runtime sandbox (in-band) | LlamaFirewall, Microsoft Prompt Shields | Tool-call gating, capability enforcement | Complementary; we make sure the architecture is gateable, they enforce the gates |
| Formal verification (proof-time) | Active research (TAINTAWI and successors) | Provable absence of taint flows | Future work; static analysis is the practical compromise today |
| Human-in-the-loop (UX) | Human review of high-stakes tool calls | Whatever the human catches | Orthogonal; we surface which sinks need human gates |

The point: **no single layer is sufficient.** A well-defended agent
combines architectural review (this tool), runtime monitoring (a
classifier or sandbox), and human approval for irreversible actions.
`agentic-guard` makes the architectural-review layer cheap enough to run
on every PR.

---

## 3. What we defend against

### 3.1 Indirect prompt injection via source tools (OWASP LLM01)

An attacker controls data that a source tool returns to the LLM —
typically by sending an email, posting to a public web page, ingesting a
document into a RAG corpus, or opening a support ticket containing
adversarial instructions. The LLM treats that content as input, the
adversarial instructions get interpreted as system directives, and the
agent executes them.

**What `agentic-guard` catches:** any agent whose toolbox includes a
classified source (see `src/agentic_guard/taxonomy.yaml`) — even one
without an explicit privileged sink. The presence of an attacker-
controllable input alone is a signal worth surfacing in the SARIF /
JSON output, even when the severity is low.

**What's required for the catch to fire:** the source must match the
taxonomy by name or docstring (`read_email`, `search_web`, `fetch_url`,
`read_pdf`, `query_database`, etc.). Tools with neutral names whose
function bodies internally call a source library (`requests.get` on
attacker-influenced URLs, `feedparser.parse`, etc.) are caught by IG003
(library-call rule) when that rule lands.

### 3.2 Confused-deputy attacks (OWASP LLM01 + LLM06)

The classical agent-security failure: an agent has *both* a source tool
(returns attacker-controllable content) *and* a privileged sink (sends
email, transfers money, executes shell commands, deletes files), with
the LLM acting as the unwitting middleman. Attacker-controlled content
flowing into the source tool causes the LLM to call the sink with
attacker-chosen arguments, under the user's authority.

Real-world incidents in this class: Bing Chat data exfiltration via
prompt-injected web content; Slack AI exfiltration via prompt-injected
direct messages; Microsoft 365 Copilot data leakage via prompt-injected
emails; ChatGPT plugin attacks via web-scraped content.

**What `agentic-guard` catches (IG001):** any agent whose toolbox
contains both a classified source and a classified sink without a
human-in-the-loop gate (`interrupt_before=[...]`,
`tool_use_behavior="stop_on_first_tool"`, `requires_approval=True`,
`StopAtTools(...)`). Severity scales with the sink's privilege and
reversibility per the rubric in [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md#severity-scoring).

**The conceptual move:** classical taint analysis tracks data flow
through variables. There is no such flow from source tools to sink
tools in LLM agent code — the LLM picks at runtime. We treat the LLM
as a *fully-connected, adversarially-controlled edge* in the taint
graph: if both endpoints exist in the same agent's toolbox, assume the
edge can be activated. The mitigation primitive — a human-approval gate
on the sink — corresponds to a classical-taint sanitizer.

### 3.3 Dynamic system-prompt injection (OWASP LLM01)

The system prompt is the highest-trust slot in any LLM call. If it's
built at runtime from user input or external data — an f-string with
user variables, `.format()` with request data, string concatenation,
loaded from a file or database — an attacker who can influence that
input can rewrite the agent's instructions.

**What `agentic-guard` catches (IG002):** any agent whose system prompt
is anything other than a static literal (or a name resolving to one in
the module-local or cross-module scope per Fix 1 + PR #4). Severity is
bumped when interpolated names match user-controlled hints (`request`,
`user_input`, `body`, `query`, `payload`, etc.).

---

## 4. What we explicitly do NOT defend against

### 4.1 Direct prompt injection from end users

When a user interacts with the agent and types adversarial text in the
chat box, the analyzer has nothing to say. Direct prompt injection is a
runtime concern; mitigations include classifier-based filters (Lakera,
Prompt Armor), reinforcement-learning-from-human-feedback hardening, and
prompt-template defenses (system-vs-user separation). Use runtime
defenses.

### 4.2 Model jailbreaking / instruction override

If the LLM itself can be convinced to ignore its system prompt via
clever phrasing, the analyzer's architectural review doesn't help —
the architecture might be sound and the model might still be tricked.
Mitigations: model-side fine-tuning, classifier wrappers, adversarial
training. Out of scope here.

### 4.3 Training-data poisoning

The analyzer assumes the LLM behaves consistently with the developer's
expectations; if the LLM was trained on poisoned data and has
adversarial backdoors, no source-code analysis can detect it.
Out of scope.

### 4.4 Supply-chain attacks on dependencies

A malicious `langchain` release or compromised PyPI package can
introduce backdoors into agent code without the agent author's
knowledge. The analyzer reads the agent author's source; it doesn't
audit dependencies. Use Sigstore, pip-audit, dependency pinning,
Sigstore-verified wheels, and vendoring policies for this. Out of scope.

### 4.5 Adversarial examples against multimodal models

Specially-crafted images, audio, or video designed to perturb a
multimodal LLM's interpretation are out of scope. The analyzer reads
Python; it doesn't analyze image content. Use multimodal-specific
defenses (input sanitization, watermarking detection). Out of scope.

### 4.6 Runtime-only attacks

The analyzer is static — it cannot detect attacks that depend on
runtime state: time-of-check-to-time-of-use (TOCTOU) races on
filesystem permissions, network conditions, memory-corruption exploits
in the agent runtime, etc. Runtime monitoring is the right layer.
Out of scope.

### 4.7 Side-channel attacks

Cache timing, power-analysis, electromagnetic emanations, and other
hardware/runtime side channels are out of scope. The analyzer cannot
see them.

### 4.8 Denial of service

Resource-exhaustion attacks (a malicious user causing the agent to
make millions of API calls, or to consume unbounded tokens) are out of
scope. Rate-limiting and quota systems handle this.

### 4.9 Model extraction / inversion

The analyzer doesn't model attackers' attempts to reconstruct the LLM's
training data or weights from query interactions. This is an AI-privacy
concern, not an architectural-safety concern. Out of scope.

---

## 5. Attacker capability assumptions

We assume an attacker has the following capabilities:

### 5.1 Can control content that flows into source tools

The attacker can:
- Send emails to addresses the agent reads (`read_email`, `get_email`,
  `fetch_email` tools)
- Post content to web pages the agent fetches (`search_web`,
  `fetch_url`, `browse`, `scrape` tools)
- Upload documents to systems the agent reads
  (`read_document`, `read_pdf` tools)
- Submit support tickets or messages the agent processes
  (`get_ticket`, `get_issue`, `read_message`, `read_slack` tools)
- Influence content in RAG corpora the agent queries (`rag_lookup`,
  `vector_search` tools)
- Insert content into database rows the agent reads (`query_database`,
  `query_user_db` tools) when the database accepts external writes

### 5.2 Cannot modify the agent's source code

If the attacker can modify the agent's source code, the threat model
changes entirely — they no longer need a confused-deputy attack
because they can just call the sink directly. We assume the attacker
operates against an agent whose code is fixed.

### 5.3 Cannot directly call privileged sinks

The attacker cannot invoke `send_email`, `transfer_money`, `run_shell`,
etc., except through the LLM. If they could, again, no architectural
defense matters. We assume the agent is the only path to the sinks.

### 5.4 The LLM is treated as adversarially-routed

This is the strongest assumption — and the most important one. We do
not model the LLM as "probably won't get tricked" or "will refuse
obvious attacks." We model it as a fully-connected edge in the
taint-flow graph: **any tool combination the LLM could route, we
assume it will, with adversarial selection of tool arguments.** This
is conservative-on-doubt by design. If a sink could be called in a way
that exfiltrates data or causes irreversible harm, we assume it will
be.

This is the same modeling assumption that makes classical buffer
overflow analysis conservative: we don't assume the attacker can't
craft the right input; we assume they can.

### 5.5 We do not rely on the LLM provider's built-in defenses

The provider's safety classifiers, fine-tuning, and RLHF alignment are
not counted as part of our threat-model coverage. If those defenses
fail — whether through adversarial inputs that bypass them, training-
time issues, or supply-chain compromise — the analyzer's claims should
still hold. This follows from §5.4 (the LLM is treated as
adversarially-routed) and is restated here so it isn't accidentally
elided by a reader who reads §5 alone.

### 5.6 Attacker does NOT have

- Access to the agent's runtime environment (process memory, env vars,
  config files)
- Ability to perform man-in-the-middle attacks on TLS connections
  between the agent and its tool implementations
- Privileged user accounts on the agent's host
- Knowledge of secrets that aren't already exposed in the agent's
  source code or visible-to-LLM metadata

If the attacker has any of these, you have a bigger problem than
prompt injection; use OS-level defenses.

---

## 6. Defender capability assumptions

We assume the defender:

- **Controls the agent's source code** and the tool definitions in it.
  The defender is the one running `agentic-guard`.
- **Wants safe-by-architecture agents.** They are willing to add
  human-approval gates, split tools across multiple agents with no
  shared LLM context, or rewrite docstrings to avoid leaks.
- **Has tool source code available for static analysis.** Tools
  implemented in vendored libraries we can read; tools implemented as
  opaque HTTP calls to external services we treat by the tool's
  documented behavior (taxonomy classification).
- **Wants pre-deployment signal.** They are running the analyzer at PR
  time or CI time, not as an incident-response tool after a breach.
- **Will read SARIF / JSON output** and act on findings before
  shipping. The analyzer doesn't auto-fix; it surfaces.

We do not assume the defender:
- Is a security specialist
- Has time to write custom rules
- Has access to runtime telemetry
- Will read every finding — high-severity must dominate the output

---

## 7. Coverage limitations

These are the sharp edges. Each is a deliberate trade-off; knowing them
is what separates the analyzer from snake oil.

### 7.1 Naming-based source/sink classification

The taxonomy classifies tools by their *names* and *docstrings* per
[`src/agentic_guard/taxonomy.yaml`](../src/agentic_guard/taxonomy.yaml).
A function named `process(payload)` whose body internally calls
`smtplib.send_message(...)` is not currently classified as a sink.

**Mitigation:** IG003 (library-call rule, planned v0.2) walks tool
function bodies for known-dangerous library calls and reclassifies
tools accordingly. Until IG003 ships, this is a known false-negative
class.

**Why we accept the limitation:** every static analyzer in production
(Bandit, ESLint, Semgrep, even CodeQL in default rule sets) relies on
naming-based source/sink classification as a first pass. It's more
defensible for agent code than for general-purpose code because the
LLM itself only sees the tool's name and docstring when deciding when
to call it — so well-written agent code has descriptive names by
necessity.

### 7.2 Dynamic dispatch is not modeled

`getattr(obj, 'method_name')(...)` patterns where `method_name` is not
a literal string are not resolved. The analyzer cannot know which
method gets called. This is a known false-negative.

### 7.3 Runtime-loaded prompts are not resolved

`instructions = open('prompt.txt').read()` or `instructions =
db.query(...)` produce prompts the analyzer cannot inspect. These are
flagged as dynamic (IG002 fires) by default; if the loaded content is
in fact static and benign, IG002 is a false positive in that case.

**Why we don't try harder:** following runtime-loaded content would
require reading files at analysis time, which violates the "no I/O,
no execution" invariant. Conservative-on-doubt is the right default.

### 7.4 Cross-module resolution is bounded

Fix 1 + PR #4 (v0.2) resolve cross-module string constants for
package-relative imports under flat and src-layout. Remaining gaps:

- **PEP 420 multi-root namespace packages** spanning multiple
  `sys.path` entries are not modeled.
- **Re-export chains beyond one hop** are not followed.
- **`pyproject.toml`-driven custom layouts** (e.g.
  `[tool.setuptools.package-dir] my_pkg = "lib/source"`) are not
  parsed.

Each is documented in [`docs/design/PR-4-src-layout.md`](design/PR-4-src-layout.md) §2.6.

### 7.5 Function-local literal binding is not resolved (until PR #5)

`instructions = "...literal..."` bound inside a function body is not
yet resolved as a static literal; the analyzer treats it as dynamic
and IG002 fires. The PR #5 design doc on the `fix-3-function-local-binding`
branch locks the scoping rules; implementation pending.

### 7.6 Cross-process attacks are not modeled

If the agent calls a microservice that itself reads attacker-controlled
content and returns it to the agent, the analyzer sees only the agent
and the tool stub. The taint flow into the microservice is invisible.

**Mitigation:** classify the tool stub as a source if its
implementation reads untrusted content. The defender has to make this
classification call; the taxonomy is community-extensible to support
project-specific entries.

### 7.7 Time-of-check-to-time-of-use (TOCTOU) issues are not modeled

If a tool checks permissions, then takes an action, and the
permissions change between the two, the analyzer doesn't catch it.
Runtime-only concern.

### 7.8 Multi-agent coordination attacks are partially covered

A two-agent system where Agent A has a source and Agent B has a sink,
connected by a `handoff` mechanism (CrewAI, OpenAI Agents SDK handoffs)
that shares LLM context — IG001 fires on the combined-toolbox view.
But more elaborate orchestrations (event-driven multi-agent systems,
asynchronous tool queues, agent-to-agent messaging via external
brokers) are not yet modeled. Active area.

### 7.9 TypeScript / non-Python frameworks are out of scope

The analyzer is Python-only. LangChain.js, Vercel AI SDK, Microsoft
Bot Framework (Node.js variant), and other JS/TS-based agent
frameworks are not analyzed. Adding TS support is a v1 consideration.

### 7.10 The analyzer trusts its own taxonomy

The taxonomy itself (`taxonomy.yaml`) is the trust root. A defender
who edits it to misclassify a sink as neutral defeats the analyzer.
This is by design — the taxonomy is community-editable for
project-specific tools — but it means an attacker who can modify the
defender's `taxonomy.yaml` can suppress findings. Treat the taxonomy
file as security-sensitive in your VCS (require reviews on changes).

---

## 8. Comparison to adjacent threat models

| Threat model | What it covers | Where it overlaps with us |
|---|---|---|
| **OWASP LLM Top 10** (2025 edition) | Application-level LLM risks: LLM01 (prompt injection), LLM02 (insecure output handling), LLM06 (sensitive info disclosure), LLM07 (insecure plugin design), LLM08 (excessive agency) | We catch LLM01, LLM06, LLM07, LLM08 patterns at design-time. Not all instances; not exhaustively. |
| **Meta LlamaFirewall** | Runtime sandbox for tool calls: argument scrubbing, capability enforcement, output redaction | Complementary. We surface designs that *can* be sandboxed; they enforce the sandbox at runtime. |
| The **formal taint-analysis line of research** for agentic workflows (TAINTAWI and successors) | Provable absence of taint flows in LLM-agent code using SMT-style techniques | Aspirational. We approximate the same intent with a fast static check; formal methods prove; we surface. |
| **Microsoft Prompt Shields** | Classifier-based input/output filtering | Different layer. They catch payloads at runtime; we catch architectures that admit payloads at design time. |
| **Simon Willison's prompt-injection writing** (informal canonical reference) | Conceptual framing of indirect prompt injection as the dominant LLM-security failure mode | We operationalize the framing into static checks. The "Markdown image exfil" example from his blog is a direct case our IG001 catches when the relevant tool is in scope. |

---

## 9. Threat-model evolution

This document is **versioned with the analyzer**. v0.2 reflects the
post-Fix-1 / post-PR-#4 state. Anticipated changes:

- **v0.3** will add: IG003 (library-call rule) → §3.1 coverage expands;
  IG004 (architectural-leak rule) → a new §3 entry opens to cover
  *architectural information leakage* (sensitive content in tool
  docstrings / decorator descriptions visible to the LLM: credential
  patterns, internal hostnames, auth instructions, embedded connection
  strings); PR #5 (function-local literal binding) → §7.5 removed.
- **v0.4 or later**: CrewAI / MCP / Microsoft Agent Framework parsers
  → §3 coverage extends to those ecosystems; multi-agent attack
  patterns may move from §7.8 to §3.

When a new rule lands, the corresponding §3 entry is added *and* the
matching §7 limitation is moved out — in the same PR. We do not let
coverage claims drift ahead of implementation; equally, we do not
claim future coverage in the present-tense sections of this document.
This v0.2 revision deliberately removed a forward-referenced §3.3
(IG004) for that reason.

---

## 10. Reporting a threat-model gap

If you find an attack class this document doesn't cover, or a coverage
claim that's stronger than the implementation supports, open an issue
at <https://github.com/sanjaybk7/agentic-guard/issues> with the label
`threat-model`. Substantive reports get incorporated into the next
version of this document.

---

## Further reading

- **OWASP LLM Top 10:** <https://genai.owasp.org/llm-top-10/>
- **Norm Hardy, "The Confused Deputy" (1988):** the original capability-
  systems framing this analyzer's IG001 rule descends from.
- **Simon Willison's prompt-injection writing:**
  <https://simonwillison.net/tags/prompt-injection/>
- **The formal taint-analysis line of research for agentic workflows**
  (TAINTAWI and successors): provable absence of taint flows in
  LLM-agent code.
- **Meta LlamaFirewall (paper + release):** runtime sandboxing for
  agent tool calls.
- **`docs/HOW_IT_WORKS.md`:** the analyzer's architecture, rule design,
  and severity scoring rubric.
