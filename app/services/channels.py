from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import Settings


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


def extract_telegram_message(body: dict[str, Any]) -> Optional[InboundMessage]:
    message = body.get("message") or body.get("edited_message")
    if message is None and isinstance(body.get("callback_query"), dict):
        callback = body["callback_query"]
        message = callback.get("message") or {}
        if "data" in callback and "text" not in message:
            message["text"] = callback.get("data")
        if "from" not in message:
            message["from"] = callback.get("from")
    if not isinstance(message, dict):
        return None

    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    text = str(message.get("text") or message.get("caption") or "").strip()
    chat_id = str(chat.get("id") or "")
    sender_id = str(sender.get("id") or chat_id).strip()
    profile_name = " ".join(
        part for part in [sender.get("first_name"), sender.get("last_name")] if part
    ).strip()
    if not sender_id and not text:
        return None

    return InboundMessage(
        channel="telegram",
        contact_id=sender_id or chat_id or "unknown",
        chat_id=chat_id or sender_id or "unknown",
        text=text,
        profile_name=profile_name or str(sender.get("username") or "").strip(),
    )


def send_telegram_message(settings: Settings, chat_id: str, text: str) -> dict[str, Any]:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    url = (
        f"{settings.telegram_api_base.rstrip('/')}/bot"
        f"{settings.telegram_bot_token}/sendMessage"
    )
    request = Request(
        url=url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Telegram API error ({exc.code}): {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"Telegram API request failed: {exc.reason}") from exc

    data = json.loads(raw)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API rejected message: {data}")
    return data
