"""
Entrypoint script to start the AI Real-Time Calling Agent server.
"""

import uvicorn
from app.config import settings

if __name__ == "__main__":
    print(f"🚀 Starting AI Calling Agent for {settings.COMPANY_NAME}...")
    print(f"📡 Telephony: Plivo AudioStream")
    print(f"👂 STT: Sarvam AI ({settings.SARVAM_LANGUAGE_CODE})")
    print(f"🧠 LLM: {settings.GEMINI_MODEL}")
    print(f"🗣️  TTS: Sarvam AI Bulbul ({settings.SARVAM_TTS_SPEAKER})")
    print(f"🌐 Public URL: {settings.PUBLIC_URL}")
    print(f"💻 Local Dashboard: http://localhost:{settings.PORT}")

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )
