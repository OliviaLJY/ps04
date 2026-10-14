#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
PYTHON="$ROOT/.venv/bin/python"; [ -x "$PYTHON" ] || PYTHON=python3
exec "$PYTHON" -m pipeline.extract "$@"
