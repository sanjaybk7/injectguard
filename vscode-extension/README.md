# injectguard for VS Code

Inline static analysis for prompt-injection and confused-deputy risks in LLM agent code.

## How it works

This extension is a thin wrapper over the `injectguard` Python CLI. On every save
(or via the `injectguard: Scan workspace` command), it:

1. Runs `injectguard scan <path> --format sarif`
2. Parses the SARIF output
3. Surfaces findings as VS Code diagnostics — red squigglies in the editor with
   hover messages mapped to OWASP LLM Top 10 IDs.

## Prerequisites

You need the Python CLI installed:

```bash
pip install injectguard
```

By default the extension looks for `injectguard` on `PATH`. If you installed it
into a virtualenv, set `injectguard.cliPath` in your settings.

## Build & run locally

```bash
cd vscode-extension
npm install
npm run compile
# Press F5 in VS Code to launch an Extension Development Host.
```

## Configuration

| Setting | Default | Description |
|---|---|---|
| `injectguard.cliPath` | `injectguard` | Path to the CLI. |
| `injectguard.runOn` | `save` | When to run: `save` or `manual`. |
