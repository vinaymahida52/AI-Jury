import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_codegraph_builds_and_maps_phases(tmp_path):
    out = tmp_path / "graph.json"
    md = tmp_path / "graph.md"
    result = subprocess.run(
        [sys.executable, "tools/codegraph/build.py", "--root", ".",
         "--out", str(out), "--markdown", str(md)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    graph = json.loads(out.read_text())

    assert graph["summary"]["modules"] > 20
    assert graph["edges"], "internal dependency edges should be discovered"
    assert "unclassified" not in graph["phases"], "every module must map to a plan phase"

    modules = {m["module"] for m in graph["modules"]}
    assert "aijury.protocol.deliberation" in modules
    assert md.read_text().startswith("# Codegraph")


def test_codegraph_captures_signatures_and_docs(tmp_path):
    out = tmp_path / "graph.json"
    subprocess.run(
        [sys.executable, "tools/codegraph/build.py", "--root", ".", "--out", str(out),
         "--markdown", str(tmp_path / "g.md")],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    graph = json.loads(out.read_text())
    deliberation = next(
        m for m in graph["modules"] if m["module"] == "aijury.protocol.deliberation"
    )
    run = next(s for s in deliberation["symbols"] if s["name"] == "Deliberation.run")
    assert "async def run" in run["signature"]
    assert deliberation["doc"]
