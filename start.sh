#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p .runtime
if [[ ! -x .venv/bin/python ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.11 .venv
    uv pip install --python .venv/bin/python -r backend/requirements.txt
  else
    python3.11 -m venv .venv
    .venv/bin/python -m pip install -r backend/requirements.txt
  fi
fi
if ! .venv/bin/python -c 'import fastapi,torch,transformers,psutil' >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python .venv/bin/python -r backend/requirements.txt
  else
    .venv/bin/python -m pip install -r backend/requirements.txt
  fi
fi
exec .venv/bin/python scripts/serve.py "$@"
