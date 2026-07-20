#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  echo "Virtuelt miljø mangler. Kør install.command først."
  exit 1
fi

source .venv/bin/activate
python3 auto_update.py
python3 app.py &
server_pid=$!

python3 tray.py --server-pid "$server_pid"
wait "$server_pid" 2>/dev/null || true
