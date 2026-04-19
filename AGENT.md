# EstateAgent AI - Master Agent Architecture & Documentation

**Project:** EstateAgent AI – WhatsApp Real Estate Agent SaaS  
**Version:** Phase 1 MVP (April 2026)  
**Owner:** Lokesh (AI Engineer, India)  
**Goal:** Build a production-grade agentic WhatsApp system for real estate brokers that qualifies leads, matches properties, books site visits, handles follow-ups, and generates revenue automatically.

## Core Philosophy
- The **AI Agent is the product**. Everything else (dashboard, integrations) exists to support and control the agent.
- We use **LangGraph** for stateful, reliable, multi-step agent workflows (not simple chains).
- All agent decisions, tool calls, memory, and conversations must be fully traceable and logged.
- **Code must be kept very minimal.** No unnecessary modularization, abstractions, extra folders, or over-engineering. Only include what is strictly required for the MVP to work. Keep files small, simple, and easy to understand. Avoid creating many small modules or complex folder structures in Phase 1.

## Central Tracking Document
**File:** `AGENT_TRACKING.md` (MUST be maintained at all times)

Every time Cursor / any AI coding agent makes changes, it **MUST**:
1. Update `AGENT_TRACKING.md` with:
   - Date & time of change
   - What was changed (file name + brief description)
   - Why it was changed
   - Key code decisions made
   - Any new edge cases discovered
   - Status (Completed / In Progress / Testing)
2. Append the latest version of important prompts, graph definitions, or schemas if modified.

This tracking document prevents context loss and helps us iterate fast.

## Agent Architecture (LangGraph)

The agent is built as a **stateful LangGraph** with the following components:

### 1. Graph States
- `messages`: List of Human/AI messages (including voice transcriptions)
- `lead_info`: Structured data about the current lead (budget, location, BHK, timeline, buyer/seller, phone)
- `properties_matched`: List of property IDs or full objects
- `calendar_slots`: Available slots
- `next_action`: "qualify" | "match_properties" | "suggest_visit" | "book_visit" | "follow_up" | "close_deal" | "handoff"
- `confidence`: float (0.0 - 1.0)
- `summary`: Short summary of conversation so far
- `human_handoff_requested`: boolean

### 2. Nodes (Core Agent Steps)
1. **Triage Node** – Decide intent and route
2. **Qualification Node** – Extract buyer/seller details
3. **Property Matching Node** – Search database (vector + filters)
4. **Calendar & Booking Node** – Check availability and book
5. **Response Generation Node** – Create natural, multilingual reply
6. **Tool Execution Node** – Call external tools (calendar, payment, GST)
7. **Handoff Node** – Notify broker when confidence is low
8. **Summarization Node** – Update long-term memory

### 3. Tools Available to Agent
- `fetch_properties(query: str, filters: dict)` → returns matching properties
- `check_calendar_availability(preferred_times: list)` 
- `create_calendar_event(lead_details, slot)`
- `generate_gst_invoice(details)` 
- `create_razorpay_payment_link(amount, description)`
- `transcribe_voice(media_url)`
- `send_whatsapp_message(text, buttons?, media?)`
- `get_lead_history(phone_number)`

### 4. Memory Strategy
- **Short-term**: LangGraph checkpoint + in-graph messages
- **Long-term**: Conversation summary stored in Supabase per phone number
- **Property Knowledge**: Supabase pgvector for semantic search

### 5. Multilingual & Voice Support
- Whisper transcription for incoming voice notes
- LLM instructed to reply in Hindi/English/regional as per user
- Optional TTS reply (voice message) for better UX

## Key Prompts (All prompts will be stored in /prompts/ folder)
- system_prompt_real_estate_agent.md
- qualification_prompt.md
- property_matching_prompt.md
- booking_prompt.md

## Edge Cases Handled by Agent
- Off-topic questions
- Voice notes in regional languages
- Low confidence / hallucinations
- Calendar conflicts
- No matching properties
- Customer wants to speak to human
- Meta message template compliance
- High message volume / rate limiting

## Success Metrics for Agent
- Average response time < 4 seconds
- Qualification rate > 70%
- Booking conversion rate > 25%
- Human handoff rate < 15%
- Cost per conversation < ₹2.5

## Code Style Rules (Strict)
- Keep code **very minimal** and simple.
- No need for heavy modularization, many small files, or complex abstractions in Phase 1.
- Prefer fewer, larger files if it keeps things straightforward.
- Only create folders/files that are strictly necessary.
- Avoid over-engineering — focus on making the agent work end-to-end first.
- Prioritize readability and speed of development over clean architecture.

## Maintenance Rules
- Never delete old versions of prompts or graph definitions — comment them out or move to archive/
- Every major change to the agent graph must be documented in `AGENT_TRACKING.md`
- Before deploying, run full end-to-end test flows (buyer enquiry, seller enquiry, voice note, handoff)

**This file is the single source of truth for the AI Agent.**  
Keep it updated at all times.