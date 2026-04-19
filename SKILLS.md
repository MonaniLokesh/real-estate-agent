# EstateAgent AI - Skills & Capabilities Inventory

**Project:** EstateAgent AI – WhatsApp Real Estate Agent SaaS  
**Purpose:** This file lists all technical and domain skills the AI coding agent (Cursor) must use while building this product.  
**Maintainer:** Lokesh

## Core Technical Skills Required

### 1. LangGraph & Agentic Architecture
- Building stateful multi-agent graphs with LangGraph 0.2+
- Defining nodes, edges, conditional routing, and checkpoints
- Implementing tool calling with structured outputs
- Memory management (short-term + long-term summarization)
- Error handling and retry logic inside graph

### 2. LangChain Ecosystem
- Prompt templates and few-shot examples
- Output parsers (Pydantic)
- Tool creation and binding to LLM
- RAG (Retrieval Augmented Generation) with pgvector

### 3. Backend Development
- FastAPI (routes, dependencies, background tasks, webhooks)
- Supabase (Auth, Postgres, pgvector, Storage, RLS)
- Python 3.12 best practices (type hints, async where needed)

### 4. WhatsApp Integration
- Official BSP webhook handling (Interakt / WATI)
- Sending text, buttons, images, voice messages via BSP API
- Handling message templates and compliance
- Media download and voice transcription

### 5. Frontend (React Native / Expo)
- Expo 52 + React Native Web (mobile + web support)
- Expo Router for navigation
- State management (Zustand or TanStack Query)
- Clean, simple UI for property management and analytics

### 6. Database & Data Modeling
- Supabase schema design
- Row Level Security (RLS) policies
- pgvector for property semantic search
- Proper indexing for fast queries

### 7. Integrations
- Google Calendar / Cal.com API
- Razorpay payment links
- Stripe for SaaS subscription
- Whisper + TTS (ElevenLabs or Google)

### 8. Observability & Reliability
- Logging every agent decision and LLM call
- LangSmith or custom logging table
- Rate limiting and cost control
- Comprehensive error handling and user-friendly fallbacks

## Domain Skills (Real Estate + India Context)
- Understanding of Indian real estate buying/selling process
- Qualification questions (budget, location, BHK, timeline, possession)
- Handling buyer vs seller enquiries differently
- GST invoice generation basics
- UPI / Razorpay payment flows
- Multilingual communication (Hindi + English priority)
- Voice note preference in Indian market

## Development Best Practices (Must Follow)
- All changes must be logged in `AGENT_TRACKING.md`
- Keep prompts, system instructions, and graph definitions clean and versioned
- Write clear docstrings and comments in code
- Prioritize reliability over fancy features in Phase 1
- Optimize for low latency and low API cost
- Make the agent feel natural and helpful, never robotic

## Non-Negotiable Rules for Cursor / Any AI Agent
1. Before making any significant change, read `AGENT.md` and `SKILLS.md` fully.
2. After every meaningful task (new node, new tool, new screen, schema change), update `AGENT_TRACKING.md` with:
   - Date/Time
   - Files changed
   - Summary of changes
   - New edge cases found
   - Testing notes
3. Never break the agent’s ability to handle basic buyer/seller flows.
4. Always ground property information in the database (no hallucination on prices/locations).
5. Keep the React Native app simple, clean, and mobile-first.

## Tracking Document Reminder
**Central file:** `AGENT_TRACKING.md`

This file must stay up-to-date as the single history of all development decisions and changes.