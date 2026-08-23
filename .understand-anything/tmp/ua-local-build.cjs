const fs = require("fs");
const path = require("path");
const cp = require("child_process");

const root = process.cwd();
const outDir = path.join(root, ".understand-anything");
const intermediateDir = path.join(outDir, "intermediate");
const tmpDir = path.join(outDir, "tmp");
fs.mkdirSync(outDir, { recursive: true });
fs.mkdirSync(intermediateDir, { recursive: true });
fs.mkdirSync(tmpDir, { recursive: true });

const safeGit = ["-c", `safe.directory=${root.replace(/\\/g, "/")}`];
function git(args, fallback = "") {
  try {
    return cp.execFileSync("git", [...safeGit, ...args], {
      cwd: root,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      maxBuffer: 32 * 1024 * 1024,
    });
  } catch {
    return fallback;
  }
}

function readText(rel, max = 160000) {
  try {
    const full = path.join(root, rel);
    const buf = fs.readFileSync(full);
    return buf.toString("utf8", 0, Math.min(buf.length, max));
  } catch {
    return "";
  }
}

function lineCount(text) {
  if (!text) return 0;
  return text.split(/\r?\n/).length;
}

function ext(rel) {
  return path.extname(rel).toLowerCase();
}

function languageOf(rel) {
  const base = path.basename(rel);
  const e = ext(rel);
  if (base === "Dockerfile") return "dockerfile";
  if (base === "Makefile") return "makefile";
  const map = {
    ".py": "python",
    ".md": "markdown",
    ".txt": "text",
    ".json": "json",
    ".jsonl": "jsonl",
    ".toml": "toml",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".html": "html",
    ".css": "css",
    ".ps1": "powershell",
    ".sh": "shell",
    ".docx": "docx",
    ".env": "dotenv",
  };
  return map[e] || (e ? e.slice(1) : "unknown");
}

