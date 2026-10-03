"""
Voice Activity Detection (VAD) & Barge-in Tracker.
Tracks energy and pauses in the incoming callee audio stream to detect:
1. Speech start (Barge-in): Interrupts any active AI speech immediately.
2. Speech end (Silence / Turn completion): Triggers AI response generation.
"""

import time
from typing import Callable, Optional
from app.core.audio import calculate_audio_energy
from app.config import settings

class VoiceActivityDetector:
    def __init__(
        self,
        energy_threshold: int = settings.VAD_ENERGY_THRESHOLD,
        silence_duration_threshold: float = settings.VAD_SILENCE_THRESHOLD_SECONDS,
        on_speech_started: Optional[Callable[[], None]] = None,
        on_speech_ended: Optional[Callable[[], None]] = None,
    ):
        self.energy_threshold = energy_threshold
        self.silence_duration_threshold = silence_duration_threshold
        self.on_speech_started = on_speech_started
        self.on_speech_ended = on_speech_ended

        self.is_speaking = False
        self.last_speech_time = 0.0
        self.speech_start_time = 0.0

    def process_pcm16_chunk(self, pcm16_chunk: bytes) -> dict:
        """
        Processes a single PCM16 audio chunk (typically 20ms-100ms)
        Returns event dict if a state change occurred.
        """
        now = time.time()
        rms = calculate_audio_energy(pcm16_chunk)
        event = None

        if rms >= self.energy_threshold:
            # Voice detected
            self.last_speech_time = now
            if not self.is_speaking:
                self.is_speaking = True
                self.speech_start_time = now
                event = "speech_started"
                if self.on_speech_started:
                    self.on_speech_started()
        else:
            # Silence detected
            if self.is_speaking:
                silence_duration = now - self.last_speech_time
                if silence_duration >= self.silence_duration_threshold:
                    self.is_speaking = False
                    event = "speech_ended"
                    if self.on_speech_ended:
                        self.on_speech_ended()

        return {
            "rms": rms,
            "is_speaking": self.is_speaking,
            "event": event
        }

    def reset(self):
        """Resets the detector state."""
        self.is_speaking = False
        self.last_speech_time = 0.0
        self.speech_start_time = 0.0
