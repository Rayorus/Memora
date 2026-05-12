"""
routers/stream.py — WebSocket for real-time face tracking + recognition

Key behaviors:
- Detection runs every frame (~20-30ms with yunet)
- Recognition runs asynchronously in background threads
- Known faces are CONTINUOUSLY RE-VERIFIED every few seconds — wrong
  identities self-correct instead of being locked forever
- Unrecognized faces auto-register as unique visitors after sustained tracking
- Sends frame dimensions so the frontend overlay aligns correctly
"""
import json
import asyncio
import time
import logging
from typing import Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.face_pipeline import (
    identify_person_from_image,
    _b64_to_image,
    detect_faces,
    get_embedding,
    find_matching_person,
    find_matching_visitor_only,
    find_matching_patient_only,
    register_person,
    next_visitor_name,
    visitor_db_count,
    _load_persons_cache,
)
from services.supabase_client import get_supabase
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

EMA_ALPHA = 0.7
MATCH_IOU = 0.15
MAX_MISSES = 4
RECOGNITION_RETRY_FRAMES = 5
RECHECK_KNOWN_INTERVAL = 12
AUTO_REGISTER_AFTER_FRAMES = 30
AUTO_REGISTER_MIN_ATTEMPTS = 3
# Must match recognition strictness: only merge into an existing DB person if as
# confident as a normal match. (0.20 wrongly mapped every new face to "Sufiyaan".)
DUPLICATE_MERGE_THRESHOLD = float(settings.face_similarity_threshold or 0.42)
# Two boxes with IoU below this cannot be the same physical person → split duplicate IDs
SAME_PERSON_MAX_BOX_IOU = 0.28
# After one auto visitor while patient is in frame, wait before another (stops Visitor 3/4 spam)
VISITOR_AUTO_REG_COOLDOWN_FRAMES = 72
# Extra failed-ID attempts before creating a new visitor when Visitor 1..N already exist in DB
EXTRA_ATTEMPTS_WHEN_VISITORS_IN_DB = 5


def _iou(a: dict, b: dict) -> float:
    ax1, ay1 = a.get("x", 0), a.get("y", 0)
    ax2, ay2 = ax1 + a.get("w", 0), ay1 + a.get("h", 0)
    bx1, by1 = b.get("x", 0), b.get("y", 0)
    bx2, by2 = bx1 + b.get("w", 0), by1 + b.get("h", 0)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return float(inter / union) if union > 0 else 0.0


def _track_box_area(tr: dict[str, Any]) -> int:
    r = tr.get("display_region") or tr.get("region") or {}
    return int(max(0, r.get("w", 0) or 0) * max(0, r.get("h", 0) or 0))


def _entry_region_area(entry: dict[str, Any]) -> int:
    r = entry.get("region") or {}
    return int(max(0, r.get("w", 0) or 0) * max(0, r.get("h", 0) or 0))


