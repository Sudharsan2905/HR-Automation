import asyncio
from datetime import datetime, timezone

from fastapi import HTTPException

from app._core.settings import settings
from app.components.auth.blacklist import blacklist_token
from app.components.auth.models import User
from app.components.common.schemas import InterviewStatus
from app.components.interview.models import Interview
from app.components.question_set.models import QuestionSet
from app.components.session.ai_bot import AIBot
from app.components.session.models import SessionLog
from app.components.session.transcript import Transcript
from app.components.utils.livekit_service import get_livekit_service
from app.components.utils.logger import log


# Active AI bots keyed by interview_id
_active_bots: dict[str, AIBot] = {}


async def _get_active_session(candidate_id: str) -> SessionLog:
    """Fetch active session or raise 404."""
    session = await SessionLog.find_one(
        SessionLog.candidate_id == candidate_id,
        SessionLog.is_active == True,
    )
    if not session:
        raise HTTPException(404, "No active session. Start a session first.")
    return session


async def start_session(candidate_id: str, jwt_jti: str, camera_available: bool = True) -> dict:
    """Start or resume an interview session with LiveKit room."""
    # Check for existing active session
    existing = await SessionLog.find_one(
        SessionLog.candidate_id == candidate_id,
        SessionLog.is_active == True,
    )
    if existing:
        interview = await Interview.get(existing.interview_id)
        if not interview:
            log.warning("Stale session %s references deleted interview %s — deactivating", existing.id, existing.interview_id)
            existing.is_active = False
            existing.completed_at = datetime.now(timezone.utc)
            await existing.save()
        else:
            qs = await QuestionSet.get(interview.question_set_id)
            interviewer = await User.get(interview.interviewer_id)
            user = await User.get(candidate_id)

            # Generate fresh token for the existing room
            lk = get_livekit_service()
            token = lk.generate_token(
                existing.livekit_room_name,
                identity=f"candidate-{candidate_id}",
                name=user.full_name if user and user.full_name else "Candidate",
                role="candidate",
            )

            # Resume AIBot if not running
            if existing.interview_id not in _active_bots:
                await _spawn_ai_bot(existing.interview_id, qs, existing.livekit_room_name, existing.current_question_index, is_resume=True)

            return {
                "session_id": str(existing.id),
                "interview_id": existing.interview_id,
                "total_questions": len(qs.questions) if qs else 0,
                "current_question_index": existing.current_question_index,
                "resumed": True,
                "camera_available": existing.camera_available,
                "room_name": existing.livekit_room_name,
                "token": token,
                "livekit_url": settings.LIVEKIT_CLIENT_URL or settings.LIVEKIT_URL,
                "interview_title": qs.title if qs else "",
                "interviewer_name": interviewer.full_name if interviewer and interviewer.full_name else "Panel",
                "candidate_name": user.full_name if user and user.full_name else "Candidate",
                "domain": qs.domain if qs else "",
                "domain_title": qs.domain_title if qs else "",
            }

    # New session
    user = await User.get(candidate_id)
    if not user:
        raise HTTPException(404, "User not found")

    interview = await Interview.find_one(
        Interview.candidate_mail == user.email,
        Interview.status == InterviewStatus.FINALIZED,
    )
    if not interview:
        raise HTTPException(404, "Interview not available. Contact your panel member.")

    qs = await QuestionSet.get(interview.question_set_id)
    if not qs:
        raise HTTPException(404, "Question set not found")

    interviewer = await User.get(interview.interviewer_id)
    interview_id = str(interview.id)

    # Create LiveKit room
    lk = get_livekit_service()
    room_name = f"interview_{interview_id}"
    await lk.create_room(room_name)

    # Generate candidate token
    token = lk.generate_token(
        room_name,
        identity=f"candidate-{candidate_id}",
        name=user.full_name if user and user.full_name else "Candidate",
        role="candidate",
    )

    # Create session log
    session = SessionLog(
        interview_id=interview_id,
        candidate_id=candidate_id,
        camera_available=camera_available,
        jwt_jti=jwt_jti,
        livekit_room_name=room_name,
    )
    await session.insert()

    # Set interview as live
    interview.is_live = True
    interview.updated_at = datetime.now(timezone.utc)
    await interview.save()

    # Spawn AI bot in background
    await _spawn_ai_bot(interview_id, qs, room_name)

    log.info("Session started: candidate=%s, interview=%s, room=%s", candidate_id, interview_id, room_name)
    return {
        "session_id": str(session.id),
        "interview_id": interview_id,
        "total_questions": len(qs.questions),
        "current_question_index": 0,
        "resumed": False,
        "camera_available": camera_available,
        "room_name": room_name,
        "token": token,
        "livekit_url": settings.LIVEKIT_CLIENT_URL or settings.LIVEKIT_URL,
        "interview_title": qs.title,
        "interviewer_name": interviewer.full_name if interviewer and interviewer.full_name else "Panel",
        "candidate_name": user.full_name if user and user.full_name else "Candidate",
        "domain": qs.domain,
        "domain_title": qs.domain_title,
    }


