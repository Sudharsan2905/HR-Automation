import asyncio
import io
import json
import struct
from datetime import datetime, timezone

from livekit import rtc

from app.components.question_set.models import QuestionSet
from app.components.session.transcript import Transcript
from app.components.utils.logger import log
from app.components.utils.stt_client import get_stt_client
from app.components.utils.tts_client import get_tts_client

SAMPLE_RATE = 24000
NUM_CHANNELS = 1
FRAME_DURATION_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_DURATION_MS // 1000

# Silence threshold for VAD (RMS of int16 samples)
VAD_SILENCE_THRESHOLD = 500
VAD_SILENCE_DURATION_S = 1.5
VAD_MIN_SPEECH_DURATION_S = 0.3


class AIBot:
    """AI interview bot — joins LiveKit room, asks questions on demand."""

    def __init__(self, interview_id: str, question_set: QuestionSet, livekit_url: str, token: str, *, wait_for_start: bool = True):
        self.interview_id = interview_id
        self.questions = question_set.questions
        self.livekit_url = livekit_url
        self.token = token
        self.room = rtc.Room()
        self.audio_source: rtc.AudioSource | None = None
        self.current_question_index = 0
        self.paused = False
        self.speaking = False
        self.finished = False
        self.errored = False
        self._running = False
        self._wait_for_start = wait_for_start
        self._stt_tasks: list[asyncio.Task] = []
        self._stt_identities: set[str] = set()
        self._next_event = asyncio.Event()

    async def _publish_data(self, payload: dict) -> None:
        """Publish a JSON data message via LiveKit data channel to all participants."""
        try:
            data = json.dumps(payload).encode("utf-8")
            await self.room.local_participant.publish_data(
                data,
                reliable=True,
                topic="interview",
            )
            log.info("AIBot: published data message type=%s", payload.get("type"))
        except Exception as e:
            log.warning("AIBot: failed to publish data message: %s", e)

    async def _publish_data_delayed(self, payload: dict, delay: float) -> None:
        """Publish a data message after a delay (fire-and-forget via ensure_future)."""
        await asyncio.sleep(delay)
        await self._publish_data(payload)

    async def connect(self) -> None:
        """Connect to LiveKit room and publish audio track."""
        self.room.on("track_subscribed")(self._on_track_subscribed)
        self.room.on("participant_disconnected")(self._on_participant_disconnected)

        await self.room.connect(
            self.livekit_url,
            self.token,
            options=rtc.RoomOptions(auto_subscribe=True),
        )

        self.audio_source = rtc.AudioSource(SAMPLE_RATE, NUM_CHANNELS)
        track = rtc.LocalAudioTrack.create_audio_track("suvera-ai-tts", self.audio_source)
        await self.room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

        self._running = True
        log.info("AIBot connected to room for interview=%s", self.interview_id)

    async def run(self) -> None:
        """Main loop — wait for start signal, then speak questions on demand."""
        if self._wait_for_start:
            # Wait for candidate to click "Start Interview"
            self._next_event.clear()
            await self._next_event.wait()
            if not self._running:
                return
        else:
            await asyncio.sleep(2)  # wait for reconnection to settle

        # Speak first/current question
        if self._running and self.current_question_index < len(self.questions):
            question = self.questions[self.current_question_index]
            await self._speak(question.question)
            log.info("AIBot: asked Q%d for interview=%s", self.current_question_index + 1, self.interview_id)

        # Now wait for explicit next_question signals for remaining questions
        while self._running and self.current_question_index < len(self.questions) - 1:
            # Wait until FE calls next_question
            self._next_event.clear()
            await self._next_event.wait()

            if not self._running:
                break

            if self.paused:
                continue

            self.current_question_index += 1
            question = self.questions[self.current_question_index]
            await self._speak(question.question)
            log.info("AIBot: asked Q%d for interview=%s", self.current_question_index + 1, self.interview_id)

        # Wait for final next_question signal (candidate clicks done on last question)
        if self._running and self.current_question_index == len(self.questions) - 1:
            self._next_event.clear()
            await self._next_event.wait()

        if self._running:
            await self._publish_data({"type": "caption_clear"})
            closing = (
                "That's a wrap on today's interview! "
                "I'll evaluate your responses and send a detailed report to your email shortly. "
                "Thank you for your time — all the best!"
            )
            await self._speak(closing, send_caption=False)
            # Wait for audio to fully play on the client before marking finished
            await asyncio.sleep(3.5)
            self.finished = True
            log.info("AIBot finished all questions for interview=%s", self.interview_id)

    def advance(self) -> dict:
        """Signal the bot to speak the next question. Called from service layer."""
        if self.speaking:
            return {"status": "busy", "message": "AI is still speaking"}
        if self.paused:
            return {"status": "paused", "message": "AI is paused by interviewer"}
        self._next_event.set()
        return {"status": "ok", "next_index": self.current_question_index + 1}

    async def _speak(self, text: str, *, send_caption: bool = True) -> None:
        """Generate TTS and publish audio frames to the room."""
        if not self.audio_source:
            return

        self.speaking = True
        try:
            await Transcript(
                interview_id=self.interview_id,
                role="ai",
                text=text,
            ).insert()

            tts = get_tts_client()
            pcm_bytes = await tts.synthesize(text, response_format="pcm")
            if not pcm_bytes:
                log.warning("AIBot: failed to generate TTS audio for interview=%s", self.interview_id)
                return

            # Schedule caption 1s after audio starts — gives audio a head start
            # so the caption appears while the participant is already hearing the question.
            # Expected points are NOT sent via data channel — the interviewer page
            # fetches them from the REST API (interview detail) and looks up by question index.
            if send_caption:
                asyncio.ensure_future(self._publish_data_delayed(
                    {
                        "type": "caption",
                        "question_index": self.current_question_index,
                        "text": text,
                    },
                    delay=1.0,
                ))

            frame_size = SAMPLES_PER_FRAME * NUM_CHANNELS * 2  # 2 bytes per int16 sample
            offset = 0
            while offset < len(pcm_bytes):
                chunk = pcm_bytes[offset:offset + frame_size]
                if len(chunk) < frame_size:
                    chunk = chunk + b'\x00' * (frame_size - len(chunk))

                frame = rtc.AudioFrame(
                    data=chunk,
                    sample_rate=SAMPLE_RATE,
                    num_channels=NUM_CHANNELS,
                    samples_per_channel=SAMPLES_PER_FRAME,
                )
                await self.audio_source.capture_frame(frame)
                offset += frame_size

            log.info("AIBot spoke: interview=%s, q_idx=%d, chars=%d", self.interview_id, self.current_question_index, len(text))
        except Exception as e:
            log.error("AIBot: speak failed for interview=%s: %s", self.interview_id, e)
        finally:
            self.speaking = False

    def _on_track_subscribed(self, track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
        """Handle subscribed audio track — start STT pipeline (one per participant)."""
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        if participant.identity in self._stt_identities:
            return

        self._stt_identities.add(participant.identity)
        role = "interviewer" if "interviewer" in participant.identity else "candidate"
        log.info("AIBot: subscribed to %s audio from %s", role, participant.identity)

        task = asyncio.ensure_future(self._stt_pipeline(track, participant, role))
        self._stt_tasks.append(task)

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        """Handle participant leaving — auto-resume AI if interviewer leaves while paused."""
        log.info("AIBot: participant left: %s", participant.identity)
        if "interviewer" in participant.identity and self.paused:
            self.paused = False
            log.info("AIBot: auto-resumed after interviewer left: interview=%s", self.interview_id)
            asyncio.ensure_future(self._clear_interviewer_state())

    async def _clear_interviewer_state(self) -> None:
        """Clear interviewer-related flags in DB after they leave."""
        try:
            from app.components.session.models import SessionLog
            session = await SessionLog.find_one(
                SessionLog.interview_id == self.interview_id,
                SessionLog.is_active == True,
            )
            if session:
                session.ai_paused = False
                session.interviewer_joined = False
                await session.save()
        except Exception as e:
            log.error("Failed to clear interviewer state: %s", e)

    async def _stt_pipeline(self, track: rtc.Track, participant: rtc.RemoteParticipant, role: str) -> None:
        """Receive audio frames, detect speech boundaries via VAD, transcribe."""
        audio_stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=NUM_CHANNELS)
        audio_buffer = bytearray()
        silence_frames = 0
        speech_frames = 0
        frames_per_second = SAMPLE_RATE // SAMPLES_PER_FRAME
        silence_threshold_frames = int(VAD_SILENCE_DURATION_S * frames_per_second)
        min_speech_frames = int(VAD_MIN_SPEECH_DURATION_S * frames_per_second)
        in_speech = False

        try:
            async for frame_event in audio_stream:
                if not self._running:
                    break

                frame = frame_event.frame
                pcm_data = bytes(frame.data)

                rms = _compute_rms(pcm_data)

                if rms > VAD_SILENCE_THRESHOLD:
                    in_speech = True
                    speech_frames += 1
                    silence_frames = 0
                    audio_buffer.extend(pcm_data)
                elif in_speech:
                    silence_frames += 1
                    audio_buffer.extend(pcm_data)

                    if silence_frames >= silence_threshold_frames and speech_frames >= min_speech_frames:
                        pcm_copy = bytes(audio_buffer)
                        audio_buffer.clear()
                        silence_frames = 0
                        speech_frames = 0
                        in_speech = False
                        asyncio.ensure_future(self._transcribe_and_save(pcm_copy, role, participant.identity))
                else:
                    audio_buffer.clear()
                    silence_frames = 0
                    speech_frames = 0
        except Exception as e:
            log.error("AIBot STT pipeline error for %s: %s", participant.identity, e)

    async def _transcribe_and_save(self, pcm_bytes: bytes, role: str, identity: str) -> None:
        """Transcribe PCM audio and save as Transcript doc."""
        try:
            wav_bytes = _pcm_to_wav(pcm_bytes, SAMPLE_RATE, NUM_CHANNELS)

            stt = get_stt_client()
            text = await stt.transcribe(wav_bytes, "utterance.wav")

            if not text or not text.strip():
                return

            await Transcript(
                interview_id=self.interview_id,
                role=role,
                text=text.strip(),
            ).insert()

            log.info("AIBot STT: interview=%s, role=%s, identity=%s, chars=%d", self.interview_id, role, identity, len(text))
        except Exception as e:
            log.error("AIBot transcription failed: interview=%s, identity=%s — %s", self.interview_id, identity, e)

    def pause(self) -> None:
        """Pause the AI bot."""
        self.paused = True
        asyncio.ensure_future(self._publish_data({"type": "ai_paused"}))
        log.info("AIBot paused: interview=%s", self.interview_id)

    def resume(self) -> None:
        """Resume the AI bot."""
        self.paused = False
        asyncio.ensure_future(self._publish_data({"type": "ai_resumed"}))
        log.info("AIBot resumed: interview=%s", self.interview_id)

    async def disconnect(self) -> None:
        """Disconnect from room and clean up."""
        self._running = False
        self._next_event.set()  # unblock if waiting

        for task in self._stt_tasks:
            task.cancel()
        self._stt_tasks.clear()

        await self.room.disconnect()
        log.info("AIBot disconnected: interview=%s", self.interview_id)


