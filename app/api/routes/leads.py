from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.schemas.leads import LeadResponse, UpdateStagePayload
from app.services.tools import (
    SupabaseQueryError,
    SupabaseTimeoutError,
    execute_supabase_query,
    get_supabase_client,
)

router = APIRouter()


def _normalize_json(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _normalize_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_json(v) for v in value]
    return value


def _safe_execute(query, operation: str):
    try:
        return execute_supabase_query(query, operation=operation)
    except SupabaseTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except SupabaseQueryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _get_lead_by_id(lead_id: str) -> dict[str, Any]:
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    response = _safe_execute(
        supabase.table("leads").select("*").eq("id", lead_id).limit(1),
        operation="get lead by id",
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="lead not found")
    return rows[0]


@router.get("", response_model=list[LeadResponse])
def list_leads():
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    response = _safe_execute(
        supabase.table("leads").select("*").order("created_at", desc=True),
        operation="list leads",
    )
    return [_normalize_json(row) for row in (response.data or [])]


@router.patch("/{lead_id}/stage", response_model=LeadResponse)
def update_lead_stage(lead_id: str, payload: UpdateStagePayload):
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    lead = _get_lead_by_id(lead_id)
    lead_info = dict(lead.get("lead_info") or {})
    lead_info["stage"] = payload.stage
    response = (
        _safe_execute(
            supabase.table("leads")
            .update({"lead_info": lead_info})
            .eq("id", lead_id),
            operation="update lead stage",
        )
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="lead not found")
    return _normalize_json(rows[0])


def _log_lead_action(lead_id: str, step: str, action: str) -> dict[str, bool]:
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    lead = _get_lead_by_id(lead_id)
    _safe_execute(
        supabase.table("agent_logs").insert(
            {
                "contact_id": lead.get("contact_id"),
                "channel": lead.get("channel"),
                "phone": lead.get("phone"),
                "step": step,
                "payload": {"lead_id": lead_id, "action": action},
            }
        ),
        operation=f"log lead action ({action})",
    )
    return {"logged": True}


@router.post("/{lead_id}/whatsapp", status_code=status.HTTP_200_OK)
def log_whatsapp_action(lead_id: str):
    return _log_lead_action(
        lead_id=lead_id,
        step="broker_whatsapp_action",
        action="whatsapp",
    )


@router.post("/{lead_id}/call-log", status_code=status.HTTP_200_OK)
def log_call_action(lead_id: str):
    return _log_lead_action(
        lead_id=lead_id,
        step="broker_call_action",
        action="call",
    )
