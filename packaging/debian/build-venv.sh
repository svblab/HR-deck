#!/bin/bash
# Собрать vendored venv для включения в .deb (EPIC-015 Task 4b).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

rm -rf build/wheels build/venv build/bootstrap-venv

python3 -m venv build/bootstrap-venv
build/bootstrap-venv/bin/pip install --upgrade pip build

build/bootstrap-venv/bin/python -m build --wheel --outdir build/wheels

python3 -m venv build/venv
build/venv/bin/pip install --upgrade pip
build/venv/bin/pip install --no-cache-dir build/wheels/*.whl

QT_QPA_PLATFORM=offscreen build/venv/bin/python -c "
import sqlcipher3
from PySide6.QtWidgets import QApplication
from data.migrations import discover_migrations
assert len(discover_migrations()) >= 8
print('venv smoke ok', len(discover_migrations()))
"
