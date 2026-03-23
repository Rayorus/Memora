"""
routers/interactions.py — store and retrieve interaction records
"""
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.supabase_client import get_supabase
from services.llm_service import summarize
from services.face_pipeline import upload_face_image, _b64_to_image

router = APIRouter()


class CreateInteractionRequest(BaseModel):
    person_id: str
    transcript: str
    image_b64: str | None = None
    # True when only the patient was on camera (no visitors) — for memory popups
    patient_solo: bool | None = None


@router.post("/")
async def create_interaction(req: CreateInteractionRequest):
    sb = get_supabase()

    try:
        summary = summarize(req.transcript)
    except Exception:
        words = req.transcript.strip().split()
        summary = " ".join(words[:10]) + ("..." if len(words) > 10 else "")

    # Optionally upload face image
    image_url = None
    if req.image_b64:
        try:
            img = _b64_to_image(req.image_b64)
            image_url = upload_face_image(img, req.person_id)
        except Exception:
            pass  # Image upload failure is non-critical

    payload: dict = {
        "id": str(uuid.uuid4()),
        "person_id": req.person_id,
        "summary": summary,
        "image_url": image_url,
    }
    if req.patient_solo is True:
        payload["patient_solo"] = True

    try:
        result = sb.table("interactions").insert(payload).execute()
    except Exception:
        if "patient_solo" in payload:
            del payload["patient_solo"]
            result = sb.table("interactions").insert(payload).execute()
        else:
            raise
    return {"interaction": result.data[0]}


@router.get("/{person_id}/latest")
async def get_latest_interaction(
    person_id: str,
    patient_solo_only: bool = False,
):
    sb = get_supabase()
    rows: list = []
    try:
        q = sb.table("interactions").select("*").eq("person_id", person_id)
        if patient_solo_only:
            q = q.eq("patient_solo", True)
        rows = q.order("timestamp", desc=True).limit(1).execute().data
    except Exception:
        rows = []
    if patient_solo_only and not rows:
        try:
            rows = (
                sb.table("interactions")
                .select("*")
                .eq("person_id", person_id)
                .order("timestamp", desc=True)
                .limit(1)
                .execute()
                .data
            )
        except Exception:
            rows = []
    if not rows:
        raise HTTPException(status_code=404, detail="No interactions found")
    return rows[0]


@router.get("/{person_id}")
async def list_interactions(person_id: str, limit: int = 20):
    sb = get_supabase()
    rows = (
        sb.table("interactions")
        .select("*")
        .eq("person_id", person_id)
        .order("timestamp", desc=True)
        .limit(limit)
        .execute()
        .data
    )
    return {"interactions": rows}
