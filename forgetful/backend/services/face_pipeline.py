"""
face_pipeline.py — Fast real-time face detection + recognition

Key fix: registration now detects the face in the image FIRST, then computes
the embedding on the CROP. This ensures stored embeddings match what the live
stream produces (which also uses crops from detection).
"""

from __future__ import annotations

import base64
import io
import json
import os

os.environ.pop("TF_USE_LEGACY_KERAS", None)
os.environ["TF_USE_LEGACY_KERAS"] = "0"

import re
import time
import uuid
from typing import Any

import numpy as np
from PIL import Image
from deepface import DeepFace

from config import settings
from services.supabase_client import get_supabase

_PERSONS_CACHE: list[dict[str, Any]] | None = None
_PERSONS_CACHE_AT: float = 0.0
_WINNING_MODEL: str | None = None


def _canonical_model(raw: str | None) -> str:
    aliases = {
        "vggface": "VGG-Face", "vgg-face": "VGG-Face",
        "facenet": "Facenet", "facenet512": "Facenet512",
        "arcface": "ArcFace", "sface": "SFace",
        "openface": "OpenFace", "deepid": "DeepID",
        "dlib": "Dlib", "ghostfacenet": "GhostFaceNet",
    }
    key = (raw or "Facenet512").strip().lower().replace("_", "").replace("-", "")
    return aliases.get(key, raw or "Facenet512")


def _canonical_detector(raw: str | None) -> str:
    return (raw or "yunet").strip().lower()


def _b64_to_image(b64: str) -> np.ndarray:
    data = base64.b64decode(b64)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    return np.array(img, dtype=np.uint8)


def _normalize(vec: np.ndarray) -> np.ndarray:
    v = vec.astype(np.float32, copy=False)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def _parse_embeddings(field: Any) -> list[np.ndarray]:
    val = field
    if isinstance(val, str):
        val = json.loads(val)
    if not val:
        return []
    if isinstance(val[0], (int, float)):
        return [_normalize(np.array(val, dtype=np.float32))]
    return [_normalize(np.array(e, dtype=np.float32)) for e in val if e]


def _iou(a: dict, b: dict) -> float:
    ax1, ay1 = float(a.get("x", 0)), float(a.get("y", 0))
    ax2, ay2 = ax1 + float(a.get("w", 0)), ay1 + float(a.get("h", 0))
    bx1, by1 = float(b.get("x", 0)), float(b.get("y", 0))
    bx2, by2 = bx1 + float(b.get("w", 0)), by1 + float(b.get("h", 0))
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return float(inter / union) if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Persons cache
# ---------------------------------------------------------------------------

def invalidate_persons_cache_after_reset() -> None:
    """Call after wiping the persons table (e.g. demo reset)."""
    global _WINNING_MODEL
    _WINNING_MODEL = None
    _load_persons_cache(force=True)