async def get_progress(candidate_id: str) -> dict:
    """Get session progress including AI speaking state."""
    session = await _get_active_session(candidate_id)
    interview = await Interview.get(session.interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")
    qs = await QuestionSet.get(interview.question_set_id)
    total = len(qs.questions) if qs else 0

    bot = _active_bots.get(session.interview_id)
    if bot:
        current_idx = bot.current_question_index
        ai_speaking = bot.speaking
        bot_finished = bot.finished
        bot_active = not bot.errored
    else:
        current_idx = session.current_question_index
        ai_speaking = False
        bot_finished = current_idx >= total - 1 and not session.is_active
        # Session still active means bot hasn't been dispatched yet (candidate waiting at lobby).
        # Only report bot_active=False when the session has already begun (index > 0 or inactive).
        bot_active = session.is_active and current_idx == 0

    # Clamp index to total so FE never sees 7/6
    current_idx = min(current_idx, total - 1) if total > 0 else 0

    return {
        "current_question_index": current_idx,
        "total_questions": total,
        "ai_speaking": ai_speaking,
        "ai_paused": session.ai_paused,
        "finished": bot_finished,
        "bot_active": bot_active,
    }


async def next_question(candidate_id: str) -> dict:
    """Signal AI bot to speak next question."""
    session = await _get_active_session(candidate_id)
    bot = _active_bots.get(session.interview_id)
    if not bot or bot.errored:
        raise HTTPException(400, "AI bot not active")
    if bot.speaking:
        raise HTTPException(400, "AI is still speaking, please wait")
    if bot.paused:
        raise HTTPException(400, "AI is paused by panel")

    result = bot.advance()

    # Persist progress
    session.current_question_index = bot.current_question_index
    await session.save()

    return result


async def complete_session(candidate_id: str, jwt_jti: str, jwt_exp: int) -> dict:
    """Complete session — disconnect bot, close room, trigger evaluation."""
    session = await _get_active_session(candidate_id)
    interview = await Interview.get(session.interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")

    interview_id = session.interview_id

    # Capture bot state BEFORE popping to detect partial completion
    bot = _active_bots.pop(interview_id, None)
    ai_finished = bot.finished if bot else False
    if bot:
        await bot.disconnect()

    # If bot ref was gone, fall back to index comparison
    if not bot:
        qs_check = await QuestionSet.get(interview.question_set_id)
        total_q = len(qs_check.questions) if qs_check else 0
        ai_finished = total_q == 0 or session.current_question_index >= total_q - 1

    # Close LiveKit room
    if session.livekit_room_name:
        try:
            lk = get_livekit_service()
            await lk.delete_room(session.livekit_room_name)
        except Exception as e:
            log.warning("Failed to delete LiveKit room %s: %s", session.livekit_room_name, e)

    # Update session
    session.is_active = False
    session.completed_at = datetime.now(timezone.utc)
    await session.save()

    # Update interview — COMPLETED if all AI questions finished, else PARTIALLY_COMPLETED
    interview.status = InterviewStatus.COMPLETED if ai_finished else InterviewStatus.PARTIALLY_COMPLETED
    interview.is_live = False
    interview.updated_at = datetime.now(timezone.utc)
    await interview.save()

    # Blacklist JWT
    exp_dt = datetime.fromtimestamp(jwt_exp, tz=timezone.utc)
    await blacklist_token(jwt_jti, exp_dt)

    log.info("Session completed: candidate=%s, interview=%s", candidate_id, interview_id)
    return {"message": "Interview completed. You will be logged out.", "interview_id": interview_id}


async def get_watch_token(interview_id: str, interviewer_id: str, is_admin: bool = False) -> dict:
    """Generate observer token for interviewer/admin to watch a live session."""
    interview = await Interview.get(interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")
    if not is_admin and interview.interviewer_id != interviewer_id:
        raise HTTPException(403, "Not your interview")
    if not interview.is_live:
        raise HTTPException(400, "Interview is not live")

    session = await SessionLog.find_one(
        SessionLog.interview_id == interview_id,
        SessionLog.is_active == True,
    )
    if not session or not session.livekit_room_name:
        raise HTTPException(404, "No active session found")

    interviewer = await User.get(interviewer_id)
    lk = get_livekit_service()
    token = lk.generate_token(
        session.livekit_room_name,
        identity=f"interviewer-{interviewer_id}",
        name=interviewer.full_name if interviewer and interviewer.full_name else "Panel",
        role="interviewer_observer",
    )

    return {
        "room_name": session.livekit_room_name,
        "token": token,
        "livekit_url": settings.LIVEKIT_CLIENT_URL or settings.LIVEKIT_URL,
    }


async def join_as_interviewer(interview_id: str, interviewer_id: str, is_admin: bool = False) -> dict:
    """Upgrade interviewer/admin from observer to active participant."""
    interview = await Interview.get(interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")
    if not is_admin and interview.interviewer_id != interviewer_id:
        raise HTTPException(403, "Not your interview")
    if not interview.is_live:
        raise HTTPException(400, "Interview is not live")

    session = await SessionLog.find_one(
        SessionLog.interview_id == interview_id,
        SessionLog.is_active == True,
    )
    if not session or not session.livekit_room_name:
        raise HTTPException(404, "No active session found")

    session.interviewer_joined = True
    await session.save()

    interviewer = await User.get(interviewer_id)
    lk = get_livekit_service()
    token = lk.generate_token(
        session.livekit_room_name,
        identity=f"interviewer-{interviewer_id}",
        name=interviewer.full_name if interviewer and interviewer.full_name else "Panel",
        role="interviewer_active",
    )

    return {
        "room_name": session.livekit_room_name,
        "token": token,
        "livekit_url": settings.LIVEKIT_CLIENT_URL or settings.LIVEKIT_URL,
    }


async def pause_ai_by_interviewer(interview_id: str, interviewer_id: str, is_admin: bool = False) -> dict:
    """Pause the AI bot (interviewer or admin)."""
    interview = await Interview.get(interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")
    if not is_admin and interview.interviewer_id != interviewer_id:
        raise HTTPException(403, "Not your interview")

    bot = _active_bots.get(interview_id)
    if bot:
        bot.pause()

    session = await SessionLog.find_one(
        SessionLog.interview_id == interview_id,
        SessionLog.is_active == True,
    )
    if session:
        session.ai_paused = True
        await session.save()

    return {"message": "AI paused"}


async def resume_ai_by_interviewer(interview_id: str, interviewer_id: str, is_admin: bool = False) -> dict:
    """Resume the AI bot (interviewer or admin)."""
    interview = await Interview.get(interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")
    if not is_admin and interview.interviewer_id != interviewer_id:
        raise HTTPException(403, "Not your interview")

    bot = _active_bots.get(interview_id)
    if bot:
        bot.resume()

    session = await SessionLog.find_one(
        SessionLog.interview_id == interview_id,
        SessionLog.is_active == True,
    )
    if session:
        session.ai_paused = False
        await session.save()

    return {"message": "AI resumed"}


# --- Internal helpers ---

async def _spawn_ai_bot(interview_id: str, qs: QuestionSet, room_name: str, resume_index: int = 0, *, is_resume: bool = False) -> None:
    """Spawn AIBot as background asyncio task."""
    lk = get_livekit_service()
    bot_token = lk.generate_token(
        room_name,
        identity=f"suvera-ai-{interview_id}",
        name="Suvera AI",
        role="ai_bot",
    )

    bot = AIBot(interview_id, qs, settings.LIVEKIT_URL, bot_token, wait_for_start=(not is_resume))
    bot.current_question_index = resume_index
    _active_bots[interview_id] = bot

    async def _run_bot():
        try:
            await bot.connect()
            await bot.run()
        except Exception as e:
            log.error("AIBot crashed for interview=%s: %s", interview_id, e, exc_info=True)
            bot.errored = True
            # Best-effort disconnect to release the LiveKit room slot
            try:
                await bot.disconnect()
            except Exception:
                pass
        finally:
            if bot.finished:
                log.info("AIBot completed all questions for interview=%s", interview_id)
            elif not bot.errored:
                # Normal graceful exit (disconnect called externally)
                _active_bots.pop(interview_id, None)
            # Errored bots stay in dict so get_progress can report bot_active=False.
            # They are cleaned up by complete_session or cleanup_all_bots on shutdown.

    asyncio.create_task(_run_bot())
    log.info("AIBot spawned: interview=%s, room=%s, resume_idx=%d", interview_id, room_name, resume_index)


async def cleanup_all_bots() -> None:
    """Disconnect all active bots — called on shutdown."""
    for interview_id, bot in list(_active_bots.items()):
        try:
            await bot.disconnect()
        except Exception:
            pass
    _active_bots.clear()


# ---------------------------------------------------------------------------
# Audio check — lobby mic & speaker test
# ---------------------------------------------------------------------------

import json
import random
from pathlib import Path

_JOKES_FILE = Path(__file__).parent / "jokes.json"
_jokes: list[dict] | None = None

_CONFIRM_RESPONSE = "😂 Ha haa! Got your joke! Your mic and speaker are working perfectly. All the best for your interview, go ahead!"


def _load_jokes() -> list[dict]:
    global _jokes
    if _jokes is None:
        _jokes = json.loads(_JOKES_FILE.read_text(encoding="utf-8"))
    return _jokes


async def _save_joke_audio(path: Path, data: bytes) -> None:
    """Persist TTS audio to disk so each joke is only synthesized once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    log.info("Cached joke audio: %s", path.name)


async def get_audio_check() -> dict:
    """Pick a random static joke, serve cached MP3 or generate+cache on first use."""
    import base64
    from app.components.utils.tts_client import get_tts_client

    joke = random.choice(_load_jokes())
    audio_path = Path(settings.AUDIO_CACHE_PATH) / "jokes" / f"{joke['unique_id']}.mp3"

    if audio_path.exists():
        joke_audio = audio_path.read_bytes()
    else:
        joke_audio = await get_tts_client().synthesize(joke["question"], response_format="mp3")
        asyncio.ensure_future(_save_joke_audio(audio_path, joke_audio))

    response_path = Path(settings.AUDIO_CACHE_PATH) / "jokes" / "suvera_response.mp3"
    if response_path.exists():
        response_audio = response_path.read_bytes()
    else:
        response_audio = await get_tts_client().synthesize(_CONFIRM_RESPONSE, response_format="mp3")
        asyncio.ensure_future(_save_joke_audio(response_path, response_audio))

    return {
        "question": joke["question"],
        "punchline": joke["punchline"],
        "question_audio": base64.b64encode(joke_audio).decode(),
        "response_audio": base64.b64encode(response_audio).decode(),
    }


