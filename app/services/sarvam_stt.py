"""
Sarvam AI Speech-to-Text (STT) Service.
Handles streaming audio transcription with support for Indian accents,
Hinglish, Hindi, and regional Indic languages.
"""

import asyncio
import io
import json
import logging
import os
import wave
from typing import AsyncGenerator, Callable, Optional, Dict, Any
import aiohttp
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

class SarvamSTTClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        language_code: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or settings.SARVAM_API_KEY
        self.language_code = language_code or settings.SARVAM_LANGUAGE_CODE
        self.model = model or settings.SARVAM_STT_MODEL
        self.sample_rate = settings.AUDIO_SAMPLE_RATE_STT
        self.ws_url = "wss://api.sarvam.ai/streaming/transcribe"
        self.rest_url = "https://api.sarvam.ai/speech-to-text"

    def _create_wav_header(self, pcm_data: bytes, sample_rate: int = 16000) -> bytes:
        """Wraps raw 16-bit PCM bytes with a standard WAV header."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return buffer.getvalue()

    async def transcribe_audio_chunk_rest(self, pcm16_bytes: bytes) -> Optional[str]:
        """
        Fast REST chunk transcription using Sarvam Saaras v2 model.
        Useful as fallback or for turn-based audio segments.
        """
        from dotenv import load_dotenv
        load_dotenv(override=True)

        api_key = os.getenv("SARVAM_API_KEY") or self.api_key
        model = os.getenv("SARVAM_STT_MODEL") or self.model or "saaras:v3"
        if model in ["saaras:v1", "saaras:v2"]:
            model = "saaras:v3"
        language_code = os.getenv("SARVAM_LANGUAGE_CODE") or self.language_code or "en-IN"

        if not api_key:
            logger.warning("SARVAM_API_KEY is not configured.")
            return None

        if len(pcm16_bytes) < 3200:  # Less than 100ms of 16kHz audio
            return None

        wav_bytes = self._create_wav_header(pcm16_bytes, self.sample_rate)
        headers = {
            "api-subscription-key": api_key
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                files = {
                    "file": ("speech.wav", wav_bytes, "audio/wav")
                }
                data = {
                    "model": model,
                    "language_code": language_code
                }
                resp = await client.post(
                    self.rest_url,
                    headers=headers,
                    files=files,
                    data=data
                )

                if resp.status_code == 200:
                    result = resp.json()
                    transcript = result.get("transcript", "").strip()
                    logger.info(f"Sarvam STT transcribed: {transcript}")
                    return transcript
                else:
                    logger.error(f"Sarvam STT failed: {resp.status_code} - {resp.text}")
                    return None
        except Exception as e:
            logger.error(f"Error in Sarvam STT REST call: {e}")
            return None

    async def start_streaming_session(
        self,
        on_transcript: Callable[[str, bool], None],
        stop_event: asyncio.Event
    ) -> asyncio.Queue:
        """
        Starts a streaming WebSocket session to Sarvam AI.
        Returns an asyncio.Queue where incoming 16kHz PCM audio bytes should be pushed.
        """
        audio_queue: asyncio.Queue = asyncio.Queue()

        async def worker():
            if not self.api_key:
                logger.warning("SARVAM_API_KEY not set for streaming STT.")
                return

            headers = {
                "api-subscription-key": self.api_key
            }
            ws_params = f"?language_code={self.language_code}&model={self.model}&sample_rate={self.sample_rate}"
            url = f"{self.ws_url}{ws_params}"

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url, headers=headers, timeout=10.0) as ws:
                        logger.info("Connected to Sarvam STT streaming WebSocket.")

                        async def sender():
                            while not stop_event.is_set():
                                try:
                                    chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.1)
                                    if chunk:
                                        await ws.send_bytes(chunk)
                                except asyncio.TimeoutError:
                                    continue
                                except Exception as err:
                                    logger.error(f"STT sender error: {err}")
                                    break

                        async def receiver():
                            async for msg in ws:
                                if stop_event.is_set():
                                    break
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    try:
                                        payload = json.loads(msg.data)
                                        # Parse Sarvam transcript response
                                        transcript = payload.get("transcript") or payload.get("text", "")
                                        is_final = payload.get("is_final", False)
                                        if transcript:
                                            on_transcript(transcript, is_final)
                                    except Exception as ex:
                                        logger.error(f"Failed to parse STT message: {ex}")
                                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                    logger.warning("STT WebSocket closed.")
                                    break

                        await asyncio.gather(sender(), receiver())
            except Exception as e:
                logger.warning(f"Sarvam STT WebSocket stream unavailable: {e}. Falling back to chunked processing.")

        asyncio.create_task(worker())
        return audio_queue

sarvam_stt = SarvamSTTClient()
