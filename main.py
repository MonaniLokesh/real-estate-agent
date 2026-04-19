"""
FastAPI WhatsApp webhook — minimal BSP-friendly JSON parser + agent turn.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent import log_agent_step, run_turn


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    webhook_secret: str = ""


settings = Settings()
app = FastAPI(title="EstateAgent AI Webhook", version="0.1.0")


def extract_phone_and_text(body: dict[str, Any]) -> tuple[Optional[str], str]:
    """
    Best-effort extraction for common BSP shapes (Interakt/WATI/generic).
    Adjust keys to match your provider once wired.
    """
    # Generic nested patterns
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
    )
    if phone is not None:
        phone = str(phone)
    return phone, str(text).strip()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    secret = settings.webhook_secret
    if secret and x_webhook_secret != secret:
        raise HTTPException(status_code=401, detail="invalid webhook secret")

    body: dict[str, Any]
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="expected JSON body")

    phone, text = extract_phone_and_text(body)
    log_agent_step(phone, "webhook_received", {"keys": list(body.keys())[:40]})

    if not text:
        return {"ok": True, "ignored": True, "reason": "no text"}

    reply = run_turn(phone or "unknown", text)
    log_agent_step(phone, "webhook_reply", {"preview": reply[:200]})

    # BSP send step stays in your provider dashboard/SDK; we only return for tests.
    return {"ok": True, "reply": reply, "phone": phone}


class DryRunBody(BaseModel):
    phone: str = "+910000000000"
    text: str = "2 BHK in Indirapuram under 80 lakhs"


@app.post("/debug/run")
def debug_run(body: DryRunBody):
    """Local test without Meta/BSP signature plumbing."""
    if os.getenv("ALLOW_DEBUG", "").lower() not in ("1", "true", "yes"):
        raise HTTPException(status_code=404, detail="not found")
    return {"reply": run_turn(body.phone, body.text)}
