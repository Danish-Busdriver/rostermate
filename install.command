#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_RUNNER=()
if [ "$(uname -m)" = "arm64" ]; then
  PYTHON_RUNNER=(arch -arm64)
fi

PYTHON_VERSION="3.14.6"
PYTHON_CMD=""

for candidate in /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 python3 /usr/local/bin/python3.14 /opt/homebrew/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 15) else 1)' 2>/dev/null; then
    PYTHON_CMD="$(command -v "$candidate")"
    break
  fi
done

if [ -z "$PYTHON_CMD" ]; then
  echo "Henter Python $PYTHON_VERSION fra python.org..."
  INSTALL_TEMP="$(mktemp -d /tmp/rostermate-python.XXXXXX)"
  PYTHON_PKG="$INSTALL_TEMP/python.pkg"
  curl --fail --location --retry 3 \
    "https://www.python.org/ftp/python/$PYTHON_VERSION/python-$PYTHON_VERSION-macos11.pkg" \
    --output "$PYTHON_PKG"
  osascript - "$PYTHON_PKG" <<'APPLESCRIPT'
on run argv
  do shell script "/usr/sbin/installer -pkg " & quoted form of (item 1 of argv) & " -target /" with administrator privileges
end run
APPLESCRIPT
  rm -f "$PYTHON_PKG"
  rmdir "$INSTALL_TEMP" 2>/dev/null || true
  PYTHON_CMD="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
fi

if [ ! -f ".venv/pyvenv.cfg" ] || [ ! -x ".venv/bin/python3" ] || ! "${PYTHON_RUNNER[@]}" .venv/bin/python3 -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)' 2>/dev/null || ! "${PYTHON_RUNNER[@]}" .venv/bin/python3 -c 'from PIL import Image' 2>/dev/null || ! "${PYTHON_RUNNER[@]}" .venv/bin/python3 -c 'from playwright.sync_api import sync_playwright; playwright = sync_playwright().start(); playwright.stop()' 2>/dev/null; then
  if [ -e ".venv" ]; then
    echo "Fjerner et ufuldstændigt virtuelt miljø..."
    rm -rf "$SCRIPT_DIR/.venv"
  fi
  echo "Opretter virtuelt miljø..."
  "${PYTHON_RUNNER[@]}" "$PYTHON_CMD" -m venv .venv
fi

"${PYTHON_RUNNER[@]}" .venv/bin/python3 -m pip install --upgrade --no-cache-dir --only-binary=:all: pip
"${PYTHON_RUNNER[@]}" .venv/bin/python3 -m pip install --no-cache-dir --force-reinstall --only-binary=:all: -r requirements.txt
"${PYTHON_RUNNER[@]}" .venv/bin/python3 -m playwright install chromium

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Oprettede .env fra skabelon."
  echo "Rediger .env med dine egne loginoplysninger før du starter appen."
fi

echo "Installationen er færdig."
echo "Start appen med: ./run.command"
