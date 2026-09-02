#!/bin/bash
# Сборка .deb из корня репозитория (Linux, EPIC-015).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

rm -rf debian dist
cp -a packaging/debian debian
cp packaging/personnel-availability.desktop debian/
chmod +x packaging/debian/*.sh packaging/debian/rules

dpkg-buildpackage -us -uc -b
mkdir -p dist
mv -f "${ROOT}"/../personnel-availability_*.deb dist/
echo "Built: ${ROOT}/dist/$(basename dist/*.deb)"
