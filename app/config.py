import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Server settings
    HOST: str = Field(default="0.0.0.0", env="HOST")
    PORT: int = Field(default=8000, env="PORT")
    PUBLIC_URL: str = Field(default="https://localhost:8000", env="PUBLIC_URL")

    # Plivo Telephony
    PLIVO_AUTH_ID: str = Field(default="", env="PLIVO_AUTH_ID")
    PLIVO_AUTH_TOKEN: str = Field(default="", env="PLIVO_AUTH_TOKEN")
    PLIVO_PHONE_NUMBER: str = Field(default="", env="PLIVO_PHONE_NUMBER")

    # Telnyx Telephony
    TELNYX_API_KEY: str = Field(default="", env="TELNYX_API_KEY")
    TELNYX_PHONE_NUMBER: str = Field(default="", env="TELNYX_PHONE_NUMBER")
    TELNYX_CONNECTION_ID: str = Field(default="", env="TELNYX_CONNECTION_ID")

    # Exotel Telephony (India Cloud Telephony - https://my.exotel.com/)
    EXOTEL_ACCOUNT_SID: str = Field(default="", env="EXOTEL_ACCOUNT_SID")
    EXOTEL_API_KEY: str = Field(default="", env="EXOTEL_API_KEY")
    EXOTEL_API_TOKEN: str = Field(default="", env="EXOTEL_API_TOKEN")
    EXOTEL_SUBDOMAIN: str = Field(default="api.exotel.com", env="EXOTEL_SUBDOMAIN")
    EXOTEL_CALLER_ID: str = Field(default="", env="EXOTEL_CALLER_ID")
    EXOTEL_APP_ID: str = Field(default="", env="EXOTEL_APP_ID")

    # Primary Telephony Provider: "exotel", "telnyx", "plivo", or "browser"
    TELEPHONY_PROVIDER: str = Field(default="exotel", env="TELEPHONY_PROVIDER")

    # Sarvam AI (STT & TTS)
    SARVAM_API_KEY: str = Field(default="", env="SARVAM_API_KEY")
    SARVAM_LANGUAGE_CODE: str = Field(default="en-IN", env="SARVAM_LANGUAGE_CODE")
    SARVAM_TTS_SPEAKER: str = Field(default="priya", env="SARVAM_TTS_SPEAKER")
    SARVAM_STT_MODEL: str = Field(default="saaras:v3", env="SARVAM_STT_MODEL")

    # Gemini LLM
    GEMINI_API_KEY: str = Field(default="", env="GEMINI_API_KEY")
    GEMINI_MODEL: str = Field(default="gemini-3.5-flash-lite", env="GEMINI_MODEL")

    # Marketing Persona
    AGENT_NAME: str = Field(default="Riya", env="AGENT_NAME")
    COMPANY_NAME: str = Field(default="ApexGrowth", env="COMPANY_NAME")
    PRODUCT_NAME: str = Field(default="AI Marketing Growth Platform", env="PRODUCT_NAME")
    CALL_OBJECTIVE: str = Field(
        default="Qualify the lead's current marketing pain points and book a 15-minute growth strategy demo.",
        env="CALL_OBJECTIVE"
    )

    # Audio & Telephony Pipeline Settings
    AUDIO_SAMPLE_RATE_TELEPHONY: int = 8000  # Plivo mu-law 8kHz
    AUDIO_SAMPLE_RATE_STT: int = 16000      # Sarvam/Deepgram STT 16kHz
    VAD_SILENCE_THRESHOLD_SECONDS: float = 0.45  # Seconds of silence to consider callee finished speaking
    VAD_ENERGY_THRESHOLD: int = 650         # RMS threshold for voice activity

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
