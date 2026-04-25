#!/bin/sh

set -eu

APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"


run_db_migrations() {
  if [ -z "${SUPABASE_DB_URL:-}" ]; then
    echo "Skipping DB migrations."
    return
  fi

  echo "Applying db/schema.sql..."
  psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f /app/db/schema.sql
}


wait_for_local_app() {
  ATTEMPTS=30

  while [ "$ATTEMPTS" -gt 0 ]; do
    if curl -fsS "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    ATTEMPTS=$((ATTEMPTS - 1))
    sleep 1
  done

  echo "App did not become healthy on port ${APP_PORT}." >&2
  return 1
}


run_db_migrations

uv run --no-sync uvicorn app.main:app --host "$APP_HOST" --port "$APP_PORT" &
APP_PID=$!

trap 'kill "$APP_PID" 2>/dev/null || true' INT TERM

wait_for_local_app
# Twilio WhatsApp webhook must be set manually in Twilio Sandbox Console:
# Sandbox Settings → "WHEN A MESSAGE COMES IN" → set to:
# https://your-ngrok-or-prod-url.com/webhooks/twilio/whatsapp
# Method: HTTP POST

wait "$APP_PID"
