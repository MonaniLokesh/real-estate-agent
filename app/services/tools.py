"""One Supabase tool: full `properties` read."""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_supabase = None


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


@tool
def get_all_properties() -> str:
    """Return every row from `properties` as JSON (no filters). Use for prices, BHK, location."""
    client = get_supabase_client()
    if client is None:
        logger.warning("get_all_properties: Supabase not configured")
        return "[]"
    try:
        response = (
            client.table("properties")
            .select("id,title,description,price_inr,location,bhk,possession,metadata")
            .limit(50)
            .execute()
        )
    except Exception as exc: 
        logger.warning("get_all_properties failed: %s", exc)
        return "[]"
    rows = response.data or []
    logger.info("get_all_properties: fetched_rows=%s", len(rows))
    return json.dumps(rows, ensure_ascii=False)
