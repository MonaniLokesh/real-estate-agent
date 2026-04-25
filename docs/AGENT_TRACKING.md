# AGENT_TRACKING.md — EstateAgent AI development log

Central history of changes per `docs/AGENT.md` / `docs/SKILLS.md`.

---

## 2026-04-18 — Supabase schema (initial)

**Time:** Session start (approx.)  
**Status:** Completed  

**Files changed**
- `schema.sql` (new) — Postgres tables, extensions, indexes, RLS.

**Summary**
- Added `leads` (phone unique, `lead_info` jsonb, `summary`, handoff flag, timestamps).
- Added `properties` with `embedding vector(1536)` (OpenAI ada-2 size), filters, IVFFLAT cosine index.
- Added `agent_logs` for traceability (`step`, `payload`, `phone`).
- Enabled RLS on all tables with no policies for anon/auth — server must use `service_role` or Edge Functions.

**Key decisions**
- Single SQL file at repo root to avoid deep folder trees in Phase 1.
- IVFFLAT with `lists=100` as default; documented that bulk loads may want a rebuild.

**Edge cases**
- Empty `lead_info` / `{}` default avoids null handling in app code.
- Vector dimension fixed to 1536; changing embedding model requires migration.

**Testing**
- Not run against a live Supabase project in this step; apply `schema.sql` in Supabase SQL Editor and verify extensions enabled.

---

## 2026-04-18 — LangGraph agent (minimal single file)

**Time:** Same session  
**Status:** Completed  

**Files changed**
- `agent.py` (new) — `AgentState`, triage + respond nodes, `MemorySaver` checkpointer, stub tools, optional Supabase `agent_logs` writes.
- `requirements.txt` (new)
- `.env.example` (new)

**Summary**
- Graph: `START → triage → respond → END`.
- **Triage:** `ChatOpenAI` pointed at **Groq** (`GROQ_API_KEY`, base `https://api.groq.com/openai/v1`) + `TriageDecision` (structured output) when configured; otherwise keyword **heuristic** (human/handoff, visit, property keywords, else qualify).
- **Respond:** same Groq-backed chat model with system prompt + short message window + JSON context (`next_action`, `lead_info`, matched properties, slots). Without `GROQ_API_KEY`, small **intent-specific fallback** strings (no hallucinated listings).
- **Stub tools:** `fetch_properties`, `check_calendar_availability`, `get_lead_history` return empty results until wired to Supabase/pgvector and calendars.
- **Logging:** `log_agent_step` inserts into `agent_logs` when `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` are set; failures are swallowed so chat never breaks.
- **Checkpointing:** `thread_id = phone` so in-process memory carries `lead_info` across turns; `run_turn` does **not** reset `lead_info` each invoke.

**Key code decisions**
- Prompts kept **inline** in `agent.py` for Phase 1 (no `/prompts/` tree yet); `AGENT.md` still lists future prompt files.
- Single compiled graph singleton via `get_graph()` for simple server use.

**Edge cases**
- No `GROQ_API_KEY`: deterministic triage + safe fallback replies.
- `fetch_properties` empty: respond path instructed (when LLM on) to admit inventory check and ask clarifiers.

**Testing**
- `python -c "from agent import run_turn; print(run_turn('+9199', '2 BHK under 80 lakh'))"` — returns fallback match copy without network.

**Prompt excerpt (system — in code)**

```text
You are EstateAgent AI, a professional WhatsApp assistant for an Indian real estate broker.
You qualify buyers/sellers, never invent property prices or addresses, and offer a human handoff when unsure.
Reply in the user's language (Hindi/English mix is common). Be concise and helpful.
```

---

## 2026-04-18 — FastAPI webhook

**Time:** Same session  
**Status:** Completed  

**Files changed**
- `main.py` (new) — FastAPI app, `/health`, `/webhooks/whatsapp`, gated `/debug/run`.
- `.gitignore` (new) — ignore `.venv/`, `__pycache__/`, `.env`.

**Summary**
- `POST /webhooks/whatsapp` accepts JSON, `extract_phone_and_text` tries several common nested keys (`message.text`, `message.from`, `customer.phone`, etc.).
- Optional `X-Webhook-Secret` header checked against `WEBHOOK_SECRET` / `webhook_secret` env when configured.
- Invokes `run_turn` and returns `reply` in JSON for now (BSP “send message” call intentionally left to provider SDK/dashboard to avoid locking to one vendor in this file).
- `POST /debug/run` behind `ALLOW_DEBUG=true` for local dry runs.

