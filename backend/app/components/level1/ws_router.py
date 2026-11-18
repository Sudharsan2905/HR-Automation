"""WebSocket endpoints: /ws/interview/{submission_id} (candidate) and /ws/admin (monitoring).

Auth is the JWT in the ?token= query param (browsers cannot set WS headers).
Candidate protocol: client {"type":"ping","remaining_seconds":int,"current_question_idx":int};
server {"type":"connected"|"on_hold"|"resume_approved"|"terminated"|"pong"|"error"}.
"""

from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app._core.security import decode_access_token
from app.components.common.schemas import Role
from app.components.level1 import db as l1db
from app.components.level1.connection_manager import admin_manager, manager
from app.components.level1.constants import TERMINAL_STATUSES, SubmissionStatus
from app.components.utils.logger import log

ws_router = APIRouter()
_ADMIN_ROLES = {Role.SUPER_ADMIN.value, Role.INTERVIEWER.value}


def _decode(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        return decode_access_token(token)
    except Exception:
        return None


async def _find_submission(db, submission_id: str, candidate_id: str) -> dict | None:
    try:
        return await db[l1db.SUBMISSIONS].find_one({"_id": ObjectId(submission_id), "candidate_id": ObjectId(candidate_id)})
    except Exception:
        return None


async def _send_initial_state(websocket: WebSocket, sub: dict) -> None:
    if sub.get("status") == SubmissionStatus.ON_HOLD:
        await websocket.send_json({"type": "on_hold", "message": "Interview paused. Awaiting admin approval to resume."})
        return
    await websocket.send_json({
        "type": "connected", "status": str(sub.get("status")),
        "remaining_seconds": sub.get("remaining_seconds"), "current_question_idx": sub.get("current_question_idx", 0),
    })


async def _handle_ping(db, websocket: WebSocket, submission_id: str, data: dict) -> None:
    remaining = data.get("remaining_seconds")
    if remaining is not None:
        now = datetime.now(UTC)
        await db[l1db.SUBMISSIONS].update_one(
            {"_id": ObjectId(submission_id)},
            {"$set": {"remaining_seconds": int(remaining), "current_question_idx": int(data.get("current_question_idx", 0)),
                      "last_heartbeat": now, "updated_at": now}},
        )
    await websocket.send_json({"type": "pong"})


@ws_router.websocket("/ws/interview/{submission_id}")
async def interview_websocket(websocket: WebSocket, submission_id: str) -> None:
    """Live candidate session channel (Level 1 token)."""
    payload = _decode(websocket.query_params.get("token"))
    if not payload or payload.get("scope") != "l1" or not payload.get("sub"):
        await websocket.close(code=4001, reason="Unauthorized")
        return
    db = l1db.get_db()
    sub = await _find_submission(db, submission_id, payload["sub"])
    if not sub:
        await websocket.close(code=4004, reason="Submission not found")
        return
    if sub.get("status") in TERMINAL_STATUSES:
        await websocket.close(code=4003, reason="Session already ended")
        return
    await manager.connect(submission_id, websocket)
    try:
        await _send_initial_state(websocket, sub)
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await _handle_ping(db, websocket, submission_id, data)
    except WebSocketDisconnect:
        await manager.disconnect(submission_id, db)
    except Exception as exc:
        log.error("Level 1 WS error: submission_id=%s error=%s", submission_id, exc)
        await manager.disconnect(submission_id, db)


async def _handle_admin_message(websocket: WebSocket, data: dict) -> None:
    if data.get("type") == "ping":
        await websocket.send_json({"type": "pong"})
        return
    if data.get("type") != "warn_candidate":
        return
    target, message = data.get("submission_id", ""), (data.get("message") or "").strip()
    if not target or not message:
        return
    delivered = await manager.send_json(target, {"type": "admin_warning", "message": message})
    await websocket.send_json({"type": "warn_ack", "submission_id": target, "delivered": delivered})


@ws_router.websocket("/ws/admin")
async def admin_websocket(websocket: WebSocket) -> None:
    """Admin monitoring channel (malpractice events, candidate warnings)."""
    payload = _decode(websocket.query_params.get("token"))
    if not payload or not payload.get("sub") or payload.get("role") not in _ADMIN_ROLES:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    admin_id = payload["sub"]
    await websocket.accept()
    await websocket.send_json({"type": "connected", "role": payload["role"]})
    admin_manager.connect(admin_id, websocket)
    try:
        while True:
            await _handle_admin_message(websocket, await websocket.receive_json())
    except WebSocketDisconnect:
        admin_manager.disconnect(admin_id)
    except Exception as exc:
        log.error("Level 1 admin WS error: admin_id=%s error=%s", admin_id, exc)
        admin_manager.disconnect(admin_id)
