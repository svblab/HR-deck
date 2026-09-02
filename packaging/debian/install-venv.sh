#!/bin/bash
# Установить vendored venv и launcher в staging debian/personnel-availability.
set -euo pipefail

DESTDIR="${1:?usage: install-venv.sh debian/personnel-availability}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET="$DESTDIR/opt/personnel-availability"
INSTALL_VENV="/opt/personnel-availability/venv"

install -d "$TARGET"
cp -a "$ROOT/build/venv" "$TARGET/venv"

PY_IMPL=""
for candidate in "$TARGET/venv/bin"/python3.*; do
    [ -e "$candidate" ] || continue
    if [ -L "$candidate" ]; then
        candidate="$(readlink -f "$candidate")"
    fi
    if [ -f "$candidate" ] && head -1 "$candidate" | grep -q '^#!'; then
        PY_IMPL="$(basename "$candidate")"
        break
    fi
done
if [ -z "$PY_IMPL" ]; then
    echo "could not find python3.* interpreter script in venv/bin" >&2
    exit 1
fi

for script in "$TARGET/venv/bin"/*; do
    [ -e "$script" ] || continue
    if [ -L "$script" ]; then
        script="$(readlink -f "$script")"
    fi
    [ -f "$script" ] || continue
    if head -1 "$script" 2>/dev/null | grep -q '^#!'; then
        sed -i "1s|^#!.*|#!${INSTALL_VENV}/bin/python|" "$script"
    fi
done

rm -f "$TARGET/venv/bin/python" "$TARGET/venv/bin/python3"
ln -sf "$PY_IMPL" "$TARGET/venv/bin/python3"
ln -sf "$PY_IMPL" "$TARGET/venv/bin/python"

if [ -f "$TARGET/venv/pyvenv.cfg" ]; then
    sed -i "s|^home = .*|home = /usr/bin|" "$TARGET/venv/pyvenv.cfg"
    sed -i "s|^command = .*|command = /usr/bin/python3 -m venv ${INSTALL_VENV}|" \
        "$TARGET/venv/pyvenv.cfg"
fi

install -d "$DESTDIR/usr/bin"
install -m 755 "$ROOT/packaging/debian/personnel-availability-launcher" \
    "$DESTDIR/usr/bin/personnel-availability"
