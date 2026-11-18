from datetime import timedelta

from livekit import api

from app._core.settings import settings
from app.components.utils.logger import log


class LiveKitService:
    """Singleton for LiveKit room management and token generation."""

    def __init__(self, url: str, api_key: str, api_secret: str):
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret
        # LiveKitAPI uses HTTP/Twirp — convert ws(s):// to http(s)://
        http_url = url.replace("ws://", "http://", 1).replace("wss://", "https://", 1)
        self._api = api.LiveKitAPI(url=http_url, api_key=api_key, api_secret=api_secret)

    async def create_room(self, room_name: str, empty_timeout: int = 600) -> str:
        """Create a LiveKit room, return room name."""
        room_info = await self._api.room.create_room(
            api.CreateRoomRequest(name=room_name, empty_timeout=empty_timeout, max_participants=4)
        )
        log.info("LiveKit room created: %s", room_info.name)
        return room_info.name

    async def delete_room(self, room_name: str) -> None:
        """Delete a LiveKit room."""
        await self._api.room.delete_room(api.DeleteRoomRequest(room=room_name))
        log.info("LiveKit room deleted: %s", room_name)

    def generate_token(self, room_name: str, identity: str, name: str, role: str) -> str:
        """Generate JWT token with role-based grants."""
        grants = _role_grants(role)
        grants.room = room_name
        grants.room_join = True

        token = (
            api.AccessToken(api_key=self.api_key, api_secret=self.api_secret)
            .with_identity(identity)
            .with_name(name)
            .with_grants(grants)
            .with_ttl(timedelta(hours=2))
        )
        return token.to_jwt()

    async def close(self) -> None:
        """Close underlying API client."""
        await self._api.aclose()


def _role_grants(role: str) -> api.VideoGrants:
    """Map role string to LiveKit VideoGrants."""
    if role == "candidate":
        return api.VideoGrants(can_publish=True, can_subscribe=True)
    if role == "interviewer_observer":
        return api.VideoGrants(can_publish=False, can_subscribe=True, hidden=True)
    if role == "interviewer_active":
        return api.VideoGrants(can_publish=True, can_subscribe=True)
    if role == "ai_bot":
        return api.VideoGrants(can_publish=True, can_subscribe=True)
    raise ValueError(f"Unknown LiveKit role: {role}")


_instance: LiveKitService | None = None


def init_livekit_service() -> None:
    """Initialize LiveKit singleton at startup."""
    global _instance
    if not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET:
        log.warning("LiveKit API key/secret not configured — LiveKit features disabled")
        return
    _instance = LiveKitService(
        url=settings.LIVEKIT_URL,
        api_key=settings.LIVEKIT_API_KEY,
        api_secret=settings.LIVEKIT_API_SECRET,
    )
    log.info("LiveKit service initialized: url=%s", settings.LIVEKIT_URL)


def get_livekit_service() -> LiveKitService:
    """Get the LiveKit singleton."""
    if _instance is None:
        raise RuntimeError("LiveKitService not initialized — call init_livekit_service() first")
    return _instance
