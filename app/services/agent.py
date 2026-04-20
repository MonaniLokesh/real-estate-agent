"""
Minimal LangGraph agent for EstateAgent AI (Phase 1).
Refactored to support shared WhatsApp + Telegram flows with simple Supabase persistence.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Annotated, Any, Literal, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from app.core.config import get_settings

SYSTEM_REAL_ESTATE = """You are EstateAgent AI, a professional real estate assistant for an Indian broker.
You qualify buyers and sellers, never invent property prices or addresses, and offer a human handoff when unsure.
Reply in the user's language, keep messages concise, and optimize for WhatsApp/Telegram chat."""

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
    channel: str
    contact_id: str
    chat_id: str
    phone: str
    profile_name: str
    lead_info: dict[str, Any]
    properties_matched: list[dict[str, Any]]
    calendar_slots: list[str]
    next_action: str
    confidence: float
    summary: str
    human_handoff_requested: bool


_supabase = None
_graph = None


def _settings():
    return get_settings()


def _sb():
    global _supabase
    if _supabase is not None:
        return _supabase

    settings = _settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None

    from supabase import create_client

    _supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _supabase


def _chat() -> Optional[BaseChatModel]:
    settings = _settings()
    if not settings.groq_api_key:
        return None
    return ChatOpenAI(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        temperature=settings.groq_temperature,
    )


def _extract_budget_max_inr(text: str) -> Optional[int]:
    cleaned = text.lower().replace(",", "").strip()
    priority_patterns = [
        r"(?:under|below|max|budget|upto|up to)\s*(\d+(?:\.\d+)?)\s*(cr|crore|crores|lakh|lakhs|lac|lacs)",
        r"(\d+(?:\.\d+)?)\s*(cr|crore|crores|lakh|lakhs|lac|lacs)",
        r"(?:under|below|max|budget|upto|up to)\s*(\d{6,})",
    ]
    for pattern in priority_patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        value = float(match.group(1))
        unit = (match.group(2) or "").lower() if len(match.groups()) > 1 else ""
        if unit in {"cr", "crore", "crores"}:
            return int(value * 10_000_000)
        if unit in {"lakh", "lakhs", "lac", "lacs"}:
            return int(value * 100_000)
        if value >= 1_000_000:
            return int(value)
    return None


def _extract_location(text: str) -> str:
    match = re.search(r"\b(?:in|at|near)\s+([a-z][a-z\s-]{2,40})", text.lower())
    if not match:
        return ""
    location = re.split(r"\b(?:under|below|for|with|and|budget)\b", match.group(1))[0]
    return location.strip(" ,.-").title()


def _extract_bhk(text: str) -> Optional[int]:
    match = re.search(r"\b(\d+)\s*bhk\b", text.lower())
    return int(match.group(1)) if match else None


def _extract_lead_delta(text: str, existing: dict[str, Any]) -> dict[str, Any]:
    lowered = text.lower()
    lead_delta: dict[str, Any] = {}

    bhk = _extract_bhk(text)
    if bhk is not None:
        lead_delta["bhk"] = bhk

    budget_max_inr = _extract_budget_max_inr(text)
    if budget_max_inr is not None:
        lead_delta["budget_max_inr"] = budget_max_inr

    location = _extract_location(text)
    if location:
        lead_delta["location"] = location

    if any(word in lowered for word in ("buy", "buyer", "purchase", "looking for", "rent")):
        lead_delta["intent"] = "buyer"
    if any(word in lowered for word in ("sell", "seller", "listing my property")):
        lead_delta["intent"] = "seller"

    if any(word in lowered for word in ("immediate", "this week", "asap", "urgent")):
        lead_delta["timeline"] = "immediate"

    if "budget_max_inr" not in lead_delta and existing.get("budget_max_inr"):
        lead_delta["budget_max_inr"] = existing["budget_max_inr"]

    return lead_delta


