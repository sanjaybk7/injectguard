/**
 * injectguard VS Code extension.
 *
 * Runs the injectguard CLI on save (or on demand), parses the SARIF output,
 * and surfaces findings as VS Code diagnostics — red squigglies in the gutter,
 * with hover messages mapped to OWASP LLM Top 10.
 */

import { spawn } from "child_process";
import * as path from "path";
import * as vscode from "vscode";

const DIAGNOSTIC_SOURCE = "injectguard";

let diagnostics: vscode.DiagnosticCollection;
let output: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext): void {
  diagnostics = vscode.languages.createDiagnosticCollection(DIAGNOSTIC_SOURCE);
  output = vscode.window.createOutputChannel("injectguard");
  context.subscriptions.push(diagnostics, output);

  context.subscriptions.push(
    vscode.commands.registerCommand("injectguard.scanWorkspace", () => scanWorkspace()),
    vscode.commands.registerCommand("injectguard.scanFile", () => {
      const editor = vscode.window.activeTextEditor;
      if (editor) {
        scanPath(editor.document.uri.fsPath);
      }
    }),
    vscode.workspace.onDidSaveTextDocument((doc) => {
      const cfg = vscode.workspace.getConfiguration("injectguard");
      if (cfg.get<string>("runOn", "save") !== "save") return;
      if (doc.languageId !== "python") return;
      scanPath(doc.uri.fsPath);
    }),
  );

  // Initial scan on activation.
  scanWorkspace();
}

export function deactivate(): void {
  diagnostics?.dispose();
}

function scanWorkspace(): void {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) return;
  for (const folder of folders) {
    scanPath(folder.uri.fsPath);
  }
}

function scanPath(target: string): void {
  const cfg = vscode.workspace.getConfiguration("injectguard");
  const cli = cfg.get<string>("cliPath", "injectguard");

  output.appendLine(`[scan] ${cli} scan ${target} --format sarif`);

  const proc = spawn(cli, ["scan", target, "--format", "sarif", "--fail-on", "none"], {
    cwd: path.dirname(target),
  });

  let stdout = "";
  let stderr = "";
  proc.stdout.on("data", (chunk) => (stdout += chunk.toString()));
  proc.stderr.on("data", (chunk) => (stderr += chunk.toString()));

  proc.on("error", (err) => {
    output.appendLine(`[error] failed to start injectguard: ${err.message}`);
    vscode.window.showWarningMessage(
      `injectguard CLI not found ('${cli}'). Set 'injectguard.cliPath' or install it: pip install injectguard`,
    );
  });

  proc.on("close", () => {
    if (stderr.trim()) output.appendLine(`[stderr] ${stderr}`);
    if (!stdout.trim()) return;
    try {
      applySarif(stdout, target);
    } catch (e) {
      output.appendLine(`[error] failed to parse SARIF: ${(e as Error).message}`);
    }
  });
}

function applySarif(sarifText: string, scanRoot: string): void {
  const doc = JSON.parse(sarifText) as SarifDocument;
  const byFile: Map<string, vscode.Diagnostic[]> = new Map();

  for (const run of doc.runs ?? []) {
    for (const result of run.results ?? []) {
      const loc = result.locations?.[0]?.physicalLocation;
      if (!loc) continue;
      const file = resolveFile(loc.artifactLocation.uri, scanRoot);
      const line = Math.max((loc.region.startLine ?? 1) - 1, 0);
      const col = Math.max((loc.region.startColumn ?? 1) - 1, 0);
      const endLine = Math.max((loc.region.endLine ?? loc.region.startLine ?? 1) - 1, line);
      const range = new vscode.Range(line, col, endLine, col + 80);

      const owasp = (result.properties?.["owasp-llm"] ?? []).join(", ");
      const fix = result.properties?.["fix-hint"];
      const message = `[${result.ruleId}] ${result.message.text}`
        + (owasp ? `  (OWASP ${owasp})` : "")
        + (fix ? `\nFix: ${fix}` : "");

      const diag = new vscode.Diagnostic(range, message, levelToSeverity(result.level));
      diag.source = DIAGNOSTIC_SOURCE;
      diag.code = result.ruleId;

      const list = byFile.get(file) ?? [];
      list.push(diag);
      byFile.set(file, list);
    }
  }

  diagnostics.clear();
  for (const [file, diags] of byFile) {
    diagnostics.set(vscode.Uri.file(file), diags);
  }
}

function resolveFile(uri: string, scanRoot: string): string {
  if (path.isAbsolute(uri)) return uri;
  return path.resolve(scanRoot, uri);
}

function levelToSeverity(level: string | undefined): vscode.DiagnosticSeverity {
  switch (level) {
    case "error":
      return vscode.DiagnosticSeverity.Error;
    case "warning":
      return vscode.DiagnosticSeverity.Warning;
    case "note":
      return vscode.DiagnosticSeverity.Information;
    default:
      return vscode.DiagnosticSeverity.Hint;
  }
}

interface SarifDocument {
  runs?: SarifRun[];
}

interface SarifRun {
  results?: SarifResult[];
}

interface SarifResult {
  ruleId: string;
  level?: string;
  message: { text: string };
  locations?: { physicalLocation: SarifPhysicalLocation }[];
  properties?: Record<string, unknown> & { "owasp-llm"?: string[]; "fix-hint"?: string };
}

interface SarifPhysicalLocation {
  artifactLocation: { uri: string };
  region: { startLine?: number; startColumn?: number; endLine?: number; endColumn?: number };
}
