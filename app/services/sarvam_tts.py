"""
Sarvam AI Text-to-Speech (TTS) Service using Bulbul engine.
Synthesizes natural conversational speech with Indian accents & Indic languages,
and formats audio frames for Plivo telephony streaming.
"""

import base64
import io
import json
import logging
import wave
from typing import AsyncGenerator, Optional, List
import httpx
from app.config import settings
from app.core.audio import pcm16_to_mulaw, resample_pcm16_16k_to_8k

logger = logging.getLogger(__name__)

class SarvamTTSClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        language_code: Optional[str] = None,
        speaker: Optional[str] = None
    ):
        self.api_key = api_key or settings.SARVAM_API_KEY
        self.language_code = language_code or settings.SARVAM_LANGUAGE_CODE
        self.speaker = speaker or settings.SARVAM_TTS_SPEAKER
        self.endpoint = "https://api.sarvam.ai/text-to-speech"

    async def synthesize_sentence(self, text: str) -> Optional[bytes]:
        """
        Synthesizes text into 8kHz G.711 mu-law audio bytes ready for Plivo.
        Returns the raw mu-law bytes.
        """
        clean_text = text.strip()
        if not clean_text:
            return None

        if not self.api_key:
            logger.warning("SARVAM_API_KEY is not configured.")
            return None

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json"
        }

        # Request 8kHz PCM/WAV directly from Sarvam Bulbul for optimal telephony latency
        payload = {
            "inputs": [clean_text],
            "target_language_code": self.language_code,
            "speaker": self.speaker,
            "pitch": 0,
            "pace": 1.05,
            "loudness": 1.2,
            "speech_sample_rate": 8000,
            "enable_preprocessing": True,
            "model": "bulbul:v3"
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.endpoint, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    audios = data.get("audios", [])
                    if audios:
                        audio_b64 = audios[0]
                        raw_audio = base64.b64decode(audio_b64)
                        
                        # Extract raw PCM from WAV if WAV header exists
                        pcm_8k = self._extract_pcm_from_wav(raw_audio)
                        
                        # Transcode 8kHz PCM to 8kHz mu-law
                        mulaw_bytes = pcm16_to_mulaw(pcm_8k)
                        return mulaw_bytes
                else:
                    logger.error(f"Sarvam TTS failed with {resp.status_code}: {resp.text}")
                    return None
        except Exception as e:
            logger.error(f"Exception during Sarvam TTS synthesis: {e}")
            return None

    def _extract_pcm_from_wav(self, audio_bytes: bytes) -> bytes:
        """Parses WAV audio container to extract raw PCM samples."""
        if audio_bytes.startswith(b"RIFF"):
            try:
                with io.BytesIO(audio_bytes) as bio:
                    with wave.open(bio, "rb") as wf:
                        return wf.readframes(wf.getnframes())
            except Exception as e:
                logger.warning(f"Could not parse WAV header, slicing 44-byte standard header: {e}")
                return audio_bytes[44:] if len(audio_bytes) > 44 else audio_bytes
        return audio_bytes

    async def stream_audio_frames(
        self,
        mulaw_bytes: bytes,
        frame_duration_ms: int = 40
    ) -> AsyncGenerator[str, None]:
        """
        Chunks raw 8kHz mu-law bytes into 40ms packets (320 bytes each)
        and yields base64 strings ready for Plivo 'playAudio' messages.
        """
        # At 8kHz 8-bit mono, 1 second = 8000 bytes. 40ms = 320 bytes.
        chunk_size = int(8000 * (frame_duration_ms / 1000.0))
        for i in range(0, len(mulaw_bytes), chunk_size):
            chunk = mulaw_bytes[i:i + chunk_size]
            b64_chunk = base64.b64encode(chunk).decode("ascii")
            yield b64_chunk

sarvam_tts = SarvamTTSClient()
