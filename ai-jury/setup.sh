#!/usr/bin/env bash
# One-shot local setup. Idempotent — safe to re-run.
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "error: Python 3.11+ required (found $("$PY" --version))" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "creating virtualenv at .venv"
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip --quiet
pip install -e ".[dev]" --quiet

if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env from template"
fi

echo
python -m pytest -q
echo
echo "Setup complete. Next:"
echo "  source .venv/bin/activate"
echo "  make run Q=\"Should we adopt microservices?\""
echo "  make eval"
echo "  make codegraph"
