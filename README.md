# EstateAgent AI

Minimal FastAPI + LangGraph backend for a real-estate sales assistant that now supports both WhatsApp and Telegram on the same agent core.

## What Changed

- Shared agent flow for `whatsapp` and `telegram`
- Channel-aware lead persistence in Supabase
- Telegram webhook + Bot API reply support
- Property lookup grounded in `properties` table filters
- Lightweight conversation summary saved back to `leads`

## Run Locally

```bash
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload
```

Or run the full local stack:

```bash
docker compose up --build
```

That now starts:
- the FastAPI app
- ngrok
- a one-shot `telegram-webhook-setup` container that registers Telegram automatically if the webhook URL changed

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Local dry run:

```bash
curl -X POST http://127.0.0.1:8000/debug/run \
  -H 'Content-Type: application/json' \
  -d '{"channel":"telegram","contact_id":"123","chat_id":"123","text":"2 BHK in Noida under 80 lakh"}'
```

## ngrok

For webhook testing, the repo now includes an `ngrok` service in [`docker-compose.yml`](/Users/dilkushsingh/Desktop/Projects/learning/real-estate-agent/docker-compose.yml:1).

1. Add your ngrok auth token in `.env`:

```env
NGROK_AUTHTOKEN=your_ngrok_auth_token
```

2. Start the stack:

```bash
docker compose up --build
```

3. Fetch the current public HTTPS URL:

```bash
curl http://127.0.0.1:4040/api/tunnels
```

4. Use the returned `public_url` as the base for your webhooks:

- Telegram: `<public_url>/webhooks/telegram`
- WhatsApp: `<public_url>/webhooks/whatsapp`

The local ngrok inspector UI is also available at `http://127.0.0.1:4040`.

If you want to register Telegram in one step, run:

```bash
sh scripts/register_telegram_webhook.sh
```

That script starts `app` and `ngrok`, reads the current public URL from ngrok’s local API, checks Telegram’s current webhook, and only calls `setWebhook` when the target URL has changed. The same script is also used automatically by the `telegram-webhook-setup` Compose service during `docker compose up`.

## Webhooks

### WhatsApp

- `POST /webhooks/whatsapp`
- Optional header: `X-Webhook-Secret: <WHATSAPP_WEBHOOK_SECRET>`
- Current behavior returns the generated reply in JSON so you can connect your BSP sender separately.

### Telegram

- `POST /webhooks/telegram`
- Optional header: `X-Telegram-Bot-Api-Secret-Token: <TELEGRAM_WEBHOOK_SECRET>`
- Requires `TELEGRAM_BOT_TOKEN`
- The app replies directly using Telegram Bot API `sendMessage`

Register Telegram against the current ngrok URL:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "<public_url>/webhooks/telegram",
    "secret_token": "<TELEGRAM_WEBHOOK_SECRET>"
  }'
```

For WhatsApp, configure your provider webhook target as:

```text
<public_url>/webhooks/whatsapp
```

## Database

Apply [`db/schema.sql`](/Users/dilkushsingh/Desktop/Projects/learning/real-estate-agent/db/schema.sql) in Supabase SQL Editor.

Key tables:

- `leads`: one row per `(channel, contact_id)`
- `properties`: factual inventory used for grounded matches
- `agent_logs`: trace of webhook events, decisions, and tool calls
