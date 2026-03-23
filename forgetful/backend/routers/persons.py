"""
routers/persons.py — CRUD for persons (patient + visitors)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.supabase_client import get_supabase
from services.face_pipeline import (
    register_person_from_images,
    update_person_from_images,
    _b64_to_image,
)

router = APIRouter()


class RegisterRequest(BaseModel):
    image_b64: str          # base64-encoded JPEG/PNG
    image_b64_list: list[str] | None = None
    role: str = "person"    # "patient" or "person" (ignored when person_id is set)
    name: str | None = None
    person_id: str | None = None  # if set, update this row (rename + refresh embeddings)


@router.post("/register")
async def register(req: RegisterRequest):
    """Register a new person (or the patient) by face image."""
    images = [req.image_b64] + (req.image_b64_list or [])
    images = images[:5]

    rgb_images = []
    for image_b64 in images:
        try:
            img = _b64_to_image(image_b64)
            rgb_images.append(img)
        except Exception:
            continue

    if not rgb_images:
        raise HTTPException(status_code=422, detail="Face not detected in any provided image")

    try:
        if req.person_id and str(req.person_id).strip():
            person = update_person_from_images(
                str(req.person_id).strip(),
                rgb_images,
                name=req.name,
            )
        else:
            person = register_person_from_images(rgb_images, role=req.role, name=req.name)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Face registration failed: {e}")

    return {"person": person}


@router.get("/")
async def list_persons():
    sb = get_supabase()
    rows = sb.table("persons").select("id, name, role, created_at").execute().data
    return {"persons": rows}


@router.get("/{person_id}")
async def get_person(person_id: str):
    sb = get_supabase()
    row = sb.table("persons").select("id, name, role, created_at").eq("id", person_id).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    return row


@router.patch("/{person_id}/name")
async def update_name(person_id: str, body: dict):
    sb = get_supabase()
    sb.table("persons").update({"name": body["name"]}).eq("id", person_id).execute()
    return {"ok": True}
