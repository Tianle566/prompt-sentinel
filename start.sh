#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "${1:-}" == "--check" ]]; then
  if [[ ! -x .venv/bin/python ]]; then
    echo "Project environment is missing. Run ./start.sh --setup first." >&2
    exit 1
  fi
  exec .venv/bin/python scripts/doctor.py
fi
mkdir -p .runtime
if [[ ! -x .venv/bin/python ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.11 .venv
  else
    python3.11 -m venv .venv
  fi
fi
.venv/bin/python scripts/bootstrap.py
exec .venv/bin/python scripts/serve.py "$@"
