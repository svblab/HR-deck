#!/bin/bash
# Проверка: собранный .deb устанавливается на чистый Ubuntu 24.04 (EPIC-015).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEB="$(ls -1 "$ROOT"/dist/*.deb 2>/dev/null | head -1)"
if [ -z "$DEB" ]; then
  DEB="$(ls -1 "$ROOT"/../*.deb 2>/dev/null | head -1)"
fi
if [ -z "$DEB" ]; then
  echo "No .deb found in $ROOT/dist or $(dirname "$ROOT")" >&2
  exit 1
fi

DEB_NAME="$(basename "$DEB")"
DEB_DIR="$(dirname "$DEB")"
SMOKE="$ROOT/scripts/verify-deb-smoke.sh"

run_in_container() {
  local engine="$1"
  local cname="pa-verify-$$"
  "$engine" rm -f "$cname" >/dev/null 2>&1 || true
  "$engine" run --name "$cname" \
    -v "$DEB_DIR:/pkgs:ro" \
    -v "$SMOKE:/verify-deb-smoke.sh:ro" \
    ubuntu:24.04 bash -cex "
      export DEBIAN_FRONTEND=noninteractive
      apt-get update
      apt-get install -y /pkgs/$DEB_NAME
      bash /verify-deb-smoke.sh
    "
  "$engine" commit "$cname" "pa-installed-$$"
  "$engine" rm -f "$cname"
  "$engine" run --rm --network none \
    -v "$SMOKE:/verify-deb-smoke.sh:ro" \
    "pa-installed-$$" bash /verify-deb-smoke.sh
  "$engine" rmi "pa-installed-$$" >/dev/null 2>&1 || true
  echo "offline smoke ok"
}

if command -v docker >/dev/null 2>&1; then
  run_in_container docker
elif command -v podman >/dev/null 2>&1; then
  run_in_container podman
else
  echo "docker or podman required for local verify-deb-install.sh" >&2
  exit 1
fi