def _dedupe_faces_out(faces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One box per known person_id (largest); drop overlapping unknown duplicates."""
    known = [f for f in faces if f.get("known") and f.get("person_id")]
    unknown = [f for f in faces if not (f.get("known") and f.get("person_id"))]

    best_by_pid: dict[str, dict[str, Any]] = {}
    for e in known:
        pid = str(e["person_id"])
        cur = best_by_pid.get(pid)
        if cur is None or _entry_region_area(e) > _entry_region_area(cur):
            best_by_pid[pid] = e
    merged_known = list(best_by_pid.values())

    unknown.sort(key=_entry_region_area, reverse=True)
    kept_u: list[dict[str, Any]] = []
    for e in unknown:
        r = e.get("region") or {}
        if any(_iou(r, u.get("region") or {}) > 0.42 for u in kept_u):
            continue
        kept_u.append(e)

    return merged_known + kept_u


def _split_same_identity_collision(
    tracks: dict[int, dict[str, Any]],
    frame_count: int,
    pending: dict[int, asyncio.Task],
    sb,
) -> None:
    """Two separate face boxes cannot share one person_id (stops twin strangers → 'Sufiyaan')."""
    visible = [
        (tid, tr)
        for tid, tr in tracks.items()
        if tr.get("last_seen") == frame_count
        and tr.get("known")
        and tr.get("person_id")
    ]
    by_pid: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for tid, tr in visible:
        pid = str(tr["person_id"])
        by_pid.setdefault(pid, []).append((tid, tr))

    for pid, group in by_pid.items():
        if len(group) < 2:
            continue
        regions = [
            g[1].get("display_region") or g[1].get("region") or {} for g in group
        ]
        max_iou = 0.0
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                max_iou = max(max_iou, _iou(regions[i], regions[j]))
        if max_iou >= SAME_PERSON_MAX_BOX_IOU:
            continue
        group_sorted = sorted(
            group,
            key=lambda x: float(x[1].get("match_similarity", 0)),
            reverse=True,
        )
        for loser_tid, loser_tr in group_sorted[1:]:
            loser_tr["known"] = False
            loser_tr["person_id"] = None
            loser_tr["name"] = None
            loser_tr["role"] = None
            loser_tr["last_interaction"] = None
            loser_tr["match_similarity"] = 0.0
            loser_tr["auto_reg_done"] = False
            loser_tr["recognition_attempts"] = max(
                loser_tr.get("recognition_attempts", 0), 99
            )
            loser_tr["last_verified"] = 0
            if loser_tid in pending:
                pending[loser_tid].cancel()
                del pending[loser_tid]
            crop = loser_tr.get("face_crop")
            if crop is not None:
                pending[loser_tid] = asyncio.create_task(
                    _auto_register_visitor(crop, sb, force_new=True)
                )
                loser_tr["last_attempt"] = frame_count
            logger.info(
                "Split shared identity %s: track %s → new visitor registration",
                pid,
                loser_tid,
            )


async def _recognize_and_fetch(crop, sb, interaction_cache):
    """Background: identify face + fetch last interaction."""
    match = await asyncio.to_thread(identify_person_from_image, crop)
    if not match:
        return None

    person_id = match["id"]
    cached = interaction_cache.get(person_id)
    if cached and (time.time() - cached.get("at", 0)) < 10:
        match["last_interaction"] = cached.get("data")
    else:
        try:
            rows = await asyncio.to_thread(
                lambda: sb.table("interactions")
                .select("summary, timestamp, image_url")
                .eq("person_id", person_id)
                .order("timestamp", desc=True)
                .limit(1)
                .execute()
                .data
            )
            last_int = rows[0] if rows else None
        except Exception:
            last_int = None
        interaction_cache[person_id] = {"at": time.time(), "data": last_int}
        match["last_interaction"] = last_int

    return match


async def _auto_register_visitor(crop, sb, *, force_new: bool = False):
    """Auto-register an unrecognized face as a new unique visitor.

    By default, merges into an existing person only if similarity ≥ DUPLICATE_MERGE_THRESHOLD
    (same bar as recognition). Use force_new after same-frame identity split so the second
    face does not incorrectly merge into another visitor — but we still try *patient-only*
    recovery so the same person on two tracks is not saved as Visitor N.
    """
    emb = await asyncio.to_thread(get_embedding, crop)
    if not emb:
        return None

    _load_persons_cache(force=True)
    main_thr = float(settings.face_similarity_threshold or 0.45)
    delta = float(getattr(settings, "face_patient_recovery_threshold_delta", 0.10) or 0.10)
    patient_recovery_thr = max(0.38, main_thr - delta)

    async def _try_patient_recovery() -> dict | None:
        return await asyncio.to_thread(
            find_matching_patient_only, emb, patient_recovery_thr
        )

    # After a split, force_new skips merging into arbitrary DB rows — but always try patient.
    if force_new:
        pm = await _try_patient_recovery()
        if pm:
            pm.setdefault("last_interaction", None)
            return pm

    if not force_new:
        near_match = await asyncio.to_thread(
            find_matching_person, emb, DUPLICATE_MERGE_THRESHOLD
        )
        if near_match:
            near_match.setdefault("last_interaction", None)
            return near_match
        # Strict match failed (threshold or visitor/patient ambiguity) — still try patient alone.
        pm = await _try_patient_recovery()
        if pm:
            pm.setdefault("last_interaction", None)
            return pm
        # Prefer matching an existing visitor before minting Visitor N+1 (strict main threshold failed)
        vcount = await asyncio.to_thread(visitor_db_count)
        if vcount >= 1:
            lo = max(0.38, DUPLICATE_MERGE_THRESHOLD - 0.04)
            vmatch = await asyncio.to_thread(
                find_matching_visitor_only, emb, lo
            )
            if vmatch:
                vmatch.setdefault("last_interaction", None)
                return vmatch

    visitor_name = await asyncio.to_thread(next_visitor_name)

    result = await asyncio.to_thread(
        register_person, emb, "person", visitor_name
    )
    logger.info("Auto-registered %s (id=%s)", visitor_name, result["id"])
    return {
        "id": result["id"],
        "name": result.get("name", visitor_name),
        "role": "person",
        "match_similarity": 1.0,
        "last_interaction": None,
    }


@router.websocket("/frame")
async def frame_stream(websocket: WebSocket):
    await websocket.accept()

    sb = get_supabase()
    interaction_cache: dict[str, dict[str, Any]] = {}

    tracks: dict[int, dict[str, Any]] = {}
    next_track_id = 1
    frame_count = 0
    pending: dict[int, asyncio.Task] = {}
    last_visitor_auto_schedule_frame = 0

    try:
        while True:
            data = await websocket.receive_text()
            frame_count += 1
            b64 = json.loads(data).get("frame", "")

            try:
                img = _b64_to_image(b64)
            except Exception as e:
                await websocket.send_text(json.dumps({"faces": [], "error": str(e)}))
                continue

            frame_h, frame_w = img.shape[:2]

            try:
                detections = await asyncio.to_thread(
                    detect_faces, img, enforce_detection=False
                )
            except Exception:
                detections = []

            detections.sort(
                key=lambda d: float(d.get("confidence", 1.0)), reverse=True
            )

            # --- Track association (greedy IoU) ---
            matched_tids: set[int] = set()
            unmatched: list[dict] = []

            for det in detections:
                region = det.get("facial_area") or {}
                if not region:
                    continue
                best_tid, best_score = None, 0.0
                for tid, tr in tracks.items():
                    if tid in matched_tids:
                        continue
                    s = _iou(region, tr.get("display_region") or tr.get("region", {}))
                    if s > best_score:
                        best_score = s
                        best_tid = tid

                if best_tid is not None and best_score >= MATCH_IOU:
                    matched_tids.add(best_tid)
                    tr = tracks[best_tid]
                    old = tr.get("display_region", region)
                    a = EMA_ALPHA
                    tr["display_region"] = {
                        "x": int(round(a * region["x"] + (1 - a) * old["x"])),
                        "y": int(round(a * region["y"] + (1 - a) * old["y"])),
                        "w": int(round(a * region["w"] + (1 - a) * old["w"])),
                        "h": int(round(a * region["h"] + (1 - a) * old["h"])),
                    }
                    tr["region"] = region
                    tr["face_crop"] = det.get("face")
                    tr["confidence"] = float(det.get("confidence", 1.0))
                    tr["misses"] = 0
                    tr["last_seen"] = frame_count
                else:
                    unmatched.append(det)

            # --- New tracks ---
            for det in unmatched:
                region = det.get("facial_area") or {}
                if not region:
                    continue
                tid = next_track_id
                next_track_id += 1
                tracks[tid] = {
                    "region": region,
                    "display_region": dict(region),
                    "face_crop": det.get("face"),
                    "confidence": float(det.get("confidence", 1.0)),
                    "known": False,
                    "person_id": None,
                    "name": None,
                    "role": None,
                    "last_interaction": None,
                    "match_similarity": 0.0,
                    "misses": 0,
                    "last_seen": frame_count,
                    "created_at": frame_count,
                    "last_attempt": 0,
                    "last_verified": 0,
                    "recognition_attempts": 0,
                    "auto_reg_done": False,
                }
                crop = det.get("face")
                if crop is not None:
                    pending[tid] = asyncio.create_task(
                        _recognize_and_fetch(crop, sb, interaction_cache)
                    )
                    tracks[tid]["last_attempt"] = frame_count

            # --- Stale track removal ---
            for tid in list(tracks.keys()):
                if tracks[tid].get("last_seen") != frame_count:
                    tracks[tid]["misses"] = tracks[tid].get("misses", 0) + 1
                    if tracks[tid]["misses"] > MAX_MISSES:
                        del tracks[tid]
                        if tid in pending:
                            pending[tid].cancel()
                            del pending[tid]

            # --- Collect completed tasks ---
            for tid in list(pending.keys()):
                task = pending[tid]
                if not task.done():
                    continue
                try:
                    result = task.result()
                except Exception:
                    result = None

                if result and tid in tracks:
                    tr = tracks[tid]
                    new_sim = result.get("match_similarity", 0)

                    should_update = (
                        not tr.get("known")
                        or result["id"] != tr.get("person_id")
                    )

                    if should_update:
                        tr["known"] = True
                        tr["person_id"] = result["id"]
                        name = result.get("name")
                        tr["name"] = name if name else "Person"
                        tr["role"] = result.get("role")
                        tr["last_interaction"] = result.get("last_interaction")
                        tr["match_similarity"] = new_sim

                    tr["last_verified"] = frame_count
                elif tid in tracks and not tracks[tid].get("known"):
                    tracks[tid]["recognition_attempts"] = (
                        tracks[tid].get("recognition_attempts", 0) + 1
                    )

                del pending[tid]

            patient_in_frame = any(
                tr.get("last_seen") == frame_count
                and tr.get("known")
                and (tr.get("role") or "").lower() == "patient"
                for tr in tracks.values()
            )
            known_visitor_in_frame = any(
                tr.get("last_seen") == frame_count
                and tr.get("known")
                and (tr.get("role") or "").lower() == "person"
                for tr in tracks.values()
            )
            unknown_visible = [
                (tid, tr)
                for tid, tr in tracks.items()
                if tr.get("last_seen") == frame_count and not tr.get("known")
            ]
            unknown_visible.sort(key=lambda x: _track_box_area(x[1]), reverse=True)
            primary_unknown_tid = unknown_visible[0][0] if unknown_visible else None

            try:
                visitors_in_db = visitor_db_count()
            except Exception:
                visitors_in_db = 0

            min_attempts_for_auto = AUTO_REGISTER_MIN_ATTEMPTS
            if patient_in_frame and visitors_in_db >= 1:
                min_attempts_for_auto = (
                    AUTO_REGISTER_MIN_ATTEMPTS + EXTRA_ATTEMPTS_WHEN_VISITORS_IN_DB
                )

            # --- Schedule recognition / re-verification / auto-registration ---
            for tid, tr in tracks.items():
                if tid in pending or tr.get("last_seen") != frame_count:
                    continue

                if tr.get("known"):
                    # Continuously re-verify known faces
                    if (frame_count - tr.get("last_verified", 0)) >= RECHECK_KNOWN_INTERVAL:
                        crop = tr.get("face_crop")
                        if crop is not None:
                            pending[tid] = asyncio.create_task(
                                _recognize_and_fetch(crop, sb, interaction_cache)
                            )
                            tr["last_verified"] = frame_count
                else:
                    frames_alive = frame_count - tr.get("created_at", frame_count)
                    attempts = tr.get("recognition_attempts", 0)

                    if (
                        not tr.get("auto_reg_done")
                        and attempts >= min_attempts_for_auto
                        and frames_alive >= AUTO_REGISTER_AFTER_FRAMES
                    ):
                        if (
                            patient_in_frame
                            and known_visitor_in_frame
                            and primary_unknown_tid is not None
                            and tid != primary_unknown_tid
                        ):
                            pass
                        elif patient_in_frame and (
                            known_visitor_in_frame or visitors_in_db >= 1
                        ) and (
                            frame_count - last_visitor_auto_schedule_frame
                            < VISITOR_AUTO_REG_COOLDOWN_FRAMES
                        ):
                            pass
                        else:
                            tr["auto_reg_done"] = True
                            last_visitor_auto_schedule_frame = frame_count
                            crop = tr.get("face_crop")
                            if crop is not None:
                                pending[tid] = asyncio.create_task(
                                    _auto_register_visitor(crop, sb)
                                )
                                tr["last_attempt"] = frame_count
                    elif (frame_count - tr.get("last_attempt", 0)) >= RECOGNITION_RETRY_FRAMES:
                        crop = tr.get("face_crop")
                        if crop is not None:
                            pending[tid] = asyncio.create_task(
                                _recognize_and_fetch(crop, sb, interaction_cache)
                            )
                            tr["last_attempt"] = frame_count

            _split_same_identity_collision(tracks, frame_count, pending, sb)

            # --- Build response ---
            faces_out: list[dict[str, Any]] = []
            for tid, tr in tracks.items():
                if tr.get("last_seen") != frame_count:
                    continue
                region = tr.get("display_region") or tr.get("region") or {}
                entry: dict[str, Any] = {
                    "track_id": tid,
                    "confidence": float(tr.get("confidence", 1.0)),
                    "region": region,
                }
                if tr.get("known"):
                    raw_role = tr.get("role")
                    norm_role = (
                        str(raw_role).strip().lower()
                        if raw_role is not None and str(raw_role).strip()
                        else None
                    )
                    entry.update({
                        "known": True,
                        "person_id": tr["person_id"],
                        "name": tr["name"],
                        "role": norm_role,
                        "last_interaction": tr.get("last_interaction"),
                    })
                else:
                    entry.update({
                        "known": False,
                        "name": "Analyzing...",
                    })
                faces_out.append(entry)

            faces_out = _dedupe_faces_out(faces_out)

            await websocket.send_text(json.dumps({
                "faces": faces_out,
                "frame_w": frame_w,
                "frame_h": frame_h,
            }))

    except WebSocketDisconnect:
        for task in pending.values():
            task.cancel()
