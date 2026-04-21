"""Supabase-backed tools for the agent (keep DB access here)."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.tools import tool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_supabase = None
LogStepFn = Callable[..., None]


def get_supabase_client():
    global _supabase
    if _supabase is not None:
        return _supabase
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    from supabase import create_client

    _supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _supabase


def fetch_all_properties_rows() -> list[dict[str, Any]]:
    """Unfiltered read of `properties` (same columns as sample CSV)."""
    client = get_supabase_client()
    if client is None:
        logger.warning("db fetch_all_properties skipped: Supabase not configured")
        return []
    try:
        response = (
            client.table("properties")
            .select("id,title,description,price_inr,location,bhk,possession,metadata")
            .limit(500)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db fetch_all_properties failed: %s", exc)
        return []
    rows = response.data or []
    logger.info("db fetch_all_properties ok rows=%s", len(rows))
    return rows


def make_listings_tool(*, channel: str, contact_id: str, phone: str, log_step: LogStepFn) -> list[Any]:
    @tool
    def get_all_properties() -> str:
        """Load every row from the `properties` table as JSON (no filters). Use only this data for listing facts.

        `price_inr` is integer rupees (e.g. 118000000 = 11.8 crore)."""
        rows = fetch_all_properties_rows()
        log_step(
            phone,
            "tool_get_all_properties",
            {"count": len(rows)},
            channel=channel,
            contact_id=contact_id,
        )
        return json.dumps(rows, ensure_ascii=False)

    return [get_all_properties]
