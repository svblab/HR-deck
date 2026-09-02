#!/bin/bash
# Установить vendored venv и launcher в staging debian/personnel-availability.
set -euo pipefail

DESTDIR="${1:?usage: install-venv.sh debian/personnel-availability}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET="$DESTDIR/opt/personnel-availability"
INSTALL_VENV="/opt/personnel-availability/venv"

install -d "$TARGET"
python3 -m venv "$TARGET/venv"
if [ ! -e "$TARGET/venv/bin/python" ]; then
    ln -s python3 "$TARGET/venv/bin/python"
fi
"$TARGET/venv/bin/pip" install --upgrade pip
"$TARGET/venv/bin/pip" install --no-cache-dir "$ROOT/build/wheels"/*.whl

# Shebangs must reference the installed path, not the build staging directory.
for script in "$TARGET/venv/bin"/*; do
    [ -f "$script" ] || continue
    if head -1 "$script" 2>/dev/null | grep -q '^#!'; then
        sed -i "1s|^#!.*|#!${INSTALL_VENV}/bin/python|" "$script"
    fi
done

if [ -f "$TARGET/venv/pyvenv.cfg" ]; then
    sed -i "s|^home = .*|home = /usr/bin|" "$TARGET/venv/pyvenv.cfg"
    sed -i "s|^command = .*|command = /usr/bin/python3 -m venv ${INSTALL_VENV}|" \
        "$TARGET/venv/pyvenv.cfg"
fi

install -d "$DESTDIR/usr/bin"
install -m 755 "$ROOT/packaging/debian/personnel-availability-launcher" \
    "$DESTDIR/usr/bin/personnel-availability"
