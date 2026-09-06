#!/usr/bin/env python3
"""Codegraph builder.

Produces a machine-readable map of the repository so another AI agent can be
handed whole-project context without reading every file. Emits:

  docs/codegraph.json  - full graph: modules, symbols, signatures, edges
  docs/CODEGRAPH.md    - a compact orientation document for an agent's context

Pure AST analysis: no imports of the target code, so it cannot execute anything
and works on a repo that does not currently run.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: Maps package paths to the build-plan phase they implement, so an agent
#: reading the graph knows why each module exists, not just what it contains.
PHASE_MAP: list[tuple[str, str]] = [
    ("aijury/contracts", "Phase 0 — contracts & schemas"),
    ("aijury/evaluation", "Phase 0 — evaluation harness & scorer"),
    ("aijury/baseline", "Phase 1 — single-agent baseline (control arm)"),
    ("aijury/core", "Phase 2 — orchestration core"),
    ("aijury/llm", "Phase 2 — provider abstraction"),
    ("aijury/agents", "Phase 3 — agent roles & dynamic spawning"),
    ("aijury/protocol", "Phase 4 — deliberation protocol"),
    ("aijury/verification", "Phase 5 — verification layer"),
    ("aijury/learning", "Phase 6 — learning loop"),
    ("aijury/security", "Phase 8 — hardening"),
    ("aijury/api", "Phase 7 — HTTP API & web console"),
    ("aijury/config", "Cross-cutting — configuration"),
    ("aijury/pipeline", "Entry point"),
    ("aijury/cli", "Entry point"),
    ("tools/codegraph", "Tooling — project context for AI agents"),
    ("tests", "Tests"),
]

SKIP_DIRS = {"__pycache__", ".git", ".venv", "node_modules", "dist", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", ".traces", ".failures"}


@dataclass
class SymbolInfo:
    name: str
    kind: str  # "function" | "async_function" | "class" | "method" | "constant"
    signature: str
    doc: str
    lineno: int
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    is_public: bool = True


@dataclass
class ModuleInfo:
    path: str
    module: str
    phase: str
    doc: str
    loc: int
    imports: list[str] = field(default_factory=list)
    internal_deps: list[str] = field(default_factory=list)
    symbols: list[SymbolInfo] = field(default_factory=list)


def _sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({args}){returns}"


def _doc(node: ast.AST) -> str:
    text = ast.get_docstring(node) or ""
    return text.strip().split("\n")[0][:220]


def _calls(node: ast.AST) -> list[str]:
    """Best-effort outgoing call names. Enough for a call graph, not a compiler."""
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                found.add(func.id)
            elif isinstance(func, ast.Attribute):
                found.add(func.attr)
    return sorted(found)


def phase_for(relpath: str) -> str:
    normalized = relpath.replace(os.sep, "/")
    if normalized.endswith("__init__.py"):
        # Package re-export shims inherit their package's phase.
        normalized = normalized.removesuffix("/__init__.py")
    for prefix, phase in PHASE_MAP:
        if f"/{prefix}" in f"/{normalized}" or normalized.startswith(prefix):
            return phase
    if normalized.rstrip("/").endswith("aijury"):
        return "Cross-cutting — package root"
    return "unclassified"


def analyze_file(path: Path, root: Path) -> ModuleInfo | None:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None

    rel = str(path.relative_to(root))
    module = rel.removesuffix(".py").replace(os.sep, ".").removeprefix("src.")
    info = ModuleInfo(
        path=rel,
        module=module,
        phase=phase_for(rel),
        doc=_doc(tree),
        loc=len(source.splitlines()),
    )

    for node in tree.body:
        if isinstance(node, ast.Import):
            info.imports += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            info.imports.append(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info.symbols.append(
                SymbolInfo(
                    name=node.name,
                    kind="async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                    signature=_sig(node),
                    doc=_doc(node),
                    lineno=node.lineno,
                    decorators=[ast.unparse(d) for d in node.decorator_list],
                    calls=_calls(node),
                    is_public=not node.name.startswith("_"),
                )
            )
        elif isinstance(node, ast.ClassDef):
            info.symbols.append(
                SymbolInfo(
                    name=node.name,
                    kind="class",
                    signature=f"class {node.name}({', '.join(ast.unparse(b) for b in node.bases)})",
                    doc=_doc(node),
                    lineno=node.lineno,
                    decorators=[ast.unparse(d) for d in node.decorator_list],
                    bases=[ast.unparse(b) for b in node.bases],
                    is_public=not node.name.startswith("_"),
                )
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    info.symbols.append(
                        SymbolInfo(
                            name=f"{node.name}.{child.name}",
                            kind="method",
                            signature=_sig(child),
                            doc=_doc(child),
                            lineno=child.lineno,
                            decorators=[ast.unparse(d) for d in child.decorator_list],
                            calls=_calls(child),
                            is_public=not child.name.startswith("_"),
                        )
                    )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.isupper():
                info.symbols.append(
                    SymbolInfo(
                        name=node.target.id,
                        kind="constant",
                        signature=f"{node.target.id}: {ast.unparse(node.annotation)}",
                        doc="",
                        lineno=node.lineno,
                    )
                )

    info.imports = sorted(set(info.imports))
    info.internal_deps = sorted({i for i in info.imports if i.startswith("aijury")})
    return info


def build_graph(root: Path) -> dict[str, Any]:
    modules: list[ModuleInfo] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                analyzed = analyze_file(Path(dirpath) / filename, root)
                if analyzed:
                    modules.append(analyzed)

    modules.sort(key=lambda m: m.path)
    names = {m.module for m in modules}
    edges = [
        {"from": m.module, "to": dep}
        for m in modules
        for dep in m.internal_deps
        if dep in names
    ]

    # Modules nothing imports: entry points, or dead code. Worth an agent knowing which.
    imported = {e["to"] for e in edges}
    roots = [m.module for m in modules if m.module not in imported]

    return {
        "schema_version": 1,
        "project": "aijury",
        "summary": {
            "modules": len(modules),
            "symbols": sum(len(m.symbols) for m in modules),
            "lines_of_code": sum(m.loc for m in modules),
            "entry_points": sorted(roots),
        },
        "phases": sorted({m.phase for m in modules}),
        "modules": [asdict(m) for m in modules],
        "edges": edges,
    }


def render_markdown(graph: dict[str, Any]) -> str:
    lines = [
        "# Codegraph — aijury",
        "",
        "Generated by `tools/codegraph/build.py`. Regenerate with `make codegraph`.",
        "Hand this file to an AI agent as whole-project context; `docs/codegraph.json`",
        "carries the same information in machine-readable form.",
        "",
        f"**{graph['summary']['modules']} modules · "
        f"{graph['summary']['symbols']} symbols · "
        f"{graph['summary']['lines_of_code']} lines**",
        "",
    ]

    by_phase: dict[str, list[dict[str, Any]]] = {}
    for module in graph["modules"]:
        by_phase.setdefault(module["phase"], []).append(module)

    for phase in sorted(by_phase):
        lines += [f"## {phase}", ""]
        for module in by_phase[phase]:
            lines.append(f"### `{module['module']}`")
            lines.append(f"`{module['path']}` · {module['loc']} lines")
            if module["doc"]:
                lines.append(f"> {module['doc']}")
            if module["internal_deps"]:
                lines.append(f"depends on: {', '.join(f'`{d}`' for d in module['internal_deps'])}")
            public = [s for s in module["symbols"] if s["is_public"] and s["kind"] != "constant"]
            if public:
                lines.append("")
                for symbol in public:
                    doc = f" — {symbol['doc']}" if symbol["doc"] else ""
                    lines.append(f"- `{symbol['signature']}`{doc}")
            lines.append("")

    lines += ["## Dependency edges", "", "```"]
    lines += [f"{e['from']} -> {e['to']}" for e in graph["edges"]]
    lines += ["```", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the project codegraph.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="docs/codegraph.json")
    parser.add_argument("--markdown", default="docs/CODEGRAPH.md")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    graph = build_graph(root)

    out = root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    (root / args.markdown).write_text(render_markdown(graph), encoding="utf-8")

    print(
        f"codegraph: {graph['summary']['modules']} modules, "
        f"{graph['summary']['symbols']} symbols -> {args.out}, {args.markdown}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