**Key code decisions**
- Return body includes `reply` for integration testing without outbound WhatsApp credentials.

**Edge cases**
- Empty body text: returns `{ok: true, ignored: true}` so Meta retries do not error-loop the agent.
- Non-JSON body: HTTP 400.

**Testing**
- `python -c "from main import app; print([r.path for r in app.routes])"` — routes registered.

---

## 2026-04-18 — LLM provider: OpenAI → Groq

**Time:** Same session  
**Status:** Completed  

**Files changed**
- `agent.py` — `_chat()` now uses `ChatOpenAI` with `base_url` Groq OpenAI-compatible endpoint and `GROQ_API_KEY`; optional `GROQ_MODEL`, `GROQ_BASE_URL`, `GROQ_TEMPERATURE`.
- `.env.example` — OpenAI vars replaced with Groq vars.
- `AGENT_TRACKING.md` — earlier LangGraph bullets aligned with Groq.

**Why**
- User request to use Groq instead of OpenAI for chat completions.

**Key decisions**
- Kept `langchain-openai` `ChatOpenAI` (no new dependency): Groq documents this compatibility layer.
- Default model `llama-3.3-70b-versatile` (override via `GROQ_MODEL`).

**Testing**
- Import/smoke without `GROQ_API_KEY` still uses heuristics + fallback strings.

---

## 2026-04-20 — Shared channel refactor + Telegram bot support

**Time:** Evening session (approx.)  
**Status:** Completed  

**Files changed**
- `agent.py` — refactored graph input/state to be channel-aware, added Supabase lead upsert/load helpers, property filtering, and a lightweight summarize node.
- `main.py` — replaced single-purpose webhook handling with shared FastAPI entrypoint for WhatsApp + Telegram.
- `channels.py` (new) — inbound payload extraction for WhatsApp/Telegram and Telegram Bot API send helper.
- `config.py` (new) — centralized environment settings.
- `schema.sql` — refactored leads/logs schema to support `(channel, contact_id)` identities while keeping WhatsApp phone support.
- `.env.example` — added Telegram env vars.
- `README.md` — added setup, webhook, and local test docs.

**Summary**
- Unified the agent runtime so both channels call the same `run_turn(...)` path.
- Added `POST /webhooks/telegram` with optional `X-Telegram-Bot-Api-Secret-Token` validation and direct `sendMessage` reply through Telegram Bot API.
- Preserved `POST /webhooks/whatsapp`, but moved it onto the same normalized inbound message shape as Telegram.
- Upgraded persistence from phone-only to channel-aware lead records, which is required for Telegram users who may not share a phone number.
- Added lightweight grounded property filtering from Supabase `properties` based on BHK, budget, and location hints.

**Key decisions**
- Kept the codebase small: only added `config.py` and `channels.py` instead of introducing a large folder tree.
- Used stdlib HTTP for Telegram messaging to avoid unnecessary new dependencies.
- Kept WhatsApp outbound sending out of scope for now because the project still has no provider-specific BSP credentials or SDK wired.
- Added a summarize node without introducing a separate prompts folder yet, to stay aligned with the Phase 1 “minimal files” rule.

**Edge cases**
- Telegram callback queries now fall back to callback `data` when there is no `message.text`.
- Missing/malformed webhook bodies return safe ignore or 400 paths instead of crashing the graph.
- Existing Supabase installs with `leads.phone NOT NULL` need the included `alter column phone drop not null` migration path before Telegram leads can be stored.
- WhatsApp still returns reply JSON only; Telegram sends outbound automatically.

**Testing**
- `.venv/bin/python -c "from main import app; print(sorted(route.path for route in app.routes))"` — confirmed `/webhooks/whatsapp`, `/webhooks/telegram`, `/debug/run`, `/health`.
- `.venv/bin/python -c "from channels import extract_telegram_message; print(...)"` — confirmed Telegram payload normalization returns expected `InboundMessage`.
- `env GROQ_API_KEY= SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= .venv/bin/python -c "from agent import run_turn; print(run_turn(...))"` — confirmed offline fallback graph responds without network access.
- `.venv/bin/python -m py_compile main.py agent.py channels.py config.py` — syntax check passed.

---

## 2026-04-20 — FastAPI folder structure refactor

**Time:** Later same session  
**Status:** Completed  

