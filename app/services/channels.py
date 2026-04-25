from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(slots=True)
class InboundMessage:
    channel: str
    contact_id: str
    chat_id: str
    text: str
    profile_name: str = ""
    phone: str = ""


def extract_whatsapp_message(body: dict[str, Any]) -> Optional[InboundMessage]:
    msg = body.get("message") or body.get("data", {}).get("message") or body
    text = (
        msg.get("text")
        or msg.get("body")
        or (msg.get("content") if isinstance(msg.get("content"), str) else None)
        or body.get("text")
        or ""
    )
    if isinstance(text, dict):
        text = text.get("body") or text.get("text") or ""

    phone = (
        msg.get("from")
        or msg.get("sender", {}).get("phone")
        or body.get("from")
        or body.get("waId")
        or body.get("customer", {}).get("phone")
        or ""
    )
    profile_name = (
        msg.get("sender", {}).get("name")
        or body.get("customer", {}).get("name")
        or body.get("profile", {}).get("name")
        or ""
    )

    phone = str(phone).strip()
    text = str(text).strip()
    if not phone and not text:
        return None

    contact_id = phone or "unknown"
    return InboundMessage(
        channel="whatsapp",
        contact_id=contact_id,
        chat_id=contact_id,
        text=text,
        profile_name=str(profile_name).strip(),
        phone=phone,
    )


