from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException

from app.services.tools import (
    SupabaseQueryError,
    SupabaseTimeoutError,
    execute_supabase_query,
    get_supabase_client,
)

router = APIRouter()


def _safe_execute(query, operation: str):
    try:
        return execute_supabase_query(query, operation=operation)
    except SupabaseTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except SupabaseQueryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _count_rows(table_name: str, filter_column: str | None = None, filter_value: str | None = None) -> int:
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    query = supabase.table(table_name).select("id", count="exact")
    if filter_column and filter_value is not None:
        query = query.filter(filter_column, "eq", filter_value)
    response = _safe_execute(query.limit(1), operation=f"count {table_name}")
    return int(response.count or 0)


@router.get("/summary")
def dashboard_summary():
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    total_listings = _count_rows("properties")
    active_listings = _count_rows("properties", "metadata->>status", "Active")
    total_leads = _count_rows("leads")

    revenue_response = (
        _safe_execute(
            supabase.table("properties")
            .select("price_inr,metadata")
            .not_.is_("price_inr", "null"),
            operation="calculate revenue estimate",
        )
    )
    revenue_estimate = 0.0
    for row in revenue_response.data or []:
        price = row.get("price_inr")
        metadata = row.get("metadata") or {}
        commission_rate = metadata.get("commission_rate")
        if price is None or commission_rate is None:
            continue
        revenue_estimate += float(Decimal(str(price)) * Decimal(str(commission_rate)) / Decimal("100"))

    return {
        "totalListings": total_listings,
        "activeListings": active_listings,
        "totalLeads": total_leads,
        "revenueEstimate": revenue_estimate,
    }
