"""
Chat model + one DB tool (full `properties` table, no filters).
Uses a small tool loop instead of AgentExecutor: Groq can return tool_calls with args=null,
which breaks LangChain's ToolsAgentOutputParser used by AgentExecutor.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.services.prompt import FALLBACK_LLM_ERROR, FALLBACK_NO_LLM, agent_system_prompt
from app.services.tools import get_supabase_client, make_listings_tool

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(h)
logger.propagate = False

_MAX_TOOL_ROUNDS = 8
_histories: dict[str, list[BaseMessage]] = {}


def _fix_null_tool_args(msg: AIMessage) -> AIMessage:
    tcs = getattr(msg, "tool_calls", None) or []
    if not tcs:
        return msg
    new_calls: list[Any] = []
    changed = False
    for tc in tcs:
        if isinstance(tc, dict):
            if tc.get("args") is None:
                new_calls.append({**tc, "args": {}})
                changed = True
            else:
                new_calls.append(tc)
        else:
            new_calls.append(tc)
    if not changed:
        return msg
    return msg.model_copy(update={"tool_calls": new_calls})


def _settings():
    return get_settings()


def _chat() -> Optional[BaseChatModel]:
    s = _settings()
    if not s.groq_api_key:
        return None
    return ChatOpenAI(
        model=s.groq_model,
        api_key=s.groq_api_key,
        base_url=s.groq_base_url,
        temperature=s.groq_temperature,
    )


def log_agent_step(
    phone: Optional[str],
    step: str,
    payload: dict[str, Any],
    *,
    channel: str = "",
    contact_id: str = "",
) -> None:
    client = get_supabase_client()
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
        logger.info("db agent_logs insert ok step=%s channel=%s contact_id=%s", step, channel, contact_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("db agent_logs insert failed: %s", exc)


def get_lead_history(channel: str, contact_id: str) -> dict[str, Any]:
    client = get_supabase_client()
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
    except Exception as exc:
        logger.warning("db get_lead_history failed: %s", exc)
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
    client = get_supabase_client()
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
        logger.warning("db leads upsert failed: %s", exc)


def _final_text(msg: AIMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _run_tool_loop(llm: BaseChatModel, messages: list[BaseMessage], tools: list[Any]) -> str:
    llm_tools = llm.bind_tools(tools)
    by_name = {t.name: t for t in tools}
    for _ in range(_MAX_TOOL_ROUNDS):
        raw = llm_tools.invoke(messages)
        ai = _fix_null_tool_args(raw) if isinstance(raw, AIMessage) else raw
        if not isinstance(ai, AIMessage):
            messages.append(ai)
            continue
        messages.append(ai)
        calls = getattr(ai, "tool_calls", None) or []
        if not calls:
            return _final_text(ai) or FALLBACK_LLM_ERROR
        for call in calls:
            name = call["name"]
            args = call.get("args") or {}
            tid = call.get("id") or ""
            runner = by_name.get(name)
            if runner is None:
                out = json.dumps({"error": f"unknown tool {name!r}"})
            else:
                try:
                    out = runner.invoke(args)
                except Exception as exc:  # noqa: BLE001
                    out = json.dumps({"error": str(exc)})
            if not isinstance(out, str):
                out = json.dumps(out, ensure_ascii=False)
            messages.append(ToolMessage(content=out, tool_call_id=tid))
    return FALLBACK_LLM_ERROR


def run_turn(
    *,
    channel: str,
    contact_id: str,
    user_text: str,
    chat_id: str = "",
    phone: str = "",
    profile_name: str = "",
) -> str:
    history = get_lead_history(channel, contact_id)
    lead_info = dict(history.get("lead_info") or {})
    lead_json = json.dumps(
        {
            "lead_info": lead_info,
            "crm_summary": history.get("summary"),
            "display_name": profile_name or history.get("display_name"),
        },
        ensure_ascii=False,
    )
    system = agent_system_prompt(lead_context_json=lead_json)
    llm = _chat()
    thread_key = f"{channel}:{contact_id}"
    prior = list(_histories.get(thread_key, []))

    if llm is None:
        log_agent_step(phone or "", "agent_no_llm", {}, channel=channel, contact_id=contact_id)
        reply = FALLBACK_NO_LLM
    else:
        tools = make_listings_tool(
            channel=channel,
            contact_id=contact_id,
            phone=phone or str(history.get("phone") or ""),
            log_step=log_agent_step,
        )
        messages: list[BaseMessage] = [SystemMessage(content=system), *prior, HumanMessage(content=user_text)]
        try:
            reply = _run_tool_loop(llm, messages, tools)
            log_agent_step(
                phone or str(history.get("phone") or ""),
                "agent_turn_ok",
                {"preview": reply[:240]},
                channel=channel,
                contact_id=contact_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("agent turn failed: %s", exc)
            log_agent_step(
                phone or str(history.get("phone") or ""),
                "agent_turn_error",
                {"error": str(exc)},
                channel=channel,
                contact_id=contact_id,
            )
            reply = FALLBACK_LLM_ERROR

    if llm is not None:
        next_hist = prior + [HumanMessage(content=user_text), AIMessage(content=reply)]
        _histories[thread_key] = next_hist[-24:]

    save_lead_context(
        channel=channel,
        contact_id=contact_id,
        chat_id=chat_id or str(history.get("chat_id") or contact_id),
        phone=phone or str(history.get("phone") or ""),
        profile_name=profile_name or str(history.get("display_name") or ""),
        lead_info=lead_info,
        summary=reply[:2000] if reply else str(history.get("summary") or ""),
        human_handoff_requested=bool(history.get("human_handoff_requested") or False),
    )
    return reply
