from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.agent import run_turn
from app.services.chat_memory import (
    AGENT_MESSAGES_KEY,
    normalize_stored_messages,
    transcript_to_base_messages,
)
from app.services.tools import execute_supabase_query, get_supabase_client
from app.services.twilio_channel import parse_twilio_whatsapp, send_twilio_whatsapp

router = APIRouter(tags=["webhooks"])
_log = logging.getLogger(__name__)


@router.post("/webhooks/twilio/whatsapp")
async def twilio_whatsapp_webhook(request: Request):
    try:
        form_data = await request.form()
        form_dict = dict(form_data)

        if not form_dict.get("From") or not form_dict.get("Body"):
            return Response(content="", media_type="text/plain", status_code=200)

        message = parse_twilio_whatsapp(form_dict)
        text = message.get("text", "")
        if not text:
            return Response(content="", media_type="text/plain", status_code=200)

        client = get_supabase_client()
        lead_info: dict[str, Any] = {}
        chat_history: list[BaseMessage] = []
        if client is not None:
            execute_supabase_query(
                client.table("leads").upsert(
                    {
                        "channel": "whatsapp",
                        "contact_id": message["contact_id"],
                        "phone": message["phone"],
                        "display_name": message["display_name"],
                    },
                    on_conflict="channel,contact_id",
                ),
                operation="upsert_twilio_lead",
            )
            try:
                sel = execute_supabase_query(
                    client.table("leads")
                    .select("lead_info")
                    .eq("channel", "whatsapp")
                    .eq("contact_id", message["contact_id"])
                    .limit(1),
                    operation="fetch_lead_chat_memory",
                )
                if sel.data:
                    lead_info = dict(sel.data[0].get("lead_info") or {})
            except Exception:  # noqa: BLE001
                _log.warning("fetch lead_info for chat memory failed", exc_info=True)

            stored = normalize_stored_messages(lead_info.get(AGENT_MESSAGES_KEY))
            chat_history = transcript_to_base_messages(stored)

        reply = run_turn(
            channel="whatsapp",
            contact_id=message["contact_id"],
            chat_id=message["contact_id"],
            user_text=text,
            chat_history=chat_history,
        )
        send_twilio_whatsapp(to=message["contact_id"], text=reply)

        if client is not None:
            try:
                msgs = list(normalize_stored_messages(lead_info.get(AGENT_MESSAGES_KEY)))
                msgs.append({"role": "user", "content": text})
                msgs.append({"role": "assistant", "content": reply})
                lead_info[AGENT_MESSAGES_KEY] = normalize_stored_messages(msgs)
                execute_supabase_query(
                    client.table("leads")
                    .update({"lead_info": lead_info})
                    .eq("channel", "whatsapp")
                    .eq("contact_id", message["contact_id"]),
                    operation="persist_whatsapp_chat",
                )
            except Exception:  # noqa: BLE001
                _log.warning("persist whatsapp chat transcript failed", exc_info=True)
    except Exception as exc:  # noqa: BLE001
        _log.exception("twilio_whatsapp_webhook failed: %s", exc)
    return Response(content="", media_type="text/plain", status_code=200)


class DryRunBody(BaseModel):
    channel: str = "whatsapp"
    contact_id: str = "+910000000000"
    chat_id: str = ""
    phone: str = ""
    profile_name: str = ""
    text: str = "2 BHK in Indirapuram under 80 lakhs"


@router.post("/debug/run")
def debug_run(body: DryRunBody):
    settings = get_settings()
    if not settings.allow_debug:
        raise HTTPException(status_code=404, detail="not found")

    reply = run_turn(
        channel=body.channel,
        contact_id=body.contact_id,
        chat_id=body.chat_id,
        phone=body.phone,
        profile_name=body.profile_name,
        user_text=body.text,
    )
    return {"reply": reply}
