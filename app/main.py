"""
Main FastAPI Application for Real-Time AI Calling Agent.
Serves:
- Plivo Telephony Webhooks (/plivo/answer, /plivo/events)
- Real-Time Media Stream WebSocket (/ws/plivo)
- REST API for outbound calling & lead campaigns (/api/calls/dial, /api/leads)
- Interactive Marketing Agent Command Dashboard (/)
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, Request,
    Response, Depends, HTTPException, Query
)
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel

from app.config import settings
from app.db.database import init_db, get_db, AsyncSessionLocal
from app.db.models import Lead, CallLog, TranscriptMessage, Appointment
from app.services.plivo_service import plivo_service
from app.services.telnyx_service import telnyx_service
from app.services.exotel_service import exotel_service
from app.services.call_orchestrator import CallSessionOrchestrator, active_calls

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ai_calling_assistant")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables on startup
    await init_db()
    logger.info("Database initialized successfully.")
    logger.info(f"AI Calling Agent initialized for {settings.COMPANY_NAME} with persona '{settings.AGENT_NAME}'.")
    yield

app = FastAPI(
    title="AI Real-Time Calling Agent",
    description="Outbound marketing calling assistant powered by Plivo, Sarvam AI, and Gemini Flash",
    version="1.0.0",
    lifespan=lifespan
)

# Mount static files and templates
import os
base_dir = os.path.dirname(__file__)
static_path = os.path.join(base_dir, "static")
templates_path = os.path.join(base_dir, "templates")

os.makedirs(static_path, exist_ok=True)
os.makedirs(templates_path, exist_ok=True)
os.makedirs(os.path.join(static_path, "css"), exist_ok=True)
os.makedirs(os.path.join(static_path, "js"), exist_ok=True)

app.mount("/static", StaticFiles(directory=static_path), name="static")
templates = Jinja2Templates(directory=templates_path)

# Dashboard WebSocket subscribers
dashboard_clients: List[WebSocket] = []


# ---------------------------------------------------------------------
# PLIVO TELEPHONY WEBHOOKS & WEBSOCKET
# ---------------------------------------------------------------------

@app.post("/plivo/answer")
async def plivo_answer_webhook(request: Request, lead_id: Optional[int] = None):
    """
    Called by Plivo when an outbound or inbound call is answered.
    Returns Plivo XML with <Stream> element pointing to our WebSocket.
    """
    form_data = await request.form()
    call_uuid = form_data.get("CallUUID")
    from_number = form_data.get("From")
    to_number = form_data.get("To")

    logger.info(f"Plivo Answer Webhook: CallUUID={call_uuid}, From={from_number}, To={to_number}, LeadID={lead_id}")

    xml_response = plivo_service.generate_bidirectional_stream_xml(lead_id=lead_id)
    return Response(content=xml_response, media_type="application/xml")


@app.post("/plivo/events")
async def plivo_events_webhook(request: Request, lead_id: Optional[int] = None):
    """
    Receives call status updates from Plivo (ringing, answered, completed, busy, no-answer).
    """
    form_data = await request.form()
    call_uuid = form_data.get("CallUUID")
    call_status = form_data.get("CallStatus") or form_data.get("Event")
    duration = form_data.get("Duration", 0)

    logger.info(f"Plivo Event: CallUUID={call_uuid}, Status={call_status}, Duration={duration}")

    if call_uuid:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CallLog).where(CallLog.call_uuid == call_uuid)
            )
            call_log = result.scalars().first()
            if call_log:
                call_log.status = call_status or call_log.status
                if duration:
                    call_log.duration_seconds = int(duration)
                await session.commit()

    return PlainTextResponse("OK")


@app.websocket("/ws/plivo")
async def plivo_websocket_media_endpoint(
    websocket: WebSocket,
    lead_id: Optional[int] = Query(None)
):
    """
    Real-time bi-directional audio stream between Plivo telephony and the AI agent.
    """
    await websocket.accept()
    logger.info(f"Incoming Plivo WebSocket connection accepted. LeadID: {lead_id}")

    orchestrator = CallSessionOrchestrator(websocket=websocket, lead_id=lead_id)

    # Attach listener to broadcast live updates to dashboard
    queue = asyncio.Queue()
    orchestrator.subscribers.append(queue)

    async def broadcast_transcripts():
        while True:
            item = await queue.get()
            for client in list(dashboard_clients):
                try:
                    await client.send_json(item)
                except Exception:
                    if client in dashboard_clients:
                        dashboard_clients.remove(client)

    broadcast_task = asyncio.create_task(broadcast_transcripts())

    try:
        await orchestrator.run()
    finally:
        broadcast_task.cancel()


# ---------------------------------------------------------------------
# TELNYX TELEPHONY WEBHOOKS & WEBSOCKET
# ---------------------------------------------------------------------

@app.api_route("/telnyx/answer", methods=["GET", "POST"])
async def telnyx_answer_webhook(request: Request, lead_id: Optional[int] = None):
    """Called by Telnyx when an outbound call is answered. Returns TeXML <Stream>."""
    logger.info(f"Incoming Telnyx answer webhook: method={request.method}, url={request.url}")
    xml_response = telnyx_service.generate_texml_stream(lead_id=lead_id)
    return Response(content=xml_response, media_type="application/xml")


@app.api_route("/telnyx/events", methods=["GET", "POST"])
async def telnyx_events_webhook(request: Request):
    """Receives call status updates from Telnyx."""
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
            data = body.get("data", {})
            event_type = data.get("event_type") or body.get("event_type") or body.get("EventType")
            payload = data.get("payload", {})
            call_control_id = payload.get("call_control_id") or body.get("CallSid")
            logger.info(f"Telnyx Event: {event_type} (CallID: {call_control_id})")
        else:
            form = await request.form()
            logger.info(f"Telnyx Form Event: {dict(form)}")
    except Exception as e:
        logger.warning(f"Error parsing Telnyx event: {e}")
    return PlainTextResponse("OK")


@app.websocket("/ws/telnyx")
async def telnyx_websocket_media_endpoint(
    websocket: WebSocket,
    lead_id: Optional[int] = Query(None)
):
    """Real-time bi-directional audio stream between Telnyx and AI agent."""
    await websocket.accept()
    logger.info(f"Telnyx WebSocket connection accepted. LeadID: {lead_id}")

    orchestrator = CallSessionOrchestrator(websocket=websocket, lead_id=lead_id, protocol="telnyx")
    queue = asyncio.Queue()
    orchestrator.subscribers.append(queue)

    async def broadcast_transcripts():
        while True:
            item = await queue.get()
            for client in list(dashboard_clients):
                try:
                    await client.send_json(item)
                except Exception:
                    if client in dashboard_clients:
                        dashboard_clients.remove(client)

    broadcast_task = asyncio.create_task(broadcast_transcripts())
    try:
        await orchestrator.run()
    finally:
        broadcast_task.cancel()


# ---------------------------------------------------------------------
# EXOTEL TELEPHONY WEBHOOKS & WEBSOCKET (Voicebot / AgentStream)
# ---------------------------------------------------------------------

@app.api_route("/exotel/events", methods=["GET", "POST"])
async def exotel_events_webhook(request: Request):
    """
    Receives call status updates and terminal events from Exotel.
    """
    try:
        form = await request.form()
        call_sid = form.get("CallSid") or form.get("Sid")
        status = form.get("Status") or form.get("CallStatus") or form.get("EventType")
        duration = form.get("RecordingDuration") or form.get("Duration") or 0
        logger.info(f"Exotel Event: CallSid={call_sid}, Status={status}, Duration={duration}")

        if call_sid:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(CallLog).where(CallLog.call_uuid == call_sid)
                )
                call_log = result.scalars().first()
                if call_log:
                    call_log.status = status or call_log.status
                    if duration:
                        call_log.duration_seconds = int(duration)
                    await session.commit()
    except Exception as e:
        logger.warning(f"Error parsing Exotel event: {e}")
    return PlainTextResponse("OK")


@app.websocket("/ws/exotel")
async def exotel_websocket_media_endpoint(
    websocket: WebSocket,
    lead_id: Optional[int] = Query(None)
):
    """
    Real-time bi-directional audio stream between Exotel Voicebot/AgentStream
    and the AI calling agent.
    """
    await websocket.accept()
    logger.info(f"Exotel Voicebot WebSocket connection accepted. LeadID: {lead_id}")

    orchestrator = CallSessionOrchestrator(websocket=websocket, lead_id=lead_id, protocol="exotel")
    queue = asyncio.Queue()
    orchestrator.subscribers.append(queue)

    async def broadcast_transcripts():
        while True:
            item = await queue.get()
            for client in list(dashboard_clients):
                try:
                    await client.send_json(item)
                except Exception:
                    if client in dashboard_clients:
                        dashboard_clients.remove(client)

    broadcast_task = asyncio.create_task(broadcast_transcripts())
    try:
        await orchestrator.run()
    finally:
        broadcast_task.cancel()


# ---------------------------------------------------------------------
# BROWSER MICROPHONE & SPEAKER WEBSOCKET (100% Free Live Testing)
# ---------------------------------------------------------------------

@app.websocket("/ws/browser")
async def browser_audio_websocket(
    websocket: WebSocket,
    lead_name: Optional[str] = Query("Prospect"),
    company: Optional[str] = Query("Acme Corp")
):
    """
    Direct in-browser microphone and speaker streaming.
    Allows testing the full Sarvam STT <-> Gemini Flash <-> Sarvam TTS
    voice agent from your computer with zero phone carrier sign-up!
    """
    await websocket.accept()
    logger.info("Browser microphone session connected.")

    orchestrator = CallSessionOrchestrator(websocket=websocket, protocol="browser")
    orchestrator.lead_data = {
        "name": lead_name,
        "company": company,
        "phone": "In-Browser Microphone"
    }

    queue = asyncio.Queue()
    orchestrator.subscribers.append(queue)

    async def broadcast_transcripts():
        while True:
            item = await queue.get()
            for client in list(dashboard_clients):
                try:
                    await client.send_json(item)
                except Exception:
                    if client in dashboard_clients:
                        dashboard_clients.remove(client)

    broadcast_task = asyncio.create_task(broadcast_transcripts())
    try:
        await orchestrator.run()
    finally:
        broadcast_task.cancel()


# ---------------------------------------------------------------------
# REST API FOR CAMPAIGNS & CALL MANAGEMENT
# ---------------------------------------------------------------------

class DialRequest(BaseModel):
    phone_number: str
    name: Optional[str] = "Prospect"
    company: Optional[str] = None
    email: Optional[str] = None
    provider: Optional[str] = None  # "exotel", "telnyx", or "plivo"

@app.post("/api/calls/dial")
async def initiate_call(payload: DialRequest, db: AsyncSession = Depends(get_db)):
    """
    Triggers an outbound call to a prospect's phone number via Exotel, Telnyx, or Plivo.
    """
    # 1. Create or get lead
    result = await db.execute(
        select(Lead).where(Lead.phone_number == payload.phone_number)
    )
    lead = result.scalars().first()
    if not lead:
        lead = Lead(
            name=payload.name,
            phone_number=payload.phone_number,
            company=payload.company,
            email=payload.email,
            status="Pending"
        )
        db.add(lead)
        await db.commit()
        await db.refresh(lead)

    # Determine provider
    provider = (payload.provider or os.getenv("TELEPHONY_PROVIDER") or settings.TELEPHONY_PROVIDER or "exotel").lower()

    if provider == "exotel":
        call_result = await exotel_service.initiate_outbound_call(
            to_number=payload.phone_number,
            lead_id=lead.id
        )
    elif provider == "telnyx":
        call_result = await telnyx_service.initiate_outbound_call(
            to_number=payload.phone_number,
            lead_id=lead.id
        )
    else:
        call_result = await plivo_service.initiate_outbound_call(
            to_number=payload.phone_number,
            lead_id=lead.id
        )

    return {
        "status": "success",
        "provider": provider,
        "lead_id": lead.id,
        "phone_number": payload.phone_number,
        "call_response": call_result
    }


@app.get("/api/calls/logs")
async def get_call_logs(db: AsyncSession = Depends(get_db)):
    """Fetches recent call history with details and transcripts."""
    result = await db.execute(
        select(CallLog).order_by(desc(CallLog.created_at)).limit(50)
    )
    calls = result.scalars().all()

    output = []
    for c in calls:
        output.append({
            "id": c.id,
            "call_uuid": c.call_uuid,
            "phone_number": c.phone_number,
            "status": c.status,
            "duration": c.duration_seconds,
            "sentiment": c.sentiment,
            "qualification": c.qualification_status,
            "summary": c.summary,
            "created_at": c.created_at.strftime("%Y-%m-%d %H:%M:%S") if c.created_at else None
        })
    return output


@app.get("/api/calls/{call_id}/transcript")
async def get_call_transcript(call_id: int, db: AsyncSession = Depends(get_db)):
    """Fetches the full conversation transcript for a specific call."""
    result = await db.execute(
        select(TranscriptMessage)
        .where(TranscriptMessage.call_id == call_id)
        .order_by(TranscriptMessage.id)
    )
    messages = result.scalars().all()
    return [
        {
            "speaker": m.speaker,
            "text": m.text,
            "timestamp": m.timestamp.strftime("%H:%M:%S") if m.timestamp else None
        }
        for m in messages
    ]


@app.get("/api/leads")
async def list_leads(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Lead).order_by(desc(Lead.created_at)))
    leads = result.scalars().all()
    return [
        {
            "id": l.id,
            "name": l.name,
            "phone": l.phone_number,
            "company": l.company,
            "email": l.email,
            "status": l.status,
            "notes": l.notes
        }
        for l in leads
    ]


@app.post("/api/leads")
async def create_lead(lead: DialRequest, db: AsyncSession = Depends(get_db)):
    new_lead = Lead(
        name=lead.name,
        phone_number=lead.phone_number,
        company=lead.company,
        email=lead.email,
        status="Pending"
    )
    db.add(new_lead)
    await db.commit()
    await db.refresh(new_lead)
    return {"status": "created", "lead_id": new_lead.id}


@app.get("/api/appointments")
async def list_appointments(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Appointment).order_by(desc(Appointment.created_at)))
    appts = result.scalars().all()
    return [
        {
            "id": a.id,
            "customer_name": a.customer_name,
            "customer_phone": a.customer_phone,
            "customer_email": a.customer_email,
            "slot_time": a.slot_time,
            "notes": a.notes,
            "created_at": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else None
        }
        for a in appts
    ]


# ---------------------------------------------------------------------
# DASHBOARD WEBSOCKET & UI VIEWS
# ---------------------------------------------------------------------

@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    await websocket.accept()
    dashboard_clients.append(websocket)
    try:
        while True:
            # Keepalive ping
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in dashboard_clients:
            dashboard_clients.remove(websocket)


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Renders the AI Marketing Calling Assistant Operations Dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "agent_name": settings.AGENT_NAME,
            "company_name": settings.COMPANY_NAME,
            "product_name": settings.PRODUCT_NAME,
            "stt_engine": f"Sarvam AI ({settings.SARVAM_LANGUAGE_CODE})",
            "llm_engine": settings.GEMINI_MODEL,
            "tts_engine": f"Sarvam Bulbul ({settings.SARVAM_TTS_SPEAKER})",
            "telephony": "Telnyx / Plivo AudioStream",
            "public_url": os.getenv("PUBLIC_URL") or settings.PUBLIC_URL
        }
    )


@app.get("/health")
async def health_check():
    from dotenv import load_dotenv
    load_dotenv(override=True)

    exotel_ok = bool(
        (os.getenv("EXOTEL_API_KEY") or settings.EXOTEL_API_KEY) and
        (os.getenv("EXOTEL_API_TOKEN") or settings.EXOTEL_API_TOKEN) and
        (os.getenv("EXOTEL_ACCOUNT_SID") or settings.EXOTEL_ACCOUNT_SID)
    )
    telnyx_ok = bool(os.getenv("TELNYX_API_KEY") or settings.TELNYX_API_KEY)
    plivo_ok = bool(
        (os.getenv("PLIVO_AUTH_ID") or settings.PLIVO_AUTH_ID) and
        (os.getenv("PLIVO_AUTH_TOKEN") or settings.PLIVO_AUTH_TOKEN)
    )

    return {
        "status": "healthy",
        "active_calls_count": len(active_calls),
        "telephony_configured": exotel_ok or telnyx_ok or plivo_ok,
        "telephony_provider": os.getenv("TELEPHONY_PROVIDER") or settings.TELEPHONY_PROVIDER,
        "exotel_configured": exotel_ok,
        "telnyx_configured": telnyx_ok,
        "sarvam_configured": bool(os.getenv("SARVAM_API_KEY") or settings.SARVAM_API_KEY),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY") or settings.GEMINI_API_KEY)
    }
