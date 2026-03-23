"""
routers/recognition.py — face identification + audio transcription
"""
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from services.face_pipeline import identify_person_from_image, _b64_to_image
from services.stt_service import transcribe_audio
from services.supabase_client import get_supabase

router = APIRouter()


class RecognizeRequest(BaseModel):
    image_b64: str  # base64 JPEG/PNG of the face crop


@router.post("/identify")
async def identify(req: RecognizeRequest):
    """Return person info + last interaction if face is recognised."""
    try:
        img = _b64_to_image(req.image_b64)
        match = identify_person_from_image(img)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Face not detected: {e}")

    if not match:
        return {"known": False}

    # Fetch latest interaction
    sb = get_supabase()
    interactions = (
        sb.table("interactions")
        .select("summary, timestamp, image_url")
        .eq("person_id", match["id"])
        .order("timestamp", desc=True)
        .limit(1)
        .execute()
        .data
    )

    return {
        "known": True,
        "person": {
            "id": match["id"],
            "name": match.get("name"),
            "role": match.get("role"),
        },
        "last_interaction": interactions[0] if interactions else None,
    }


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Receive audio blob, return Whisper transcription."""
    audio_bytes = await file.read()
    try:
        text = transcribe_audio(audio_bytes, filename=file.filename, content_type=file.content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    return {"text": text}
