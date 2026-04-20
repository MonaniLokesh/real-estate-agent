from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.agent import log_agent_step, run_turn
from app.services.channels import (
    extract_telegram_message,
    extract_whatsapp_message,
    send_telegram_message,
)

router = APIRouter(tags=["webhooks"])


def _require_secret(expected: str, received: Optional[str], detail: str) -> None:
    if expected and received != expected:
        raise HTTPException(status_code=401, detail=detail)


async def _parse_json(request: Request) -> dict[str, Any]:
    try:
        return await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="expected JSON body") from exc


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    settings = get_settings()
    _require_secret(settings.webhook_secret, x_webhook_secret, "invalid webhook secret")
    body = await _parse_json(request)
    inbound = extract_whatsapp_message(body)
    log_agent_step(
        inbound.phone if inbound else "",
        "webhook_received",
        {"keys": list(body.keys())[:40]},
        channel="whatsapp",
        contact_id=inbound.contact_id if inbound else "",
    )

    if inbound is None or not inbound.text:
        return {"ok": True, "ignored": True, "reason": "no text"}

    reply = run_turn(
        channel=inbound.channel,
        contact_id=inbound.contact_id,
        chat_id=inbound.chat_id,
        phone=inbound.phone,
        profile_name=inbound.profile_name,
        user_text=inbound.text,
    )
    log_agent_step(
        inbound.phone,
        "webhook_reply",
        {"preview": reply[:200]},
        channel=inbound.channel,
        contact_id=inbound.contact_id,
    )
    return {"ok": True, "reply": reply, "phone": inbound.phone}


@router.post("/webhooks/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(
        default=None,
        alias="X-Telegram-Bot-Api-Secret-Token",
    ),
):
    settings = get_settings()
    _require_secret(
        settings.telegram_webhook_secret,
        x_telegram_bot_api_secret_token,
        "invalid telegram secret token",
    )
    body = await _parse_json(request)
    inbound = extract_telegram_message(body)
    log_agent_step(
        "",
        "telegram_webhook_received",
        {"keys": list(body.keys())[:40]},
        channel="telegram",
        contact_id=inbound.contact_id if inbound else "",
    )

    if inbound is None or not inbound.text:
        return {"ok": True, "ignored": True, "reason": "no text"}

    reply = run_turn(
        channel=inbound.channel,
        contact_id=inbound.contact_id,
        chat_id=inbound.chat_id,
        profile_name=inbound.profile_name,
        user_text=inbound.text,
    )
    telegram_response = send_telegram_message(settings, inbound.chat_id, reply)
    log_agent_step(
        "",
        "telegram_webhook_reply",
        {"preview": reply[:200], "telegram_ok": telegram_response.get("ok")},
        channel=inbound.channel,
        contact_id=inbound.contact_id,
    )
    return {"ok": True, "reply": reply, "chat_id": inbound.chat_id}


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
