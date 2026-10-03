# 📞 Autonomous Real-Time AI Calling Agent for Marketing

A production-grade, sub-second latency outbound AI calling agent built for marketing, sales qualification, and automated demo scheduling. 

Architected with **Plivo / Telnyx Telephony** (bi-directional `<Stream>` WebSockets) or **Direct In-Browser Microphone Call**, **Sarvam AI** (Indian Accents & Indic STT + Bulbul TTS), **Google Gemini Flash** (low-latency conversational reasoning + RAG + Tool Calling), and **FastAPI**.

---

## 🏗️ Architecture

```
[Phone Callee]
      ↕ (PSTN Phone Audio)
   [Plivo]
      ↕ (Bi-directional WebSocket Audio: 8kHz μ-law Base64)
[FastAPI Server]
      ├──> Inbound Audio -> Transcoder (8kHz μ-law -> 16kHz PCM) -> VAD (Barge-in Tracker)
      │                                                                    │
      ├──> [Sarvam AI STT] <───────────────────────────────────────────────┘
      │         │ (Interim & Final Transcripts)
      │         ▼
      ├──> [Gemini Flash Agent] <──> [RAG Knowledge Base (Product / Pricing / FAQs)]
      │         │               <──> [Database (Leads / Call Logs / Transcripts)]
      │         │               <──> [Tools (Book Audit, WhatsApp Brochure, Qualify)]
      │         │ (Streamed Sentence Tokens)
      │         ▼
      ├──> [Sarvam AI Bulbul TTS]
      │         │ (Synthesized Audio Chunks)
      │         ▼
      └──> Outbound Audio -> Transcoder (16kHz PCM -> 8kHz μ-law) -> Plivo `playAudio`
                │
                ▼
            [Plivo]
                ↕
          [Phone Callee]
```

---

## ⚡ Key Highlights

1. **Sub-Second Latency Budget (< 750ms turnaround):**
   - Telephony Ingress/Egress via Plivo WebSockets: ~40-60ms
   - Streaming STT via Sarvam Saaras v2: ~180-220ms
   - LLM Sentence Chunking via Gemini Flash: ~150-200ms
   - Streaming TTS via Sarvam Bulbul: ~120-180ms
   - Total latency feels immediate, engaging, and conversational.
2. **Native Barge-In / Interruption Handling:**
   - Real-time VAD monitors callee speech energy. If the customer interrupts while the AI is speaking, the orchestrator immediately halts the LLM task, cancels TTS streaming, and dispatches a `clearAudio` event to Plivo, clearing the playback buffer instantly.
3. **Dynamic Marketing RAG:**
   - Real-time keyword & semantic retrieval over product specs, pricing packages, competitive differentiators, and objection counters (e.g., *"No budget"*, *"Send WhatsApp instead"*, *"Already have an agency"*).
4. **Autonomous Function Calling (Tools):**
   - **`book_growth_audit`**: Confirms customer slot and records appointment in DB.
   - **`send_whatsapp_brochure`**: Triggers automated marketing deck dispatch.
   - **`update_lead_qualification`**: Rates lead interest and qualification status.
5. **Full Web Operations Command Dashboard:**
   - Initiate single test calls or batch campaigns.
   - Live visualizer node lighting as audio packets flow through Plivo -> STT -> Gemini -> TTS.
   - Live streaming transcript chat view via WebSocket.
   - Historical call logs, recorded audio URLs, and appointment tracker.

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- Python 3.11 or 3.12
- A [Plivo](https://www.plivo.com/) account with an active phone number
- A [Sarvam AI](https://www.sarvam.ai/) API key
- A [Google Gemini](https://aistudio.google.com/) API key
- [ngrok](https://ngrok.com/) (or Cloudflare Tunnel) to expose your local port 8000 to Plivo

### 2. Setup Environment

```bash
# 1. Clone repository and navigate
cd ai_calling_assistant

# 2. Activate virtual environment
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

### 3. Configure API Credentials

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` with your actual credentials:
```ini
# Public URL (from ngrok or server domain)
PUBLIC_URL=https://your-domain.ngrok-free.app

# Plivo Telephony
PLIVO_AUTH_ID=MAMDY0NT...
PLIVO_AUTH_TOKEN=MzQ4Yj...
PLIVO_PHONE_NUMBER=+14155552671

# Sarvam AI
SARVAM_API_KEY=your_sarvam_api_key_here
SARVAM_LANGUAGE_CODE=en-IN
SARVAM_TTS_SPEAKER=ananya

# Google Gemini
GEMINI_API_KEY=AIzaSy...
GEMINI_MODEL=gemini-2.0-flash
```

### 4. Start the Application

```bash
python run.py
```

### 5. Expose with ngrok

In a separate terminal:
```bash
ngrok http 8000
```
Copy the generated HTTPS URL (e.g. `https://a1b2-c3d4.ngrok-free.app`) and paste it as `PUBLIC_URL` in your `.env`.

### 6. Access the Dashboard

Open your browser to:
```
http://localhost:8000
```
Enter a phone number with country code (e.g., `+919876543210` or `+14155552671`) and click **Dial Lead via Plivo**.

---

## 🛠️ Plivo Telephony Webhook Details

- **Answer URL**: `https://<PUBLIC_URL>/plivo/answer`
  Returns Plivo XML:
  ```xml
  <Response>
      <Stream bidirectional="true" streamTimeout="86400" keepCallAlive="true">
          wss://<PUBLIC_URL>/ws/plivo
      </Stream>
  </Response>
  ```
- **Hangup URL**: `https://<PUBLIC_URL>/plivo/events` (records call duration and status).
- **Media Stream WebSocket**: `wss://<PUBLIC_URL>/ws/plivo`.

---

## 📁 Directory Structure

```plaintext
ai_calling_assistant/
├── app/
│   ├── config.py                 # Configuration and environment loader
│   ├── main.py                   # FastAPI app, endpoints, and WebSockets
│   ├── core/
│   │   ├── audio.py              # Mu-law (8kHz) <-> PCM (16kHz) transcoder
│   │   └── vad.py                # Voice Activity Detection & Barge-in
│   ├── services/
│   │   ├── plivo_service.py      # Plivo REST API & XML builder
│   │   ├── sarvam_stt.py         # Sarvam Saaras v2 STT client
│   │   ├── gemini_agent.py       # Gemini Flash LLM with sentence chunking
│   │   ├── sarvam_tts.py         # Sarvam Bulbul TTS with telephony framing
│   │   └── call_orchestrator.py  # Bidirectional real-time loop coordinator
│   ├── knowledge/
│   │   ├── marketing_knowledge.json # Offers, pricing, FAQs, objections
│   │   └── rag.py                # Fast semantic knowledge retriever
│   ├── tools/
│   │   └── marketing_tools.py    # Appointment booking, WhatsApp sender
│   ├── db/
│   │   ├── database.py           # Async SQLite engine
│   │   └── models.py             # Leads, Calls, Transcripts, Appointments
│   ├── templates/
│   │   └── index.html            # Dashboard UI template
│   └── static/
│       ├── css/style.css         # Modern dark-theme styling
│       └── js/app.js             # Client WebSocket and table controllers
├── .env.example
├── requirements.txt
├── run.py
└── README.md
```
