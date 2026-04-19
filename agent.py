"""
Minimal LangGraph agent for EstateAgent AI (Phase 1).
Single file: state, stub tools, triage + reply nodes, optional Supabase logging.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Annotated, Any, Literal, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# --- Prompts (inline for Phase 1 minimal layout) ---
SYSTEM_REAL_ESTATE = """You are EstateAgent AI, a professional WhatsApp assistant for an Indian real estate broker.
You qualify buyers/sellers, never invent property prices or addresses, and offer a human handoff when unsure.
Reply in the user's language (Hindi/English mix is common). Be concise and helpful."""

NEXT_ACTION_LITERAL = Literal[
    "qualify",
    "match_properties",
    "suggest_visit",
    "book_visit",
    "follow_up",
    "close_deal",
    "handoff",
]


class TriageDecision(BaseModel):
    next_action: NEXT_ACTION_LITERAL
    confidence: float = Field(ge=0.0, le=1.0)
    lead_delta: dict[str, Any] = Field(default_factory=dict)
    human_handoff_requested: bool = False


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    phone: str
    lead_info: dict[str, Any]
    properties_matched: list[Any]
    calendar_slots: list[Any]
    next_action: str
    confidence: float
    summary: str
    human_handoff_requested: bool


# --- Stub tools (replace with Supabase + APIs later) ---


