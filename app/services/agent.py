"""Simple agent setup: LLM + tools + prompt."""
from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.core.config import get_settings
from app.services.prompt import FALLBACK_LLM_ERROR, FALLBACK_NO_LLM, SYSTEM_PROMPT
from app.services.tools import get_all_properties

logger = logging.getLogger(__name__)


def create_agent() -> Any | None:
    settings = get_settings()
    if not settings.groq_api_key:
        return None

    llm = ChatOpenAI(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        temperature=settings.groq_temperature,
    )
    tools = [get_all_properties]
    return create_react_agent(model=llm, tools=tools, prompt=SYSTEM_PROMPT)


def run_turn(
    *,
    channel: str = "",
    contact_id: str = "",
    user_text: str,
    chat_id: str = "",
    phone: str = "",
    profile_name: str = "",
) -> str:
    _ = channel, contact_id, chat_id, phone, profile_name
    agent = create_agent()
    if agent is None:
        logger.info("missing GROQ_API_KEY")
        return FALLBACK_NO_LLM

    try:
        result = agent.invoke({"messages": [{"role": "user", "content": user_text}]})
        messages = result.get("messages", [])

        for message in reversed(messages):
            content = getattr(message, "content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = [
                    str(block.get("text", ""))
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                text = "\n".join(parts).strip()
                if text:
                    return text

        return FALLBACK_LLM_ERROR
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_turn failed: %s", exc)
        return FALLBACK_LLM_ERROR
