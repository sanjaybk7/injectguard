# Contributing to injectguard

Thanks for your interest. This project is alpha — feedback, bug reports, taxonomy
additions, and rule contributions are all welcome.

If you haven't read [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) yet, start there.
It explains the architecture and where each kind of contribution fits.

---

## Development setup

```bash
git clone https://github.com/sanjaybk7/injectguard.git
cd injectguard
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Python 3.11+ is required (we use `StrEnum` and modern typing features).

## Running checks

```bash
pytest -q          # full test suite
ruff check .       # lint (auto-fix with --fix)
mypy               # type-check (strict on src/, lenient on tests/)
```

All three must pass before opening a PR. The CI workflow runs them on Python
3.11, 3.12, and 3.13.

---

## The three contribution paths, ranked by impact

### 1. Add taxonomy entries (no Python required)

The taxonomy in `src/injectguard/taxonomy.yaml` is the brain of the tool — it
maps tool-name patterns (matched against function name + docstring) to a
classification (`source` / `sink` / `both`), a privilege level (0–3), and a
reversibility flag.

The single highest-leverage way to improve InjectGuard is to add tool names
you've seen in real agent code that we don't currently classify. Pattern
matching is case-insensitive substring; longest match wins.

Example: if you've seen agents with a tool called `wire_funds`:

```yaml
sinks:
  - pattern: wire_funds
    privilege: 3
    reversible: false
    rationale: "Bank wire transfers are non-reversible and high-impact."
```

A PR that adds 5–10 well-justified taxonomy entries (with rationale strings)
is a great first contribution.

### 2. Write a new detection rule

A rule lives in `src/injectguard/rules/`. The minimal template:

```python
# src/injectguard/rules/my_rule.py
from collections.abc import Iterable
from typing import ClassVar

from injectguard.ir import Finding, Severity
from injectguard.rules.base import Rule, RuleContext


class MyRule(Rule):
    id: ClassVar[str] = "IG003"
    name: ClassVar[str] = "Short description"
    owasp_llm_ids: ClassVar[list[str]] = ["LLM01"]

    def check(self, ctx: RuleContext) -> Iterable[Finding]:
        for agent in ctx.agents:
            if <condition>:
                yield Finding(
                    rule_id=self.id,
                    rule_name=self.name,
                    severity=Severity.HIGH,
                    location=agent.location,
                    message="...",
                    owasp_llm_ids=list(self.owasp_llm_ids),
                    fix_hint="...",
                )
```

Steps:
1. Add the rule class.
2. Register it in `src/injectguard/rules/__init__.py` by yielding from
   `all_rules()`.
3. Add a vulnerable fixture in `tests/fixtures/vulnerable/` and a safe
   counterpart in `tests/fixtures/safe/`.
4. Add tests in `tests/test_rules.py` (or a dedicated file for the new rule).
5. Add a `docs/rules/IGNNN.md` page with the rule's intent, false-positive
   considerations, and fix guidance — the SARIF output's `helpUri` references it.

### 3. Add a new framework parser

A parser lives in `src/injectguard/parsers/` and subclasses `FrameworkParser`.
Implement two methods:

- `matches_file(source, tree) -> bool` — return True only if the file imports
  this framework. This prevents false matches on common identifiers.
- `extract(path, source, tree) -> tuple[list[Tool], list[Agent]]` — walk the
  AST and produce the framework-agnostic IR.

See `parsers/openai_agents.py` for a complete worked example. Register your
parser in `parsers/__init__.py` and add it to the default list in
`engine.py:Scanner.__init__`.

For prompt classification, use the shared `classify_prompt_expr(expr, module=ctx)`
helper in `parsers/base.py` — it handles f-strings, `.format()`, concatenation,
constant resolution, and known-safe SDK helpers consistently across parsers.

For approval-gate detection, set `Tool.requires_approval = True` on tools that
the parser determines are gated by a framework-specific mechanism. The
`ConfusedDeputyRule` honors this flag.

---

## Adding a notebook fixture

For test fixtures that exercise notebook scanning, generate `.ipynb` files
programmatically via `nbformat` rather than hand-editing JSON. See the
existing notebook fixtures and `tests/test_notebook.py` for examples.

---

## Style and review

- Follow the existing patterns rather than introducing new ones.
- `ruff` and `mypy` configs live in `pyproject.toml` — match them.
- Keep comments focused on *why*, not *what* — the code already shows what.
- Don't add backwards-compat shims; v0 is alpha and we're free to refactor.
- Don't introduce runtime dependencies beyond what the task requires.

---

## Reporting a security issue

If you find a vulnerability in `injectguard` itself (rather than using it to
find vulnerabilities elsewhere), please email the maintainer rather than
opening a public issue.

If you find a vulnerability in a third-party project using `injectguard`,
please disclose it responsibly to that project's maintainers — give them at
least 30 days to fix before public discussion. Do not file findings against
specific repos in this project's issue tracker.
