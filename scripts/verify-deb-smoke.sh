#!/bin/bash
# Smoke-проверка установленного .deb (EPIC-015): shebang, импорты, Qt offscreen.
set -euo pipefail

export QT_QPA_PLATFORM=offscreen

PY=/opt/personnel-availability/venv/bin/python
ENTRY=/opt/personnel-availability/venv/bin/personnel-availability
LAUNCHER=/usr/bin/personnel-availability
EXPECTED_SHEBANG='#!/opt/personnel-availability/venv/bin/python'

for path in "$LAUNCHER" "$ENTRY" "$PY"; do
  if [ ! -e "$path" ]; then
    echo "missing required path: $path" >&2
    exit 1
  fi
done

script_shebang() {
  local file="$1"
  if [ -L "$file" ]; then
    file="$(readlink -f "$file")"
  fi
  head -1 "$file"
}

actual_entry="$(script_shebang "$ENTRY")"
if [ "$actual_entry" != "$EXPECTED_SHEBANG" ]; then
  echo "bad shebang on $ENTRY: $actual_entry (expected $EXPECTED_SHEBANG)" >&2
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
