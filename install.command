#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  echo "Opretter virtuelt miljø..."
  python3 -m venv .venv
fi

source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Oprettede .env fra skabelon."
  echo "Rediger .env med dine egne loginoplysninger før du starter appen."
fi

echo "Installationen er færdig."
echo "Start appen med: ./run.command"
