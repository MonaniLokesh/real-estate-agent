# AGENT_TRACKING.md — EstateAgent AI development log

Central history of changes per `AGENT.md` / `SKILLS.md`.

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