def _build_summary(channel: str, profile_name: str, lead_info: dict[str, Any], next_action: str) -> str:
    parts: list[str] = []
    if profile_name:
        parts.append(f"Lead: {profile_name}")
    parts.append(f"Channel: {channel}")
    if lead_info.get("intent"):
        parts.append(f"Intent: {lead_info['intent']}")
    if lead_info.get("location"):
        parts.append(f"Location: {lead_info['location']}")
    if lead_info.get("bhk"):
        parts.append(f"BHK: {lead_info['bhk']}")
    if lead_info.get("budget_max_inr"):
        parts.append(f"Budget up to INR {lead_info['budget_max_inr']}")
    parts.append(f"Next action: {next_action}")
    return " | ".join(parts)


def _format_property_preview(properties: list[dict[str, Any]]) -> str:
    if not properties:
        return ""
    lines: list[str] = []
    for idx, item in enumerate(properties[:3], start=1):
        title = item.get("title") or f"Property {idx}"
        location = item.get("location") or "location on request"
        bhk = item.get("bhk")
        price = item.get("price_inr")
        bits = [title, location]
        if bhk:
            bits.append(f"{bhk} BHK")
        if price:
            bits.append(f"INR {int(price):,}")
        lines.append(f"{idx}. " + " | ".join(bits))
    return "\n".join(lines)


def log_agent_step(
    phone: Optional[str],
    step: str,
    payload: dict[str, Any],
    *,
    channel: str = "",
    contact_id: str = "",
) -> None:
    client = _sb()
    if client is None:
        return

    row = {
        "phone": phone,
        "channel": channel or None,
        "contact_id": contact_id or None,
        "step": step,
        "payload": payload,
    }
    try:
        client.table("agent_logs").insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        print("agent_logs insert failed:", exc)