def fetch_properties(_query: str, _filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Grounding hook: later query `properties` + pgvector; never hallucinate listings."""
    return []


def check_calendar_availability(_preferred_times: list[str]) -> list[str]:
    return []


def get_lead_history(_phone: str) -> dict[str, Any]:
    return {}


_supabase = None


def _sb():
    global _supabase
    if _supabase is not None:
        return _supabase
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    from supabase import create_client

    _supabase = create_client(url, key)
    return _supabase


def log_agent_step(phone: Optional[str], step: str, payload: dict[str, Any]) -> None:
    client = _sb()
    if client is None:
        return
    row = {"phone": phone, "step": step, "payload": payload}
    try:
        client.table("agent_logs").insert(row).execute()
    except Exception as exc:  # noqa: BLE001 — never break the chat path
        print("agent_logs insert failed:", exc)


GROQ_OPENAI_BASE = "https://api.groq.com/openai/v1"


def _chat() -> Optional[BaseChatModel]:
    """Groq exposes an OpenAI-compatible API; same client, different base URL + key."""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    return ChatOpenAI(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        api_key=key,
        base_url=os.getenv("GROQ_BASE_URL", GROQ_OPENAI_BASE),
        temperature=float(os.getenv("GROQ_TEMPERATURE", "0.2")),
    )


def _heuristic_triage(text: str) -> TriageDecision:
    t = text.lower()
    if any(x in t for x in ("human", "agent", "call me", "बात", "इंसान")):
        return TriageDecision(next_action="handoff", confidence=0.4, human_handoff_requested=True)
    if any(x in t for x in ("visit", "site visit", "देख", "मुलाकात")):
        return TriageDecision(next_action="suggest_visit", confidence=0.55, lead_delta={})
    if any(x in t for x in ("flat", "bhk", "property", "budget", "घर", "प्रॉपर्टी")):
        return TriageDecision(next_action="match_properties", confidence=0.5, lead_delta={})
    return TriageDecision(next_action="qualify", confidence=0.45, lead_delta={})


def triage_node(state: AgentState) -> dict[str, Any]:
    phone = state.get("phone")
    last = state["messages"][-1].content if state.get("messages") else ""
    text = last if isinstance(last, str) else str(last)
    llm = _chat()
    if llm is None:
        decision = _heuristic_triage(text)
        log_agent_step(phone, "triage", {"mode": "heuristic", "decision": decision.model_dump()})
    else:
        structured = llm.with_structured_output(TriageDecision)
        decision = structured.invoke(
            [
                SystemMessage(content=SYSTEM_REAL_ESTATE + " Classify the user and fill fields."),
                HumanMessage(
                    content=(
                        f"User phone (context only): {phone}\n"
                        f"Existing lead_info JSON: {json.dumps(state.get('lead_info') or {}, ensure_ascii=False)}\n"
                        f"Latest user message: {text}\n"
                        "Return next_action, confidence, lead_delta (only new/changed keys), human_handoff_requested."
                    )
                ),
            ]
        )
        log_agent_step(phone, "triage", {"mode": "llm", "decision": decision.model_dump()})

    lead = dict(state.get("lead_info") or {})
    for k, v in (decision.lead_delta or {}).items():
        if v is not None:
            lead[k] = v

    props: list[Any] = list(state.get("properties_matched") or [])
    if decision.next_action == "match_properties":
        props = fetch_properties(text, {"lead": lead})
        log_agent_step(phone, "tool_fetch_properties", {"count": len(props)})

    return {
        "lead_info": lead,
        "next_action": decision.next_action,
        "confidence": decision.confidence,
        "human_handoff_requested": decision.human_handoff_requested,
        "properties_matched": props,
    }


def respond_node(state: AgentState) -> dict[str, Any]:
    phone = state.get("phone")
    slots = check_calendar_availability([])
    history = get_lead_history(phone or "")
    ctx = {
        "next_action": state.get("next_action"),
        "confidence": state.get("confidence"),
        "lead_info": state.get("lead_info") or {},
        "properties_matched": state.get("properties_matched") or [],
        "calendar_slots": slots,
        "human_handoff_requested": state.get("human_handoff_requested"),
        "lead_history": history,
    }
    llm = _chat()
    if llm is None:
        if state.get("human_handoff_requested"):
            msg = (
                "Thanks for your message. Our assistant is warming up (set GROQ_API_KEY). "
                "A broker will reply shortly."
            )
        elif state.get("next_action") == "match_properties":
            msg = (
                "Thanks — I am checking live inventory for your criteria. "
                "Please confirm preferred micro-location and exact budget band."
            )
        elif state.get("next_action") == "suggest_visit":
            msg = "Noted. Please share 2–3 preferred time windows this week for a site visit."
        else:
            msg = "Hi! Please share your budget, preferred location, and BHK, and whether you are buying or selling."
        log_agent_step(phone, "respond", {"mode": "fallback", "ctx": ctx})
        return {"messages": [AIMessage(content=msg)], "calendar_slots": slots}

    prompt = SystemMessage(
        content=SYSTEM_REAL_ESTATE
        + " Generate the next WhatsApp reply. If properties_matched is empty and user asked for listings, "
        "say you are checking inventory and ask one clarifying question. "
        "If human_handoff_requested, say you are connecting them to the broker."
    )
    human = HumanMessage(
        content="Context JSON:\n" + json.dumps(ctx, ensure_ascii=False),
    )
    out = llm.invoke([prompt, *state.get("messages", [])[-6:], human])
    log_agent_step(phone, "respond", {"mode": "llm", "ctx": ctx})
    return {"messages": [out], "calendar_slots": slots}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("triage", triage_node)
    g.add_node("respond", respond_node)
    g.add_edge(START, "triage")
    g.add_edge("triage", "respond")
    g.add_edge("respond", END)
    return g.compile(checkpointer=MemorySaver())


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_turn(phone: str, user_text: str) -> str:
    """Run one user message through the graph; returns assistant text."""
    graph = get_graph()
    tid = phone or str(uuid.uuid4())
    cfg: dict[str, Any] = {"configurable": {"thread_id": tid}}
    # Do not pass lead_info each turn — let the checkpointer carry it forward.
    out = graph.invoke({"messages": [HumanMessage(content=user_text)], "phone": phone}, cfg)
    msgs = out.get("messages") or []
    last_ai = next((m for m in reversed(msgs) if isinstance(m, AIMessage)), None)
    return (last_ai.content if last_ai and isinstance(last_ai.content, str) else str(last_ai.content if last_ai else "")).strip()
