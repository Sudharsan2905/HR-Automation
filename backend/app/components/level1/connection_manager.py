"""WebSocket connection managers for live exam sessions and admin monitoring."""

import asyncio

from fastapi import WebSocket
from motor.motor_asyncio import AsyncIOMotorDatabase

from app._core.settings import settings
from app.components.utils.logger import log


class ConnectionManager:
    """Tracks one candidate socket per submission and schedules ON_HOLD after a drop."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._hold_tasks: dict[str, asyncio.Task] = {}

    async def connect(self, submission_id: str, websocket: WebSocket) -> None:
        """Accept a socket and cancel any pending ON_HOLD task."""
        await websocket.accept()
        self._connections[submission_id] = websocket
        await self._cancel_hold_task(submission_id)

    async def disconnect(self, submission_id: str, db: AsyncIOMotorDatabase) -> None:
        """Unregister a socket and schedule the ON_HOLD transition."""
        self._connections.pop(submission_id, None)
        task = asyncio.create_task(self._hold_after_delay(submission_id, db), name=f"hold-{submission_id}")
        self._hold_tasks[submission_id] = task

    async def send_json(self, submission_id: str, data: dict) -> bool:
        """Push a JSON message to the candidate; False when offline."""
        ws = self._connections.get(submission_id)
        if not ws:
            return False
        try:
            await ws.send_json(data)
            return True
        except Exception:
            self._connections.pop(submission_id, None)
            return False

    def is_connected(self, submission_id: str) -> bool:
        """Whether the candidate currently has a live socket."""
        return submission_id in self._connections

    async def _cancel_hold_task(self, submission_id: str) -> None:
        task = self._hold_tasks.pop(submission_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _hold_after_delay(self, submission_id: str, db: AsyncIOMotorDatabase) -> None:
        try:
            await asyncio.sleep(settings.LEVEL1_HOLD_DELAY_SECONDS)
        except asyncio.CancelledError:
            return
        if submission_id not in self._connections:
            from app.components.level1.candidate_service import put_session_on_hold

            await put_session_on_hold(db, submission_id)
        self._hold_tasks.pop(submission_id, None)


class AdminConnectionManager:
    """Admin sockets that receive live malpractice/status events."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    def connect(self, admin_id: str, websocket: WebSocket) -> None:
        """Register an admin socket."""
        self._connections[admin_id] = websocket
        log.info("Level 1 admin WS connected: admin_id=%s", admin_id)

    def disconnect(self, admin_id: str) -> None:
        """Remove an admin socket."""
        self._connections.pop(admin_id, None)

    async def broadcast_event(self, event: dict) -> None:
        """Send an event to every connected admin."""
        gone = []
        for admin_id, ws in self._connections.items():
            try:
                await ws.send_json(event)
            except Exception:
                gone.append(admin_id)
        for admin_id in gone:
            self._connections.pop(admin_id, None)


manager = ConnectionManager()
admin_manager = AdminConnectionManager()
