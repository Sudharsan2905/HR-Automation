"""Local-disk file storage for proctoring evidence (same idea as an object store)."""

import asyncio
import mimetypes
from pathlib import Path

from fastapi import HTTPException

from app._core.settings import settings


def _root() -> Path:
    root = Path(settings.LEVEL1_STORAGE_PATH).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve(key: str) -> Path:
    path = (_root() / key).resolve()
    if _root() not in path.parents:
        raise HTTPException(400, "Invalid storage key")
    return path


def make_screenshot_key(submission_id: str, round_number: int, stamp: str) -> str:
    """Build the storage key for a periodic screenshot."""
    return f"screenshots/{submission_id}/r{round_number}/{_safe(stamp)}.jpg"


def make_evidence_key(submission_id: str, round_number: int, kind: str, evidence: str, stamp: str) -> str:
    """Build the storage key for malpractice evidence."""
    return f"evidence/{submission_id}/r{round_number}/{_safe(kind)}_{_safe(evidence)}_{_safe(stamp)}.jpg"


def _safe(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in str(value))


async def upload(data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
    """Write ``data`` under ``key`` and return the key."""
    path = _resolve(key)

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    await asyncio.to_thread(_write)
    return key


async def get_bytes(key: str) -> tuple[bytes, str]:
    """Return (content, content_type) for ``key``."""
    path = _resolve(key)
    if not path.is_file():
        raise HTTPException(404, "File not found")
    content = await asyncio.to_thread(path.read_bytes)
    return content, mimetypes.guess_type(path.name)[0] or "image/jpeg"


async def delete(key: str) -> None:
    """Remove ``key`` if present."""
    path = _resolve(key)
    await asyncio.to_thread(path.unlink, True)
