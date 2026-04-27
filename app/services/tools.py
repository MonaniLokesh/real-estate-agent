"""Supabase tools plus optional read-only SQL over Postgres for `properties`."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from httpx import TimeoutException
from langchain_core.tools import tool
import psycopg
from psycopg.rows import dict_row

from app.core.config import get_settings
from dotenv import load_dotenv
import os
load_dotenv()

logger = logging.getLogger(__name__)
_supabase = None

_PROPERTY_FROM_PATTERN = re.compile(
    r"\bfrom\s+(public\.)?properties\b",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN_SQL = re.compile(
    r"\b("
    r"insert|update|delete|drop|truncate|alter|create|grant|revoke|"
    r"copy|execute|call|set\s+role|set\s+session|"
    r"union\b|into\s+outfile|into\s+dumpfile|"
    r"information_schema|pg_catalog|pg_sleep|"
    r"lo_import|lo_export"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDS_EMBEDDING = re.compile(r"\bembedding\b", re.IGNORECASE)


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


def _validate_property_sql(sql: str) -> str | None:
    """Return an error message if invalid; None if OK."""
    raw = (sql or "").strip()
    if not raw:
        return "empty SQL"
    body = raw.rstrip().rstrip(";").strip()
    if ";" in body:
        return "only a single statement is allowed (no semicolons inside the query)"
    if not re.match(r"^\s*select\b", body, re.IGNORECASE | re.DOTALL):
        return "query must be a single SELECT"
    if _FORBIDDEN_SQL.search(body):
        return "query contains forbidden keywords or patterns"
    if _FORBIDS_EMBEDDING.search(body):
        return "do not reference the embedding column; select other columns only"
    if not _PROPERTY_FROM_PATTERN.search(body):
        return "query must read from table properties (or public.properties)"
    return None


def _normalize_cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _normalize_cell(v) for k, v in row.items()}


def _choose_sql_dsn() -> str:
    """Prefer explicit DB URL, then fallback to Supabase pooler URL."""
    settings = get_settings()
    primary = (os.getenv("SUPABASE_DB_URL") or "").strip()
    return primary



@tool
def run_property_sql(sql: str) -> str:
    """Run one read-only SELECT on public.properties. Returns JSON rows (capped) or an error object.

    Prefer this tool whenever the user asks for listings, counts, filters, price ranges, BHK, or
    location — write a tight SELECT instead of pulling the whole inventory.

    Allowed columns include: id, title, description, price_inr, location, bhk, possession,
    metadata (jsonb), created_at, updated_at. Do not select embedding.

    Example: SELECT id, title, price_inr, location, bhk FROM public.properties
    WHERE bhk = 3 AND price_inr <= 15000000 ORDER BY price_inr ASC LIMIT 10
    """
    err = _validate_property_sql(sql)
    if err:
        return json.dumps({"error": err, "rows": []}, ensure_ascii=False)

    dsn = _choose_sql_dsn()
    if not dsn:
        return json.dumps(
            {
                "error": "database_url/supabase_db_url is not configured on the server; use get_all_properties instead",
                "rows": [],
            },
            ensure_ascii=False,
        )

    body = sql.strip().rstrip().rstrip(";").strip()
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            conn.execute("SET statement_timeout = '8s'")
            conn.execute("BEGIN READ ONLY")
            try:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(body)
                    rows = [dict(r) for r in cur.fetchmany(51)]
            finally:
                conn.rollback()
    except Exception as exc:  # noqa: BLE001
        logger.warning("run_property_sql failed: %s", exc)
        return json.dumps(
            {"error": f"query failed: {exc}", "rows": []},
            ensure_ascii=False,
        )

    truncated = len(rows) > 50
    rows = rows[:50]
    out = [_normalize_row(r) for r in rows]
    payload: dict[str, Any] = {"error": None, "rows": out, "row_count": len(out)}
    if truncated:
        payload["truncated"] = True
        payload["note"] = "more than 50 rows matched; results truncated to 50"
    return json.dumps(payload, ensure_ascii=False)


@tool
def get_all_properties() -> str:
    """Return up to 50 rows from `properties` via Supabase (no SQL). Use when database_url is unset or as a fallback."""
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
