# EstateAgent AI

Minimal FastAPI + LangGraph backend for a real-estate sales assistant using Twilio WhatsApp Sandbox on a shared agent core.

## What Changed

- Shared agent flow for `whatsapp` via Twilio
- Channel-aware lead persistence in Supabase
- Twilio webhook parsing + WhatsApp API reply support
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
- automatic startup logic in the app container that can apply `db/schema.sql`

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Local dry run:

```bash
curl -X POST http://127.0.0.1:8000/debug/run \
  -H 'Content-Type: application/json' \
  -d '{"channel":"whatsapp","contact_id":"whatsapp:+911234567890","text":"2 BHK in Noida under 80 lakh"}'
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

- Twilio WhatsApp: `<public_url>/webhooks/twilio/whatsapp`

The local ngrok inspector UI is also available at `http://127.0.0.1:4040`.

## Startup Automation

[`entrypoint.sh`](/Users/dilkushsingh/Desktop/Projects/learning/real-estate-agent/entrypoint.sh:1) runs inside the app container and supports:

- optional database schema apply from [`db/schema.sql`](/Users/dilkushsingh/Desktop/Projects/learning/real-estate-agent/db/schema.sql:1)
- a startup reminder comment for manual Twilio sandbox webhook configuration

Relevant env vars:

```env
SUPABASE_DB_URL=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```

Behavior:

- If `SUPABASE_DB_URL` is present, the container applies [`db/schema.sql`](/Users/dilkushsingh/Desktop/Projects/learning/real-estate-agent/db/schema.sql:1) on startup.

Use a direct Postgres connection string for `SUPABASE_DB_URL`, not the Supabase REST URL.

## Webhooks

### Twilio WhatsApp Sandbox

- `POST /webhooks/twilio/whatsapp`
- Twilio sends `application/x-www-form-urlencoded` payloads
- The app sends reply messages through Twilio REST API

Configure Twilio sandbox webhook target as:

```text
<public_url>/webhooks/twilio/whatsapp
```

## Database

Apply [`db/schema.sql`](/Users/dilkushsingh/Desktop/Projects/learning/real-estate-agent/db/schema.sql) in Supabase SQL Editor.

Key tables:

- `leads`: one row per `(channel, contact_id)`
- `properties`: factual inventory used for grounded matches
- `agent_logs`: trace of webhook events, decisions, and tool calls
