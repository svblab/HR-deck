#!/bin/bash
# Установить vendored venv и launcher в staging debian/personnel-availability.
set -euo pipefail

DESTDIR="${1:?usage: install-venv.sh debian/personnel-availability}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET="$DESTDIR/opt/personnel-availability"
INSTALL_VENV="/opt/personnel-availability/venv"

install -d "$TARGET"
# Fresh venv in DESTDIR so bin/python* correctly point at system python3
# (package Depends: python3). Do not use --copies: a copied interpreter
# loses its stdlib prefix after relocation.
python3 -m venv "$TARGET/venv"
"$TARGET/venv/bin/pip" install --upgrade pip
"$TARGET/venv/bin/pip" install --no-cache-dir "$ROOT/build/wheels"/*.whl

# Rewrite pip/entry-point shebangs from the DESTDIR path to the install path.
for script in "$TARGET/venv/bin"/*; do
    [ -f "$script" ] || continue
    [ -L "$script" ] && continue
    if head -1 "$script" 2>/dev/null | grep -q '^#!'; then
        sed -i "1s|^#!.*|#!${INSTALL_VENV}/bin/python|" "$script"
    fi
done

if [ -f "$TARGET/venv/pyvenv.cfg" ]; then
    sed -i "s|^home = .*|home = /usr/bin|" "$TARGET/venv/pyvenv.cfg"
fi

install -d "$DESTDIR/usr/bin"
install -m 755 "$ROOT/packaging/debian/personnel-availability-launcher" \
    "$DESTDIR/usr/bin/personnel-availability"
# Windows checkouts may leave CRLF in the launcher; Linux rejects #!/bin/sh\r.
sed -i 's/\r$//' "$DESTDIR/usr/bin/personnel-availability"
# Defense in depth: strip CR from any text entry-point scripts we rewrote.
for script in "$TARGET/venv/bin"/*; do
    [ -f "$script" ] || continue
    [ -L "$script" ] && continue
    if head -1 "$script" 2>/dev/null | grep -q '^#!'; then
        sed -i 's/\r$//' "$script"
    fi
done
