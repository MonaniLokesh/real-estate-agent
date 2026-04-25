"""One Supabase tool: full `properties` read."""
from __future__ import annotations

import json
import logging
from typing import Any

from httpx import TimeoutException
from langchain_core.tools import tool

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_supabase = None


class SupabaseTimeoutError(RuntimeError):
    """Raised when a Supabase request exceeds configured timeout."""


class SupabaseQueryError(RuntimeError):
    """Raised for non-timeout Supabase request failures."""


def get_supabase_client():
    global _supabase
    if _supabase is not None:
        return _supabase
    settings = get_settings()
    supabase_url = (settings.supabase_url or "").strip()
    service_role_key = (settings.supabase_service_role_key or "").strip()
    if not supabase_url or not service_role_key:
        return None
    from supabase import ClientOptions, create_client

    options = ClientOptions(
        postgrest_client_timeout=10,
        storage_client_timeout=10,
        function_client_timeout=10,
        auto_refresh_token=False,
        persist_session=False,
    )
    _supabase = create_client(supabase_url, service_role_key, options=options)
    return _supabase


def execute_supabase_query(query, operation: str):
    """Execute a Supabase query and convert low-level failures."""
    try:
        return query.execute()
    except TimeoutException as exc:
        raise SupabaseTimeoutError(f"supabase timeout during {operation}") from exc
    except Exception as exc:  # noqa: BLE001
        raise SupabaseQueryError(f"supabase error during {operation}: {exc}") from exc


@tool
def get_all_properties() -> str:
    """Return every row from `properties` as JSON (no filters). Use for prices, BHK, location."""
    client = get_supabase_client()
    if client is None:
        logger.warning("get_all_properties: Supabase not configured")
        return "[]"
    try:
        response = execute_supabase_query(
            client.table("properties")
            .select("id,title,description,price_inr,location,bhk,possession,metadata")
            .limit(50),
            operation="get_all_properties",
        )
    except Exception as exc: 
        logger.warning("get_all_properties failed: %s", exc)
        return "[]"
    rows = response.data or []
    logger.info("get_all_properties: fetched_rows=%s", len(rows))
    return json.dumps(rows, ensure_ascii=False)
