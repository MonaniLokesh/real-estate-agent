from __future__ import annotations

from twilio.rest import Client

from app.core.config import get_settings


def parse_twilio_whatsapp(form_data: dict) -> dict:
    contact_id = form_data.get("From", "")
    raw_phone = contact_id.replace("whatsapp:", "")
    return {
        "channel": "whatsapp",
        "contact_id": contact_id,
        "phone": "".join(ch for ch in raw_phone if ch.isdigit()),
        "display_name": form_data.get("ProfileName", ""),
        "text": form_data.get("Body", "").strip(),
        "message_id": form_data.get("MessageSid", ""),
    }


def send_twilio_whatsapp(to: str, text: str) -> None:
    settings = get_settings()
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    client.messages.create(
        from_=settings.twilio_whatsapp_from,
        to=to,
        body=text,
    )
