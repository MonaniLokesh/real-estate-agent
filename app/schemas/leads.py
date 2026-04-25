from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LeadInfo(BaseModel):
    stage: str | None = None
    priority: str | None = None
    budget: float | None = None
    property_interest: str | None = None
    next_action: str | None = None
    extra: dict[str, object] = Field(default_factory=dict)


class LeadResponse(BaseModel):
    id: UUID
    channel: str
    contact_id: str
    phone: str | None = None
    chat_id: str | None = None
    display_name: str | None = None
    lead_info: dict[str, object] = Field(default_factory=dict)
    summary: str | None = None
    human_handoff_requested: bool
    created_at: datetime
    updated_at: datetime


class UpdateStagePayload(BaseModel):
    stage: str