def _load_persons_cache(force: bool = False) -> None:
    global _PERSONS_CACHE, _PERSONS_CACHE_AT
    if not force and _PERSONS_CACHE is not None and (time.time() - _PERSONS_CACHE_AT) < 30:
        return
    sb = get_supabase()
    rows = sb.table("persons").select("id, name, role, face_embedding").execute().data
    persons: list[dict[str, Any]] = []
    for row in rows:
        embs = _parse_embeddings(row.get("face_embedding"))
        if embs:
            raw_role = (row.get("role") or "").strip().lower()
            if raw_role not in ("patient", "person"):
                raw_role = "person"
            persons.append({
                "id": row["id"],
                "name": row.get("name"),
                "role": raw_role,
                "embeddings": embs,
            })
    _PERSONS_CACHE = persons
    _PERSONS_CACHE_AT = time.time()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_faces(
    img_rgb: np.ndarray,
    *,
    enforce_detection: bool = False,
) -> list[dict[str, Any]]:
    if img_rgb is None or img_rgb.ndim != 3 or img_rgb.shape[2] != 3:
        return []

    orig_h, orig_w = img_rgb.shape[:2]

    target_w = max(1, int(settings.face_detect_resize_width or 640))
    target_h = max(1, int(settings.face_detect_resize_height or 480))
    scale = min(target_w / orig_w, target_h / orig_h, 1.0)

    if scale < 1.0:
        import cv2
        new_w = max(1, int(round(orig_w * scale)))
        new_h = max(1, int(round(orig_h * scale)))
        resized = cv2.resize(img_rgb, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    else:
        resized = img_rgb
        new_w, new_h = orig_w, orig_h

    bgr = resized[..., ::-1]
    detector = _canonical_detector(settings.face_detector_backend)

    try:
        faces = DeepFace.extract_faces(
            img_path=bgr,
            detector_backend=detector,
            enforce_detection=enforce_detection,
            align=True,
            expand_percentage=10,
            grayscale=False,
            anti_spoofing=False,
        )
    except Exception:
        return []

    if not faces:
        return []

    inv_x = orig_w / new_w
    inv_y = orig_h / new_h
    min_size = int(settings.face_min_size or 30)
    min_conf = float(settings.face_detection_confidence or 0.3)
    max_faces = int(settings.face_max_faces_per_frame or 3)
    nms_iou = float(settings.face_nms_iou or 0.5)

    out: list[dict[str, Any]] = []
    for f in faces:
        region = f.get("facial_area") or {}
        x = int(round(float(region.get("x", 0)) * inv_x))
        y = int(round(float(region.get("y", 0)) * inv_y))
        w = int(round(float(region.get("w", 0)) * inv_x))
        h = int(round(float(region.get("h", 0)) * inv_y))

        if w < min_size or h < min_size:
            continue

        conf = 1.0
        try:
            c = f.get("confidence")
            if c is not None:
                conf = float(c)
        except Exception:
            pass
        if conf < min_conf:
            continue

        x = max(0, min(x, orig_w - 1))
        y = max(0, min(y, orig_h - 1))
        w = min(w, orig_w - x)
        h = min(h, orig_h - y)
        if w <= 0 or h <= 0:
            continue

        out.append({
            "face": np.asarray(f.get("face"), dtype=np.float32),
            "facial_area": {"x": x, "y": y, "w": w, "h": h},
            "confidence": conf,
        })

    out.sort(key=lambda f: f["confidence"], reverse=True)
    kept: list[dict[str, Any]] = []
    for f in out:
        if any(_iou(f["facial_area"], k["facial_area"]) > nms_iou for k in kept):
            continue
        kept.append(f)

    return kept[:max_faces]


def extract_faces_with_fallback(
    image_array: np.ndarray, enforce_detection: bool = True
) -> list[dict[str, Any]]:
    return detect_faces(image_array, enforce_detection=enforce_detection)


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def get_embedding(
    image_array: np.ndarray, *, model_override: str | None = None
) -> list[float]:
    img = np.asarray(image_array)
    model = _canonical_model(model_override or settings.face_model)

    if img.dtype.kind == "f":
        if float(np.max(img)) <= 1.5:
            img = (img * 255).clip(0, 255).astype(np.uint8)
        else:
            img = img.clip(0, 255).astype(np.uint8)

    try:
        result = DeepFace.represent(
            img_path=img,
            model_name=model,
            enforce_detection=False,
            detector_backend="skip",
            align=False,
        )
    except Exception:
        return []

    if not result:
        return []
    emb = result[0].get("embedding", [])
    return list(emb) if emb else []


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------

def find_matching_person(
    embedding: list[float] | np.ndarray,
    threshold_override: float | None = None,
    *,
    exclude_roles: frozenset[str] | None = None,
) -> dict | None:
    """Match embedding to one DB person using best score *per person*, with ambiguity rejection."""
    _load_persons_cache()
    if not _PERSONS_CACHE:
        return None

    emb = _normalize(np.array(embedding, dtype=np.float32))
    dim = len(emb)
    threshold = threshold_override if threshold_override is not None else float(
        settings.face_similarity_threshold or 0.45
    )
    margin = float(getattr(settings, "face_match_min_margin", 0.05) or 0.05)

    scored: list[tuple[float, dict[str, Any]]] = []
    for person in _PERSONS_CACHE:
        role = (person.get("role") or "").strip().lower()
        if exclude_roles and role in exclude_roles:
            continue
        best_for = -1.0
        for stored in person["embeddings"]:
            if len(stored) != dim:
                continue
            best_for = max(best_for, float(np.dot(emb, stored)))
        if best_for >= 0.0:
            scored.append((best_for, person))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_sim, best = scored[0]
    second_sim = scored[1][0] if len(scored) > 1 else -1.0

    if best_sim < threshold:
        return None

    # Two different people both "close" → reject (prevents random pick / duplicate visitors)
    if second_sim >= threshold - 0.08 and (best_sim - second_sim) < margin:
        return None

    # Near-tie: prefer a named profile over anonymous
    if len(scored) > 1 and abs(best_sim - second_sim) < 0.02:
        tier = [s for s in scored if abs(s[0] - best_sim) < 0.02]
        named = [s for s in tier if s[1].get("name")]
        if named:
            best_sim, best = max(named, key=lambda x: x[0])

    return {
        "id": best["id"],
        "name": best.get("name"),
        "role": (best.get("role") or "").strip().lower() or None,
        "match_similarity": best_sim,
    }


def find_matching_visitor_only(
    embedding: list[float] | np.ndarray,
    threshold_override: float | None = None,
) -> dict | None:
    """Like find_matching_person but never matches the patient — for disambiguating extras."""
    return find_matching_person(
        embedding, threshold_override, exclude_roles=frozenset({"patient"})
    )


def find_matching_patient_only(
    embedding: list[float] | np.ndarray,
    threshold_override: float | None = None,
) -> dict | None:
    """Match only DB rows with role *patient*.

    Used to recover the patient after an identity split or a near-miss strict match, without
    letting a *visitor* cosine score trigger the global ambiguity rejection (which would block
    patient ID when a Visitor N is almost as close).
    """
    _load_persons_cache()
    if not _PERSONS_CACHE:
        return None

    emb = _normalize(np.array(embedding, dtype=np.float32))
    dim = len(emb)
    threshold = threshold_override if threshold_override is not None else float(
        settings.face_similarity_threshold or 0.45
    )
    margin = float(getattr(settings, "face_match_min_margin", 0.05) or 0.05)

    scored: list[tuple[float, dict[str, Any]]] = []
    for person in _PERSONS_CACHE:
        if (person.get("role") or "").strip().lower() != "patient":
            continue
        best_for = -1.0
        for stored in person["embeddings"]:
            if len(stored) != dim:
                continue
            best_for = max(best_for, float(np.dot(emb, stored)))
        if best_for >= 0.0:
            scored.append((best_for, person))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_sim, best = scored[0]
    second_sim = scored[1][0] if len(scored) > 1 else -1.0

    if best_sim < threshold:
        return None

    if len(scored) > 1 and second_sim >= threshold - 0.08 and (best_sim - second_sim) < margin:
        return None

    return {
        "id": best["id"],
        "name": best.get("name"),
        "role": (best.get("role") or "").strip().lower() or None,
        "match_similarity": best_sim,
    }


def visitor_db_count() -> int:
    _load_persons_cache()
    return sum(1 for p in (_PERSONS_CACHE or []) if (p.get("role") or "") == "person")


def identify_person_from_image(image_array: np.ndarray) -> dict | None:
    """Identify a person from a face crop. Caches the winning model for speed."""
    global _WINNING_MODEL

    if _WINNING_MODEL:
        emb = get_embedding(image_array, model_override=_WINNING_MODEL)
        if emb:
            match = find_matching_person(emb)
            if match:
                return match

    for model in ["Facenet512", "ArcFace"]:
        if model == _WINNING_MODEL:
            continue
        emb = get_embedding(image_array, model_override=model)
        if emb:
            match = find_matching_person(emb)
            if match:
                _WINNING_MODEL = model
                return match

    return None


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

def register_person(
    embedding, role: str = "person", name: str | None = None
) -> dict:
    sb = get_supabase()
    payload = {
        "id": str(uuid.uuid4()),
        "name": name,
        "role": role,
        "face_embedding": json.dumps(embedding),
    }
    result = sb.table("persons").insert(payload).execute()
    _load_persons_cache(force=True)
    return result.data[0]


def register_person_from_images(
    images: list, role: str = "person", name: str | None = None
) -> dict:
    """Register a person by detecting faces in images and storing face-crop embeddings.

    Previously this passed full-frame images to get_embedding with detector_backend="skip",
    creating embeddings of the entire frame (background, body, etc.) instead of just the face.
    Now we detect the face first, crop it, then compute the embedding on the crop —
    matching exactly what the live webcam stream does.
    """
    embeddings = []
    for img in images:
        faces = detect_faces(img, enforce_detection=False)
        if faces:
            best = max(
                faces,
                key=lambda f: f.get("facial_area", {}).get("w", 0)
                * f.get("facial_area", {}).get("h", 0),
            )
            crop = best["face"]
            emb = get_embedding(crop)
        else:
            emb = get_embedding(img)
        if emb:
            embeddings.append(emb)

    if not embeddings:
        raise ValueError("No face detected or embedding generated from provided images")

    payload = embeddings if len(embeddings) > 1 else embeddings[0]
    return register_person(payload, role=role, name=name)


def update_person_from_images(
    person_id: str,
    images: list,
    *,
    name: str | None = None,
) -> dict:
    """Replace face embedding(s) for an existing person; optionally set a new display name."""
    embeddings: list[list[float]] = []
    for img in images:
        faces = detect_faces(img, enforce_detection=False)
        if faces:
            best = max(
                faces,
                key=lambda f: f.get("facial_area", {}).get("w", 0)
                * f.get("facial_area", {}).get("h", 0),
            )
            crop = best["face"]
            emb = get_embedding(crop)
        else:
            emb = get_embedding(img)
        if emb:
            embeddings.append(emb)

    if not embeddings:
        raise ValueError("No face detected or embedding generated from provided images")

    payload = embeddings if len(embeddings) > 1 else embeddings[0]
    sb = get_supabase()
    existing = sb.table("persons").select("id").eq("id", person_id).execute().data
    if not existing:
        raise ValueError("Person not found")

    update_body: dict[str, Any] = {"face_embedding": json.dumps(payload)}
    if name is not None and str(name).strip():
        update_body["name"] = str(name).strip()

    result = sb.table("persons").update(update_body).eq("id", person_id).execute()
    if not result.data:
        raise ValueError("Update failed")
    _load_persons_cache(force=True)
    return result.data[0]


def upload_face_image(image_array: np.ndarray, person_id: str) -> str:
    sb = get_supabase()
    img = Image.fromarray(image_array.astype(np.uint8), mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    path = f"{person_id}/{uuid.uuid4()}.jpg"
    sb.storage.from_(settings.supabase_storage_bucket).upload(
        path, buf.read(), {"content-type": "image/jpeg"}
    )
    return sb.storage.from_(settings.supabase_storage_bucket).get_public_url(path)


def count_persons_by_role(role: str) -> int:
    sb = get_supabase()
    try:
        rows = sb.table("persons").select("id").eq("role", role).execute().data
        return len(rows) if rows else 0
    except Exception:
        return 0


def next_visitor_name() -> str:
    """Smallest unused Visitor N so deleted slots (e.g. Visitor 2) are reused."""
    sb = get_supabase()
    try:
        rows = sb.table("persons").select("name").eq("role", "person").execute().data
    except Exception:
        rows = []
    used_nums: set[int] = set()
    for r in rows or []:
        name = (r.get("name") or "").strip()
        m = re.match(r"(?i)^visitor\s*(\d+)\s*$", name)
        if m:
            used_nums.add(int(m.group(1)))
    n = 1
    while n in used_nums:
        n += 1
    return f"Visitor {n}"
