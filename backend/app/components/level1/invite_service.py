"""Send each candidate ONE invite email: exam link, username and Level 1 access key."""

import html

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app._core.settings import settings
from app.components.auth.models import User
from app.components.auth.service import issue_level1_key
from app.components.common.schemas import Role
from app.components.level1 import db as l1db
from app.components.level1.mailer import send_email
from app.components.level1.utils import utcnow


def _shell(inner: str) -> str:
    return (
        '<div style="font-family:Inter,Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px">'
        '<div style="background:#2563EB;padding:18px 28px;border-radius:8px 8px 0 0">'
        f'<h1 style="color:#fff;margin:0;font-size:20px">{html.escape(settings.APP_NAME)}</h1></div>'
        '<div style="background:#fff;padding:28px;border:1px solid #e2e8f0;'
        f'border-radius:0 0 8px 8px;color:#334155;font-size:15px">{inner}</div></div>'
    )


def exam_url(share_link: str) -> str:
    """Public exam URL for a share link."""
    return f"{settings.APP_URL.rstrip('/')}/exam/{share_link}"


def build_invite_html(name: str, title: str, link: str, email: str, key: str) -> str:
    """Invite email body."""
    return _shell(
        f"<p>Hello {html.escape(name or '')},</p>"
        f"<p>You have been shortlisted for the <b>{html.escape(title)}</b> role and are invited to a "
        "proctored online assessment.</p>"
        "<p><b>Your login details</b></p>"
        f"<p>Username (email): <b>{html.escape(email)}</b><br/>"
        f"Access key: <b>{html.escape(key)}</b></p>"
        f'<p><a href="{html.escape(link)}" style="background:#2563EB;color:#fff;padding:12px 24px;'
        'border-radius:8px;text-decoration:none;font-weight:600">Start Assessment</a></p>'
        f'<p style="font-size:13px;color:#64748b">Or open this link: <a href="{html.escape(link)}">{html.escape(link)}</a></p>'
        f"<p>The access key is valid for {settings.LEVEL1_KEY_TTL_HOURS} hours or until you submit the exam. "
        "The exam is strictly monitored (camera, microphone, screen and tab switching). "
        "Please keep your key private. This email was sent only to you.</p>"
    )


async def _mark(db: AsyncIOMotorDatabase, cand_id: ObjectId, **fields: object) -> None:
    await db[l1db.PIPELINE_CANDIDATES].update_one(
        {"_id": cand_id}, {"$set": {**fields, "updated_at": utcnow()}}
    )


async def _invite_one(db: AsyncIOMotorDatabase, pipeline: dict, cand: dict, link: str) -> bool | None:
    """Invite one candidate; True/False for sent/failed, None when blocked."""
    user = await User.get(cand["user_id"]) if cand.get("user_id") else None
    if user is None or user.role != Role.CANDIDATE:
        await _mark(
            db, cand["_id"], invite_status="failed", failed_step="invites",
            error="This email belongs to a non-candidate account; not modified",
        )
        return None
    key = await issue_level1_key(user)
    body = build_invite_html(cand.get("name") or user.full_name or "", pipeline["jd_title"], link, user.email, key)
    ok = await send_email(user.email, f"Assessment Invitation: {pipeline['jd_title']}", body)
    await _mark(db, cand["_id"], invite_status="sent" if ok else "failed",
                status="invited" if ok else cand["status"])
    await db[l1db.PIPELINES].update_one(
        {"_id": pipeline["_id"], "steps.key": "invites"},
        {"$inc": {"steps.$.progress.done": 1 if ok else 0}},
    )
    return ok


async def send_invites(db: AsyncIOMotorDatabase, pipeline_id: str, candidate_ids: list[ObjectId] | None = None) -> dict:
    """Invite every candidate with an email that has not been invited yet."""
    pipeline = await db[l1db.PIPELINES].find_one({"_id": ObjectId(pipeline_id)})
    if not pipeline or not pipeline.get("share_link"):
        return {"invited": 0, "failed": 0}
    query: dict = {"pipeline_id": pipeline["_id"], "email": {"$ne": None}, "invite_status": {"$ne": "sent"}}
    if candidate_ids is not None:
        query["_id"] = {"$in": candidate_ids}
    cands = await db[l1db.PIPELINE_CANDIDATES].find(query).to_list(None)
    link = exam_url(pipeline["share_link"])
    outcomes = [await _invite_one(db, pipeline, c, link) for c in cands]
    return {"invited": outcomes.count(True), "failed": len(outcomes) - outcomes.count(True)}
