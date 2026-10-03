"""
Real-Time Call Orchestrator.
Manages the bidirectional audio loop between:
Plivo WebSocket <--> Sarvam STT <--> Gemini Flash <--> Sarvam TTS <--> Plivo WebSocket.
Implements sub-second latency, barge-in (interruption handling), and state tracking.
"""

import asyncio
import base64
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select, update

from app.config import settings
from app.core.audio import (
    decode_plivo_media_payload,
    encode_plivo_media_payload,
    decode_exotel_media_payload,
    mulaw_to_pcm16,
    calculate_audio_energy
)
from app.core.vad import VoiceActivityDetector
from app.services.sarvam_stt import sarvam_stt
from app.services.sarvam_tts import sarvam_tts
from app.services.gemini_agent import gemini_agent
from app.db.database import AsyncSessionLocal
from app.db.models import CallLog, Lead, TranscriptMessage

logger = logging.getLogger(__name__)

# Active active orchestrators registry for dashboard monitoring
active_calls: Dict[str, "CallSessionOrchestrator"] = {}

class CallSessionOrchestrator:
    def __init__(self, websocket: WebSocket, lead_id: Optional[int] = None, protocol: str = "exotel"):
        self.ws = websocket
        self.lead_id = lead_id
        self.protocol = protocol.lower()  # "exotel", "telnyx", "plivo", or "browser"
        self.call_uuid: Optional[str] = None
        self.stream_id: Optional[str] = None
        self.call_log_id: Optional[int] = None

        self.conversation_history: List[Dict[str, str]] = []
        self.lead_data: Dict[str, Any] = {}
        
        # Audio & pipeline states
        self.is_agent_speaking = False
        self.current_ai_task: Optional[asyncio.Task] = None
        self.stop_event = asyncio.Event()
        self.audio_in_buffer = bytearray()
        self.start_time = time.time()

        from dotenv import load_dotenv
        load_dotenv(override=True)
        energy_thresh = int(os.getenv("VAD_ENERGY_THRESHOLD") or settings.VAD_ENERGY_THRESHOLD)
        silence_thresh = float(os.getenv("VAD_SILENCE_THRESHOLD_SECONDS") or settings.VAD_SILENCE_THRESHOLD_SECONDS)

        # VAD for turn completion and barge-in
        self.vad = VoiceActivityDetector(
            energy_threshold=energy_thresh,
            silence_duration_threshold=silence_thresh,
            on_speech_started=self._handle_barge_in,
            on_speech_ended=self._handle_turn_completed
        )

        # Transcript listener callbacks for dashboard live-view
        self.subscribers: List[asyncio.Queue] = []

    async def initialize(self):
        """Loads lead data and creates initial call log."""
        async with AsyncSessionLocal() as session:
            lead = None
            if self.lead_id:
                result = await session.execute(select(Lead).where(Lead.id == self.lead_id))
                lead = result.scalars().first()
                if lead:
                    self.lead_data = {
                        "name": lead.name,
                        "company": lead.company or "Business",
                        "phone": lead.phone_number
                    }
                    lead.status = "In_Progress"

            call_log = CallLog(
                lead_id=self.lead_id,
                phone_number=self.lead_data.get("phone", "Incoming/Direct"),
                direction="outbound",
                status="in_progress",
                created_at=datetime.utcnow()
            )
            session.add(call_log)
            await session.commit()
            await session.refresh(call_log)
            self.call_log_id = call_log.id

    async def run(self):
        """Main event loop receiving Plivo WebSocket messages."""
        await self.initialize()

        try:
            # Send initial greeting
            asyncio.create_task(self._send_initial_greeting())

            while not self.stop_event.is_set():
                raw_data = await self.ws.receive_text()
                message = json.loads(raw_data)

                if self.protocol == "browser":
                    # Browser microphone client
                    msg_type = message.get("type") or message.get("event")
                    if msg_type == "audio":
                        b64_pcm = message.get("audio", "")
                        if b64_pcm:
                            raw_pcm = base64.b64decode(b64_pcm)
                            self.audio_in_buffer.extend(raw_pcm)
                            self.vad.process_pcm16_chunk(raw_pcm)
                    elif msg_type == "stop":
                        break
                else:
                    # Exotel, Telnyx, or Plivo telephony
                    event_type = message.get("event")

                    if event_type == "connected":
                        logger.info(f"{self.protocol.capitalize()} connected event received.")

                    elif event_type == "start":
                        start_data = message.get("start", {})
                        self.call_uuid = (
                            message.get("call_sid")
                            or start_data.get("call_sid")
                            or start_data.get("callId")
                            or start_data.get("call_control_id")
                            or start_data.get("callSid")
                        )
                        self.stream_id = (
                            message.get("stream_sid")
                            or start_data.get("stream_sid")
                            or start_data.get("streamId")
                            or start_data.get("stream_id")
                        )
                        logger.info(f"{self.protocol.capitalize()} Stream Started: CallUUID={self.call_uuid}, StreamID={self.stream_id}")
                        if self.call_uuid:
                            active_calls[self.call_uuid] = self
                            async with AsyncSessionLocal() as session:
                                await session.execute(
                                    update(CallLog)
                                    .where(CallLog.id == self.call_log_id)
                                    .values(call_uuid=self.call_uuid)
                                )
                                await session.commit()

                    elif event_type == "media":
                        media = message.get("media", {})
                        payload_b64 = media.get("payload")
                        if payload_b64:
                            if self.protocol == "exotel":
                                pcm16k = decode_exotel_media_payload(payload_b64)
                            else:
                                pcm16k = decode_plivo_media_payload(payload_b64)
                            self.audio_in_buffer.extend(pcm16k)
                            self.vad.process_pcm16_chunk(pcm16k)

                    elif event_type == "stop":
                        logger.info(f"{self.protocol.capitalize()} Stream Stop received.")
                        break

        except WebSocketDisconnect:
            logger.info(f"{self.protocol.capitalize()} WebSocket disconnected.")
        except Exception as e:
            logger.error(f"Error in orchestrator run loop: {e}")
        finally:
            await self.cleanup()

    def _handle_barge_in(self):
        """Callee interrupted the AI agent while AI was speaking."""
        if self.is_agent_speaking:
            logger.info("Barge-in detected! Halting AI playback immediately.")
            self.is_agent_speaking = False
            self.audio_in_buffer.clear()

            # Cancel active generation/synthesis task
            if self.current_ai_task and not self.current_ai_task.done():
                self.current_ai_task.cancel()

            # Tell Telephony/Browser to clear any buffered audio frames
            asyncio.create_task(self._send_clear_audio())

    def _handle_turn_completed(self):
        """Callee has stopped speaking. Trigger STT and LLM generation."""
        if self.is_agent_speaking:
            # Echo prevention: Ignore self-audio while agent is speaking
            self.audio_in_buffer.clear()
            return

        if len(self.audio_in_buffer) < 4800:  # Ignore tiny noise (< 150ms)
            self.audio_in_buffer.clear()
            return

        speech_pcm = bytes(self.audio_in_buffer)
        self.audio_in_buffer.clear()

        # Launch response task in background
        if self.current_ai_task and not self.current_ai_task.done():
            self.current_ai_task.cancel()
        self.current_ai_task = asyncio.create_task(self._process_callee_speech(speech_pcm))

    async def _send_clear_audio(self):
        """Sends clear command to flush audio playback buffer."""
        try:
            if self.protocol == "plivo":
                await self.ws.send_text(json.dumps({"event": "clearAudio"}))
            elif self.protocol == "telnyx":
                await self.ws.send_text(json.dumps({"event": "clear"}))
            elif self.protocol == "exotel":
                clear_msg = {"event": "clear"}
                if self.stream_id:
                    clear_msg["stream_sid"] = self.stream_id
                await self.ws.send_text(json.dumps(clear_msg))
            elif self.protocol == "browser":
                await self.ws.send_text(json.dumps({"type": "clear_audio"}))
        except Exception as e:
            logger.warning(f"Could not send clear audio: {e}")

    async def _send_initial_greeting(self):
        """Delivers the opening marketing hook when call connects."""
        lead_name = self.lead_data.get("name", "there")
        greeting_text = (
            f"Hello {lead_name}! This is {settings.AGENT_NAME} calling from {settings.COMPANY_NAME}. "
            f"Am I catching you at a good time?"
        )
        await self._speak_agent_text(greeting_text)

    async def _process_callee_speech(self, pcm_bytes: bytes):
        """Processes callee voice audio -> STT -> Gemini -> TTS -> Telephony."""
        try:
            # Step 1: STT
            transcript = await sarvam_stt.transcribe_audio_chunk_rest(pcm_bytes)
            if not transcript or not transcript.strip():
                return

            logger.info(f"Callee said: {transcript}")
            await self._record_transcript("callee", transcript)
            self.conversation_history.append({"role": "user", "content": transcript})

            # Step 2: Stream LLM + Stream TTS
            self.is_agent_speaking = True
            full_agent_reply = []

            async for sentence in gemini_agent.generate_response_stream(
                self.conversation_history,
                lead_context=self.lead_data
            ):
                if not self.is_agent_speaking:
                    # Cancelled by barge-in
                    break

                full_agent_reply.append(sentence)
                await self._synthesize_and_play_sentence(sentence)

            if full_agent_reply:
                complete_text = " ".join(full_agent_reply)
                await self._record_transcript("agent", complete_text)
                self.conversation_history.append({"role": "assistant", "content": complete_text})

            self.is_agent_speaking = False

        except asyncio.CancelledError:
            logger.info("Speech processing task was cancelled (barge-in).")
            self.is_agent_speaking = False
        except Exception as e:
            logger.error(f"Error processing callee speech: {e}")
            self.is_agent_speaking = False

    async def _speak_agent_text(self, text: str):
        """Helper to speak a direct sentence (e.g. greeting)."""
        self.is_agent_speaking = True
        await self._record_transcript("agent", text)
        self.conversation_history.append({"role": "assistant", "content": text})
        await self._synthesize_and_play_sentence(text)
        await asyncio.sleep(0.3)
        self.audio_in_buffer.clear()
        self.is_agent_speaking = False

    async def _synthesize_and_play_sentence(self, sentence: str):
        """Synthesizes a sentence and streams frames to WebSocket."""
        logger.info(f"Synthesizing sentence: {sentence}")
        mulaw_audio = await sarvam_tts.synthesize_sentence(sentence)
        if not mulaw_audio:
            return

        if self.protocol == "browser":
            # For browser, send audio chunk
            b64_audio = base64.b64encode(mulaw_audio).decode("ascii")
            await self.ws.send_text(json.dumps({
                "type": "audio",
                "format": "mulaw",
                "audio": b64_audio
            }))
            return

        async for b64_frame in sarvam_tts.stream_audio_frames(mulaw_audio):
            if not self.is_agent_speaking:
                # Interrupted
                break

            if self.protocol == "plivo":
                msg = {
                    "event": "playAudio",
                    "media": {
                        "payload": b64_frame,
                        "sampleRate": 8000
                    }
                }
            elif self.protocol == "telnyx":
                msg = {
                    "event": "media",
                    "media": {
                        "payload": b64_frame
                    }
                }
            elif self.protocol == "exotel":
                # Convert 8kHz mu-law frame to 8kHz 16-bit PCM for Exotel
                raw_mulaw = base64.b64decode(b64_frame)
                pcm8k = mulaw_to_pcm16(raw_mulaw)
                b64_pcm = base64.b64encode(pcm8k).decode("ascii")
                msg = {
                    "event": "media",
                    "stream_sid": self.stream_id or "",
                    "media": {
                        "payload": b64_pcm
                    }
                }
            await self.ws.send_text(json.dumps(msg))
            # 40ms frame delay for natural audio pacing
            await asyncio.sleep(0.038)

    async def _record_transcript(self, speaker: str, text: str):
        """Saves transcript message to DB and broadcasts to dashboard subscribers."""
        if not self.call_log_id:
            return

        async with AsyncSessionLocal() as session:
            msg = TranscriptMessage(
                call_id=self.call_log_id,
                speaker=speaker,
                text=text,
                timestamp=datetime.utcnow()
            )
            session.add(msg)
            await session.commit()

        # Broadcast to UI subscribers
        payload = {
            "type": "transcript",
            "call_id": self.call_log_id,
            "speaker": speaker,
            "text": text,
            "timestamp": datetime.utcnow().isoformat()
        }
        for sub in self.subscribers:
            await sub.put(payload)

    async def cleanup(self):
        """Finalizes call log duration, summary, and removes from active calls."""
        duration = int(time.time() - self.start_time)
        if self.call_uuid and self.call_uuid in active_calls:
            del active_calls[self.call_uuid]

        if self.call_log_id:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(CallLog)
                    .where(CallLog.id == self.call_log_id)
                    .values(
                        status="completed",
                        duration_seconds=duration,
                        ended_at=datetime.utcnow()
                    )
                )
                await session.commit()
        logger.info(f"Call session cleaned up. Total duration: {duration}s")
