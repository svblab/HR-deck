#!/bin/bash
# Собрать папку dist/test-bundle-<version>/ для передачи тестировщику (USB/сеть).
# Не коммитит артефакты в git — только собирает локальную папку.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p dist

if ! ls dist/personnel-availability_*.deb >/dev/null 2>&1; then
  echo "No .deb in dist/ — running scripts/build-deb.sh…"
  chmod +x scripts/build-deb.sh packaging/debian/*.sh
  ./scripts/build-deb.sh
fi

DEB="$(ls -1 dist/personnel-availability_*.deb | head -1)"
DEB_NAME="$(basename "$DEB")"
# Version from filename: personnel-availability_0.1.0-1_amd64.deb → 0.1.0-1
VERSION="$(echo "$DEB_NAME" | sed -n 's/^personnel-availability_\(.*\)_amd64\.deb$/\1/p')"
if [ -z "$VERSION" ]; then
  echo "Cannot parse version from $DEB_NAME" >&2
  exit 1
fi

SUM="${DEB}.sha256"
if [ ! -f "$SUM" ]; then
  echo "Computing sha256 for $DEB_NAME…"
  (cd dist && sha256sum "$DEB_NAME" > "${DEB_NAME}.sha256")
fi

BUNDLE="dist/test-bundle-${VERSION}"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE"

cp -f "$DEB" "$SUM" "$BUNDLE/"
cp -f docs/manual/install-update-quick.md "$BUNDLE/"
cp -f docs/manual/user-guide.md "$BUNDLE/"
cp -f docs/manual/quick-reference.md "$BUNDLE/"
cp -f docs/TESTING.md "$BUNDLE/"

echo
echo "=== test bundle ready: ${BUNDLE}/ ==="
(
  cd "$BUNDLE"
  echo "Contents:"
  ls -la
  echo
  echo "SHA256 of all files:"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum *
  else
    # macOS fallback (not the primary target)
    shasum -a 256 *
  fi
)
echo
echo "Copy the whole folder ${BUNDLE}/ onto external media for the HR tester."
echo "They should start with install-update-quick.md §0 (pre-install checks)."
