#!/bin/bash
# RosterMate til macOS: installation fra Terminal uden Gatekeeper-advarslen.
# Filer hentet med curl får ikke macOS' "hentet fra internettet"-mærke, så den
# officielle .pkg fra seneste GitHub-udgivelse kan installeres direkte.
#
# Brug:
#   curl -fsSL https://raw.githubusercontent.com/Danish-Busdriver/rostermate/main/install-mac.sh | bash
set -euo pipefail

REPO="Danish-Busdriver/rostermate"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Finder den seneste RosterMate-version …"
curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" -o "$work/release.json"

url=""
digest=""
i=0
while name="$(plutil -extract "assets.$i.name" raw "$work/release.json" 2>/dev/null)"; do
  if [[ "$name" == *-macOS.pkg ]]; then
    url="$(plutil -extract "assets.$i.browser_download_url" raw "$work/release.json")"
    digest="$(plutil -extract "assets.$i.digest" raw "$work/release.json" 2>/dev/null || true)"
    break
  fi
  i=$((i + 1))
done

# Installér kun pakker fra RosterMates egne GitHub-udgivelser.
if [[ "$url" != "https://github.com/$REPO/releases/download/"* ]]; then
  echo "Der blev ikke fundet en macOS-pakke i den seneste udgivelse." >&2
  exit 1
fi

version="$(plutil -extract tag_name raw "$work/release.json")"
echo "Henter RosterMate $version …"
curl -fL --progress-bar "$url" -o "$work/RosterMate.pkg"

if [[ "$digest" == sha256:* ]]; then
  actual="sha256:$(shasum -a 256 "$work/RosterMate.pkg" | awk '{print $1}')"
  if [ "$actual" != "$digest" ]; then
    echo "Filen blev ikke hentet korrekt. Prøv igen." >&2
    exit 1
  fi
fi

echo
echo "Installerer. Skriv din Mac-adgangskode, når du bliver spurgt."
echo "Adgangskoden vises ikke, mens du skriver. Tryk Enter bagefter."
sudo installer -pkg "$work/RosterMate.pkg" -target /

echo
echo "Færdig. RosterMate åbner i din browser om et øjeblik."