**Files changed**
- `app/main.py` (new) — application factory and FastAPI assembly.
- `app/api/routes/health.py` (new) — health route.
- `app/api/routes/webhooks.py` (new) — WhatsApp, Telegram, and debug endpoints.
- `app/core/config.py` (new) — settings moved under a standard core module.
- `app/services/agent.py` (new) — agent logic moved into service layer.
- `app/services/channels.py` (new) — channel parsing and Telegram sending moved into service layer.
- `app/__init__.py`, `app/api/__init__.py`, `app/api/routes/__init__.py`, `app/core/__init__.py`, `app/services/__init__.py` (new) — package markers.
- `main.py`, `agent.py`, `channels.py`, `config.py` — converted to compatibility shims.
- `Dockerfile` — startup command updated to `app.main:app`.
- `README.md` — local run command updated to `app.main:app`.

**Summary**
- Refactored the project into a minimal conventional FastAPI package layout while preserving existing behavior.
- Kept root-level compatibility shims so old imports and commands continue working during the transition.
- Preserved public routes as `/health`, `/webhooks/whatsapp`, `/webhooks/telegram`, and `/debug/run`.

**Key decisions**
- Chose a small FastAPI structure rather than a larger layered architecture to stay aligned with the MVP simplicity rule.
- Used explicit route modules instead of keeping all endpoints in `app/main.py`, which makes further API growth easier.
- Retained root shim files to avoid unnecessary breakage for current scripts and IDE entrypoints.

**Edge cases**
- During the refactor, the debug route briefly risked moving under `/webhooks`; this was corrected to keep `/debug/run` unchanged.
- Import compatibility is preserved for code that still references root modules like `agent` or `config`.

**Testing**
- `.venv/bin/python -c "from app.main import app; print(sorted(route.path for route in app.routes))"` — confirmed `/health`, `/webhooks/whatsapp`, `/webhooks/telegram`, `/debug/run`.
- `env GROQ_API_KEY= SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= .venv/bin/python -c "from app.services.agent import run_turn; print(run_turn(...))"` — confirmed the refactored service-layer agent still returns the offline fallback reply.
- `.venv/bin/python -c "from main import app; print(app.title)"` — confirmed root shim compatibility still works.
- `.venv/bin/python -m py_compile main.py agent.py channels.py config.py app/main.py app/api/routes/health.py app/api/routes/webhooks.py app/core/config.py app/services/agent.py app/services/channels.py` — syntax check passed.

---

## 2026-04-20 — Root cleanup after package refactor

**Time:** Same session, follow-up cleanup  
**Status:** Completed  

**Files changed**
- Removed root compatibility shims: `main.py`, `agent.py`, `channels.py`, `config.py`.
- Moved `AGENT.md`, `SKILLS.md`, `AGENT_TRACKING.md` into `docs/`.
- Moved `schema.sql` into `db/schema.sql`.
- Updated `README.md`, `docs/AGENT.md`, `docs/SKILLS.md`, and this tracking file to reference the new paths.

**Summary**
- Cleaned the repository root so only true project-level files remain there.
- Dropped the temporary backward-compatibility layer now that the FastAPI package layout is established.
- Grouped operational docs under `docs/` and database artifacts under `db/`.

**Key decisions**
- Kept `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `uv.lock`, and `README.md` at root because they are standard repository entrypoint files.
- Chose not to move `.env.example` because it is commonly expected at the repository root.

**Edge cases**
- Any external scripts or commands still importing from root modules like `agent` or `config` will now need to use `app.services.agent` and `app.core.config`.
- Any manual schema references must now point to `db/schema.sql`.

**Testing**
- `ls -1` — confirmed root reduced to `app/`, `db/`, `docs/`, `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `uv.lock`, and `README.md` before cleanup of generated cache files.
- `.venv/bin/python -c "from app.main import app; print(sorted(route.path for route in app.routes))"` — confirmed `/health`, `/webhooks/whatsapp`, `/webhooks/telegram`, `/debug/run`.
- `env GROQ_API_KEY= SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= .venv/bin/python -c "from app.services.agent import run_turn; print(run_turn(...))"` — confirmed the package-only import path works after removing the root shims.
- `.venv/bin/python -m py_compile app/main.py app/api/routes/health.py app/api/routes/webhooks.py app/core/config.py app/services/agent.py app/services/channels.py` — syntax check passed.
- Removed generated root `__pycache__/` after verification.

---

## 2026-04-20 — ngrok Docker Compose support

**Time:** Same session, local webhook setup  
**Status:** Completed  

**Files changed**
- `docker-compose.yml` — added an `ngrok` service that tunnels to `app:8000` and exposes port `4040`.
- `.env.example` — added `NGROK_AUTHTOKEN` and removed hardcoded example Telegram secrets.
- `.env` — added `NGROK_AUTHTOKEN` placeholder for local compose usage.
- `README.md` — added ngrok startup, tunnel discovery, and webhook registration instructions.

