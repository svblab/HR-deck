#!/bin/bash
# Smoke-проверка установленного .deb (EPIC-015): shebang, импорты, Qt offscreen.
set -euo pipefail

export QT_QPA_PLATFORM=offscreen

PY=/opt/personnel-availability/venv/bin/python
ENTRY=/opt/personnel-availability/venv/bin/personnel-availability
LAUNCHER=/usr/bin/personnel-availability
EXPECTED_SHEBANG='#!/opt/personnel-availability/venv/bin/python'

test -x "$LAUNCHER"
test -x "$ENTRY"
test -x "$PY"

actual_entry="$(head -1 "$ENTRY")"
actual_py="$(head -1 "$PY")"
if [ "$actual_entry" != "$EXPECTED_SHEBANG" ]; then
    echo "bad shebang on $ENTRY: $actual_entry (expected $EXPECTED_SHEBANG)" >&2
    exit 1
fi
if [ "$actual_py" != "$EXPECTED_SHEBANG" ]; then
    echo "bad shebang on $PY: $actual_py (expected $EXPECTED_SHEBANG)" >&2
    exit 1
fi

grep -q '/opt/personnel-availability/venv/bin/personnel-availability' "$LAUNCHER"

"$PY" -c "
import argon2  # noqa: F401
import sqlcipher3  # noqa: F401
from PySide6.QtWidgets import QApplication
from data.migrations import discover_migrations

assert len(discover_migrations()) >= 8
QApplication([])
print('deb smoke ok')
"
