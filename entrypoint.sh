#!/bin/sh

set -eu

APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"
NGROK_API_URL="${NGROK_API_URL:-http://ngrok:4040/api/tunnels}"


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


resolve_ngrok_url() {
  ATTEMPTS=30
  URL=""

  while [ "$ATTEMPTS" -gt 0 ]; do
    RESPONSE="$(curl -fsS "$NGROK_API_URL" || true)"
    URL="$(printf '%s' "$RESPONSE" | grep -o 'https://[^"]*' | head -n 1 || true)"
    if [ -n "$URL" ]; then
      printf '%s' "$URL"
      return 0
    fi
    ATTEMPTS=$((ATTEMPTS - 1))
    sleep 1
  done

  return 1
}


register_telegram_webhook() {
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_WEBHOOK_SECRET:-}" ]; then
    echo "Skipping Telegram webhook registration because TELEGRAM_BOT_TOKEN or TELEGRAM_WEBHOOK_SECRET is missing."
    return
  fi

  URL="$(resolve_ngrok_url || true)"
  if [ -z "$URL" ]; then
    echo "Could not determine ngrok public URL from $NGROK_API_URL" >&2
    return 1
  fi

  WEBHOOK_URL="$URL/webhooks/telegram"
  TELEGRAM_API_URL="https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN"
  CURRENT_WEBHOOK_URL="$(curl -fsS "$TELEGRAM_API_URL/getWebhookInfo" | sed -n 's/.*"url":"\([^"]*\)".*/\1/p')"

  if [ "$CURRENT_WEBHOOK_URL" = "$WEBHOOK_URL" ]; then
    echo "Telegram webhook is already set to $WEBHOOK_URL"
    return
  fi

  echo "Registering Telegram webhook: $WEBHOOK_URL"
  curl -fsS -X POST "$TELEGRAM_API_URL/setWebhook" \
    -H "Content-Type: application/json" \
    -d "{\"url\":\"$WEBHOOK_URL\",\"secret_token\":\"$TELEGRAM_WEBHOOK_SECRET\"}" >/dev/null

  echo "Telegram webhook registered successfully."
}


run_db_migrations

uv run --no-sync uvicorn app.main:app --host "$APP_HOST" --port "$APP_PORT" &
APP_PID=$!

trap 'kill "$APP_PID" 2>/dev/null || true' INT TERM

wait_for_local_app
register_telegram_webhook

wait "$APP_PID"
