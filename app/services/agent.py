"""
Minimal LangGraph agent for EstateAgent AI (Phase 1).
Refactored to support shared WhatsApp + Telegram flows with simple Supabase persistence.
"""
from __future__ import annotations

import json
import logging
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
from app.services.prompt import (
    FALLBACK_NO_LLM_DEFAULT,
    FALLBACK_NO_LLM_SUGGEST_VISIT,
    FALLBACK_RESPOND_LLM_ERROR,
    GROUNDED_REPLY_BUDGET_RELAXED_INTRO,
    GROUNDED_REPLY_DB_NUMBERS_INTRO,
    GROUNDED_REPLY_FOOTER,
    HANDOFF_USER_MESSAGE,
    NO_INVENTORY_INTRO,
    NO_INVENTORY_OUTRO,
    respond_system_content,
    triage_classifier_system_content,
    triage_human_content,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _stderr_handler = logging.StreamHandler()
    _stderr_handler.setFormatter(logging.Formatter("%(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(_stderr_handler)
logger.propagate = False

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
    refresh_property_inventory: bool = Field(
        default=False,
        description="User asked prices/details while bhk or location exists in lead; force DB re-fetch.",
    )


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    channel: str
    contact_id: str
    chat_id: str
    phone: str
    profile_name: str
    lead_info: dict[str, Any]
    properties_matched: list[dict[str, Any]]
    property_match_meta: dict[str, Any]
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


def _normalize_lead_delta_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key == "bhk" and isinstance(value, (int, float, str)):
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return value
    if key == "budget_max_inr" and isinstance(value, (int, float, str)):
        try:
            return int(float(str(value).replace(",", "").strip()))
        except (TypeError, ValueError):
            return value
    return value


def _apply_lead_delta(lead: dict[str, Any], delta: dict[str, Any] | None) -> None:
    """Merge model output: JSON null clears a key; omit key to keep prior value."""
    for key, raw in (delta or {}).items():
        value = _normalize_lead_delta_value(key, raw)
        if value is None:
            lead.pop(key, None)
        elif value != "":
            lead[key] = value


def _no_llm_triage_decision() -> TriageDecision:
    return TriageDecision(
        next_action="qualify",
        confidence=0.0,
        lead_delta={},
        human_handoff_requested=False,
        refresh_property_inventory=False,
    )


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
        if price is not None and price != "":
            bits.append(f"INR {_as_int_price(price):,}")
        lines.append(f"{idx}. " + " | ".join(bits))
    return "\n".join(lines)


def _as_int_price(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _format_grounded_property_reply(
    properties: list[dict[str, Any]],
    lead: dict[str, Any],
    *,
    budget_relaxed: bool,
) -> str:
    """Reply built only from DB rows — no LLM, no approximate prices."""
    lines: list[str] = []
    if budget_relaxed and lead.get("budget_max_inr"):
        lines.append(GROUNDED_REPLY_BUDGET_RELAXED_INTRO)
    else:
        lines.append(GROUNDED_REPLY_DB_NUMBERS_INTRO)

    for idx, item in enumerate(properties[:5], start=1):
        title = str(item.get("title") or f"Listing {idx}").strip()
        location = str(item.get("location") or "").strip()
        bhk = item.get("bhk")
        price = item.get("price_inr")
        poss = str(item.get("possession") or "").strip()
        pid = str(item.get("id") or "")[:8]
        price_txt = f"₹{_as_int_price(price):,}" if price is not None and price != "" else "price on request"
        bhk_txt = f"{int(bhk)} BHK" if bhk is not None else "BHK n/a"
        bit = f"{idx}) {title} | {location} | {bhk_txt} | {price_txt}"
        if poss:
            bit += f" | possession: {poss}"
        if pid:
            bit += f" | id: {pid}…"
        lines.append(bit)

    lines.append(GROUNDED_REPLY_FOOTER)
    return "\n".join(lines)


def _format_no_matching_inventory(lead: dict[str, Any]) -> str:
    parts = [NO_INVENTORY_INTRO]
    if lead.get("bhk"):
        parts.append(f"Filter: {lead['bhk']} BHK.")
    if lead.get("location"):
        parts.append(f"Location contains: {lead['location']}.")
    if lead.get("budget_max_inr"):
        parts.append(f"Budget cap: up to ₹{_as_int_price(lead['budget_max_inr']):,}.")
    parts.append(NO_INVENTORY_OUTRO)
    return " ".join(parts)


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
        logger.warning("db log_agent_step skipped: Supabase not configured (step=%s)", step)
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
        logger.info(
            "db agent_logs insert ok step=%s channel=%s contact_id=%s",
            step,
            channel or row.get("channel") or "",
            contact_id or row.get("contact_id") or "",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db agent_logs insert failed: %s", exc)


def get_lead_history(channel: str, contact_id: str) -> dict[str, Any]:
    client = _sb()
    if client is None:
        logger.warning("db get_lead_history skipped: Supabase not configured")
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
        logger.warning("db get_lead_history failed: %s", exc)
        return {}
    rows = response.data or []
    if rows:
        row = rows[0]
        li = row.get("lead_info") or {}
        logger.info(
            "db get_lead_history ok channel=%s contact_id=%s lead_id=%s lead_info_keys=%s",
            channel,
            contact_id,
            row.get("id"),
            sorted(li.keys()) if isinstance(li, dict) else [],
        )
        return row
    logger.info("db get_lead_history miss channel=%s contact_id=%s (new lead)", channel, contact_id)
    return {}


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
        logger.warning("db save_lead_context skipped: Supabase not configured")
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
        li = lead_info or {}
        logger.info(
            "db leads upsert ok channel=%s contact_id=%s lead_info_keys=%s handoff=%s",
            channel,
            contact_id,
            sorted(li.keys()) if isinstance(li, dict) else [],
            human_handoff_requested,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db leads upsert failed: %s", exc)


def fetch_properties(
    _query: str,
    filters: dict[str, Any],
    *,
    relax_budget: bool = False,
) -> list[dict[str, Any]]:
    client = _sb()
    if client is None:
        logger.warning("db fetch_properties skipped: Supabase not configured")
        return []

    lead = dict(filters.get("lead") or {})
    try:
        request = (
            client.table("properties")
            .select("id,title,location,price_inr,bhk,possession,metadata")
            .limit(5)
        )
        if lead.get("bhk"):
            request = request.eq("bhk", int(lead["bhk"]))
        if lead.get("budget_max_inr") and not relax_budget:
            request = request.lte("price_inr", int(lead["budget_max_inr"]))
        if lead.get("location"):
            request = request.ilike("location", f"%{lead['location']}%")
        response = request.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("db fetch_properties failed: %s", exc)
        log_agent_step(
            lead.get("phone"),
            "tool_fetch_properties_error",
            {"query": _query, "error": str(exc)},
            channel=filters.get("channel", ""),
            contact_id=filters.get("contact_id", ""),
        )
        return []
    data = response.data or []
    logger.info(
        "db fetch_properties ok rows=%s relax_budget=%s bhk=%s location=%s budget_max_inr=%s",
        len(data),
        relax_budget,
        lead.get("bhk"),
        lead.get("location"),
        lead.get("budget_max_inr"),
    )
    return data


def check_calendar_availability(_preferred_times: list[str]) -> list[str]:
    return []


def triage_node(state: AgentState) -> dict[str, Any]:
    phone = state.get("phone")
    channel = state.get("channel", "")
    contact_id = state.get("contact_id", "")
    last = state["messages"][-1].content if state.get("messages") else ""
    text = last if isinstance(last, str) else str(last)
    existing_lead = dict(state.get("lead_info") or {})
    llm = _chat()

    if llm is None:
        logger.warning("triage: no LLM configured (GROQ_API_KEY missing); using empty triage decision")
        decision = _no_llm_triage_decision()
        mode = "no_llm"
    else:
        try:
            structured = llm.with_structured_output(TriageDecision)
            decision = structured.invoke(
                [
                    SystemMessage(content=triage_classifier_system_content()),
                    HumanMessage(
                        content=triage_human_content(
                            channel=channel,
                            profile_name=str(state.get("profile_name") or ""),
                            existing_lead=existing_lead,
                            latest_user_message=text,
                        )
                    ),
                ]
            )
            mode = "llm"
        except Exception as exc:  # noqa: BLE001
            decision = _no_llm_triage_decision()
            mode = "no_llm_after_error"
            log_agent_step(
                phone,
                "triage_error",
                {"error": str(exc)},
                channel=channel,
                contact_id=contact_id,
            )

    lead = dict(existing_lead)
    _apply_lead_delta(lead, decision.lead_delta)

    next_action = decision.next_action
    force_fetch = (
        not decision.human_handoff_requested
        and next_action != "match_properties"
        and bool(decision.refresh_property_inventory)
    )
    if force_fetch:
        next_action = "match_properties"

    properties: list[dict[str, Any]] = []
    budget_relaxed = False
    if next_action == "match_properties":
        properties = fetch_properties(
            text,
            {"lead": lead, "channel": channel, "contact_id": contact_id},
        )
        if not properties and lead.get("budget_max_inr"):
            relaxed = fetch_properties(
                text,
                {"lead": lead, "channel": channel, "contact_id": contact_id},
                relax_budget=True,
            )
            if relaxed:
                properties = relaxed
                budget_relaxed = True
        log_agent_step(
            phone,
            "tool_fetch_properties",
            {
                "count": len(properties),
                "location": lead.get("location"),
                "bhk": lead.get("bhk"),
                "forced": force_fetch,
                "budget_relaxed": budget_relaxed,
            },
            channel=channel,
            contact_id=contact_id,
        )

    log_agent_step(
        phone,
        "triage",
        {"mode": mode, "decision": decision.model_dump(), "next_action_resolved": next_action},
        channel=channel,
        contact_id=contact_id,
    )

    match_meta: dict[str, Any] = {}
    if next_action == "match_properties":
        match_meta["budget_relaxed"] = budget_relaxed

    return {
        "lead_info": lead,
        "next_action": next_action,
        "confidence": decision.confidence,
        "human_handoff_requested": decision.human_handoff_requested,
        "properties_matched": properties,
        "property_match_meta": match_meta,
    }


def respond_node(state: AgentState) -> dict[str, Any]:
    phone = state.get("phone")
    channel = state.get("channel", "")
    contact_id = state.get("contact_id", "")
    slots = check_calendar_availability([])
    history = get_lead_history(channel, contact_id)
    properties = state.get("properties_matched") or []
    pm_meta = state.get("property_match_meta") or {}
    ctx = {
        "next_action": state.get("next_action"),
        "confidence": state.get("confidence"),
        "lead_info": state.get("lead_info") or {},
        "properties_matched": properties,
        "property_match_meta": pm_meta,
        "calendar_slots": slots,
        "human_handoff_requested": state.get("human_handoff_requested"),
        "lead_history": {
            "summary": history.get("summary"),
            "lead_info": history.get("lead_info"),
        },
    }

    if state.get("human_handoff_requested"):
        message = HANDOFF_USER_MESSAGE
        log_agent_step(
            phone,
            "respond",
            {"mode": "handoff", "ctx": ctx},
            channel=channel,
            contact_id=contact_id,
        )
        return {"messages": [AIMessage(content=message)], "calendar_slots": slots}

    if state.get("next_action") == "match_properties":
        lead = state.get("lead_info") or {}
        if properties:
            message = _format_grounded_property_reply(
                properties,
                lead,
                budget_relaxed=bool(pm_meta.get("budget_relaxed")),
            )
        else:
            message = _format_no_matching_inventory(lead)
        log_agent_step(
            phone,
            "respond",
            {"mode": "grounded_inventory", "ctx": ctx},
            channel=channel,
            contact_id=contact_id,
        )
        return {"messages": [AIMessage(content=message)], "calendar_slots": slots}

    llm = _chat()
    if llm is None:
        if state.get("next_action") == "suggest_visit":
            message = FALLBACK_NO_LLM_SUGGEST_VISIT
        else:
            message = FALLBACK_NO_LLM_DEFAULT
        log_agent_step(
            phone,
            "respond",
            {"mode": "fallback", "ctx": ctx},
            channel=channel,
            contact_id=contact_id,
        )
        return {"messages": [AIMessage(content=message)], "calendar_slots": slots}

    prompt = SystemMessage(content=respond_system_content())
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
            "messages": [AIMessage(content=FALLBACK_RESPOND_LLM_ERROR)],
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
