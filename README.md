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

## Webhooks

### WhatsApp

- `POST /webhooks/whatsapp`
- Optional header: `X-Webhook-Secret: <WEBHOOK_SECRET>`
- Current behavior returns the generated reply in JSON so you can connect your BSP sender separately.

### Telegram

- `POST /webhooks/telegram`
- Optional header: `X-Telegram-Bot-Api-Secret-Token: <TELEGRAM_WEBHOOK_SECRET>`
- Requires `TELEGRAM_BOT_TOKEN`
- The app replies directly using Telegram Bot API `sendMessage`

## Database

Apply [`db/schema.sql`](/Users/dilkushsingh/Desktop/Projects/learning/real-estate-agent/db/schema.sql) in Supabase SQL Editor.

Key tables:

- `leads`: one row per `(channel, contact_id)`
- `properties`: factual inventory used for grounded matches
- `agent_logs`: trace of webhook events, decisions, and tool calls
