"""
Audio utilities for telephony transcoding.
Converts between Plivo's G.711 mu-law (8kHz) and Sarvam AI / Deepgram linear PCM (16kHz).
"""

import base64
import math
import struct
from typing import Optional

# Precomputed G.711 Mu-law decompression table (8-bit mu-law -> 16-bit linear PCM)
# Follows ITU-T G.711 recommendation
def _build_mulaw_to_pcm_table():
    table = []
    for i in range(256):
        byte = ~i & 0xFF
        sign = byte & 0x80
        exponent = (byte >> 4) & 0x07
        mantissa = byte & 0x0F
        sample = (mantissa << 3) + 0x84
        sample <<= exponent
        sample -= 0x84
        if sign == 0:
            sample = -sample
        table.append(sample)
    return table

MULAW_DECODE_TABLE = _build_mulaw_to_pcm_table()

# Precomputed Linear PCM to Mu-law table (clipped to 16-bit signed range)
def _pcm_sample_to_mulaw(sample: int) -> int:
    BIAS = 0x84
    CLIP = 32635
    sign = 0x80 if sample < 0 else 0x00
    if sample < 0:
        sample = -sample
    if sample > CLIP:
        sample = CLIP
    sample += BIAS
    
    exponent = 7
    for exp, mask in enumerate([0x4000, 0x2000, 0x1000, 0x0800, 0x0400, 0x0200, 0x0100]):
        if sample & mask:
            exponent = 7 - exp
            break
    else:
        exponent = 0

    mantissa = (sample >> (exponent + 3)) & 0x0F
    mulaw = ~(sign | (exponent << 4) | mantissa) & 0xFF
    return mulaw


def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    """Decodes 8-bit G.711 mu-law bytes to 16-bit linear PCM bytes."""
    samples = [MULAW_DECODE_TABLE[b] for b in mulaw_bytes]
    return struct.pack(f"<{len(samples)}h", *samples)


def pcm16_to_mulaw(pcm16_bytes: bytes) -> bytes:
    """Encodes 16-bit linear PCM bytes to 8-bit G.711 mu-law bytes."""
    num_samples = len(pcm16_bytes) // 2
    samples = struct.unpack(f"<{num_samples}h", pcm16_bytes)
    mulaw_bytes = bytes([_pcm_sample_to_mulaw(s) for s in samples])
    return mulaw_bytes


def resample_pcm16_8k_to_16k(pcm8k_bytes: bytes) -> bytes:
    """
    Upsamples 16-bit PCM from 8kHz to 16kHz using linear interpolation.
    Fast and sufficient for speech telephony.
    """
    num_samples = len(pcm8k_bytes) // 2
    if num_samples == 0:
        return b""
    
    samples = struct.unpack(f"<{num_samples}h", pcm8k_bytes)
    out_samples = []
    
    for i in range(num_samples - 1):
        s1 = samples[i]
        s2 = samples[i + 1]
        out_samples.append(s1)
        out_samples.append((s1 + s2) // 2)
    
    # Last sample duplicate
    out_samples.append(samples[-1])
    out_samples.append(samples[-1])
    
    return struct.pack(f"<{len(out_samples)}h", *out_samples)


def resample_pcm16_16k_to_8k(pcm16k_bytes: bytes) -> bytes:
    """
    Downsamples 16-bit PCM from 16kHz to 8kHz by taking alternate samples.
    """
    num_samples = len(pcm16k_bytes) // 2
    if num_samples == 0:
        return b""
    
    samples = struct.unpack(f"<{num_samples}h", pcm16k_bytes)
    # Subsample every second sample
    downsampled = samples[::2]
    return struct.pack(f"<{len(downsampled)}h", *downsampled)


def decode_plivo_media_payload(payload_b64: str) -> bytes:
    """
    Decodes base64 payload from Plivo (8kHz mu-law) to 16kHz linear PCM bytes for STT.
    """
    mulaw_bytes = base64.b64decode(payload_b64)
    pcm8k = mulaw_to_pcm16(mulaw_bytes)
    pcm16k = resample_pcm16_8k_to_16k(pcm8k)
    return pcm16k


def encode_plivo_media_payload(pcm16k_bytes: bytes) -> str:
    """
    Encodes 16kHz linear PCM bytes from TTS down to 8kHz mu-law and base64 encodes it for Plivo.
    """
    pcm8k = resample_pcm16_16k_to_8k(pcm16k_bytes)
    mulaw = pcm16_to_mulaw(pcm8k)
    return base64.b64encode(mulaw).decode("ascii")


def decode_exotel_media_payload(payload_b64: str) -> bytes:
    """
    Decodes base64 payload from Exotel (8kHz 16-bit PCM) to 16kHz linear PCM bytes for STT.
    """
    pcm8k = base64.b64decode(payload_b64)
    pcm16k = resample_pcm16_8k_to_16k(pcm8k)
    return pcm16k


def encode_exotel_media_payload_from_mulaw(mulaw_bytes: bytes) -> str:
    """
    Converts 8kHz mu-law bytes from Sarvam TTS to 8kHz 16-bit PCM base64 string for Exotel.
    """
    pcm8k = mulaw_to_pcm16(mulaw_bytes)
    return base64.b64encode(pcm8k).decode("ascii")


def calculate_audio_energy(pcm16_bytes: bytes) -> float:
    """Calculates RMS (Root Mean Square) energy of 16-bit linear PCM audio."""
    num_samples = len(pcm16_bytes) // 2
    if num_samples == 0:
        return 0.0
    samples = struct.unpack(f"<{num_samples}h", pcm16_bytes)
    sum_squares = sum(s * s for s in samples)
    rms = math.sqrt(sum_squares / num_samples)
    return rms
