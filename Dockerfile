# Multi-stage build using uv
# Reference: https://docs.astral.sh/uv/guides/integration/docker/

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install system deps needed for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    default-jre \
    git \
 && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install project
COPY . .
RUN uv sync --frozen --no-dev

# Install dbt packages at build time (needs git, no DB required)
RUN cd mpi_analytics && uv run python run_dbt.py deps

# --- Runtime stage ---
# Use the same base as the builder so Python patch versions match exactly.
# python:3.12-slim-bookworm can drift to a different patch (e.g. 3.12.13)
# while the uv image stays on 3.12.12, breaking the copied venv.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

RUN groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# scripts/backup_database.py requires pg_dump, psql, and pg_restore at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    default-jre-headless \
    git \
    gnupg \
    wget \
    lsb-release \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
 && mkdir -p /etc/apt/keyrings/ \
 # Grafana Alloy (observability sidecar)
 && wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
    > /etc/apt/sources.list.d/grafana.list \
 # PostgreSQL Global Development Group (PGDG) repo for pg16 client tools
 && wget -q -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/keyrings/pgdg.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update && apt-get install -y --no-install-recommends \
    alloy \
    postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the virtual environment and source from builder
# (uv/uvx are already in this image)
COPY --from=builder --chown=appuser:appuser /app /app

# App creates logs/ at import time; ensure appuser can write to /app
RUN chown appuser:appuser /app

# Ensure entrypoint has Linux line endings (strips Windows \r)
RUN sed -i 's/\r$//' /app/scripts/entrypoint.sh && chmod +x /app/scripts/entrypoint.sh

# Alloy needs a writable data dir for positions file (owned by appuser)
RUN mkdir -p /app/data/alloy && chown appuser:appuser /app/data/alloy

USER appuser

# Put the venv on PATH so `alembic` and `uvicorn` are found
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Tell uv to use the existing venv instead of creating a new one.
# The dbt scheduler shells out to `uv run python ...` -- without this,
# uv sees pyproject.toml and tries to resolve/download everything again.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV UV_NO_SYNC=1

# Ensure Java is in the PATH (use default-java symlink for multi-arch support)
ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV PATH="${JAVA_HOME}/bin:${PATH}"

EXPOSE 8000

# Alembic runs from repo root (where alembic.ini lives), then start uvicorn
CMD ["bash", "/app/scripts/entrypoint.sh"]
