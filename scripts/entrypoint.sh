#!/usr/bin/env bash
set -e

# Start Alloy in background (only if fully configured)
if [ -n "$GRAFANA_LOKI_URL" ]; then
  ALLOY_MISSING=""
  for var in GRAFANA_LOKI_USER GRAFANA_LOKI_API_KEY GRAFANA_METRICS_URL GRAFANA_METRICS_USER GRAFANA_METRICS_API_KEY ALLOY_PG_DSN; do
    [ -z "${!var}" ] && ALLOY_MISSING="$ALLOY_MISSING $var"
  done

  if [ -n "$ALLOY_MISSING" ]; then
    echo "WARNING: Skipping Alloy -- missing env vars:$ALLOY_MISSING"
  else
    echo "Starting Grafana Alloy..."
    alloy run \
      --storage.path=/app/data/alloy \
      --server.http.listen-addr=127.0.0.1:12345 \
      /app/config/alloy-config.alloy &
    ALLOY_PID=$!
    echo "Alloy started (PID $ALLOY_PID)"
  fi
fi

# Run database migrations
echo "Running alembic migrations..."
alembic upgrade head

# Start the application (exec replaces shell, uvicorn gets PID 1 signals)
echo "Starting uvicorn..."
exec uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8000
