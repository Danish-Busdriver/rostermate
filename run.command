#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  echo "Virtuelt miljø mangler. Kør install.command først."
  exit 1
fi

source .venv/bin/activate
python3 app.py
