"""
Telnyx Telephony Service.
Free trial alternative to Plivo ($10 free signup credit).
Handles outbound dialing and TeXML bi-directional Media Streams over WebSockets.
"""

import os
import httpx
import logging
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)

class TelnyxService:
    def __init__(self):
        self.api_key = os.getenv("TELNYX_API_KEY", "")
        self.from_number = os.getenv("TELNYX_PHONE_NUMBER", "")
        self.connection_id = os.getenv("TELNYX_CONNECTION_ID", "")
        self.base_url = "https://api.telnyx.com/v2"

    async def initiate_outbound_call(
        self,
        to_number: str,
        lead_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Triggers an outbound call via Telnyx REST API.
        When answered, Telnyx executes TeXML pointing to our WebSocket stream.
        """
        from dotenv import load_dotenv
        load_dotenv(override=True)

        api_key = os.getenv("TELNYX_API_KEY") or self.api_key
        from_number = os.getenv("TELNYX_PHONE_NUMBER") or self.from_number
        connection_id = os.getenv("TELNYX_CONNECTION_ID") or self.connection_id

        if not api_key:
            logger.warning("Telnyx API key not configured in .env.")
            return {
                "status": "error",
                "message": "TELNYX_API_KEY is not set in .env"
            }

        public_base = (os.getenv("PUBLIC_URL") or settings.PUBLIC_URL).rstrip("/")
        ws_base = public_base.replace("https://", "wss://").replace("http://", "ws://")
        stream_url = f"{ws_base}/ws/telnyx"
        if lead_id:
            stream_url += f"?lead_id={lead_id}"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        call_control_payload = {
            "to": to_number,
            "from": from_number,
            "connection_id": connection_id or None,
            "stream_url": stream_url,
            "stream_track": "both_tracks",
            "stream_bidirectional_mode": "rtp",
            "stream_bidirectional_codec": "PCMU"
        }
        call_control_payload = {k: v for k, v in call_control_payload.items() if v is not None}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/calls",
                    headers=headers,
                    json=call_control_payload
                )

                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

                if resp.status_code in [200, 201]:
                    call_data = data.get("data", {})
                    call_id = call_data.get("call_control_id") or "active"
                    # Check if Telnyx returned non-fatal warnings or soft errors
                    if "errors" in data and data["errors"]:
                        err_detail = data["errors"][0].get("detail", "")
                        logger.warning(f"Telnyx call initiated with notice: {err_detail}")
                        return {
                            "status": "error",
                            "message": err_detail,
                            "data": data
                        }
                    logger.info(f"Telnyx Call Control initiated: {call_id}")
                    return {
                        "status": "success",
                        "call_control_id": call_id,
                        "data": call_data
                    }
                else:
                    err_msg = resp.text
                    if "errors" in data and data["errors"]:
                        err_msg = data["errors"][0].get("detail") or str(data["errors"])
                    logger.error(f"Telnyx call failed: {resp.status_code} - {err_msg}")
                    return {
                        "status": "error",
                        "status_code": resp.status_code,
                        "error": err_msg,
                        "message": err_msg
                    }
        except Exception as e:
            logger.error(f"Exception during Telnyx call: {e}")
            return {"status": "error", "error": str(e), "message": str(e)}

    def generate_texml_stream(self, lead_id: Optional[int] = None) -> str:
        """
        Generates TeXML instructing Telnyx to stream bi-directional audio
        via WebSockets to our FastAPI server.
        """
        from dotenv import load_dotenv
        load_dotenv(override=True)
        public_url = (os.getenv("PUBLIC_URL") or settings.PUBLIC_URL).rstrip("/")
        if public_url.startswith("https://"):
            ws_url = "wss://" + public_url[len("https://"):]
        elif public_url.startswith("http://"):
            ws_url = "ws://" + public_url[len("http://"):]
        elif public_url.startswith("ws://") or public_url.startswith("wss://"):
            ws_url = public_url
        else:
            ws_url = f"wss://{public_url}"

        ws_endpoint = f"{ws_url}/ws/telnyx"
        if lead_id:
            ws_endpoint += f"?lead_id={lead_id}"

        texml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream 
        url="{ws_endpoint}" 
        track="both_tracks" 
        codec="PCMU"
        bidirectionalMode="rtp"
        bidirectionalCodec="PCMU"
        bidirectionalSamplingRate="8000"
    />
</Response>"""
        return texml.strip()

telnyx_service = TelnyxService()
