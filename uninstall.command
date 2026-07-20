#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$HOME/Documents/RosterMate Backup $STAMP"
TRASH_DIR="$HOME/.Trash"

answer="$(osascript -e 'button returned of (display dialog "RosterMate bliver stoppet og installationen flyttet til Papirkurv. Dine profiler og kalenderdata sikkerhedskopieres først i Dokumenter." with title "Afinstaller RosterMate" buttons {"Annuller", "Afinstaller"} default button "Afinstaller" cancel button "Annuller" with icon caution)' 2>/dev/null || true)"
if [ "$answer" != "Afinstaller" ]; then
  echo "Afinstallationen blev annulleret."
  exit 0
fi

mkdir -p "$BACKUP_DIR" "$TRASH_DIR"
for item in data output backups .env; do
  if [ -e "$SCRIPT_DIR/$item" ]; then
    ditto "$SCRIPT_DIR/$item" "$BACKUP_DIR/$item"
  fi
done

PORT="8080"
if [ -x "$SCRIPT_DIR/.venv/bin/python3" ] && [ -f "$SCRIPT_DIR/port_config.py" ]; then
  PORT="$(cd "$SCRIPT_DIR" && .venv/bin/python3 port_config.py configured 2>/dev/null || printf '8080')"
fi
health="$(curl -fsS "http://127.0.0.1:$PORT/health" 2>/dev/null || true)"
if printf '%s' "$health" | grep -q '"status":"ok"'; then
  pids="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null || true
  fi
fi

for plist in "$HOME"/Library/LaunchAgents/dk.rostermate.*.plist; do
  [ -e "$plist" ] || continue
  launchctl unload "$plist" >/dev/null 2>&1 || true
  mv "$plist" "$TRASH_DIR/$(basename "$plist").$STAMP"
done

destination="$TRASH_DIR/RosterMate-$STAMP"
cd /
mv "$SCRIPT_DIR" "$destination"

osascript -e "display dialog \"RosterMate er flyttet til Papirkurv. En sikkerhedskopi af dine data ligger i: $BACKUP_DIR\" with title \"RosterMate er afinstalleret\" buttons {\"OK\"} default button \"OK\"" >/dev/null 2>&1 || true
echo "RosterMate er afinstalleret."
echo "Data-backup: $BACKUP_DIR"
