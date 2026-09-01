#!/bin/bash
# Проверка: собранный .deb устанавливается на чистый Ubuntu 24.04 (EPIC-015).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEB="$(ls -1 "$ROOT"/../*.deb 2>/dev/null | head -1)"
if [ -z "$DEB" ]; then
  echo "No .deb found in $(dirname "$ROOT")" >&2
  exit 1
fi

DEB_NAME="$(basename "$DEB")"
DEB_DIR="$(dirname "$DEB")"

docker run --rm \
  -v "$DEB_DIR:/pkgs:ro" \
  ubuntu:24.04 bash -cex "
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y /pkgs/$DEB_NAME
    QT_QPA_PLATFORM=offscreen /opt/personnel-availability/venv/bin/python -c \"
import sqlcipher3
from PySide6.QtWidgets import QApplication
from data.migrations import discover_migrations
print('install smoke ok', len(discover_migrations()))
\"
  "