function categoryOf(rel) {
  const base = path.basename(rel);
  const e = ext(rel);
  if (/^\.github\/workflows\//.test(rel) || base === "Dockerfile" || base === "Makefile") return "infra";
  if ([".md", ".txt", ".docx"].includes(e)) return "docs";
  if ([".json", ".jsonl", ".toml", ".yml", ".yaml", ".env"].includes(e) || base === ".gitignore") return "config";
  if ([".csv", ".tsv", ".sql"].includes(e)) return "data";
  if ([".ps1", ".sh", ".bat", ".cmd"].includes(e)) return "script";
  if ([".html", ".css"].includes(e)) return "markup";
  return "code";
}

function nodeTypeForCategory(category, rel) {
  if (category === "config") return "config";
  if (category === "docs") return "document";
  if (category === "infra") {
    if (/\.github\/workflows\//.test(rel)) return "pipeline";
    return "service";
  }
  if (category === "data") return "schema";
  return "file";
}

function nodePrefix(type) {
  return `${type}:`;
}

function tagsFor(rel, type) {
  const parts = rel.split(/[\\/]/);
  const tags = new Set([type]);
  if (parts[0]) tags.add(parts[0].replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase());
  if (rel.startsWith("src/")) tags.add("runtime");
  if (rel.startsWith("tests/")) tags.add("test");
  if (rel.startsWith("docs/")) tags.add("documentation");
  if (rel.startsWith("configs/")) tags.add("configuration");
  if (rel.startsWith("eval_tasks/")) tags.add("eval");
  if (rel.startsWith("experiment_suites/")) tags.add("experiment");
  if (rel.startsWith("sandbox_experiments/")) tags.add("sandbox");
  return [...tags].filter(Boolean);
}

function summaryForFile(rel, type, sizeLines) {
  const base = path.basename(rel);
  if (rel === "README.md") return "Project overview describing the self-coding-agent research harness, its current Phase 9 loop, model interface, tools, verification, eval, and experiment workflows.";
  if (rel === "pyproject.toml") return "Python package manifest defining the self-coding-agent package metadata, source layout, console entry point, and pytest configuration.";
  if (rel === "src/cli.py") return "Command-line entry point for running single tasks, eval batches, and experiment workflows against a repository.";
  if (rel === "src/loop.py") return "Core multi-step agent loop coordinating ingest, analysis, planning, tool execution, observation, verification, and finalization.";
  if (rel === "src/model.py") return "Model adapter and response validation layer for OpenAI-compatible decision calls and structured tool plans.";
  if (rel === "src/runner.py") return "Run orchestration layer that prepares task state, invokes the loop, writes artifacts, and handles task-level outcomes.";
  if (rel === "src/tools.py") return "Tool execution implementations for repository search, file reads, patches, line replacement, shell commands, and git diffs.";
  if (rel === "src/verify.py") return "Task verification engine for command checks and structured rules over files, JSON, diffs, text, and regex expectations.";
  if (rel === "src/context.py") return "Context construction and compression logic for repository recall, fresh file state, observations, and per-round planning inputs.";
  if (rel === "src/memory.py") return "Long-term and working memory support for facts, conflict handling, recall, summaries, and trace-visible memory events.";
  if (rel.startsWith("tests/")) return `Pytest coverage for ${base.replace(/^test_/, "").replace(/\.py$/, "")} behavior in the harness.`;
  if (rel.startsWith("docs/")) return `Documentation artifact covering ${base.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ")} for the project.`;
  if (rel.startsWith("configs/")) return `Configuration variant used to tune runtime, context, memory, observation, or verification behavior.`;
  if (rel.startsWith("sandbox_experiments/")) return `Sandbox experiment fixture or task asset used to exercise the coding-agent harness on controlled repositories.`;
  return `${type} node for ${rel} (${sizeLines} lines).`;
}

function complexity(sizeLines) {
  if (sizeLines > 700) return "complex";
  if (sizeLines > 180) return "moderate";
  return "simple";
}

function pyModuleName(rel) {
  return rel.replace(/^src\//, "").replace(/\.py$/, "").replace(/\//g, ".");
}

function resolvePythonImport(fromRel, mod, level, fileSet) {
  if (!mod && level === 0) return null;
  const fromDir = path.dirname(fromRel).replace(/\\/g, "/");
  let prefixParts = [];
  if (level > 0) {
    const parts = fromDir.split("/");
    prefixParts = parts.slice(0, Math.max(0, parts.length - level + 1));
  }
  const modParts = mod ? mod.split(".") : [];
  const candidates = [];
  const joined = [...prefixParts, ...modParts].filter(Boolean).join("/");
  if (joined) {
    candidates.push(`src/${joined}.py`);
    candidates.push(`${joined}.py`);
    candidates.push(`src/${joined}/__init__.py`);
    candidates.push(`${joined}/__init__.py`);
  }
  if (modParts.length === 1) {
    candidates.push(`src/${modParts[0]}.py`);
  }
  return candidates.find((c) => fileSet.has(c)) || null;
}

function addEdge(edges, seen, source, target, type, weight = 0.5) {
  if (!source || !target || source === target) return;
  const key = `${source}|${target}|${type}`;
  if (seen.has(key)) return;
  seen.add(key);
  edges.push({ source, target, type, direction: "forward", weight });
}

function sanitizeName(name) {
  return String(name || "unknown").replace(/[^\w.$-]/g, "_");
}

const commit = git(["rev-parse", "HEAD"], "unknown").trim() || "unknown";
const tracked = git(["ls-files"], "")
  .split(/\r?\n/)
  .map((s) => s.trim())
  .filter(Boolean)
  .filter((rel) => !rel.startsWith(".understand-anything/"));
const fileSet = new Set(tracked);

const files = tracked.map((rel) => {
  const text = readText(rel);
  return {
    path: rel,
    language: languageOf(rel),
    sizeLines: lineCount(text),
    fileCategory: categoryOf(rel),
  };
});

const byCategory = {};
const byLanguage = {};
for (const f of files) {
  byCategory[f.fileCategory] = (byCategory[f.fileCategory] || 0) + 1;
  byLanguage[f.language] = (byLanguage[f.language] || 0) + 1;
}

const nodes = [];
const edges = [];
const edgeSeen = new Set();
const fileNodeByPath = new Map();
const symbolNodeByName = new Map();

for (const f of files) {
  const type = nodeTypeForCategory(f.fileCategory, f.path);
  const id = `${nodePrefix(type)}${f.path}`;
  fileNodeByPath.set(f.path, id);
  nodes.push({
    id,
    type,
    name: path.basename(f.path),
    filePath: f.path,
    summary: summaryForFile(f.path, type, f.sizeLines),
    tags: tagsFor(f.path, type),
    complexity: complexity(f.sizeLines),
  });
}

for (const f of files.filter((x) => x.language === "python")) {
  const text = readText(f.path);
  const fileId = fileNodeByPath.get(f.path);
  const classRe = /^class\s+([A-Za-z_]\w*)/gm;
  const funcRe = /^def\s+([A-Za-z_]\w*)|^async\s+def\s+([A-Za-z_]\w*)/gm;
  let m;
  while ((m = classRe.exec(text))) {
    const name = m[1];
    const id = `class:${f.path}:${sanitizeName(name)}`;
    symbolNodeByName.set(`${pyModuleName(f.path)}.${name}`, id);
    nodes.push({
      id,
      type: "class",
      name,
      filePath: f.path,
      summary: `Class ${name} defined in ${f.path}.`,
      tags: ["class", f.path.startsWith("tests/") ? "test" : "python"],
      complexity: complexity(f.sizeLines),
    });
    addEdge(edges, edgeSeen, fileId, id, "contains", 1.0);
  }
  while ((m = funcRe.exec(text))) {
    const name = m[1] || m[2];
    const id = `function:${f.path}:${sanitizeName(name)}`;
    symbolNodeByName.set(`${pyModuleName(f.path)}.${name}`, id);
    nodes.push({
      id,
      type: "function",
      name,
      filePath: f.path,
      summary: `Function ${name} implemented in ${f.path}.`,
      tags: ["function", f.path.startsWith("tests/") ? "test" : "python"],
      complexity: complexity(f.sizeLines),
    });
    addEdge(edges, edgeSeen, fileId, id, "contains", 1.0);
  }
}

const importMap = {};
for (const f of files) importMap[f.path] = [];
for (const f of files.filter((x) => x.language === "python")) {
  const text = readText(f.path);
  const fileId = fileNodeByPath.get(f.path);
  const importLines = text.matchAll(/^(?:from\s+([.]*)((?:[A-Za-z_]\w*)(?:\.[A-Za-z_]\w*)*)?\s+import\s+([^\n#]+)|import\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*))/gm);
  for (const match of importLines) {
    let target = null;
    if (match[4]) {
      const top = match[4].split(".")[0];
      target = resolvePythonImport(f.path, top, 0, fileSet);
    } else {
      const dots = match[1] || "";
      const mod = match[2] || "";
      target = resolvePythonImport(f.path, mod, dots.length, fileSet);
    }
    if (target) {
      importMap[f.path].push(target);
      addEdge(edges, edgeSeen, fileId, fileNodeByPath.get(target), "imports", 0.7);
    }
  }
}
for (const key of Object.keys(importMap)) importMap[key] = [...new Set(importMap[key])].sort();

for (const f of files.filter((x) => x.path.startsWith("tests/test_") && x.path.endsWith(".py"))) {
  const subject = `src/${f.path.replace(/^tests\/test_/, "").replace(/\.py$/, ".py")}`;
  if (fileSet.has(subject)) addEdge(edges, edgeSeen, fileNodeByPath.get(subject), fileNodeByPath.get(f.path), "tested_by", 0.5);
}

for (const cfg of files.filter((x) => x.path.startsWith("configs/") && x.path.endsWith(".json"))) {
  addEdge(edges, edgeSeen, fileNodeByPath.get(cfg.path), fileNodeByPath.get("src/config.py"), "configures", 0.6);
  addEdge(edges, edgeSeen, fileNodeByPath.get(cfg.path), fileNodeByPath.get("src/runner.py"), "configures", 0.6);
}

for (const doc of files.filter((x) => x.fileCategory === "docs")) {
  const docId = fileNodeByPath.get(doc.path);
  if (doc.path === "README.md" || doc.path.includes("ARCHITECTURE") || doc.path.includes("USAGE") || doc.path.includes("MVP")) {
    for (const target of ["src/cli.py", "src/runner.py", "src/loop.py", "src/tools.py", "src/verify.py"].filter((p) => fileSet.has(p))) {
      addEdge(edges, edgeSeen, docId, fileNodeByPath.get(target), "documents", 0.5);
    }
  }
}

const layers = [
  {
    id: "layer:entry-orchestration",
    name: "Entry and Orchestration",
    description: "CLI, runner, loop, tracing, and outcome files that execute a task run from request to final report.",
    prefixes: ["src/cli.py", "src/runner.py", "src/loop.py", "src/runtime_trace.py", "src/outcome_summary.py", "src/live_trace_view.py"],
  },
  {
    id: "layer:model-context-memory",
    name: "Model, Context, and Memory",
    description: "Decision adapter, prompt/context construction, memory recall, file structure summaries, and environment loading.",
    prefixes: ["src/model.py", "src/context.py", "src/memory.py", "src/file_structure.py", "src/env_loader.py"],
  },
  {
    id: "layer:tools-verification-hitl",
    name: "Tools, Verification, and HITL",
    description: "Repository tools, command execution, patching, verification rules, and human-in-the-loop approval paths.",
    prefixes: ["src/tools.py", "src/verify.py", "src/hitl.py"],
  },
  {
    id: "layer:evaluation-experiments",
    name: "Evaluation and Experiments",
    description: "Eval batch runners, strategy comparisons, experiment suite assets, and sandbox task repositories.",
    prefixes: ["src/eval_runner.py", "src/experiment_runner.py", "eval_tasks/", "experiment_suites/", "sandbox_experiments/"],
  },
  {
    id: "layer:configuration-docs",
    name: "Configuration and Documentation",
    description: "Project manifests, runtime config variants, planning notes, guides, and development history.",
    prefixes: ["configs/", "docs/", "dev_process_history/", "README.md", "AGENTS.md", "agent_notes.md", "pyproject.toml", "requirements.txt", "skills/", "ai-chat/", ".agent_memory/"],
  },
  {
    id: "layer:tests",
    name: "Tests",
    description: "Pytest suites validating CLI, loop, model, tools, verification, eval, context, memory, and HITL behavior.",
    prefixes: ["tests/"],
  },
];

for (const layer of layers) {
  layer.nodeIds = nodes
    .filter((n) => ["file", "config", "document", "service", "pipeline", "table", "schema", "resource", "endpoint"].includes(n.type))
    .filter((n) => layer.prefixes.some((p) => n.filePath === p || n.filePath.startsWith(p)))
    .map((n) => n.id);
  delete layer.prefixes;
}
const assigned = new Set(layers.flatMap((l) => l.nodeIds));
const fallbackLayer = layers.find((l) => l.id === "layer:configuration-docs");
for (const n of nodes.filter((n) => ["file", "config", "document", "service", "pipeline", "table", "schema", "resource", "endpoint"].includes(n.type))) {
  if (!assigned.has(n.id)) fallbackLayer.nodeIds.push(n.id);
}

const tour = [
  { order: 1, title: "Project Overview", description: "Start with the README to understand the research harness, Phase 9 status, supported tools, verification model, eval flow, and operating assumptions.", nodeIds: ["document:README.md"] },
  { order: 2, title: "Command Entry", description: "Follow how command-line arguments select a single run, eval batch, or experiment suite and hand control to the orchestration layer.", nodeIds: ["file:src/cli.py", "file:src/runner.py"] },
  { order: 3, title: "Agent Loop", description: "Inspect the multi-round loop that sequences ingest, analyze, plan, act, observe, verify, and finalize states.", nodeIds: ["file:src/loop.py", "file:src/runtime_trace.py"] },
  { order: 4, title: "Model Decisions", description: "Review the OpenAI-compatible model adapter, structured response validation, and raw decision trace surface.", nodeIds: ["file:src/model.py", "file:src/config.py"] },
  { order: 5, title: "Context and Memory", description: "Learn how repository facts, fresh file ranges, recent observations, and long-term memory are shaped for planning.", nodeIds: ["file:src/context.py", "file:src/memory.py", "file:src/file_structure.py"] },
  { order: 6, title: "Tool Execution", description: "See the local tool layer for text search, file reads, patch application, line replacement, commands, and git diffs.", nodeIds: ["file:src/tools.py", "file:src/hitl.py"] },
  { order: 7, title: "Verification", description: "Inspect task-level verification commands and structured rule checks that decide whether a run actually succeeded.", nodeIds: ["file:src/verify.py", "document:docs/MVP_ACCEPTANCE.md"] },
  { order: 8, title: "Eval and Experiments", description: "Trace how task batches, strategy comparisons, experiment suites, and summary artifacts support repeatable harness research.", nodeIds: ["file:src/eval_runner.py", "file:src/experiment_runner.py", "config:eval_tasks/sample_batch.json", "config:experiment_suites/first_batch.json"] },
  { order: 9, title: "Tests and Documentation", description: "Use the tests and architecture docs as the high-signal map of expected behavior and current project contracts.", nodeIds: ["document:docs/ARCHITECTURE.md", "file:tests/test_loop.py", "file:tests/test_model.py", "file:tests/test_verify.py"] },
].map((step) => ({ ...step, nodeIds: step.nodeIds.filter((id) => nodes.some((n) => n.id === id)) }));

const graph = {
  version: "1.0.0",
  project: {
    name: "self-coding-agent",
    languages: Object.keys(byLanguage).sort(),
    frameworks: ["pytest"],
    description: "A local research harness for studying coding-agent loops, model decisions, tool execution, observation, verification, eval batches, and strategy comparisons.",
    analyzedAt: new Date().toISOString(),
    gitCommitHash: commit,
  },
  nodes,
  edges,
  layers,
  tour,
};

const scanResult = {
  name: graph.project.name,
  description: graph.project.description + (files.length > 100 ? " Note: this project has over 100 tracked files; scoped analysis can be faster for focused work." : ""),
  languages: graph.project.languages,
  frameworks: graph.project.frameworks,
  files,
  totalFiles: files.length,
  filteredByIgnore: 0,
  estimatedComplexity: files.length > 250 ? "complex" : files.length > 80 ? "moderate" : "simple",
  importMap,
  stats: { byCategory, byLanguage },
};

fs.writeFileSync(path.join(intermediateDir, "scan-result.json"), JSON.stringify(scanResult, null, 2));
fs.writeFileSync(path.join(intermediateDir, "assembled-graph.json"), JSON.stringify(graph, null, 2));
fs.writeFileSync(path.join(outDir, "knowledge-graph.json"), JSON.stringify(graph, null, 2));
fs.writeFileSync(path.join(outDir, "meta.json"), JSON.stringify({
  lastAnalyzedAt: graph.project.analyzedAt,
  gitCommitHash: commit,
  version: "1.0.0",
  analyzedFiles: files.length,
  generator: "codex-local-fallback",
  note: "Bundled understand-anything plugin scripts could not run because sandbox approval for reading the plugin directory failed.",
}, null, 2));

const nodeTypes = {};
const edgeTypes = {};
for (const n of nodes) nodeTypes[n.type] = (nodeTypes[n.type] || 0) + 1;
for (const e of edges) edgeTypes[e.type] = (edgeTypes[e.type] || 0) + 1;
fs.writeFileSync(path.join(intermediateDir, "review.json"), JSON.stringify({
  issues: [],
  warnings: [
    "Used codex-local-fallback generator because bundled understand-anything scripts could not run under current sandbox permissions.",
    "Structural fingerprints baseline was not generated by the plugin build-fingerprints script.",
  ],
  stats: {
    totalNodes: nodes.length,
    totalEdges: edges.length,
    totalLayers: layers.length,
    tourSteps: tour.length,
    nodeTypes,
    edgeTypes,
  },
}, null, 2));

console.log(JSON.stringify({
  files: files.length,
  nodes: nodes.length,
  edges: edges.length,
  layers: layers.length,
  tourSteps: tour.length,
  byCategory,
  nodeTypes,
  edgeTypes,
}, null, 2));
