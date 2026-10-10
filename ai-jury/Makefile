.PHONY: setup serve install test lint typecheck codegraph eval run clean

# One-shot: venv + deps + .env + test run.
setup:
	./setup.sh

install:
	pip install -e ".[dev]"

test:
	PYTHONPATH=src python -m pytest -q

lint:
	ruff check src tools tests

typecheck:
	mypy src

codegraph:
	PYTHONPATH=src python tools/codegraph/build.py --root . --out docs/codegraph.json --markdown docs/CODEGRAPH.md

eval:
	PYTHONPATH=src python -m aijury.cli eval --dataset src/aijury/evaluation/datasets/golden.jsonl

run:
	PYTHONPATH=src python -m aijury.cli ask "$(Q)"

# Web console at http://localhost:8000
serve:
	PYTHONPATH=src python -m aijury.cli serve

clean:
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
