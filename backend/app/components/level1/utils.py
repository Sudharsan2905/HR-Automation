"""Small shared helpers (time, ids, BSON serialization)."""

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException


def utcnow() -> datetime:
    """Current UTC time."""
    return datetime.now(UTC)


def oid(value: str | ObjectId, label: str = "id") -> ObjectId:
    """Parse an ObjectId or raise HTTP 422."""
    try:
        return ObjectId(str(value))
    except Exception as exc:
        raise HTTPException(422, f"Invalid {label}") from exc


def _serialize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return serialize_doc(value)
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def serialize_doc(doc: dict | None) -> dict:
    """Convert a Mongo document into JSON-safe data (``_id`` becomes ``id``)."""
    if doc is None:
        return {}
    return {("id" if k == "_id" else k): _serialize_value(v) for k, v in doc.items()}
