#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="${1:-1.7.1}"
BUILD_PARENT="$SCRIPT_DIR/dist/.pkg-build"
mkdir -p "$BUILD_PARENT"
BUILD_DIR="$(mktemp -d "$BUILD_PARENT/rostermate-pkg.XXXXXX")"
PAYLOAD_DIR="$BUILD_DIR/payload"
COMPONENT_PKG="$BUILD_DIR/RosterMate-component.pkg"
OUTPUT_DIR="$SCRIPT_DIR/dist/macos"
OUTPUT_PKG="$OUTPUT_DIR/RosterMate-$VERSION-macOS.pkg"

cleanup() {
  rm -rf "$BUILD_DIR"
}
trap cleanup EXIT

mkdir -p "$PAYLOAD_DIR" "$OUTPUT_DIR"

(cd "$SCRIPT_DIR" && COPYFILE_DISABLE=1 git ls-files --cached --others --exclude-standard -z | COPYFILE_DISABLE=1 cpio -0 -pdm "$PAYLOAD_DIR")
rm -rf "$PAYLOAD_DIR/.venv" "$PAYLOAD_DIR/data" "$PAYLOAD_DIR/output" \
  "$PAYLOAD_DIR/backups" "$PAYLOAD_DIR/.pytest_cache" "$PAYLOAD_DIR/dist" \
  "$PAYLOAD_DIR/.github" "$PAYLOAD_DIR/tests" "$PAYLOAD_DIR/installer"
rm -f "$PAYLOAD_DIR/.env" "$PAYLOAD_DIR/.DS_Store"
rm -f "$PAYLOAD_DIR/AGENTS.md" "$PAYLOAD_DIR/windows_launcher.py" \
  "$PAYLOAD_DIR/install-windows.cmd" "$PAYLOAD_DIR/install-windows.ps1" \
  "$PAYLOAD_DIR/run-windows.cmd" "$PAYLOAD_DIR/run-windows.ps1" \
  "$PAYLOAD_DIR/uninstall-windows.cmd" "$PAYLOAD_DIR/uninstall-windows.ps1" \
  "$PAYLOAD_DIR/assets/RosterMate.ico" "$PAYLOAD_DIR/docs/INSTALL_WINDOWS.md" \
  "$PAYLOAD_DIR/build-macos-pkg.command"
/usr/bin/find "$PAYLOAD_DIR" -name '._*' -delete
/usr/bin/xattr -cr "$PAYLOAD_DIR"

chmod +x "$PAYLOAD_DIR/install.command" "$PAYLOAD_DIR/run.command" \
  "$PAYLOAD_DIR/uninstall.command" "$PAYLOAD_DIR/RosterMate.app/Contents/MacOS/RosterMate"
chmod +x "$SCRIPT_DIR/installer/macos/scripts/postinstall"

/usr/bin/pkgbuild \
  --root "$PAYLOAD_DIR" \
  --install-location "/Applications/RosterMate" \
  --scripts "$SCRIPT_DIR/installer/macos/scripts" \
  --identifier "dk.pullen.rostermate.pkg" \
  --version "$VERSION" \
  "$COMPONENT_PKG"

cp "$SCRIPT_DIR/installer/macos/distribution.xml" "$BUILD_DIR/distribution.xml"
sed -i '' "s/version=\"1.7.1\"/version=\"$VERSION\"/" "$BUILD_DIR/distribution.xml"

/usr/bin/productbuild \
  --distribution "$BUILD_DIR/distribution.xml" \
  --resources "$SCRIPT_DIR/installer/macos/resources/da.lproj" \
  --package-path "$BUILD_DIR" \
  "$OUTPUT_PKG"

echo "$OUTPUT_PKG"
