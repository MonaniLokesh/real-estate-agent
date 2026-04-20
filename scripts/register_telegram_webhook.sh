#!/bin/sh

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN is required in .env}"
: "${TELEGRAM_WEBHOOK_SECRET:?TELEGRAM_WEBHOOK_SECRET is required in .env}"

TELEGRAM_API_URL="https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN"
START_DEPENDENCIES="${START_DEPENDENCIES:-1}"
NGROK_API_URL="${NGROK_API_URL:-http://127.0.0.1:4040/api/tunnels}"

if [ "$START_DEPENDENCIES" = "1" ]; then
  echo "Starting app and ngrok..."
  docker compose up -d app ngrok >/dev/null
fi

echo "Waiting for ngrok public URL..."
URL=""
ATTEMPTS=30

while [ "$ATTEMPTS" -gt 0 ]; do
  RESPONSE="$(curl -fsS "$NGROK_API_URL" || true)"
  URL="$(printf '%s' "$RESPONSE" | grep -o 'https://[^"]*' | head -n 1 || true)"
  if [ -n "$URL" ]; then
    break
  fi
  ATTEMPTS=$((ATTEMPTS - 1))
  sleep 1
done

if [ -z "$URL" ]; then
  echo "Could not determine ngrok public URL from $NGROK_API_URL" >&2
  exit 1
fi

WEBHOOK_URL="$URL/webhooks/telegram"
CURRENT_WEBHOOK_URL="$(curl -fsS "$TELEGRAM_API_URL/getWebhookInfo" | sed -n 's/.*"url":"\([^"]*\)".*/\1/p')"

if [ "$CURRENT_WEBHOOK_URL" = "$WEBHOOK_URL" ]; then
  echo "Telegram webhook is already set to $WEBHOOK_URL"
  exit 0
fi

echo "Registering Telegram webhook: $WEBHOOK_URL"
curl -fsS -X POST "$TELEGRAM_API_URL/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"$WEBHOOK_URL\",\"secret_token\":\"$TELEGRAM_WEBHOOK_SECRET\"}"

printf '\nTelegram webhook registered successfully.\n'
printf 'Webhook URL: %s\n' "$WEBHOOK_URL"