**Summary**
- Added an ngrok container so Telegram and WhatsApp webhooks can hit the local FastAPI app during development.
- Documented the exact flow for retrieving the public tunnel URL and using it for webhook registration.

**Key decisions**
- Kept the implementation Docker-first to match the existing local stack.
- Used the ngrok local inspector/API on `127.0.0.1:4040` as the simplest way to discover the active public URL.

**Edge cases**
- ngrok public URLs change on restart unless you use a reserved domain on your ngrok account.
- Telegram webhook registration must be repeated whenever the ngrok URL changes.
- WhatsApp provider verification still depends on the BSP you use; this repo now provides the reachable local endpoint only.

**Testing**
- Static configuration and documentation update only; live ngrok startup and webhook registration were not executed in this environment.
- `docker compose config` — validated the Compose structure with the new `ngrok` service.

---

## 2026-04-20 — WhatsApp secret env rename

**Time:** Same session, env naming cleanup  
**Status:** Completed  

**Files changed**
- `app/core/config.py` — renamed `webhook_secret` setting to `whatsapp_webhook_secret`.
- `app/api/routes/webhooks.py` — updated WhatsApp webhook auth to read `settings.whatsapp_webhook_secret`.
- `.env` — renamed `WEBHOOK_SECRET` to `WHATSAPP_WEBHOOK_SECRET`.
- `.env.example` — renamed the example variable and updated the comment.
- `README.md` — updated the WhatsApp webhook header/env reference.

**Summary**
- Renamed the WhatsApp secret env var to make it explicit and avoid confusion with Telegram webhook auth.

**Key decisions**
- Kept the inbound HTTP header name as `X-Webhook-Secret` so external integrations do not need to change headers, only the local env variable name.

**Edge cases**
- Any existing deployment still using `WEBHOOK_SECRET` in its environment will stop authenticating WhatsApp requests until it is renamed to `WHATSAPP_WEBHOOK_SECRET`.

**Testing**
- Static rename only; verified by code search and syntax pass after the change.

---

## 2026-04-20 — One-time Telegram webhook registration script

**Time:** Same session, webhook automation follow-up  
**Status:** Completed  

**Files changed**
- `scripts/register_telegram_webhook.sh` (new) — starts `app` and `ngrok`, reads the active ngrok public URL, and registers Telegram via `setWebhook`.
- `README.md` — documented the one-command Telegram webhook registration flow.

**Summary**
- Added a helper script so Telegram webhook setup does not require manually copying the ngrok URL and crafting the `curl` request each time.
- Updated it to check the current Telegram webhook first and skip `setWebhook` if the target URL already matches.

**Key decisions**
- Used the existing Docker Compose `ngrok` service instead of starting a separate local `ngrok http 8000` process.
- Read the public URL from ngrok’s inspector API on `127.0.0.1:4040` rather than scraping CLI logs.

