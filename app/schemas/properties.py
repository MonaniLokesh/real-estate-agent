from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PropertyMetadata(BaseModel):
    type: str | None = None
    status: str | None = None
    size_sqft: float | None = None
    images: list[str] = Field(default_factory=list)
    amenities: list[str] = Field(default_factory=list)
    owner_name: str | None = None
    owner_phone: str | None = None
    commission_rate: float | None = None


class PropertyPayload(BaseModel):
    title: str
    description: str | None = None
    price_inr: float | None = None
    location: str | None = None
    bhk: int | None = None
    possession: str | None = None
    metadata: PropertyMetadata = Field(default_factory=PropertyMetadata)


class PropertyResponse(PropertyPayload):
    id: UUID
    created_at: datetime
    updated_at: datetime