def get_lead_history(channel: str, contact_id: str) -> dict[str, Any]:
    client = _sb()
    if client is None:
        return {}
    try:
        response = (
            client.table("leads")
            .select("*")
            .eq("channel", channel)
            .eq("contact_id", contact_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        print("lead lookup failed:", exc)
        return {}
    rows = response.data or []
    return rows[0] if rows else {}


def save_lead_context(
    *,
    channel: str,
    contact_id: str,
    chat_id: str,
    phone: str,
    profile_name: str,
    lead_info: dict[str, Any],
    summary: str,
    human_handoff_requested: bool,
) -> None:
    client = _sb()
    if client is None:
        return

    row = {
        "channel": channel,
        "contact_id": contact_id,
        "chat_id": chat_id or None,
        "phone": phone or None,
        "display_name": profile_name or None,
        "lead_info": lead_info or {},
        "summary": summary or None,
        "human_handoff_requested": human_handoff_requested,
    }
    try:
        client.table("leads").upsert(row, on_conflict="channel,contact_id").execute()
    except Exception as exc:  # noqa: BLE001
        print("lead upsert failed:", exc)


def fetch_properties(query: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    client = _sb()
    if client is None:
        return []

    lead = filters.get("lead") or {}
    try:
        request = (
            client.table("properties")
            .select("id,title,location,price_inr,bhk,possession,metadata")
            .limit(5)
        )
        if lead.get("bhk"):
            request = request.eq("bhk", int(lead["bhk"]))
        if lead.get("budget_max_inr"):
            request = request.lte("price_inr", int(lead["budget_max_inr"]))
        if lead.get("location"):
            request = request.ilike("location", f"%{lead['location']}%")
        response = request.execute()
    except Exception as exc:  # noqa: BLE001
        print("property lookup failed:", exc)
        log_agent_step(
            lead.get("phone"),
            "tool_fetch_properties_error",
            {"query": query, "error": str(exc)},
            channel=filters.get("channel", ""),
            contact_id=filters.get("contact_id", ""),
        )
        return []
    return response.data or []


def check_calendar_availability(_preferred_times: list[str]) -> list[str]:
    return []


def _heuristic_triage(text: str, existing: dict[str, Any]) -> TriageDecision:
    lowered = text.lower()
    lead_delta = _extract_lead_delta(text, existing)
    if any(x in lowered for x in ("human", "agent", "call me", "broker", "बात", "इंसान")):
        return TriageDecision(
            next_action="handoff",
            confidence=0.4,
            lead_delta=lead_delta,
            human_handoff_requested=True,
        )
    if any(x in lowered for x in ("visit", "site visit", "देख", "मुलाकात", "schedule")):
        return TriageDecision(next_action="suggest_visit", confidence=0.6, lead_delta=lead_delta)
    if any(x in lowered for x in ("flat", "bhk", "property", "budget", "house", "घर", "प्रॉपर्टी")):
        return TriageDecision(next_action="match_properties", confidence=0.55, lead_delta=lead_delta)
    return TriageDecision(next_action="qualify", confidence=0.45, lead_delta=lead_delta)


def triage_node(state: AgentState) -> dict[str, Any]:
    phone = state.get("phone")
    channel = state.get("channel", "")
    contact_id = state.get("contact_id", "")
    last = state["messages"][-1].content if state.get("messages") else ""
    text = last if isinstance(last, str) else str(last)
    existing_lead = dict(state.get("lead_info") or {})
    llm = _chat()

    if llm is None:
        decision = _heuristic_triage(text, existing_lead)
        mode = "heuristic"
    else:
        try:
            structured = llm.with_structured_output(TriageDecision)
            decision = structured.invoke(
                [
                    SystemMessage(content=SYSTEM_REAL_ESTATE + " Classify the user and fill fields."),
                    HumanMessage(
                        content=(
                            f"Channel: {channel}\n"
                            f"Profile name: {state.get('profile_name') or ''}\n"
                            f"Existing lead_info JSON: {json.dumps(existing_lead, ensure_ascii=False)}\n"
                            f"Latest user message: {text}\n"
                            "Return next_action, confidence, lead_delta (only new or changed keys), "
                            "human_handoff_requested."
                        )
                    ),
                ]
            )
            mode = "llm"
        except Exception as exc:  # noqa: BLE001
            decision = _heuristic_triage(text, existing_lead)
            mode = "heuristic_after_llm_error"
            log_agent_step(
                phone,
                "triage_error",
                {"error": str(exc)},
                channel=channel,
                contact_id=contact_id,
            )

    lead = dict(existing_lead)
    for key, value in (decision.lead_delta or {}).items():
        if value is not None and value != "":
            lead[key] = value

    properties: list[dict[str, Any]] = []
    if decision.next_action == "match_properties":
        properties = fetch_properties(
            text,
            {"lead": lead, "channel": channel, "contact_id": contact_id},
        )
        log_agent_step(
            phone,
            "tool_fetch_properties",
            {"count": len(properties), "location": lead.get("location"), "bhk": lead.get("bhk")},
            channel=channel,
            contact_id=contact_id,
        )

    log_agent_step(
        phone,
        "triage",
        {"mode": mode, "decision": decision.model_dump()},
        channel=channel,
        contact_id=contact_id,
    )

    return {
        "lead_info": lead,
        "next_action": decision.next_action,
        "confidence": decision.confidence,
        "human_handoff_requested": decision.human_handoff_requested,
        "properties_matched": properties,
    }


def respond_node(state: AgentState) -> dict[str, Any]:
    phone = state.get("phone")
    channel = state.get("channel", "")
    contact_id = state.get("contact_id", "")
    slots = check_calendar_availability([])
    history = get_lead_history(channel, contact_id)
    properties = state.get("properties_matched") or []
    ctx = {
        "next_action": state.get("next_action"),
        "confidence": state.get("confidence"),
        "lead_info": state.get("lead_info") or {},
        "properties_matched": properties,
        "calendar_slots": slots,
        "human_handoff_requested": state.get("human_handoff_requested"),
        "lead_history": {
            "summary": history.get("summary"),
            "lead_info": history.get("lead_info"),
        },
    }

    llm = _chat()
    if llm is None:
        if state.get("human_handoff_requested"):
            message = "I’m connecting you with a broker now. They’ll follow up shortly."
        elif state.get("next_action") == "match_properties" and properties:
            message = (
                "I found a few matching options:\n"
                f"{_format_property_preview(properties)}\n"
                "Tell me which one you want details or a site visit for."
            )
        elif state.get("next_action") == "match_properties":
            message = (
                "I’m checking live inventory. Please confirm your preferred micro-location "
                "and exact budget band so I can narrow the options."
            )
        elif state.get("next_action") == "suggest_visit":
            message = "Please share 2 or 3 preferred time slots this week for a site visit."
        else:
            message = (
                "Please share your budget, preferred location, BHK, and whether you want to buy or sell."
            )
        log_agent_step(
            phone,
            "respond",
            {"mode": "fallback", "ctx": ctx},
            channel=channel,
            contact_id=contact_id,
        )
        return {"messages": [AIMessage(content=message)], "calendar_slots": slots}

    prompt = SystemMessage(
        content=SYSTEM_REAL_ESTATE
        + " Generate the next chat reply."
        + " If properties_matched is empty and the user wants listings, ask one clarifying question."
        + " If properties_matched is present, mention up to three options briefly."
        + " If human_handoff_requested is true, confirm broker handoff."
    )
    human = HumanMessage(content="Context JSON:\n" + json.dumps(ctx, ensure_ascii=False))
    try:
        output = llm.invoke([prompt, *state.get("messages", [])[-6:], human])
        log_agent_step(
            phone,
            "respond",
            {"mode": "llm", "ctx": ctx},
            channel=channel,
            contact_id=contact_id,
        )
        return {"messages": [output], "calendar_slots": slots}
    except Exception as exc:  # noqa: BLE001
        log_agent_step(
            phone,
            "respond_error",
            {"error": str(exc)},
            channel=channel,
            contact_id=contact_id,
        )
        return {
            "messages": [
                AIMessage(
                    content="I have your requirement. Please share your budget and preferred location so I can help."
                )
            ],
            "calendar_slots": slots,
        }


def summarize_node(state: AgentState) -> dict[str, Any]:
    summary = _build_summary(
        state.get("channel", ""),
        state.get("profile_name", ""),
        state.get("lead_info") or {},
        state.get("next_action", "qualify"),
    )
    log_agent_step(
        state.get("phone"),
        "summarize",
        {"summary": summary},
        channel=state.get("channel", ""),
        contact_id=state.get("contact_id", ""),
    )
    return {"summary": summary}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("triage", triage_node)
    graph.add_node("respond", respond_node)
    graph.add_node("summarize", summarize_node)
    graph.add_edge(START, "triage")
    graph.add_edge("triage", "respond")
    graph.add_edge("respond", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile(checkpointer=MemorySaver())


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_turn(
    *,
    channel: str,
    contact_id: str,
    user_text: str,
    chat_id: str = "",
    phone: str = "",
    profile_name: str = "",
) -> str:
    graph = get_graph()
    thread_id = f"{channel}:{contact_id or uuid.uuid4()}"
    history = get_lead_history(channel, contact_id)
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    initial_state: AgentState = {
        "messages": [HumanMessage(content=user_text)],
        "channel": channel,
        "contact_id": contact_id,
        "chat_id": chat_id or str(history.get("chat_id") or contact_id),
        "phone": phone or str(history.get("phone") or ""),
        "profile_name": profile_name or str(history.get("display_name") or ""),
        "lead_info": dict(history.get("lead_info") or {}),
        "summary": str(history.get("summary") or ""),
        "human_handoff_requested": bool(history.get("human_handoff_requested") or False),
    }
    output = graph.invoke(initial_state, config)
    messages = output.get("messages") or []
    last_ai = next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)
    reply = (
        last_ai.content
        if last_ai is not None and isinstance(last_ai.content, str)
        else str(last_ai.content if last_ai is not None else "")
    ).strip()

    save_lead_context(
        channel=channel,
        contact_id=contact_id,
        chat_id=output.get("chat_id") or initial_state["chat_id"],
        phone=output.get("phone") or initial_state["phone"],
        profile_name=output.get("profile_name") or initial_state["profile_name"],
        lead_info=output.get("lead_info") or initial_state.get("lead_info") or {},
        summary=output.get("summary") or "",
        human_handoff_requested=bool(output.get("human_handoff_requested")),
    )

    return reply
