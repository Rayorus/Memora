"""
Admin / demo utilities — gated by env (off by default).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from services.supabase_client import get_supabase
from services.face_pipeline import invalidate_persons_cache_after_reset

router = APIRouter()

# Sentinel UUID: every real row has id != this, so PostgREST deletes all rows.
_ALL_ROWS_FILTER = "00000000-0000-0000-0000-000000000000"


class ResetAllRequest(BaseModel):
    """Must send exact phrase so accidental clicks cannot wipe data."""
    confirm: str


@router.post("/reset-all")
async def reset_all_database(req: ResetAllRequest):
    """Delete all interactions and persons. Next app load behaves like first run (register patient).

    Enable with ALLOW_FULL_DATABASE_RESET=true in backend .env.local (demo only).
    """
    if not getattr(settings, "allow_full_database_reset", False):
        raise HTTPException(
            status_code=403,
            detail="Full database reset is disabled. Set ALLOW_FULL_DATABASE_RESET=true in backend env.",
        )
    if req.confirm != "DELETE_ALL_DATA":
        raise HTTPException(
            status_code=400,
            detail='Send JSON body: {"confirm": "DELETE_ALL_DATA"}',
        )

    sb = get_supabase()
    try:
        sb.table("interactions").delete().neq("id", _ALL_ROWS_FILTER).execute()
        sb.table("persons").delete().neq("id", _ALL_ROWS_FILTER).execute()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database reset failed: {e}",
        ) from e

    invalidate_persons_cache_after_reset()

    return {"ok": True, "message": "All persons and interactions removed."}
