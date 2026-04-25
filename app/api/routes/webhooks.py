from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.agent import run_turn
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

        reply = run_turn(
            channel="whatsapp",
            contact_id=message["contact_id"],
            user_text=text,
        )
        send_twilio_whatsapp(to=message["contact_id"], text=reply)
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
