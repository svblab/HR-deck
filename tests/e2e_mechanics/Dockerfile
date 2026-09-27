# Dual-peer E2E mechanics runner (Ubuntu 24.04).
# Two isolated data volumes + shared exchange; orchestration is service-layer-only
# (single runner process, two independent SQLCipher installations).
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QT_QPA_PLATFORM=offscreen

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        build-essential \
        libegl1 \
        libxkbcommon0 \
        libgl1 \
        libdbus-1-3 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE.txt ./
COPY src ./src
COPY tests ./tests

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -e ".[dev]" \
    && /opt/venv/bin/python -c "from sqlcipher3 import dbapi2 as s; print('sqlcipher3', s.sqlite_version)"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src:/app

VOLUME ["/e2e-data"]

ENTRYPOINT ["python", "-m", "tests.e2e_mechanics"]
CMD ["--root", "/e2e-data", "--seed", "20260927", "--duration-seconds", "1440"]
