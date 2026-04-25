from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from httpx import TimeoutException

from app.schemas.properties import PropertyPayload, PropertyResponse
from app.services.tools import (
    SupabaseQueryError,
    SupabaseTimeoutError,
    execute_supabase_query,
    get_supabase_client,
)

router = APIRouter()


def _to_row(payload: PropertyPayload) -> dict[str, object]:
    return {
        "title": payload.title,
        "description": payload.description,
        "price_inr": payload.price_inr,
        "location": payload.location,
        "bhk": payload.bhk,
        "possession": payload.possession,
        "metadata": payload.metadata.model_dump(),
    }


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


@router.get("", response_model=list[PropertyResponse])
def list_properties(
    status: str | None = None,
    bhk: int | None = None,
    search: str | None = None,
):
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    query = supabase.table("properties").select("*")
    if status:
        query = query.filter("metadata->>status", "eq", status)
    if bhk is not None:
        query = query.eq("bhk", bhk)
    if search:
        query = query.or_(f"title.ilike.%{search}%,location.ilike.%{search}%")

    response = _safe_execute(query.order("created_at", desc=True), operation="list properties")
    return [_normalize_json(row) for row in (response.data or [])]


@router.get("/{property_id}", response_model=PropertyResponse)
def get_property(property_id: str):
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    response = _safe_execute(
        supabase.table("properties").select("*").eq("id", property_id).limit(1),
        operation="get property",
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="property not found")
    return _normalize_json(rows[0])


@router.post("", response_model=PropertyResponse, status_code=status.HTTP_201_CREATED)
def create_property(payload: PropertyPayload):
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    response = _safe_execute(
        supabase.table("properties").insert(_to_row(payload)),
        operation="create property",
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="failed to create property")
    return _normalize_json(rows[0])


@router.put("/{property_id}", response_model=PropertyResponse)
def update_property(property_id: str, payload: PropertyPayload):
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    response = (
        _safe_execute(
            supabase.table("properties")
            .update(_to_row(payload))
            .eq("id", property_id),
            operation="update property",
        )
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="property not found")
    return _normalize_json(rows[0])


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(property_id: str):
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    response = _safe_execute(
        supabase.table("properties").delete().eq("id", property_id),
        operation="delete property",
    )
    if not (response.data or []):
        raise HTTPException(status_code=404, detail="property not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/images/upload")
async def upload_property_images(files: list[UploadFile] = File(...)):
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(status_code=500, detail="supabase not configured")

    public_urls: list[str] = []
    bucket = supabase.storage.from_("property-images")
    for upload in files:
        raw = await upload.read()
        ext = upload.filename.rsplit(".", maxsplit=1)[-1] if upload.filename and "." in upload.filename else "bin"
        object_path = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex}.{ext}"
        try:
            bucket.upload(
                object_path,
                raw,
                {"content-type": upload.content_type or "application/octet-stream"},
            )
            url_result = bucket.get_public_url(object_path)
        except TimeoutException as exc:
            raise HTTPException(status_code=504, detail="supabase timeout during image upload") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"supabase error during image upload: {exc}") from exc
        if isinstance(url_result, dict):
            public_url = (
                url_result.get("publicUrl")
                or (url_result.get("data") or {}).get("publicUrl")
                or ""
            )
        else:
            public_url = str(url_result)
        public_urls.append(public_url)

    return public_urls
