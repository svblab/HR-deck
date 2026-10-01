#!/usr/bin/env bash
# Full pytest on Debian 12 with distro Python 3.11 (CI job test-debian12-py311 / deploy baseline).
# Source tree is shipped via git archive into the container (no repo bind mount).
# Usage: ./scripts/test-in-debian12.sh [GIT_REF]
set -euo pipefail

REF="${1:-HEAD}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DOCKER_VOLUMES=()
if [[ -n "${PIP_CACHE_DIR_HOST:-}" ]]; then
  mkdir -p "${PIP_CACHE_DIR_HOST}"
  DOCKER_VOLUMES=(-v "${PIP_CACHE_DIR_HOST}:/pip-cache")
fi

git archive --format=tar "${REF}" | docker run --rm -i "${DOCKER_VOLUMES[@]}" \
  -e PIP_CACHE_DIR=/pip-cache \
  debian:12 bash -cex '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y \
      python3 python3-pip python3-venv python3-dev build-essential \
      libegl1 libxkbcommon0 libgl1 libdbus-1-3 libfontconfig1 libfreetype6 \
      libglib2.0-0 libxcb-xinerama0 libxcb-cursor0 libxcb-icccm4 \
      libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 \
      fonts-dejavu-core
    mkdir -p /tmp/src /pip-cache
    tar -xf - -C /tmp/src
    cd /tmp/src
    python3 -m venv .venv
    # shellcheck disable=SC1091
    . .venv/bin/activate
    pip install --upgrade pip
    pip install -e ".[dev]"
    export QT_QPA_PLATFORM=offscreen
    pytest -q
  '