def _compute_rms(pcm_bytes: bytes) -> float:
    """Compute RMS energy of int16 PCM samples."""
    if len(pcm_bytes) < 2:
        return 0.0
    n_samples = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{n_samples}h", pcm_bytes[:n_samples * 2])
    if not samples:
        return 0.0
    sum_sq = sum(s * s for s in samples)
    return (sum_sq / n_samples) ** 0.5


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int, num_channels: int) -> bytes:
    """Wrap raw PCM int16 bytes in a WAV header."""
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


async def _decode_opus_to_pcm(opus_bytes: bytes) -> bytes | None:
    """Decode Opus audio to PCM int16 using ffmpeg (thread pool for Windows compat)."""
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _ffmpeg_decode_sync, opus_bytes)
        return result
    except FileNotFoundError:
        log.error("ffmpeg not found — required for Opus→PCM decoding")
        return None


def _ffmpeg_decode_sync(opus_bytes: bytes) -> bytes | None:
    """Synchronous ffmpeg decode — runs in thread pool."""
    import subprocess
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-i", "pipe:0",
                "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(NUM_CHANNELS),
                "pipe:1",
            ],
            input=opus_bytes,
            capture_output=True,
        )
        if proc.returncode != 0:
            log.error("ffmpeg decode failed: %s", proc.stderr.decode(errors="replace")[:200])
            return None
        return proc.stdout
    except FileNotFoundError:
        log.error("ffmpeg not found — required for Opus→PCM decoding")
        return None
