"""Simple agent setup: LLM + tools + prompt."""
from __future__ import annotations

import logging
from typing import Any

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.core.config import get_settings
from app.services.prompt import FALLBACK_LLM_ERROR, FALLBACK_NO_LLM, SYSTEM_PROMPT
from app.services.tools import get_all_properties, run_property_sql

logger = logging.getLogger(__name__)


def create_agent() -> Any | None:
    settings = get_settings()
    if not settings.groq_api_key:
        return None

    model_name = settings.groq_model
    # Some lightweight models occasionally emit malformed tool-call payloads
    # (e.g., null tool args), which breaks tool parsers before trace is produced.
    if model_name == "llama-3.1-8b-instant":
        logger.warning("switching tool-calling model from %s to llama-3.3-70b-versatile", model_name)
        model_name = "llama-3.3-70b-versatile"

    llm = ChatGroq(
        model=model_name,
        temperature=settings.groq_temperature,
        api_key=settings.groq_api_key,
    )
    tools = [run_property_sql, get_all_properties]
    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )
    agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


def run_turn(
    *,
    channel: str = "",
    contact_id: str = "",
    user_text: str,
    chat_id: str = "",
    phone: str = "",
    profile_name: str = "",
    chat_history: list[BaseMessage] | None = None,
) -> str:
    _ = channel, contact_id, chat_id, phone, profile_name
    agent = create_agent()
    if agent is None:
        logger.info("missing GROQ_API_KEY")
        return FALLBACK_NO_LLM

    try:
        result = agent.invoke({"input": user_text, "chat_history": chat_history or []})
        output = result.get("output", "")
        if isinstance(output, str) and output.strip():
            return output.strip()
        return FALLBACK_LLM_ERROR
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_turn failed: %s", exc)
        return FALLBACK_LLM_ERROR