**Edge cases**
- The script expects `.env` to contain both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET`.
- The script assumes Docker Compose is available locally.
- If ngrok takes too long to start or no tunnel is available, the script exits with an error.
- If the ngrok URL changes, the script will re-register Telegram as expected.

**Testing**
- Static script/documentation update only; live webhook registration was not executed in this environment.

---

## 2026-04-20 — Automatic Telegram webhook setup via Compose

**Time:** Same session, Compose automation follow-up  
**Status:** Completed  

**Files changed**
- `docker-compose.yml` — added `telegram-webhook-setup` one-shot service.
- `scripts/register_telegram_webhook.sh` — made the script reusable both locally and inside Docker via `START_DEPENDENCIES` and `NGROK_API_URL`.
- `README.md` — documented that `docker compose up` now runs Telegram webhook setup automatically.

**Summary**
- Added a one-shot Compose service that registers the Telegram webhook automatically whenever the local stack starts.
- Reused the existing script instead of duplicating webhook registration logic.

**Key decisions**
- Used `curlimages/curl` as a minimal runtime for the one-shot setup container.
- Mounted the repository read-only and reused `.env` plus the existing shell script to keep behavior consistent between local and Compose execution.

**Edge cases**
- The one-shot setup container exits after completing its work; this is expected.
- If ngrok has not produced a public URL yet, the setup container retries for a short period and then exits with an error.
- If the current Telegram webhook already matches the ngrok URL, the setup container exits successfully without changing anything.

**Testing**
- `docker compose config` — validated the Compose structure with the `telegram-webhook-setup` one-shot service.

---

## 2026-04-20 — Consolidated container startup entrypoint

**Time:** Same session, startup consolidation  
**Status:** Completed  

**Files changed**
- `entrypoint.sh` (new) — app container startup logic for optional DB migrations, app boot, health wait, and Telegram webhook registration.
- `Dockerfile` — installs `curl` and `postgresql-client`, makes `entrypoint.sh` executable, and uses it as the container entrypoint.
- `docker-compose.yml` — removed the separate `telegram-webhook-setup` service and passed `NGROK_API_URL` into the app container.
- `.env.example` — added `SUPABASE_DB_URL`, `RUN_DB_MIGRATIONS`, and `AUTO_REGISTER_TELEGRAM_WEBHOOK`.
- `README.md` — updated startup docs to describe the new entrypoint-based flow.
- Removed `scripts/register_telegram_webhook.sh` because its logic now lives in `entrypoint.sh`.

**Summary**
- Moved startup-time automation into the app container so `docker compose up` handles DB schema apply and Telegram webhook registration from one place.
- Simplified Compose by removing the extra one-shot service.

**Key decisions**
- Added an optional direct Postgres connection string (`SUPABASE_DB_URL`) because Supabase DDL migrations need SQL access, not only the REST/service-role client used by the app.
- Kept DB migrations opt-in with `RUN_DB_MIGRATIONS=0` by default to avoid accidental schema changes on every startup.
- Kept Telegram webhook auto-registration enabled by default because it is idempotent and useful in local ngrok development.

**Edge cases**
- `RUN_DB_MIGRATIONS=1` without `SUPABASE_DB_URL` now causes container startup to fail fast.
- If ngrok is slow to produce a public URL, the entrypoint waits briefly and then fails the container startup.
- If Telegram webhook credentials are missing, webhook registration is skipped without blocking app startup.

**Testing**
- `sh -n entrypoint.sh` — shell syntax check passed.
- `docker compose config` — validated the consolidated startup flow with the app entrypoint and ngrok service.

---

## 2026-04-20 — Removed startup flags

**Time:** Same session, startup simplification  
**Status:** Completed  

**Files changed**
- `entrypoint.sh` — removed `RUN_DB_MIGRATIONS` and `AUTO_REGISTER_TELEGRAM_WEBHOOK` flag checks.
- `.env.example` — removed the two flags from example config.
- `README.md` — updated startup docs to describe env-presence-driven behavior.

**Summary**
- Simplified startup so migrations run when `SUPABASE_DB_URL` exists, and Telegram registration runs when the Telegram credentials exist.

**Key decisions**
- Switched from boolean flags to presence-based behavior to reduce config clutter for the normal local workflow.

**Edge cases**
- If `SUPABASE_DB_URL` is set, migrations run on every container start; the schema file therefore needs to remain idempotent.
- If Telegram credentials are present but ngrok is unavailable, webhook registration still fails startup after the retry window.

**Testing**
- Pending shell syntax and Compose validation after flag removal.

---

## 2026-04-25 — Broker REST APIs for mobile app

**Time:** Afternoon session  
**Status:** Completed  

**Files changed**
- `app/api/routes/properties.py` (new) — CRUD + image upload endpoints for broker property management.
- `app/api/routes/leads.py` (new) — leads list, stage update, and broker action log endpoints.
- `app/api/routes/dashboard.py` (new) — summary metrics endpoint for listings, leads, and revenue estimate.
- `app/schemas/properties.py` (new) — property metadata/payload/response Pydantic models.
- `app/schemas/leads.py` (new) — lead response + stage update payload models.
- `app/schemas/__init__.py` (new) — schema exports.
- `app/main.py` — registered new routers and added permissive CORS middleware.
- `.env.example` — added `SUPABASE_SERVICE_KEY` example entry.

**Summary**
- Added broker-facing REST APIs under `/properties`, `/leads`, and `/dashboard` without modifying webhook handling logic.
- Reused the existing shared Supabase client getter from `app/services/tools.py` in all new routes.
- Implemented property image upload to Supabase Storage bucket `property-images` and returned public URLs.

**Key decisions**
- Kept existing webhook routes intact and only extended app router registration.
- Preserved snake_case column names and avoided writing the `embedding` column from broker APIs.
- Used JSON object updates for `metadata` and `lead_info` handling consistent with current table design.

**Edge cases**
- Endpoints return 404 for missing `properties`/`leads` IDs.
- API returns a 500 when Supabase credentials are not configured.
- Revenue estimate ignores rows where `price_inr` or `metadata.commission_rate` is missing.

**Testing**
- Static validation and syntax checks only in this session.

---
