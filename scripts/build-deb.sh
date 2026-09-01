#!/bin/bash
# Сборка .deb из корня репозитория (Linux, EPIC-015).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

rm -rf debian
cp -a packaging/debian debian
cp packaging/personnel-availability.desktop debian/
chmod +x packaging/debian/*.sh

dpkg-buildpackage -us -uc -b
echo "Built: ${ROOT}/../personnel-availability_*.deb"
