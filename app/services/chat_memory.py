"""Persisted chat transcript for WhatsApp / Telegram → LangChain message lists."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

# Stored under leads.lead_info[AGENT_MESSAGES_KEY] as list[{"role","content"}, ...]
AGENT_MESSAGES_KEY = "agent_messages"
_MAX_STORED = 50
_MAX_FOR_MODEL = 24


def transcript_to_base_messages(items: list[dict[str, Any]]) -> list[BaseMessage]:
    """Turn stored JSON rows into LangChain messages (capped for model context)."""
    out: list[BaseMessage] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content", ""))
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
    if len(out) > _MAX_FOR_MODEL:
        out = out[-_MAX_FOR_MODEL:]
    return out


def normalize_stored_messages(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in ("user", "assistant"):
            continue
        out.append({"role": role, "content": str(item.get("content", ""))})
    return out[-_MAX_STORED:]
