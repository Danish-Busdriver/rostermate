#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 blev ikke fundet. Installer Python 3.12 eller nyere fra python.org."
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "RosterMate kræver Python 3.12 eller nyere."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Opretter virtuelt miljø..."
  python3 -m venv .venv
fi

source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
python3 -m playwright install chromium

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Oprettede .env fra skabelon."
  echo "Rediger .env med dine egne loginoplysninger før du starter appen."
fi

echo "Installationen er færdig."
echo "Start appen med: ./run.command"
